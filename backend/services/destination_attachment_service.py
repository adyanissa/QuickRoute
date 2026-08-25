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
    SAME_PHYSICAL_LOCATION_TOLERANCE_PX,
    _ensure_map_source_available,
    _get_wall_mask,
    has_clear_line,
)
from services.strict_geometry_service import (
    StrictWallMetrics,
    _is_wall_pixel_on_mask,
    get_strict_wall_metrics,
    strict_has_clear_line,
    strict_segment_profile,
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


class TransitComponents:
    """Connected components of one floor's corridor graph."""

    __slots__ = (
        "root_by_id",
        "members_by_root",
        "main_root",
        "has_any_internal_edge",
        "coincident_merges",
    )

    def __init__(
        self,
        root_by_id: Dict[str, str],
        members_by_root: Dict[str, List[str]],
        main_root: Optional[str],
        has_any_internal_edge: bool,
        coincident_merges: int,
    ) -> None:
        self.root_by_id = root_by_id
        self.members_by_root = members_by_root
        self.main_root = main_root
        self.has_any_internal_edge = has_any_internal_edge
        # How many pairs of corridor endpoints were joined because they sit
        # on the same physical spot. Reported, never silent.
        self.coincident_merges = coincident_merges

    @property
    def component_count(self) -> int:
        return len(self.members_by_root)

    @property
    def main_component_size(self) -> int:
        if self.main_root is None:
            return 0
        return len(self.members_by_root.get(self.main_root, ()))

    def size_of(self, point_id: str) -> int:
        root = self.root_by_id.get(point_id)
        if root is None:
            return 0
        return len(self.members_by_root.get(root, ()))


def _transit_components(
    transit_points: List[RoutePoint],
    edges: List[RouteEdge],
    *,
    map_floor: Optional[int] = None,
) -> TransitComponents:
    """
    Connected components of the CORRIDOR graph.

    Two points end up in the same component when either is true:

      1. an active walkway edge joins them and BOTH endpoints are transit
         points — the original rule, unchanged; or

      2. they sit within SAME_PHYSICAL_LOCATION_TOLERANCE_PX of each other
         on a compatible floor.

    Rule 2 fixes a real defect. Union used to happen only through explicit
    RouteEdges, so two corridor runs whose endpoints occupy the SAME
    physical spot but are two RoutePoint documents stayed two components
    forever, and every candidate in the smaller one was reported "off the
    walkable graph". That is reachable from ordinary use: point dedup only
    merges inside 6 px, and the draw panel's "Automatic graph merging: off"
    sets force_create and bypasses dedup entirely, so ending one draw
    session and starting the next a few pixels away splits the corridor.

    This is deliberately NOT a bridge across open space. The tolerance is
    the same 6 px coincidence rule graph_connection_service and
    logic/multi_floor_routing already use to decide that two records
    describe one place; it says "these are the same point", not "these are
    close enough to walk between". Two genuinely separate corridors a
    visible gap apart stay separate, and are reported as such.

    main_root is the largest component that actually contains more than one
    point, and None when no transit point is wired to any other. That
    distinction is deliberate: on a map whose entire corridor network is
    one hand-placed hallway point there is no multi-point component, so
    nothing is "isolated" and that point stays a perfectly good candidate.

    Ties are broken by the component's smallest member id, NOT by whichever
    root the union order happened to produce. The old code used
    `size > best_size`, so two equal-sized wings resolved by dict order and
    half the corridor was silently stranded — and which half was not stable
    between runs.
    """

    transit_ids = {str(p.id) for p in transit_points}

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

    # Coincident endpoints. Bucketed on a grid of the tolerance itself, so
    # this stays linear instead of comparing every pair.
    tolerance = SAME_PHYSICAL_LOCATION_TOLERANCE_PX
    buckets: Dict[Tuple[int, int], List[RoutePoint]] = defaultdict(list)
    for point in transit_points:
        buckets[
            (int(float(point.x) // tolerance), int(float(point.y) // tolerance))
        ].append(point)

    coincident_merges = 0
    for point in transit_points:
        point_id = str(point.id)
        px, py = float(point.x), float(point.y)
        cell_x, cell_y = int(px // tolerance), int(py // tolerance)

        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for other in buckets.get((cell_x + dx, cell_y + dy), ()):
                    other_id = str(other.id)
                    if other_id <= point_id:
                        continue
                    if not _floors_are_compatible(
                        point.floor, other.floor, map_floor
                    ):
                        continue
                    if (
                        math.hypot(float(other.x) - px, float(other.y) - py)
                        > tolerance
                    ):
                        continue
                    if union_find.find(point_id) == union_find.find(other_id):
                        continue
                    union_find.union(point_id, other_id)
                    coincident_merges += 1

    root_by_id: Dict[str, str] = {
        point_id: union_find.find(point_id) for point_id in transit_ids
    }

    members_by_root: Dict[str, List[str]] = defaultdict(list)
    for point_id, root in root_by_id.items():
        members_by_root[root].append(point_id)

    # Largest first; ties broken by the smallest member id, which does not
    # depend on the order the unions happened to run in.
    ranked = sorted(
        (
            (len(members), min(members), root)
            for root, members in members_by_root.items()
            if len(members) >= 2
        ),
        key=lambda entry: (-entry[0], entry[1]),
    )
    main_root: Optional[str] = ranked[0][2] if ranked else None

    return TransitComponents(
        root_by_id=root_by_id,
        members_by_root=dict(members_by_root),
        main_root=main_root,
        has_any_internal_edge=has_any_internal_edge,
        coincident_merges=coincident_merges,
    )


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


# ─────────────────────────────────────────────────────────────────────
# DOOR-AWARE ATTACHMENT
#
# THE PROBLEM, precisely. A destination marker placed at a real doorway
# was being rejected as wall-blocked with a corridor 47-83 px away. Two
# stacked causes, both measured:
#
#   1. RESOLUTION. The legacy validator builds its mask from a copy
#      downscaled to 900 px on the longest side, samples every 4 mask px,
#      and passes when blocked/(samples+1) <= 0.03. On a 75 px line at a
#      typical downscale that is SIX samples, so the 3% budget floors to
#      ZERO tolerated blocked samples. The first blocked sample only
#      becomes affordable somewhere past 235-616 source px depending on
#      image size — longer than any attachment worth making. One mask
#      pixel anywhere on the line, including the destination endpoint
#      itself, therefore rejects the candidate.
#
#   2. INDISTINGUISHABILITY AT THAT RESOLUTION. Measured on synthetic
#      plans at 3000x2000 with an 8 px wall stroke: on the 900 px mask a
#      2 px threshold line, a 4 px closed door leaf and the 8 px
#      structural wall ALL collapse to a blocked run of 1-2 samples. They
#      are genuinely not separable there. That is exactly why a generic
#      "forgive one wall crossing" rule is unsafe, and why this module
#      does not have one.
#
# WHAT THIS DOES INSTEAD. It re-measures the SAME line on the strict,
# full-resolution mask (services/strict_geometry_service, cap 4000 px,
# 2 px sampling) and compares each obstruction against the wall stroke
# thickness measured from that same drawing. On the same synthetic plans:
#
#     2 px threshold line     4.0 mask px      0.42 x stroke
#     4 px closed door leaf   6.0 mask px      0.63 x stroke
#     genuine wall           10.0 mask px      1.05 x stroke
#     room partition         10.0 mask px      1.05 x stroke
#     (measured stroke thickness: 9.55 mask px)
#
# The gap is real, deterministic and scale-free, and it exists ONLY at
# strict resolution. Thickness comes from the distance transform, so it is
# the structure's true caliper in every direction at once — an obliquely
# crossed wall cannot masquerade as a thin line.
#
# WHAT THIS IS NOT
#   * It does not weaken has_clear_line, strict_has_clear_line,
#     MAX_BLOCKED_SAMPLE_FRACTION, STRICT_BLOCKED_SAMPLE_FRACTION or
#     MAX_WALL_CROSSINGS. All are untouched, and the legacy gate still
#     runs FIRST on every candidate.
#   * It does not ignore the first blocked sample. Every obstruction must
#     individually prove it is sub-stroke, and any obstruction that is not
#     within the bounded radius of the destination disqualifies the
#     candidate outright.
#   * It does not move the stored point. `doorway_exit_point` is a
#     validation waypoint that exists for the duration of one check; the
#     RouteEdge that gets written still runs from the admin's own
#     coordinates, and Dijkstra sees exactly what it sees today.
#   * It never runs at all on a map with no readable source image, so
#     every existing test and every un-imaged map behaves as before.
# ─────────────────────────────────────────────────────────────────────

# An obstruction may be treated as a rasterised doorway artefact only when
# its caliper is at most this fraction of the caliper of THE WALL IT
# PIERCES, measured by probing parallel lines a little to either side.
#
# The reference is deliberately the LOCAL wall and not
# measure_wall_stroke_thickness's map-wide 80th percentile. Measured on a
# synthetic plan with an 8 px wall and three differently-drawn doors:
#
#                       caliper   vs local wall (9.55)   vs global (7.64)
#   2 px threshold        3.82           0.40                 0.50
#   4 px closed leaf      5.73           0.60                 0.75
#   the wall itself       9.55           1.00                 1.25
#
# The global percentile is dragged DOWN by every thin line on the drawing,
# which compresses the margin, and — much worse — it is biased toward the
# thickest walls, so a genuinely thin interior partition would measure well
# under it and be forgiven. Against its own local wall that same partition
# measures 1.00 and is refused. The local reference is both the wider
# margin and the safer one.
DOORWAY_MAX_THICKNESS_FRACTION_OF_LOCAL_WALL = 0.70

# Where to look for that local wall: parallel probes at these multiples of
# the map-wide stroke, to either side of the segment, far enough to clear a
# door opening but not so far as to wander into unrelated structure.
DOORWAY_WALL_PROBE_OFFSET_STROKES = (2.0, 4.0, 6.0, 9.0, 12.0, 16.0)
DOORWAY_WALL_PROBE_MAX_OFFSET_PX = 200.0
# A probe's obstruction only counts as "the same wall" when it sits at
# roughly the same depth along the segment as the crossing does.
DOORWAY_WALL_PROBE_DEPTH_TOLERANCE_STROKES = 3.0

# At most this many obstructions may be forgiven, and all of them must lie
# within the bounded exit radius of the destination. One threshold line is
# a doorway; entering and leaving something is not.
DOORWAY_MAX_LOCAL_RUNS = 1

# HARD SAFETY BOUNDS on how far the exit point may sit from the admin's own
# coordinates. Derived from the measured stroke thickness rather than a
# guessed pixel constant, because almost every map here is uncalibrated
# (Map.scale defaults to 1.0) and a fixed constant behaves completely
# differently at 150 and at 400 DPI. Stroke thickness scales with the
# render; a multiple of it does not. Every additional clamp below can only
# make the bound smaller.
DOORWAY_EXIT_STROKE_FACTOR = 3.0
DOORWAY_EXIT_MIN_PX = 6.0
DOORWAY_EXIT_MAX_PX = 60.0
DOORWAY_EXIT_MAX_FRACTION_OF_DIAGONAL = 0.012
# On a calibrated map the bound is additionally a real-world distance: a
# doorway is a doorway, not a room.
DOORWAY_EXIT_MAX_METERS = 1.0
# ...and never more than part of the way to the corridor, so resolving a
# doorway can never quietly become "walk most of the way there".
DOORWAY_EXIT_MAX_FRACTION_OF_CANDIDATE_DISTANCE = 0.5
# Clearance past the far edge of the artefact, as a fraction of the stroke.
DOORWAY_EXIT_CLEARANCE_FACTOR = 0.5

# ── RASTERISATION NOISE ───────────────────────────────────────────────
# A single sample of antialiasing where a line grazes a stroke at a shallow
# angle. Tolerated so that a long, genuinely clear connection is not
# rejected by one fringe pixel — but bounded BY CALIPER against this
# drawing's own wall stroke, so a real wall can never qualify however
# briefly the line clips it. At a measured stroke of 9.55 mask px this
# admits nothing thicker than 2.4 px: a 2 px door threshold measures 3.82
# and is NOT noise (it goes through full doorway resolution), and an 8 px
# wall measures 9.55.
#
# This REPLACES the fractional budgets rather than adding to them, and it
# does not grow with the length of the line.
NOISE_MAX_THICKNESS_FRACTION_OF_STROKE = 0.25
NOISE_MAX_RUN_FRACTION_OF_STROKE = 0.30
NOISE_MAX_RUNS = 2


def _significant_runs(runs, stroke_px: float):
    """Split a segment's obstructions into the ones that matter and a
    bounded count of rasterisation noise.

    An out-of-bounds run is never noise: leaving the image has no
    measurable thickness, and a path off the drawing is not a path.
    """

    thickness_limit = stroke_px * NOISE_MAX_THICKNESS_FRACTION_OF_STROKE
    length_limit = stroke_px * NOISE_MAX_RUN_FRACTION_OF_STROKE

    significant = []
    noise_count = 0

    for run in runs:
        is_noise = (
            not run.out_of_bounds
            and 0.0 < run.max_thickness_px <= thickness_limit
            and run.length_px <= length_limit
            and noise_count < NOISE_MAX_RUNS
        )
        if is_noise:
            noise_count += 1
        else:
            significant.append(run)

    return significant, noise_count


# Outcomes.
DOORWAY_MODE_NOT_NEEDED = "strict_clear"
DOORWAY_MODE_RESOLVED = "doorway_resolved"
DOORWAY_MODE_UNAVAILABLE = "strict_mask_unavailable"
DOORWAY_MODE_REFUSED = "refused"
DOORWAY_REASON_NOT_RESOLVED = "doorway_not_resolved"
DOORWAY_REASON_BLOCKED_AFTER = "blocked_after_doorway"


class DoorwayResolution:
    """The outcome of one door-aware re-check of one rejected candidate."""

    __slots__ = (
        "mode",
        "accepted",
        "reason",
        "exit_x",
        "exit_y",
        "snap_px",
        "crossing_thickness_px",
        "stroke_thickness_px",
        "clear_line_after",
        "wall_crossings_after",
        "noise_runs",
    )

    def __init__(
        self,
        *,
        mode: str,
        accepted: bool,
        reason: Optional[str] = None,
        exit_x: Optional[float] = None,
        exit_y: Optional[float] = None,
        snap_px: Optional[float] = None,
        crossing_thickness_px: Optional[float] = None,
        stroke_thickness_px: Optional[float] = None,
        clear_line_after: Optional[bool] = None,
        wall_crossings_after: Optional[int] = None,
        noise_runs: int = 0,
    ) -> None:
        self.mode = mode
        self.accepted = accepted
        self.reason = reason
        self.exit_x = exit_x
        self.exit_y = exit_y
        self.snap_px = snap_px
        self.crossing_thickness_px = crossing_thickness_px
        self.stroke_thickness_px = stroke_thickness_px
        self.clear_line_after = clear_line_after
        self.wall_crossings_after = wall_crossings_after
        # Grazing antialiasing samples tolerated on this line. Reported so
        # the allowance is never silent.
        self.noise_runs = noise_runs


def _doorway_exit_bound_px(
    *,
    metrics: StrictWallMetrics,
    canonical_diagonal_px: Optional[float],
    is_calibrated: bool,
    scale: float,
    candidate_distance_px: float,
) -> float:
    """The hard ceiling on how far a doorway exit point may sit from the
    admin's own coordinates, in full-resolution source pixels."""

    stroke_source_px = metrics.stroke_thickness_px / max(metrics.downscale, 1e-9)

    bound = DOORWAY_EXIT_STROKE_FACTOR * stroke_source_px
    bound = max(DOORWAY_EXIT_MIN_PX, min(DOORWAY_EXIT_MAX_PX, bound))

    if canonical_diagonal_px:
        bound = min(
            bound, canonical_diagonal_px * DOORWAY_EXIT_MAX_FRACTION_OF_DIAGONAL
        )

    if is_calibrated and scale > 0:
        bound = min(bound, DOORWAY_EXIT_MAX_METERS / scale)

    bound = min(
        bound,
        candidate_distance_px * DOORWAY_EXIT_MAX_FRACTION_OF_CANDIDATE_DISTANCE,
    )

    return max(0.0, bound)


def _local_wall_caliper_px(
    metrics: StrictWallMetrics,
    origin_x: float,
    origin_y: float,
    target_x: float,
    target_y: float,
    crossing_start_px: float,
    max_depth_mask_px: float,
) -> Optional[float]:
    """
    The caliper of the wall the segment is crossing, measured just to
    either side of the crossing, in mask pixels.

    Returns None when no probe finds any obstruction at a comparable depth
    — which means the segment is not crossing a wall at all, and nothing
    here may be called a doorway.
    """

    stroke_px = metrics.stroke_thickness_px
    downscale = max(metrics.downscale, 1e-9)

    dx = target_x - origin_x
    dy = target_y - origin_y
    length = math.hypot(dx, dy)
    if length <= 0:
        return None

    # Unit perpendicular, in full-resolution source pixels.
    perp_x, perp_y = -dy / length, dx / length
    depth_tolerance = DOORWAY_WALL_PROBE_DEPTH_TOLERANCE_STROKES * stroke_px

    # Probe only as deep as the crossing itself, never the whole segment.
    # The wall being characterised lies beside the crossing; on a 600 px
    # attachment, twelve full-length probes would cost thousands of sample
    # lookups per candidate for information that is all in the first few
    # dozen pixels.
    probe_depth_source_px = (
        max_depth_mask_px + depth_tolerance + stroke_px
    ) / downscale
    probe_ratio = min(1.0, probe_depth_source_px / length)
    probe_end_x = origin_x + dx * probe_ratio
    probe_end_y = origin_y + dy * probe_ratio

    best: Optional[float] = None

    for multiple in DOORWAY_WALL_PROBE_OFFSET_STROKES:
        offset_mask_px = min(
            multiple * stroke_px, DOORWAY_WALL_PROBE_MAX_OFFSET_PX
        )
        offset_source_px = offset_mask_px / downscale

        for sign in (1.0, -1.0):
            shift_x = perp_x * offset_source_px * sign
            shift_y = perp_y * offset_source_px * sign

            probe = strict_segment_profile(
                metrics,
                origin_x + shift_x,
                origin_y + shift_y,
                probe_end_x + shift_x,
                probe_end_y + shift_y,
            )

            for run in probe.runs:
                if run.out_of_bounds:
                    continue
                if run.start_px > max_depth_mask_px:
                    break
                if abs(run.start_px - crossing_start_px) > depth_tolerance:
                    continue
                if best is None or run.max_thickness_px > best:
                    best = run.max_thickness_px
                break

    return best


def resolve_doorway_exit_point(
    *,
    map_id: str,
    metrics: Optional[StrictWallMetrics],
    origin_x: float,
    origin_y: float,
    target_x: float,
    target_y: float,
    canonical_diagonal_px: Optional[float],
    is_calibrated: bool,
    scale: float,
) -> DoorwayResolution:
    """
    THE safety decision for one destination -> corridor line.

    Accepts ONLY when one of two things is provably true on the strict,
    full-resolution mask:

      * the line crosses nothing of substance there; or
      * the ONLY thing it crosses is a single sub-stroke obstruction
        sitting within the bounded exit radius of the destination — a
        rasterised threshold, door leaf or swing arc at the door the admin
        placed the marker on — AND the whole remaining segment beyond it is
        clear.

    Anything else is refused with a reason. Nothing is ever fabricated:
    when the geometry does not prove a doorway, the answer is
    `doorway_not_resolved`, not a guess.

    LENGTH-INDEPENDENT BY CONSTRUCTION. Every verdict below is made from
    RUNS — discrete obstructions and their calipers — never from a fraction
    of the sampled length. That is deliberate, and it is what closes the
    long-line bypass:

        legacy has_clear_line   3% of samples      625 px line, 8 px wall:
                                                   5 blocked / 157 = 3.2%... and
                                                   on the 900 px mask ~1/47 = 2.1%
                                                   -> ACCEPTED THROUGH A WALL
        strict_has_clear_line   3% of samples      same line at 2 px sampling:
                                                   5 blocked / 313 = 1.6%
                                                   -> ALSO ACCEPTED
        this function           one wall = one     -> REJECTED, at any length
                                run of ~one
                                stroke's caliper

    Both fractional rules get more permissive the longer the line is, which
    is exactly backwards for safety. Neither is consulted here.
    """

    if metrics is None:
        return DoorwayResolution(
            mode=DOORWAY_MODE_UNAVAILABLE,
            accepted=False,
            reason=DOORWAY_MODE_UNAVAILABLE,
        )

    stroke_px = metrics.stroke_thickness_px
    profile = strict_segment_profile(
        metrics, origin_x, origin_y, target_x, target_y
    )

    significant, noise_count = _significant_runs(profile.runs, stroke_px)

    # ── The line crosses nothing of substance ─────────────────────────
    # Nothing to resolve. A legacy rejection here was resolution, not a
    # wall: a 2 px mask dilation at downscale 0.3 is ~7 source px of
    # phantom thickness, and the legacy budget on a short line is zero
    # samples.
    if not significant:
        return DoorwayResolution(
            mode=DOORWAY_MODE_NOT_NEEDED,
            accepted=True,
            exit_x=origin_x,
            exit_y=origin_y,
            snap_px=0.0,
            crossing_thickness_px=0.0,
            stroke_thickness_px=stroke_px,
            clear_line_after=True,
            wall_crossings_after=0,
            noise_runs=noise_count,
        )

    candidate_distance_px = math.hypot(target_x - origin_x, target_y - origin_y)
    if candidate_distance_px <= 0:
        return DoorwayResolution(
            mode=DOORWAY_MODE_REFUSED,
            accepted=False,
            reason=DOORWAY_REASON_NOT_RESOLVED,
            stroke_thickness_px=stroke_px,
        )

    max_exit_px = _doorway_exit_bound_px(
        metrics=metrics,
        canonical_diagonal_px=canonical_diagonal_px,
        is_calibrated=is_calibrated,
        scale=scale,
        candidate_distance_px=candidate_distance_px,
    )
    # The radius in MASK pixels, since run positions are measured there.
    max_exit_mask_px = max_exit_px * metrics.downscale

    # ── Every obstruction must be endpoint-local ──────────────────────
    # An obstruction that starts beyond the exit radius is a wall between
    # the door and the corridor, not the door. Refuse outright rather than
    # forgiving the near one and hoping.
    if any(run.start_px > max_exit_mask_px for run in significant):
        return DoorwayResolution(
            mode=DOORWAY_MODE_REFUSED,
            accepted=False,
            reason=DOORWAY_REASON_BLOCKED_AFTER,
            stroke_thickness_px=stroke_px,
            wall_crossings_after=len(significant),
            noise_runs=noise_count,
        )

    if len(significant) > DOORWAY_MAX_LOCAL_RUNS:
        return DoorwayResolution(
            mode=DOORWAY_MODE_REFUSED,
            accepted=False,
            reason=DOORWAY_REASON_NOT_RESOLVED,
            stroke_thickness_px=stroke_px,
            wall_crossings_after=len(significant),
            noise_runs=noise_count,
        )

    crossing = significant[0]

    # An out-of-bounds run has no measurable thickness and is never thin.
    if crossing.out_of_bounds or crossing.max_thickness_px <= 0.0:
        return DoorwayResolution(
            mode=DOORWAY_MODE_REFUSED,
            accepted=False,
            reason=DOORWAY_REASON_NOT_RESOLVED,
            stroke_thickness_px=stroke_px,
            wall_crossings_after=len(significant),
            noise_runs=noise_count,
        )

    # ── THE DISCRIMINATOR ─────────────────────────────────────────────
    # How thick is this obstruction compared with the wall it pierces?
    #
    # The caliper comes from the distance transform, so it is the true
    # thickness of the structure in EVERY direction — a wall crossed at a
    # shallow angle produces a long run along the segment but its caliper
    # is still one wall stroke, and it is refused. `length_px` is checked
    # too, so an obliquely crossed thin line cannot be forgiven either.
    local_wall_px = _local_wall_caliper_px(
        metrics,
        origin_x,
        origin_y,
        target_x,
        target_y,
        crossing.start_px,
        max_exit_mask_px + stroke_px,
    )

    if local_wall_px is None:
        # Nothing wall-like beside the crossing at a comparable depth.
        # Then this is not a hole in a wall, and there is nothing here to
        # call a doorway.
        return DoorwayResolution(
            mode=DOORWAY_MODE_REFUSED,
            accepted=False,
            reason=DOORWAY_REASON_NOT_RESOLVED,
            crossing_thickness_px=round(crossing.max_thickness_px, 2),
            stroke_thickness_px=stroke_px,
            wall_crossings_after=len(significant),
            noise_runs=noise_count,
        )

    thickness_limit_px = (
        local_wall_px * DOORWAY_MAX_THICKNESS_FRACTION_OF_LOCAL_WALL
    )

    if (
        crossing.max_thickness_px > thickness_limit_px
        or crossing.length_px > thickness_limit_px
    ):
        return DoorwayResolution(
            mode=DOORWAY_MODE_REFUSED,
            accepted=False,
            reason=DOORWAY_REASON_NOT_RESOLVED,
            crossing_thickness_px=round(crossing.max_thickness_px, 2),
            stroke_thickness_px=stroke_px,
            wall_crossings_after=len(significant),
            noise_runs=noise_count,
        )

    # ── The exit point ────────────────────────────────────────────────
    # Just past the far edge of the artefact, plus a clearance margin.
    exit_along_mask_px = crossing.end_px + DOORWAY_EXIT_CLEARANCE_FACTOR * stroke_px
    if exit_along_mask_px > max_exit_mask_px or exit_along_mask_px >= profile.length_px:
        return DoorwayResolution(
            mode=DOORWAY_MODE_REFUSED,
            accepted=False,
            reason=DOORWAY_REASON_NOT_RESOLVED,
            crossing_thickness_px=round(crossing.max_thickness_px, 2),
            stroke_thickness_px=stroke_px,
        )

    ratio = exit_along_mask_px / profile.length_px
    exit_x = origin_x + (target_x - origin_x) * ratio
    exit_y = origin_y + (target_y - origin_y) * ratio
    snap_px = math.hypot(exit_x - origin_x, exit_y - origin_y)

    if snap_px > max_exit_px:
        return DoorwayResolution(
            mode=DOORWAY_MODE_REFUSED,
            accepted=False,
            reason=DOORWAY_REASON_NOT_RESOLVED,
            crossing_thickness_px=round(crossing.max_thickness_px, 2),
            stroke_thickness_px=stroke_px,
        )

    # The exit must land in free space, not in an antialiasing notch
    # inside the artefact.
    if _is_wall_pixel_on_mask(
        metrics.wall_mask, metrics.downscale, exit_x, exit_y, 0.0
    ):
        return DoorwayResolution(
            mode=DOORWAY_MODE_REFUSED,
            accepted=False,
            reason=DOORWAY_REASON_NOT_RESOLVED,
            crossing_thickness_px=round(crossing.max_thickness_px, 2),
            stroke_thickness_px=stroke_px,
        )

    # ── FINAL VALIDATION of the remaining segment ─────────────────────
    # Forgiveness stops at the doorway. From the exit point to the corridor
    # there must be NOTHING of substance at strict resolution — no second
    # thin line, and certainly no wall — however long that remaining run
    # is. Only rasterisation noise, bounded by caliper against this
    # drawing's own wall stroke, is tolerated.
    #
    # NEITHER fractional validator is consulted. The legacy one is the
    # instrument this stage exists to work around (on the 900 px mask the
    # exit still sits inside the ~7 source px dilation halo of the very
    # stroke just proven to be a door, so it would reject every doorway by
    # construction), and strict_has_clear_line's own 3% budget grows with
    # length in exactly the way that let a long line through a wall.
    remaining = strict_segment_profile(metrics, exit_x, exit_y, target_x, target_y)
    remaining_significant, remaining_noise = _significant_runs(
        remaining.runs, stroke_px
    )
    crossings_after = len(remaining_significant)

    if crossings_after > 0:
        return DoorwayResolution(
            mode=DOORWAY_MODE_REFUSED,
            accepted=False,
            reason=DOORWAY_REASON_BLOCKED_AFTER,
            exit_x=round(exit_x, 2),
            exit_y=round(exit_y, 2),
            snap_px=round(snap_px, 2),
            crossing_thickness_px=round(crossing.max_thickness_px, 2),
            stroke_thickness_px=stroke_px,
            clear_line_after=False,
            wall_crossings_after=crossings_after,
            noise_runs=noise_count + remaining_noise,
        )

    return DoorwayResolution(
        mode=DOORWAY_MODE_RESOLVED,
        accepted=True,
        exit_x=round(exit_x, 2),
        exit_y=round(exit_y, 2),
        snap_px=round(snap_px, 2),
        crossing_thickness_px=round(crossing.max_thickness_px, 2),
        stroke_thickness_px=stroke_px,
        clear_line_after=True,
        wall_crossings_after=0,
        noise_runs=noise_count + remaining_noise,
    )


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

    # Floor agreement, through the SHARED rule rather than a raw
    # comparison. A raw `!=` here refused to split a perfectly good corridor
    # edge whenever one of its endpoints was a legacy point whose own
    # `floor` was never stamped — on a Map that HAS a floor, every RoutePoint
    # on it is on that floor by construction, which is exactly what
    # _floors_are_compatible encodes and what calculate_edge_distance
    # already does. The search proposed such an attachment and this
    # returned None, so apply reported "rejected invalid" and the same
    # proposal came back on every reopen.
    #
    # The junction still inherits a concrete floor from an endpoint that
    # has one, so nothing downstream sees a less specific value than before.
    map_item = await Map.get(PydanticObjectId(map_id))
    map_floor = map_item.floor if map_item else None

    if not _floors_are_compatible(
        endpoints[0].floor, endpoints[1].floor, map_floor
    ):
        return None

    floor = next(
        (point.floor for point in endpoints if point.floor is not None),
        map_floor,
    )

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

        self.components = _transit_components(
            self.transit_points, edges, map_floor=map_item.floor
        )
        # Kept as attributes under their original names: callers and tests
        # outside this module read them.
        self.component_root_by_id = self.components.root_by_id
        self.main_component_root = self.components.main_root
        self.transit_network_has_internal_edges = (
            self.components.has_any_internal_edge
        )

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
        self.canonical_diagonal_px = _canonical_diagonal_px(map_item)

        # Strict, full-resolution geometry. Loaded on FIRST USE only: it is
        # needed exclusively to re-examine a candidate the legacy validator
        # already rejected, so a floor whose attachments all pass never
        # builds the expensive mask at all.
        self._strict_metrics: Optional[StrictWallMetrics] = None
        self._strict_metrics_loaded = False

        # Any active edge at all touching a point — a warning signal only,
        # never evidence of connectivity (a stale Room-to-Room edge sets
        # it).
        self.has_any_edge: Dict[str, bool] = defaultdict(bool)
        for edge in edges:
            self.has_any_edge[edge.from_point_id] = True
            self.has_any_edge[edge.to_point_id] = True

    @property
    def strict_metrics(self) -> Optional[StrictWallMetrics]:
        """The strict mask and its measurements, or None when this map has
        no readable source image. Built at most once per context."""
        if not self._strict_metrics_loaded:
            self._strict_metrics = get_strict_wall_metrics(self.map_id)
            self._strict_metrics_loaded = True
        return self._strict_metrics

    def is_graph_connected(self, point_id: str) -> bool:
        """Whether this corridor point belongs to the main walkable
        component. When no transit point is wired to any other there is no
        main component to be isolated from, so everything qualifies —
        which keeps a floor whose whole corridor is one hand-placed
        hallway point working."""
        if self.main_component_root is None:
            return True
        return self.component_root_by_id.get(point_id) == self.main_component_root

    def component_diagnostics(self) -> dict:
        """What the corridor graph actually looks like, for the preview.

        "corridor_component_isolated" on its own tells an admin nothing
        actionable; the size of the stray component and how far it sits
        from the main one is what tells them whether a point needs deleting
        or a corridor needs joining.
        """
        components = self.components
        stray_sizes = sorted(
            (
                len(members)
                for root, members in components.members_by_root.items()
                if root != components.main_root
            ),
            reverse=True,
        )
        return {
            "corridor_component_count": components.component_count,
            "corridor_main_component_size": components.main_component_size,
            "corridor_isolated_component_sizes": stray_sizes[:5],
            "corridor_coincident_merges": components.coincident_merges,
        }

    def distance_to_main_component_px(self, point_id: str) -> Optional[float]:
        """How far the nearest main-component corridor point is from this
        one. Reporting only — nothing bridges the gap."""
        components = self.components
        if components.main_root is None:
            return None
        point = self.transit_by_id.get(point_id)
        if point is None:
            return None

        best: Optional[float] = None
        for member_id in components.members_by_root.get(components.main_root, ()):
            other = self.transit_by_id.get(member_id)
            if other is None:
                continue
            distance = math.hypot(
                float(other.x) - float(point.x), float(other.y) - float(point.y)
            )
            if best is None or distance < best:
                best = distance
        return round(best, 2) if best is not None else None


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

# CANONICAL DIAGNOSTIC VOCABULARY.
#
# `reason` keeps the exact strings it has always emitted — the preview UI,
# the bulk retry and a dozen existing tests match on them, and renaming
# them would be a breaking API change for no functional gain.
# `final_reason` is the additional, canonical name for the same outcome,
# plus the two new door-aware outcomes that had no previous equivalent.
FINAL_REASON_BY_REASON = {
    REASON_NO_TRANSIT_POINTS: "no_corridor_candidate",
    REASON_TRANSIT_NOT_CONNECTED: "corridor_component_isolated",
    REASON_TOO_FAR: "no_corridor_candidate",
    REASON_BLOCKED_BY_WALL: "blocked_by_wall",
    REASON_ISOLATED: "corridor_component_isolated",
    DOORWAY_REASON_NOT_RESOLVED: "doorway_not_resolved",
    DOORWAY_REASON_BLOCKED_AFTER: "blocked_after_doorway",
    "nested_parent_no_point": "nested_parent_required",
    "nested_parent_not_pass_through": "nested_parent_not_pass_through",
}


def canonical_final_reason(reason: Optional[str]) -> Optional[str]:
    if reason is None:
        return None
    return FINAL_REASON_BY_REASON.get(reason, reason)


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
        diagnostics: Optional[dict] = None,
    ) -> None:
        self.candidates = candidates
        self.blocked_count = blocked_count
        self.isolated_count = isolated_count
        self.nearest_found_px = nearest_found_px
        self.reason = reason
        self.diagnostics = diagnostics or {}

    @property
    def best(self) -> Optional[dict]:
        return self.candidates[0] if self.candidates else None

    @property
    def final_reason(self) -> Optional[str]:
        return canonical_final_reason(self.reason)


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
    doorway_attempts = 0
    doorway_resolutions = 0
    strict_rescues = 0
    legacy_bypass_rejections = 0
    # The most informative door-aware failure seen, used only when nothing
    # valid was found. "blocked after the doorway" is more specific than
    # "no doorway here", so it wins.
    doorway_failure: Optional[str] = None
    nearest_isolated_id: Optional[str] = None

    for candidate in within_safety:
        if not candidate["graph_connected"]:
            # A corridor point stranded off the walkable network is not a
            # successful attachment.
            isolated_count += 1
            if nearest_isolated_id is None and candidate["point_id"]:
                nearest_isolated_id = candidate["point_id"]
            continue

        doorway_crossing = False
        doorway: Optional[DoorwayResolution] = None

        if context.wall_mask_available:
            legacy_clear, doorway_crossing = _attachment_is_clear(
                context.map_id,
                px,
                py,
                candidate["attachment_x"],
                candidate["attachment_y"],
            )

            metrics = context.strict_metrics

            if metrics is None:
                # No strict mask for this map. Behave exactly as before any
                # of this existed: nothing to measure means nothing to
                # forgive AND nothing to tighten.
                if not legacy_clear:
                    blocked_count += 1
                    continue
            else:
                # STRICT IS THE AUTHORITY — for every candidate, at every
                # length. The legacy verdict above is now diagnostics only.
                #
                # It used to be a shortcut: a candidate the legacy gate
                # ACCEPTED was attached with no further check. That is the
                # long-line bypass, and it was a real QuickRoute failure —
                # Auto Connect wired rooms straight through walls with it.
                # has_clear_line passes when under 3% of its samples are
                # blocked, and on the 900 px mask a 625 px line takes ~47
                # samples, so a genuine 8 px wall (one or two samples)
                # comes in under budget. The identical arithmetic defeats
                # strict_has_clear_line once a line is long enough.
                #
                # Both rules get MORE permissive as the line gets longer,
                # which is exactly backwards for safety.
                # resolve_doorway_exit_point decides from discrete
                # obstructions and their calipers instead, so its verdict
                # does not depend on length at all: one wall is one wall at
                # 60 px and at 600 px.
                doorway_attempts += 1
                doorway = resolve_doorway_exit_point(
                    map_id=context.map_id,
                    metrics=metrics,
                    origin_x=px,
                    origin_y=py,
                    target_x=candidate["attachment_x"],
                    target_y=candidate["attachment_y"],
                    canonical_diagonal_px=context.canonical_diagonal_px,
                    is_calibrated=context.is_calibrated,
                    scale=context.scale,
                )

                if not doorway.accepted:
                    blocked_count += 1
                    if legacy_clear:
                        # The bypass, caught. Counted separately because it
                        # is the difference between "Auto Connect found
                        # nothing here" and "Auto Connect would have routed
                        # this room through a wall".
                        legacy_bypass_rejections += 1
                    if doorway.reason == DOORWAY_REASON_BLOCKED_AFTER:
                        doorway_failure = DOORWAY_REASON_BLOCKED_AFTER
                    elif (
                        doorway_failure is None
                        and doorway.reason == DOORWAY_REASON_NOT_RESOLVED
                    ):
                        doorway_failure = DOORWAY_REASON_NOT_RESOLVED
                    continue

                if doorway.mode == DOORWAY_MODE_RESOLVED:
                    doorway_resolutions += 1
                    doorway_crossing = True
                elif not legacy_clear:
                    strict_rescues += 1

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
                # The doorway exit is a VALIDATION WAYPOINT, never a new
                # position: the edge written from this candidate still runs
                # from the admin's own coordinates.
                "doorway_resolved": bool(
                    doorway and doorway.mode == DOORWAY_MODE_RESOLVED
                ),
                "doorway_exit_x": doorway.exit_x if doorway else None,
                "doorway_exit_y": doorway.exit_y if doorway else None,
                "doorway_snap_px": doorway.snap_px if doorway else None,
                "doorway_crossing_thickness_px": (
                    doorway.crossing_thickness_px if doorway else None
                ),
                "wall_stroke_thickness_px": (
                    round(doorway.stroke_thickness_px, 2)
                    if doorway and doorway.stroke_thickness_px is not None
                    else None
                ),
                "clear_line_after_doorway": (
                    doorway.clear_line_after if doorway else None
                ),
                "wall_crossings_after_doorway": (
                    doorway.wall_crossings_after if doorway else None
                ),
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

    diagnostics = {
        "origin_x": round(px, 2),
        "origin_y": round(py, 2),
        "nearest_corridor_distance_px": nearest_found_px,
        "rejected_by_wall_count": blocked_count,
        "rejected_off_graph_count": isolated_count,
        "doorway_attempted_count": doorway_attempts,
        "doorway_resolved_count": doorway_resolutions,
        "strict_resolution_rescue_count": strict_rescues,
        # Candidates the legacy 3%-of-samples rule would have ACCEPTED and
        # the strict run-based rule refused. Non-zero means this map had
        # the long-line bypass in it.
        "legacy_bypass_rejected_count": legacy_bypass_rejections,
        # Only asked when the door-aware stage actually ran, so a floor
        # with no rejections never pays for building the strict mask.
        "strict_mask_available": (
            context.strict_metrics is not None if doorway_attempts else None
        ),
        **context.component_diagnostics(),
    }
    if nearest_isolated_id is not None:
        diagnostics["isolated_candidate_component_size"] = (
            context.components.size_of(nearest_isolated_id)
        )
        diagnostics["isolated_candidate_gap_to_main_px"] = (
            context.distance_to_main_component_px(nearest_isolated_id)
        )

    best_candidate = valid[0] if valid else None
    if best_candidate is not None:
        diagnostics.update(
            {
                "doorway_resolved": best_candidate["doorway_resolved"],
                "doorway_exit_x": best_candidate["doorway_exit_x"],
                "doorway_exit_y": best_candidate["doorway_exit_y"],
                "doorway_snap_px": best_candidate["doorway_snap_px"],
                "wall_stroke_thickness_px": best_candidate[
                    "wall_stroke_thickness_px"
                ],
                "doorway_crossing_thickness_px": best_candidate[
                    "doorway_crossing_thickness_px"
                ],
                "clear_line_after_doorway": best_candidate[
                    "clear_line_after_doorway"
                ],
                "wall_crossings_after_doorway": best_candidate[
                    "wall_crossings_after_doorway"
                ],
            }
        )
    else:
        diagnostics["doorway_resolved"] = False

    # `reason` deliberately keeps its long-standing coarse value —
    # "blocked_by_wall" — because the preview UI, the bulk retry and a dozen
    # existing tests match on it. `final_reason` is where the door-aware
    # stage says WHICH wall it was: the one at the door the marker sits on,
    # or one between that door and the corridor.
    diagnostics["final_reason"] = canonical_final_reason(
        doorway_failure
        if (reason == REASON_BLOCKED_BY_WALL and doorway_failure)
        else reason
    )

    return AttachmentSearch(
        candidates=valid,
        blocked_count=blocked_count,
        isolated_count=isolated_count,
        nearest_found_px=nearest_found_px,
        reason=reason,
        diagnostics=diagnostics,
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
