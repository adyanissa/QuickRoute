"""
Deciding which free space on a drawing sheet is actually inside the
building — the safety layer the old automatic graph generator never had.

WHY NOT JUST FLOOD-FILL FROM THE PAGE BORDER
--------------------------------------------
Because real buildings have entrances. Free space inside the building is
routinely connected to the page exterior through a door opening, so the
rule "border-connected free space is outside" can classify an entire real
corridor network as outside and discard the whole floor. That failure is
silent and total, so border connectivity is used here as ONE WEAK SIGNAL
and is never on its own sufficient to reject anything.

THE MASK ROLE SPLIT — this is what makes entrances safe
--------------------------------------------------------
Two masks are derived from the same strict wall mask and are never
confused:

  TOPOLOGY MASK  the wall mask CLOSED with a gap-sealing kernel sized from
                 the measured wall stroke thickness. Used only to decide
                 what is connected to what. Closing seals a doorway or
                 entrance gap, so the interior stops leaking to the page
                 exterior through it.

  GEOMETRY MASK  the strict wall mask, unmodified. Used for every skeleton
                 and every line-of-sight proof.

So classification sees a sealed building while the corridor skeleton is
still traced on the real, open geometry and threads through doorways
normally. Nothing is ever validated against the closed mask.

SIX INDEPENDENT SIGNALS
-----------------------
  S1  validated arrival points inside the component   STRONG POSITIVE
  S2  enclosure — 16-direction ray casting            STRONG
  S3  page-border exposure                            MODERATE NEGATIVE
  S4  size and shape (bbox fill ratio)                MODERATE
  S5  accepted-room label boxes                       WEAK SUPPORT ONLY
  S6  page-furniture overlap                          STRONG NEGATIVE

S2 is the signal that survives an entrance: losing one direction of
sixteen to a door opening barely moves the score, whereas a page margin is
open in most directions.

S5 CANNOT PROMOTE A COMPONENT ON ITS OWN. A room label's bounding box sits
inside the room it names, which says nothing about whether the free space
around it is the building's circulation network — and a dense cluster of
labels is at least as likely to be a legend. Label support may lower the
enclosure bar by a small amount and never below an absolute floor. The
only strong semantic evidence is a validated arrival point: a coordinate
that has already been proven off-wall and line-of-sight connected.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np

from services.page_furniture_service import (
    FurnitureRegion,
    build_exclusion_mask,
    furniture_overlap_fraction,
)


# --- Gap sealing -------------------------------------------------------

# The closing kernel is this multiple of the measured wall stroke
# thickness. Doors are about 4-6 stroke-thicknesses wide across ordinary
# drawing scales (a 200 mm wall and a 900 mm door keep their ratio at
# 1:50, 1:100 or 1:200), so this is scale-invariant in a way a fixed pixel
# constant could never be.
GAP_SEAL_THICKNESS_MULTIPLE = 6.0
MIN_GAP_SEAL_KERNEL_PX = 3
MAX_GAP_SEAL_KERNEL_PX = 81

# Closing must not swallow the corridors it is meant to preserve. If the
# kernel removes more than this fraction of the free space, it is halved
# and retried — a corridor narrower than the kernel would otherwise be
# bridged shut.
MAX_FREE_SPACE_LOSS_FRACTION = 0.35
GAP_SEAL_BACKOFF_ATTEMPTS = 3

# --- Component filtering ----------------------------------------------

MIN_COMPONENT_AREA_FRACTION = 0.0008
MIN_REGION_AREA_FRACTION = 0.02

# --- S2 enclosure ------------------------------------------------------

ENCLOSURE_RAY_COUNT = 16
ENCLOSURE_STEP_PX = 2.0
ENCLOSURE_MIN_SCORE = 0.80
# The field is computed on a downscaled copy; every point on it is
# sampled, so this bounds the cost rather than the accuracy of any one
# reading.
ENCLOSURE_FIELD_MAX_EDGE_PX = 400
# Thresholding the field nicks the interior open at each doorway; heal
# cuts up to this fraction of the shorter image side so one opening does
# not sever a corridor into two components.
INTERIORITY_HEAL_FRACTION = 0.02
# Labels may lower the bar by at most this much...
LABEL_SUPPORT_ENCLOSURE_BONUS = 0.05
# ...and never below this, no matter how many labels a component holds.
ENCLOSURE_ABSOLUTE_FLOOR = 0.70

# --- S3 border exposure ------------------------------------------------

BORDER_MARGIN_FRACTION = 0.03
MAX_BORDER_EXPOSURE = 0.35

# --- S4 shape ----------------------------------------------------------

# A page margin is a thin ring: it has a huge bounding box and fills
# almost none of it. Real floors fill a respectable share of their own box.
MIN_BBOX_FILL_RATIO = 0.12

# A secondary enclosed area smaller than this share of the main floor is
# not treated as part of it unless an arrival point vouches for it.
MIN_SECONDARY_AREA_RATIO = 0.15

# --- S6 furniture ------------------------------------------------------

MAX_FURNITURE_OVERLAP = 0.40


@dataclass
class RegionComponent:
    index: int
    area: int
    bbox: Tuple[int, int, int, int]
    area_fraction: float
    enclosure: float
    border_exposure: float
    bbox_fill_ratio: float
    arrival_point_count: int
    label_box_count: int
    furniture_overlap: float
    decision: str                 # "interior" | "rejected"
    reason: Optional[str] = None
    promoted_by: Optional[str] = None   # arrival_points | enclosure

    def to_dict(self) -> Dict[str, Any]:
        return {
            "index": self.index,
            "area": self.area,
            "bbox": list(self.bbox),
            "area_fraction": round(self.area_fraction, 5),
            "signals": {
                "arrival_points": self.arrival_point_count,
                "enclosure": round(self.enclosure, 3),
                "border_exposure": round(self.border_exposure, 3),
                "bbox_fill_ratio": round(self.bbox_fill_ratio, 3),
                "label_boxes": self.label_box_count,
                "furniture_overlap": round(self.furniture_overlap, 3),
            },
            "decision": self.decision,
            "reason": self.reason,
            "promoted_by": self.promoted_by,
        }


@dataclass
class RegionResult:
    available: bool = False
    reason: Optional[str] = None
    interior_mask: Optional[np.ndarray] = None    # 0/1, mask resolution
    # The gap-sealed mask used for classification, kept so a later stage
    # can reuse the SAME sealing decision instead of recomputing a
    # different one. Never used for a geometry proof.
    topology_mask: Optional[np.ndarray] = None
    components: List[RegionComponent] = field(default_factory=list)
    stroke_thickness_px: float = 0.0
    topology_kernel_px: int = 0
    gap_seal_backoffs: int = 0
    mask_width: int = 0
    mask_height: int = 0
    furniture: List[FurnitureRegion] = field(default_factory=list)

    @property
    def interior_components(self) -> List[RegionComponent]:
        return [c for c in self.components if c.decision == "interior"]

    @property
    def rejected_components(self) -> List[RegionComponent]:
        return [c for c in self.components if c.decision == "rejected"]

    def diagnostics(self) -> Dict[str, Any]:
        return {
            "available": self.available,
            "reason": self.reason,
            "stroke_thickness_px": round(self.stroke_thickness_px, 2),
            "topology_closing_kernel_px": self.topology_kernel_px,
            "gap_seal_backoffs": self.gap_seal_backoffs,
            "mask_width": self.mask_width,
            "mask_height": self.mask_height,
            "component_count": len(self.components),
            "interior_component_count": len(self.interior_components),
            "rejected_component_count": len(self.rejected_components),
            "components": [c.to_dict() for c in self.components],
            "furniture": [f.to_dict() for f in self.furniture],
        }


# =========================================================
# Topology mask
# =========================================================


def build_topology_mask(
    wall_mask: np.ndarray, stroke_thickness_px: float
) -> Tuple[np.ndarray, int, int]:
    """
    (topology_mask, kernel_px, backoff_count).

    Closes door and entrance gaps so connectivity reflects the building
    rather than the drawing's openings, backing the kernel off if it would
    destroy too much free space (which happens when a corridor is narrower
    than the kernel and gets bridged shut).
    """

    base_free = int(np.count_nonzero(wall_mask == 0))

    kernel_px = int(round(stroke_thickness_px * GAP_SEAL_THICKNESS_MULTIPLE))
    kernel_px = max(MIN_GAP_SEAL_KERNEL_PX, min(MAX_GAP_SEAL_KERNEL_PX, kernel_px))

    if kernel_px % 2 == 0:
        kernel_px += 1

    backoffs = 0

    for _attempt in range(GAP_SEAL_BACKOFF_ATTEMPTS):
        closed = cv2.morphologyEx(
            (wall_mask > 0).astype(np.uint8) * 255,
            cv2.MORPH_CLOSE,
            cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kernel_px, kernel_px)),
            iterations=1,
        )

        free_after = int(np.count_nonzero(closed == 0))

        if base_free == 0:
            return closed, kernel_px, backoffs

        loss = 1.0 - (free_after / base_free)

        if loss <= MAX_FREE_SPACE_LOSS_FRACTION or kernel_px <= MIN_GAP_SEAL_KERNEL_PX:
            return closed, kernel_px, backoffs

        kernel_px = max(MIN_GAP_SEAL_KERNEL_PX, kernel_px // 2)
        if kernel_px % 2 == 0:
            kernel_px += 1
        backoffs += 1

    closed = cv2.morphologyEx(
        (wall_mask > 0).astype(np.uint8) * 255,
        cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kernel_px, kernel_px)),
        iterations=1,
    )
    return closed, kernel_px, backoffs


# =========================================================
# S2 — enclosure, as a PER-PIXEL field
# =========================================================


def compute_enclosure_field(
    wall_mask: np.ndarray,
) -> Tuple[np.ndarray, float]:
    """
    (enclosure_field, field_scale) — for each sampled point, the fraction
    of ENCLOSURE_RAY_COUNT rays that strike ink before leaving the page.

    THIS IS COMPUTED PER PIXEL, NOT PER COMPONENT, AND THAT IS THE WHOLE
    POINT. A building with an entrance has its interior free space
    CONNECTED to the page exterior through the opening, so inside and
    outside are frequently one connected component. Scoring per component
    then averages the enclosed interior together with the wide-open margin
    and rejects the entire floor — the precise failure this module exists
    to avoid.

    A per-pixel field separates them regardless of connectivity: a pixel
    in a corridor is enclosed in nearly every direction even when it is
    three metres from an open door, while a pixel out on the sheet margin
    is open in most directions. Losing one ray of sixteen to a doorway
    barely moves an interior pixel's score.

    Computed on a downscaled copy for speed and returned at that
    resolution; `field_scale` converts mask pixels into field pixels.
    """

    height, width = wall_mask.shape[:2]
    longest = max(height, width)
    field_scale = min(1.0, float(ENCLOSURE_FIELD_MAX_EDGE_PX) / float(longest))

    if field_scale < 1.0:
        # INTER_AREA then threshold above zero, so a wall one pixel wide
        # survives downscaling instead of being sampled away. Rays must
        # never pass through a wall that only the full-resolution mask
        # knows about.
        reduced = cv2.resize(
            (wall_mask > 0).astype(np.float32),
            (
                max(1, int(round(width * field_scale))),
                max(1, int(round(height * field_scale))),
            ),
            interpolation=cv2.INTER_AREA,
        )
        small = (reduced > 0.0).astype(np.uint8)
    else:
        small = (wall_mask > 0).astype(np.uint8)

    fh, fw = small.shape[:2]
    walls = small > 0

    ys, xs = np.mgrid[0:fh, 0:fw]
    ys = ys.ravel().astype(np.float64)
    xs = xs.ravel().astype(np.float64)
    point_count = ys.size

    hits = np.zeros(point_count, dtype=np.int32)
    max_steps = int(math.hypot(fh, fw) / ENCLOSURE_STEP_PX) + 1

    for ray in range(ENCLOSURE_RAY_COUNT):
        angle = 2.0 * math.pi * ray / ENCLOSURE_RAY_COUNT
        dy = math.sin(angle) * ENCLOSURE_STEP_PX
        dx = math.cos(angle) * ENCLOSURE_STEP_PX

        # Compaction: carry only the points whose ray is still travelling.
        # Inside a building most rays strike a wall within a few steps, so
        # the working set collapses quickly and the cost becomes the sum of
        # live rays rather than steps x every point.
        live = np.arange(point_count)
        cy = ys.copy()
        cx = xs.copy()

        for _step in range(max_steps):
            if live.size == 0:
                break

            cy += dy
            cx += dx

            iy = np.round(cy).astype(np.int64)
            ix = np.round(cx).astype(np.int64)

            inside = (iy >= 0) & (iy < fh) & (ix >= 0) & (ix < fw)

            # Rays that left the page stop unhit: "open in this direction".
            if not inside.all():
                live = live[inside]
                cy = cy[inside]
                cx = cx[inside]
                iy = iy[inside]
                ix = ix[inside]

            if live.size == 0:
                break

            struck = walls[iy, ix]

            if struck.any():
                hits[live[struck]] += 1
                keep = ~struck
                live = live[keep]
                cy = cy[keep]
                cx = cx[keep]

    field = (hits.astype(np.float32) / float(ENCLOSURE_RAY_COUNT)).reshape(fh, fw)
    return field, field_scale


def _interiority_mask(
    wall_mask: np.ndarray, enclosure_field: np.ndarray, field_scale: float
) -> np.ndarray:
    """
    Threshold the enclosure field back up to mask resolution, then heal
    the small nicks thresholding leaves around doorways so a corridor is
    not cut in two at every opening.
    """

    height, width = wall_mask.shape[:2]

    interior = (enclosure_field >= ENCLOSURE_MIN_SCORE).astype(np.uint8)

    upsampled = cv2.resize(
        interior, (width, height), interpolation=cv2.INTER_NEAREST
    )

    heal_px = max(3, int(round(min(height, width) * INTERIORITY_HEAL_FRACTION)))
    if heal_px % 2 == 0:
        heal_px += 1

    return cv2.morphologyEx(
        upsampled,
        cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (heal_px, heal_px)),
        iterations=1,
    )


def _mean_enclosure(
    enclosure_field: np.ndarray, field_scale: float, component_mask: np.ndarray
) -> float:
    fh, fw = enclosure_field.shape[:2]
    small = cv2.resize(component_mask, (fw, fh), interpolation=cv2.INTER_NEAREST)
    values = enclosure_field[small > 0]

    if values.size == 0:
        return 0.0

    return float(np.mean(values))


# =========================================================
# S3 / S4
# =========================================================


def _border_exposure(component_mask: np.ndarray) -> float:
    height, width = component_mask.shape[:2]
    margin_y = max(1, int(height * BORDER_MARGIN_FRACTION))
    margin_x = max(1, int(width * BORDER_MARGIN_FRACTION))

    total = int(np.count_nonzero(component_mask))
    if total == 0:
        return 1.0

    band = np.zeros_like(component_mask)
    band[:margin_y, :] = 1
    band[-margin_y:, :] = 1
    band[:, :margin_x] = 1
    band[:, -margin_x:] = 1

    return float(np.count_nonzero(component_mask & band)) / float(total)


def _bbox_fill_ratio(area: int, bbox: Tuple[int, int, int, int]) -> float:
    x0, y0, x1, y1 = bbox
    box_area = max(1, (x1 - x0) * (y1 - y0))
    return float(area) / float(box_area)


# =========================================================
# Classification
# =========================================================


def classify_regions(
    wall_mask: np.ndarray,
    stroke_thickness_px: float,
    *,
    arrival_points: Sequence[Tuple[float, float]] = (),
    label_boxes: Sequence[Tuple[float, float, float, float]] = (),
    furniture: Sequence[FurnitureRegion] = (),
    mask_scale: float = 1.0,
) -> RegionResult:
    """
    `arrival_points` and `label_boxes` are in FULL-RESOLUTION source
    pixels; `mask_scale` converts them to mask pixels.

    Pass no arrival points for the provisional (weak-evidence) pass, and
    the validated ones for the refined pass.

    Order of operations matters. The per-pixel enclosure field is applied
    FIRST, so inside and outside are separated before components are
    formed. Component scoring then runs on candidates that are already
    interior-by-geometry, and its job is only to reject leftovers and to
    let a validated arrival point rescue something geometry missed.
    """

    if wall_mask is None or wall_mask.size == 0:
        return RegionResult(
            available=False, reason="No wall mask is available for this map."
        )

    height, width = wall_mask.shape[:2]
    total_pixels = float(height * width)

    topology_mask, kernel_px, backoffs = build_topology_mask(
        wall_mask, stroke_thickness_px
    )

    base = RegionResult(
        topology_mask=topology_mask,
        stroke_thickness_px=stroke_thickness_px,
        topology_kernel_px=kernel_px,
        gap_seal_backoffs=backoffs,
        mask_width=width,
        mask_height=height,
        furniture=list(furniture),
    )

    enclosure_field, field_scale = compute_enclosure_field(wall_mask)
    interiority = _interiority_mask(wall_mask, enclosure_field, field_scale)

    exclusion = build_exclusion_mask((height, width), furniture)

    # Free space that is also interior-by-enclosure and not page furniture.
    free = (topology_mask == 0).astype(np.uint8)
    candidate = (free & (interiority > 0) & (exclusion == 0)).astype(np.uint8)

    component_count, labels, stats, _centroids = cv2.connectedComponentsWithStats(
        candidate, connectivity=8
    )

    if component_count <= 1:
        base.available = False
        base.reason = (
            "No enclosed interior space was found on this drawing. Every open "
            "area was open to the page edge in most directions, which is what "
            "a margin or an outdoor area looks like rather than a floor."
        )
        return base

    scaled_arrivals = [(x * mask_scale, y * mask_scale) for (x, y) in arrival_points]
    scaled_labels = [
        (x0 * mask_scale, y0 * mask_scale, x1 * mask_scale, y1 * mask_scale)
        for (x0, y0, x1, y1) in label_boxes
    ]

    min_area = max(40, int(total_pixels * MIN_COMPONENT_AREA_FRACTION))

    measured: List[Tuple[RegionComponent, np.ndarray]] = []

    for component_id in range(1, component_count):
        area = int(stats[component_id, cv2.CC_STAT_AREA])

        if area < min_area:
            continue

        x0 = int(stats[component_id, cv2.CC_STAT_LEFT])
        y0 = int(stats[component_id, cv2.CC_STAT_TOP])
        w = int(stats[component_id, cv2.CC_STAT_WIDTH])
        h = int(stats[component_id, cv2.CC_STAT_HEIGHT])
        bbox = (x0, y0, x0 + w, y0 + h)

        component_mask = (labels == component_id).astype(np.uint8)

        arrivals_inside = sum(
            1
            for (ax, ay) in scaled_arrivals
            if 0 <= int(round(ay)) < height
            and 0 <= int(round(ax)) < width
            and component_mask[int(round(ay)), int(round(ax))]
        )

        labels_inside = 0
        for (lx0, ly0, lx1, ly1) in scaled_labels:
            cx = int(round((lx0 + lx1) / 2.0))
            cy = int(round((ly0 + ly1) / 2.0))
            if 0 <= cy < height and 0 <= cx < width and component_mask[cy, cx]:
                labels_inside += 1

        measured.append(
            (
                RegionComponent(
                    index=component_id,
                    area=area,
                    bbox=bbox,
                    area_fraction=area / total_pixels,
                    enclosure=_mean_enclosure(
                        enclosure_field, field_scale, component_mask
                    ),
                    border_exposure=_border_exposure(component_mask),
                    bbox_fill_ratio=_bbox_fill_ratio(area, bbox),
                    arrival_point_count=arrivals_inside,
                    label_box_count=labels_inside,
                    furniture_overlap=furniture_overlap_fraction(
                        component_mask, exclusion
                    ),
                    decision="rejected",
                ),
                component_mask,
            )
        )

    if not measured:
        base.available = False
        base.reason = (
            "Every enclosed area on this drawing was too small to be a floor."
        )
        return base

    largest_area = max(component.area for component, _mask in measured)

    interior = np.zeros((height, width), dtype=np.uint8)

    for component, component_mask in measured:
        # S5 may lower the enclosure bar, never below the absolute floor,
        # and never substitute for it.
        enclosure_bar = ENCLOSURE_MIN_SCORE
        if component.label_box_count > 0:
            enclosure_bar = max(
                ENCLOSURE_ABSOLUTE_FLOOR,
                ENCLOSURE_MIN_SCORE - LABEL_SUPPORT_ENCLOSURE_BONUS,
            )

        if component.furniture_overlap > MAX_FURNITURE_OVERLAP:
            component.reason = "page_furniture"
        elif component.arrival_point_count > 0:
            # S1, the strong semantic seed. A validated arrival point is a
            # coordinate already proven off-wall and line-of-sight
            # connected, so its presence settles that this free space is
            # inside the building whatever the geometry signals say.
            component.decision = "interior"
            component.promoted_by = "arrival_points"
        elif component.enclosure < enclosure_bar:
            component.reason = "not_enclosed"
        elif component.border_exposure > MAX_BORDER_EXPOSURE:
            component.reason = "page_margin"
        elif component.bbox_fill_ratio < MIN_BBOX_FILL_RATIO:
            component.reason = "ring_shaped"
        elif component.area < largest_area * MIN_SECONDARY_AREA_RATIO:
            # A small enclosed pocket with no semantic support: a stair
            # core, a duct riser, a courtyard. Real, but not somewhere to
            # route through on this evidence.
            component.reason = "too_small_relative_to_main_floor"
        else:
            component.decision = "interior"
            component.promoted_by = "enclosure"

        if component.decision == "interior":
            interior |= component_mask

    base.components = [component for component, _mask in measured]
    base.interior_mask = interior

    interior_area = int(np.count_nonzero(interior))

    if interior_area == 0:
        base.available = False
        base.reason = (
            "No part of this drawing could be identified as the inside of a "
            "building. Every enclosed area was page furniture, a margin, or "
            "too small to be a floor."
        )
        return base

    if interior_area / total_pixels < MIN_REGION_AREA_FRACTION:
        base.available = False
        base.reason = (
            "The area identified as building interior is too small to be a "
            "floor plan — this is usually a title block or a detail drawing "
            "rather than the building."
        )
        return base

    base.available = True
    return base


def region_contours(
    interior_mask: np.ndarray, mask_scale: float, *, simplify_px: float = 2.0
) -> List[List[List[float]]]:
    """
    Simplified outlines of the interior region, converted back to
    FULL-RESOLUTION source pixels so the admin map can draw them straight
    over the floor plan image.
    """

    if interior_mask is None or not np.any(interior_mask):
        return []

    contours, _hierarchy = cv2.findContours(
        (interior_mask > 0).astype(np.uint8),
        cv2.RETR_EXTERNAL,
        cv2.CHAIN_APPROX_SIMPLE,
    )

    inverse = 1.0 / mask_scale if mask_scale else 1.0
    polygons: List[List[List[float]]] = []

    for contour in contours:
        approximated = cv2.approxPolyDP(contour, simplify_px, True)

        if len(approximated) < 3:
            continue

        polygons.append(
            [
                [round(float(point[0][0]) * inverse, 1), round(float(point[0][1]) * inverse, 1)]
                for point in approximated
            ]
        )

    return polygons
