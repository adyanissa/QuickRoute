"""
Deterministic geometry for accepted semantic rooms — the READ-ONLY half.

THE PROBLEM THIS SOLVES
-----------------------
Semantic analysis deliberately carries no coordinates (see
FORBIDDEN_ROUTING_FIELD_NAMES in schemas/semantic_analysis_schema.py: the
AI is never asked where anything is, and is rejected if it answers). So
every accepted room arrives with a name and no position, and an admin has
had to click each one on the map. This module finds the position from the
DRAWING instead — never from the AI, and never by inventing one.

THIS IS NOT DOOR DETECTION
--------------------------
It must never be described as such, in code, in the UI, or in the report.
QuickRoute has no door, opening, threshold, or polygon data anywhere, and
this module creates none. It does not detect a room's shape, boundary or
entrance, and it never infers routing topology. It reads two things that
already exist:

  1. the bounding box of a text label PRINTED on the map
     (services/map_label_extraction_service — vector PDF text, or OCR),
  2. the wall mask the graph generator already builds from the same image
     (services/graph_connection_service).

and produces at most one (x, y) per room.

WHY A NUDGE IS NEEDED AT ALL
----------------------------
A room's label centre is a good guess at "somewhere inside this room", but
it is not a good arrival point: the label's own glyphs register in the
wall mask, a long label can overhang a wall, and a corner position can
have no line of sight to the corridor. So the search tries a small, FIXED
set of positions derived from the label's own box, in a FIXED order, and
takes the first one that passes every safety check.

It is bounded by construction, not by a stopping heuristic: every probe
must lie within NUDGE_BUDGET of the label's bounding box, and the budget
is derived from the label's own text height and hard-capped. The search
cannot walk away from the label looking for somewhere that works.

WHEN IT REFUSES — WHICH IS OFTEN, ON PURPOSE
--------------------------------------------
  * no wall mask (no processed source image)  -> needs_arrival_confirmation
  * no label matches this room                -> no_label_match
  * two labels match equally well             -> ambiguous_label
  * no probe is off-wall AND has a clear line
    to a corridor point within the existing
    hard safety distance                      -> no_safe_graph_connection

A refusal costs one admin click. A wrong placement is silently wrong
forever. Note in particular that has_clear_line() FAILS OPEN — it returns
True when there is no mask to check against — so this module verifies
wall_mask_available() FIRST and refuses outright without one, rather than
reading that True as evidence of a clear path.

WRITES
------
None. This module never calls insert()/save()/delete() on anything. The
positions it suggests are applied through the EXISTING destination apply
endpoint, exactly as if the admin had clicked them, which keeps
auto-connect, room sync, and QR issuance on the one graph-write path they
already use.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

from beanie import PydanticObjectId

from constants.route_point_types import TRANSIT_CANDIDATE_POINT_TYPES
from logic.instruction_generator import resolve_localized_display_name
from models.map_model import Map
from models.route_point_model import RoutePoint
from services.auto_connect_destinations_service import (
    _confidence_tier,
    _effective_bounds,
)
from services.graph_connection_service import (
    _ensure_map_source_available,
    has_clear_line,
    is_wall_pixel,
    wall_mask_available,
)
from services.map_label_extraction_service import (
    LabelExtractionResult,
    MapLabel,
    extract_map_labels,
    extract_room_number,
    normalize_label_text,
)
from services.semantic_destination_service import preview_semantic_destinations
from services.semantic_label_matching_service import (
    LabelMatch,
    match_entity_to_label,
)


# ---------------------------------------------------------------
# Bounds. Every one of these is a hard limit, not a starting value
# the search is allowed to grow.
# ---------------------------------------------------------------

# The nudge budget is this multiple of the matched label's own text
# height. A label's height is the only scale information the drawing
# gives us for free, and it tracks the drawing's zoom: a 3x-text-height
# reach is a small step on any map, at any resolution.
NUDGE_LABEL_HEIGHT_MULTIPLE = 3.0

# ...clamped into this range regardless, so a freak 2px-high OCR box
# cannot collapse the budget to nothing and a huge title block cannot
# turn it into a floor-wide search.
NUDGE_MIN_PX = 24.0
NUDGE_ABSOLUTE_MAX_PX = 120.0

# Probes along the ray to the corridor candidate are taken at this
# spacing. Fixed, so the result is reproducible.
NUDGE_STEP_PX = 8.0

# Each bbox edge midpoint is pushed this far outward (as a multiple of
# label height) to clear the printed glyphs themselves.
EDGE_MARGIN_LABEL_HEIGHT_MULTIPLE = 0.75

# A suggested point must be at least this far (source pixels) from any
# detected wall. Small — this is "not standing in the wall", not a
# clearance corridor.
WALL_CLEARANCE_PX = 6.0

# How many corridor candidates are probed per room, nearest first.
MAX_CANDIDATES_PROBED = 3

# Geometry confidence weighting.
MAX_NUDGE_CONFIDENCE_PENALTY = 0.4
DISTANCE_TIER_FACTOR = {"high": 1.0, "medium": 0.85, "low": 0.7}
OCR_GEOMETRY_FACTOR = 0.9   # an OCR box is less precise than vector text


class GeometryValidator:
    """
    The three wall-geometry primitives this service depends on, bundled so
    a caller can supply a different implementation.

    The default is the established legacy pair from
    graph_connection_service, so every existing caller — the admin's
    auto-place preview — behaves exactly as it did before this indirection
    existed. The automatic navigation-build pipeline injects the STRICT
    high-resolution validator instead, because the legacy mask downscales
    to 900 px and cannot see thin interior walls, and a coordinate no
    human reviewed must not rest on a check that coarse.
    """

    def __init__(self, mask_available=None, wall_pixel=None, clear_line=None):
        self._mask_available = mask_available or wall_mask_available
        self._wall_pixel = wall_pixel or is_wall_pixel
        self._clear_line = clear_line or has_clear_line

    def mask_available(self, map_id: str) -> bool:
        return bool(self._mask_available(map_id))

    def is_wall_pixel(self, map_id, x, y, radius_px=0.0):
        return self._wall_pixel(map_id, x, y, radius_px)

    def has_clear_line(self, map_id, x1, y1, x2, y2):
        result = self._clear_line(map_id, x1, y1, x2, y2)
        # The strict validator is tri-state and returns None when it
        # cannot decide. None is never a pass.
        return result is True


DEFAULT_GEOMETRY = GeometryValidator()


# =========================================================
# Geometry helpers
# =========================================================


def _distance_to_box(x: float, y: float, label: MapLabel) -> float:
    """
    Distance from (x, y) to the label's bounding box; 0 inside it.

    The nudge budget is measured against the BOX, not the centre, so a
    long label does not get a bigger effective search area than a short
    one — the reach beyond the printed text is the same either way.
    """

    dx = max(label.x0 - x, 0.0, x - label.x1)
    dy = max(label.y0 - y, 0.0, y - label.y1)
    return math.hypot(dx, dy)


def _nudge_budget_px(label: MapLabel) -> float:
    return min(
        NUDGE_ABSOLUTE_MAX_PX,
        max(NUDGE_MIN_PX, label.height * NUDGE_LABEL_HEIGHT_MULTIPLE),
    )


def _edge_midpoints(label: MapLabel) -> List[Tuple[float, float]]:
    """
    The midpoint of each side of the label box, pushed outward by a
    fraction of the text height. Fixed order — up, down, left, right —
    so the same map always produces the same answer.
    """

    margin = max(1.0, label.height * EDGE_MARGIN_LABEL_HEIGHT_MULTIPLE)
    cx, cy = label.center_x, label.center_y

    return [
        (cx, label.y0 - margin),
        (cx, label.y1 + margin),
        (label.x0 - margin, cy),
        (label.x1 + margin, cy),
    ]


def _ray_probes(
    label: MapLabel,
    target_x: float,
    target_y: float,
    budget: float,
) -> List[Tuple[float, float]]:
    """
    Positions stepping from the label centre toward one corridor
    candidate, stopping the moment they leave the budget or reach the
    candidate. This is the probe that actually gets a room's arrival
    point out from under its own label and into open floor.
    """

    ax, ay = label.center_x, label.center_y
    dx, dy = target_x - ax, target_y - ay
    distance = math.hypot(dx, dy)

    if distance <= NUDGE_STEP_PX:
        return []

    ux, uy = dx / distance, dy / distance

    probes: List[Tuple[float, float]] = []
    travelled = NUDGE_STEP_PX

    while travelled < distance:
        px, py = ax + ux * travelled, ay + uy * travelled

        if _distance_to_box(px, py, label) > budget:
            break

        probes.append((px, py))
        travelled += NUDGE_STEP_PX

    return probes


def _probe_sequence(
    label: MapLabel,
    candidate: RoutePoint,
    budget: float,
) -> List[Tuple[str, float, float]]:
    """
    Every position tried for one (label, candidate) pair, in the fixed
    order they are tried in: the label centre first (no nudge at all is
    always preferable), then out along the ray toward the corridor, then
    the label's own edge midpoints.
    """

    sequence: List[Tuple[str, float, float]] = [
        ("label_center", label.center_x, label.center_y)
    ]

    sequence.extend(
        ("nudge_toward_corridor", px, py)
        for px, py in _ray_probes(
            label, float(candidate.x), float(candidate.y), budget
        )
    )

    sequence.extend(
        ("label_edge_midpoint", px, py)
        for px, py in _edge_midpoints(label)
        if _distance_to_box(px, py, label) <= budget
    )

    return sequence


def _bearing_deg(from_x: float, from_y: float, to_x: float, to_y: float) -> float:
    """Compass-style bearing in image space (0 = up/north, clockwise)."""

    dx, dy = to_x - from_x, to_y - from_y

    if dx == 0 and dy == 0:
        return 0.0

    # Image y grows downward, so "up" is -dy.
    return round((math.degrees(math.atan2(dx, -dy)) + 360.0) % 360.0, 1)


def _geometry_confidence(
    nudge_px: float,
    budget: float,
    tier: str,
    label_source: str,
    label_confidence: float,
) -> float:
    nudge_ratio = min(1.0, nudge_px / budget) if budget > 0 else 1.0
    score = 1.0 - MAX_NUDGE_CONFIDENCE_PENALTY * nudge_ratio
    score *= DISTANCE_TIER_FACTOR.get(tier, 0.7)

    if label_source == "ocr":
        score *= OCR_GEOMETRY_FACTOR
        score *= max(0.5, min(1.0, label_confidence))

    return round(max(0.0, min(1.0, score)), 3)


# =========================================================
# One room
# =========================================================


def _place_one(
    map_id: str,
    label: MapLabel,
    candidates: Sequence[Tuple[RoutePoint, float]],
    bounds: Tuple[float, float, float],
    geometry: "GeometryValidator" = None,
) -> Dict[str, Any]:
    """
    The whole safety gate for one matched room, in one place.

    `candidates` is (corridor point, distance from the label centre),
    nearest first, already filtered to the same map and floor and to the
    existing hard safety ceiling. Returns a dict the caller folds into
    diagnostics; `accepted` is None on every refusal.
    """

    geometry = geometry or DEFAULT_GEOMETRY
    high_max_px, medium_max_px, hard_safety_max_px = bounds

    budget = _nudge_budget_px(label)
    rejections: List[str] = []
    probed = 0

    for candidate, _label_distance in candidates[:MAX_CANDIDATES_PROBED]:
        cx, cy = float(candidate.x), float(candidate.y)

        for rule, px, py in _probe_sequence(label, candidate, budget):
            probed += 1

            on_wall = geometry.is_wall_pixel(map_id, px, py, WALL_CLEARANCE_PX)

            if on_wall is None:
                # Mask vanished mid-scan (source file removed). Refuse the
                # whole room rather than continuing without the check.
                return {
                    "accepted": None,
                    "budget": budget,
                    "probed": probed,
                    "rejections": rejections
                    + ["wall_mask_became_unavailable"],
                    "candidate_on_wall": None,
                    "clear_line_passed": None,
                }

            if on_wall:
                rejections.append(f"{rule}:on_wall")
                continue

            distance_to_candidate = math.hypot(cx - px, cy - py)

            if distance_to_candidate > hard_safety_max_px:
                rejections.append(f"{rule}:beyond_hard_safety_distance")
                continue

            if distance_to_candidate < 1.0:
                rejections.append(f"{rule}:coincides_with_corridor_point")
                continue

            if not geometry.has_clear_line(map_id, px, py, cx, cy):
                rejections.append(f"{rule}:blocked_by_wall")
                continue

            nudge_px = math.hypot(px - label.center_x, py - label.center_y)
            tier = _confidence_tier(
                distance_to_candidate, high_max_px, medium_max_px
            )

            return {
                "accepted": {
                    "x": round(px, 2),
                    "y": round(py, 2),
                    "rule": rule,
                    "nudge_px": round(nudge_px, 2),
                    "nudge_deg": _bearing_deg(
                        label.center_x, label.center_y, px, py
                    ),
                    "candidate": candidate,
                    "distance_px": round(distance_to_candidate, 2),
                    "tier": tier,
                },
                "budget": budget,
                "probed": probed,
                "rejections": rejections,
                "candidate_on_wall": False,
                "clear_line_passed": True,
            }

    return {
        "accepted": None,
        "budget": budget,
        "probed": probed,
        "rejections": rejections,
        "candidate_on_wall": None,
        "clear_line_passed": False if probed else None,
    }


# =========================================================
# Entry point
# =========================================================


def _corridor_points_for(
    points: Sequence[RoutePoint], floor: Optional[int]
) -> List[RoutePoint]:
    return [
        point
        for point in points
        if point.is_active
        and point.point_type in TRANSIT_CANDIDATE_POINT_TYPES
        and (floor is None or point.floor == floor)
    ]


def _candidate_name(point: RoutePoint, lang: str) -> str:
    resolved = resolve_localized_display_name(
        point.name,
        display_name=point.display_name,
        display_name_en=point.display_name_en,
        display_name_ar=point.display_name_ar,
        display_name_he=point.display_name_he,
        is_auto_generated=point.is_auto_generated,
        lang=lang,
    )
    return resolved or point.name or str(point.id)


def _best_name(proposal: Dict[str, Any]) -> Optional[str]:
    for key in ("name_en", "name_original", "name_ar", "name_he"):
        value = proposal.get(key)
        if value:
            return str(value)
    return None


def _empty_diagnostics(**overrides: Any) -> Dict[str, Any]:
    diagnostics: Dict[str, Any] = {
        "wall_mask_available": False,
        "candidates_considered": 0,
        "positions_probed": 0,
        "rejections": [],
        "tied_label_texts": [],
    }
    diagnostics.update(overrides)
    return diagnostics


def _match_diagnostics(match: LabelMatch) -> Dict[str, Any]:
    diagnostics: Dict[str, Any] = {
        "matching_rule": match.rule,
        "matched_name": match.matched_name,
        "matched_language": match.matched_language,
        "tied_label_texts": list(match.tied_label_texts),
    }

    if match.label is not None:
        diagnostics.update(
            {
                "matched_label": match.label.text,
                "label_source": match.label.source,
                "label_bbox": [
                    round(match.label.x0, 2),
                    round(match.label.y0, 2),
                    round(match.label.x1, 2),
                    round(match.label.y1, 2),
                ],
                "label_center": [
                    round(match.label.center_x, 2),
                    round(match.label.center_y, 2),
                ],
                "label_ocr_confidence": round(match.label.confidence, 3),
                "anchor_x": round(match.label.center_x, 2),
                "anchor_y": round(match.label.center_y, 2),
            }
        )

    return diagnostics


async def preview_destination_auto_placement(
    map_id: str,
    *,
    item_external_ids: Optional[List[str]] = None,
    lang: str = "en",
    corridor_candidates: Optional[Sequence[Any]] = None,
    geometry: Optional["GeometryValidator"] = None,
) -> Dict[str, Any]:
    """
    Read-only. Returns the AutoPlacementPreviewResponse shape.

    Reuses preview_semantic_destinations() as its input rather than
    re-deriving which items are accepted — the two previews must never
    disagree about what is eligible, and there is exactly one place that
    decision is made.

    `corridor_candidates` and `geometry` exist for the automatic
    navigation-build pipeline and BOTH DEFAULT TO TODAY'S BEHAVIOR when
    omitted, so the admin-facing endpoint is unchanged.

    Why they are needed: this service can only validate an arrival point
    against corridor RoutePoints that already exist in the database. On a
    freshly uploaded map there are none, so every room returns
    `no_safe_graph_connection` and the zero-touch flow cannot start — the
    corridor graph needs arrival points as semantic seeds, and arrival
    points need a corridor graph to be validated against. Injecting a
    provisional in-memory graph as the candidate set breaks that cycle
    without ever persisting it.
    """

    summary = {
        "scanned": 0,
        "auto_connectable": 0,
        "needs_arrival_confirmation": 0,
        "ambiguous_label": 0,
        "no_label_match": 0,
        "no_safe_graph_connection": 0,
        "already_placed": 0,
    }
    proposals_out: List[Dict[str, Any]] = []
    warnings: List[str] = []

    map_item = await Map.get(PydanticObjectId(map_id))
    if not map_item:
        return {
            "publication_id": None,
            "label_source": "unavailable",
            "label_source_reason": "Map not found.",
            "label_count": 0,
            "wall_mask_available": False,
            "summary": summary,
            "proposals": proposals_out,
            "warnings": warnings,
        }

    destination_preview = await preview_semantic_destinations(
        map_id=map_id, item_external_ids=item_external_ids, lang=lang
    )
    warnings.extend(destination_preview.get("warnings") or [])

    labels: LabelExtractionResult = extract_map_labels(map_item)

    geometry = geometry or DEFAULT_GEOMETRY

    # Restore the source PNG before asking whether a wall mask exists — an
    # ECS restart must not silently turn every room into a refusal.
    await _ensure_map_source_available(map_id)
    mask_ok = geometry.mask_available(map_id)

    if not mask_ok:
        warnings.append(
            "This map has no processed source image, so wall checking is "
            "unavailable and no location can be suggested automatically. "
            "Every destination must be placed by hand."
        )

    if not labels.available and labels.reason:
        warnings.append(labels.reason)

    if corridor_candidates is None:
        all_points = await RoutePoint.find({"map_id": map_id}).to_list()
        corridor_points = _corridor_points_for(all_points, map_item.floor)
    else:
        corridor_points = _corridor_points_for(
            list(corridor_candidates), map_item.floor
        )

    if mask_ok and labels.available and not corridor_points:
        warnings.append(
            "This map has no hallway or junction route points yet, so there "
            "is nothing for a suggested location to connect to."
        )

    bounds = _effective_bounds(map_item, None)
    hard_safety_max_px = bounds[2]

    for proposal in destination_preview.get("proposals") or []:
        if proposal.get("excluded") or proposal.get("room_action") == "skip":
            continue

        summary["scanned"] += 1

        name = _best_name(proposal)
        base: Dict[str, Any] = {
            "semantic_item_id": proposal.get("semantic_item_id"),
            "map_id": map_id,
            "floor": proposal.get("floor"),
            "room_name": name,
            "room_number": extract_room_number(normalize_label_text(name)),
            "matched_room_id": proposal.get("matched_room_id"),
            "placement_source": "needs_manual_placement",
            "semantic_match_confidence": 0.0,
            "geometry_confidence": 0.0,
            "suggested_room_point": None,
            "suggested_arrival_point": None,
            "matched_graph_element": None,
        }

        # Already has a trustworthy coordinate — never re-place it.
        if not proposal.get("needs_location_review"):
            summary["already_placed"] += 1
            proposals_out.append(
                {
                    **base,
                    "status": "needs_arrival_confirmation",
                    "placement_source": proposal.get("placement_source")
                    or "existing_route_point",
                    "diagnostics": _empty_diagnostics(
                        wall_mask_available=mask_ok
                    ),
                    "message": (
                        "This destination already has a map location — it was "
                        "left exactly as it is."
                    ),
                }
            )
            continue

        if not mask_ok:
            summary["needs_arrival_confirmation"] += 1
            proposals_out.append(
                {
                    **base,
                    "status": "needs_arrival_confirmation",
                    "diagnostics": _empty_diagnostics(),
                    "message": (
                        "No wall data is available for this map, so no "
                        "location can be verified as safe. Place this one on "
                        "the map."
                    ),
                }
            )
            continue

        if not labels.available:
            summary["needs_arrival_confirmation"] += 1
            proposals_out.append(
                {
                    **base,
                    "status": "needs_arrival_confirmation",
                    "diagnostics": _empty_diagnostics(
                        wall_mask_available=True
                    ),
                    "message": labels.reason
                    or "No text labels could be read from this map.",
                }
            )
            continue

        match = match_entity_to_label(proposal, labels.labels)

        if match.status == "ambiguous_label":
            summary["ambiguous_label"] += 1
            proposals_out.append(
                {
                    **base,
                    "status": "ambiguous_label",
                    "diagnostics": _empty_diagnostics(
                        wall_mask_available=True, **_match_diagnostics(match)
                    ),
                    "message": match.reason,
                }
            )
            continue

        if not match.matched:
            summary["no_label_match"] += 1
            proposals_out.append(
                {
                    **base,
                    "status": "no_label_match",
                    "diagnostics": _empty_diagnostics(
                        wall_mask_available=True, **_match_diagnostics(match)
                    ),
                    "message": match.reason
                    or "No label on this map matches this destination.",
                }
            )
            continue

        label = match.label
        assert label is not None  # narrowed by match.matched

        ranked: List[Tuple[RoutePoint, float]] = []
        for point in corridor_points:
            distance = math.hypot(
                float(point.x) - label.center_x,
                float(point.y) - label.center_y,
            )
            if distance <= hard_safety_max_px:
                ranked.append((point, distance))
        ranked.sort(key=lambda pair: pair[1])

        outcome = _place_one(map_id, label, ranked, bounds, geometry)

        diagnostics = _empty_diagnostics(
            wall_mask_available=True,
            candidates_considered=min(len(ranked), MAX_CANDIDATES_PROBED),
            positions_probed=outcome["probed"],
            rejections=outcome["rejections"],
            nudge_budget_px=round(outcome["budget"], 2),
            candidate_on_wall=outcome["candidate_on_wall"],
            clear_line_passed=outcome["clear_line_passed"],
            **_match_diagnostics(match),
        )

        accepted = outcome["accepted"]

        if accepted is None:
            summary["no_safe_graph_connection"] += 1
            proposals_out.append(
                {
                    **base,
                    "status": "no_safe_graph_connection",
                    "semantic_match_confidence": match.confidence,
                    "diagnostics": diagnostics,
                    "message": (
                        "The label for this room was found, but no position "
                        "near it has a clear, wall-free line to a corridor "
                        "point. Place this one on the map."
                        if ranked
                        else "The label for this room was found, but there is "
                        "no corridor point within reach to connect it to. "
                        "Place this one on the map."
                    ),
                }
            )
            continue

        candidate: RoutePoint = accepted["candidate"]

        diagnostics.update(
            {
                "nudge_distance_px": accepted["nudge_px"],
                "nudge_direction_deg": accepted["nudge_deg"],
                "nudge_rule": accepted["rule"],
            }
        )

        geometry_confidence = _geometry_confidence(
            accepted["nudge_px"],
            outcome["budget"],
            accepted["tier"],
            label.source,
            label.confidence,
        )

        summary["auto_connectable"] += 1
        proposals_out.append(
            {
                **base,
                "status": "auto_connectable",
                "placement_source": "map_label",
                "suggested_room_point": [accepted["x"], accepted["y"]],
                "suggested_arrival_point": [accepted["x"], accepted["y"]],
                "semantic_match_confidence": match.confidence,
                "geometry_confidence": geometry_confidence,
                "matched_graph_element": {
                    "route_point_id": str(candidate.id),
                    "point_type": candidate.point_type,
                    "name": _candidate_name(candidate, lang),
                    "x": float(candidate.x),
                    "y": float(candidate.y),
                    "distance_px": accepted["distance_px"],
                    "confidence_tier": accepted["tier"],
                },
                "diagnostics": diagnostics,
                "message": None,
            }
        )

    return {
        "publication_id": destination_preview.get("publication_id"),
        "label_source": labels.source,
        "label_source_reason": labels.reason,
        "label_count": len(labels.labels),
        "wall_mask_available": mask_ok,
        "summary": summary,
        "proposals": proposals_out,
        "warnings": warnings,
    }
