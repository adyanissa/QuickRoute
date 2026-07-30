"""
Multi-floor Dijkstra + floor-by-floor segmentation (PHASES 9-10).

This is a NEW module — it deliberately does not replace or import
logic/route_calculator.py, which stays exactly as it was for the existing
single-map /api/navigation/route endpoint (Task's "do not rewrite working
same-floor Dijkstra behavior unnecessarily" + "preserve backward
compatibility"). This module is what routes/navigation_routes.py's new
multi-floor endpoint calls instead.
"""

from __future__ import annotations

import heapq
import math
from dataclasses import dataclass, field
from typing import Dict, FrozenSet, List, Optional, Tuple

from constants.route_point_types import is_destination_capable_point_type
from logic.instruction_generator import resolve_display_name, resolve_localized_display_name
from logic.multi_floor_graph import MultiFloorGraph, build_multi_floor_graph
from models.route_point_model import RoutePoint
from models.vertical_connector_model import VerticalConnector


@dataclass
class PathStep:
    point_id: str
    edge_ref: Optional[object] = None  # GraphEdgeRef used to REACH this point (None for the start point)


@dataclass
class MultiFloorRouteResult:
    point_ids: List[str]
    total_distance_meters: float
    total_estimated_time_seconds: float
    segments: List[dict]
    is_accessible: bool


NO_TRANSITION_MESSAGE_TEMPLATE = (
    "No configured route between Floor {from_floor} and Floor {to_floor}. "
    "Add or activate stairs/elevator connections."
)


class RoomTransitBlockedError(Exception):
    """
    Raised by calculate_multi_floor_route when the ONLY reason no route
    could be found is that a destination-capable RoutePoint (room/store —
    see constants/route_point_types.py) would have had to be used as an
    intermediate transit node, and Section 3's "a room/store point must
    not be used as an intermediate transit point" rule correctly refused
    to route through it.

    This is a graph-topology/admin-configuration issue (a missing direct
    corridor connection), never a "no route exists at all" situation — the
    caller (routes/navigation_routes.py) turns this into a clear,
    distinguishable admin/debug-facing error rather than either silently
    routing through the room or returning an indistinguishable generic
    "no route found".
    """

    def __init__(self, blocking_point_ids: List[str]):
        self.blocking_point_ids = blocking_point_ids
        super().__init__(
            "Route blocked: a destination-only room/store point would "
            "have to be used as an intermediate transit point. "
            f"Candidate blocking point id(s): {blocking_point_ids}."
        )


# Bug-fix round — "same physical spot" tolerance used ONLY to recognize
# a destination-capable node that coincides with the actual selected
# start/end point (see _suppress_intermediate_destination_nodes below).
# Deliberately mirrors services/point_dedup_service.py's own
# DEFAULT_COORDINATE_TOLERANCE_PX (6.0 map-image pixels) so "the same
# place" means the same thing everywhere in this codebase, without this
# logic-layer module importing from the services layer.
_SAME_LOCATION_TOLERANCE_PX = 6.0


def _suppress_intermediate_destination_nodes(
    graph: MultiFloorGraph, start_id: str, end_id: str
) -> None:
    """
    Section 3 — "a room/store point may be used when it is the selected
    start point; may be used when it is the selected destination; must
    not be used as an intermediate transit point between other
    locations."

    This never deletes any RoutePoint/RouteEdge data — `graph` is a
    fresh, per-request in-memory structure built by build_multi_floor_graph
    for this call only, and this function only prunes the OUTGOING
    adjacency of a non-start/end destination-capable node before the
    search runs. Dijkstra itself (below) is completely unmodified: it can
    still reach such a node (e.g. confirm it's connected at all), it can
    just never continue PAST it to reach a third point, which is exactly
    "terminal, not transit" semantics. Applied here (a discrete
    pre-Dijkstra filtering step), never inside build_multi_floor_graph
    itself, so this never affects the admin graph-validation endpoint or
    any other consumer of that shared graph builder — only this specific
    end-user route calculation.

    Bug-fix round: `start_id`/`end_id` are normalized to plain `str` here
    (canonical format — see graph.nodes' own keys, which are always
    `str(RoutePoint.id)` per multi_floor_graph.py) so a caller that
    happens to pass a PydanticObjectId or other non-str id type is never
    silently mismatched against the graph's own string keys.

    Also never suppresses a destination-capable node that PHYSICALLY
    coincides (within _SAME_LOCATION_TOLERANCE_PX, on the same map) with
    the real start or end node — a Room/Store point placed exactly on top
    of another existing destination-capable point (e.g. a Room attached
    to a pre-existing "store" RoutePoint at the same spot, auto-connected
    to it during placement) is the SAME physical destination as far as a
    user is concerned, never an "unrelated" one, even though it has a
    different RoutePoint id. Only ever widens the start/end exemption
    itself — a destination-capable node anywhere else on the map, even a
    few pixels from an UNRELATED spot, is still fully suppressed exactly
    as before.
    """

    start_id = str(start_id)
    end_id = str(end_id)

    anchor_nodes = [
        graph.nodes[anchor_id]
        for anchor_id in (start_id, end_id)
        if anchor_id in graph.nodes
    ]

    def _coincides_with_an_anchor(node) -> bool:
        for anchor in anchor_nodes:
            if anchor.map_id != node.map_id:
                continue
            if math.hypot(anchor.x - node.x, anchor.y - node.y) <= _SAME_LOCATION_TOLERANCE_PX:
                return True
        return False

    for node_id, node in graph.nodes.items():
        if node_id in (start_id, end_id):
            continue
        if not is_destination_capable_point_type(node.point_type):
            continue
        if _coincides_with_an_anchor(node):
            continue
        # Nested-room navigation (Section 13 of the Approved Semantic
        # Analysis -> Automatic Destinations spec): a destination-capable
        # node an admin has EXPLICITLY approved as a pass-through ("outer")
        # room is never suppressed as an intermediate node — this is the
        # one and only exemption beyond start/end/same-location-as-anchor
        # above. An ordinary Room/Store (allow_transit_through False, the
        # default for every node) is suppressed exactly as before; this
        # never uses coordinate coincidence to authorize transit, only the
        # explicit per-node flag.
        if node.allow_transit_through:
            continue
        graph.adjacency[node_id] = []


def _dijkstra(
    graph: MultiFloorGraph, start_id: str, end_id: str
) -> Optional[Tuple[List[str], List]]:
    if start_id not in graph.nodes or end_id not in graph.nodes:
        return None

    distances: Dict[str, float] = {start_id: 0.0}
    previous: Dict[str, Tuple[str, object]] = {}
    visited = set()
    queue: List[Tuple[float, str]] = [(0.0, start_id)]

    while queue:
        current_dist, current_id = heapq.heappop(queue)

        if current_id in visited:
            continue
        visited.add(current_id)

        if current_id == end_id:
            break

        for edge_ref in graph.adjacency.get(current_id, []):
            neighbor_id = edge_ref.to_node_id
            new_dist = current_dist + edge_ref.weight

            if neighbor_id not in distances or new_dist < distances[neighbor_id]:
                distances[neighbor_id] = new_dist
                previous[neighbor_id] = (current_id, edge_ref)
                heapq.heappush(queue, (new_dist, neighbor_id))

    if end_id not in distances:
        return None

    point_ids = [end_id]
    edges_used = []
    current = end_id

    while current != start_id:
        prev_id, edge_ref = previous[current]
        point_ids.append(prev_id)
        edges_used.append(edge_ref)
        current = prev_id

    point_ids.reverse()
    edges_used.reverse()

    return point_ids, edges_used


async def _connector_name(connector_id: Optional[str]) -> Optional[str]:
    if not connector_id:
        return None
    try:
        connector = await VerticalConnector.get(connector_id)
    except Exception:
        connector = None
    return connector.name if connector else None


def _floor_label_for_map(graph: MultiFloorGraph, map_id: str) -> Optional[str]:
    map_item = graph.maps_by_id.get(map_id)
    return map_item.floor_label if map_item else None


async def _build_segments(
    graph: MultiFloorGraph, point_ids: List[str], edges_used: List, lang: str = "en"
) -> List[dict]:
    segments: List[dict] = []

    if not point_ids:
        return segments

    current_floor_points: List[str] = [point_ids[0]]

    async def _flush_floor_segment(points: List[str]):
        if not points:
            return
        first_node = graph.nodes[points[0]]
        map_item = graph.maps_by_id.get(first_node.map_id)

        distance = 0.0
        for i in range(len(points) - 1):
            for edge_ref in graph.adjacency.get(points[i], []):
                if edge_ref.to_node_id == points[i + 1] and edge_ref.edge.connector_id is None:
                    distance += float(edge_ref.edge.distance or 0.0)
                    break

        segments.append(
            {
                "segment_type": "floor",
                "floor": first_node.floor,
                "floor_label": map_item.floor_label if map_item else None,
                "map_id": first_node.map_id,
                "distance_meters": round(distance, 2),
                "point_ids": list(points),
                "coordinates": [
                    {
                        "point_id": pid,
                        "x": graph.nodes[pid].x,
                        "y": graph.nodes[pid].y,
                        "name": resolve_localized_display_name(
                            graph.nodes[pid].name,
                            display_name=graph.nodes[pid].display_name,
                            display_name_en=graph.nodes[pid].display_name_en,
                            display_name_ar=graph.nodes[pid].display_name_ar,
                            display_name_he=graph.nodes[pid].display_name_he,
                            is_auto_generated=graph.nodes[pid].is_auto_generated,
                            lang=lang,
                        ),
                        "point_type": graph.nodes[pid].point_type,
                        # Nested-room navigation (Section 14 of the
                        # Approved Semantic Analysis -> Automatic
                        # Destinations spec) — lets the instruction
                        # generator recognize a real, approved pass-through
                        # room in the actual returned route and phrase it
                        # truthfully, without needing a second lookup.
                        "allow_transit_through": graph.nodes[pid].allow_transit_through,
                    }
                    for pid in points
                ],
            }
        )

    for i, edge_ref in enumerate(edges_used):
        to_point_id = point_ids[i + 1]

        if edge_ref.edge.connector_id is not None:
            # Close the floor segment ending at the connector's FROM stop.
            await _flush_floor_segment(current_floor_points)

            from_node = graph.nodes[point_ids[i]]
            to_node = graph.nodes[to_point_id]
            connector_name = await _connector_name(edge_ref.edge.connector_id)

            segments.append(
                {
                    "segment_type": "transition",
                    "transition_type": edge_ref.edge.edge_type,
                    "connector_id": edge_ref.edge.connector_id,
                    "connector_name": connector_name,
                    "from_floor": from_node.floor,
                    "to_floor": to_node.floor,
                    "from_map_id": from_node.map_id,
                    "to_map_id": to_node.map_id,
                    "distance_meters": round(float(edge_ref.edge.distance or 0.0), 2),
                    "estimated_time_seconds": round(edge_ref.time_seconds, 2),
                    "is_accessible": bool(edge_ref.edge.is_accessible),
                }
            )

            current_floor_points = [to_point_id]
        else:
            current_floor_points.append(to_point_id)

    await _flush_floor_segment(current_floor_points)

    return segments


async def calculate_multi_floor_route(
    *,
    map_ids: List[str],
    start_point_id: str,
    end_point_id: str,
    mode: str = "shortest",
    accessible_only: bool = False,
    avoid_edge_types: Optional[FrozenSet[str]] = None,
    lang: str = "en",
) -> Optional[MultiFloorRouteResult]:
    # Canonical id format for every comparison below — see
    # _suppress_intermediate_destination_nodes's docstring (graph.nodes
    # keys are always plain str(RoutePoint.id)).
    start_point_id = str(start_point_id)
    end_point_id = str(end_point_id)

    graph = await build_multi_floor_graph(
        map_ids,
        mode=mode,
        accessible_only=accessible_only,
        avoid_edge_types=avoid_edge_types,
    )

    # Section 3 — never let a room/store node act as a bridge between two
    # OTHER points for this route calculation. Dijkstra itself (below) is
    # untouched; only the graph's adjacency is pruned first.
    _suppress_intermediate_destination_nodes(graph, start_point_id, end_point_id)

    result = _dijkstra(graph, start_point_id, end_point_id)
    if result is None:
        # Distinguish "genuinely no route" from "blocked only because a
        # room/store point would have had to act as an intermediate
        # transit node" (Section 3: "return a clear admin/debug
        # indication rather than silently routing through the Room").
        # Rebuilds the graph WITHOUT the suppression step above — a fresh
        # build rather than mutating a copy, since this only ever runs on
        # the rare failure path and keeps this function's normal-path cost
        # unchanged.
        unfiltered_graph = await build_multi_floor_graph(
            map_ids,
            mode=mode,
            accessible_only=accessible_only,
            avoid_edge_types=avoid_edge_types,
        )
        unfiltered_result = _dijkstra(unfiltered_graph, start_point_id, end_point_id)
        if unfiltered_result is not None:
            unfiltered_anchor_nodes = [
                unfiltered_graph.nodes[anchor_id]
                for anchor_id in (start_point_id, end_point_id)
                if anchor_id in unfiltered_graph.nodes
            ]

            def _coincides_with_an_unfiltered_anchor(node) -> bool:
                for anchor in unfiltered_anchor_nodes:
                    if anchor.map_id != node.map_id:
                        continue
                    if (
                        math.hypot(anchor.x - node.x, anchor.y - node.y)
                        <= _SAME_LOCATION_TOLERANCE_PX
                    ):
                        return True
                return False

            blocking_point_ids = [
                pid
                for pid in unfiltered_result[0]
                if pid not in (start_point_id, end_point_id)
                and is_destination_capable_point_type(
                    unfiltered_graph.nodes[pid].point_type
                )
                and not _coincides_with_an_unfiltered_anchor(unfiltered_graph.nodes[pid])
            ]
            if blocking_point_ids:
                raise RoomTransitBlockedError(blocking_point_ids)
        return None

    point_ids, edges_used = result

    total_distance = sum(float(e.edge.distance or 0.0) for e in edges_used)
    total_time = sum(e.time_seconds for e in edges_used)

    segments = await _build_segments(graph, point_ids, edges_used, lang=lang)

    is_accessible = all(
        bool(e.edge.is_accessible) for e in edges_used
    ) if edges_used else True

    return MultiFloorRouteResult(
        point_ids=point_ids,
        total_distance_meters=round(total_distance, 2),
        total_estimated_time_seconds=round(total_time, 2),
        segments=segments,
        is_accessible=is_accessible,
    )
