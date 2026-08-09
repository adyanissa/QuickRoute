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

    # Corridor point_type filtering fix — required reason distinction #1
    # ("no hallway/junction points exist") and #2 ("hallway/junction
    # points exist but are not connected by RouteEdges"). Computed once
    # per map, not per destination.
    #
    # #2 is only meaningful when there is more than one transit-type
    # point to potentially connect to another one — a lone hallway/
    # junction point has nothing else on the corridor network to be
    # "connected to" and remains a perfectly valid candidate purely on
    # its own proximity to a destination (see
    # test_no_candidate_outside_configured_threshold, which uses exactly
    # one hallway point and must keep getting reason
    # "no_transit_point_within_range" unchanged). With two or more
    # transit points, if literally none of them are wired to each other by
    # an active walkway RouteEdge, the admin has likely created isolated
    # dots rather than an actual corridor network. This is used ONLY as
    # the reason on the fallback "no valid candidate found nearby" path
    # below — never as a reason to reject a candidate that a destination
    # genuinely did find within range, so an independent, well-placed
    # single hallway point is never penalized just because some other,
    # unrelated transit point elsewhere on the same map isn't connected to
    # it.
    transit_network_has_internal_edges = True
    if len(transit_points) >= 2:
        transit_network_has_internal_edges = any(
            edge.edge_type == "walkway"
            and edge.from_point_id in transit_ids
            and edge.to_point_id in transit_ids
            for edge in edges
        )

    # Cell size = this map's hard safety ceiling, so a destination's 3x3
    # cell neighborhood is always guaranteed to fully cover every transit
    # point within hard_safety_max_px, regardless of where in a cell it
    # falls — same invariant as before, just sized per-map now instead of
    # off one fixed global constant.
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
                                "x": round(float(parent_point.x), 2),
                                "y": round(float(parent_point.y), 2),
                                "distance_px": round(distance_px, 2),
                                "distance_meters": distance_meters,
                                "blocked_by_wall": False,
                            }
                        ],
                        "is_nested_access": True,
                        "destination_x": round(float(destination.x), 2),
                        "destination_y": round(float(destination.y), 2),
                        "nearest_distance_px": round(distance_px, 2),
                        "max_hard_distance_px": round(hard_safety_max_px, 2),
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
                    "destination_x": round(float(destination.x), 2),
                    "destination_y": round(float(destination.y), 2),
                    "nearest_distance_px": None,
                    "max_hard_distance_px": round(hard_safety_max_px, 2),
                }
            )
            continue

        if has_valid_transit_edge.get(destination_id):
            summary["already_connected"] += 1
            continue

        # Reason distinction #1 (corridor point_type filtering fix):
        # checked BEFORE the geometric/wall search so the admin always
        # sees the most fundamental problem first. Reason #2 ("exist but
        # not connected by RouteEdges") is deliberately NOT an early exit
        # here — a destination with a genuinely close, valid hallway/
        # junction candidate must still be proposed even if that map
        # happens to also contain OTHER, unrelated disconnected transit
        # points elsewhere (see transit_network_has_internal_edges'
        # own docstring above); #2 is only used as the reason on the
        # "nothing valid found" fallback below, once the ordinary distance
        # search has already come up empty.
        if not transit_points:
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
                    "reason": "no_transit_points_on_map",
                    "has_existing_invalid_edges": bool(has_any_edge.get(destination_id)),
                    "is_calibrated": is_calibrated,
                    "proposed_candidate_id": None,
                    "candidates": [],
                    "destination_x": round(float(destination.x), 2),
                    "destination_y": round(float(destination.y), 2),
                    "nearest_distance_px": None,
                    "max_hard_distance_px": round(hard_safety_max_px, 2),
                }
            )
            continue

        nearby = grid.nearby(float(destination.x), float(destination.y))

        # Item 1/7/9: every same-map/same-floor hallway or junction is
        # scored here, NOT pre-filtered by a small fixed cutoff — the grid
        # neighborhood itself already only covers points within
        # hard_safety_max_px (its cell size), so `scored` is effectively
        # "every same-floor transit point within the hard safety ceiling,
        # plus a little overlap from neighboring cells." The hard-safety
        # cutoff and wall-blocking check are applied afterward, not here —
        # that split is what lets a rejected proposal still report the
        # nearest distance that WAS found, for diagnostics (item 2/8).
        scored: List[Tuple[RoutePoint, float]] = []
        for candidate in nearby:
            if str(candidate.id) == destination_id:
                continue
            # map_id/floor filtering fix: a Map document can still contain
            # RoutePoints recorded on more than one distinct `floor` value
            # (legacy data, or vertical-connector transition points) even
            # though this project's normal model is one floor per Map.
            # Two points merely sharing a map_id and a similar pixel
            # position must never be proposed as connected across a real
            # floor difference — that would silently draw a same-floor
            # "walkway" edge between two points that are not actually on
            # the same physical floor at all.
            if candidate.floor != destination.floor:
                continue
            distance_px = math.hypot(
                float(candidate.x) - float(destination.x),
                float(candidate.y) - float(destination.y),
            )
            scored.append((candidate, distance_px))

        scored.sort(key=lambda pair: pair[1])

        # The hard safety ceiling (item 2): candidates beyond this are
        # never proposed, no matter how "nearest" they are.
        within_safety = [
            (candidate, distance_px)
            for candidate, distance_px in scored
            if distance_px <= hard_safety_max_px
        ]

        valid_candidates: List[dict] = []
        for candidate, distance_px in within_safety:
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
                    "x": round(float(candidate.x), 2),
                    "y": round(float(candidate.y), 2),
                    "distance_px": round(distance_px, 2),
                    "distance_meters": distance_meters,
                    "blocked_by_wall": False,
                }
            )
            if len(valid_candidates) >= MAX_CANDIDATES_PER_PROPOSAL:
                break

        has_existing_invalid_edges = bool(has_any_edge.get(destination_id))

        if not valid_candidates:
            # Reason distinction #2 vs #3 (corridor point_type filtering
            # fix): once the ordinary distance/wall search has come up
            # empty, a disconnected corridor network (2+ transit points on
            # this map, none wired to each other by any walkway edge) is
            # reported as the more fundamental, more actionable diagnosis
            # than a plain "too far" — but only as a fallback here, never
            # as a reason to reject a candidate that WAS found within
            # range (see the transit_network_has_internal_edges docstring
            # above for why a lone/independent transit point must never be
            # penalized just because some other, unrelated transit point
            # elsewhere on the map isn't connected to it).
            no_candidate_reason = (
                "transit_points_not_connected_by_edges"
                if not transit_network_has_internal_edges
                else "no_transit_point_within_range"
            )

            # Diagnostics (item 2/8): even when nothing valid was found —
            # whether because every scored candidate was beyond the hard
            # safety ceiling, or wall-blocked — report the nearest distance
            # that WAS found by the grid scan, so the admin can see why
            # (e.g. "nearest hallway was 2400px away, hard cap is 1500px")
            # instead of just a bare "no candidate". None only when the
            # grid genuinely found nothing on this floor at all.
            nearest_found_px = round(scored[0][1], 2) if scored else None

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
                    "reason": no_candidate_reason,
                    "has_existing_invalid_edges": has_existing_invalid_edges,
                    "is_calibrated": is_calibrated,
                    "proposed_candidate_id": None,
                    "candidates": [],
                    "destination_x": round(float(destination.x), 2),
                    "destination_y": round(float(destination.y), 2),
                    "nearest_distance_px": nearest_found_px,
                    "max_hard_distance_px": round(hard_safety_max_px, 2),
                }
            )
            continue

        nearest_px = valid_candidates[0]["distance_px"]

        # Section 7: without a real wall mask for this map, the segment's
        # walkability was never actually checked — this must never be
        # reported as a distance-based high/medium/low confidence
        # proposal, only "needs_review", regardless of how close the
        # nearest candidate is.
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
                "destination_name": _display_name(destination, lang),
                "destination_point_type": destination.point_type,
                "status": "proposed",
                "confidence": confidence,
                "reason": None,
                "has_existing_invalid_edges": has_existing_invalid_edges,
                "is_calibrated": is_calibrated,
                "proposed_candidate_id": valid_candidates[0]["point_id"],
                "candidates": valid_candidates,
                "destination_x": round(float(destination.x), 2),
                "destination_y": round(float(destination.y), 2),
                "nearest_distance_px": nearest_px,
                "max_hard_distance_px": round(hard_safety_max_px, 2),
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