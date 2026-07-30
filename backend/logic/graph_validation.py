"""
Admin multi-floor graph validation (PHASE 15).

Given one MapGroup, reports every structural problem that would make
cross-floor (or even same-floor) navigation silently wrong or impossible:
floors with no points, disconnected same-floor sub-graphs, connector stops
that never actually reach their local corridor, floors unreachable from
the building's main entrance, destinations unreachable from any
LocationCode start point, uncalibrated maps, inactive connectors, and
transition edges that reference something invalid (missing connector,
same-floor "transition", missing endpoint).

This module never writes anything — it is a pure read + report. It is
intentionally NOT the same code path as the actual router
(logic/multi_floor_routing.py); it re-derives reachability directly from
RoutePoint/RouteEdge documents so a bug in the router itself wouldn't also
hide itself from validation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from models.location_code_model import LocationCode
from models.map_model import Map
from models.map_group_model import MapGroup
from models.room_model import Room
from models.route_edge_model import RouteEdge
from models.route_point_model import RoutePoint
from models.vertical_connector_model import VerticalConnector


@dataclass
class ValidationIssue:
    category: str
    message: str
    floor: Optional[int] = None
    map_id: Optional[str] = None
    connector_id: Optional[str] = None


@dataclass
class ConnectorSummary:
    id: str
    name: str
    connector_type: str
    is_active: bool
    is_accessible: bool
    serves_floors: List[int]
    is_fully_connected: bool


@dataclass
class GraphValidationResult:
    map_group_id: str
    floor_count: int
    ready: bool
    issues: List[ValidationIssue] = field(default_factory=list)
    connectors: List[ConnectorSummary] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "map_group_id": self.map_group_id,
            "floor_count": self.floor_count,
            "ready": self.ready,
            "issue_count": len(self.issues),
            "issues": [
                {
                    "category": i.category,
                    "message": i.message,
                    "floor": i.floor,
                    "map_id": i.map_id,
                    "connector_id": i.connector_id,
                }
                for i in self.issues
            ],
            "connectors": [
                {
                    "id": c.id,
                    "name": c.name,
                    "connector_type": c.connector_type,
                    "is_active": c.is_active,
                    "is_accessible": c.is_accessible,
                    "serves_floors": c.serves_floors,
                    "is_fully_connected": c.is_fully_connected,
                }
                for c in self.connectors
            ],
        }


def _connected_components(
    point_ids: Set[str], edges: List[RouteEdge]
) -> List[Set[str]]:
    """
    Undirected connectivity (a component check cares about physical
    reachability of the drawn corridor shape, not one-way restrictions) —
    ignores edges whose endpoints aren't in `point_ids` (i.e. transition
    edges leaving this floor are not followed here; this is a same-floor
    check only).
    """

    adjacency: Dict[str, Set[str]] = {pid: set() for pid in point_ids}
    for edge in edges:
        if edge.from_point_id in adjacency and edge.to_point_id in adjacency:
            adjacency[edge.from_point_id].add(edge.to_point_id)
            adjacency[edge.to_point_id].add(edge.from_point_id)

    visited: Set[str] = set()
    components: List[Set[str]] = []

    for start in point_ids:
        if start in visited:
            continue
        stack = [start]
        component: Set[str] = set()
        while stack:
            current = stack.pop()
            if current in component:
                continue
            component.add(current)
            stack.extend(adjacency.get(current, set()) - component)
        visited |= component
        components.append(component)

    return components


def _bfs_reachable(
    start_ids: Set[str], adjacency: Dict[str, Set[str]]
) -> Set[str]:
    visited: Set[str] = set()
    stack = list(start_ids)
    while stack:
        current = stack.pop()
        if current in visited:
            continue
        visited.add(current)
        stack.extend(adjacency.get(current, set()) - visited)
    return visited


async def validate_multi_floor_navigation(group: MapGroup) -> GraphValidationResult:
    group_id = str(group.id)
    issues: List[ValidationIssue] = []

    floor_maps = await Map.find(Map.map_group_id == group_id).to_list()
    floor_maps.sort(key=lambda m: (m.floor is None, m.floor if m.floor is not None else 0))
    map_ids = [str(m.id) for m in floor_maps]

    result = GraphValidationResult(
        map_group_id=group_id, floor_count=len(floor_maps), ready=True
    )

    if not floor_maps:
        issues.append(
            ValidationIssue(
                category="floors",
                message="This map group has no floor maps yet.",
            )
        )
        result.issues = issues
        result.ready = False
        return result

    all_points = await RoutePoint.find(
        {"map_id": {"$in": map_ids}, "is_active": True}
    ).to_list()
    points_by_map: Dict[str, List[RoutePoint]] = {m: [] for m in map_ids}
    for p in all_points:
        points_by_map.setdefault(p.map_id, []).append(p)

    all_edges = await RouteEdge.find(
        {
            "$or": [
                {"map_id": {"$in": map_ids}},
                {"to_map_id": {"$in": map_ids}},
            ],
            "is_active": True,
        }
    ).to_list()

    # --- Uncalibrated maps -------------------------------------------------
    for m in floor_maps:
        if not m.is_calibrated:
            issues.append(
                ValidationIssue(
                    category="calibration",
                    message=f"Floor {m.floor} ({m.floor_label or m.title}) map is uncalibrated — distances/times on this floor are not trustworthy.",
                    floor=m.floor,
                    map_id=str(m.id),
                )
            )

    # --- Floors with no RoutePoints -----------------------------------------
    for m in floor_maps:
        if not points_by_map.get(str(m.id)):
            issues.append(
                ValidationIssue(
                    category="floors",
                    message=f"Floor {m.floor} ({m.floor_label or m.title}) has no route points.",
                    floor=m.floor,
                    map_id=str(m.id),
                )
            )

    # --- Same-floor disconnected components ---------------------------------
    same_floor_edges_by_map: Dict[str, List[RouteEdge]] = {m: [] for m in map_ids}
    for edge in all_edges:
        if edge.connector_id is None and edge.to_map_id is None:
            same_floor_edges_by_map.setdefault(edge.map_id, []).append(edge)

    for m in floor_maps:
        map_id = str(m.id)
        pts = points_by_map.get(map_id, [])
        if len(pts) < 2:
            continue
        point_ids = {str(p.id) for p in pts}
        components = _connected_components(point_ids, same_floor_edges_by_map.get(map_id, []))
        if len(components) > 1:
            issues.append(
                ValidationIssue(
                    category="connectivity",
                    message=(
                        f"Floor {m.floor} ({m.floor_label or m.title}) has "
                        f"{len(components)} disconnected groups of route points "
                        "that cannot reach each other on this floor."
                    ),
                    floor=m.floor,
                    map_id=map_id,
                )
            )

    # --- Connectors -----------------------------------------------------------
    connectors = await VerticalConnector.find(
        VerticalConnector.map_group_id == group_id
    ).to_list()

    stops_by_connector: Dict[str, List[RoutePoint]] = {}
    for p in all_points:
        if p.connector_id:
            stops_by_connector.setdefault(p.connector_id, []).append(p)

    walkway_edges_by_point: Dict[str, bool] = {}
    for edge in all_edges:
        if edge.edge_type == "walkway" and edge.connector_id is None:
            walkway_edges_by_point[edge.from_point_id] = True
            walkway_edges_by_point[edge.to_point_id] = True

    for connector in connectors:
        stops = stops_by_connector.get(str(connector.id), [])
        stops.sort(key=lambda p: (p.floor is None, p.floor if p.floor is not None else 0))
        serves_floors = [p.floor for p in stops if p.floor is not None]

        if not connector.is_active:
            issues.append(
                ValidationIssue(
                    category="connectors",
                    message=f"{connector.name} ({connector.connector_type}) is inactive and cannot currently be routed through.",
                    connector_id=str(connector.id),
                )
            )

        if len(stops) < 2:
            issues.append(
                ValidationIssue(
                    category="connectors",
                    message=f"{connector.name} ({connector.connector_type}) has fewer than 2 floor stops and cannot connect any floors yet.",
                    connector_id=str(connector.id),
                )
            )

        fully_connected = len(stops) >= 2
        for stop in stops:
            if not walkway_edges_by_point.get(str(stop.id)):
                fully_connected = False
                issues.append(
                    ValidationIssue(
                        category="connector_connectivity",
                        message=(
                            f"{connector.name} stop on Floor {stop.floor} is not "
                            "connected to that floor's corridor graph."
                        ),
                        floor=stop.floor,
                        map_id=stop.map_id,
                        connector_id=str(connector.id),
                    )
                )

        result.connectors.append(
            ConnectorSummary(
                id=str(connector.id),
                name=connector.name,
                connector_type=connector.connector_type,
                is_active=connector.is_active,
                is_accessible=connector.is_accessible,
                serves_floors=sorted(serves_floors),
                is_fully_connected=fully_connected,
            )
        )

    # --- Invalid transition edge records ---------------------------------------
    connector_ids = {str(c.id) for c in connectors}
    point_ids_by_id = {str(p.id): p for p in all_points}

    for edge in all_edges:
        if edge.connector_id is None:
            continue

        if edge.connector_id not in connector_ids:
            issues.append(
                ValidationIssue(
                    category="transitions",
                    message=f"A transition edge references connector {edge.connector_id}, which does not exist in this map group.",
                    map_id=edge.map_id,
                )
            )
            continue

        from_point = point_ids_by_id.get(edge.from_point_id)
        to_point = point_ids_by_id.get(edge.to_point_id)

        if from_point is None or to_point is None:
            issues.append(
                ValidationIssue(
                    category="transitions",
                    message="A transition edge references a route point that no longer exists.",
                    connector_id=edge.connector_id,
                )
            )
            continue

        if from_point.map_id == to_point.map_id:
            issues.append(
                ValidationIssue(
                    category="transitions",
                    message="A transition edge connects two points on the same floor map, which is invalid for a vertical connector.",
                    connector_id=edge.connector_id,
                    map_id=from_point.map_id,
                )
            )

    # --- Reachability from the main entrance -----------------------------------
    # "Main entrance" = an entrance-type point on the lowest floor of this
    # group, if one exists. Reachability here follows the SAME usable-edge
    # rules a real "shortest" mode route would (no accessibility filter),
    # since this check is about basic structural connectivity, not any one
    # optimization mode.
    adjacency: Dict[str, Set[str]] = {str(p.id): set() for p in all_points}
    for edge in all_edges:
        if edge.from_point_id not in adjacency or edge.to_point_id not in adjacency:
            continue
        adjacency[edge.from_point_id].add(edge.to_point_id)
        if edge.is_bidirectional:
            adjacency[edge.to_point_id].add(edge.from_point_id)

    lowest_floor_map = floor_maps[0]
    entrance_candidates = [
        p
        for p in points_by_map.get(str(lowest_floor_map.id), [])
        if (p.point_type or "").lower() == "entrance"
    ]

    reachable: Set[str] = set()
    if entrance_candidates:
        start_ids = {str(p.id) for p in entrance_candidates}
        reachable = _bfs_reachable(start_ids, adjacency)

        for m in floor_maps:
            floor_point_ids = {str(p.id) for p in points_by_map.get(str(m.id), [])}
            if floor_point_ids and not (floor_point_ids & reachable):
                issues.append(
                    ValidationIssue(
                        category="reachability",
                        message=(
                            f"Floor {m.floor} ({m.floor_label or m.title}) is not "
                            "reachable from the main entrance."
                        ),
                        floor=m.floor,
                        map_id=str(m.id),
                    )
                )
    else:
        issues.append(
            ValidationIssue(
                category="reachability",
                message=(
                    f"No 'entrance' point found on the lowest floor "
                    f"(Floor {lowest_floor_map.floor}) — reachability from a "
                    "main entrance cannot be checked."
                ),
                floor=lowest_floor_map.floor,
                map_id=str(lowest_floor_map.id),
            )
        )

    # --- Destinations unreachable from any LocationCode start ------------------
    location_codes = await LocationCode.find(
        {"building_id": group.building_id, "is_active": True}
    ).to_list()
    relevant_codes = [lc for lc in location_codes if lc.map_id in map_ids]

    if relevant_codes:
        start_ids = {lc.route_point_id for lc in relevant_codes if lc.route_point_id in adjacency}
        reachable_from_codes = _bfs_reachable(start_ids, adjacency) if start_ids else set()

        rooms = await Room.find(
            {
                "building_id": group.building_id,
                "is_active": True,
                "route_point_id": {"$ne": None},
            }
        ).to_list()

        for room in rooms:
            if room.map_id not in map_ids:
                continue
            if room.route_point_id and room.route_point_id not in reachable_from_codes:
                issues.append(
                    ValidationIssue(
                        category="reachability",
                        message=f"{room.name_en} cannot be reached from any Location Code start point.",
                        floor=room.floor,
                        map_id=room.map_id,
                    )
                )

    result.issues = issues
    result.ready = len(issues) == 0
    return result
