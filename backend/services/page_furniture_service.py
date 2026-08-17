"""
Positive detection of the things on a drawing sheet that are NOT the
building: title blocks, legends, drawing frames, revision tables.

WHY DETECT THEM RATHER THAN HOPE THE REGION LOGIC EXCLUDES THEM
---------------------------------------------------------------
The automatic graph generator in this repository was disabled for exactly
one reason, recorded at routes/map_routes.py:585 — it produced "points
outside the building, in title-block/metadata regions". Relying on a
generic region heuristic to happen to exclude a title block is passive:
the interior of a title block is enclosed white space bounded by drawn
lines, which is structurally very similar to a room. So it is detected
here explicitly and subtracted, rather than left for something else to
maybe reject.

THE TWO-EVIDENCE RULE
---------------------
A rectangle is only furniture when BOTH hold:

  1. GEOMETRY — an axis-aligned rectangle formed by long straight ink,
     positioned against a page edge or corner (title blocks and legends
     are, essentially by drafting convention, never floating in the
     middle of the plan).

  2. TEXT DENSITY — many small printed labels per unit area, and no large
     open interior. A title block is mostly writing; a room is mostly
     empty floor with one or two labels in it.

Requiring both is the whole point. Geometry alone would flag a large plain
rectangular room that happens to sit against the sheet edge. Text density
alone would flag a dense cluster of room numbers. Neither mistake is
acceptable, because a false positive here silently deletes part of a real
floor from the navigable region.

Label boxes come from services/map_label_extraction_service, which is
already built and already reports its own source and failures.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np


# A candidate rectangle must be at least this fraction of the page on its
# long side to be a title block or legend. Smaller boxes are dimension
# call-outs, door tags, or a north arrow — none of which enclose enough
# free space to matter to the region decision.
MIN_RECT_LONG_SIDE_FRACTION = 0.08

# ...and no more than this, or we are looking at the drawing frame around
# the whole sheet rather than a block within it. The frame is handled
# separately: it is reported, but its interior is NOT excluded, because
# the building lives inside it.
MAX_BLOCK_AREA_FRACTION = 0.35

# How close to a page edge a rectangle must sit, as a fraction of the page
# dimension, to count as "against the edge".
EDGE_PROXIMITY_FRACTION = 0.04

# Text density, in labels per million mask pixels, above which a region
# reads as written-on rather than drawn-on.
MIN_FURNITURE_LABEL_DENSITY = 12.0

# A furniture rectangle must contain at least this many labels outright —
# density alone is unstable for very small rectangles.
MIN_FURNITURE_LABEL_COUNT = 4

# If the largest open (ink-free) blob inside a rectangle covers more than
# this fraction of it, the rectangle has a big empty middle and is a room
# or a courtyard, not a title block.
MAX_FURNITURE_OPEN_FRACTION = 0.55


@dataclass
class FurnitureRegion:
    """One detected non-building rectangle, in MASK pixel coordinates."""

    kind: str                    # title_block | legend | table | frame
    x0: int
    y0: int
    x1: int
    y1: int
    label_count: int = 0
    label_density: float = 0.0
    open_fraction: float = 0.0
    touches_edges: Tuple[str, ...] = field(default_factory=tuple)
    # True only for kinds whose INTERIOR should be removed from the
    # candidate building region. A sheet frame is reported but never
    # excluded — the building is inside it.
    excludes_interior: bool = True

    @property
    def width(self) -> int:
        return self.x1 - self.x0

    @property
    def height(self) -> int:
        return self.y1 - self.y0

    @property
    def area(self) -> int:
        return max(0, self.width) * max(0, self.height)

    def contains(self, x: float, y: float) -> bool:
        return self.x0 <= x <= self.x1 and self.y0 <= y <= self.y1

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind,
            "bbox": [self.x0, self.y0, self.x1, self.y1],
            "label_count": self.label_count,
            "label_density": round(self.label_density, 2),
            "open_fraction": round(self.open_fraction, 3),
            "touches_edges": list(self.touches_edges),
            "excludes_interior": self.excludes_interior,
        }


def _touching_edges(
    x0: int, y0: int, x1: int, y1: int, width: int, height: int
) -> Tuple[str, ...]:
    margin_x = width * EDGE_PROXIMITY_FRACTION
    margin_y = height * EDGE_PROXIMITY_FRACTION

    edges = []
    if x0 <= margin_x:
        edges.append("left")
    if y0 <= margin_y:
        edges.append("top")
    if x1 >= width - margin_x:
        edges.append("right")
    if y1 >= height - margin_y:
        edges.append("bottom")

    return tuple(edges)


def _rectangle_candidates(
    wall_mask: np.ndarray,
) -> List[Tuple[int, int, int, int]]:
    """
    Axis-aligned rectangles enclosed by drawn ink.

    Found by closing the ink slightly (so a rectangle whose border is
    broken by a leader line still reads as closed), then taking the
    external contours of the ink and keeping those whose contour area
    nearly fills their own bounding box — which is what a drawn box does
    and what a wall run does not.
    """

    height, width = wall_mask.shape[:2]
    binary = (wall_mask > 0).astype(np.uint8)

    closed = cv2.morphologyEx(
        binary, cv2.MORPH_CLOSE, np.ones((5, 5), dtype=np.uint8), iterations=1
    )

    contours, _hierarchy = cv2.findContours(
        closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )

    min_long_side = min(width, height) * MIN_RECT_LONG_SIDE_FRACTION
    candidates: List[Tuple[int, int, int, int]] = []

    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)

        if max(w, h) < min_long_side:
            continue

        if w <= 0 or h <= 0:
            continue

        # A drawn rectangle's own outline traces its bounding box almost
        # exactly. A diagonal wall run, an L of corridor, or a scattered
        # blob does not.
        perimeter = cv2.arcLength(contour, True)
        box_perimeter = 2.0 * (w + h)

        if box_perimeter <= 0:
            continue

        if not (0.75 <= perimeter / box_perimeter <= 1.6):
            continue

        candidates.append((x, y, x + w, y + h))

    return candidates


def _open_fraction(
    wall_mask: np.ndarray,
    box: Tuple[int, int, int, int],
    contained_labels: Sequence[Tuple[float, float, float, float]],
) -> float:
    """
    Largest genuinely EMPTY blob inside the box, as a fraction of the box.

    Occupancy counts printed text as well as ink, because the wall mask
    deliberately discards small text (that is its whole job — see
    map_image_service._build_navigation_line_mask). Measuring emptiness
    against the wall mask alone makes a title block look like a big empty
    rectangle, which is exactly backwards: a title block is the most
    written-on part of the sheet.
    """

    x0, y0, x1, y1 = box
    window = wall_mask[y0:y1, x0:x1]

    if window.size == 0:
        return 0.0

    occupied = (window > 0).astype(np.uint8)

    for (lx0, ly0, lx1, ly1) in contained_labels:
        ax0 = max(0, int(round(lx0)) - x0)
        ay0 = max(0, int(round(ly0)) - y0)
        ax1 = min(occupied.shape[1], int(round(lx1)) - x0)
        ay1 = min(occupied.shape[0], int(round(ly1)) - y0)
        if ax1 > ax0 and ay1 > ay0:
            occupied[ay0:ay1, ax0:ax1] = 1

    free = (occupied == 0).astype(np.uint8)
    count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(
        free, connectivity=8
    )

    if count <= 1:
        return 0.0

    largest = int(np.max(stats[1:, cv2.CC_STAT_AREA]))
    return float(largest) / float(window.size)


def detect_page_furniture(
    wall_mask: np.ndarray,
    label_boxes: Sequence[Tuple[float, float, float, float]],
    *,
    mask_scale: float = 1.0,
) -> List[FurnitureRegion]:
    """
    `label_boxes` are (x0, y0, x1, y1) in FULL-RESOLUTION source pixels —
    the space MapLabel uses — and `mask_scale` converts them into mask
    pixels. Returns every detected furniture rectangle, sorted largest
    first.

    Never raises on a degenerate mask; an empty list means "found no
    furniture", which is a perfectly normal answer for a clean plan
    exported straight from CAD.
    """

    if wall_mask is None or wall_mask.size == 0:
        return []

    height, width = wall_mask.shape[:2]
    page_area = float(width * height)

    scaled_labels = [
        (x0 * mask_scale, y0 * mask_scale, x1 * mask_scale, y1 * mask_scale)
        for (x0, y0, x1, y1) in label_boxes
    ]

    regions: List[FurnitureRegion] = []

    for box in _rectangle_candidates(wall_mask):
        x0, y0, x1, y1 = box
        area = float((x1 - x0) * (y1 - y0))

        if area <= 0:
            continue

        touching = _touching_edges(x0, y0, x1, y1, width, height)

        # A rectangle covering most of the sheet is the drawing frame.
        # Report it (useful diagnostics) but never exclude its interior —
        # the building is in there.
        if area / page_area > MAX_BLOCK_AREA_FRACTION:
            regions.append(
                FurnitureRegion(
                    kind="frame",
                    x0=x0,
                    y0=y0,
                    x1=x1,
                    y1=y1,
                    touches_edges=touching,
                    excludes_interior=False,
                )
            )
            continue

        # EVIDENCE 1 — geometry: must sit against the sheet edge.
        if not touching:
            continue

        # EVIDENCE 2 — text density.
        contained = [
            label
            for label in scaled_labels
            if label[0] >= x0 and label[1] >= y0 and label[2] <= x1 and label[3] <= y1
        ]
        label_count = len(contained)
        density = (label_count / area) * 1_000_000.0

        if label_count < MIN_FURNITURE_LABEL_COUNT:
            continue

        if density < MIN_FURNITURE_LABEL_DENSITY:
            continue

        open_fraction = _open_fraction(wall_mask, box, contained)

        # A big empty middle means this is a room or courtyard.
        if open_fraction > MAX_FURNITURE_OPEN_FRACTION:
            continue

        kind = "title_block" if len(touching) >= 2 else "legend"

        regions.append(
            FurnitureRegion(
                kind=kind,
                x0=x0,
                y0=y0,
                x1=x1,
                y1=y1,
                label_count=label_count,
                label_density=density,
                open_fraction=open_fraction,
                touches_edges=touching,
                excludes_interior=True,
            )
        )

    regions.sort(key=lambda region: region.area, reverse=True)
    return regions


def build_exclusion_mask(
    shape: Tuple[int, int], regions: Sequence[FurnitureRegion]
) -> np.ndarray:
    """0/1 mask of everything a detected furniture rectangle covers."""

    exclusion = np.zeros(shape, dtype=np.uint8)

    for region in regions:
        if not region.excludes_interior:
            continue
        exclusion[region.y0 : region.y1, region.x0 : region.x1] = 1

    return exclusion


def furniture_overlap_fraction(
    component_mask: np.ndarray, exclusion_mask: Optional[np.ndarray]
) -> float:
    """How much of one free-space component sits inside page furniture."""

    if exclusion_mask is None:
        return 0.0

    total = int(np.count_nonzero(component_mask))

    if total == 0:
        return 0.0

    overlap = int(np.count_nonzero(component_mask & (exclusion_mask > 0)))
    return float(overlap) / float(total)
