"""
Centralized routing cost model (PHASE 7).

Every place that needs to know "how much does this edge cost" for a given
optimization mode imports from here, instead of re-deriving its own
formula — a single, auditable place for the shortest/fastest/accessible
cost rules so they can never quietly drift apart between, say, the
same-floor path and the multi-floor path.

Average walking speed for same-floor time estimates: ~1.3 m/s (78 m/min),
matching frontend/src/utils/routeHelpers.js's existing
`estimateTimeFromDistance` (meters / 80 ≈ minutes, i.e. ~1.33 m/s) so a
same-floor walking-time estimate is consistent whether it's computed here
or on the client.
"""

from __future__ import annotations

from typing import Optional, FrozenSet

WALKING_SPEED_METERS_PER_SECOND = 1.3

OPTIMIZATION_MODES = ("shortest", "fastest", "accessible")


def estimate_walking_seconds(distance_meters: float) -> float:
    if not distance_meters or distance_meters <= 0:
        return 0.0
    return distance_meters / WALKING_SPEED_METERS_PER_SECOND


def edge_time_seconds(edge) -> float:
    """
    The real-world time cost of traversing one RouteEdge, regardless of
    optimization mode. A connector transition edge (edge.connector_id set,
    or edge.estimated_time_seconds explicitly stored) uses its own stored
    cost — a same-floor walkway edge falls back to a walking-speed
    estimate from its distance.
    """

    if edge.estimated_time_seconds is not None:
        return float(edge.estimated_time_seconds)

    return estimate_walking_seconds(float(edge.distance or 0.0))


def edge_routing_weight(
    edge,
    mode: str = "shortest",
) -> float:
    """
    The scalar weight Dijkstra actually minimizes for this edge, given the
    requested optimization mode:
      - "shortest"/"accessible": primarily physical distance_meters.
      - "fastest": primarily estimated_time_seconds.
    Accessibility FILTERING (excluding inaccessible edges entirely) is a
    separate concern handled by the graph builder (see
    logic/multi_floor_graph.py) — this function only decides the weight of
    an edge that has already been allowed into the graph.
    """

    if mode == "fastest":
        return edge_time_seconds(edge)

    # "shortest" and "accessible" both minimize physical distance among
    # the edges that are allowed to be used; accessible-mode's real
    # difference from shortest-mode is which edges are allowed in the
    # graph at all (see is_edge_usable below), not a different weight
    # formula for the edges that remain.
    return float(edge.distance or 0.0)


def is_edge_usable(
    edge,
    *,
    accessible_only: bool,
    avoid_edge_types: Optional[FrozenSet[str]] = None,
) -> bool:
    """
    True when this edge may be used at all for the current request.
    `accessible_only=False` (shortest/fastest modes) allows every active
    edge regardless of its own is_accessible flag — a non-accessible
    stairs edge is a perfectly normal, usable part of the graph for a
    user who didn't ask for wheelchair-accessible routing. This is
    deliberately DIFFERENT from the legacy same-floor
    logic/route_calculator.py, which unconditionally drops every
    is_accessible=False edge regardless of mode; that legacy behavior is
    left completely untouched for its own existing endpoint (see
    routes/navigation_routes.py's original /api/navigation/route), but a
    new cost-mode-aware graph must not inherit that unconditional
    exclusion, or "fastest" could never legitimately choose stairs.

    `avoid_edge_types` (PHASE 14's "avoid stairs / avoid escalators / prefer
    elevators" end-user preferences) is a separate, independent hard
    exclusion on top of the accessibility filter — applies to same-floor
    edges too (e.g. a physical in-floor staircase drawn with
    edge_type="stairs"), not just cross-floor connector transitions.
    """

    if not edge.is_active:
        return False

    if accessible_only and not edge.is_accessible:
        return False

    if avoid_edge_types and edge.edge_type in avoid_edge_types:
        return False

    return True
