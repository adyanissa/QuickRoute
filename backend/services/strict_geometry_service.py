"""
STRICT, high-resolution geometry validation — the safety proof for
automatically generated navigation geometry.

WHY THIS EXISTS SEPARATELY FROM graph_connection_service
--------------------------------------------------------
The existing wall mask (graph_connection_service._get_wall_mask) downscales
every map to at most 900 px on its longest side, and
map_image_service._build_navigation_line_mask computes its retention
thresholds from the dimensions of the array it is HANDED. So on a 900 px
working image `minimum_line_length` collapses to its floor of 28 px — a
wall must span roughly 3.1% of the image to be retained, against 0.9% at
3000 px. Thin interior walls are therefore invisible to the legacy
collision check.

That is acceptable for an admin placing points by hand who can see the
drawing. It is not acceptable as the final safety proof for geometry no
human reviewed. This module builds the same mask at full working
resolution and offers strict validators for the automatic pipeline.

TWO DELIBERATE DIFFERENCES FROM THE LEGACY VALIDATOR
----------------------------------------------------
1. **It fails CLOSED.** has_clear_line() returns True when there is no
   source image, because "nothing to reject the connection with" is the
   right answer for a human-in-the-loop action. Every function here
   returns None instead, and callers must treat None as a refusal.

2. **Short links are not rejected by a single pixel.** The legacy rule is
   `blocked / (samples + 1) <= 0.03`, so a segment needs about 34 samples
   before even one blocked sample is tolerated (1/33 = 0.0303 > 0.03).
   A corridor skeleton is mostly short edges, and one antialiased pixel
   on a doorway jamb would reject a perfectly good link. Below the sample
   floor this module allows a small ABSOLUTE number of blocked samples;
   above it, the fractional rule applies unchanged. A real wall crossing
   is many samples thick and is still rejected either way.

NOTHING HERE MUTATES THE LEGACY PATH
------------------------------------
graph_connection_service._get_wall_mask, has_clear_line, is_wall_pixel and
_WALL_MASK_CACHE are untouched and keep their exact current behavior, so
existing Auto Connect decisions do not change. This module keeps its own
separate, BOUNDED cache: a full-resolution mask is roughly 12 MB, and the
legacy cache is unbounded and never evicted — copying that here would leak
one mask per map previewed for the lifetime of the process.
"""

from __future__ import annotations

import math
from collections import OrderedDict
from typing import Dict, Optional, Tuple

import cv2
import numpy as np

from services.map_image_service import SOURCE_DIR, _build_navigation_line_mask


# Longest side of the image the strict mask is built from. Full resolution
# for almost every real floor plan; the cap only bites on very large
# scans, and even there it is 4.4x the legacy 900 px.
STRICT_MAX_EDGE_PX = 4000

# Bounded LRU. Three masks at ~12 MB each is a deliberate ceiling.
STRICT_CACHE_ENTRIES = 3

# Sampling along a candidate line, in mask pixels. Finer than the legacy
# 4.0 because the mask itself is finer.
STRICT_SAMPLE_STEP_PX = 2.0

# Above this many samples the fractional rule applies...
SHORT_LINK_SAMPLE_FLOOR = 34
# ...below it, at most this many blocked samples are tolerated.
SHORT_LINK_BLOCKED_ALLOWANCE = 1

STRICT_BLOCKED_SAMPLE_FRACTION = 0.03

# Wall stroke thickness is estimated from this percentile of the distance
# transform over wall pixels, doubled. The 80th percentile ignores the
# thin antialiased fringe without being dragged up by the thickest
# structural blocks.
STROKE_THICKNESS_PERCENTILE = 80.0
MIN_STROKE_THICKNESS_PX = 1.0
MAX_STROKE_THICKNESS_PX = 40.0


# map_id -> (source mtime, mask, downscale). OrderedDict as an LRU.
_STRICT_MASK_CACHE: "OrderedDict[str, Tuple[float, np.ndarray, float]]" = OrderedDict()

# map_id -> (source mtime, stroke_thickness_px, half_thickness_field).
#
# Separate from the mask cache and the same size, because both values are
# derived from one mask and both are expensive: each runs a full distance
# transform over an array that is ~16 megapixels on a large plan. Computing
# them per candidate would make a sixty-room bulk retry unusable; computing
# them once per map is free.
_STRICT_THICKNESS_CACHE: "OrderedDict[str, Tuple[float, float, np.ndarray]]" = (
    OrderedDict()
)


def clear_strict_mask_cache() -> None:
    """Test hook. Never called by request code."""

    _STRICT_MASK_CACHE.clear()
    _STRICT_THICKNESS_CACHE.clear()


def get_strict_wall_mask(map_id: str) -> Optional[Tuple[np.ndarray, float]]:
    """
    (wall_mask, downscale) built at up to STRICT_MAX_EDGE_PX, or None when
    this map has no readable source image.

    `downscale` converts full-resolution source pixels into mask pixels,
    exactly as the legacy helper does, so callers use the same arithmetic.
    It is 1.0 for any map under the cap — i.e. usually.
    """

    source_path = SOURCE_DIR / f"{map_id}.png"

    if not source_path.exists():
        return None

    try:
        mtime = source_path.stat().st_mtime
    except OSError:
        return None

    cached = _STRICT_MASK_CACHE.get(map_id)

    if cached and cached[0] == mtime:
        _STRICT_MASK_CACHE.move_to_end(map_id)
        return cached[1], cached[2]

    gray = cv2.imread(str(source_path), cv2.IMREAD_GRAYSCALE)

    if gray is None:
        return None

    height, width = gray.shape[:2]
    longest_side = max(height, width)
    downscale = min(1.0, float(STRICT_MAX_EDGE_PX) / float(longest_side))

    working = (
        cv2.resize(
            gray,
            (
                max(1, int(round(width * downscale))),
                max(1, int(round(height * downscale))),
            ),
            interpolation=cv2.INTER_AREA,
        )
        if downscale < 1.0
        else gray
    )

    wall_mask = _build_navigation_line_mask(working)

    _STRICT_MASK_CACHE[map_id] = (mtime, wall_mask, downscale)
    _STRICT_MASK_CACHE.move_to_end(map_id)

    while len(_STRICT_MASK_CACHE) > STRICT_CACHE_ENTRIES:
        _STRICT_MASK_CACHE.popitem(last=False)

    return wall_mask, downscale


def strict_mask_available(map_id: str) -> bool:
    return get_strict_wall_mask(map_id) is not None


def strict_has_clear_line(
    map_id: str,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
) -> Optional[bool]:
    """
    Tri-state. True = provably clear, False = provably blocked,
    **None = could not be determined** (no mask). None is not True:
    automatic callers must refuse.

    Coordinates are full-resolution source-image pixels, the same space
    RoutePoint.x/y uses.
    """

    cached = get_strict_wall_mask(map_id)

    if cached is None:
        return None

    wall_mask, downscale = cached
    return _clear_line_on_mask(wall_mask, downscale, x1, y1, x2, y2)


def _clear_line_on_mask(
    wall_mask: np.ndarray,
    downscale: float,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
) -> bool:
    """
    The sampling rule itself, separated so a caller that already holds a
    mask (the corridor generator validates hundreds of edges in a row) can
    avoid a cache lookup per call.
    """

    height, width = wall_mask.shape[:2]

    mx1, my1 = x1 * downscale, y1 * downscale
    mx2, my2 = x2 * downscale, y2 * downscale

    distance = math.hypot(mx2 - mx1, my2 - my1)

    if distance <= 0:
        # A zero-length segment proves nothing about a path, but it also
        # crosses nothing. Defer to the point test instead.
        return True

    sample_count = max(2, int(distance / STRICT_SAMPLE_STEP_PX))
    total_samples = sample_count + 1
    blocked = 0

    for i in range(total_samples):
        t = i / sample_count
        px = int(round(mx1 + (mx2 - mx1) * t))
        py = int(round(my1 + (my2 - my1) * t))

        if 0 <= py < height and 0 <= px < width:
            if wall_mask[py, px] > 0:
                blocked += 1
        else:
            # Leaving the image is treated as blocked, matching the legacy
            # validator — a path off the drawing is not a path.
            blocked += 1

    if total_samples < SHORT_LINK_SAMPLE_FLOOR:
        return blocked <= SHORT_LINK_BLOCKED_ALLOWANCE

    return (blocked / total_samples) <= STRICT_BLOCKED_SAMPLE_FRACTION


def strict_is_wall_pixel(
    map_id: str,
    x: float,
    y: float,
    radius_px: float = 0.0,
) -> Optional[bool]:
    """
    Tri-state, same contract as strict_has_clear_line. True when the point
    is on, within radius_px of, or outside the image.
    """

    cached = get_strict_wall_mask(map_id)

    if cached is None:
        return None

    wall_mask, downscale = cached
    return _is_wall_pixel_on_mask(wall_mask, downscale, x, y, radius_px)


def _is_wall_pixel_on_mask(
    wall_mask: np.ndarray,
    downscale: float,
    x: float,
    y: float,
    radius_px: float = 0.0,
) -> bool:
    height, width = wall_mask.shape[:2]

    mx = int(round(float(x) * downscale))
    my = int(round(float(y) * downscale))

    if not (0 <= mx < width and 0 <= my < height):
        return True

    mask_radius = int(math.floor(max(0.0, float(radius_px)) * downscale))

    if mask_radius <= 0:
        return bool(wall_mask[my, mx] > 0)

    x_start = max(0, mx - mask_radius)
    x_end = min(width, mx + mask_radius + 1)
    y_start = max(0, my - mask_radius)
    y_end = min(height, my + mask_radius + 1)

    return bool(np.any(wall_mask[y_start:y_end, x_start:x_end] > 0))


def measure_wall_stroke_thickness(wall_mask: np.ndarray) -> float:
    """
    Estimated typical wall stroke thickness, in MASK pixels.

    This is the one scale-free measurement available on an uncalibrated
    drawing, and the gap-sealing kernel in building_region_service is
    derived from it rather than from a guessed pixel constant. Almost
    every map in this system is uncalibrated (Map.scale defaults to 1.0),
    so a fixed constant would behave completely differently at 150 DPI and
    at 400 DPI. Stroke thickness scales with the render, so a multiple of
    it does not.

    Returns 0.0 when the mask has no wall pixels at all.
    """

    if wall_mask is None or not np.any(wall_mask):
        return 0.0

    binary = (wall_mask > 0).astype(np.uint8)
    distance = cv2.distanceTransform(binary, cv2.DIST_L2, 3)

    values = distance[binary > 0]

    if values.size == 0:
        return 0.0

    half_thickness = float(np.percentile(values, STROKE_THICKNESS_PERCENTILE))
    thickness = 2.0 * half_thickness

    return float(
        min(MAX_STROKE_THICKNESS_PX, max(MIN_STROKE_THICKNESS_PX, thickness))
    )


def strict_resolution_of(map_id: str) -> Optional[Dict[str, int]]:
    """Mask dimensions, for the preview's diagnostics block."""

    cached = get_strict_wall_mask(map_id)

    if cached is None:
        return None

    mask, _downscale = cached
    return {"width": int(mask.shape[1]), "height": int(mask.shape[0])}


# =====================================================================
# MEASUREMENT ONLY — nothing below changes a verdict
#
# Everything from here down is read-only measurement of the strict mask.
# No function here decides whether a link is allowed; strict_has_clear_line
# and its constants above are untouched, and the legacy validator in
# graph_connection_service is untouched. These helpers exist so a caller
# can ask "how thick is the thing this line crosses, and where along the
# line is it?" instead of only "is it blocked?".
#
# The one measurement that makes that question answerable is the distance
# transform: for a wall pixel, its distance to the nearest free pixel is
# exactly the local HALF thickness of the structure it belongs to, in every
# direction at once. measure_wall_stroke_thickness() already takes the 80th
# percentile of that same field to characterise the drawing's typical wall
# stroke, so a per-pixel reading and the map-wide reference are the same
# quantity in the same units and are directly comparable.
# =====================================================================


class StrictWallMetrics:
    """One map's strict mask plus the two derived measurements."""

    __slots__ = ("wall_mask", "downscale", "stroke_thickness_px", "half_thickness")

    def __init__(
        self,
        wall_mask: np.ndarray,
        downscale: float,
        stroke_thickness_px: float,
        half_thickness: np.ndarray,
    ) -> None:
        self.wall_mask = wall_mask
        # Multiply a full-resolution source coordinate by this to get mask
        # pixels; divide a mask-pixel length by it to get source pixels.
        self.downscale = downscale
        # Typical wall stroke thickness of THIS drawing, in mask pixels.
        self.stroke_thickness_px = stroke_thickness_px
        # Per-pixel half thickness, same shape as wall_mask. 0 off the wall.
        self.half_thickness = half_thickness

    def local_thickness_px(self, mask_x: int, mask_y: int) -> float:
        """Thickness of the structure covering one mask pixel, in mask
        pixels. 0.0 off the wall or outside the image."""

        height, width = self.wall_mask.shape[:2]
        if not (0 <= mask_y < height and 0 <= mask_x < width):
            return 0.0
        return 2.0 * float(self.half_thickness[mask_y, mask_x])


def get_strict_wall_metrics(map_id: str) -> Optional[StrictWallMetrics]:
    """
    The strict mask plus its measured stroke thickness and per-pixel
    half-thickness field, or None when this map has no readable source
    image. None is a refusal, exactly like the validators above.
    """

    cached = get_strict_wall_mask(map_id)

    if cached is None:
        return None

    wall_mask, downscale = cached

    source_path = SOURCE_DIR / f"{map_id}.png"
    try:
        mtime = source_path.stat().st_mtime
    except OSError:
        return None

    entry = _STRICT_THICKNESS_CACHE.get(map_id)

    if entry and entry[0] == mtime:
        _STRICT_THICKNESS_CACHE.move_to_end(map_id)
        _, stroke_thickness_px, half_thickness = entry
    else:
        binary = (wall_mask > 0).astype(np.uint8)
        half_thickness = cv2.distanceTransform(binary, cv2.DIST_L2, 3)
        stroke_thickness_px = measure_wall_stroke_thickness(wall_mask)

        _STRICT_THICKNESS_CACHE[map_id] = (
            mtime,
            stroke_thickness_px,
            half_thickness,
        )
        _STRICT_THICKNESS_CACHE.move_to_end(map_id)

        while len(_STRICT_THICKNESS_CACHE) > STRICT_CACHE_ENTRIES:
            _STRICT_THICKNESS_CACHE.popitem(last=False)

    if stroke_thickness_px <= 0.0:
        # A mask with no wall pixels at all. Nothing to measure against, so
        # no caller may reason about thickness on this map.
        return None

    return StrictWallMetrics(
        wall_mask, downscale, stroke_thickness_px, half_thickness
    )


class StrictBlockedRun:
    """One contiguous obstruction along a sampled segment.

    All lengths are in MASK pixels, measured along the segment from its
    start point, so they are directly comparable with
    StrictWallMetrics.stroke_thickness_px.
    """

    __slots__ = ("start_px", "length_px", "max_thickness_px", "out_of_bounds")

    def __init__(
        self,
        start_px: float,
        length_px: float,
        max_thickness_px: float,
        out_of_bounds: bool,
    ) -> None:
        self.start_px = start_px
        self.length_px = length_px
        # The thickest structure any sample in this run sits on, from the
        # distance-transform field. Direction-independent, so an obliquely
        # crossed wall is not mistaken for a thin one.
        self.max_thickness_px = max_thickness_px
        # True when any sample in this run left the image. Out-of-bounds is
        # blocked, but it has no measurable thickness, so a caller must
        # never treat such a run as a thin structure.
        self.out_of_bounds = out_of_bounds

    @property
    def end_px(self) -> float:
        return self.start_px + self.length_px


class StrictSegmentProfile:
    """Every obstruction along one segment, measured on the strict mask."""

    __slots__ = ("runs", "length_px", "stroke_thickness_px", "downscale")

    def __init__(
        self,
        runs: "list[StrictBlockedRun]",
        length_px: float,
        stroke_thickness_px: float,
        downscale: float,
    ) -> None:
        self.runs = runs
        self.length_px = length_px
        self.stroke_thickness_px = stroke_thickness_px
        self.downscale = downscale


def strict_segment_profile(
    metrics: StrictWallMetrics,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
) -> StrictSegmentProfile:
    """
    Measure every obstruction along the straight line between two
    full-resolution source coordinates.

    Sampled at STRICT_SAMPLE_STEP_PX on the strict mask — the same sampling
    _clear_line_on_mask uses — so a run length here and a strict verdict
    describe the same pixels.
    """

    wall_mask = metrics.wall_mask
    downscale = metrics.downscale
    height, width = wall_mask.shape[:2]

    mx1, my1 = x1 * downscale, y1 * downscale
    mx2, my2 = x2 * downscale, y2 * downscale

    distance = math.hypot(mx2 - mx1, my2 - my1)

    if distance <= 0:
        return StrictSegmentProfile(
            [], 0.0, metrics.stroke_thickness_px, downscale
        )

    sample_count = max(2, int(distance / STRICT_SAMPLE_STEP_PX))
    total_samples = sample_count + 1
    step_px = distance / sample_count

    runs: "list[StrictBlockedRun]" = []
    run_start: Optional[int] = None
    run_thickness = 0.0
    run_out_of_bounds = False

    def close_run(end_index: int) -> None:
        runs.append(
            StrictBlockedRun(
                start_px=run_start * step_px,
                length_px=(end_index - run_start) * step_px,
                max_thickness_px=run_thickness,
                out_of_bounds=run_out_of_bounds,
            )
        )

    for index in range(total_samples):
        t = index / sample_count
        px = int(round(mx1 + (mx2 - mx1) * t))
        py = int(round(my1 + (my2 - my1) * t))

        inside = 0 <= py < height and 0 <= px < width
        if inside:
            blocked = wall_mask[py, px] > 0
            thickness = (
                2.0 * float(metrics.half_thickness[py, px]) if blocked else 0.0
            )
        else:
            # Leaving the image is blocked, matching both validators.
            blocked = True
            thickness = 0.0

        if blocked:
            if run_start is None:
                run_start = index
                run_thickness = 0.0
                run_out_of_bounds = False
            run_thickness = max(run_thickness, thickness)
            run_out_of_bounds = run_out_of_bounds or not inside
        elif run_start is not None:
            close_run(index)
            run_start = None

    if run_start is not None:
        close_run(total_samples)

    return StrictSegmentProfile(
        runs, distance, metrics.stroke_thickness_px, downscale
    )
