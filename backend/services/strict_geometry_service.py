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


def clear_strict_mask_cache() -> None:
    """Test hook. Never called by request code."""

    _STRICT_MASK_CACHE.clear()


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
