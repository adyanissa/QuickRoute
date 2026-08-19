import logging
from datetime import datetime
from typing import Dict, List, Optional, Set, Tuple

from beanie import PydanticObjectId
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from core.auth_deps import (
    get_current_user,
    get_current_user_optional,
    user_can_manage_building,
    user_can_access_building,
    user_can_access_map,
    get_accessible_building_ids,
)
from core.errors import FORBIDDEN_MAP_SCOPE
from core.errors import FORBIDDEN_BUILDING_SCOPE, FORBIDDEN_ROLE
from models.room_model import Room
from models.building_model import Building
from models.map_model import Map
from models.route_edge_model import RouteEdge
from models.route_point_model import RoutePoint
from models.user_model import User

from schemas.room_schema import (
    RoomCreate,
    RoomUpdate,
    RoomResponse,
    RoomSyncRequest,
    RoomSyncResponse,
)
from constants.destination_types import (
    ALL_ACCEPTED_DESTINATION_TYPES,
    is_accepted_destination_type,
)
from constants.route_point_types import DESTINATION_CAPABLE_POINT_TYPES
from services.point_dedup_service import find_or_create_route_point
from services.destination_attachment_service import attach_point_safely
from services.graph_connectivity_service import room_connection_state
from services.room_sync_service import sync_room_for_route_point
from schemas.localization_schema import localized_text_to_dict, merge_localized_text


logger = logging.getLogger(__name__)


router = APIRouter(
    prefix="/api/rooms",
    tags=["Rooms & Destinations"]
)


async def resolve_room_map_group_id(map_id: Optional[str]) -> Optional[str]:
    """
    A Room never stores map_group_id itself — it is resolved from
    Map(map_id).map_group_id at response time, exactly like
    MapResponse.map_group_code (see map_routes.resolve_map_group_code),
    so there is never a second, independently-drifting copy of "which
    group is this destination's floor in".
    """

    if not map_id:
        return None

    try:
        map_item = await Map.get(PydanticObjectId(map_id))
    except Exception:
        return None

    return map_item.map_group_id if map_item else None


async def compute_room_navigability(room: Room) -> Tuple[bool, Optional[str]]:
    """
    The single, live source of truth for whether a normal user can
    navigate to this destination right now.

    The rule itself now lives in services/graph_connectivity_service so
    that this endpoint, the QR issuer and Auto Connect cannot disagree —
    they previously did, on real data: Auto Connect reported a room as
    already connected while this function reported the same room as
    disconnected. See that module's docstring for the three definitions
    that had drifted apart and what replaced them.

    Reasons are unchanged for every case that could occur before:
      1. missing_route_point
      2. route_point_not_found
      3. inactive_route_point
      4. inactive_destination
      5. disconnected_from_graph

    One reason is NEW: only_invalid_edges, for a room whose arrival point
    has edges but none of them reaches the walkable graph legitimately —
    in practice a stale Room-to-Room edge from before the Auto Connect
    correction. That case used to be reported as fully navigable, which is
    exactly the bug: the room looked routable and was not.
    """

    return await room_connection_state(room)


def _room_static_response_fields(room: Room) -> dict:
    """
    Every RoomResponse field that comes straight off the Room document,
    with no database access at all.

    Extracted so the single-room path (room_to_response below) and the
    batched list path (build_room_list_responses further down) map the
    document to the response through ONE piece of code. They cannot drift
    into two subtly different response shapes, which is the only real risk
    in having a second enrichment path.
    """

    return dict(
        id=str(room.id),
        building_id=room.building_id,
        name_en=room.name_en,
        name_local=room.name_local,
        names=localized_text_to_dict(room.names) if room.names is not None else None,
        semantic_publication_id=room.semantic_publication_id,
        semantic_entity_external_id=room.semantic_entity_external_id,
        semantic_entity_type=room.semantic_entity_type,
        room_number=room.room_number,
        floor=room.floor,
        room_type=room.room_type,
        description=room.description,
        category=room.category,
        map_id=room.map_id,
        x=room.x,
        y=room.y,
        route_point_id=room.route_point_id,
        parent_room_id=room.parent_room_id,
        is_active=room.is_active,
        created_at=room.created_at,
        updated_at=room.updated_at,
    )


async def room_to_response(
    room: Room,
    *,
    route_point_was_reused: bool = False,
    route_point_connected: bool = False,
) -> RoomResponse:
    is_navigable, navigation_unavailable_reason = await compute_room_navigability(room)

    return RoomResponse(
        **_room_static_response_fields(room),
        map_group_id=await resolve_room_map_group_id(room.map_id),
        route_point_was_reused=route_point_was_reused,
        route_point_connected=route_point_connected,
        is_navigable=is_navigable,
        navigation_unavailable_reason=navigation_unavailable_reason,
    )


# ---------------------------------------------------------------------
# Batched enrichment — used ONLY by GET /api/rooms (get_all_rooms).
#
# WHY THIS EXISTS
# ---------------
# room_to_response() is correct but asks the database three questions per
# room: RoutePoint.get(), RouteEdge.find_one() and Map.get(). Building a
# LIST that way costs 1 + 3N sequential round trips. Against a remote
# Atlas cluster that is roughly N x 3 x RTT of pure network latency — the
# measured cause of a ~35 second GET /api/rooms?building_id=... on a
# building with a normal number of destinations.
#
# The list endpoint therefore asks the same three questions ONCE FOR ALL
# ROOMS, in at most three additional queries, and then answers each room
# from memory. The decision ladder below is a line-for-line mirror of
# compute_room_navigability() and resolve_room_map_group_id(); those two
# functions are deliberately left untouched and still serve every
# create / update / get-by-id path exactly as before.
#
# Query count: at most 4 (rooms, route_points, route_edges, maps),
# CONSTANT in the number of rooms. Queries whose input set is empty are
# skipped entirely, so a building with no placed rooms costs fewer.
#
# The response is byte-identical to the old path — tests/test_rooms_list_
# batching.py asserts equality against room_to_response() room by room.
# ---------------------------------------------------------------------


class _RouteEdgeEndpoints(BaseModel):
    """
    Projection: an edge's two endpoint ids are the only thing the
    connectivity test reads. Fetching whole RouteEdge documents here would
    pull the entire corridor graph across the wire for nothing.
    """

    from_point_id: Optional[str] = None
    to_point_id: Optional[str] = None


def _to_object_id(value) -> Optional[PydanticObjectId]:
    """
    Mirrors the `try: PydanticObjectId(...) except: treat as missing`
    behaviour both single-room helpers rely on, so a malformed stored id
    degrades to exactly the same result it does today rather than raising.
    """

    if not value:
        return None

    try:
        return PydanticObjectId(value)
    except Exception:  # noqa: BLE001 - a malformed id is a data problem
        return None


class RoomListEnrichment:
    """
    Pre-fetched answers to the two per-room questions, keyed by the
    CANONICAL id string (str(document.id)) rather than by the raw value
    stored on the Room — the single-room path resolves through
    PydanticObjectId too, so keying any other way could disagree with it
    for a differently-formatted stored id.
    """

    __slots__ = ("points_by_id", "connected_point_ids", "group_id_by_map_id")

    def __init__(
        self,
        points_by_id: Dict[str, RoutePoint],
        connected_point_ids: Set[str],
        group_id_by_map_id: Dict[str, Optional[str]],
    ) -> None:
        self.points_by_id = points_by_id
        self.connected_point_ids = connected_point_ids
        self.group_id_by_map_id = group_id_by_map_id

    def navigability(self, room: Room) -> Tuple[bool, Optional[str]]:
        """Same ladder, same precedence, same reasons as
        compute_room_navigability() — see that function's docstring."""

        if not room.route_point_id:
            if not room.is_active:
                return False, "inactive_destination"

            return False, "missing_route_point"

        point_oid = _to_object_id(room.route_point_id)
        point = (
            self.points_by_id.get(str(point_oid))
            if point_oid is not None
            else None
        )

        if point is not None and not point.is_active:
            return False, "inactive_route_point"

        if not room.is_active:
            return False, "inactive_destination"

        if point is None:
            return False, "route_point_not_found"

        if str(point.id) not in self.connected_point_ids:
            return False, "disconnected_from_graph"

        return True, None

    def map_group_id(self, room: Room) -> Optional[str]:
        """Same resolution as resolve_room_map_group_id()."""

        map_oid = _to_object_id(room.map_id)

        if map_oid is None:
            return None

        return self.group_id_by_map_id.get(str(map_oid))


async def build_room_list_enrichment(rooms: List[Room]) -> RoomListEnrichment:
    point_oids = {
        oid
        for oid in (_to_object_id(room.route_point_id) for room in rooms)
        if oid is not None
    }

    points_by_id: Dict[str, RoutePoint] = {}

    if point_oids:
        points = await RoutePoint.find(
            {"_id": {"$in": list(point_oids)}}
        ).to_list()
        points_by_id = {str(point.id): point for point in points}

    # Only ACTIVE points can ever reach the connectivity check: the ladder
    # above returns inactive_route_point first. Restricting the edge query
    # to them is exactly sufficient and keeps the result set smaller.
    active_point_ids = {
        point_id
        for point_id, point in points_by_id.items()
        if point.is_active
    }

    connected_point_ids: Set[str] = set()

    if active_point_ids:
        candidate_ids = list(active_point_ids)

        # Identical predicate to compute_room_navigability's find_one, just
        # asked for every point at once: an ACTIVE edge touching the point
        # from either end. Served by the two compound indexes declared on
        # RouteEdge (is_active + from_point_id / is_active + to_point_id).
        edges = await RouteEdge.find(
            {
                "is_active": True,
                "$or": [
                    {"from_point_id": {"$in": candidate_ids}},
                    {"to_point_id": {"$in": candidate_ids}},
                ],
            },
            projection_model=_RouteEdgeEndpoints,
        ).to_list()

        for edge in edges:
            if edge.from_point_id in active_point_ids:
                connected_point_ids.add(edge.from_point_id)

            if edge.to_point_id in active_point_ids:
                connected_point_ids.add(edge.to_point_id)

    map_oids = {
        oid
        for oid in (_to_object_id(room.map_id) for room in rooms)
        if oid is not None
    }

    group_id_by_map_id: Dict[str, Optional[str]] = {}

    if map_oids:
        map_items = await Map.find({"_id": {"$in": list(map_oids)}}).to_list()
        group_id_by_map_id = {
            str(map_item.id): map_item.map_group_id for map_item in map_items
        }

    return RoomListEnrichment(
        points_by_id=points_by_id,
        connected_point_ids=connected_point_ids,
        group_id_by_map_id=group_id_by_map_id,
    )


def room_to_list_response(
    room: Room, enrichment: RoomListEnrichment
) -> RoomResponse:
    """
    The batched counterpart of room_to_response(). Synchronous by design —
    every question it needs answered was already answered in bulk.

    route_point_was_reused / route_point_connected are hard-coded False
    here for the same reason room_to_response() defaults them to False:
    they are one-shot signals only meaningful on the exact create/update
    response that performed the map-linking step, and a plain GET has
    always returned False for both (see schemas/room_schema.py).
    """

    is_navigable, navigation_unavailable_reason = enrichment.navigability(room)

    return RoomResponse(
        **_room_static_response_fields(room),
        map_group_id=enrichment.map_group_id(room),
        route_point_was_reused=False,
        route_point_connected=False,
        is_navigable=is_navigable,
        navigation_unavailable_reason=navigation_unavailable_reason,
    )


async def build_room_list_responses(rooms: List[Room]) -> List[RoomResponse]:
    enrichment = await build_room_list_enrichment(rooms)
    return [room_to_list_response(room, enrichment) for room in rooms]


async def _place_room_on_map(
    room: Room,
    *,
    map_id: str,
    x: float,
    y: float,
    building_id: str,
) -> Tuple[bool, bool]:
    """
    Map-based destination placement (create or reposition).

    Creates-or-reuses a "room"-type RoutePoint at (x, y) on this map/floor
    using the same server-side dedup used everywhere else (Priority 2) —
    so clicking the same real-world spot twice, or a spot already covered
    by an existing point within the normal tolerance, reuses that point
    instead of creating a duplicate. A freshly created point is then
    auto-connected to the nearest *valid* (line-of-sight, same map/floor)
    neighbor via the existing graph_connection_service — never "nearest
    regardless of walls", and never invented from scratch here.

    Mutates `room.map_id` / `room.x` / `room.y` / `room.route_point_id`
    in place but does not save it — callers save once, after this
    returns successfully, so a raised exception here never leaves a
    half-updated Room persisted (create_room additionally rolls the new
    Room back entirely on failure — see its try/except).

    Returns (was_reused, connected).
    """

    map_item = await Map.get(PydanticObjectId(map_id))

    if not map_item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Map not found",
        )

    if map_item.building_id and map_item.building_id != building_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="map_id does not belong to the given building_id",
        )

    # PHASE 16/17 — the new RoutePoint (and the Room itself, below) must
    # use the TARGET map's own floor, never the room's previous floor.
    # Using `room.floor` here would be wrong for the exact case this
    # matters most: moving a destination to a different floor's map —
    # the point would be created with the OLD floor number while living
    # on the NEW floor's map, and Room.floor would silently disagree with
    # Room.map_id forever after.
    # The TARGET map's floor wins (PHASE 16/17 — see above). But when the
    # Map itself carries no floor, RoutePoint.floor is the only source of
    # truth on that map (see calculate_edge_distance's own note on the two
    # floor models), so falling back to None would stamp the arrival point
    # with no floor while the corridor points around it have real ones —
    # and the edge layer would then correctly refuse to connect them.
    resolved_point_floor = map_item.floor if map_item.floor is not None else room.floor

    point, was_reused = await find_or_create_route_point(
        map_id=map_id,
        name=room.name_en,
        point_type="room",
        x=x,
        y=y,
        floor=resolved_point_floor,
        building_id=building_id,
        room_id=str(room.id),
        is_accessible=True,
    )

    # A reused point that is already linked to a *different* room is a
    # genuine conflict (two distinct destinations effectively on top of
    # each other) — never silently steal the link, since that would
    # quietly break the other room's navigation.
    if point.room_id and point.room_id != str(room.id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "This map location is already linked to a different "
                "room/destination."
            ),
        )

    if point.room_id != str(room.id):
        point.room_id = str(room.id)
        point.updated_at = datetime.utcnow()
        await point.save()

    if was_reused:
        # Report whatever the point's real current connection state is —
        # it may already have been connected from whenever it was first
        # created, regardless of this specific call.
        existing_edge = await RouteEdge.find_one(
            {
                "map_id": map_id,
                "$or": [
                    {"from_point_id": str(point.id)},
                    {"to_point_id": str(point.id)},
                ],
            }
        )
        connected = existing_edge is not None
    else:
        # ATTACH-ON-SAVE. One shared algorithm
        # (services/destination_attachment_service): corridor nodes AND
        # projection onto a drawn corridor edge, splitting that edge with a
        # junction when the perpendicular foot is the best target, all
        # validated against strict clear-line geometry.
        #
        # This used to call graph_connection_service.auto_connect_point,
        # which only ever looked at corridor NODES — so a room saved beside
        # the MIDDLE of a long corridor stayed unconnected and the admin
        # had to go back and press Auto Connect by hand.
        #
        # Never fails the room creation: a room with no reachable corridor
        # is saved unconnected (pending) and picked up by the bulk retry
        # once the corridor exists.
        attachment = await attach_point_safely(point)
        connected = attachment["status"] in ("attached", "already_connected")

    room.map_id = map_id
    room.x = point.x
    room.y = point.y
    room.route_point_id = str(point.id)
    # Keep Room.floor and its arrival point's floor in agreement. They
    # used to be able to disagree on a Map with no floor of its own (the
    # point got None while the Room kept its requested number), which is
    # exactly the drift that makes an otherwise-valid walkway edge look
    # cross-floor to the edge layer.
    room.floor = resolved_point_floor

    return was_reused, connected


@router.post(
    "",
    response_model=RoomResponse,
    status_code=status.HTTP_201_CREATED
)
async def create_room(
    room_data: RoomCreate,
    user: User = Depends(get_current_user),
):
    if user.role == "regular_user":
        raise HTTPException(**FORBIDDEN_ROLE)

    if not user_can_access_building(user, room_data.building_id):
        raise HTTPException(**FORBIDDEN_BUILDING_SCOPE)

    building = await Building.get(PydanticObjectId(room_data.building_id))

    if not building:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Building not found"
        )

    new_room = Room(
        building_id=room_data.building_id,
        name_en=room_data.name_en,
        name_local=room_data.name_local,
        # merge_localized_text with existing=None simply keeps whatever
        # language(s) the caller actually supplied — no fabrication of
        # the others, exactly like every other creation path.
        names=(
            merge_localized_text(None, room_data.names)
            if room_data.names is not None
            else None
        ),
        semantic_publication_id=room_data.semantic_publication_id,
        semantic_entity_external_id=room_data.semantic_entity_external_id,
        semantic_entity_type=room_data.semantic_entity_type,
        room_number=room_data.room_number,
        floor=room_data.floor,
        room_type=room_data.room_type,
        description=room_data.description,
        category=room_data.category,
        parent_room_id=room_data.parent_room_id,
    )

    await new_room.insert()

    # Map-based placement is opt-in: all three of map_id/x/y must be given
    # together, otherwise this behaves exactly like the pre-existing
    # manual-only flow (no RoutePoint, no navigation link — the fallback
    # the task requires stays fully intact).
    route_point_was_reused = False
    route_point_connected = False

    if (
        room_data.map_id is not None
        and room_data.x is not None
        and room_data.y is not None
    ):
        # RBAC/dashboard cleanup task, Phase 2 continuation: Room
        # authorization was previously building-level only — a
        # building_manager restricted via map_group_ids/map_ids could
        # place a map-linked destination on ANY map within their building,
        # bypassing the finer scope those fields exist to enforce. Fixed
        # here by re-checking the specific target Map, not just the
        # Building, whenever a Room is actually being map-linked.
        try:
            target_map = await Map.get(PydanticObjectId(room_data.map_id))
        except Exception:
            target_map = None
        if target_map is None or not user_can_access_map(user, target_map):
            await new_room.delete()
            raise HTTPException(**FORBIDDEN_MAP_SCOPE)

        try:
            route_point_was_reused, route_point_connected = await _place_room_on_map(
                new_room,
                map_id=room_data.map_id,
                x=room_data.x,
                y=room_data.y,
                building_id=room_data.building_id,
            )
            await new_room.save()
        except Exception:
            # Compensating rollback — never leave an orphaned Room behind
            # just because the map-linking half of this operation failed.
            await new_room.delete()
            raise

    return await room_to_response(
        new_room,
        route_point_was_reused=route_point_was_reused,
        route_point_connected=route_point_connected,
    )


@router.post(
    "/sync-from-route-points",
    response_model=RoomSyncResponse,
)
async def sync_rooms_from_route_points(
    sync_request: RoomSyncRequest,
    user: User = Depends(get_current_user),
):
    """
    Admin-only bulk repair (Section 4): "Sync Rooms from Route Points".

    The project already contains destination-capable RoutePoints (type
    "room"/"store") created before this feature existed, with no linked
    Room at all — this scans exactly those points within the given scope
    and creates/updates their linked Rooms via the same
    services.room_sync_service logic the normal create/update path now
    uses automatically, PLUS the conservative legacy-name-matching
    fallback (Section 5) that only this deliberate, admin-confirmed bulk
    action is allowed to use.

    Never touches Dijkstra, RouteEdge, graph topology, or coordinates —
    reachability/routing are entirely unaffected by this action (Section
    7: "Reachability and route calculation remain separate from
    destination registration").
    """

    if user.role == "regular_user":
        raise HTTPException(**FORBIDDEN_ROLE)

    if not sync_request.building_id and not sync_request.map_group_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Either building_id or map_group_id is required.",
        )

    if sync_request.building_id:
        if not user_can_access_building(user, sync_request.building_id):
            raise HTTPException(**FORBIDDEN_BUILDING_SCOPE)

        query = {
            "point_type": {"$in": sorted(DESTINATION_CAPABLE_POINT_TYPES)},
            "is_active": True,
            "building_id": sync_request.building_id,
        }
    else:
        maps_in_group = await Map.find(
            Map.map_group_id == sync_request.map_group_id
        ).to_list()
        map_ids = [str(m.id) for m in maps_in_group]

        # An admin scoping by Map Group must be able to manage every
        # building those maps belong to — mirrors the single-building
        # check above rather than trusting map_group_id blindly.
        building_ids_in_group = {
            m.building_id for m in maps_in_group if m.building_id
        }
        for scoped_building_id in building_ids_in_group:
            if not user_can_access_building(user, scoped_building_id):
                raise HTTPException(**FORBIDDEN_BUILDING_SCOPE)

        query = {
            "point_type": {"$in": sorted(DESTINATION_CAPABLE_POINT_TYPES)},
            "is_active": True,
            "map_id": {"$in": map_ids},
        }

    points = await RoutePoint.find(query).to_list()

    scanned = 0
    created = 0
    updated = 0
    skipped = 0
    failed = 0
    warnings: List[str] = []

    for point in points:
        scanned += 1

        try:
            outcome = await sync_room_for_route_point(
                point, allow_legacy_fallback=True
            )
        except Exception:
            failed += 1
            logger.exception(
                "Bulk room sync failed for RoutePoint %s", point.id
            )
            warnings.append(
                f"RoutePoint {point.id} (\"{point.name}\"): sync failed — "
                "see server logs."
            )
            continue

        if outcome.action == "created":
            created += 1
        elif outcome.action in ("updated", "reused"):
            updated += 1
        else:
            # skipped_ambiguous / skipped_no_building / any other
            # non-error outcome the single-point path can also return.
            skipped += 1

        if outcome.warning:
            warnings.append(outcome.warning)

    return RoomSyncResponse(
        scanned=scanned,
        created=created,
        updated=updated,
        skipped=skipped,
        failed=failed,
        warnings=warnings[:50],
    )


@router.get(
    "",
    response_model=List[RoomResponse]
)
async def get_all_rooms(
    building_id: Optional[str] = Query(default=None),
    # FLOOR ISOLATION. In this project one Map IS one floor, so map_id is
    # the only exact floor scope: `floor` alone is ambiguous whenever a
    # building holds two maps for the same floor number (a superseded
    # upload with is_current_for_floor=False, or two wings). Without this
    # filter the admin Rooms list and every count derived from it showed
    # every floor's rooms at once, which is what made one floor's data
    # look like it had replaced another's.
    map_id: Optional[str] = Query(default=None),
    floor: Optional[int] = Query(default=None),
    room_type: Optional[str] = Query(default=None),
    admin: User = Depends(get_current_user_optional),
):
    """
    RBAC/dashboard cleanup task, Phase 9 — same optional-auth pattern as
    GET /api/locations/buildings above: this endpoint is also the one the
    public, anonymous DestinationSelectionScreen uses to browse rooms for
    end-user navigation, so an anonymous caller (and a logged-in
    `regular_user`) see exactly the same unrestricted result as before.

    When the caller IS an authenticated admin-tier user, the result is
    additionally narrowed to only rooms in buildings they can access —
    this is what makes the Admin Dashboard's room count correctly scoped
    per role instead of always reflecting the whole system.
    """

    query = {}

    if building_id:
        query["building_id"] = building_id

    if map_id:
        query["map_id"] = map_id

    if floor is not None:
        query["floor"] = floor

    if room_type:
        query["room_type"] = room_type

    if admin is not None and admin.role != "regular_user":
        accessible_ids = get_accessible_building_ids(admin)
        if accessible_ids is not None:
            if building_id:
                # Caller explicitly asked for one building — honor scope by
                # rejecting rather than silently ignoring an out-of-scope
                # request (consistent with the rest of this task's
                # "never silently re-scope an explicit request" rule).
                if building_id not in accessible_ids:
                    raise HTTPException(**FORBIDDEN_BUILDING_SCOPE)
            else:
                query["building_id"] = {"$in": accessible_ids}

    rooms = await Room.find(query).to_list()

    # Batched enrichment — see build_room_list_enrichment above. Produces
    # the identical RoomResponse list the previous
    # `[await room_to_response(room) for room in rooms]` produced, in a
    # constant number of queries instead of 1 + 3N.
    return await build_room_list_responses(rooms)


@router.get(
    "/{room_id}",
    response_model=RoomResponse
)
async def get_room_by_id(room_id: PydanticObjectId):
    room = await Room.get(room_id)

    if not room:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Room not found"
        )

    return await room_to_response(room)


@router.put(
    "/{room_id}",
    response_model=RoomResponse
)
async def update_room(
    room_id: PydanticObjectId,
    room_data: RoomUpdate,
    user: User = Depends(get_current_user),
):
    room = await Room.get(room_id)

    if not room:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Room not found"
        )

    if user.role == "regular_user":
        raise HTTPException(**FORBIDDEN_ROLE)

    if not user_can_access_building(user, room.building_id):
        raise HTTPException(**FORBIDDEN_BUILDING_SCOPE)

    # RBAC/dashboard cleanup task, Phase 2 continuation: a Room already
    # linked to a specific Map (map-based destination placement) must also
    # be checked at map/map-group scope, not just building scope — the
    # same fix as create_room above, now for editing an existing one.
    if room.map_id:
        try:
            current_map = await Map.get(PydanticObjectId(room.map_id))
        except Exception:
            current_map = None
        if current_map is not None and not user_can_access_map(user, current_map):
            raise HTTPException(**FORBIDDEN_MAP_SCOPE)

    update_data = room_data.model_dump(exclude_unset=True)

    # Only validate room_type when it is actually CHANGING to a new value
    # — resaving a Room without touching its Type (or an admin action that
    # round-trips the existing value unchanged) must never fail just
    # because the CURRENTLY STORED value predates this canonical list
    # (e.g. a genuinely old, unknown legacy value not in
    # ALL_ACCEPTED_DESTINATION_TYPES at all). This is what keeps "preserve
    # all existing stored values" true even for values this list can't
    # anticipate, while still rejecting a genuinely new unsupported value
    # someone tries to actively set.
    if (
        "room_type" in update_data
        and update_data["room_type"] != room.room_type
        and not is_accepted_destination_type(update_data["room_type"])
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Unsupported room_type '{update_data['room_type']}'. "
                f"Must be one of: {sorted(ALL_ACCEPTED_DESTINATION_TYPES)}"
            ),
        )

    if "building_id" in update_data:
        if not user_can_access_building(user, update_data["building_id"]):
            raise HTTPException(**FORBIDDEN_BUILDING_SCOPE)

        building = await Building.get(PydanticObjectId(update_data["building_id"]))

        if not building:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Building not found"
            )

    # Map placement (map_id/x/y) is handled separately below via
    # _place_room_on_map — same "all three together, or treat as no
    # placement change" rule as create_room — so it's excluded from the
    # generic setattr loop instead of being written to the Room directly.
    new_map_id = update_data.pop("map_id", None)
    new_x = update_data.pop("x", None)
    new_y = update_data.pop("y", None)

    # `names` needs LANGUAGE-LEVEL merge semantics, not a blind overwrite
    # — model_dump(exclude_unset=True) only tracks whether the whole
    # `names` field was sent, not which individual language keys inside
    # it were. Sending {"names": {"ar": "..."}} must correct Arabic only
    # and leave any already-stored English/Hebrew translations untouched
    # (never silently blanked), so this is merged explicitly rather than
    # falling through the generic setattr loop below.
    if "names" in update_data:
        new_names = update_data.pop("names")
        room.names = merge_localized_text(room.names, new_names)

    for field, value in update_data.items():
        setattr(room, field, value)

    route_point_was_reused = False
    route_point_connected = False

    if new_map_id is not None and new_x is not None and new_y is not None:
        # Uses the room's building_id/floor as they stand AFTER the
        # updates above are applied, so repositioning a destination that
        # is also being moved to a new building/floor in the same request
        # links the new RoutePoint under the correct building/floor.
        route_point_was_reused, route_point_connected = await _place_room_on_map(
            room,
            map_id=new_map_id,
            x=new_x,
            y=new_y,
            building_id=room.building_id,
        )
    elif room.route_point_id:
        # No placement change this call — report the linked point's real
        # current connection state rather than defaulting to "false", so
        # an admin editing just the name/description doesn't see a
        # misleading "not connected" for an already-connected destination.
        existing_edge = await RouteEdge.find_one(
            {
                "map_id": room.map_id,
                "$or": [
                    {"from_point_id": room.route_point_id},
                    {"to_point_id": room.route_point_id},
                ],
            }
        )
        route_point_connected = existing_edge is not None

    room.updated_at = datetime.utcnow()

    await room.save()
    return await room_to_response(
        room,
        route_point_was_reused=route_point_was_reused,
        route_point_connected=route_point_connected,
    )


@router.delete(
    "/{room_id}",
    status_code=status.HTTP_200_OK
)
async def delete_room(
    room_id: PydanticObjectId,
    user: User = Depends(get_current_user),
):
    room = await Room.get(room_id)

    if not room:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Room not found"
        )

    if user.role == "regular_user":
        raise HTTPException(**FORBIDDEN_ROLE)

    if not user_can_access_building(user, room.building_id):
        raise HTTPException(**FORBIDDEN_BUILDING_SCOPE)

    # A room that is already connected to the navigation graph (has a
    # RoutePoint pointing at it) must not be silently unlinked — the
    # admin needs to disconnect it from the graph first.
    linked_point = await RoutePoint.find_one(
        RoutePoint.room_id == str(room_id)
    )

    if linked_point:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "This room is still connected to the navigation graph. "
                "Remove its route point connection before deleting it."
            ),
        )

    await room.delete()

    return {
        "message": "Room deleted successfully"
    }