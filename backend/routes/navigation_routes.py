from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel
from beanie import PydanticObjectId

import json
import os

from logic.route_logic import build_graph, dijkstra
from logic.route_calculator import calculate_shortest_path
from logic.multi_floor_routing import (
    calculate_multi_floor_route,
    NO_TRANSITION_MESSAGE_TEMPLATE,
    RoomTransitBlockedError,
)
from logic.instruction_generator import (
    generate_instructions_for_route,
    resolve_display_name,
)

from models.route_edge_model import RouteEdge
from models.route_point_model import RoutePoint
from models.map_model import Map

from core.errors import (
    BUILDING_NOT_FOUND,
    ROOM_NOT_FOUND,
    START_NODE_NOT_FOUND,
    END_NODE_NOT_FOUND,
    NO_ROUTE_FOUND
)


router = APIRouter(tags=["Navigation"])

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class NavigationRouteRequest(BaseModel):
    map_id: str
    start_point_id: str
    end_point_id: str


class NavigationRouteResponse(BaseModel):
    map_id: str
    start_point_id: str
    end_point_id: str
    path_point_ids: list[str]
    path_details: list[dict]
    total_distance: float


def load_json_file(filename):
    file_path = os.path.join(BASE_DIR, "data", filename)

    with open(file_path, "r", encoding="utf-8") as file:
        return json.load(file)


# -----------------------------
# DEPRECATED — old temporary JSON-file-backed endpoints from before the
# MongoDB Atlas migration. Confirmed unused by the current frontend
# (grepped frontend/src for calls to /buildings, /buildings/{id}/rooms,
# /rooms/{id}, /graph, /route — none exist; every screen now calls the
# real /api/... endpoints instead). Left in place rather than deleted so
# no existing API route is removed, but these should not be built upon —
# use /api/locations/buildings, /api/rooms, /api/route-points,
# /api/route-edges and /api/navigation/route instead.
# -----------------------------

@router.get("/buildings", deprecated=True)
def get_buildings():
    buildings = load_json_file("buildings.json")
    return buildings


@router.get("/buildings/{building_id}/rooms", deprecated=True)
def get_rooms_by_building(building_id: str):
    rooms = load_json_file("rooms.json")

    if building_id not in rooms:
        raise HTTPException(**BUILDING_NOT_FOUND)

    return rooms[building_id]


@router.get("/rooms/{room_id}", deprecated=True)
def get_room_by_id(room_id: str):
    rooms = load_json_file("rooms.json")

    for building_rooms in rooms.values():
        for room in building_rooms:
            if room["id"] == room_id:
                return room

    raise HTTPException(**ROOM_NOT_FOUND)


@router.get("/graph", deprecated=True)
def get_graph():
    graph = load_json_file("map_graph.json")
    return graph


@router.get("/route", deprecated=True)
def get_smart_route(
    start: str = Query(..., alias="from"),
    end: str = Query(..., alias="to")
):
    graph_data = load_json_file("map_graph.json")

    nodes = graph_data["nodes"]
    edges = graph_data["edges"]

    node_ids = [node["id"] for node in nodes]

    if start not in node_ids:
        raise HTTPException(**START_NODE_NOT_FOUND)

    if end not in node_ids:
        raise HTTPException(**END_NODE_NOT_FOUND)

    graph = build_graph(edges)
    path, total_distance = dijkstra(graph, start, end)

    if path is None:
        raise HTTPException(**NO_ROUTE_FOUND)

    path_details = []

    for node_id in path:
        node = next((n for n in nodes if n["id"] == node_id), None)
        if node:
            path_details.append(node)

    return {
        "from": start,
        "to": end,
        "path": path,
        "pathDetails": path_details,
        "totalDistance": total_distance
    }


# -----------------------------
# New real MongoDB route API
# -----------------------------

@router.post("/api/navigation/route", response_model=NavigationRouteResponse)
async def calculate_route_from_mongodb(route_data: NavigationRouteRequest):
    start_point = await RoutePoint.get(
        PydanticObjectId(route_data.start_point_id)
    )

    if not start_point:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Start route point not found"
        )

    end_point = await RoutePoint.get(
        PydanticObjectId(route_data.end_point_id)
    )

    if not end_point:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="End route point not found"
        )

    if start_point.map_id != route_data.map_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Start point does not belong to this map"
        )

    if end_point.map_id != route_data.map_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="End point does not belong to this map"
        )

    edges = await RouteEdge.find(
        RouteEdge.map_id == route_data.map_id
    ).to_list()

    result = calculate_shortest_path(
        edges=edges,
        start_point_id=route_data.start_point_id,
        end_point_id=route_data.end_point_id
    )

    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No route found between the selected points"
        )

    path_details = []

    for point_id in result["path_point_ids"]:
        point = await RoutePoint.get(PydanticObjectId(point_id))

        if point:
            path_details.append({
                "id": str(point.id),
                "name": point.name,
                "display_name": resolve_display_name(
                    point.name, point.display_name, point.is_auto_generated
                ),
                # Full multilingual object alongside the legacy single
                # `display_name` above (Section 7) — None for any
                # language never set, never fabricated.
                "display_names": {
                    "en": point.display_name_en,
                    "ar": point.display_name_ar,
                    "he": point.display_name_he,
                },
                "point_type": point.point_type,
                "x": point.x,
                "y": point.y,
                "floor": point.floor,
                "building_id": point.building_id,
                "room_id": point.room_id,
                "is_accessible": point.is_accessible,
            })

    return {
        "map_id": route_data.map_id,
        "start_point_id": route_data.start_point_id,
        "end_point_id": route_data.end_point_id,
        "path_point_ids": result["path_point_ids"],
        "path_details": path_details,
        "total_distance": result["total_distance"]
    }


# -----------------------------
# Multi-floor navigation (PHASES 6-11) — a NEW endpoint, deliberately
# separate from /api/navigation/route above so every existing consumer of
# that endpoint (e.g. AdminMapScreen's Test Route) is completely
# unaffected. Works for same-floor requests too (returns a single floor
# segment, no transitions) so a frontend consumer only needs one endpoint
# once it migrates.
# -----------------------------


class MultiFloorRouteRequest(BaseModel):
    start_point_id: str
    end_point_id: str
    # "shortest" (default) | "fastest" | "accessible"
    optimization_mode: str = "shortest"
    # PHASE 14 — optional avoid settings, independent of optimization_mode
    # (e.g. a "fastest" route that still avoids stairs). prefer_elevators
    # is implemented as a strong preference: avoid both stairs AND
    # escalators, forcing an elevator/ramp where one is configured.
    # Kept exactly as-is (still fully supported) for every existing
    # caller/test — vertical_transport_preference below is a newer,
    # single-choice ADDITION, not a replacement (Section 10: "existing
    # clients and tests must continue working").
    avoid_stairs: bool = False
    avoid_escalators: bool = False
    prefer_elevators: bool = False
    # Single-choice vertical-transport preference (Section 7/8 of the
    # end-user navigation redesign task): "any" (default — every
    # currently-enabled connector type is a valid choice, same as before
    # this field existed), "elevator" (only elevator vertical edges are
    # usable for this route request), or "stairs" (only stairs vertical
    # edges are usable). Never guessed from an existing field — this is a
    # deliberately NEW field name; no pre-existing field meant this
    # (avoid_stairs/avoid_escalators/prefer_elevators are independent
    # boolean toggles, not a single-choice preference, and are preserved
    # unchanged above). Defaulting to "any" means every existing caller
    # that never sends this field is completely unaffected (Section 10).
    vertical_transport_preference: str = "any"
    # Requested UI language for turn-by-turn instruction TEXT only (static
    # phrasing + any dynamic entity/connector names embedded in it) — see
    # logic/instruction_generator.py. Never affects which route is
    # computed (routing/Dijkstra/topology are completely language-
    # independent). An unrecognized value safely falls back to "en"
    # rather than erroring, so a client sending a bad/unsupported value
    # never breaks navigation.
    lang: str = "en"


VERTICAL_PREFERENCE_VALUES = ("any", "elevator", "stairs")

# The connector edge_types (see schemas/route_edge_schema.py's EdgeType)
# that must be excluded from the graph for each single-choice preference
# — Section 8.B/8.C: "elevator" allows ONLY elevator vertical edges,
# "stairs" allows ONLY stairs vertical edges; both always still exclude
# escalator/ramp so a route can never silently substitute a different
# vertical-transport type than the one the user explicitly chose. "any"
# excludes nothing extra (existing avoid_stairs/avoid_escalators/
# prefer_elevators flags, if sent, still apply independently).
VERTICAL_PREFERENCE_EXCLUDED_TYPES = {
    "elevator": frozenset({"stairs", "escalator", "ramp"}),
    "stairs": frozenset({"elevator", "escalator", "ramp"}),
}

# Section 8 — localized, user-friendly "no route available for this
# specific vertical-transport choice" messages. Deliberately separate
# from the generic NO_ROUTE_FOUND/accessible-mode/avoid-preference
# messages already below — a user who explicitly chose "Prefer stairs"
# needs to know THAT choice is the reason, not a generic failure.
NO_ROUTE_FOR_PREFERENCE_MESSAGES = {
    "en": {
        "stairs": "No route using stairs is available to this destination.",
        "elevator": "No route using an elevator is available to this destination.",
    },
    "ar": {
        "stairs": "لا يوجد مسار متاح باستخدام الدرج إلى هذه الوجهة.",
        "elevator": "لا يوجد مسار متاح باستخدام المصعد إلى هذه الوجهة.",
    },
    "he": {
        "stairs": "אין מסלול זמין באמצעות מדרגות ליעד זה.",
        "elevator": "אין מסלול זמין באמצעות מעלית ליעד זה.",
    },
}


class MultiFloorRouteResponse(BaseModel):
    start_point_id: str
    destination_point_id: str
    map_group_id: Optional[str] = None
    optimization_mode: str
    total_distance_meters: float
    total_estimated_time_seconds: float
    is_accessible: bool
    segments: List[dict]
    instructions: List[dict]


@router.post(
    "/api/navigation/multi-floor-route",
    response_model=MultiFloorRouteResponse,
)
async def calculate_multi_floor_route_endpoint(
    route_data: MultiFloorRouteRequest,
):
    if route_data.optimization_mode not in ("shortest", "fastest", "accessible"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="optimization_mode must be one of shortest, fastest, accessible",
        )

    if route_data.vertical_transport_preference not in VERTICAL_PREFERENCE_VALUES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "vertical_transport_preference must be one of "
                f"{', '.join(VERTICAL_PREFERENCE_VALUES)}"
            ),
        )

    # Never let an arbitrary/unexpected value reach the instruction
    # templates below — a client sending anything outside the three
    # supported UI languages just gets English text, exactly the same
    # graceful behavior TEXT_TEMPLATES.get(lang, TEXT_TEMPLATES["en"])
    # already has, made explicit here too.
    lang = route_data.lang if route_data.lang in ("en", "ar", "he") else "en"

    start_point = await RoutePoint.get(PydanticObjectId(route_data.start_point_id))
    if not start_point:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Start route point not found",
        )

    end_point = await RoutePoint.get(PydanticObjectId(route_data.end_point_id))
    if not end_point:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="End route point not found",
        )

    start_map = await Map.get(PydanticObjectId(start_point.map_id))
    end_map = await Map.get(PydanticObjectId(end_point.map_id))

    if not start_map or not end_map:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="One of this route's points has no valid map",
        )

    # Same building is required regardless of whether the two points are
    # on the same floor or different floors of one group — a route must
    # never silently span two unrelated buildings.
    if start_map.building_id and end_map.building_id and (
        start_map.building_id != end_map.building_id
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Start and destination belong to different buildings.",
        )

    map_group_id: Optional[str] = None
    map_ids: List[str]

    if start_point.map_id == end_point.map_id:
        # Same-floor request: always resolvable, whether or not this map
        # belongs to a group — scope the graph to just this one map so an
        # ungrouped single-floor map keeps working through this endpoint
        # too (PHASE 18 backward compatibility), without ever pulling in
        # every OTHER ungrouped map in the system.
        map_group_id = start_map.map_group_id
        map_ids = [start_point.map_id]

        if map_group_id:
            group_maps = await Map.find(
                {"map_group_id": map_group_id}
            ).to_list()
            map_ids = [str(m.id) for m in group_maps] or map_ids
    else:
        if not start_map.map_group_id or not end_map.map_group_id or (
            start_map.map_group_id != end_map.map_group_id
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Start and destination are on different maps that do "
                    "not belong to the same multi-floor map group — "
                    "cross-floor navigation requires both floors to be "
                    "part of one map group."
                ),
            )
        map_group_id = start_map.map_group_id
        group_maps = await Map.find({"map_group_id": map_group_id}).to_list()
        map_ids = [str(m.id) for m in group_maps]

    accessible_only = route_data.optimization_mode == "accessible"

    avoid_types = set()
    if route_data.avoid_stairs or route_data.prefer_elevators:
        avoid_types.add("stairs")
    if route_data.avoid_escalators or route_data.prefer_elevators:
        avoid_types.add("escalator")
    # Section 8 — the single-choice vertical-transport preference is a
    # separate, additive exclusion on top of the legacy avoid_*/
    # prefer_elevators flags above (both may be sent at once; their
    # excluded-type sets simply union together, same as any other
    # avoid_edge_types combination already did before this field existed).
    avoid_types |= VERTICAL_PREFERENCE_EXCLUDED_TYPES.get(
        route_data.vertical_transport_preference, frozenset()
    )
    avoid_edge_types = frozenset(avoid_types) if avoid_types else None

    try:
        result = await calculate_multi_floor_route(
            map_ids=map_ids,
            start_point_id=route_data.start_point_id,
            end_point_id=route_data.end_point_id,
            mode=route_data.optimization_mode,
            accessible_only=accessible_only,
            avoid_edge_types=avoid_edge_types,
            lang=lang,
        )
    except RoomTransitBlockedError as blocked:
        # Section 3 — a clear, distinguishable admin/debug indication
        # rather than a generic no-route error or a silent route through
        # the room. 409 (not 404): the destination IS reachable in
        # principle, but only via a graph configuration this endpoint
        # correctly refuses to use as a through-route.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "This route is blocked: the only path passes through a "
                "destination room/store point, which cannot be used as a "
                "through-route. An admin needs to add a direct corridor "
                "connection between these areas. Blocked point id(s): "
                f"{blocked.blocking_point_ids}."
            ),
        )

    if result is None:
        if accessible_only or avoid_edge_types:
            # Distinguish "no route matching these preferences" from "no
            # route at all": if a route exists once the accessibility/avoid
            # constraints are lifted, the failure is specifically about the
            # requested preferences, and PHASE 14 requires that specific
            # message rather than a generic no-route/no-transition error
            # (and never a silent fallback to an excluded path type).
            try:
                unconstrained = await calculate_multi_floor_route(
                    map_ids=map_ids,
                    start_point_id=route_data.start_point_id,
                    end_point_id=route_data.end_point_id,
                    mode=route_data.optimization_mode,
                    accessible_only=False,
                    avoid_edge_types=None,
                )
            except RoomTransitBlockedError:
                unconstrained = None

            if unconstrained is not None:
                if route_data.vertical_transport_preference in ("stairs", "elevator"):
                    # Section 8 — the specific, localized "no route using
                    # X" message for the exact vertical-transport choice
                    # the user made, distinct from the generic
                    # avoid-stairs/escalators message below.
                    detail = NO_ROUTE_FOR_PREFERENCE_MESSAGES.get(
                        lang, NO_ROUTE_FOR_PREFERENCE_MESSAGES["en"]
                    )[route_data.vertical_transport_preference]
                elif accessible_only:
                    detail = "No accessible route is currently configured."
                else:
                    detail = "No route matches your current avoid-stairs/escalators preference. Try a different route preference."
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=detail,
                )

        if start_point.map_id != end_point.map_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=NO_TRANSITION_MESSAGE_TEMPLATE.format(
                    from_floor=start_point.floor, to_floor=end_point.floor
                ),
            )
        raise HTTPException(**NO_ROUTE_FOUND)

    instructions = generate_instructions_for_route(result.segments, lang=lang)

    return MultiFloorRouteResponse(
        start_point_id=route_data.start_point_id,
        destination_point_id=route_data.end_point_id,
        map_group_id=map_group_id,
        optimization_mode=route_data.optimization_mode,
        total_distance_meters=result.total_distance_meters,
        total_estimated_time_seconds=result.total_estimated_time_seconds,
        is_accessible=result.is_accessible,
        segments=result.segments,
        instructions=instructions,
    )