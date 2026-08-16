"""
"Every accepted navigable room gets its own QR" — the one place that turns a
navigable Room into exactly one active LocationCode.

WHY THIS IS ITS OWN MODULE
--------------------------
A room only becomes *navigable* in two steps, in two different services:

  Stage 1  services/semantic_destination_service.apply_semantic_destinations
           -> Room + arrival RoutePoint (deliberately no RouteEdge)
  Stage 2  services/auto_connect_destinations_service.apply_auto_connect_
           destinations  -> the RouteEdge(s) that join that arrival point to
           the corridor graph

Issuing the QR in Stage 1 alone would hand a code to rooms that are not
reachable yet. Issuing it in Stage 2 alone would miss a room whose arrival
point was already connected (a reused point, or a re-apply). So both stages
call THIS function, and this function alone decides. It is fully idempotent,
so being called from two places — or twice from the same place — is safe by
construction.

WHAT "NAVIGABLE" MEANS HERE
---------------------------
Exactly the test this codebase already uses for a placed destination
(routes/room_routes.py's _place_room_on_map, and the connector analogue
services/vertical_connector_service.is_stop_connected_to_floor_graph):

    the Room has a route_point_id, that RoutePoint is active, and at least
    one ACTIVE RouteEdge on the same map touches it.

A room that fails either half is reported for review and gets NO code. This
module never creates a RouteEdge, never moves or invents a coordinate, and
never relaxes the wall check — an unconnected room is a review item, never a
reason to fabricate a connection.

ARCHITECTURE
------------
    Room  <->  arrival RoutePoint  <->  LocationCode / QR
                       |
                       +-- RouteEdges -- corridor graph -- Dijkstra

A LocationCode points at a RoutePoint, never at another LocationCode, and
the graph is never traversed through codes. The QR is only an identifier for
"where the user physically is".

The room identity behind a scanned code is derived at read time from
RoutePoint.room_id (already exposed by GET /api/route-points/public/{id}),
so LocationCode itself needs no room_id field and no migration.
"""

from __future__ import annotations

import secrets
from typing import Any, Dict, List, Optional

from beanie import PydanticObjectId

from models.location_code_model import LocationCode
from models.room_model import Room
from models.route_edge_model import RouteEdge
from models.route_point_model import RoutePoint


# 8 unambiguous uppercase alphanumeric characters (no 0/O/1/I) — short
# enough to type from a printed label, long enough that collisions are rare
# even before the uniqueness retry loop. Lifted verbatim out of
# routes/location_code_routes.py so the manual "Generate code" button and
# the automatic room-QR path can never drift into two different formats;
# that route now imports this function instead of keeping its own copy.
LOCATION_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
LOCATION_CODE_LENGTH = 8

# How many times to re-roll on a code collision before giving up. Same value
# the manual generate endpoint has always used.
MAX_CODE_GENERATION_ATTEMPTS = 10


def generate_location_code_candidate() -> str:
    return "".join(
        secrets.choice(LOCATION_CODE_ALPHABET) for _ in range(LOCATION_CODE_LENGTH)
    )


async def route_point_is_connected_to_graph(point: RoutePoint) -> bool:
    """
    True when this RoutePoint has at least one ACTIVE RouteEdge on its own
    map touching it — the same "is this destination actually reachable"
    test routes/room_routes.py:_place_room_on_map already applies right
    after placing a room.

    Deliberately does NOT count a cross-floor transition edge whose map_id
    belongs to the other floor: a destination must be joined to its OWN
    floor's corridor graph to be walkable to.
    """

    edge = await RouteEdge.find_one(
        {
            "map_id": point.map_id,
            "is_active": True,
            "$or": [
                {"from_point_id": str(point.id)},
                {"to_point_id": str(point.id)},
            ],
        }
    )
    return edge is not None


async def find_active_location_code_for_point(
    route_point_id: str,
) -> Optional[LocationCode]:
    """
    The MVP invariant is ONE active code per room. Because a Room's arrival
    RoutePoint is its identity for navigation, "a code for this room" means
    "an active code pointing at this room's arrival RoutePoint".

    A code an admin created by hand for the same point counts and is reused
    — this never mints a second code alongside one that already works, and
    never deactivates or rewrites an admin's own code.
    """

    return await LocationCode.find_one(
        {"route_point_id": route_point_id, "is_active": True}
    )


def _empty_summary() -> Dict[str, Any]:
    return {
        "rooms_scanned": 0,
        "qr_codes_created": 0,
        "qr_codes_reused": 0,
        "rooms_unplaced": 0,
        "rooms_unconnected": 0,
        "rooms_needing_review": [],
        "created_location_code_ids": [],
        "warnings": [],
    }


async def ensure_room_location_codes(map_id: str) -> Dict[str, Any]:
    """
    Idempotently guarantee exactly one active LocationCode for every
    navigable Room on `map_id`, and report every room that could not become
    navigable instead of forcing one through.

    Scope is the whole map on purpose: an apply run should leave the map in
    a consistent state, not just the handful of rooms that run happened to
    touch. Re-running it is a no-op apart from picking up rooms that have
    become navigable since.

    Returns (all counts are for THIS call):

        rooms_scanned              active rooms considered on this map
        qr_codes_created           new codes minted
        qr_codes_reused            rooms that already had an active code
        rooms_unplaced             no arrival RoutePoint yet (admin must
                                   place them; semantic analysis has no
                                   coordinates to place them from)
        rooms_unconnected          arrival point exists but has no active
                                   RouteEdge on its own map — NOT navigable,
                                   deliberately no code
        rooms_needing_review       [{room_id, name, reason}] for the two
                                   cases above, so the admin UI can name
                                   them rather than just count them
        created_location_code_ids  ids of codes minted by this call
        warnings                   non-fatal per-room problems

    Never raises for a single bad room — one unplaceable room must never
    abort the rest of an apply.
    """

    summary = _empty_summary()

    rooms = await Room.find({"map_id": map_id, "is_active": True}).to_list()
    summary["rooms_scanned"] = len(rooms)

    for room in rooms:
        room_label = room.name_en or str(room.id)

        try:
            if not room.route_point_id:
                summary["rooms_unplaced"] += 1
                summary["rooms_needing_review"].append(
                    {
                        "room_id": str(room.id),
                        "name": room_label,
                        "reason": "no_arrival_point",
                    }
                )
                continue

            try:
                point = await RoutePoint.get(PydanticObjectId(room.route_point_id))
            except Exception:  # noqa: BLE001 - malformed id is a data problem
                point = None

            if point is None or not point.is_active:
                summary["rooms_unplaced"] += 1
                summary["rooms_needing_review"].append(
                    {
                        "room_id": str(room.id),
                        "name": room_label,
                        "reason": "arrival_point_missing_or_inactive",
                    }
                )
                continue

            if not await route_point_is_connected_to_graph(point):
                summary["rooms_unconnected"] += 1
                summary["rooms_needing_review"].append(
                    {
                        "room_id": str(room.id),
                        "name": room_label,
                        "reason": "not_connected_to_graph",
                    }
                )
                continue

            existing = await find_active_location_code_for_point(str(point.id))
            if existing is not None:
                summary["qr_codes_reused"] += 1
                continue

            if not point.building_id:
                # Same refusal the manual generate endpoint makes: a code
                # must carry a real building, and the resolver relies on it.
                summary["warnings"].append(
                    f"Room '{room_label}' has an arrival point with no "
                    "building_id — its map must be associated with a "
                    "building before a QR code can be issued."
                )
                summary["rooms_needing_review"].append(
                    {
                        "room_id": str(room.id),
                        "name": room_label,
                        "reason": "arrival_point_has_no_building",
                    }
                )
                continue

            created = await _mint_code_for_point(point, label=room_label)

            if created is None:
                summary["warnings"].append(
                    f"Could not generate a unique location code for room "
                    f"'{room_label}' — try applying again."
                )
                continue

            summary["qr_codes_created"] += 1
            summary["created_location_code_ids"].append(str(created.id))

        except Exception as error:  # noqa: BLE001 - one room never aborts the run
            summary["warnings"].append(
                f"Could not ensure a QR code for room '{room_label}': {error}"
            )

    return summary


async def _mint_code_for_point(
    point: RoutePoint, *, label: Optional[str]
) -> Optional[LocationCode]:
    """
    Creates one LocationCode for `point`, retrying on code collision.
    Mirrors POST /api/location-codes/generate exactly — same alphabet, same
    retry count, same field derivation (building/map come from the point
    itself, never from a caller) — so an automatically issued room QR is
    indistinguishable from one an admin generated by hand.
    """

    for _attempt in range(MAX_CODE_GENERATION_ATTEMPTS):
        candidate = generate_location_code_candidate()

        if await LocationCode.find_one(LocationCode.code == candidate):
            continue

        entry = LocationCode(
            code=candidate,
            building_id=point.building_id,
            map_id=point.map_id,
            route_point_id=str(point.id),
            label=label or point.name,
            is_active=True,
        )
        await entry.insert()
        return entry

    return None


# Keys this module contributes to a caller's existing apply-result dict.
# Kept as an explicit list so the two callers merge exactly the same set and
# their response schemas cannot drift apart.
MERGEABLE_SUMMARY_KEYS = (
    "qr_codes_created",
    "qr_codes_reused",
    "rooms_unplaced",
    "rooms_unconnected",
    "rooms_needing_review",
)


def merge_into_apply_result(
    result: Dict[str, Any], qr_summary: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Folds this module's counters into an existing apply-result dict without
    disturbing any key the caller already owns, and forwards QR warnings
    into the caller's own `warnings` list so the admin sees one list.
    """

    for key in MERGEABLE_SUMMARY_KEYS:
        result[key] = qr_summary.get(key, 0 if key != "rooms_needing_review" else [])

    qr_warnings: List[str] = qr_summary.get("warnings") or []
    if qr_warnings:
        result.setdefault("warnings", []).extend(qr_warnings)

    return result
