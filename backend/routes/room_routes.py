import logging
from datetime import datetime
from typing import List, Optional, Tuple

from beanie import PydanticObjectId
from fastapi import APIRouter, Depends, HTTPException, Query, status

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
from services.graph_connection_service import auto_connect_point
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

    The reason returned should preserve the original cause:
      1. missing_route_point
      2. route_point_not_found
      3. inactive_route_point
      4. inactive_destination
      5. disconnected_from_graph

    A RoutePoint deactivation may also synchronize Room.is_active=False.
    When the linked RoutePoint still exists and is inactive, the more
    specific reason is therefore inactive_route_point. If the point was
    deleted and the Room was soft-deactivated, the reason remains
    inactive_destination.
    """

    if not room.route_point_id:
        if not room.is_active:
            return False, "inactive_destination"

        return False, "missing_route_point"

    point = None

    try:
        point = await RoutePoint.get(
            PydanticObjectId(room.route_point_id)
        )
    except Exception:
        point = None

    if point is not None and not point.is_active:
        return False, "inactive_route_point"

    if not room.is_active:
        return False, "inactive_destination"

    if point is None:
        return False, "route_point_not_found"

    # Any active edge referencing this point, from either end, counts.
    connected_edge = await RouteEdge.find_one(
        {
            "is_active": True,
            "$or": [
                {"from_point_id": str(point.id)},
                {"to_point_id": str(point.id)},
            ],
        }
    )

    if not connected_edge:
        return False, "disconnected_from_graph"

    return True, None


async def room_to_response(
    room: Room,
    *,
    route_point_was_reused: bool = False,
    route_point_connected: bool = False,
) -> RoomResponse:
    is_navigable, navigation_unavailable_reason = await compute_room_navigability(room)

    return RoomResponse(
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
        map_group_id=await resolve_room_map_group_id(room.map_id),
        is_active=room.is_active,
        created_at=room.created_at,
        updated_at=room.updated_at,
        route_point_was_reused=route_point_was_reused,
        route_point_connected=route_point_connected,
        is_navigable=is_navigable,
        navigation_unavailable_reason=navigation_unavailable_reason,
    )


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
    point, was_reused = await find_or_create_route_point(
        map_id=map_id,
        name=room.name_en,
        point_type="room",
        x=x,
        y=y,
        floor=map_item.floor,
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
        connection_summary = await auto_connect_point(point, mode="nearest")
        connected = len(connection_summary["edges_created"]) > 0

    room.map_id = map_id
    room.x = point.x
    room.y = point.y
    room.route_point_id = str(point.id)
    room.floor = map_item.floor

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
    return [await room_to_response(room) for room in rooms]


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