import logging
from datetime import datetime
from typing import List, Optional

from beanie import PydanticObjectId
from fastapi import APIRouter, Depends, HTTPException, Query, status

from core.auth_deps import require_global_admin
from models.route_point_model import RoutePoint
from models.route_edge_model import RouteEdge
from models.location_code_model import LocationCode
from models.map_model import Map
from models.building_model import Building
from models.room_model import Room
from models.user_model import User
from schemas.route_point_schema import (
    RoutePointCreate,
    RoutePointUpdate,
    RoutePointResponse,
    RoutePointFloorBackfillRequest,
    RoutePointFloorBackfillResponse,
    RoutePointFloorChange,
)

from services.point_dedup_service import find_or_create_route_point
from services.graph_connection_service import auto_connect_point
from services.room_sync_service import (
    sync_room_for_route_point,
    deactivate_linked_room_for_deleted_point,
)


logger = logging.getLogger(__name__)


router = APIRouter(
    prefix="/api/route-points",
    tags=["Route Points"]
)


def route_point_to_response(
    point: RoutePoint,
    was_reused: bool = False,
    auto_connected_edge_ids: Optional[List[str]] = None,
    room_sync_action: Optional[str] = None,
    room_sync_warning: Optional[str] = None,
) -> RoutePointResponse:
    return RoutePointResponse(
        id=str(point.id),
        map_id=point.map_id,
        name=point.name,
        point_type=point.point_type,
        x=point.x,
        y=point.y,
        floor=point.floor,
        building_id=point.building_id,
        room_id=point.room_id,
        is_accessible=point.is_accessible,
        is_active=point.is_active,
        display_name=point.display_name,
        display_name_en=point.display_name_en,
        display_name_ar=point.display_name_ar,
        display_name_he=point.display_name_he,
        semantic_publication_id=point.semantic_publication_id,
        semantic_entity_external_id=point.semantic_entity_external_id,
        semantic_entity_type=point.semantic_entity_type,
        allow_transit_through=point.allow_transit_through,
        is_auto_generated=point.is_auto_generated,
        generation_method=point.generation_method,
        generation_confidence=point.generation_confidence,
        generation_version=point.generation_version,
        created_at=point.created_at,
        updated_at=point.updated_at,
        was_reused=was_reused,
        auto_connected_edge_ids=auto_connected_edge_ids or [],
        room_sync_action=room_sync_action,
        room_sync_warning=room_sync_warning,
    )


async def _sync_linked_room_safely(point: RoutePoint, *, context: str) -> tuple:
    """
    Shared create/update wrapper around room_sync_service (Section 8:
    "If automatic Room creation fails after a RoutePoint is created:
    return a clear admin-facing error or warning; log enough context
    safely; do not expose secrets or raw database exceptions to end
    users."). A sync failure NEVER fails the RoutePoint create/update
    itself — the point is already safely saved by the time this runs; the
    caller only ever surfaces a short, safe warning string alongside the
    otherwise-successful response.
    """

    try:
        outcome = await sync_room_for_route_point(point)
        return outcome.action, outcome.warning
    except Exception:
        logger.exception(
            "Room sync failed for RoutePoint %s during %s", point.id, context
        )
        return "sync_failed", (
            "This route point was saved, but automatically creating/"
            "updating its linked destination Room failed. It will not "
            "appear in the user destination list yet — try again or use "
            "'Sync Rooms from Route Points'."
        )


async def validate_related_ids(
    map_id: Optional[str] = None,
    building_id: Optional[str] = None,
    room_id: Optional[str] = None,
):
    if map_id:
        map_item = await Map.get(PydanticObjectId(map_id))
        if not map_item:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Map not found"
            )

    if building_id:
        building = await Building.get(PydanticObjectId(building_id))
        if not building:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Building not found"
            )

    if room_id:
        room = await Room.get(PydanticObjectId(room_id))
        if not room:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Room not found"
            )


@router.post(
    "",
    response_model=RoutePointResponse,
    status_code=status.HTTP_201_CREATED
)
async def create_route_point(
    point_data: RoutePointCreate,
    # "off" (default): never auto-connect — the caller (e.g. Draw Walkable
    # Path) manages every edge explicitly and must not get surprise edges.
    # "nearest": connect to the single closest valid neighbor.
    # "all_valid": connect to every valid neighbor up to a small cap, for
    # junctions with multiple real branches.
    auto_connect: str = Query(
        default="off", pattern="^(off|nearest|all_valid)$"
    ),
    _admin: User = Depends(require_global_admin),
):
    map_item = await Map.get(PydanticObjectId(point_data.map_id))

    if not map_item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Map not found"
        )

    # A point belongs to the same building as its map (Part 8 consistency
    # rule) — inherit silently when the caller didn't specify one, reject
    # loudly when they specified one that disagrees with the map's.
    resolved_building_id = point_data.building_id

    if resolved_building_id and map_item.building_id:
        if resolved_building_id != map_item.building_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "building_id does not match the building_id of "
                    "this point's map"
                ),
            )
    elif not resolved_building_id:
        resolved_building_id = map_item.building_id

    await validate_related_ids(
        map_id=point_data.map_id,
        building_id=resolved_building_id,
        room_id=point_data.room_id,
    )

    # "Treat map_id as the authoritative floor source" — a RoutePoint's
    # floor is derived from the Map it belongs to whenever that Map has a
    # real floor recorded, never trusted verbatim from the caller (the
    # frontend's own state can be stale, e.g. mid floor-switch, or simply
    # wrong for a legacy client). Only when the Map itself has no floor at
    # all (a legacy/ungrouped map that predates floor tracking) does the
    # caller-supplied value get used as a last resort — this never
    # fabricates a floor that isn't backed by either the Map or an
    # explicit caller value.
    resolved_floor = (
        map_item.floor if map_item.floor is not None else point_data.floor
    )

    if point_data.force_create:
        new_point = RoutePoint(
            map_id=point_data.map_id,
            name=point_data.name,
            point_type=point_data.point_type,
            x=point_data.x,
            y=point_data.y,
            floor=resolved_floor,
            building_id=resolved_building_id,
            room_id=point_data.room_id,
            is_accessible=point_data.is_accessible,
            display_name=point_data.display_name,
            display_name_en=point_data.display_name_en,
            display_name_ar=point_data.display_name_ar,
            display_name_he=point_data.display_name_he,
            semantic_publication_id=point_data.semantic_publication_id,
            semantic_entity_external_id=point_data.semantic_entity_external_id,
            semantic_entity_type=point_data.semantic_entity_type,
            allow_transit_through=point_data.allow_transit_through,
        )
        await new_point.insert()
        was_reused = False
    else:
        # Server-side safety net: even if the frontend's own marker-click
        # reuse logic somehow fails to catch it, a create call for a point
        # that already effectively exists at this map/floor/location
        # returns the existing document instead of inserting a duplicate.
        #
        # display_name*/semantic_* are passed through here too (previously
        # this branch silently dropped them — a real bug: a caller's
        # display_name_en was accepted by the request schema, validated,
        # and then discarded, so the user-facing name it was meant to
        # provide never made it onto the point at all, only the raw
        # `name`). Only takes effect on a genuinely NEW point — a reused
        # point is still never mutated by this call, unchanged from
        # before.
        new_point, was_reused = await find_or_create_route_point(
            map_id=point_data.map_id,
            name=point_data.name,
            point_type=point_data.point_type,
            x=point_data.x,
            y=point_data.y,
            floor=resolved_floor,
            building_id=resolved_building_id,
            room_id=point_data.room_id,
            is_accessible=point_data.is_accessible,
            display_name=point_data.display_name,
            display_name_en=point_data.display_name_en,
            display_name_ar=point_data.display_name_ar,
            display_name_he=point_data.display_name_he,
            semantic_publication_id=point_data.semantic_publication_id,
            semantic_entity_external_id=point_data.semantic_entity_external_id,
            semantic_entity_type=point_data.semantic_entity_type,
        )

    auto_connected_edge_ids: List[str] = []

    if not was_reused and auto_connect != "off":
        connect_summary = await auto_connect_point(new_point, mode=auto_connect)
        auto_connected_edge_ids = [
            str(edge.id) for edge in connect_summary["edges_created"]
        ]

    # Destination data flow (Section 2) — a freshly created or reused
    # destination-capable point (type "room"/"store") gets its linked Room
    # created/reused/updated here, automatically, so the admin never has
    # to separately open Add Room and re-enter the same name. A no-op for
    # every other point_type (entrance/hallway/junction/stairs/elevator).
    room_sync_action, room_sync_warning = await _sync_linked_room_safely(
        new_point, context="create_route_point"
    )

    return route_point_to_response(
        new_point,
        was_reused=was_reused,
        auto_connected_edge_ids=auto_connected_edge_ids,
        room_sync_action=room_sync_action,
        room_sync_warning=room_sync_warning,
    )


@router.post(
    "/backfill-floor-from-map",
    response_model=RoutePointFloorBackfillResponse,
)
async def backfill_floor_from_map(
    backfill_request: RoutePointFloorBackfillRequest,
    _admin: User = Depends(require_global_admin),
):
    """
    Legacy data-consistency repair: for every RoutePoint, treat its
    map_id's Map.floor as the authoritative floor and correct
    RoutePoint.floor to match whenever it's missing (null) or
    inconsistent (a stale value left over from before this Map's floor
    was known, or from a Map replacement). Never touches a point whose
    floor already matches its Map, never touches coordinates, names,
    ids, edges, rooms, or connectors, and never deletes or recreates
    anything — it only ever corrects the single `floor` field on
    already-existing RoutePoint documents.

    A point whose Map is missing entirely, or whose Map itself has no
    floor recorded (so there is nothing authoritative to copy), is left
    untouched and reported as a warning instead of being guessed at.

    Idempotent: run this any number of times — after the first run fixes
    every derivable inconsistency, every subsequent run finds zero points
    needing an update (point.floor already equals map.floor everywhere
    it could be determined), so `dry_run=false` twice in a row produces
    the same end state as running it once.

    `dry_run` defaults to true — the caller must explicitly pass
    `dry_run: false` to actually write anything, matching the required
    "run dry-run first, confirm, then apply" flow of the admin UI action
    that calls this.
    """

    points = await RoutePoint.find_all().to_list()

    # Cache Map lookups — many RoutePoints share the same map_id, and this
    # can run over the entire collection.
    map_cache: dict[str, Optional[Map]] = {}

    async def get_cached_map(map_id: str) -> Optional[Map]:
        if map_id not in map_cache:
            try:
                map_cache[map_id] = await Map.get(PydanticObjectId(map_id))
            except Exception:
                map_cache[map_id] = None
        return map_cache[map_id]

    points_inspected = 0
    changes: List[RoutePointFloorChange] = []
    warnings: List[str] = []

    for point in points:
        points_inspected += 1

        map_item = await get_cached_map(point.map_id)

        if not map_item:
            warnings.append(
                f"RoutePoint {point.id} (\"{point.name}\") references "
                f"missing Map {point.map_id} — left untouched."
            )
            continue

        if map_item.floor is None:
            # The Map itself has no floor recorded (a legacy map that
            # predates floor tracking entirely) — there is nothing
            # authoritative to copy, so this point is reported, not
            # guessed at.
            if point.floor is None:
                warnings.append(
                    f"RoutePoint {point.id} (\"{point.name}\") and its Map "
                    f"{point.map_id} both have no floor recorded — left "
                    f"untouched."
                )
            continue

        if point.floor == map_item.floor:
            continue

        changes.append(
            RoutePointFloorChange(
                point_id=str(point.id),
                map_id=point.map_id,
                name=point.name,
                old_floor=point.floor,
                new_floor=map_item.floor,
            )
        )

        if not backfill_request.dry_run:
            point.floor = map_item.floor
            point.updated_at = datetime.utcnow()
            await point.save()

    return RoutePointFloorBackfillResponse(
        dry_run=backfill_request.dry_run,
        points_inspected=points_inspected,
        points_needing_update=len(changes),
        points_updated=0 if backfill_request.dry_run else len(changes),
        changes=changes,
        warnings=warnings,
    )


@router.get(
    "",
    response_model=List[RoutePointResponse]
)
async def get_all_route_points(
    map_id: Optional[str] = Query(default=None),
    building_id: Optional[str] = Query(default=None),
    room_id: Optional[str] = Query(default=None),
    floor: Optional[int] = Query(default=None),
    point_type: Optional[str] = Query(default=None),
):
    query = {}

    if map_id:
        query["map_id"] = map_id

    if building_id:
        query["building_id"] = building_id

    if room_id:
        query["room_id"] = room_id

    if floor is not None:
        query["floor"] = floor

    if point_type:
        query["point_type"] = point_type

    points = await RoutePoint.find(query).to_list()
    return [route_point_to_response(point) for point in points]


@router.get(
    "/{point_id}",
    response_model=RoutePointResponse
)
async def get_route_point_by_id(point_id: PydanticObjectId):
    point = await RoutePoint.get(point_id)

    if not point:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Route point not found"
        )

    return route_point_to_response(point)


@router.put(
    "/{point_id}",
    response_model=RoutePointResponse
)
async def update_route_point(
    point_id: PydanticObjectId,
    point_data: RoutePointUpdate,
    _admin: User = Depends(require_global_admin),
):
    point = await RoutePoint.get(point_id)

    if not point:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Route point not found"
        )

    update_data = point_data.model_dump(exclude_unset=True)

    await validate_related_ids(
        map_id=update_data.get("map_id"),
        building_id=update_data.get("building_id"),
        room_id=update_data.get("room_id"),
    )

    for field, value in update_data.items():
        setattr(point, field, value)

    point.updated_at = datetime.utcnow()

    await point.save()

    # Destination data flow (Section 3) — keep the linked Room's owned
    # fields (name/translations/building/map/floor/active status) in sync
    # whenever the RoutePoint itself changes. Also handles a point_type
    # change either into "room"/"store" (creates/attaches a Room, same as
    # create) or away from it (deactivates the now-stale linked Room —
    # see room_sync_service.sync_room_for_route_point).
    room_sync_action, room_sync_warning = await _sync_linked_room_safely(
        point, context="update_route_point"
    )

    return route_point_to_response(
        point,
        room_sync_action=room_sync_action,
        room_sync_warning=room_sync_warning,
    )


@router.delete(
    "/{point_id}",
    status_code=status.HTTP_200_OK
)
async def delete_route_point(
    point_id: PydanticObjectId,
    _admin: User = Depends(require_global_admin),
):
    point = await RoutePoint.get(point_id)

    if not point:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Route point not found"
        )

    point_id_str = str(point_id)

    # A point that still has edges attached is load-bearing for the
    # navigation graph — deleting it would silently break every route that
    # passes through it. Reject instead of a wide implicit cascade; the
    # admin deletes the edges first (e.g. by re-drawing that corridor).
    linked_edge = await RouteEdge.find_one(
        {
            "$or": [
                {"from_point_id": point_id_str},
                {"to_point_id": point_id_str},
            ]
        }
    )

    if linked_edge:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "This route point still has connected edges. "
                "Delete the connecting edges before deleting the point."
            ),
        )

    linked_location_code = await LocationCode.find_one(
        LocationCode.route_point_id == point_id_str
    )

    if linked_location_code:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "This route point is used as a location code's start "
                "point. Delete or reassign that location code first."
            ),
        )

    # Destination data flow (Section 3) — never leave a selectable Room
    # pointing at a point that's about to stop existing. Soft-deactivates
    # the linked Room (if any) rather than deleting it, so the admin's
    # Room data isn't destructively cascaded away — only ever done once
    # every other delete guard above has already passed, so this never
    # runs on a delete attempt that's about to fail anyway. Best-effort:
    # a failure here is logged but never blocks the point deletion itself
    # (an already-orphaned-by-deletion point is a strictly worse state to
    # leave the admin stuck in than a Room that stays visible-but-
    # eventually-inconsistent until the next "Sync Rooms" run notices it).
    try:
        await deactivate_linked_room_for_deleted_point(point)
    except Exception:
        logger.exception(
            "Failed to deactivate linked Room before deleting RoutePoint %s",
            point.id,
        )

    await point.delete()

    return {
        "message": "Route point deleted successfully"
    }