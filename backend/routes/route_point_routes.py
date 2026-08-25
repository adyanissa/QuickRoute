import logging
from datetime import datetime
from typing import List, Optional

from beanie import PydanticObjectId
from fastapi import APIRouter, Depends, HTTPException, Query, status

from core.auth_deps import (
    require_global_admin,
    require_any_admin,
    get_current_user_optional,
    get_accessible_building_ids,
    user_can_access_map,
    user_can_access_building,
)
from core.errors import FORBIDDEN_BUILDING_SCOPE, FORBIDDEN_MAP_SCOPE
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
    RoutePointCountResponse,
    RoutePointListResponse,
    PublicRoutePointResponse,
    RoutePointBulkDeleteRequest,
    RoutePointBulkDeleteIssue,
    RoutePointBulkDeleteWarning,
    RoutePointBulkDeletePreviewResponse,
    RoutePointBulkDeleteApplyResponse,
)
import math as _math

from services.point_dedup_service import find_or_create_route_point
from constants.route_point_types import DESTINATION_CAPABLE_POINT_TYPES
from services.graph_connection_service import auto_connect_point
from services.destination_attachment_service import attach_point_safely
from services.room_sync_service import (
    sync_room_for_route_point,
    deactivate_linked_room_for_deleted_point,
)


logger = logging.getLogger(__name__)


router = APIRouter(
    prefix="/api/route-points",
    tags=["Route Points"]
)


# ---------------------------------------------------------
# Scoped counts + source classification (navigation-data cleanup task,
# Problem 2). Both the list endpoint and the count endpoint below share
# this exact same query-builder, so a count can never disagree with what
# the paired list actually shows — the root cause of the old "492 vs 28"
# confusion was two DIFFERENT frontend call sites (one with no filter at
# all, one map-scoped) hitting the same endpoint, not a query bug; giving
# every caller one shared builder plus an explicit `scope` echo in the
# response makes the difference between "all locations" and "this map"
# impossible to conflate silently.
# ---------------------------------------------------------

# This module has no import-time dependency on graph_generation_service
# on purpose (avoids a service-layer <-> route-layer cross-import for a
# single regex) — kept in sync by convention/comment with the identical
# pattern in graph_generation_service.py's _LEGACY_AUTO_POINT_NAME_RE.
import re as _re

_LEGACY_AUTO_POINT_NAME_RE = _re.compile(r"^Auto Point \d+$")


def classify_route_point_source(point: RoutePoint) -> str:
    """
    Authoritative-metadata-first classification (Problem 2.3): never
    infers from the name alone when a real provenance field already
    settles the question. Categories: manual | generated |
    semantic_destination | vertical_connector | unknown_legacy. There is
    currently no distinct "imported" signal anywhere in the RoutePoint
    model, so an explicitly-imported point (if any exist) is
    indistinguishable from "manual" today — a known limitation, not
    silently invented.
    """

    if point.is_auto_generated:
        return "generated"
    if point.semantic_entity_external_id:
        return "semantic_destination"
    if point.connector_id:
        return "vertical_connector"
    if point.name and _LEGACY_AUTO_POINT_NAME_RE.match(point.name.strip()):
        return "unknown_legacy"
    return "manual"


def build_route_point_query(
    *,
    map_id: Optional[str] = None,
    building_id: Optional[str] = None,
    room_id: Optional[str] = None,
    floor: Optional[int] = None,
    point_type: Optional[str] = None,
) -> dict:
    """The one and only place a RoutePoint scope filter is built from
    these params — used by BOTH the list and count endpoints below so
    they can never disagree. `source` is deliberately NOT part of this
    Mongo-level query (it is a derived classification, not a single
    indexed field for every category) — callers that need source
    filtering apply classify_route_point_source() after fetching."""

    query: dict = {}

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

    return query


async def _apply_authorized_scope_to_query(
    query: dict, user: Optional[User]
) -> dict:
    """
    RBAC/dashboard cleanup task, Phase 2 — the critical RoutePoint IDOR
    fix. Intersects a caller-supplied query (from build_route_point_query)
    with what `user` is actually authorized to see, WITHOUT breaking the
    public, unauthenticated kiosk-style navigation flow that also calls
    these same list/count endpoints (IndoorNavigationScreen.jsx resolves
    entrance points and specific RoutePoints with no login at all — this
    is the existing, intentional public wayfinding contract, not a bug,
    and changing it would be exactly the kind of navigation regression
    this task is explicitly forbidden from introducing).

    Behavior:
      - user is None (anonymous) or user.role == "regular_user": query is
        returned completely unchanged — preserves the public navigation
        contract exactly as it already works today.
      - user.role == "super_admin": unchanged — unrestricted by design.
      - user.role in (global_manager, building_manager): the query is
        narrowed to the caller's authorized building/map scope. A request
        that explicitly asks for a building_id/map_id outside that scope
        is rejected with 403 (never silently re-scoped, so an admin UI bug
        can't accidentally show a restricted admin data that LOOKS like
        it's for the building they asked for but silently isn't). A
        request with no building_id/map_id filter at all is scoped down to
        exactly what the caller may see, rather than defaulting to global.
    """

    if user is None or user.role in ("regular_user", "super_admin"):
        return query

    accessible_building_ids = get_accessible_building_ids(user)

    if accessible_building_ids is not None:
        requested_building_id = query.get("building_id")
        if requested_building_id:
            if requested_building_id not in accessible_building_ids:
                raise HTTPException(**FORBIDDEN_BUILDING_SCOPE)
        else:
            query["building_id"] = {"$in": accessible_building_ids}

    if user.role == "building_manager" and user.map_ids:
        requested_map_id = query.get("map_id")
        if requested_map_id:
            if requested_map_id not in user.map_ids:
                raise HTTPException(**FORBIDDEN_MAP_SCOPE)
        else:
            query["map_id"] = {"$in": user.map_ids}
    elif user.role == "building_manager" and user.map_group_ids:
        allowed_maps = await Map.find(
            {"map_group_id": {"$in": user.map_group_ids}}
        ).to_list()
        allowed_map_ids = [str(m.id) for m in allowed_maps]
        requested_map_id = query.get("map_id")
        if requested_map_id:
            if requested_map_id not in allowed_map_ids:
                raise HTTPException(**FORBIDDEN_MAP_SCOPE)
        else:
            query["map_id"] = {"$in": allowed_map_ids}

    return query


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
        connector_id=point.connector_id,
        connector_code=point.connector_code,
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
        source=classify_route_point_source(point),
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
    admin: User = Depends(require_any_admin),
):
    map_item = await Map.get(PydanticObjectId(point_data.map_id))

    if not map_item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Map not found"
        )

    # RBAC/dashboard cleanup task, Phase 2: previously this endpoint was
    # require_global_admin-only, which fully blocked every building_manager
    # from creating RoutePoints at all, even inside their own assigned
    # building/map. Now any admin-tier role may reach this far, but a
    # building_manager (or a global_manager restricted to specific
    # building_ids) must actually be authorized for THIS map.
    if not user_can_access_map(admin, map_item):
        raise HTTPException(**FORBIDDEN_MAP_SCOPE)

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
        # A DESTINATION point goes through the shared attachment service
        # (corridor nodes + corridor-edge projection + junction split +
        # strict geometry) — the same path Room creation, connector stops
        # and the bulk retry use. A corridor/entrance/untyped point keeps
        # the historical nearest-neighbour merge, which is what Draw
        # Walkable Path's "merge with safe nearby graph points" relies on.
        if new_point.point_type in DESTINATION_CAPABLE_POINT_TYPES:
            attachment = await attach_point_safely(new_point)
            auto_connected_edge_ids = (
                [attachment["edge_id"]] if attachment.get("edge_id") else []
            )
        else:
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
    source: Optional[str] = Query(
        default=None,
        description=(
            "Filter by provenance: manual | generated | "
            "semantic_destination | vertical_connector | unknown_legacy. "
            "Omitted (default) returns every source, exactly matching this "
            "endpoint's behavior before this filter existed — fully "
            "backward compatible."
        ),
    ),
    user: Optional[User] = Depends(get_current_user_optional),
):
    """
    NOTE on scope: with no map_id/building_id given AND no authenticated
    admin-tier caller, this returns EVERY RoutePoint in the entire
    database — intentionally unchanged for the public/anonymous kiosk
    navigation flow that relies on it (see
    _apply_authorized_scope_to_query's docstring). An authenticated
    global_manager/building_manager caller has the query automatically
    narrowed to their own authorized building/map scope instead (RBAC/
    dashboard cleanup task, Phase 2) — they can no longer enumerate every
    RoutePoint system-wide through this endpoint. super_admin remains
    unrestricted. Callers that want a scoped count matching what they
    display should call GET .../count below with the SAME filters, rather
    than counting len(this response).
    """

    query = build_route_point_query(
        map_id=map_id,
        building_id=building_id,
        room_id=room_id,
        floor=floor,
        point_type=point_type,
    )

    query = await _apply_authorized_scope_to_query(query, user)

    points = await RoutePoint.find(query).to_list()

    if source:
        points = [p for p in points if classify_route_point_source(p) == source]

    return [route_point_to_response(point) for point in points]


@router.get(
    "/count",
    response_model=RoutePointCountResponse,
)
async def count_route_points(
    map_id: Optional[str] = Query(default=None),
    building_id: Optional[str] = Query(default=None),
    room_id: Optional[str] = Query(default=None),
    floor: Optional[int] = Query(default=None),
    point_type: Optional[str] = Query(default=None),
    source: Optional[str] = Query(default=None),
    user: Optional[User] = Depends(get_current_user_optional),
):
    """
    Problem 2.1/2.6: returns a count with its scope explicitly echoed back
    (never a bare number the caller has to guess the meaning of), built
    from the EXACT SAME build_route_point_query() the list endpoint above
    uses — a dashboard card and a filtered list can never disagree because
    they are never allowed to build their filter two different ways.
    `is_global` is true only when NONE of map_id/building_id/room_id/floor
    were given, i.e. this is the "every RoutePoint in the whole system"
    count — the one that must always be labeled as global/all-locations
    in the UI, never presented as if it belonged to a building or map.
    """

    query = build_route_point_query(
        map_id=map_id,
        building_id=building_id,
        room_id=room_id,
        floor=floor,
        point_type=point_type,
    )

    query = await _apply_authorized_scope_to_query(query, user)

    if source:
        points = await RoutePoint.find(query).to_list()
        count = sum(
            1 for p in points if classify_route_point_source(p) == source
        )
    else:
        count = await RoutePoint.find(query).count()

    return RoutePointCountResponse(
        count=count,
        map_id=map_id,
        building_id=building_id,
        room_id=room_id,
        floor=floor,
        point_type=point_type,
        source=source,
        is_global=not any([map_id, building_id, room_id, floor is not None, point_type]),
    )


@router.get(
    "/list",
    response_model=RoutePointListResponse,
)
async def list_route_points_paginated(
    map_id: Optional[str] = Query(default=None),
    building_id: Optional[str] = Query(default=None),
    map_group_id: Optional[str] = Query(default=None),
    room_id: Optional[str] = Query(default=None),
    floor: Optional[int] = Query(default=None),
    point_type: Optional[str] = Query(default=None),
    source: Optional[str] = Query(default=None),
    search: Optional[str] = Query(default=None, max_length=120),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    user: Optional[User] = Depends(get_current_user_optional),
):
    """
    RBAC/dashboard cleanup task, Phase 8 — paginated, scope-authorized
    RoutePoint listing for the admin management UI. Additive: the plain
    GET /api/route-points (unpaginated) endpoint above is completely
    unchanged and still backs the public navigation flow; this is a new,
    separate endpoint so nothing that already depends on the old response
    shape can break.

    Uses the exact same build_route_point_query() +
    _apply_authorized_scope_to_query() as every other RoutePoint endpoint,
    so a paginated admin list can never disagree with the plain list/count
    for the same filters — the same "one query builder" guarantee Problem
    2 already established.

    `map_group_id` is resolved to its member maps' ids and merged into the
    `map_id` filter (as $in) — RoutePoint has no map_group_id field of its
    own (only Map does), so this is the only way to filter by map group.
    """

    query = build_route_point_query(
        map_id=map_id,
        building_id=building_id,
        room_id=room_id,
        floor=floor,
        point_type=point_type,
    )

    if map_group_id:
        maps_in_group = await Map.find(Map.map_group_id == map_group_id).to_list()
        group_map_ids = [str(m.id) for m in maps_in_group]
        if map_id:
            if map_id not in group_map_ids:
                # Contradictory filters (a map_id that isn't in the
                # requested map_group_id) — an empty, well-formed result
                # rather than a confusing 500 or a silently-wrong match.
                query["map_id"] = "__no_match__"
        else:
            query["map_id"] = {"$in": group_map_ids}

    if search:
        query["name"] = {"$regex": search.strip(), "$options": "i"}

    query = await _apply_authorized_scope_to_query(query, user)

    all_matching = await RoutePoint.find(query).to_list()

    if source:
        all_matching = [
            p for p in all_matching if classify_route_point_source(p) == source
        ]

    total_count = len(all_matching)
    total_pages = max(1, _math.ceil(total_count / page_size)) if total_count else 1

    start = (page - 1) * page_size
    page_items = all_matching[start : start + page_size]

    return RoutePointListResponse(
        items=[route_point_to_response(p) for p in page_items],
        page=page,
        page_size=page_size,
        loaded_count=len(page_items),
        total_count=total_count,
        total_pages=total_pages,
        map_id=map_id,
        building_id=building_id,
        room_id=room_id,
        floor=floor,
        point_type=point_type,
        source=source,
        search=search,
        is_global=not any(
            [map_id, building_id, map_group_id, room_id, floor is not None, point_type]
        ),
    )


def route_point_to_public_response(point: RoutePoint) -> PublicRoutePointResponse:
    """RBAC/dashboard cleanup task, Phase 3 — see PublicRoutePointResponse's
    own docstring for exactly what is deliberately omitted here."""
    return PublicRoutePointResponse(
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
        allow_transit_through=point.allow_transit_through,
    )


@router.get(
    "/public",
    response_model=List[PublicRoutePointResponse],
)
async def get_public_route_points(
    map_id: Optional[str] = Query(default=None),
    building_id: Optional[str] = Query(default=None),
    point_type: Optional[str] = Query(default=None),
):
    """
    RBAC/dashboard cleanup task, Phase 3 — the ONE endpoint the anonymous/
    end-user QR + kiosk navigation flow (IndoorNavigationScreen.jsx) should
    call going forward instead of the general-purpose GET /api/route-points
    above. Requires AT LEAST ONE of map_id/building_id (never both
    omitted) — this is the actual fix for "anonymous global RoutePoint
    enumeration": a specific navigation context is mandatory, but a
    building-wide entrance lookup (the existing, legitimate "find this
    building's entrance point" call, which isn't scoped to one floor/map)
    is still allowed, matching the real pre-existing product behavior
    rather than breaking it. Returns only PublicRoutePointResponse's
    minimal, non-admin field set. No authentication required — this is the
    same public wayfinding data GET /api/maps/{map_id} and GET /api/rooms
    already expose with no login, just explicitly scoped rather than an
    unscoped whole-database dump.
    """

    if not map_id and not building_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="map_id or building_id is required.",
        )

    query: dict = {"is_active": True}
    if map_id:
        query["map_id"] = map_id
    if building_id:
        query["building_id"] = building_id
    if point_type:
        query["point_type"] = point_type

    points = await RoutePoint.find(query).to_list()
    return [route_point_to_public_response(p) for p in points]


@router.get(
    "/public/{point_id}",
    response_model=PublicRoutePointResponse,
)
async def get_public_route_point_by_id(point_id: PydanticObjectId):
    """
    Companion to get_public_route_points above — resolves exactly one
    RoutePoint by id with the same minimal public shape, for the
    entrance/destination-by-id lookups the navigation flow already does
    today. Functionally the public equivalent of GET /{point_id}, kept as
    a genuinely separate route (not just a response_model swap on the
    existing one) so the admin endpoint can evolve independently — e.g.
    if a future change adds authentication-required fields to the admin
    response, this route is unaffected by construction, not by convention.
    """

    point = await RoutePoint.get(point_id)
    if not point:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Route point not found",
        )
    return route_point_to_public_response(point)


@router.get(
    "/{point_id}",
    response_model=RoutePointResponse
)
async def get_route_point_by_id(
    point_id: PydanticObjectId,
    user: Optional[User] = Depends(get_current_user_optional),
):
    point = await RoutePoint.get(point_id)

    if not point:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Route point not found"
        )

    # RBAC/dashboard cleanup task, Phase 2: an authenticated admin-tier
    # caller (global_manager/building_manager) is IDOR-checked against
    # their own building/map scope — they can no longer fetch an arbitrary
    # RoutePoint id outside what they're authorized to manage just by
    # guessing/enumerating ids. Anonymous callers and regular_user are left
    # completely unchanged (see _apply_authorized_scope_to_query's
    # docstring for why: this is the same endpoint the public kiosk
    # navigation flow resolves a destination/entrance point through with
    # no login at all, and that must keep working exactly as before).
    if user is not None and user.role not in ("regular_user", "super_admin"):
        map_item = None
        try:
            map_item = await Map.get(PydanticObjectId(point.map_id))
        except Exception:
            map_item = None

        if map_item is not None:
            if not user_can_access_map(user, map_item):
                raise HTTPException(**FORBIDDEN_MAP_SCOPE)
        elif not point.building_id or not user_can_access_building(
            user, point.building_id
        ):
            raise HTTPException(**FORBIDDEN_BUILDING_SCOPE)

    return route_point_to_response(point)


@router.put(
    "/{point_id}",
    response_model=RoutePointResponse
)
async def update_route_point(
    point_id: PydanticObjectId,
    point_data: RoutePointUpdate,
    admin: User = Depends(require_any_admin),
):
    point = await RoutePoint.get(point_id)

    if not point:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Route point not found"
        )

    # RBAC/dashboard cleanup task, Phase 2: scope-check against the point's
    # CURRENT map (never the caller-supplied update_data.map_id, which
    # hasn't been validated yet at this point and must never be trusted for
    # an authorization decision) before allowing any admin-tier role other
    # than super_admin to modify it.
    if admin.role != "super_admin":
        current_map = None
        try:
            current_map = await Map.get(PydanticObjectId(point.map_id))
        except Exception:
            current_map = None
        if current_map is not None:
            if not user_can_access_map(admin, current_map):
                raise HTTPException(**FORBIDDEN_MAP_SCOPE)
        elif not point.building_id or not user_can_access_building(
            admin, point.building_id
        ):
            raise HTTPException(**FORBIDDEN_BUILDING_SCOPE)

    update_data = point_data.model_dump(exclude_unset=True)

    await validate_related_ids(
        map_id=update_data.get("map_id"),
        building_id=update_data.get("building_id"),
        room_id=update_data.get("room_id"),
    )

    # A caller narrowing this point onto a DIFFERENT map must be authorized
    # for that target map too — otherwise a building_manager could "move"
    # a point they own onto a map outside their scope.
    if admin.role != "super_admin" and update_data.get("map_id"):
        target_map = None
        try:
            target_map = await Map.get(PydanticObjectId(update_data["map_id"]))
        except Exception:
            target_map = None
        if target_map is None or not user_can_access_map(admin, target_map):
            raise HTTPException(**FORBIDDEN_MAP_SCOPE)

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


async def _evaluate_bulk_delete_candidates(
    admin: User,
    point_ids: List[str],
):
    """
    RBAC/dashboard cleanup task, Phase 6 — shared core used by BOTH the
    preview and apply bulk-delete endpoints below, so the two can never
    disagree (the exact same rules, in the exact same order, checked
    against the exact same live database state). Mirrors the single-point
    delete_route_point validation above rule-for-rule:
      1. valid ObjectId
      2. exists (404 -> not_found)
      3. in the caller's scope (map- or building-level)
      4. has no connected RouteEdge (409 on single-delete -> here:
         has_connected_edges, with the actual blocking count)
      5. is not a LocationCode's start point (409 on single-delete -> here:
         has_location_code)
    A point that clears every check is "deletable" and is returned as a
    live RoutePoint document (not just an id) so apply never needs a
    second fetch. Room deactivation (the single-delete's best-effort
    side-effect) is reported here only as a non-blocking warning — it
    never prevents deletion, exactly like the single-point path.
    """

    issues: List[RoutePointBulkDeleteIssue] = []
    warnings: List[RoutePointBulkDeleteWarning] = []
    deletable_points: List[RoutePoint] = []

    # Dedupe while preserving order — a caller accidentally sending the
    # same id twice should never be double-counted or double-deleted.
    seen = set()
    ordered_ids = []
    for raw_id in point_ids:
        if raw_id not in seen:
            seen.add(raw_id)
            ordered_ids.append(raw_id)

    for raw_id in ordered_ids:
        try:
            obj_id = PydanticObjectId(raw_id)
        except Exception:
            issues.append(
                RoutePointBulkDeleteIssue(
                    point_id=raw_id,
                    reason="invalid_id",
                    detail="Not a valid route point id.",
                )
            )
            continue

        point = await RoutePoint.get(obj_id)
        if not point:
            issues.append(
                RoutePointBulkDeleteIssue(
                    point_id=raw_id,
                    reason="not_found",
                    detail="Route point not found.",
                )
            )
            continue

        if admin.role != "super_admin":
            in_scope = False
            current_map = None
            try:
                current_map = await Map.get(PydanticObjectId(point.map_id))
            except Exception:
                current_map = None
            if current_map is not None:
                in_scope = user_can_access_map(admin, current_map)
            elif point.building_id:
                in_scope = user_can_access_building(admin, point.building_id)

            if not in_scope:
                issues.append(
                    RoutePointBulkDeleteIssue(
                        point_id=raw_id,
                        reason="out_of_scope",
                        detail=(
                            "You do not have access to this route point's "
                            "map or building."
                        ),
                    )
                )
                continue

        point_id_str = str(obj_id)

        connected_edge_count = await RouteEdge.find(
            {
                "$or": [
                    {"from_point_id": point_id_str},
                    {"to_point_id": point_id_str},
                ]
            }
        ).count()

        if connected_edge_count > 0:
            issues.append(
                RoutePointBulkDeleteIssue(
                    point_id=raw_id,
                    reason="has_connected_edges",
                    detail=(
                        "This route point still has connected edges. "
                        "Delete the connecting edges before deleting the "
                        "point."
                    ),
                    connected_edge_count=connected_edge_count,
                )
            )
            continue

        linked_location_code = await LocationCode.find_one(
            LocationCode.route_point_id == point_id_str
        )
        if linked_location_code:
            issues.append(
                RoutePointBulkDeleteIssue(
                    point_id=raw_id,
                    reason="has_location_code",
                    detail=(
                        "This route point is used as a location code's "
                        "start point. Delete or reassign that location "
                        "code first."
                    ),
                )
            )
            continue

        if point.room_id:
            warnings.append(
                RoutePointBulkDeleteWarning(
                    point_id=raw_id,
                    reason="linked_room_will_be_deactivated",
                    detail=(
                        "The room linked to this route point will be "
                        "deactivated as a destination."
                    ),
                )
            )

        deletable_points.append(point)

    return issues, warnings, deletable_points


@router.post(
    "/bulk-delete/preview",
    response_model=RoutePointBulkDeletePreviewResponse,
)
async def preview_bulk_delete_route_points(
    payload: RoutePointBulkDeleteRequest,
    admin: User = Depends(require_any_admin),
):
    """
    RBAC/dashboard cleanup task, Phase 6 — read-only. Never deletes
    anything; only reports exactly what would happen if this same
    `point_ids` list were POSTed to /bulk-delete/apply right now. Static
    path registered ahead of GET "/{point_id}" is irrelevant here (this is
    POST, a separate method namespace), but kept alongside apply below for
    readability.
    """

    issues, warnings, deletable_points = await _evaluate_bulk_delete_candidates(
        admin, payload.point_ids
    )

    deletable_ids = [str(p.id) for p in deletable_points]

    return RoutePointBulkDeletePreviewResponse(
        requested_count=len(payload.point_ids),
        deletable_count=len(deletable_ids),
        blocked_count=len(issues),
        deletable_point_ids=deletable_ids,
        issues=issues,
        warnings=warnings,
        can_apply_all=len(issues) == 0 and len(deletable_ids) > 0,
    )


@router.post(
    "/bulk-delete/apply",
    response_model=RoutePointBulkDeleteApplyResponse,
)
async def apply_bulk_delete_route_points(
    payload: RoutePointBulkDeleteRequest,
    admin: User = Depends(require_any_admin),
):
    """
    RBAC/dashboard cleanup task, Phase 6 — strictly all-or-nothing: if ANY
    id in the request fails ANY check (not found, out of scope, has
    connected edges, has a location code, invalid id), the ENTIRE batch is
    rejected with 409 and the full issue list, and NOTHING is deleted.
    This deliberately mirrors the app's existing batch-destination-
    placement convention (all-or-nothing rather than partial-success) so
    an admin bulk-deleting never ends up in a half-applied state they
    have to reconcile by hand. Re-validates everything fresh against the
    live database — never trusts a client-cached preview result.
    """

    issues, warnings, deletable_points = await _evaluate_bulk_delete_candidates(
        admin, payload.point_ids
    )

    if issues:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": (
                    "Bulk delete rejected: one or more route points "
                    "cannot be deleted. Nothing was deleted."
                ),
                "issues": [issue.model_dump() for issue in issues],
            },
        )

    if not deletable_points:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No route points were provided to delete.",
        )

    deleted_ids: List[str] = []
    for point in deletable_points:
        try:
            await deactivate_linked_room_for_deleted_point(point)
        except Exception:
            logger.exception(
                "Failed to deactivate linked Room before bulk-deleting "
                "RoutePoint %s",
                point.id,
            )

        await point.delete()
        deleted_ids.append(str(point.id))

    return RoutePointBulkDeleteApplyResponse(
        deleted_count=len(deleted_ids),
        deleted_point_ids=deleted_ids,
        warnings=warnings,
    )


@router.delete(
    "/{point_id}",
    status_code=status.HTTP_200_OK
)
async def delete_route_point(
    point_id: PydanticObjectId,
    admin: User = Depends(require_any_admin),
):
    point = await RoutePoint.get(point_id)

    if not point:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Route point not found"
        )

    if admin.role != "super_admin":
        current_map = None
        try:
            current_map = await Map.get(PydanticObjectId(point.map_id))
        except Exception:
            current_map = None
        if current_map is not None:
            if not user_can_access_map(admin, current_map):
                raise HTTPException(**FORBIDDEN_MAP_SCOPE)
        elif not point.building_id or not user_can_access_building(
            admin, point.building_id
        ):
            raise HTTPException(**FORBIDDEN_BUILDING_SCOPE)

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