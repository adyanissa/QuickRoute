"""
"Auto Connect Destinations to Corridors": proposes, and — only once an
admin explicitly accepts each one — creates, ordinary same-floor walkway
RouteEdges between an unconnected Room/Store RoutePoint and a nearby valid
corridor/hallway/junction RoutePoint.

Two entry points, matching the required preview/apply split:
  - preview_auto_connect_destinations(): 100% read-only. Never inserts,
    updates, or deletes anything. Safe to call as often as needed.
  - apply_auto_connect_destinations(): the ONLY function in this module
    that writes to MongoDB, and only for the exact accepted pairs it is
    given — every pair is fully revalidated here from fresh database
    reads, never trusting whatever the frontend's preview state claims.

Deliberately does not touch: Dijkstra/shortest-path logic (logic/), Room
documents, QR/location codes, vertical connectors, calibration, semantic
analysis results, or any existing RouteEdge/RoutePoint. The only database
writes this module ever performs are brand-new RouteEdge inserts, one per
explicitly accepted pair, in apply_auto_connect_destinations().

Performance: for potentially thousands of destination points, this
deliberately avoids the O(destinations x transit_points) "compare every
Room to every corridor point" approach (and the per-point-DB-query
approach graph_connection_service.find_connection_candidates() uses, which
is fine for one point at a time but does not scale to a bulk scan). All
active RoutePoints/RouteEdges for the scanned map(s) are fetched from
MongoDB exactly once, up front; nearest-transit-candidate lookups are then
done entirely in memory against a small stdlib-only uniform spatial grid
(_SpatialGrid below) — no new third-party dependency.
"""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

from beanie import PydanticObjectId

from constants.route_point_types import (
    DESTINATION_CAPABLE_POINT_TYPES,
    TRANSIT_CANDIDATE_POINT_TYPES,
)
from logic.instruction_generator import resolve_localized_display_name
from models.map_model import Map
from models.room_model import Room
from models.route_edge_model import RouteEdge
from models.route_point_model import RoutePoint
from services.graph_connection_service import (
    _ensure_map_source_available,
    _get_wall_mask,
    has_clear_line,
)


# Reuses graph_connection_service's own already-established "how far is too
# far for an ordinary walkway connection" default (DEFAULT_MAX_DISTANCE_PX)
# as this feature's overall safety ceiling, rather than inventing an
# unrelated number — see that module's auto_connect_point() (Draw Path /
# new-point auto-connect), which is the same underlying concept applied to
# a single point instead of a bulk scan.
MAX_DISTANCE_PX_DEFAULT = 600.0

# Confidence tiers, as fractions of the overall max distance — "very close"
# vs "within the configured maximum" vs "outside the recommended range",
# per this feature's spec. Kept as simple named constants (not a config
# file) so they are easy for a future admin-facing settings screen to pick
# up without any structural change here.
HIGH_CONFIDENCE_MAX_PX = 150.0
MEDIUM_CONFIDENCE_MAX_PX = 390.0

MAX_CANDIDATES_PER_PROPOSAL = 3

# Uniform grid cell size for the in-memory spatial index. Sized to the
# overall max search distance so that a destination's 3x3 neighborhood of
# cells always fully covers its search radius regardless of where in a
# cell it falls.
_GRID_CELL_SIZE_PX = MAX_DISTANCE_PX_DEFAULT


class _SpatialGrid:
    """
    Minimal stdlib-only uniform grid spatial index over a fixed list of
    (RoutePoint, x, y) entries. Not a general-purpose library — just
    enough to turn an O(n) "scan every transit point for every
    destination" comparison into an O(1)-amortized neighborhood lookup for
    the bulk auto-connect scan.
    """

    def __init__(self, cell_size: float):
        self._cell_size = max(1.0, cell_size)
        self._cells: Dict[Tuple[int, int], List[RoutePoint]] = defaultdict(list)

    def _cell_key(self, x: float, y: float) -> Tuple[int, int]:
        return (int(x // self._cell_size), int(y // self._cell_size))

    def add(self, point: RoutePoint) -> None:
        self._cells[self._cell_key(float(point.x), float(point.y))].append(point)

    def nearby(self, x: float, y: float) -> List[RoutePoint]:
        """Every point in this cell and its 8 neighbors — a superset of
        every point actually within `_cell_size` of (x, y); callers still
        filter by exact Euclidean distance afterward."""
        cx, cy = self._cell_key(x, y)
        results: List[RoutePoint] = []
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                results.extend(self._cells.get((cx + dx, cy + dy), []))
        return results


def _get_scale_for_floor(map_item: Map, floor: Optional[int]) -> float:
    """
    Mirrors routes/route_edge_routes.py's get_scale_for_floor() exactly
    (same lookup: floor_scales[str(floor)] if present, else the map's
    overall scale). Duplicated as a small, self-contained helper rather
    than imported from routes/route_edge_routes.py to avoid a circular
    import (that module imports this service for its two new endpoints).
    """

    if floor is not None and map_item.floor_scales:
        floor_key = str(floor)
        if floor_key in map_item.floor_scales:
            return map_item.floor_scales[floor_key]

    return map_item.scale


def _confidence_tier(distance_px: float) -> str:
    if distance_px <= HIGH_CONFIDENCE_MAX_PX:
        return "high"
    if distance_px <= MEDIUM_CONFIDENCE_MAX_PX:
        return "medium"
    return "low"


def _display_name(point: RoutePoint, lang: str) -> str:
    resolved = resolve_localized_display_name(
        point.name,
        display_name=point.display_name,
        display_name_en=point.display_name_en,
        display_name_ar=point.display_name_ar,
        display_name_he=point.display_name_he,
        is_auto_generated=point.is_auto_generated,
        lang=lang,
    )
    # Every candidate/destination shown in the preview must have SOME
    # human-facing label (never a raw technical id as the primary label,
    # per this feature's spec) — resolve_localized_display_name can
    # legitimately return None for a suppressed technical name, so this
    # falls back to the raw name rather than ever showing nothing.
    return resolved or point.name or str(point.id)


async def _resolve_scan_maps(map_id: str, scope: str) -> List[Map]:
    origin_map = await Map.get(PydanticObjectId(map_id))
    if not origin_map:
        return []

    if scope != "map_group" or not origin_map.map_group_id:
        return [origin_map]

    group_maps = await Map.find(
        {
            "map_group_id": origin_map.map_group_id,
            "is_current_for_floor": True,
        }
    ).to_list()

    # Always include the origin map itself even if, for some legacy data
    # reason, it didn't come back from the is_current_for_floor query —
    # never silently drop the map the admin actually selected.
    if not any(str(m.id) == str(origin_map.id) for m in group_maps):
        group_maps.append(origin_map)

    return group_maps


async def _scan_one_map(
    map_item: Map,
    floor: Optional[int],
    max_distance_px: float,
    lang: str,
) -> Tuple[dict, List[dict]]:
    map_id = str(map_item.id)

    point_query: dict = {"map_id": map_id, "is_active": True}
    if floor is not None:
        point_query["floor"] = floor

    all_points = await RoutePoint.find(point_query).to_list()

    destinations = [
        p
        for p in all_points
        if p.point_type in DESTINATION_CAPABLE_POINT_TYPES
        and p.connector_id is None
        and p.x is not None
        and p.y is not None
    ]
    transit_points = [
        p
        for p in all_points
        if p.point_type in TRANSIT_CANDIDATE_POINT_TYPES
        and p.connector_id is None
        and p.x is not None
        and p.y is not None
    ]

    edges = await RouteEdge.find({"map_id": map_id, "is_active": True}).to_list()
    transit_ids = {str(p.id) for p in transit_points}
    points_by_id: Dict[str, RoutePoint] = {str(p.id): p for p in all_points}

    # Nested-room navigation (Approved Semantic Analysis -> Automatic
    # Destinations spec, Section 12.B). Batched once per map, never one
    # query per destination: every Room on this map, indexed both by its
    # linked RoutePoint id (to find "is THIS destination point nested
    # under something") and by its own id (to resolve "what IS that
    # parent Room's own destination point").
    rooms = await Room.find({"map_id": map_id}).to_list()
    rooms_by_route_point_id: Dict[str, Room] = {
        r.route_point_id: r for r in rooms if r.route_point_id
    }
    rooms_by_id: Dict[str, Room] = {str(r.id): r for r in rooms}

    # For every RoutePoint id: does it have at least one active edge (of
    # ANY edge_type) at all, and does it have at least one active WALKWAY
    # edge specifically to a valid transit point? These are deliberately
    # tracked separately — "has an edge" alone must never be treated as
    # "correctly connected" (a stale Room-to-Room edge must still leave the
    # Room eligible for a real proposal, just flagged with a warning).
    has_any_edge: Dict[str, bool] = defaultdict(bool)
    has_valid_transit_edge: Dict[str, bool] = defaultdict(bool)

    for edge in edges:
        has_any_edge[edge.from_point_id] = True
        has_any_edge[edge.to_point_id] = True

        if edge.edge_type != "walkway":
            continue

        if edge.to_point_id in transit_ids:
            has_valid_transit_edge[edge.from_point_id] = True
        if edge.from_point_id in transit_ids:
            has_valid_transit_edge[edge.to_point_id] = True

    grid = _SpatialGrid(_GRID_CELL_SIZE_PX)
    for point in transit_points:
        grid.add(point)

    # ECS task storage is temporary. Restore the normalized source image
    # from S3 once per scanned map before building the wall mask.
    await _ensure_map_source_available(map_id)

    wall_mask_available = _get_wall_mask(map_id) is not None
    is_calibrated = bool(map_item.is_calibrated)
    scale = _get_scale_for_floor(map_item, floor if floor is not None else map_item.floor)

    summary = {
        "scanned": len(destinations),
        "already_connected": 0,
        "proposed": 0,
        "needs_review": 0,
        "no_candidate": 0,
    }
    proposals: List[dict] = []

    for destination in destinations:
        destination_id = str(destination.id)

        # Nested-room navigation (Section 12.B): an approved inner
        # destination proposes ONLY its confirmed parent Room's own
        # destination point — never a random nearby Room, and never the
        # normal hallway/junction grid search. Confirmed containment
        # (Room.parent_room_id, set only via explicit admin approval —
        # see services/semantic_destination_service.py) is required; a
        # merely-nearby Room is never treated as a parent just because it
        # is close.
        destination_room = rooms_by_route_point_id.get(destination_id)
        if destination_room and destination_room.parent_room_id:
            parent_room = rooms_by_id.get(destination_room.parent_room_id)
            parent_point = (
                points_by_id.get(parent_room.route_point_id)
                if parent_room and parent_room.route_point_id
                else None
            )

            if (
                parent_point
                and parent_point.is_active
                and parent_point.allow_transit_through
            ):
                already_linked_to_parent = any(
                    (edge.from_point_id == destination_id and edge.to_point_id == str(parent_point.id))
                    or (edge.to_point_id == destination_id and edge.from_point_id == str(parent_point.id))
                    for edge in edges
                )
                if already_linked_to_parent:
                    summary["already_connected"] += 1
                    continue

                distance_px = math.hypot(
                    float(parent_point.x) - float(destination.x),
                    float(parent_point.y) - float(destination.y),
                )
                distance_meters = (
                    round(distance_px * scale, 2) if is_calibrated else None
                )
                summary["proposed"] += 1
                proposals.append(
                    {
                        "map_id": map_id,
                        "floor": destination.floor,
                        "destination_point_id": destination_id,
                        "destination_name": _display_name(destination, lang),
                        "destination_point_type": destination.point_type,
                        "status": "proposed",
                        # Declared/approved, not distance-derived — always
                        # "high" rather than running through the ordinary
                        # distance-based tiers, since this is a confirmed
                        # relationship, not a geometric guess.
                        "confidence": "high",
                        "reason": None,
                        "has_existing_invalid_edges": bool(has_any_edge.get(destination_id)),
                        "is_calibrated": is_calibrated,
                        "proposed_candidate_id": str(parent_point.id),
                        "candidates": [
                            {
                                "point_id": str(parent_point.id),
                                "name": _display_name(parent_point, lang),
                                "point_type": parent_point.point_type,
                                "distance_px": round(distance_px, 2),
                                "distance_meters": distance_meters,
                                "blocked_by_wall": False,
                            }
                        ],
                        "is_nested_access": True,
                    }
                )
                continue

            # A parent relationship is declared but not yet usable (parent
            # has no destination point yet, or its own allow_transit
            # approval hasn't happened) — never silently fall through to
            # an ordinary nearby-hallway proposal for a destination that
            # is known to require its specific approved parent.
            summary["no_candidate"] += 1
            proposals.append(
                {
                    "map_id": map_id,
                    "floor": destination.floor,
                    "destination_point_id": destination_id,
                    "destination_name": _display_name(destination, lang),
                    "destination_point_type": destination.point_type,
                    "status": "no_candidate",
                    "confidence": None,
                    "reason": "nested_parent_not_ready",
                    "has_existing_invalid_edges": bool(has_any_edge.get(destination_id)),
                    "is_calibrated": is_calibrated,
                    "proposed_candidate_id": None,
                    "candidates": [],
                    "is_nested_access": True,
                }
            )
            continue

        if has_valid_transit_edge.get(destination_id):
            summary["already_connected"] += 1
            continue

        nearby = grid.nearby(float(destination.x), float(destination.y))

        scored: List[Tuple[RoutePoint, float]] = []
        for candidate in nearby:
            if str(candidate.id) == destination_id:
                continue
            distance_px = math.hypot(
                float(candidate.x) - float(destination.x),
                float(candidate.y) - float(destination.y),
            )
            if distance_px <= max_distance_px:
                scored.append((candidate, distance_px))

        scored.sort(key=lambda pair: pair[1])

        valid_candidates: List[dict] = []
        for candidate, distance_px in scored:
            blocked = False
            if wall_mask_available:
                blocked = not has_clear_line(
                    map_id,
                    float(destination.x),
                    float(destination.y),
                    float(candidate.x),
                    float(candidate.y),
                )
                if blocked:
                    continue

            distance_meters = (
                round(distance_px * scale, 2) if is_calibrated else None
            )
            valid_candidates.append(
                {
                    "point_id": str(candidate.id),
                    "name": _display_name(candidate, lang),
                    "point_type": candidate.point_type,
                    "distance_px": round(distance_px, 2),
                    "distance_meters": distance_meters,
                    "blocked_by_wall": False,
                }
            )
            if len(valid_candidates) >= MAX_CANDIDATES_PER_PROPOSAL:
                break

        has_existing_invalid_edges = bool(has_any_edge.get(destination_id))

        if not valid_candidates:
            summary["no_candidate"] += 1
            proposals.append(
                {
                    "map_id": map_id,
                    "floor": destination.floor,
                    "destination_point_id": destination_id,
                    "destination_name": _display_name(destination, lang),
                    "destination_point_type": destination.point_type,
                    "status": "no_candidate",
                    "confidence": None,
                    "reason": "no_transit_point_within_range",
                    "has_existing_invalid_edges": has_existing_invalid_edges,
                    "is_calibrated": is_calibrated,
                    "proposed_candidate_id": None,
                    "candidates": [],
                }
            )
            continue

        nearest_px = valid_candidates[0]["distance_px"]

        # Section 7: without a real wall mask for this map, the segment's
        # walkability was never actually checked — this must never be
        # reported as a distance-based high/medium/low confidence
        # proposal, only "needs_review", regardless of how close the
        # nearest candidate is.
        confidence = "needs_review" if not wall_mask_available else _confidence_tier(nearest_px)

        if confidence == "needs_review":
            summary["needs_review"] += 1
        summary["proposed"] += 1

        proposals.append(
            {
                "map_id": map_id,
                "floor": destination.floor,
                "destination_point_id": destination_id,
                "destination_name": _display_name(destination, lang),
                "destination_point_type": destination.point_type,
                "status": "proposed",
                "confidence": confidence,
                "reason": None,
                "has_existing_invalid_edges": has_existing_invalid_edges,
                "is_calibrated": is_calibrated,
                "proposed_candidate_id": valid_candidates[0]["point_id"],
                "candidates": valid_candidates,
            }
        )

    return summary, proposals


async def preview_auto_connect_destinations(
    map_id: str,
    floor: Optional[int] = None,
    max_distance_px: Optional[float] = None,
    scope: str = "map",
    lang: str = "en",
) -> dict:
    """
    Entirely read-only. Never calls .insert()/.save()/.delete() on
    anything — only RoutePoint.find()/RouteEdge.find()/Map.get()/Map.find()
    reads.
    """

    effective_max_distance = max_distance_px or MAX_DISTANCE_PX_DEFAULT

    maps_to_scan = await _resolve_scan_maps(map_id, scope)

    overall_summary = {
        "scanned": 0,
        "already_connected": 0,
        "proposed": 0,
        "needs_review": 0,
        "no_candidate": 0,
    }
    all_proposals: List[dict] = []

    for map_item in maps_to_scan:
        summary, proposals = await _scan_one_map(
            map_item, floor, effective_max_distance, lang
        )
        for key in overall_summary:
            overall_summary[key] += summary[key]
        all_proposals.extend(proposals)

    return {"summary": overall_summary, "proposals": all_proposals}


async def apply_auto_connect_destinations(
    map_id: str,
    accepted_pairs: List[dict],
) -> dict:
    """
    The only function in this module that writes to MongoDB. Every pair is
    independently, fully revalidated from a fresh database read here —
    the frontend's preview response is never trusted as-is. One invalid or
    failed pair never aborts the others (Section 12: continue safely with
    other independent accepted proposals).

    Reuses the EXISTING route_edge_routes.py validation/duplicate/distance
    helpers (validate_edge_ids, find_duplicate_edge, calculate_edge_distance)
    via a function-scoped import — deferred specifically so this module
    never has a circular top-level import with routes/route_edge_routes.py
    (which imports THIS module for its two new endpoints). By the time
    apply_auto_connect_destinations() actually runs, the app has already
    fully imported both modules, so this import is always cheap and safe.
    """

    from routes.route_edge_routes import (  # noqa: PLC0415 (deferred: see docstring)
        calculate_edge_distance,
        find_duplicate_edge,
    )

    result = {
        "requested": len(accepted_pairs),
        "created": 0,
        "skipped_existing": 0,
        "rejected_invalid": 0,
        "failed": 0,
        "created_edge_ids": [],
        "warnings": [],
    }

    map_item = await Map.get(PydanticObjectId(map_id))
    if not map_item:
        result["rejected_invalid"] = len(accepted_pairs)
        result["warnings"].append("Map not found.")
        return result

    for pair in accepted_pairs:
        destination_id = pair.get("destination_point_id")
        corridor_id = pair.get("corridor_point_id")

        try:
            if not destination_id or not corridor_id:
                result["rejected_invalid"] += 1
                continue

            if destination_id == corridor_id:
                result["rejected_invalid"] += 1
                continue

            destination = await RoutePoint.get(PydanticObjectId(destination_id))
            corridor = await RoutePoint.get(PydanticObjectId(corridor_id))

            if not destination or not corridor:
                result["rejected_invalid"] += 1
                continue

            if not destination.is_active or not corridor.is_active:
                result["rejected_invalid"] += 1
                continue

            # Both points must genuinely belong to the exact map this
            # apply call was scoped to — never trust a stale/forged pair
            # that has since drifted, even if both points still exist.
            if destination.map_id != map_id or corridor.map_id != map_id:
                result["rejected_invalid"] += 1
                continue

            if destination.floor != corridor.floor:
                result["rejected_invalid"] += 1
                continue

            if destination.point_type not in DESTINATION_CAPABLE_POINT_TYPES:
                result["rejected_invalid"] += 1
                continue

            # Nested-room navigation (Section 12.B): the "corridor" side of
            # an approved nested pair is actually the destination's own
            # confirmed parent Room's destination point (point_type
            # "room"/"store"), never a hallway/junction — so the ordinary
            # transit-candidate check is deliberately widened, but ONLY
            # when there is a real, explicit, approved containment
            # relationship AND the parent has allow_transit_through set.
            # An unrelated nearby Room can never slip through this check
            # just because it happens to be destination-capable.
            is_nested_pair = False
            if corridor.point_type not in TRANSIT_CANDIDATE_POINT_TYPES:
                if corridor.point_type in DESTINATION_CAPABLE_POINT_TYPES:
                    destination_room = await Room.find_one(
                        {"route_point_id": destination_id}
                    )
                    corridor_room = await Room.find_one(
                        {"route_point_id": corridor_id}
                    )
                    if (
                        destination_room
                        and corridor_room
                        and destination_room.parent_room_id == str(corridor_room.id)
                        and corridor.allow_transit_through
                    ):
                        is_nested_pair = True

                if not is_nested_pair:
                    result["rejected_invalid"] += 1
                    continue

            # Never a vertical-connector stop on either side.
            if destination.connector_id is not None or corridor.connector_id is not None:
                result["rejected_invalid"] += 1
                continue

            duplicate = await find_duplicate_edge(
                map_id=map_id,
                from_point_id=destination_id,
                to_point_id=corridor_id,
                edge_type="walkway",
            )
            if duplicate:
                result["skipped_existing"] += 1
                continue

            distance = await calculate_edge_distance(
                map_id=map_id,
                from_point_id=destination_id,
                to_point_id=corridor_id,
                edge_type="walkway",
            )

            new_edge = RouteEdge(
                map_id=map_id,
                from_point_id=destination_id,
                to_point_id=corridor_id,
                edge_type="walkway",
                distance=distance,
                is_bidirectional=True,
                is_accessible=True,
                description=(
                    "Auto Connect: approved nested-room access"
                    if is_nested_pair
                    else "Auto Connect Destinations to Corridors"
                ),
                access_relation="nested" if is_nested_pair else None,
            )
            await new_edge.insert()

            result["created"] += 1
            result["created_edge_ids"].append(str(new_edge.id))

        except Exception as error:  # noqa: BLE001 — one bad pair must never
            # abort the batch, and the raw exception must never reach the
            # admin — only a safe, generic warning does.
            result["failed"] += 1
            result["warnings"].append(
                f"Could not connect destination {destination_id} to corridor "
                f"point {corridor_id}."
            )

    return result