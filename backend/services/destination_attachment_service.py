"""
The ONE algorithm for attaching a point to a floor's corridor graph.

WHY THIS MODULE EXISTS
----------------------
There used to be two different connection algorithms:

  * services/graph_connection_service.auto_connect_point — nearest NODE
    only, no corridor-edge projection, no connected-component check. This
    is what ran when a Room door point or a stair/elevator stop was saved.

  * services/auto_connect_destinations_service — the good one: corridor
    nodes PLUS the nearest point along a drawn corridor edge, a union-find
    component check, strict clear-line geometry, and edge splitting. This
    only ran when an admin pressed Auto Connect by hand.

So saving a room beside the middle of a long corridor left it unconnected,
and the admin had to go back and press Auto Connect anyway. Everything the
good algorithm knows now lives HERE, and every caller goes through it:

    Room door point saved            routes/room_routes.py
    POST /route-points?auto_connect= routes/route_point_routes.py
    Stair/elevator stop placed       services/vertical_connector_service.py
    Bulk retry after corridor edits  retry_pending_attachments() below
    Auto Connect preview/apply       services/auto_connect_destinations_service.py
    Legacy edge repair               services/legacy_edge_repair_service.py

LAYERING
--------
This is the LOWER layer. It must never import
auto_connect_destinations_service — that module imports from here. The
preview/apply pair up there is a presentation of these candidates (it adds
confidence tiers, localisation and multi-candidate review); the search,
the geometry and the splitting are all here, once.

SAFETY RULES, unchanged from the Auto Connect correction
--------------------------------------------------------
  * same map and same floor;
  * a normal destination attaches ONLY to hallway/junction points or to a
    point projected onto a corridor edge — never to another destination;
  * strict clear-line geometry is authoritative, and a line crossing more
    than one wall stroke is refused outright;
  * a corridor point stranded off the main walkable component is not a
    successful attachment;
  * nothing is ever fabricated: when no valid candidate exists the point
    stays unconnected and the reason is reported.
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
from models.map_model import Map
from models.room_model import Room
from models.route_edge_model import RouteEdge
from models.route_point_model import RoutePoint
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


# ─────────────────────────────────────────────────────────────────────
# Floor context — everything the search needs, read once per map
# ─────────────────────────────────────────────────────────────────────


class CorridorFloorContext:
    """
    One floor's corridor graph, prepared for repeated attachment queries.

    Built once and reused across every point on the floor: a bulk retry
    over sixty rooms must not re-read the graph sixty times, and the Auto
    Connect preview scans a whole map in one pass.
    """

    def __init__(
        self,
        *,
        map_item: Map,
        floor: Optional[int],
        all_points: List[RoutePoint],
        edges: List[RouteEdge],
        rooms: List[Room],
        bounds: Tuple[float, float, float],
    ) -> None:
        self.map_item = map_item
        self.map_id = str(map_item.id)
        self.floor = floor

        self.high_max_px, self.medium_max_px, self.hard_safety_max_px = bounds

        self.all_points = all_points
        self.edges = edges
        self.rooms = rooms

        self.points_by_id: Dict[str, RoutePoint] = {
            str(p.id): p for p in all_points
        }

        self.destinations = [
            p
            for p in all_points
            if p.point_type in DESTINATION_CAPABLE_POINT_TYPES
            and p.connector_id is None
            and p.x is not None
            and p.y is not None
        ]
        self.transit_points = [
            p
            for p in all_points
            if p.point_type in TRANSIT_CANDIDATE_POINT_TYPES
            and p.connector_id is None
            and p.x is not None
            and p.y is not None
        ]
        self.transit_by_id: Dict[str, RoutePoint] = {
            str(p.id): p for p in self.transit_points
        }
        self.transit_ids = set(self.transit_by_id)

        self.rooms_by_route_point_id: Dict[str, Room] = {
            r.route_point_id: r for r in rooms if r.route_point_id
        }
        self.rooms_by_id: Dict[str, Room] = {str(r.id): r for r in rooms}

        (
            self.component_root_by_id,
            self.main_component_root,
            self.transit_network_has_internal_edges,
        ) = _transit_components(self.transit_ids, edges)

        # Corridor EDGES, so a point beside the MIDDLE of a long corridor
        # run can attach even when neither endpoint node is near it.
        self.corridor_segments: List[Tuple[RouteEdge, RoutePoint, RoutePoint]] = []
        for edge in edges:
            if edge.edge_type != "walkway":
                continue
            if (
                edge.from_point_id not in self.transit_ids
                or edge.to_point_id not in self.transit_ids
            ):
                continue
            point_a = self.transit_by_id.get(edge.from_point_id)
            point_b = self.transit_by_id.get(edge.to_point_id)
            if not point_a or not point_b or point_a.floor != point_b.floor:
                continue
            self.corridor_segments.append((edge, point_a, point_b))

        self.min_node_gap_px = max(
            EDGE_SPLIT_MIN_NODE_GAP_FLOOR_PX,
            self.high_max_px * EDGE_SPLIT_MIN_NODE_GAP_FRACTION_OF_HIGH,
        )

        # Cell size = this map's hard safety ceiling, so a point's 3x3 cell
        # neighbourhood always covers every transit point within reach.
        self.grid = _SpatialGrid(self.hard_safety_max_px)
        for point in self.transit_points:
            self.grid.add(point)

        self.wall_mask_available = _get_wall_mask(self.map_id) is not None
        self.is_calibrated = bool(map_item.is_calibrated)
        self.scale = _get_scale_for_floor(
            map_item, floor if floor is not None else map_item.floor
        )

        # Any active edge at all touching a point — a warning signal only,
        # never evidence of connectivity (a stale Room-to-Room edge sets
        # it).
        self.has_any_edge: Dict[str, bool] = defaultdict(bool)
        for edge in edges:
            self.has_any_edge[edge.from_point_id] = True
            self.has_any_edge[edge.to_point_id] = True

    def is_graph_connected(self, point_id: str) -> bool:
        """Whether this corridor point belongs to the main walkable
        component. When no transit point is wired to any other there is no
        main component to be isolated from, so everything qualifies —
        which keeps a floor whose whole corridor is one hand-placed
        hallway point working."""
        if self.main_component_root is None:
            return True
        return self.component_root_by_id.get(point_id) == self.main_component_root


async def load_corridor_floor_context(
    map_item: Map,
    *,
    floor: Optional[int] = None,
    max_distance_px_override: Optional[float] = None,
) -> CorridorFloorContext:
    map_id = str(map_item.id)

    point_query: dict = {"map_id": map_id, "is_active": True}
    if floor is not None:
        point_query["floor"] = floor

    all_points = await RoutePoint.find(point_query).to_list()
    edges = await RouteEdge.find({"map_id": map_id, "is_active": True}).to_list()
    rooms = await Room.find({"map_id": map_id}).to_list()

    # ECS task storage is temporary; restore the normalized source image
    # once per context so wall checking is actually available.
    await _ensure_map_source_available(map_id)

    return CorridorFloorContext(
        map_item=map_item,
        floor=floor,
        all_points=all_points,
        edges=edges,
        rooms=rooms,
        bounds=_effective_bounds(map_item, max_distance_px_override),
    )


async def load_corridor_floor_context_by_map_id(
    map_id: str,
    *,
    floor: Optional[int] = None,
    max_distance_px_override: Optional[float] = None,
) -> Optional[CorridorFloorContext]:
    try:
        map_item = await Map.get(PydanticObjectId(map_id))
    except Exception:  # noqa: BLE001 — malformed id is a data problem
        map_item = None

    if not map_item:
        return None

    return await load_corridor_floor_context(
        map_item, floor=floor, max_distance_px_override=max_distance_px_override
    )


# ─────────────────────────────────────────────────────────────────────
# The search
# ─────────────────────────────────────────────────────────────────────

# Reasons a point could not be attached. Stable strings — the Auto Connect
# preview, the bulk retry and the tests all match on them.
REASON_NO_TRANSIT_POINTS = "no_transit_points_on_map"
REASON_TRANSIT_NOT_CONNECTED = "transit_points_not_connected_by_edges"
REASON_TOO_FAR = "no_transit_point_within_range"
REASON_BLOCKED_BY_WALL = "blocked_by_wall"
REASON_ISOLATED = "corridor_candidate_isolated"


def _floors_are_compatible(
    a: Optional[int], b: Optional[int], map_floor: Optional[int]
) -> bool:
    """
    Whether two points on this map may be joined by a walkway edge.

    Mirrors routes/route_edge_routes.calculate_edge_distance EXACTLY, so
    the search can never propose an attachment the edge layer would then
    refuse:

      * Map.floor set  — every RoutePoint on the map is on that floor BY
        CONSTRUCTION, and a raw comparison of the points' own `floor`
        fields is actively wrong for legacy points whose stored floor is
        null or stale relative to their Map;
      * Map.floor None — the older model where one Map hosts several
        floors through RoutePoint.floor alone, so RoutePoint.floor is the
        only source of truth and the raw comparison must apply.
    """
    if map_floor is not None:
        return True
    return a == b


class AttachmentSearch:
    """Result of looking for somewhere to attach ONE point."""

    def __init__(
        self,
        *,
        candidates: List[dict],
        blocked_count: int,
        isolated_count: int,
        nearest_found_px: Optional[float],
        reason: Optional[str],
    ) -> None:
        self.candidates = candidates
        self.blocked_count = blocked_count
        self.isolated_count = isolated_count
        self.nearest_found_px = nearest_found_px
        self.reason = reason

    @property
    def best(self) -> Optional[dict]:
        return self.candidates[0] if self.candidates else None


def find_attachment_candidates(
    context: CorridorFloorContext,
    point: RoutePoint,
    *,
    limit: int = 3,
    label_for: Optional[callable] = None,
) -> AttachmentSearch:
    """
    Every valid place `point` could attach to on this floor, best first.

    THE one candidate search. Corridor nodes and corridor-edge projections
    are ranked together; a normal destination can never see another
    destination because `transit_points` excludes them by point_type.

    `label_for(route_point) -> str` supplies human-facing names when the
    caller needs them (the Auto Connect review panel does; an automatic
    attach does not).
    """

    naming = label_for or (lambda p: p.name or str(p.id))
    point_id = str(point.id)
    px = float(point.x)
    py = float(point.y)

    raw: List[dict] = []

    # ── corridor NODES ────────────────────────────────────────────────
    for candidate in context.grid.nearby(px, py):
        candidate_id = str(candidate.id)
        if candidate_id == point_id:
            continue
        # A Map document can hold RoutePoints on more than one `floor`
        # (legacy data, vertical-connector transition points). Two points
        # sharing a map_id and a similar pixel position must never be
        # joined across a REAL floor difference.
        #
        # An unrecorded floor (None on either side) is not a real
        # difference — it is legacy data with no floor stamped on it, and
        # excluding it would strand every point on a pre-floor map. This
        # matches graph_connection_service.find_connection_candidates,
        # which only applies its floor filter when the point has one.
        if not _floors_are_compatible(
            candidate.floor, point.floor, context.map_item.floor
        ):
            continue

        distance_px = math.hypot(
            float(candidate.x) - px, float(candidate.y) - py
        )
        raw.append(
            {
                "target_type": "corridor_node",
                "candidate_key": candidate_id,
                "point_id": candidate_id,
                "corridor_edge_id": None,
                "name": naming(candidate),
                "point_type": candidate.point_type,
                "x": float(candidate.x),
                "y": float(candidate.y),
                "attachment_x": float(candidate.x),
                "attachment_y": float(candidate.y),
                "distance_px": distance_px,
                "priority_rank": transit_candidate_priority_rank(
                    candidate.point_type
                ),
                "graph_connected": context.is_graph_connected(candidate_id),
            }
        )

    # ── corridor EDGES ────────────────────────────────────────────────
    for edge, point_a, point_b in context.corridor_segments:
        if not _floors_are_compatible(
            point_a.floor, point.floor, context.map_item.floor
        ):
            continue

        ax, ay = float(point_a.x), float(point_a.y)
        bx, by = float(point_b.x), float(point_b.y)

        # Cheap bounding-box reject before the projection maths, so a bulk
        # scan stays linear in practice.
        if (
            px < min(ax, bx) - context.hard_safety_max_px
            or px > max(ax, bx) + context.hard_safety_max_px
            or py < min(ay, by) - context.hard_safety_max_px
            or py > max(ay, by) + context.hard_safety_max_px
        ):
            continue

        qx, qy, t, segment_length = _project_point_on_segment(px, py, ax, ay, bx, by)

        # A projection landing essentially on one of the edge's own
        # endpoints adds nothing — that node is already a candidate. This
        # is also what makes a repeated attach idempotent: once an edge has
        # been split, the new junction sits exactly where the next
        # projection would land, so the node wins and no second junction is
        # created.
        if (
            t * segment_length < context.min_node_gap_px
            or (1.0 - t) * segment_length < context.min_node_gap_px
        ):
            continue

        distance_px = math.hypot(qx - px, qy - py)

        raw.append(
            {
                "target_type": "corridor_edge",
                "candidate_key": f"edge:{edge.id}",
                "point_id": None,
                "corridor_edge_id": str(edge.id),
                "name": f"{naming(point_a)} ↔ {naming(point_b)}",
                "point_type": (
                    point_a.point_type
                    if transit_candidate_priority_rank(point_a.point_type)
                    <= transit_candidate_priority_rank(point_b.point_type)
                    else point_b.point_type
                ),
                "x": qx,
                "y": qy,
                "attachment_x": qx,
                "attachment_y": qy,
                "distance_px": distance_px,
                "priority_rank": min(
                    transit_candidate_priority_rank(point_a.point_type),
                    transit_candidate_priority_rank(point_b.point_type),
                ),
                # An edge IS the corridor graph; it counts as connected
                # exactly when its own component is the main one.
                "graph_connected": context.is_graph_connected(str(point_a.id)),
            }
        )

    nearest_found_px = (
        round(min(c["distance_px"] for c in raw), 2) if raw else None
    )

    within_safety = [
        c for c in raw if c["distance_px"] <= context.hard_safety_max_px
    ]

    # PRIORITY. Connected always beats isolated. Then distance — except
    # among candidates effectively equidistant with the nearest, where the
    # declared corridor/hallway -> junction -> other order decides. Outside
    # that tie window distance alone rules, so a hallway across the floor
    # never outranks a junction right outside the door.
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
                candidate["priority_rank"] if tied else 0,
                candidate["distance_px"],
            )

        within_safety.sort(key=_priority_sort_key)

    valid: List[dict] = []
    blocked_count = 0
    isolated_count = 0

    for candidate in within_safety:
        if not candidate["graph_connected"]:
            # A corridor point stranded off the walkable network is not a
            # successful attachment.
            isolated_count += 1
            continue

        doorway_crossing = False
        if context.wall_mask_available:
            is_clear, doorway_crossing = _attachment_is_clear(
                context.map_id,
                px,
                py,
                candidate["attachment_x"],
                candidate["attachment_y"],
            )
            if not is_clear:
                # Reject and try the next valid candidate — never connect
                # through a wall because it happens to be closer.
                blocked_count += 1
                continue

        distance_meters = (
            round(candidate["distance_px"] * context.scale, 2)
            if context.is_calibrated
            else None
        )
        valid.append(
            {
                **candidate,
                "distance_meters": distance_meters,
                "blocked_by_wall": False,
                "clear_line": True,
                "doorway_crossing": doorway_crossing,
            }
        )
        if len(valid) >= limit:
            break

    reason = None
    if not valid:
        # Each of these is a genuinely different problem with a different
        # fix; conflating them is what produced "no corridor point close
        # enough" for a room with a corridor drawn right beside it.
        if blocked_count:
            reason = REASON_BLOCKED_BY_WALL
        elif isolated_count:
            reason = REASON_ISOLATED
        elif not context.transit_points:
            reason = REASON_NO_TRANSIT_POINTS
        elif (
            not context.transit_network_has_internal_edges
            and len(context.transit_points) >= 2
        ):
            reason = REASON_TRANSIT_NOT_CONNECTED
        else:
            reason = REASON_TOO_FAR

    return AttachmentSearch(
        candidates=valid,
        blocked_count=blocked_count,
        isolated_count=isolated_count,
        nearest_found_px=nearest_found_px,
        reason=reason,
    )


# ─────────────────────────────────────────────────────────────────────
# Attaching (the only place outside Auto Connect's apply that writes)
# ─────────────────────────────────────────────────────────────────────

ATTACH_DESCRIPTION = "Auto attach: destination connected to corridor graph"


async def attach_point_to_corridor(
    point: RoutePoint,
    *,
    context: Optional[CorridorFloorContext] = None,
    refresh_context: bool = False,
) -> dict:
    """
    Attach ONE point to its floor's corridor graph, if a valid place
    exists.

    Returns:
        {
          "status": "attached" | "already_connected" | "pending",
          "reason": str | None,          # only when pending
          "edge_id": str | None,
          "junction_point_id": str | None,   # set when an edge was split
          "target_type": str | None,
          "distance_px": float | None,
        }

    IDEMPOTENT by construction:
      * a point that already reaches the walkable graph returns
        "already_connected" and writes nothing;
      * an existing duplicate edge is detected and reused;
      * after an edge split, the junction sits exactly where the next
        projection would land, so a repeat run picks the NODE and never
        creates a second junction.

    Never raises for a point that simply cannot be attached — that is
    "pending", not an error, and must never fail the save that triggered
    it.
    """

    from routes.route_edge_routes import (  # noqa: PLC0415 (deferred: circular)
        calculate_edge_distance,
        find_duplicate_edge,
    )
    from services.graph_connectivity_service import FloorGraphIndex

    result = {
        "status": "pending",
        "reason": None,
        "edge_id": None,
        "junction_point_id": None,
        "target_type": None,
        "distance_px": None,
    }

    if point.x is None or point.y is None:
        result["reason"] = "point_has_no_coordinates"
        return result

    if context is None or refresh_context:
        context = await load_corridor_floor_context_by_map_id(point.map_id)

    if context is None:
        result["reason"] = "map_not_found"
        return result

    point_id = str(point.id)

    # Already reaching the walkable graph? Then there is nothing to do —
    # this is what stops a repeated retry from stacking edges.
    connectivity = FloorGraphIndex(
        context.map_id, context.all_points, context.edges, context.rooms
    )
    if point_id in connectivity.points_by_id:
        connected, _reason = connectivity.connection_state(point_id)
        if connected:
            result["status"] = "already_connected"
            return result

    # ── SAME-PHYSICAL-LOCATION TWIN ───────────────────────────────────
    # Before the corridor search: a destination placed on the SAME spot as
    # an existing destination is two records of one physical place (a
    # "store" RoutePoint that already existed where an admin then places a
    # Room — point dedup does not merge them because the concrete
    # point_types differ), not a route through an unrelated room.
    #
    # logic/multi_floor_routing.py already recognises exactly this pair via
    # its own 6px coincidence rule, and
    # services/graph_connection_service.py allows exactly this link. It
    # must survive here too, or every such room is stranded (see
    # tests/test_navigation_redesign.py::test_selected_room_destination_is_not_blocked).
    twin_edge_id = await _link_same_location_twin(point, context)
    if twin_edge_id is not None:
        result["status"] = "attached"
        result["edge_id"] = twin_edge_id
        result["target_type"] = "same_physical_location"
        result["distance_px"] = 0.0
        return result

    search = find_attachment_candidates(context, point, limit=3)
    best = search.best

    if best is None:
        result["reason"] = search.reason
        return result

    target_point_id = best["point_id"]
    junction: Optional[RoutePoint] = None

    if best["target_type"] == "corridor_edge":
        try:
            corridor_edge = await RouteEdge.get(
                PydanticObjectId(best["corridor_edge_id"])
            )
        except Exception:  # noqa: BLE001
            corridor_edge = None

        if not corridor_edge or not corridor_edge.is_active:
            result["reason"] = "corridor_edge_no_longer_available"
            return result

        junction = await _split_corridor_edge_for_attachment(
            context.map_id,
            corridor_edge,
            float(best["attachment_x"]),
            float(best["attachment_y"]),
            calculate_edge_distance,
        )
        if junction is None:
            result["reason"] = "corridor_edge_split_failed"
            return result

        target_point_id = str(junction.id)
        result["junction_point_id"] = target_point_id

    duplicate = await find_duplicate_edge(
        map_id=context.map_id,
        from_point_id=point_id,
        to_point_id=target_point_id,
        edge_type="walkway",
    )
    if duplicate:
        result["status"] = "already_connected"
        result["edge_id"] = str(duplicate.id)
        result["target_type"] = best["target_type"]
        return result

    distance = await calculate_edge_distance(
        map_id=context.map_id,
        from_point_id=point_id,
        to_point_id=target_point_id,
        edge_type="walkway",
    )

    edge = RouteEdge(
        map_id=context.map_id,
        from_point_id=point_id,
        to_point_id=target_point_id,
        edge_type="walkway",
        distance=distance,
        is_bidirectional=True,
        is_accessible=True,
        description=ATTACH_DESCRIPTION,
    )
    await edge.insert()

    result["status"] = "attached"
    result["edge_id"] = str(edge.id)
    result["target_type"] = best["target_type"]
    result["distance_px"] = round(float(best["distance_px"]), 2)
    return result



async def _link_same_location_twin(
    point: RoutePoint, context: CorridorFloorContext
) -> Optional[str]:
    """
    Link `point` to a destination sitting at the same physical location,
    returning the edge id, or None when there is no such twin.

    Deliberately narrow: BOTH sides must be destination-capable and within
    SAME_PHYSICAL_LOCATION_TOLERANCE_PX on the same floor. A room even ten
    pixels away is a different room and is never linked.
    """

    from routes.route_edge_routes import (  # noqa: PLC0415 (deferred: circular)
        calculate_edge_distance,
        find_duplicate_edge,
    )
    from services.graph_connection_service import (
        SAME_PHYSICAL_LOCATION_TOLERANCE_PX,
    )

    if point.point_type not in DESTINATION_CAPABLE_POINT_TYPES:
        return None

    point_id = str(point.id)
    px, py = float(point.x), float(point.y)

    for other in context.destinations:
        other_id = str(other.id)
        if other_id == point_id or other.floor != point.floor:
            continue
        if (
            math.hypot(float(other.x) - px, float(other.y) - py)
            > SAME_PHYSICAL_LOCATION_TOLERANCE_PX
        ):
            continue

        duplicate = await find_duplicate_edge(
            map_id=context.map_id,
            from_point_id=point_id,
            to_point_id=other_id,
            edge_type="walkway",
        )
        if duplicate:
            return str(duplicate.id)

        edge = RouteEdge(
            map_id=context.map_id,
            from_point_id=point_id,
            to_point_id=other_id,
            edge_type="walkway",
            distance=await calculate_edge_distance(
                map_id=context.map_id,
                from_point_id=point_id,
                to_point_id=other_id,
                edge_type="walkway",
            ),
            is_bidirectional=True,
            is_accessible=True,
            description="Auto attach: same physical location",
        )
        await edge.insert()
        return str(edge.id)

    return None


async def attach_point_safely(point: RoutePoint) -> dict:
    """
    attach_point_to_corridor with every exception swallowed.

    Used by the save paths (Room creation, route-point creation, connector
    stop placement): a point that cannot be attached must still be SAVED.
    An attachment failure is never allowed to fail the create.
    """

    try:
        return await attach_point_to_corridor(point)
    except Exception as error:  # noqa: BLE001 — a save must never fail here
        return {
            "status": "pending",
            "reason": f"attachment_error: {error}",
            "edge_id": None,
            "junction_point_id": None,
            "target_type": None,
            "distance_px": None,
        }


# ─────────────────────────────────────────────────────────────────────
# Bulk retry
# ─────────────────────────────────────────────────────────────────────


async def retry_pending_attachments(
    map_id: str, *, floor: Optional[int] = None
) -> dict:
    """
    Attach every still-unconnected destination and vertical-connector stop
    on ONE map/floor.

    This is what makes the real admin workflow possible: place sixty room
    door points first, draw the corridor afterwards, then run this ONCE
    for the floor instead of reopening sixty rooms.

    Scope is always one map. There is deliberately no global variant.

    Returns:
        {
          "map_id", "scanned", "already_connected", "attached",
          "junctions_created", "still_pending",
          "pending": [{point_id, name, point_type, reason}],
          "warnings": [str],
        }
    """

    from services.graph_connectivity_service import FloorGraphIndex

    summary = {
        "map_id": map_id,
        "scanned": 0,
        "already_connected": 0,
        "attached": 0,
        "junctions_created": 0,
        "still_pending": 0,
        "pending": [],
        "warnings": [],
    }

    context = await load_corridor_floor_context_by_map_id(map_id, floor=floor)
    if context is None:
        summary["warnings"].append("Map not found.")
        return summary

    # Destinations plus connector stops — a stair or elevator stop is just
    # as useless floating off the horizontal graph as a room is.
    targets: List[RoutePoint] = list(context.destinations)
    targets.extend(
        p
        for p in context.all_points
        if p.connector_id is not None and p.x is not None and p.y is not None
    )
    if floor is not None:
        targets = [p for p in targets if p.floor == floor]

    summary["scanned"] = len(targets)

    connectivity = FloorGraphIndex(
        context.map_id, context.all_points, context.edges, context.rooms
    )

    needs_attachment: List[RoutePoint] = []
    for target in targets:
        connected, _reason = connectivity.connection_state(str(target.id))
        if connected:
            summary["already_connected"] += 1
        else:
            needs_attachment.append(target)

    # Each successful attachment changes the graph (an edge, sometimes a
    # junction), so the context is reloaded between attachments. That is
    # what lets a room attach to a junction another room's split just
    # created, instead of splitting the same edge twice.
    for target in needs_attachment:
        try:
            outcome = await attach_point_to_corridor(target, refresh_context=True)
        except Exception as error:  # noqa: BLE001 — one bad point never
            # aborts the batch
            summary["still_pending"] += 1
            summary["pending"].append(
                {
                    "point_id": str(target.id),
                    "name": target.name,
                    "point_type": target.point_type,
                    "reason": f"attachment_error: {error}",
                }
            )
            continue

        if outcome["status"] == "attached":
            summary["attached"] += 1
            if outcome["junction_point_id"]:
                summary["junctions_created"] += 1
        elif outcome["status"] == "already_connected":
            summary["already_connected"] += 1
        else:
            summary["still_pending"] += 1
            summary["pending"].append(
                {
                    "point_id": str(target.id),
                    "name": target.name,
                    "point_type": target.point_type,
                    "reason": outcome["reason"],
                }
            )

    return summary
