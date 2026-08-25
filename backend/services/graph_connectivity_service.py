"""
The single authoritative answer to "can this destination actually be
reached?".

WHY THIS MODULE EXISTS
----------------------
Three different definitions of "connected" had grown up independently, and
they disagreed on real data — Auto Connect reported a room as already
connected while the Rooms page showed the same room as having no valid
graph connection:

  A  routes/room_routes.compute_room_navigability
     any active RouteEdge touching the point, ANY edge_type, ANY neighbour
     type, and with NO map filter at all.

  B  services/room_location_code_service.route_point_is_connected_to_graph
     the same test, but restricted to the point's own map.

  C  services/auto_connect_destinations_service's has_valid_transit_edge
     an active WALKWAY edge to a hallway/junction point on the same map.

C is the only one that means what an admin thinks it means, because A and
B are both satisfied by a stale Room-to-Room edge — exactly the legacy data
this release also has to repair. But C alone would call a legitimately
nested inner room disconnected, since that room reaches the corridor
THROUGH its approved parent rather than directly.

So the rule below is C plus the nested exception, in one place, used by
every caller. Nothing here writes; nothing here changes the graph.

WHAT COUNTS AS CONNECTED
------------------------
A destination RoutePoint is connected when at least one of:

  1. an active walkway RouteEdge on its own map joins it to a
     hallway/junction point (the ordinary case);

  2. an active walkway RouteEdge joins it to a destination point that is
     its EXPLICIT approved nested parent — Room.parent_room_id set and the
     parent's RoutePoint.allow_transit_through True — and that parent is
     itself connected, transitively. This is what makes
     corridor -> Room 1 -> Room 1.1 -> Room 1.1.1 legitimate;

  3. an active walkway RouteEdge joins it to a destination point at the
     SAME physical location (within SAME_PHYSICAL_LOCATION_TOLERANCE_PX).
     Two records of one place, not a route through an unrelated room —
     logic/multi_floor_routing.py already treats such a pair this way, and
     services/graph_connection_service.py allows exactly this link.

Anything else — including a walkway edge to an unrelated room — is NOT
connectivity, and is reported as such so the legacy repair path can find
it.
"""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Dict, Iterable, List, Optional, Set, Tuple

from beanie import PydanticObjectId

from constants.route_point_types import (
    DESTINATION_CAPABLE_POINT_TYPES,
    TRANSIT_CANDIDATE_POINT_TYPES,
)
from models.room_model import Room
from models.route_edge_model import RouteEdge
from models.route_point_model import RoutePoint
from services.graph_connection_service import (
    SAME_PHYSICAL_LOCATION_TOLERANCE_PX,
)


# How deep a nested chain may be followed before giving up. Real buildings
# nest two or three levels (room -> suite -> wing); this only exists so a
# cyclic parent_room_id in legacy data can never spin forever.
MAX_NESTED_PARENT_DEPTH = 8


# Reasons a destination is not connected. Stable strings — the admin UI and
# the tests both match on them.
REASON_NO_POINT = "missing_route_point"
REASON_POINT_NOT_FOUND = "route_point_not_found"
REASON_POINT_INACTIVE = "inactive_route_point"
REASON_DESTINATION_INACTIVE = "inactive_destination"
REASON_DISCONNECTED = "disconnected_from_graph"
# Has edges, but none of them is a legitimate route to the walkable graph —
# e.g. only a stale Room-to-Room edge. Deliberately distinct from
# REASON_DISCONNECTED so the admin can tell "nothing attached" apart from
# "attached to the wrong thing".
REASON_ONLY_INVALID_EDGES = "only_invalid_edges"


class FloorGraphIndex:
    """
    Everything needed to answer connectivity questions for ONE map, read
    once.

    Built per map rather than per point on purpose: the Rooms page, the QR
    issuer and Auto Connect all ask about every room on a floor at once,
    and doing it per point was N queries per screen.
    """

    def __init__(
        self,
        map_id: str,
        points: Iterable[RoutePoint],
        edges: Iterable[RouteEdge],
        rooms: Iterable[Room],
    ) -> None:
        self.map_id = map_id
        self.points_by_id: Dict[str, RoutePoint] = {
            str(p.id): p for p in points
        }
        self.edges: List[RouteEdge] = [
            e for e in edges if e.is_active and e.edge_type == "walkway"
        ]

        self.transit_ids: Set[str] = {
            pid
            for pid, p in self.points_by_id.items()
            if p.point_type in TRANSIT_CANDIDATE_POINT_TYPES
            and p.connector_id is None
        }

        # A vertical-connector stop is a legitimate member of its floor's
        # walkable graph even though its point_type is stairs/elevator.
        self.connector_stop_ids: Set[str] = {
            pid for pid, p in self.points_by_id.items() if p.connector_id
        }

        self.rooms_by_route_point_id: Dict[str, Room] = {
            r.route_point_id: r for r in rooms if r.route_point_id
        }
        self.rooms_by_id: Dict[str, Room] = {str(r.id): r for r in rooms}

        self.neighbours: Dict[str, Set[str]] = defaultdict(set)
        for edge in self.edges:
            self.neighbours[edge.from_point_id].add(edge.to_point_id)
            self.neighbours[edge.to_point_id].add(edge.from_point_id)

    # ── membership ────────────────────────────────────────────────────

    def is_walkable_graph_member(self, point_id: str) -> bool:
        """Hallway/junction points and vertical-connector stops are the
        graph a destination attaches TO. Rooms never are."""
        return point_id in self.transit_ids or point_id in self.connector_stop_ids

    def approved_parent_point_id(self, point_id: str) -> Optional[str]:
        """
        The RoutePoint id of this destination's EXPLICIT approved
        pass-through parent, or None.

        Both halves are required and neither is ever inferred:
        Room.parent_room_id must be set (only
        services/semantic_destination_service.py sets it, after admin
        confirmation) AND the parent's own point must have
        allow_transit_through.
        """
        room = self.rooms_by_route_point_id.get(point_id)
        if not room or not room.parent_room_id:
            return None

        parent_room = self.rooms_by_id.get(room.parent_room_id)
        if not parent_room or not parent_room.route_point_id:
            return None

        parent_point = self.points_by_id.get(parent_room.route_point_id)
        if (
            not parent_point
            or not parent_point.is_active
            or not parent_point.allow_transit_through
        ):
            return None

        return str(parent_point.id)

    def is_same_physical_location(self, a_id: str, b_id: str) -> bool:
        a = self.points_by_id.get(a_id)
        b = self.points_by_id.get(b_id)
        if not a or not b or a.floor != b.floor:
            return False
        return (
            math.hypot(float(b.x) - float(a.x), float(b.y) - float(a.y))
            <= SAME_PHYSICAL_LOCATION_TOLERANCE_PX
        )

    # ── the rule ──────────────────────────────────────────────────────

    def connection_state(self, point_id: str) -> Tuple[bool, Optional[str]]:
        """
        (is_connected, reason_when_not). See the module docstring for the
        three ways a destination can legitimately be connected.
        """

        point = self.points_by_id.get(point_id)
        if point is None:
            return False, REASON_POINT_NOT_FOUND
        if not point.is_active:
            return False, REASON_POINT_INACTIVE

        # A point that IS the walkable graph (a corridor node or a
        # connector stop) counts as connected once it has any walkway edge
        # to another graph member.
        if self.is_walkable_graph_member(point_id):
            for neighbour_id in self.neighbours.get(point_id, ()):  # noqa: SIM110
                if self.is_walkable_graph_member(neighbour_id):
                    return True, None
            return False, REASON_DISCONNECTED

        return self._destination_connection_state(point_id, set())

    def _destination_connection_state(
        self, point_id: str, visited: Set[str]
    ) -> Tuple[bool, Optional[str]]:
        if point_id in visited or len(visited) >= MAX_NESTED_PARENT_DEPTH:
            # Cyclic or absurdly deep parent chain in legacy data.
            return False, REASON_DISCONNECTED
        visited = visited | {point_id}

        neighbour_ids = self.neighbours.get(point_id, set())
        if not neighbour_ids:
            return False, REASON_DISCONNECTED

        approved_parent = self.approved_parent_point_id(point_id)
        has_any_neighbour = False

        for neighbour_id in neighbour_ids:
            has_any_neighbour = True

            # 1. Ordinary case — straight onto the corridor graph.
            if self.is_walkable_graph_member(neighbour_id):
                return True, None

            # 3. Two records of one physical place. Checked before the
            #    nested rule because it needs no relationship at all.
            if self.is_same_physical_location(point_id, neighbour_id):
                connected, _ = self._destination_connection_state(
                    neighbour_id, visited
                )
                if connected:
                    return True, None

            # 2. Explicit approved nested parent, followed transitively so
            #    a multi-level chain resolves.
            if approved_parent and neighbour_id == approved_parent:
                connected, _ = self._destination_connection_state(
                    neighbour_id, visited
                )
                if connected:
                    return True, None

        # It has edges, but none of them leads anywhere legitimate — this
        # is the stale Room-to-Room case, and saying so is what lets the
        # admin find it.
        return False, (
            REASON_ONLY_INVALID_EDGES if has_any_neighbour else REASON_DISCONNECTED
        )


async def load_floor_graph_index(map_id: str) -> FloorGraphIndex:
    """Three reads per map, never per point."""

    points = await RoutePoint.find(
        {"map_id": map_id, "is_active": True}
    ).to_list()
    edges = await RouteEdge.find({"map_id": map_id, "is_active": True}).to_list()
    rooms = await Room.find({"map_id": map_id}).to_list()

    return FloorGraphIndex(map_id, points, edges, rooms)


async def room_connection_state(room: Room) -> Tuple[bool, Optional[str]]:
    """
    Connectivity for ONE Room, resolved through its linked arrival point.

    Convenience wrapper for the single-room API responses. A caller
    rendering a whole floor should build a FloorGraphIndex once instead.
    """

    if not room.route_point_id:
        if not room.is_active:
            return False, REASON_DESTINATION_INACTIVE
        return False, REASON_NO_POINT

    try:
        point = await RoutePoint.get(PydanticObjectId(room.route_point_id))
    except Exception:  # noqa: BLE001 — a malformed id is a data problem
        point = None

    if point is not None and not point.is_active:
        return False, REASON_POINT_INACTIVE

    if not room.is_active:
        return False, REASON_DESTINATION_INACTIVE

    if point is None:
        return False, REASON_POINT_NOT_FOUND

    index = await load_floor_graph_index(point.map_id)
    return index.connection_state(str(point.id))


def is_destination_point_type(point: Optional[RoutePoint]) -> bool:
    return bool(point) and point.point_type in DESTINATION_CAPABLE_POINT_TYPES
