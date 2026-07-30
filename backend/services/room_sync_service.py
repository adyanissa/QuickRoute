"""
Automatic Room <-> RoutePoint synchronization.

Problem this solves: an admin adding a destination-capable RoutePoint
(type "room" or "store") via Add Route Point previously had no linked
Room at all — the end-user destination screen reads from the Rooms
collection (GET /api/rooms), never from RoutePoints directly — so the
admin had to separately open Add Room and re-type the same name/building/
floor to make that same physical spot actually show up as something a
user could navigate to. This module removes that duplicate entry.

It operates on the SAME two link fields that already existed before this
feature (see models/room_model.py / models/route_point_model.py):
  - Room.route_point_id        — the pre-existing, AUTHORITATIVE forward
                                  link end-user navigation resolves
                                  directly (see room_routes.py's own
                                  extensive comments on this).
  - RoutePoint.room_id         — the reverse pointer, pre-existing but
                                  previously only ever written by the
                                  OTHER direction (Room-first placement,
                                  room_routes.py's _place_room_on_map).

This module is the missing "RoutePoint-first" direction: given a
RoutePoint, create-or-reuse-or-update the Room it should map to, and keep
both sides of the link consistent.

Explicitly, deliberately OUT of scope here (never touched by anything in
this module): Dijkstra, RouteEdge, graph topology/connectivity, map
calibration, coordinates beyond the plain x/y a Room already stores,
authentication, or the navigation API response shape. This module only
ever reads/writes Room documents and the single `room_id` field on a
RoutePoint document.
"""

from __future__ import annotations

from datetime import datetime
from typing import Dict, NamedTuple, Optional

from beanie import PydanticObjectId

from constants.route_point_types import is_destination_capable_point_type
from models.room_model import Room
from models.route_point_model import RoutePoint
from schemas.localization_schema import merge_localized_text


class RoomSyncOutcome(NamedTuple):
    # One of: "created", "updated", "reused", "deactivated",
    # "skipped_non_destination", "skipped_ambiguous", "skipped_no_building".
    action: str
    room: Optional[Room]
    # Set only for the "skipped_ambiguous"/failure-adjacent cases — a
    # short, safe (never a raw exception/stack trace) human-readable
    # explanation an admin-facing UI can show directly.
    warning: Optional[str] = None


def _resolve_room_name_en(point: RoutePoint) -> str:
    """Same display-name priority every other admin-facing surface in this
    codebase already uses (see instruction_generator.py's
    resolve_display_name): an explicit admin-chosen display name first,
    then the raw point name. Never fabricated, never auto-translated."""
    return point.display_name_en or point.display_name or point.name


def _build_room_names(point: RoutePoint) -> Dict[str, str]:
    """Only includes a language key when the RoutePoint actually has a
    non-empty value for it — an absent key is what tells
    merge_localized_text() to leave that language's existing Room
    translation untouched, so this never blanks a manually-entered
    Arabic/Hebrew Room name just because the RoutePoint itself never had
    one set."""
    names: Dict[str, str] = {}
    if point.display_name_en:
        names["en"] = point.display_name_en
    if point.display_name_ar:
        names["ar"] = point.display_name_ar
    if point.display_name_he:
        names["he"] = point.display_name_he
    return names


async def _get_room_by_id(room_id: Optional[str]) -> Optional[Room]:
    if not room_id:
        return None
    try:
        return await Room.get(PydanticObjectId(room_id))
    except Exception:
        return None


async def resolve_linked_room(point: RoutePoint) -> RoomSyncOutcome:
    """
    The single, primary matching step (Section 5): "the primary match must
    use an existing direct Room-to-RoutePoint ID link... do not rely only
    on room name matching."

    Checks BOTH directions of the existing link fields and only ever
    trusts them when they agree:
      - point.room_id           -> the Room it (reverse-)points at.
      - Room.route_point_id     -> whichever Room's forward link points at
                                    this exact point.

    Returns action="reused" with the room when exactly one, mutually
    agreeing Room is found; action="skipped_ambiguous" (room=None) when
    the two directions disagree (a real data inconsistency — never merged
    silently); otherwise room=None with no warning (simply "no link yet",
    the normal case for a brand new point).
    """

    direct_room = await _get_room_by_id(point.room_id)
    forward_room = await Room.find_one(Room.route_point_id == str(point.id))

    if direct_room and forward_room:
        if str(direct_room.id) == str(forward_room.id):
            return RoomSyncOutcome("reused", direct_room)
        return RoomSyncOutcome(
            "skipped_ambiguous",
            None,
            (
                f"RoutePoint {point.id} has conflicting Room links: "
                f"room_id points to {direct_room.id}, but Room "
                f"{forward_room.id} also links back to this point. "
                "Skipped rather than merging incorrectly."
            ),
        )

    if direct_room:
        return RoomSyncOutcome("reused", direct_room)

    if forward_room:
        return RoomSyncOutcome("reused", forward_room)

    return RoomSyncOutcome("reused", None)


def _normalize_name(value: Optional[str]) -> str:
    return (value or "").strip().lower()


async def find_legacy_unlinked_match(point: RoutePoint) -> RoomSyncOutcome:
    """
    Conservative fallback matching (Section 5) for a legacy Room that was
    created via the old manual-only Add Room flow — no route_point_id at
    all — that nonetheless clearly corresponds to this same physical
    point. Only ever used by the bulk sync action, never by the normal
    create/update path (which should never silently "adopt" an unrelated
    pre-existing Room just because a RoutePoint with a similar name was
    saved).

    Matches only when building + normalized name agree, AND map/floor
    either agree or are unset on the legacy Room (a manual-entry Room
    often never had a map/floor at all). If more than one candidate
    matches, this is genuinely ambiguous — skipped and reported, never
    guessed.
    """

    candidate_name = _normalize_name(_resolve_room_name_en(point))

    if not point.building_id or not candidate_name:
        return RoomSyncOutcome("skipped_ambiguous", None, None)

    candidates = await Room.find(
        {"building_id": point.building_id, "route_point_id": None}
    ).to_list()

    matches = [
        room
        for room in candidates
        if _normalize_name(room.name_en) == candidate_name
        and (room.map_id is None or room.map_id == point.map_id)
        and (room.floor is None or room.floor == point.floor)
    ]

    if len(matches) == 1:
        return RoomSyncOutcome("reused", matches[0])

    if len(matches) > 1:
        return RoomSyncOutcome(
            "skipped_ambiguous",
            None,
            (
                f"RoutePoint {point.id} (\"{point.name}\") matches "
                f"{len(matches)} unlinked legacy Rooms by name/building — "
                "skipped rather than guessing which one to link."
            ),
        )

    return RoomSyncOutcome("reused", None)


def _apply_owned_fields(room: Room, point: RoutePoint) -> bool:
    """Writes only the fields the RoutePoint side legitimately owns
    (Section 3: "preserve existing Room fields not owned by the
    RoutePoint" — description/category/room_type/room_number/semantic_*
    links are NEVER touched here). Returns True if anything actually
    changed."""

    changed = False

    name_en = _resolve_room_name_en(point)
    if name_en and room.name_en != name_en:
        room.name_en = name_en
        changed = True

    new_names = _build_room_names(point)
    if new_names:
        merged = merge_localized_text(room.names, new_names)
        if merged != (room.names or {}):
            room.names = merged
            changed = True

    if room.building_id != point.building_id and point.building_id:
        room.building_id = point.building_id
        changed = True

    if room.map_id != point.map_id:
        room.map_id = point.map_id
        changed = True

    if room.floor != point.floor:
        room.floor = point.floor
        changed = True

    if room.x != point.x or room.y != point.y:
        room.x = point.x
        room.y = point.y
        changed = True

    if room.route_point_id != str(point.id):
        room.route_point_id = str(point.id)
        changed = True

    # Section 3: "When a destination RoutePoint is deactivated, make the
    # linked Room unavailable... using the project's existing active/
    # published behaviour" — Room.is_active is exactly that existing
    # behaviour (DestinationSelectionScreen.jsx filters it out of the list
    # entirely). is_active is therefore an owned field too, kept in sync
    # in both directions (deactivate AND reactivate).
    if room.is_active != point.is_active:
        room.is_active = point.is_active
        changed = True

    return changed


async def sync_room_for_route_point(
    point: RoutePoint,
    *,
    allow_legacy_fallback: bool = False,
) -> RoomSyncOutcome:
    """
    The main entry point (Section 2/3). Idempotent: calling this again for
    a point that already has a correctly-linked Room only ever updates
    that same Room in place — it never creates a second one.

    `allow_legacy_fallback` is only ever set True by the bulk "Sync Rooms
    from Route Points" action (Section 4/5) — the normal single-point
    create/update path never guesses at a pre-existing unlinked Room by
    name, only the deliberate, admin-confirmed bulk action does.
    """

    if not is_destination_capable_point_type(point.point_type):
        # Not a destination-capable type. If it *used* to be one and still
        # has a linked Room (e.g. an admin changed its type away from
        # "room"), that Room is no longer a legitimate mapped destination
        # — deactivate it rather than leaving a stale, now-orphaned-in-
        # spirit destination selectable. Never deletes it (Section 3:
        # avoid destructive cascading; an admin may still want the Room's
        # own data).
        existing = await resolve_linked_room(point)
        if existing.room and existing.room.is_active:
            existing.room.is_active = False
            existing.room.updated_at = datetime.utcnow()
            await existing.room.save()
            return RoomSyncOutcome("deactivated", existing.room)
        return RoomSyncOutcome("skipped_non_destination", None)

    if not point.building_id:
        return RoomSyncOutcome(
            "skipped_no_building",
            None,
            (
                f"RoutePoint {point.id} (\"{point.name}\") has no "
                "building_id — cannot create a Room without one."
            ),
        )

    match = await resolve_linked_room(point)

    if match.action == "skipped_ambiguous":
        return match

    room = match.room

    if not room and allow_legacy_fallback:
        legacy_match = await find_legacy_unlinked_match(point)
        if legacy_match.action == "skipped_ambiguous" and legacy_match.warning:
            return legacy_match
        room = legacy_match.room

    if room:
        changed = _apply_owned_fields(room, point)

        if changed:
            room.updated_at = datetime.utcnow()
            await room.save()

        if point.room_id != str(room.id):
            point.room_id = str(room.id)
            point.updated_at = datetime.utcnow()
            await point.save()

        return RoomSyncOutcome("updated" if changed else "reused", room)

    # No existing linked Room anywhere — create one.
    new_room = Room(
        building_id=point.building_id,
        name_en=_resolve_room_name_en(point),
        names=_build_room_names(point) or None,
        map_id=point.map_id,
        x=point.x,
        y=point.y,
        floor=point.floor,
        route_point_id=str(point.id),
        is_active=point.is_active,
    )
    await new_room.insert()

    point.room_id = str(new_room.id)
    point.updated_at = datetime.utcnow()
    await point.save()

    return RoomSyncOutcome("created", new_room)


async def deactivate_linked_room_for_deleted_point(point: RoutePoint) -> Optional[Room]:
    """
    Called just before a RoutePoint is actually deleted (Section 3: "do
    not leave a selectable Room pointing to a deleted RoutePoint; avoid
    destructive cascading"). Soft-deactivates the linked Room, if any —
    never deletes it, so the admin's Room data/manually-added description
    etc. is never lost, but it immediately stops appearing in the
    end-user destination list. Returns the deactivated Room, or None if
    there was nothing linked.
    """

    match = await resolve_linked_room(point)

    if not match.room or not match.room.is_active:
        return None

    match.room.is_active = False
    match.room.updated_at = datetime.utcnow()
    await match.room.save()
    return match.room
