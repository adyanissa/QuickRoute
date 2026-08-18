import logging
import math
from datetime import datetime
from typing import List, Optional, Tuple

from beanie import PydanticObjectId
from fastapi import APIRouter, Depends, HTTPException, Query, status

from core.auth_deps import (
    require_global_admin,
    require_any_admin,
    get_current_user_optional,
    user_can_access_map,
    get_accessible_building_ids,
)
from core.errors import FORBIDDEN_MAP_SCOPE, FORBIDDEN_BUILDING_SCOPE
from models.route_edge_model import RouteEdge
from models.route_point_model import RoutePoint
from models.map_model import Map
from models.user_model import User
from schemas.route_edge_schema import (
    RouteEdgeCreate,
    RouteEdgeUpdate,
    RouteEdgeResponse,
)
from schemas.legacy_repair_schema import (
    LegacyRepairApplyRequest,
    LegacyRepairApplyResult,
    LegacyRepairPreviewRequest,
    LegacyRepairPreviewResponse,
    PendingAttachmentRetryRequest,
    PendingAttachmentRetryResult,
)
from schemas.auto_connect_schema import (
    AutoConnectPreviewRequest,
    AutoConnectPreviewResponse,
    AutoConnectApplyRequest,
    AutoConnectApplyResult,
)
from services.auto_connect_destinations_service import (
    preview_auto_connect_destinations,
    apply_auto_connect_destinations,
)
from services.destination_attachment_service import retry_pending_attachments
from services.legacy_edge_repair_service import (
    apply_legacy_edge_repair,
    preview_legacy_edge_repair,
)


router = APIRouter(
    prefix="/api/route-edges",
    tags=["Route Edges"]
)

logger = logging.getLogger("route_edges")


def route_edge_to_response(edge: RouteEdge) -> RouteEdgeResponse:
    return RouteEdgeResponse(
        id=str(edge.id),
        map_id=edge.map_id,
        to_map_id=edge.to_map_id,
        from_point_id=edge.from_point_id,
        to_point_id=edge.to_point_id,
        edge_type=edge.edge_type,
        distance=edge.distance,
        distance_override=edge.distance_override,
        connector_id=edge.connector_id,
        estimated_time_seconds=edge.estimated_time_seconds,
        is_bidirectional=edge.is_bidirectional,
        is_accessible=edge.is_accessible,
        is_active=edge.is_active,
        description=edge.description,
        access_relation=edge.access_relation,
        created_at=edge.created_at,
        updated_at=edge.updated_at,
    )


async def _require_edge_scope(
    admin: User, map_id: str, to_map_id: Optional[str] = None
) -> None:
    """RBAC/dashboard cleanup task, Phase 2 continuation: scope-checks a
    RouteEdge's owning map(s) — for an ordinary same-floor edge this is
    just map_id; for a cross-floor transition edge, BOTH map_id and
    to_map_id must be in the caller's scope (a building_manager restricted
    via map_ids can't reach a connector edge by way of only one of its two
    floors being authorized)."""
    for candidate_map_id in [map_id] + ([to_map_id] if to_map_id else []):
        try:
            map_item = await Map.get(PydanticObjectId(candidate_map_id))
        except Exception:
            map_item = None
        if map_item is None:
            continue
        if not user_can_access_map(admin, map_item):
            raise HTTPException(**FORBIDDEN_MAP_SCOPE)


async def _apply_edge_scope_to_query(query: dict, admin: User) -> dict:
    """Same intersect-with-authorized-scope pattern as
    route_point_routes.py's _apply_authorized_scope_to_query, applied to
    RouteEdge's map_id field. super_admin unrestricted; global_manager/
    building_manager narrowed to their accessible building's maps when no
    explicit map_id filter was given, and rejected outright with 403 when
    they explicitly request a map_id outside their scope."""
    if admin.role == "super_admin":
        return query

    accessible_building_ids = get_accessible_building_ids(admin)

    # A caller whose accessible scope is already "every building" is not
    # narrowed at all, and must not be put through the per-map existence
    # check below either. This mirrors the sibling implementation in
    # route_point_routes._apply_authorized_scope_to_query, which likewise
    # only narrows when get_accessible_building_ids() returns a real list.
    #
    # Without this early return, an unrestricted caller (all_buildings=True,
    # or a project-wide global_manager — see the scope shapes in
    # core/auth_deps.py) still fell into `map_item is None -> 403`, so
    # asking for the edges of a map that simply no longer exists answered
    # 403 "You do not have permission to access this map" instead of an
    # empty list. That made a perfectly ordinary check — "after deleting a
    # map, are its edges gone?" — impossible, and gave a different answer
    # from GET /api/route-points for the identical query and caller.
    if accessible_building_ids is None:
        return query

    requested_map_id = query.get("map_id")
    if requested_map_id:
        try:
            map_item = await Map.get(PydanticObjectId(requested_map_id))
        except Exception:
            map_item = None
        if map_item is None or not user_can_access_map(admin, map_item):
            raise HTTPException(**FORBIDDEN_MAP_SCOPE)
        return query

    maps_in_scope = await Map.find(
        {"building_id": {"$in": accessible_building_ids}}
    ).to_list()
    map_ids_in_scope = [str(m.id) for m in maps_in_scope]

    if admin.role == "building_manager" and admin.map_ids:
        map_ids_in_scope = [m for m in map_ids_in_scope if m in admin.map_ids]
    elif admin.role == "building_manager" and admin.map_group_ids:
        map_ids_in_scope = [
            str(m.id)
            for m in maps_in_scope
            if m.map_group_id in admin.map_group_ids
        ]

    query["map_id"] = {"$in": map_ids_in_scope}
    return query


def get_scale_for_floor(map_item: Map, floor: int) -> float:
    floor_key = str(floor)

    if map_item.floor_scales and floor_key in map_item.floor_scales:
        return map_item.floor_scales[floor_key]

    return map_item.scale


async def validate_edge_ids(
    map_id: Optional[str] = None,
    from_point_id: Optional[str] = None,
    to_point_id: Optional[str] = None,
):
    if map_id:
        map_item = await Map.get(PydanticObjectId(map_id))
        if not map_item:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Map not found"
            )

    # A point being reused into a new edge (e.g. from Draw Walkable Path
    # snapping onto an already-saved point) must still be a real, currently
    # usable point — not just any document that happens to exist.
    if from_point_id:
        from_point = await RoutePoint.get(PydanticObjectId(from_point_id))
        if not from_point:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="From route point not found"
            )
        if not from_point.is_active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="From route point is not active"
            )

    if to_point_id:
        to_point = await RoutePoint.get(PydanticObjectId(to_point_id))
        if not to_point:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="To route point not found"
            )
        if not to_point.is_active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="To route point is not active"
            )


async def find_duplicate_edge(
    map_id: str,
    from_point_id: str,
    to_point_id: str,
    edge_type: str,
    exclude_edge_id: Optional[PydanticObjectId] = None,
) -> Optional[RouteEdge]:
    """
    An "identical" edge is the same map, same edge_type, and the same pair
    of points regardless of stored direction — RouteEdge.is_bidirectional
    already represents direction/traversal, so a second same-type edge
    between the same two points would always be redundant graph data for
    Dijkstra. Used to reject accidental duplicates (e.g. two admins drawing
    over the same corridor, or a stale frontend cache re-submitting a
    segment that already exists) without relying only on client-side
    de-duplication.
    """

    candidates = await RouteEdge.find(
        {
            "map_id": map_id,
            "edge_type": edge_type,
            "$or": [
                {"from_point_id": from_point_id, "to_point_id": to_point_id},
                {"from_point_id": to_point_id, "to_point_id": from_point_id},
            ],
        }
    ).to_list()

    for candidate in candidates:
        if exclude_edge_id is not None and candidate.id == exclude_edge_id:
            continue
        return candidate

    return None


async def resolve_edge_to_map_id(
    map_id: str,
    from_point: RoutePoint,
    to_point: RoutePoint,
    edge_type: str,
) -> Optional[str]:
    """
    Returns the value RouteEdge.to_map_id should be set to for this edge:
    None for every ordinary same-map edge, or the destination floor's
    map_id for a cross-floor stairs/elevator transition. Also performs the
    actual "is this cross-floor connection even allowed" validation, since
    that check needs the same two Map documents this function already
    has to load.

    A normal hallway/walkway edge must NEVER cross floors or maps — that
    rule is unconditional and unrelated to map groups entirely (see the
    `edge_type == "walkway"` branch below, checked before this function is
    even called for that case).

    A stairs/elevator edge MAY connect two different Map documents, but
    only when both maps share the same non-null map_group_id (i.e. they
    are two floors of the *same* explicitly-created multi-floor set) and
    the same building — never merely because two points' coordinates
    happen to be close, and never across unrelated buildings/groups. This
    is deliberately the only place two different Map documents may ever be
    referenced by one RouteEdge.
    """

    if from_point.map_id == to_point.map_id:
        return None

    if edge_type == "walkway":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Both points must belong to the same map",
        )

    from_map = await Map.get(PydanticObjectId(from_point.map_id))
    to_map = await Map.get(PydanticObjectId(to_point.map_id))

    if not from_map or not to_map:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="One of this edge's route points has no valid map",
        )

    if not from_map.map_group_id or not to_map.map_group_id or (
        from_map.map_group_id != to_map.map_group_id
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "A stairs/elevator edge across two different maps is only "
                "allowed when both maps belong to the same map group."
            ),
        )

    if from_map.building_id != to_map.building_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Both maps must belong to the same building.",
        )

    if from_point.map_id != map_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "A cross-floor edge's map_id must be its from_point's "
                "map_id."
            ),
        )

    return to_point.map_id


async def calculate_edge_distance(
    map_id: str,
    from_point_id: str,
    to_point_id: str,
    edge_type: str = "walkway",
    distance_override: Optional[float] = None
) -> float:
    map_item = await Map.get(PydanticObjectId(map_id))
    from_point = await RoutePoint.get(PydanticObjectId(from_point_id))
    to_point = await RoutePoint.get(PydanticObjectId(to_point_id))

    if not map_item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Map not found"
        )

    if not from_point or not to_point:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Route point not found"
        )

    if edge_type == "walkway":
        if (
            from_point.map_id != map_id
            or to_point.map_id != map_id
            or from_point.map_id != to_point.map_id
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Both points must belong to the same map"
            )

        # "Treat map_id as the authoritative floor source" — but only when
        # the Map itself actually has a floor. This codebase supports two
        # floor models side by side:
        #   1. One Map = one floor (Map.floor is set — the normal case for
        #      every Map Group floor, and for any single map created with
        #      an explicit floor). Once two points are confirmed to share
        #      this Map's map_id, they are on the same floor BY
        #      CONSTRUCTION — a raw comparison of the two points' own
        #      `floor` fields is then not just redundant but actively
        #      wrong for legacy RoutePoints whose stored `floor` is null
        #      or stale relative to their Map (exactly the reported
        #      Sakara / "Corridor Point 1784655473213-3" bug). That
        #      comparison must never block an otherwise-valid same-map
        #      edge in this case.
        #   2. One Map hosts multiple floors via RoutePoint.floor alone
        #      (Map.floor is None — the older, still-supported model
        #      predating per-Map floor tracking). Here the Map carries no
        #      floor at all, so RoutePoint.floor remains the only source
        #      of truth and two points on the same map CAN legitimately be
        #      on different floors — the raw comparison must still apply.
        if map_item.floor is not None:
            effective_floor = map_item.floor
        else:
            if from_point.floor != to_point.floor:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Walkway edge must connect points on the same floor"
                )
            effective_floor = from_point.floor

        pixel_distance = math.sqrt(
            (to_point.x - from_point.x) ** 2 +
            (to_point.y - from_point.y) ** 2
        )

        floor_scale = get_scale_for_floor(map_item, effective_floor)
        distance_meters = pixel_distance * floor_scale

        return round(distance_meters, 2)

    if edge_type in ["stairs", "elevator", "escalator", "ramp"]:
        # Cross-map (cross-floor-group) validation — a same-map, different
        # RoutePoint.floor pair (the legacy "one Map = many floors via
        # RoutePoint.floor" model) is unaffected and still requires
        # same_floor to be False below; a cross-map pair is validated by
        # resolve_edge_to_map_id and, if allowed, is always by definition
        # on different floors (two distinct floor Map documents), so no
        # further same-floor check is meaningful for that case.
        if from_point.map_id == to_point.map_id:
            if from_point.floor == to_point.floor:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Stairs or elevator edge should connect points on different floors"
                )
        else:
            await resolve_edge_to_map_id(map_id, from_point, to_point, edge_type)

        if distance_override is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="distance_override is required for stairs/elevator edges"
            )

        return round(distance_override, 2)

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Invalid edge_type"
    )


async def recalculate_walkway_edges_for_map(map_id: str) -> Tuple[int, int]:
    """
    Safe, additive recalculation of existing walkway-edge distances after
    a Map's scale changes (calibrate-scale / copy-calibration). Scoped to
    exactly this Map and exactly `edge_type == "walkway"`:

      - stairs/elevator/escalator/ramp edges are never touched — those use
        `distance_override`, which this never reads or writes (requirement 8);
      - an edge belonging to a different map is never even loaded
        (requirement 9);
      - RoutePoints, coordinates, graph topology, edge direction,
        accessibility, active status, and Dijkstra are never touched — only
        `edge.distance`/`edge.updated_at` are written, via the exact same
        `calculate_edge_distance()` every create/update call already uses,
        so recalculated distances are computed identically to a brand-new
        edge between the same two points;
      - one invalid/orphaned edge (a missing RoutePoint, or a point that no
        longer belongs to this map) is skipped and never aborts the batch
        or the calibration that already succeeded and saved.

    Returns (recalculated_count, skipped_count).
    """

    edges = await RouteEdge.find(
        {"map_id": map_id, "edge_type": "walkway"}
    ).to_list()

    recalculated = 0
    skipped = 0

    for edge in edges:
        try:
            new_distance = await calculate_edge_distance(
                map_id=map_id,
                from_point_id=edge.from_point_id,
                to_point_id=edge.to_point_id,
                edge_type="walkway",
            )
        except Exception as error:  # noqa: BLE001 — one bad edge must never
            # abort the batch or the calibration save that already
            # succeeded (requirement 5). Covers both the deliberate
            # HTTPException validation failures inside
            # calculate_edge_distance (missing/orphaned point, point no
            # longer on this map) and any unexpected error.
            skipped += 1
            logger.warning(
                "Skipped walkway edge %s during scale recalculation for "
                "map %s: %s",
                edge.id,
                map_id,
                error,
            )
            continue

        edge.distance = new_distance
        edge.updated_at = datetime.utcnow()
        await edge.save()
        recalculated += 1

    logger.info(
        "Recalculated %s walkway edge(s), skipped %s, for map %s",
        recalculated,
        skipped,
        map_id,
    )

    return recalculated, skipped


@router.post(
    "",
    response_model=RouteEdgeResponse,
    status_code=status.HTTP_201_CREATED
)
async def create_route_edge(
    edge_data: RouteEdgeCreate,
    admin: User = Depends(require_any_admin),
):
    if edge_data.from_point_id == edge_data.to_point_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="from_point_id and to_point_id cannot be the same"
        )

    await validate_edge_ids(
        map_id=edge_data.map_id,
        from_point_id=edge_data.from_point_id,
        to_point_id=edge_data.to_point_id,
    )

    # RBAC/dashboard cleanup task, Phase 2: previously require_global_admin
    # blocked every building_manager from drawing edges at all, even in
    # their own building/map.
    await _require_edge_scope(admin, edge_data.map_id)

    duplicate_edge = await find_duplicate_edge(
        map_id=edge_data.map_id,
        from_point_id=edge_data.from_point_id,
        to_point_id=edge_data.to_point_id,
        edge_type=edge_data.edge_type,
    )

    if duplicate_edge:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "An edge of this type already exists between these "
                "two route points"
            ),
        )

    calculated_distance = await calculate_edge_distance(
        map_id=edge_data.map_id,
        from_point_id=edge_data.from_point_id,
        to_point_id=edge_data.to_point_id,
        edge_type=edge_data.edge_type,
        distance_override=edge_data.distance_override
    )

    # calculate_edge_distance already validated (and would have raised on)
    # any illegal cross-map pairing — re-deriving to_map_id here just
    # records the already-approved result, it never re-decides anything.
    to_map_id = None
    from_point = await RoutePoint.get(PydanticObjectId(edge_data.from_point_id))
    to_point = await RoutePoint.get(PydanticObjectId(edge_data.to_point_id))
    if from_point and to_point and from_point.map_id != to_point.map_id:
        to_map_id = to_point.map_id
        # The other floor this cross-floor edge reaches into must also be
        # in scope — never just the from_point's map.
        await _require_edge_scope(admin, to_map_id)

    new_edge = RouteEdge(
        map_id=edge_data.map_id,
        to_map_id=to_map_id,
        from_point_id=edge_data.from_point_id,
        to_point_id=edge_data.to_point_id,
        edge_type=edge_data.edge_type,
        distance=calculated_distance,
        distance_override=edge_data.distance_override,
        is_bidirectional=edge_data.is_bidirectional,
        is_accessible=edge_data.is_accessible,
        description=edge_data.description,
    )

    await new_edge.insert()
    return route_edge_to_response(new_edge)


@router.get(
    "",
    response_model=List[RouteEdgeResponse]
)
async def get_all_route_edges(
    map_id: Optional[str] = Query(default=None),
    from_point_id: Optional[str] = Query(default=None),
    to_point_id: Optional[str] = Query(default=None),
    edge_type: Optional[str] = Query(default=None),
    is_accessible: Optional[bool] = Query(default=None),
    admin: User = Depends(require_any_admin),
):
    # RBAC/dashboard cleanup task, Phase 2/3: RouteEdges are never consumed
    # by the public/anonymous navigation flow (unlike RoutePoint) — routing
    # itself goes through a dedicated Dijkstra endpoint, never this raw
    # list — so this can safely require authentication outright rather
    # than needing the optional-auth compromise route_point_routes.py
    # uses.
    query = {}

    if map_id:
        query["map_id"] = map_id

    if from_point_id:
        query["from_point_id"] = from_point_id

    if to_point_id:
        query["to_point_id"] = to_point_id

    if edge_type:
        query["edge_type"] = edge_type

    if is_accessible is not None:
        query["is_accessible"] = is_accessible

    query = await _apply_edge_scope_to_query(query, admin)

    edges = await RouteEdge.find(query).to_list()
    return [route_edge_to_response(edge) for edge in edges]


@router.get(
    "/{edge_id}",
    response_model=RouteEdgeResponse
)
async def get_route_edge_by_id(
    edge_id: PydanticObjectId,
    admin: User = Depends(require_any_admin),
):
    edge = await RouteEdge.get(edge_id)

    if not edge:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Route edge not found"
        )

    if admin.role != "super_admin":
        await _require_edge_scope(admin, edge.map_id, edge.to_map_id)

    return route_edge_to_response(edge)


@router.put(
    "/{edge_id}",
    response_model=RouteEdgeResponse
)
async def update_route_edge(
    edge_id: PydanticObjectId,
    edge_data: RouteEdgeUpdate,
    admin: User = Depends(require_any_admin),
):
    edge = await RouteEdge.get(edge_id)

    if not edge:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Route edge not found"
        )

    if admin.role != "super_admin":
        await _require_edge_scope(admin, edge.map_id, edge.to_map_id)

    update_data = edge_data.model_dump(exclude_unset=True)

    new_map_id = update_data.get("map_id", edge.map_id)
    new_from_point_id = update_data.get("from_point_id", edge.from_point_id)
    new_to_point_id = update_data.get("to_point_id", edge.to_point_id)
    new_edge_type = update_data.get("edge_type", edge.edge_type)
    new_distance_override = update_data.get(
        "distance_override",
        edge.distance_override
    )

    if new_from_point_id == new_to_point_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="from_point_id and to_point_id cannot be the same"
        )

    await validate_edge_ids(
        map_id=update_data.get("map_id"),
        from_point_id=update_data.get("from_point_id"),
        to_point_id=update_data.get("to_point_id"),
    )

    if (
        "map_id" in update_data
        or "from_point_id" in update_data
        or "to_point_id" in update_data
        or "edge_type" in update_data
    ):
        duplicate_edge = await find_duplicate_edge(
            map_id=new_map_id,
            from_point_id=new_from_point_id,
            to_point_id=new_to_point_id,
            edge_type=new_edge_type,
            exclude_edge_id=edge.id,
        )

        if duplicate_edge:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "An edge of this type already exists between these "
                    "two route points"
                ),
            )

    if (
        "map_id" in update_data
        or "from_point_id" in update_data
        or "to_point_id" in update_data
        or "edge_type" in update_data
        or "distance_override" in update_data
    ):
        update_data["distance"] = await calculate_edge_distance(
            map_id=new_map_id,
            from_point_id=new_from_point_id,
            to_point_id=new_to_point_id,
            edge_type=new_edge_type,
            distance_override=new_distance_override
        )

    for field, value in update_data.items():
        setattr(edge, field, value)

    edge.updated_at = datetime.utcnow()

    await edge.save()
    return route_edge_to_response(edge)


@router.delete(
    "/{edge_id}",
    status_code=status.HTTP_200_OK
)
async def delete_route_edge(
    edge_id: PydanticObjectId,
    admin: User = Depends(require_any_admin),
):
    edge = await RouteEdge.get(edge_id)

    if not edge:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Route edge not found"
        )

    if admin.role != "super_admin":
        await _require_edge_scope(admin, edge.map_id, edge.to_map_id)

    await edge.delete()

    return {
        "message": "Route edge deleted successfully"
    }


# ---------------------------------------------------------------------------
# "Auto Connect Destinations to Corridors" — preview/apply pair. Both are
# POST but neither collides with any existing route in this file: the only
# other POST here is POST "" (create_route_edge, the exact empty path), and
# every "/{edge_id}"-shaped route below is GET/PUT/DELETE only — so route
# registration order relative to those doesn't matter here. Real
# candidate-selection/validation logic lives in
# services/auto_connect_destinations_service.py; this file only wires the
# two admin-protected endpoints to it, matching this file's existing
# router-is-thin convention.
# ---------------------------------------------------------------------------

@router.post(
    "/auto-connect-destinations/preview",
    response_model=AutoConnectPreviewResponse,
)
async def preview_auto_connect_destinations_route(
    request: AutoConnectPreviewRequest,
    admin: User = Depends(require_any_admin),
):
    """
    Entirely read-only — never writes to MongoDB. Returns up to 3 nearest
    valid transit-point candidates per unconnected Room/Store RoutePoint on
    the requested map (or, with scope="map_group", every current floor map
    in the same Map Group), plus a scan summary.
    """

    map_item = await Map.get(PydanticObjectId(request.map_id))
    if not map_item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Map not found",
        )

    if admin.role != "super_admin" and not user_can_access_map(admin, map_item):
        raise HTTPException(**FORBIDDEN_MAP_SCOPE)

    result = await preview_auto_connect_destinations(
        map_id=request.map_id,
        floor=request.floor,
        max_distance_px=request.max_distance_px,
        scope=request.scope,
        lang=request.lang,
    )

    return AutoConnectPreviewResponse(**result)


@router.post(
    "/auto-connect-destinations/apply",
    response_model=AutoConnectApplyResult,
)
async def apply_auto_connect_destinations_route(
    request: AutoConnectApplyRequest,
    admin: User = Depends(require_any_admin),
):
    """
    Creates exactly one ordinary same-floor walkway RouteEdge per
    explicitly accepted destination/corridor pair — never trusting the
    frontend's preview state; every pair is independently revalidated here
    from a fresh database read (see
    services.auto_connect_destinations_service.apply_auto_connect_destinations
    for the full revalidation list). One invalid/failed pair never blocks
    the others. Never deletes or modifies any existing RoutePoint or
    RouteEdge.
    """

    map_item = await Map.get(PydanticObjectId(request.map_id))
    if not map_item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Map not found",
        )

    if admin.role != "super_admin" and not user_can_access_map(admin, map_item):
        raise HTTPException(**FORBIDDEN_MAP_SCOPE)

    result = await apply_auto_connect_destinations(
        map_id=request.map_id,
        accepted_pairs=[pair.model_dump() for pair in request.accepted],
    )

    return AutoConnectApplyResult(**result)


# ─────────────────────────────────────────────────────────────────────
# Legacy invalid-connection repair, and the bulk pending-attachment retry
# ─────────────────────────────────────────────────────────────────────


async def _map_for_admin(map_id: str, admin: User) -> Map:
    """Same map-scope check the Auto Connect endpoints above apply."""
    map_item = await Map.get(PydanticObjectId(map_id))
    if not map_item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Map not found",
        )
    if admin.role != "super_admin" and not user_can_access_map(admin, map_item):
        raise HTTPException(**FORBIDDEN_MAP_SCOPE)
    return map_item


@router.post(
    "/legacy-connections/preview",
    response_model=LegacyRepairPreviewResponse,
)
async def preview_legacy_connections_route(
    request: LegacyRepairPreviewRequest,
    admin: User = Depends(require_any_admin),
):
    """
    Entirely read-only. Finds walkway edges created before the Auto Connect
    correction that route through ordinary destination rooms, and reports
    what is wrong with each one.

    Deliberately preserves approved nested access, same-physical-location
    twins and every ordinary Room -> corridor attachment — see
    services/legacy_edge_repair_service.py for the exact rules.
    """

    await _map_for_admin(request.map_id, admin)

    result = await preview_legacy_edge_repair(request.map_id)
    return LegacyRepairPreviewResponse(**result)


@router.post(
    "/legacy-connections/apply",
    response_model=LegacyRepairApplyResult,
)
async def apply_legacy_connections_route(
    request: LegacyRepairApplyRequest,
    admin: User = Depends(require_any_admin),
):
    """
    Deactivates (never deletes) the confirmed-invalid edges on ONE map,
    then gives every affected destination a chance to reattach to the
    corridor graph through the shared attachment service.

    Never touches the Room, its RoutePoint or its LocationCode. An edge id
    that this map's own preview does not classify as repairable is
    rejected rather than acted on.
    """

    await _map_for_admin(request.map_id, admin)

    result = await apply_legacy_edge_repair(request.map_id, request.edge_ids)
    return LegacyRepairApplyResult(**result)


@router.post(
    "/pending-attachments/retry",
    response_model=PendingAttachmentRetryResult,
)
async def retry_pending_attachments_route(
    request: PendingAttachmentRetryRequest,
    admin: User = Depends(require_any_admin),
):
    """
    Attaches every still-unconnected destination and vertical-connector
    stop on ONE map/floor, using the same algorithm a single save uses.

    This is what makes "place sixty room door points, draw the corridor
    afterwards" work without reopening sixty rooms. Safe to run repeatedly:
    a point that already reaches the graph is skipped, and a repeat run
    never creates a second junction on the same corridor edge.
    """

    await _map_for_admin(request.map_id, admin)

    result = await retry_pending_attachments(request.map_id, floor=request.floor)
    return PendingAttachmentRetryResult(**result)
