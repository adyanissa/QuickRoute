"""
Preview and safe repair of legacy invalid walkway edges.

WHY THIS EXISTS
---------------
Before the Auto Connect correction, graph_connection_service.auto_connect_point
had no point_type filter, so a newly created Room point wired itself to
whatever happened to be nearest — frequently another Room. The policy fix
stops NEW bad edges; it does nothing about the ones already in the
database, and those still produce the reported symptom:

    "The only path passes through a destination room/store point"

even on a floor whose corridor was drawn correctly.

WHAT IS INVALID
---------------
    room_to_room            an active walkway edge between two
                            destination-capable points that are neither an
                            approved nested pair NOR two records of one
                            physical location. Auto-repairable.

    stale_attachment        an active walkway edge from a destination to a
                            point that no longer exists or is inactive.
                            Auto-repairable.

    room_used_as_transit_bridge
                            an ordinary (non pass-through) destination with
                            walkway edges to TWO OR MORE separate walkable
                            graph members — the CORRIDOR -> ROOM -> CORRIDOR
                            shape. Reported, never auto-repaired: removing
                            either edge could sever the corridor itself, and
                            which one to keep is a judgement only the admin
                            can make from the drawing.

    only_invalid_edges      a destination whose every active edge is
                            invalid, so it is advertised nowhere and routes
                            nowhere. Informational; clearing its bad edges
                            is what fixes it.

WHAT IS EXPLICITLY NOT INVALID
------------------------------
  * an approved nested pair — Room.parent_room_id set AND the parent's
    RoutePoint.allow_transit_through True. Nesting is never inferred from
    proximity;
  * RouteEdge.access_relation == "nested" backed by a real parent/child
    relationship;
  * two destinations at the SAME physical location (within
    SAME_PHYSICAL_LOCATION_TOLERANCE_PX) — one place with two records,
    which logic/multi_floor_routing.py already treats as one node;
  * any Room -> hallway/junction/connector-stop attachment;
  * every non-walkway edge, and every vertical connector transition.

SAFETY
------
Preview is completely read-only. Apply DEACTIVATES (never deletes) only
the edges it was explicitly given, never touches the Room, its RoutePoint
or its LocationCode, and is scoped to one map. It is idempotent: an edge
already inactive is skipped, and reconnection goes through the shared
attachment service, which refuses to add an edge to a point that already
reaches the graph.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Dict, List, Optional, Set

from beanie import PydanticObjectId

from constants.route_point_types import DESTINATION_CAPABLE_POINT_TYPES
from models.map_model import Map
from models.room_model import Room
from models.route_edge_model import RouteEdge
from models.route_point_model import RoutePoint
from services.destination_attachment_service import (
    attach_point_to_corridor,
    load_corridor_floor_context_by_map_id,
)
from services.graph_connection_service import SAME_PHYSICAL_LOCATION_TOLERANCE_PX
from services.graph_connectivity_service import (
    REASON_ONLY_INVALID_EDGES,
    FloorGraphIndex,
)


FINDING_ROOM_TO_ROOM = "room_to_room"
FINDING_STALE_ATTACHMENT = "stale_attachment"
FINDING_TRANSIT_BRIDGE = "room_used_as_transit_bridge"
FINDING_ONLY_INVALID_EDGES = "only_invalid_edges"

# Findings this service is willing to repair automatically. A transit
# bridge is deliberately absent: cutting one of its two corridor edges can
# disconnect the corridor, so it is an admin decision.
AUTO_REPAIRABLE_FINDINGS = frozenset({FINDING_ROOM_TO_ROOM, FINDING_STALE_ATTACHMENT})

REPAIR_DESCRIPTION_SUFFIX = " [deactivated by legacy connection repair]"


def _point_label(point: Optional[RoutePoint]) -> str:
    if point is None:
        return "(missing point)"
    return point.display_name or point.name or str(point.id)


def _room_name_for_point(
    point_id: str, rooms_by_route_point_id: Dict[str, Room]
) -> Optional[str]:
    room = rooms_by_route_point_id.get(point_id)
    return room.name_en if room else None


def _is_approved_nested_pair(
    a_id: str, b_id: str, index: FloorGraphIndex
) -> bool:
    """True when one of the two points is the other's EXPLICIT approved
    pass-through parent. Both halves are required and neither is inferred:
    Room.parent_room_id must be set, and the parent's own RoutePoint must
    have allow_transit_through."""
    return (
        index.approved_parent_point_id(a_id) == b_id
        or index.approved_parent_point_id(b_id) == a_id
    )


def _is_same_physical_location(
    a: Optional[RoutePoint], b: Optional[RoutePoint]
) -> bool:
    if not a or not b or a.floor != b.floor:
        return False
    return (
        math.hypot(float(b.x) - float(a.x), float(b.y) - float(a.y))
        <= SAME_PHYSICAL_LOCATION_TOLERANCE_PX
    )


async def preview_legacy_edge_repair(map_id: str) -> dict:
    """
    Entirely read-only. Never inserts, updates or deletes anything.

    Scoped to ONE map — there is deliberately no global variant, because a
    destructive cleanup must never be able to reach a floor the admin is
    not looking at.
    """

    summary = {
        "map_id": map_id,
        "scanned_edges": 0,
        "scanned_destinations": 0,
        "invalid_edges": 0,
        "repairable_edges": 0,
        "needs_review": 0,
        "findings": [],
        "warnings": [],
    }

    try:
        map_item = await Map.get(PydanticObjectId(map_id))
    except Exception:  # noqa: BLE001 — malformed id is a data problem
        map_item = None

    if not map_item:
        summary["warnings"].append("Map not found.")
        return summary

    points = await RoutePoint.find({"map_id": map_id}).to_list()
    edges = await RouteEdge.find({"map_id": map_id, "is_active": True}).to_list()
    rooms = await Room.find({"map_id": map_id}).to_list()

    points_by_id: Dict[str, RoutePoint] = {str(p.id): p for p in points}
    active_points = [p for p in points if p.is_active]
    rooms_by_route_point_id: Dict[str, Room] = {
        r.route_point_id: r for r in rooms if r.route_point_id
    }

    index = FloorGraphIndex(map_id, active_points, edges, rooms)

    walkway_edges = [e for e in edges if e.edge_type == "walkway"]
    summary["scanned_edges"] = len(walkway_edges)
    summary["scanned_destinations"] = len(
        [
            p
            for p in active_points
            if p.point_type in DESTINATION_CAPABLE_POINT_TYPES
            and p.connector_id is None
        ]
    )

    invalid_edge_ids: Set[str] = set()

    # ── per-edge classification ───────────────────────────────────────
    for edge in walkway_edges:
        from_point = points_by_id.get(edge.from_point_id)
        to_point = points_by_id.get(edge.to_point_id)

        from_is_destination = (
            from_point is not None
            and from_point.point_type in DESTINATION_CAPABLE_POINT_TYPES
            and from_point.connector_id is None
        )
        to_is_destination = (
            to_point is not None
            and to_point.point_type in DESTINATION_CAPABLE_POINT_TYPES
            and to_point.connector_id is None
        )

        # A walkway edge from a destination to something that is gone or
        # deactivated routes nowhere and keeps the destination looking
        # "attached".
        missing_side = (from_point is None or not from_point.is_active) or (
            to_point is None or not to_point.is_active
        )
        if missing_side and (from_is_destination or to_is_destination):
            invalid_edge_ids.add(str(edge.id))
            summary["findings"].append(
                {
                    "kind": FINDING_STALE_ATTACHMENT,
                    "repairable": True,
                    "edge_id": str(edge.id),
                    "from_point_id": edge.from_point_id,
                    "to_point_id": edge.to_point_id,
                    "from_name": _point_label(from_point),
                    "to_name": _point_label(to_point),
                    "room_name": _room_name_for_point(
                        edge.from_point_id, rooms_by_route_point_id
                    )
                    or _room_name_for_point(
                        edge.to_point_id, rooms_by_route_point_id
                    ),
                    "detail": (
                        "This connection points at a route point that no "
                        "longer exists or has been deactivated."
                    ),
                }
            )
            continue

        if not (from_is_destination and to_is_destination):
            continue

        a_id, b_id = str(from_point.id), str(to_point.id)

        # PRESERVED: an approved nested parent/child pair.
        if _is_approved_nested_pair(a_id, b_id, index):
            continue

        # PRESERVED: an edge already marked as nested access AND backed by
        # a real relationship. The marking alone is not enough — an edge
        # mislabelled "nested" without the Room link is still invalid.
        if edge.access_relation == "nested" and _is_approved_nested_pair(
            a_id, b_id, index
        ):
            continue

        # PRESERVED: two records of one physical place.
        if _is_same_physical_location(from_point, to_point):
            continue

        invalid_edge_ids.add(str(edge.id))
        summary["findings"].append(
            {
                "kind": FINDING_ROOM_TO_ROOM,
                "repairable": True,
                "edge_id": str(edge.id),
                "from_point_id": a_id,
                "to_point_id": b_id,
                "from_name": _point_label(from_point),
                "to_name": _point_label(to_point),
                "room_name": _room_name_for_point(a_id, rooms_by_route_point_id),
                "detail": (
                    "Two unrelated destinations are wired directly to each "
                    "other. Normal rooms are destinations, never corridors."
                ),
            }
        )

    # ── per-destination classification ────────────────────────────────
    for point in active_points:
        if point.point_type not in DESTINATION_CAPABLE_POINT_TYPES:
            continue
        if point.connector_id is not None:
            continue

        point_id = str(point.id)

        # CORRIDOR -> ROOM -> CORRIDOR. Reported, never auto-repaired.
        if not point.allow_transit_through:
            graph_neighbours = [
                neighbour_id
                for neighbour_id in index.neighbours.get(point_id, ())
                if index.is_walkable_graph_member(neighbour_id)
            ]
            if len(graph_neighbours) >= 2:
                summary["findings"].append(
                    {
                        "kind": FINDING_TRANSIT_BRIDGE,
                        "repairable": False,
                        "edge_id": None,
                        "point_id": point_id,
                        "from_name": _point_label(point),
                        "to_name": None,
                        "room_name": _room_name_for_point(
                            point_id, rooms_by_route_point_id
                        ),
                        "graph_neighbour_ids": graph_neighbours,
                        "detail": (
                            "This ordinary room sits between two corridor "
                            "points, so the corridor may be relying on it to "
                            "stay connected. Draw a direct corridor link "
                            "between those points, then remove the room's "
                            "extra connection by hand."
                        ),
                    }
                )

        connected, reason = index.connection_state(point_id)
        if not connected and reason == REASON_ONLY_INVALID_EDGES:
            summary["findings"].append(
                {
                    "kind": FINDING_ONLY_INVALID_EDGES,
                    "repairable": False,
                    "edge_id": None,
                    "point_id": point_id,
                    "from_name": _point_label(point),
                    "to_name": None,
                    "room_name": _room_name_for_point(
                        point_id, rooms_by_route_point_id
                    ),
                    "detail": (
                        "Every connection this destination has is invalid, "
                        "so it cannot be routed to. Repairing those "
                        "connections will let it reattach to the corridor."
                    ),
                }
            )

    summary["invalid_edges"] = len(invalid_edge_ids)
    summary["repairable_edges"] = len(
        [f for f in summary["findings"] if f.get("repairable")]
    )
    summary["needs_review"] = len(
        [f for f in summary["findings"] if not f.get("repairable")]
    )

    return summary


async def apply_legacy_edge_repair(
    map_id: str, edge_ids: Optional[List[str]] = None
) -> dict:
    """
    Deactivate the confirmed-invalid edges and give every affected
    destination a chance to reattach properly.

    `edge_ids` is the explicit set the admin confirmed. Passing None
    repairs every auto-repairable finding the preview reports for this map
    — still scoped to the one map, and still only the kinds in
    AUTO_REPAIRABLE_FINDINGS.

    Never deletes a RouteEdge, a Room, a RoutePoint or a LocationCode. An
    edge is deactivated (is_active = False), which is reversible and keeps
    the audit trail.

    Idempotent: an already-inactive edge is skipped, and reconnection goes
    through the shared attachment service, which returns
    "already_connected" rather than stacking a second edge.
    """

    result = {
        "map_id": map_id,
        "requested": 0,
        "repaired": 0,
        "skipped_already_repaired": 0,
        "rejected_invalid": 0,
        "reconnected": 0,
        "still_needs_review": 0,
        "unconnected": [],
        "warnings": [],
    }

    try:
        map_item = await Map.get(PydanticObjectId(map_id))
    except Exception:  # noqa: BLE001
        map_item = None

    if not map_item:
        result["warnings"].append("Map not found.")
        return result

    preview = await preview_legacy_edge_repair(map_id)
    repairable_by_id = {
        finding["edge_id"]: finding
        for finding in preview["findings"]
        if finding.get("repairable") and finding.get("edge_id")
    }

    targets = (
        list(edge_ids)
        if edge_ids is not None
        else list(repairable_by_id)
    )
    result["requested"] = len(targets)

    affected_destination_ids: Set[str] = set()

    for edge_id in targets:
        # Only ever an edge this preview classified as repairable ON THIS
        # MAP — a caller can never hand in an arbitrary id and have it
        # deactivated.
        if edge_id not in repairable_by_id:
            result["rejected_invalid"] += 1
            continue

        try:
            edge = await RouteEdge.get(PydanticObjectId(edge_id))
        except Exception:  # noqa: BLE001
            edge = None

        if edge is None or edge.map_id != map_id:
            result["rejected_invalid"] += 1
            continue

        if not edge.is_active:
            result["skipped_already_repaired"] += 1
            continue

        for side in (edge.from_point_id, edge.to_point_id):
            affected_destination_ids.add(side)

        edge.is_active = False
        edge.updated_at = datetime.utcnow()
        if edge.description and REPAIR_DESCRIPTION_SUFFIX not in edge.description:
            edge.description = f"{edge.description}{REPAIR_DESCRIPTION_SUFFIX}"
        elif not edge.description:
            edge.description = REPAIR_DESCRIPTION_SUFFIX.strip()
        await edge.save()

        result["repaired"] += 1

    # ── reconnect ─────────────────────────────────────────────────────
    # Every destination that lost an edge now gets the CURRENT attachment
    # logic: corridor node, or projection onto a corridor edge with a
    # junction split, validated against strict geometry. A destination that
    # cannot be reconnected is left safely unconnected with a precise
    # reason — never given a fabricated edge.
    context = await load_corridor_floor_context_by_map_id(map_id)

    for point_id in sorted(affected_destination_ids):
        try:
            point = await RoutePoint.get(PydanticObjectId(point_id))
        except Exception:  # noqa: BLE001
            point = None

        if point is None or not point.is_active:
            continue
        if point.point_type not in DESTINATION_CAPABLE_POINT_TYPES:
            continue
        if point.connector_id is not None:
            continue

        try:
            outcome = await attach_point_to_corridor(point, refresh_context=True)
        except Exception as error:  # noqa: BLE001 — one bad point never
            # aborts the repair; the edges are already fixed.
            result["still_needs_review"] += 1
            result["unconnected"].append(
                {
                    "point_id": point_id,
                    "name": _point_label(point),
                    "reason": f"attachment_error: {error}",
                }
            )
            continue

        if outcome["status"] in ("attached", "already_connected"):
            result["reconnected"] += 1
        else:
            result["still_needs_review"] += 1
            result["unconnected"].append(
                {
                    "point_id": point_id,
                    "name": _point_label(point),
                    "reason": outcome["reason"],
                }
            )

    if context is None:
        result["warnings"].append(
            "Could not load the floor's corridor graph for reconnection."
        )

    return result
