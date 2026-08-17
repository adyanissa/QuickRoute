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
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from beanie import PydanticObjectId

from constants.route_point_types import (
    DESTINATION_CAPABLE_POINT_TYPES,
    TRANSIT_CANDIDATE_POINT_TYPES,
    transit_candidate_priority_rank,
)
from logic.instruction_generator import resolve_localized_display_name
from models.map_model import Map
from models.room_model import Room
from models.route_edge_model import RouteEdge
from models.route_point_model import RoutePoint
from services.room_location_code_service import (
    ensure_room_location_codes,
    merge_into_apply_result,
)
from services.graph_connection_service import (
    LINE_SAMPLE_STEP_PX,
    _ensure_map_source_available,
    _get_wall_mask,
    has_clear_line,
)


# Reuses graph_connection_service's own already-established "how far is too
# far for an ordinary walkway connection" default (DEFAULT_MAX_DISTANCE_PX)
# as this feature's ABSOLUTE FLOOR — never a ceiling — for the hard safety
# distance below, and as the fallback for maps with no known canonical
# image dimensions (pre-upload-pipeline maps, or synthetic/test maps that
# never went through image processing). Every real, imaged map computes a
# larger, scale-aware ceiling instead — see _effective_bounds() — so this
# constant only ever WIDENS the old fixed 600px cutoff, never narrows it.
MAX_DISTANCE_PX_DEFAULT = 600.0

# Confidence tiers, as fixed pixel fallbacks (used only when a map has no
# canonical image dimensions — see _effective_bounds()) and as the absolute
# floor for the scale-aware tiers on every other map. "very close" vs
# "within the recommended range" vs "outside the recommended range but
# still within the hard safety ceiling", per this feature's spec.
HIGH_CONFIDENCE_MAX_PX = 150.0
MEDIUM_CONFIDENCE_MAX_PX = 390.0

# Scale-aware thresholds, expressed as fractions of a map's canonical
# image diagonal (source_width/source_height, falling back to
# display_width/display_height) rather than one fixed raw-pixel cutoff.
# This is what actually fixes "Auto Connect proposes nothing for any
# destination whose nearest hallway/junction happens to be more than 600
# raw pixels away on a large, high-resolution floor-plan image" — on a
# large image, 600px can be a tiny fraction of the actual floor, so a
# fixed pixel cutoff was effectively far too small regardless of how close
# the two points really are on the physical floor.
HIGH_CONFIDENCE_FRACTION_OF_DIAGONAL = 0.05
MEDIUM_CONFIDENCE_FRACTION_OF_DIAGONAL = 0.18
# The hard safety ceiling: candidates beyond this are never proposed
# ("extremely unreasonable distance" per this feature's spec), regardless
# of confidence tier. Deliberately generous (a majority of the image
# diagonal) so that any destination with a genuine hallway/junction
# candidate anywhere on the SAME map/floor is still proposed (at "low"
# confidence if far), and only truly implausible pairings — e.g. two
# points that are effectively on opposite corners of the whole floor
# plan — are rejected.
HARD_SAFETY_FRACTION_OF_DIAGONAL = 0.60

MAX_CANDIDATES_PER_PROPOSAL = 3


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


def _confidence_tier(distance_px: float, high_max_px: float, medium_max_px: float) -> str:
    if distance_px <= high_max_px:
        return "high"
    if distance_px <= medium_max_px:
        return "medium"
    return "low"


def _canonical_diagonal_px(map_item: Map) -> Optional[float]:
    """
    The map's canonical image diagonal, used as the basis for every
    scale-aware distance threshold below. Prefers the true source image
    dimensions (source_width/source_height — the full-resolution file the
    admin actually uploaded); falls back to the cosmetic display image's
    dimensions when source dimensions aren't known; returns None for maps
    with neither (pre-upload-pipeline or synthetic maps), which signals
    every caller to fall back to the fixed pixel defaults instead.
    """

    width = map_item.source_width or map_item.display_width
    height = map_item.source_height or map_item.display_height
    if not width or not height:
        return None
    return math.hypot(float(width), float(height))


def _effective_bounds(
    map_item: Map, max_distance_px_override: Optional[float]
) -> Tuple[float, float, float]:
    """
    Resolves this scan's (high_confidence_max_px, medium_confidence_max_px,
    hard_safety_max_px) — the three distance thresholds every destination
    on this map is scored against.

    - An explicit caller-supplied max_distance_px always wins for the hard
      safety ceiling (preserves the existing request-level override
      contract) — confidence tiers still fall back to the fixed pixel
      defaults in that case, clamped to never exceed the override.
    - Otherwise, when the map has known canonical image dimensions, every
      threshold scales with the image diagonal.
    - Every threshold is clamped to never be SMALLER than the old fixed
      pixel default — this change only ever widens what used to be a
      single very small hard cutoff, never narrows it.
    """

    diagonal = _canonical_diagonal_px(map_item)

    if max_distance_px_override is not None:
        hard_safety_max_px = float(max_distance_px_override)
        high_max_px = HIGH_CONFIDENCE_MAX_PX
        medium_max_px = MEDIUM_CONFIDENCE_MAX_PX
    elif diagonal is not None:
        hard_safety_max_px = max(
            diagonal * HARD_SAFETY_FRACTION_OF_DIAGONAL, MAX_DISTANCE_PX_DEFAULT
        )
        high_max_px = max(
            diagonal * HIGH_CONFIDENCE_FRACTION_OF_DIAGONAL, HIGH_CONFIDENCE_MAX_PX
        )
        medium_max_px = max(
            diagonal * MEDIUM_CONFIDENCE_FRACTION_OF_DIAGONAL, MEDIUM_CONFIDENCE_MAX_PX
        )
    else:
        hard_safety_max_px = MAX_DISTANCE_PX_DEFAULT
        high_max_px = HIGH_CONFIDENCE_MAX_PX
        medium_max_px = MEDIUM_CONFIDENCE_MAX_PX

    # A confidence tier boundary must never exceed the hard safety ceiling
    # itself (only meaningful when an explicit override happens to be
    # smaller than the fixed pixel defaults above).
    high_max_px = min(high_max_px, hard_safety_max_px)
    medium_max_px = min(medium_max_px, hard_safety_max_px)

    return high_max_px, medium_max_px, hard_safety_max_px


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


# ─────────────────────────────────────────────────────────────────────
# Corridor-EDGE attachment, corridor connectivity, and the doorway rule
#
# Everything in this block exists to fix the two real-map failures this
# feature had: "no hallway/junction point close enough" reported for a
# room whose corridor is drawn right beside it, and a candidate pool that
# could not tell "too far" from "a wall is in the way".
# ─────────────────────────────────────────────────────────────────────

# A projected attachment closer than this to one of the corridor edge's
# own endpoints is not worth splitting the edge for — the endpoint node is
# already a candidate in its own right, and a junction placed a few pixels
# from an existing node is graph clutter, not accuracy.
EDGE_SPLIT_MIN_NODE_GAP_FRACTION_OF_HIGH = 0.15
EDGE_SPLIT_MIN_NODE_GAP_FLOOR_PX = 24.0

# A straight line that crosses this many DISTINCT wall strokes has
# entered and left some enclosed space on the way. See
# _attachment_is_clear for why counting crossings, rather than counting
# wall pixels, is what actually enforces "never use an unrelated room
# interior as a shortcut".
MAX_WALL_CROSSINGS = 1

# CANDIDATE PRIORITY is a tie-break, not an override. Two candidates are
# "effectively equidistant" when the second is within this much of the
# nearest one — measured relative to the nearest distance, so it means the
# same thing on a small plan and a huge one. Only inside that window does
# the corridor/hallway-before-junction order decide; outside it, the closer
# candidate wins, so a hallway across the floor can never beat a junction
# right outside the door.
PRIORITY_TIE_FRACTION = 0.15
PRIORITY_TIE_FLOOR_PX = 4.0


def _priority_tie_cutoff_px(best_distance_px: float) -> float:
    return best_distance_px + max(
        PRIORITY_TIE_FLOOR_PX, best_distance_px * PRIORITY_TIE_FRACTION
    )


def _project_point_on_segment(
    px: float, py: float, x1: float, y1: float, x2: float, y2: float
) -> Tuple[float, float, float, float]:
    """
    Closest point on the SEGMENT (x1,y1)-(x2,y2) to (px,py) — the
    perpendicular foot when it falls within the segment, otherwise the
    nearer endpoint.

    Returns (qx, qy, t, segment_length_px) with t clamped to [0, 1].
    """

    vx, vy = x2 - x1, y2 - y1
    length_sq = vx * vx + vy * vy

    if length_sq <= 0.0:
        return x1, y1, 0.0, 0.0

    t = ((px - x1) * vx + (py - y1) * vy) / length_sq
    t = max(0.0, min(1.0, t))

    return x1 + t * vx, y1 + t * vy, t, math.sqrt(length_sq)


class _UnionFind:
    """Iterative union-find with path compression. Small enough to keep
    here rather than pull in a dependency for one connectivity pass."""

    def __init__(self) -> None:
        self._parent: Dict[str, str] = {}

    def add(self, item: str) -> None:
        self._parent.setdefault(item, item)

    def find(self, item: str) -> str:
        self.add(item)
        root = item
        while self._parent[root] != root:
            root = self._parent[root]
        while self._parent[item] != root:
            self._parent[item], item = root, self._parent[item]
        return root

    def union(self, a: str, b: str) -> None:
        root_a, root_b = self.find(a), self.find(b)
        if root_a != root_b:
            self._parent[root_b] = root_a


def _transit_components(
    transit_ids: set, edges: List[RouteEdge]
) -> Tuple[Dict[str, str], Optional[str], bool]:
    """
    Connected components of the CORRIDOR graph — active walkway edges whose
    BOTH endpoints are transit points.

    Returns (component_root_by_point_id, main_component_root,
    has_any_internal_edge).

    main_component_root is the root of the largest component that actually
    contains more than one point, and None when no transit point is wired
    to any other. That distinction is deliberate: on a map whose entire
    corridor network is one hand-placed hallway point there is no
    multi-point component, so nothing is "isolated" and that point stays a
    perfectly good candidate — exactly the behaviour
    test_no_candidate_outside_configured_threshold depends on.
    """

    union_find = _UnionFind()
    for point_id in transit_ids:
        union_find.add(point_id)

    has_any_internal_edge = False

    for edge in edges:
        if edge.edge_type != "walkway":
            continue
        if edge.from_point_id in transit_ids and edge.to_point_id in transit_ids:
            union_find.union(edge.from_point_id, edge.to_point_id)
            has_any_internal_edge = True

    roots: Dict[str, str] = {
        point_id: union_find.find(point_id) for point_id in transit_ids
    }

    sizes: Dict[str, int] = defaultdict(int)
    for root in roots.values():
        sizes[root] += 1

    main_root: Optional[str] = None
    best_size = 1
    for root, size in sizes.items():
        if size > best_size:
            best_size, main_root = size, root

    return roots, main_root, has_any_internal_edge


def _blocked_runs_on_line(
    wall_mask, downscale: float, x1: float, y1: float, x2: float, y2: float
) -> Tuple[List[Tuple[int, int]], int]:
    """
    Contiguous runs of wall samples along the straight line, as
    (start_index, length) pairs, plus the total number of samples taken.

    Sampled with exactly the same step graph_connection_service.has_clear_line
    uses, so a run length here is directly comparable to a wall stroke
    measured on the same mask.
    """

    height, width = wall_mask.shape[:2]

    mx1, my1 = x1 * downscale, y1 * downscale
    mx2, my2 = x2 * downscale, y2 * downscale

    distance = math.hypot(mx2 - mx1, my2 - my1)
    if distance <= 0:
        return [], 0

    sample_count = max(2, int(distance / LINE_SAMPLE_STEP_PX))
    total_samples = sample_count + 1

    runs: List[Tuple[int, int]] = []
    run_start: Optional[int] = None

    for index in range(total_samples):
        t = index / sample_count
        px = int(round(mx1 + (mx2 - mx1) * t))
        py = int(round(my1 + (my2 - my1) * t))

        if 0 <= py < height and 0 <= px < width:
            blocked = wall_mask[py, px] > 0
        else:
            # Leaving the image is treated as blocked, matching
            # has_clear_line — a path off the drawing is not a path.
            blocked = True

        if blocked:
            if run_start is None:
                run_start = index
        elif run_start is not None:
            runs.append((run_start, index - run_start))
            run_start = None

    if run_start is not None:
        runs.append((run_start, total_samples - run_start))

    return runs, total_samples


def _attachment_is_clear(
    map_id: str,
    destination_x: float,
    destination_y: float,
    target_x: float,
    target_y: float,
) -> Tuple[bool, bool]:
    """
    Whether a destination may be attached to (target_x, target_y).

    Returns (is_clear, grazes_wall_stroke). The second value is purely
    informational — it feeds the review UI's per-candidate diagnostics and
    changes no decision.

    has_clear_line stays authoritative and is checked FIRST: anything it
    rejects is rejected here, unconditionally. A candidate that crosses a
    wall is never proposed because it happens to be closer; the caller
    moves on to the next valid corridor candidate.

    On top of that, this adds one rule that only ever makes the answer
    STRICTER: a line is also rejected when it crosses more than
    MAX_WALL_CROSSINGS distinct wall strokes. has_clear_line's tolerance is
    a fraction of the sampled length, so a sufficiently long line can clip
    several walls and still come in under 3% — which is exactly the
    "routed straight through the middle of an unrelated room" case. A line
    that enters and leaves another enclosed space produces two separate
    blocked runs, and counting runs rejects it regardless of how long the
    line is.
    """

    if not has_clear_line(map_id, destination_x, destination_y, target_x, target_y):
        return False, False

    cached = _get_wall_mask(map_id)
    if cached is None:
        # No mask means nothing to check against; has_clear_line already
        # returned True on that basis and the caller separately refuses to
        # report distance-based confidence for such a map.
        return True, False

    wall_mask, downscale = cached
    runs, _total_samples = _blocked_runs_on_line(
        wall_mask, downscale, destination_x, destination_y, target_x, target_y
    )

    if len(runs) > MAX_WALL_CROSSINGS:
        return False, False

    return True, bool(runs)


def _corridor_edge_label(point_a: RoutePoint, point_b: RoutePoint, lang: str) -> str:
    """Human-facing label for an attachment onto a corridor RUN rather than
    onto one of its endpoint nodes — the review UI must never show a raw
    edge id as the primary label."""
    return f"{_display_name(point_a, lang)} \u2194 {_display_name(point_b, lang)}"


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


def _no_candidate_proposal(
    *,
    map_id: str,
    destination: RoutePoint,
    destination_name: str,
    reason: str,
    is_calibrated: bool,
    has_existing_invalid_edges: bool,
    hard_safety_max_px: float,
    nearest_distance_px: Optional[float] = None,
    status: str = "no_candidate",
    diagnostics: Optional[dict] = None,
) -> dict:
    """One shape for every "nothing was proposed" outcome, so a new reason
    can never accidentally omit the diagnostics the review UI relies on."""

    payload = {
        "map_id": map_id,
        "floor": destination.floor,
        "destination_point_id": str(destination.id),
        "destination_name": destination_name,
        "destination_point_type": destination.point_type,
        "status": status,
        "confidence": None,
        "reason": reason,
        "has_existing_invalid_edges": has_existing_invalid_edges,
        "is_calibrated": is_calibrated,
        "proposed_candidate_id": None,
        "proposed_candidate_key": None,
        "candidates": [],
        "destination_x": round(float(destination.x), 2),
        "destination_y": round(float(destination.y), 2),
        "nearest_distance_px": nearest_distance_px,
        "max_hard_distance_px": round(hard_safety_max_px, 2),
    }
    payload.update(diagnostics or {})
    return payload


async def _scan_one_map(
    map_item: Map,
    floor: Optional[int],
    max_distance_px_override: Optional[float],
    lang: str,
) -> Tuple[dict, List[dict]]:
    map_id = str(map_item.id)

    high_max_px, medium_max_px, hard_safety_max_px = _effective_bounds(
        map_item, max_distance_px_override
    )

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
    transit_by_id: Dict[str, RoutePoint] = {str(p.id): p for p in transit_points}

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

    # CONNECTED GRAPH RULE. Components of the corridor graph itself, so a
    # candidate that exists but is stranded off the walkable network can be
    # reported as exactly that instead of being silently proposed (or,
    # worse, reported as a distance problem). See _transit_components for
    # why a map with a single lone hallway point is deliberately NOT
    # treated as having anything isolated.
    component_root_by_id, main_component_root, transit_network_has_internal_edges = (
        _transit_components(transit_ids, edges)
    )

    def _is_graph_connected(point_id: str) -> bool:
        if main_component_root is None:
            # No transit point is wired to any other anywhere on this map,
            # so there is no "main walkable graph" to be isolated from.
            return True
        return component_root_by_id.get(point_id) == main_component_root

    # Corridor EDGES, for attachment to the nearest point ALONG a drawn
    # corridor rather than only to its endpoint nodes. This is the fix for
    # "the room door is beside the middle of a long corridor run, and
    # neither end node is anywhere near it".
    corridor_segments: List[Tuple[RouteEdge, RoutePoint, RoutePoint]] = []
    for edge in edges:
        if edge.edge_type != "walkway":
            continue
        if edge.from_point_id not in transit_ids or edge.to_point_id not in transit_ids:
            continue
        point_a = transit_by_id.get(edge.from_point_id)
        point_b = transit_by_id.get(edge.to_point_id)
        if not point_a or not point_b:
            continue
        if point_a.floor != point_b.floor:
            continue
        corridor_segments.append((edge, point_a, point_b))

    min_node_gap_px = max(
        EDGE_SPLIT_MIN_NODE_GAP_FLOOR_PX,
        high_max_px * EDGE_SPLIT_MIN_NODE_GAP_FRACTION_OF_HIGH,
    )

    # Cell size = this map's hard safety ceiling, so a destination's 3x3
    # cell neighborhood is always guaranteed to fully cover every transit
    # point within hard_safety_max_px, regardless of where in a cell it
    # falls.
    grid = _SpatialGrid(hard_safety_max_px)
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
        destination_name = _display_name(destination, lang)
        has_existing_invalid_edges = bool(has_any_edge.get(destination_id))

        # ── NESTED ROOMS ────────────────────────────────────────────────
        # An approved inner destination proposes ONLY its confirmed parent
        # Room's own destination point — never a random nearby Room, and
        # never the ordinary hallway/junction search. Confirmed
        # containment (Room.parent_room_id, set only via explicit admin
        # approval in services/semantic_destination_service.py) is
        # required; a merely-nearby Room is never treated as a parent
        # because it happens to be close.
        destination_room = rooms_by_route_point_id.get(destination_id)
        if destination_room and destination_room.parent_room_id:
            parent_room = rooms_by_id.get(destination_room.parent_room_id)
            parent_point = (
                points_by_id.get(parent_room.route_point_id)
                if parent_room and parent_room.route_point_id
                else None
            )

            nested_diagnostics = {
                "is_nested_access": True,
                "nested_parent_room_id": destination_room.parent_room_id,
                "nested_parent_room_name": (
                    _display_name(parent_point, lang) if parent_point else None
                ),
                "parent_pass_through": bool(
                    parent_point and parent_point.allow_transit_through
                ),
                "connection_type": "nested_room_via_parent",
            }

            if (
                parent_point
                and parent_point.is_active
                and parent_point.allow_transit_through
            ):
                parent_point_id = str(parent_point.id)
                already_linked_to_parent = any(
                    (
                        edge.from_point_id == destination_id
                        and edge.to_point_id == parent_point_id
                    )
                    or (
                        edge.to_point_id == destination_id
                        and edge.from_point_id == parent_point_id
                    )
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
                        "destination_name": destination_name,
                        "destination_point_type": destination.point_type,
                        "status": "proposed",
                        # Declared/approved, not distance-derived — always
                        # "high" rather than running through the ordinary
                        # distance-based tiers, since this is a confirmed
                        # relationship, not a geometric guess.
                        "confidence": "high",
                        "reason": None,
                        "has_existing_invalid_edges": has_existing_invalid_edges,
                        "is_calibrated": is_calibrated,
                        "proposed_candidate_id": parent_point_id,
                        "proposed_candidate_key": parent_point_id,
                        "candidates": [
                            {
                                "candidate_key": parent_point_id,
                                "point_id": parent_point_id,
                                "name": _display_name(parent_point, lang),
                                "point_type": parent_point.point_type,
                                "target_type": "nested_parent",
                                "corridor_edge_id": None,
                                "x": round(float(parent_point.x), 2),
                                "y": round(float(parent_point.y), 2),
                                "attachment_x": round(float(parent_point.x), 2),
                                "attachment_y": round(float(parent_point.y), 2),
                                "distance_px": round(distance_px, 2),
                                "distance_meters": distance_meters,
                                "blocked_by_wall": False,
                                "clear_line": True,
                                "doorway_crossing": False,
                                "graph_connected": True,
                            }
                        ],
                        "destination_x": round(float(destination.x), 2),
                        "destination_y": round(float(destination.y), 2),
                        "nearest_distance_px": round(distance_px, 2),
                        "max_hard_distance_px": round(hard_safety_max_px, 2),
                        "target_type": "nested_parent",
                        "graph_connected": True,
                        "clear_line": True,
                        "doorway_crossing": False,
                        **nested_diagnostics,
                    }
                )
                continue

            # A parent relationship is declared but not usable. This is
            # NEEDS REVIEW, not "no candidate": the data is nearly right
            # and an admin can fix it in one click, and it must never fall
            # through to an ordinary nearby-hallway proposal for a
            # destination that is known to require its specific approved
            # parent.
            if parent_point is None or not parent_point.is_active:
                nested_reason = "nested_parent_no_point"
            else:
                nested_reason = "nested_parent_not_pass_through"

            summary["needs_review"] += 1
            proposals.append(
                _no_candidate_proposal(
                    map_id=map_id,
                    destination=destination,
                    destination_name=destination_name,
                    reason=nested_reason,
                    is_calibrated=is_calibrated,
                    has_existing_invalid_edges=has_existing_invalid_edges,
                    hard_safety_max_px=hard_safety_max_px,
                    status="needs_review",
                    diagnostics=nested_diagnostics,
                )
            )
            continue

        if has_valid_transit_edge.get(destination_id):
            summary["already_connected"] += 1
            continue

        # The most fundamental problem first: no corridor graph exists at
        # all on this map/floor.
        if not transit_points:
            summary["no_candidate"] += 1
            proposals.append(
                _no_candidate_proposal(
                    map_id=map_id,
                    destination=destination,
                    destination_name=destination_name,
                    reason="no_transit_points_on_map",
                    is_calibrated=is_calibrated,
                    has_existing_invalid_edges=has_existing_invalid_edges,
                    hard_safety_max_px=hard_safety_max_px,
                )
            )
            continue

        destination_x = float(destination.x)
        destination_y = float(destination.y)

        # ── CANDIDATE POOL ──────────────────────────────────────────────
        # Corridor/hallway and junction NODES, plus the nearest point along
        # every drawn corridor EDGE. Room/store points are not in
        # transit_points at all, so a normal destination can never see
        # another destination here.
        raw_candidates: List[dict] = []

        for candidate in grid.nearby(destination_x, destination_y):
            candidate_id = str(candidate.id)
            if candidate_id == destination_id:
                continue
            # A Map document can still contain RoutePoints recorded on more
            # than one distinct `floor` value (legacy data, or
            # vertical-connector transition points). Two points merely
            # sharing a map_id and a similar pixel position must never be
            # proposed as connected across a real floor difference.
            if candidate.floor != destination.floor:
                continue

            distance_px = math.hypot(
                float(candidate.x) - destination_x,
                float(candidate.y) - destination_y,
            )
            raw_candidates.append(
                {
                    "target_type": "corridor_node",
                    "candidate_key": candidate_id,
                    "point_id": candidate_id,
                    "corridor_edge_id": None,
                    "name": _display_name(candidate, lang),
                    "point_type": candidate.point_type,
                    "x": float(candidate.x),
                    "y": float(candidate.y),
                    "attachment_x": float(candidate.x),
                    "attachment_y": float(candidate.y),
                    "distance_px": distance_px,
                    "priority_rank": transit_candidate_priority_rank(
                        candidate.point_type
                    ),
                    "graph_connected": _is_graph_connected(candidate_id),
                }
            )

        for edge, point_a, point_b in corridor_segments:
            if point_a.floor != destination.floor:
                continue

            ax, ay = float(point_a.x), float(point_a.y)
            bx, by = float(point_b.x), float(point_b.y)

            # Cheap bounding-box reject before the projection maths, so a
            # bulk scan over thousands of destinations stays linear in
            # practice rather than doing full geometry per (destination,
            # edge) pair.
            if (
                destination_x < min(ax, bx) - hard_safety_max_px
                or destination_x > max(ax, bx) + hard_safety_max_px
                or destination_y < min(ay, by) - hard_safety_max_px
                or destination_y > max(ay, by) + hard_safety_max_px
            ):
                continue

            qx, qy, t, segment_length = _project_point_on_segment(
                destination_x, destination_y, ax, ay, bx, by
            )

            # A projection that lands essentially on one of the edge's own
            # endpoints adds nothing — that node is already a candidate,
            # and splitting an edge a few pixels from an existing junction
            # is graph clutter rather than accuracy.
            if (
                t * segment_length < min_node_gap_px
                or (1.0 - t) * segment_length < min_node_gap_px
            ):
                continue

            distance_px = math.hypot(qx - destination_x, qy - destination_y)

            # An edge is, by definition, part of the corridor graph; it is
            # "connected" exactly when its own component is the main one.
            edge_connected = _is_graph_connected(str(point_a.id))

            raw_candidates.append(
                {
                    "target_type": "corridor_edge",
                    "candidate_key": f"edge:{edge.id}",
                    "point_id": None,
                    "corridor_edge_id": str(edge.id),
                    "name": _corridor_edge_label(point_a, point_b, lang),
                    "point_type": (
                        point_a.point_type
                        if transit_candidate_priority_rank(point_a.point_type)
                        <= transit_candidate_priority_rank(point_b.point_type)
                        else point_b.point_type
                    ),
                    "x": round(qx, 2),
                    "y": round(qy, 2),
                    "attachment_x": qx,
                    "attachment_y": qy,
                    "distance_px": distance_px,
                    "priority_rank": min(
                        transit_candidate_priority_rank(point_a.point_type),
                        transit_candidate_priority_rank(point_b.point_type),
                    ),
                    "graph_connected": edge_connected,
                }
            )

        # Nearest thing found at all, before any safety filtering — kept
        # for diagnostics so a rejection can say how far away the corridor
        # actually was.
        nearest_found_px = (
            round(min(c["distance_px"] for c in raw_candidates), 2)
            if raw_candidates
            else None
        )

        within_safety = [
            c for c in raw_candidates if c["distance_px"] <= hard_safety_max_px
        ]

        # CANDIDATE PRIORITY. Connected always beats isolated. Then
        # distance — except among candidates that are effectively
        # equidistant with the nearest one, where the declared
        # corridor/hallway -> junction -> other order decides. Anything
        # outside that tie window is ordered purely by distance, which is
        # what stops a hallway on the far side of the floor from
        # outranking a junction right outside the door.
        within_safety.sort(
            key=lambda c: (0 if c["graph_connected"] else 1, c["distance_px"])
        )

        if within_safety:
            connected_first = [c for c in within_safety if c["graph_connected"]]
            reference = (connected_first or within_safety)[0]
            tie_cutoff = _priority_tie_cutoff_px(reference["distance_px"])

            def _priority_sort_key(candidate: dict) -> tuple:
                tied = candidate["distance_px"] <= tie_cutoff
                return (
                    0 if candidate["graph_connected"] else 1,
                    0 if tied else 1,
                    # Untied candidates all share slot 0 here, so they stay
                    # ordered by pure distance below.
                    candidate["priority_rank"] if tied else 0,
                    candidate["distance_px"],
                )

            within_safety.sort(key=_priority_sort_key)

        valid_candidates: List[dict] = []
        blocked_count = 0
        isolated_count = 0

        for candidate in within_safety:
            if not candidate["graph_connected"]:
                # CONNECTED GRAPH RULE: a corridor point stranded off the
                # walkable network is not a successful attachment. Counted
                # so the reason below can say so precisely.
                isolated_count += 1
                continue

            doorway_crossing = False
            if wall_mask_available:
                is_clear, doorway_crossing = _attachment_is_clear(
                    map_id,
                    destination_x,
                    destination_y,
                    candidate["attachment_x"],
                    candidate["attachment_y"],
                )
                if not is_clear:
                    # GEOMETRY SAFETY: reject and try the next valid
                    # corridor candidate — never connect through a wall
                    # just because it is closer.
                    blocked_count += 1
                    continue

            distance_meters = (
                round(candidate["distance_px"] * scale, 2) if is_calibrated else None
            )
            valid_candidates.append(
                {
                    "candidate_key": candidate["candidate_key"],
                    "point_id": candidate["point_id"],
                    "name": candidate["name"],
                    "point_type": candidate["point_type"],
                    "target_type": candidate["target_type"],
                    "corridor_edge_id": candidate["corridor_edge_id"],
                    "x": round(candidate["x"], 2),
                    "y": round(candidate["y"], 2),
                    "attachment_x": round(candidate["attachment_x"], 2),
                    "attachment_y": round(candidate["attachment_y"], 2),
                    "distance_px": round(candidate["distance_px"], 2),
                    "distance_meters": distance_meters,
                    "blocked_by_wall": False,
                    "clear_line": True,
                    "doorway_crossing": doorway_crossing,
                    "graph_connected": True,
                }
            )
            if len(valid_candidates) >= MAX_CANDIDATES_PER_PROPOSAL:
                break

        if not valid_candidates:
            # PREVIEW DIAGNOSTICS: each of these is a genuinely different
            # problem with a genuinely different fix, and conflating them
            # is what made "no corridor point close enough" appear for a
            # room with a corridor drawn right beside it.
            if blocked_count:
                no_candidate_reason = "blocked_by_wall"
            elif isolated_count:
                no_candidate_reason = "corridor_candidate_isolated"
            elif not transit_network_has_internal_edges and len(transit_points) >= 2:
                no_candidate_reason = "transit_points_not_connected_by_edges"
            else:
                no_candidate_reason = "no_transit_point_within_range"

            summary["no_candidate"] += 1
            proposals.append(
                _no_candidate_proposal(
                    map_id=map_id,
                    destination=destination,
                    destination_name=destination_name,
                    reason=no_candidate_reason,
                    is_calibrated=is_calibrated,
                    has_existing_invalid_edges=has_existing_invalid_edges,
                    hard_safety_max_px=hard_safety_max_px,
                    nearest_distance_px=nearest_found_px,
                    diagnostics={
                        "blocked_candidate_count": blocked_count,
                        "isolated_candidate_count": isolated_count,
                    },
                )
            )
            continue

        best = valid_candidates[0]
        nearest_px = best["distance_px"]

        # Without a real wall mask for this map, the segment's walkability
        # was never actually checked — this must never be reported as a
        # distance-based high/medium/low confidence proposal, only
        # "needs_review", regardless of how close the nearest candidate is.
        confidence = (
            "needs_review"
            if not wall_mask_available
            else _confidence_tier(nearest_px, high_max_px, medium_max_px)
        )

        if confidence == "needs_review":
            summary["needs_review"] += 1
        summary["proposed"] += 1

        proposals.append(
            {
                "map_id": map_id,
                "floor": destination.floor,
                "destination_point_id": destination_id,
                "destination_name": destination_name,
                "destination_point_type": destination.point_type,
                "status": "proposed",
                "confidence": confidence,
                "reason": None,
                "has_existing_invalid_edges": has_existing_invalid_edges,
                "is_calibrated": is_calibrated,
                "proposed_candidate_id": best["point_id"],
                "proposed_candidate_key": best["candidate_key"],
                "candidates": valid_candidates,
                "destination_x": round(destination_x, 2),
                "destination_y": round(destination_y, 2),
                "nearest_distance_px": nearest_px,
                "max_hard_distance_px": round(hard_safety_max_px, 2),
                "target_type": best["target_type"],
                "graph_connected": True,
                "clear_line": True,
                "doorway_crossing": best["doorway_crossing"],
                "connection_type": (
                    "corridor_edge_split"
                    if best["target_type"] == "corridor_edge"
                    else "corridor_node"
                ),
                "blocked_candidate_count": blocked_count,
                "isolated_candidate_count": isolated_count,
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
            map_item, floor, max_distance_px, lang
        )
        for key in overall_summary:
            overall_summary[key] += summary[key]
        all_proposals.extend(proposals)

    return {"summary": overall_summary, "proposals": all_proposals}


# Provenance stamped on the junction point and the two replacement
# corridor edges an edge-split attachment creates, so a later regeneration
# or cleanup can recognise them and an admin can see where they came from.
EDGE_SPLIT_GENERATION_METHOD = "auto_connect_edge_split"


async def _split_corridor_edge_for_attachment(
    map_id: str,
    edge: RouteEdge,
    attachment_x: float,
    attachment_y: float,
    calculate_edge_distance,
) -> Optional[RoutePoint]:
    """
    Turn a point partway along a corridor edge into a real junction the
    graph can attach to.

    Deliberately conservative and order-dependent:
      1. insert the new junction RoutePoint,
      2. insert the two replacement corridor edges,
      3. only then deactivate the original edge.

    If any step fails the caller's exception handler runs with the original
    edge still active, so the corridor is never left severed — the worst
    case is a redundant junction point, not a broken walkway.

    Uses the SAME point_type ("junction"), edge_type ("walkway") and
    calculate_edge_distance() every manually drawn corridor uses. No new
    document type, no new edge type, nothing for Dijkstra to learn.
    """

    endpoints = await RoutePoint.find(
        {"_id": {"$in": [PydanticObjectId(edge.from_point_id), PydanticObjectId(edge.to_point_id)]}}
    ).to_list()
    if len(endpoints) != 2:
        return None

    floor = endpoints[0].floor
    if any(point.floor != floor for point in endpoints):
        return None

    junction = RoutePoint(
        map_id=map_id,
        name=f"Auto Corridor Junction {round(attachment_x)}-{round(attachment_y)}",
        point_type="junction",
        x=round(float(attachment_x), 2),
        y=round(float(attachment_y), 2),
        floor=floor,
        building_id=endpoints[0].building_id,
        is_accessible=True,
        is_auto_generated=True,
        generation_method=EDGE_SPLIT_GENERATION_METHOD,
    )
    await junction.insert()
    junction_id = str(junction.id)

    for endpoint in endpoints:
        endpoint_id = str(endpoint.id)
        replacement = RouteEdge(
            map_id=map_id,
            from_point_id=junction_id,
            to_point_id=endpoint_id,
            edge_type="walkway",
            distance=await calculate_edge_distance(
                map_id=map_id,
                from_point_id=junction_id,
                to_point_id=endpoint_id,
                edge_type="walkway",
            ),
            is_bidirectional=edge.is_bidirectional,
            is_accessible=edge.is_accessible,
            description="Auto Connect: corridor split for room attachment",
            is_auto_generated=True,
            generation_method=EDGE_SPLIT_GENERATION_METHOD,
        )
        await replacement.insert()

    # Last, so a failure above can never sever the corridor.
    edge.is_active = False
    edge.updated_at = datetime.utcnow()
    await edge.save()

    return junction


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
        # Edge-split attachments performed (a room whose nearest valid
        # corridor point was partway along a drawn corridor edge rather
        # than at one of its endpoint nodes).
        "corridor_junctions_created": 0,
        "created_point_ids": [],
    }

    map_item = await Map.get(PydanticObjectId(map_id))
    if not map_item:
        result["rejected_invalid"] = len(accepted_pairs)
        result["warnings"].append("Map not found.")
        return result

    for pair in accepted_pairs:
        destination_id = pair.get("destination_point_id")
        corridor_id = pair.get("corridor_point_id")
        corridor_edge_id = pair.get("corridor_edge_id")
        attachment_x = pair.get("attachment_x")
        attachment_y = pair.get("attachment_y")
        created_junction_id: Optional[str] = None

        try:
            if not destination_id:
                result["rejected_invalid"] += 1
                continue

            # Exactly one attachment target: an existing corridor point, or
            # a position along an existing corridor edge. Never both, never
            # neither.
            if bool(corridor_id) == bool(corridor_edge_id):
                result["rejected_invalid"] += 1
                continue

            destination = await RoutePoint.get(PydanticObjectId(destination_id))

            if not destination:
                result["rejected_invalid"] += 1
                continue

            if destination.map_id != map_id or not destination.is_active:
                result["rejected_invalid"] += 1
                continue

            if destination.point_type not in DESTINATION_CAPABLE_POINT_TYPES:
                result["rejected_invalid"] += 1
                continue

            # ── EDGE ATTACHMENT ─────────────────────────────────────────
            # Revalidated from a fresh read exactly like a point pair: the
            # edge must still be an active same-map walkway between two
            # real transit points, and the requested attachment must still
            # have a clear line from the destination. Only then is the
            # junction created.
            if corridor_edge_id:
                if attachment_x is None or attachment_y is None:
                    result["rejected_invalid"] += 1
                    continue

                corridor_edge = await RouteEdge.get(PydanticObjectId(corridor_edge_id))

                if (
                    not corridor_edge
                    or not corridor_edge.is_active
                    or corridor_edge.map_id != map_id
                    or corridor_edge.edge_type != "walkway"
                    or corridor_edge.to_map_id is not None
                ):
                    result["rejected_invalid"] += 1
                    continue

                edge_from = await RoutePoint.get(
                    PydanticObjectId(corridor_edge.from_point_id)
                )
                edge_to = await RoutePoint.get(
                    PydanticObjectId(corridor_edge.to_point_id)
                )

                if (
                    not edge_from
                    or not edge_to
                    or not edge_from.is_active
                    or not edge_to.is_active
                    or edge_from.point_type not in TRANSIT_CANDIDATE_POINT_TYPES
                    or edge_to.point_type not in TRANSIT_CANDIDATE_POINT_TYPES
                    or edge_from.floor != destination.floor
                    or edge_to.floor != destination.floor
                ):
                    result["rejected_invalid"] += 1
                    continue

                await _ensure_map_source_available(map_id)
                if _get_wall_mask(map_id) is not None:
                    is_clear, _ = _attachment_is_clear(
                        map_id,
                        float(destination.x),
                        float(destination.y),
                        float(attachment_x),
                        float(attachment_y),
                    )
                    if not is_clear:
                        result["rejected_invalid"] += 1
                        continue

                junction = await _split_corridor_edge_for_attachment(
                    map_id,
                    corridor_edge,
                    float(attachment_x),
                    float(attachment_y),
                    calculate_edge_distance,
                )
                if junction is None:
                    result["rejected_invalid"] += 1
                    continue

                corridor = junction
                corridor_id = str(junction.id)
                created_junction_id = corridor_id
                result["corridor_junctions_created"] += 1
                result["created_point_ids"].append(corridor_id)
            else:
                corridor = await RoutePoint.get(PydanticObjectId(corridor_id))

            if destination_id == corridor_id:
                result["rejected_invalid"] += 1
                continue

            if not corridor:
                result["rejected_invalid"] += 1
                continue

            if not corridor.is_active:
                result["rejected_invalid"] += 1
                continue

            # The corridor side must genuinely belong to the exact map this
            # apply call was scoped to — never trust a stale/forged pair
            # that has since drifted, even if both points still exist.
            if corridor.map_id != map_id:
                result["rejected_invalid"] += 1
                continue

            if destination.floor != corridor.floor:
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
            if created_junction_id:
                # A junction was created before the failure. The corridor
                # itself is intact (the original edge is only deactivated
                # once both replacements exist), so this is a harmless
                # leftover — but say so rather than leaving it unexplained.
                result["warnings"].append(
                    f"Could not attach destination {destination_id} to the "
                    f"corridor; a corridor junction was created and left in "
                    f"place."
                )
            else:
                result["warnings"].append(
                    f"Could not connect destination {destination_id} to corridor "
                    f"point {corridor_id}."
                )

    # "Every accepted navigable room gets its own QR", stage 2 of 2 — and in
    # practice the one that actually issues most of them.
    #
    # This is the moment a destination stops being an isolated point and
    # becomes reachable, which is exactly the condition
    # ensure_room_location_codes() requires before it will mint a code. The
    # identical call also runs at the end of
    # services/semantic_destination_service.apply_semantic_destinations for
    # the rooms whose arrival point was already connected; the function is
    # idempotent, so whichever of the two runs first wins and the other
    # simply reports the code as reused.
    #
    # Never raises: the edges above are already written and must stand on
    # their own even if QR issuing has a problem.
    try:
        qr_summary = await ensure_room_location_codes(map_id)
        merge_into_apply_result(result, qr_summary)
    except Exception as error:  # noqa: BLE001 - never fails the apply
        result["warnings"].append(
            f"Connections were applied, but automatic QR issuing failed: {error}"
        )

    return result