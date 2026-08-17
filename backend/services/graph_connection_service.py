"""
Automatic connection of a new RoutePoint to the surrounding valid graph
(Priority 2, Part 6) and separate-path merge reporting (Part 7).

This deliberately does NOT connect points just because they are near each
other. A candidate must also pass a walkability check against the same
wall/architectural-line mask the automatic graph generator uses, whenever
a processed source image is available for the map — so a corridor point on
one side of a wall from a room point on the other side is never linked
just because they happen to be a few pixels apart in x/y. When no source
image exists yet (older maps, or maps created without an upload — e.g. via
the plain JSON create endpoint used by some tests/integrations), the wall
check is skipped rather than blocking every connection, and candidate
selection falls back to distance + exclusion rules alone.
"""

from __future__ import annotations

import asyncio
import math
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

from models.map_model import Map
from models.route_edge_model import RouteEdge
from models.route_point_model import RoutePoint
from services.map_image_service import SOURCE_DIR, _build_navigation_line_mask
from services.storage_backend import ensure_generated_file_local


DEFAULT_MAX_CANDIDATES = 3
DEFAULT_MAX_DISTANCE_PX = 600.0
LINE_SAMPLE_STEP_PX = 4.0
MAX_BLOCKED_SAMPLE_FRACTION = 0.03

# Per-process cache of (source mtime, wall_mask, downscale) keyed by
# map_id, so repeated connection checks against the same map don't
# re-run wall detection on the full-resolution source image every time.
_WALL_MASK_CACHE: Dict[str, Tuple[float, np.ndarray, float]] = {}


def _get_wall_mask(map_id: str) -> Optional[Tuple[np.ndarray, float]]:
    source_path = SOURCE_DIR / f"{map_id}.png"

    if not source_path.exists():
        return None

    try:
        mtime = source_path.stat().st_mtime
    except OSError:
        return None

    cached = _WALL_MASK_CACHE.get(map_id)

    if cached and cached[0] == mtime:
        return cached[1], cached[2]

    gray = cv2.imread(str(source_path), cv2.IMREAD_GRAYSCALE)

    if gray is None:
        return None

    height, width = gray.shape[:2]
    longest_side = max(height, width)
    downscale = min(1.0, 900.0 / float(longest_side))

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
    _WALL_MASK_CACHE[map_id] = (mtime, wall_mask, downscale)

    return wall_mask, downscale


async def _ensure_map_source_available(map_id: str) -> bool:
    """
    Ensures the normalized source PNG is present on this process's local
    disk before wall detection runs.

    ECS task storage is temporary. If the file disappeared after a restart,
    restore it from the map's durable S3 URL. Maps created without an upload
    keep the historical behavior: no source image means wall checking is
    unavailable rather than every connection being rejected.
    """

    source_path = SOURCE_DIR / f"{map_id}.png"

    if source_path.exists():
        return True

    try:
        map_item = await Map.get(map_id)
    except Exception:
        map_item = None

    if not map_item:
        return False

    stored_source_url = (
        map_item.source_image_url
        or map_item.image_url
    )

    if not stored_source_url:
        return False

    return await asyncio.to_thread(
        ensure_generated_file_local,
        stored_source_url,
        source_path,
    )


def has_clear_line(
    map_id: str,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
) -> bool:
    """
    True when there is no processed source image to check against (nothing
    to reject the connection with), or when the straight line between the
    two points crosses detected wall pixels for less than
    MAX_BLOCKED_SAMPLE_FRACTION of its sampled length.
    """

    cached = _get_wall_mask(map_id)

    if cached is None:
        return True

    wall_mask, downscale = cached
    height, width = wall_mask.shape[:2]

    wx1, wy1 = x1 * downscale, y1 * downscale
    wx2, wy2 = x2 * downscale, y2 * downscale

    distance = math.hypot(wx2 - wx1, wy2 - wy1)

    if distance <= 0:
        return True

    sample_count = max(2, int(distance / LINE_SAMPLE_STEP_PX))
    blocked = 0

    for i in range(sample_count + 1):
        t = i / sample_count
        px = int(round(wx1 + (wx2 - wx1) * t))
        py = int(round(wy1 + (wy2 - wy1) * t))

        if 0 <= py < height and 0 <= px < width:
            if wall_mask[py, px] > 0:
                blocked += 1
        else:
            blocked += 1

    blocked_fraction = blocked / (sample_count + 1)

    return blocked_fraction <= MAX_BLOCKED_SAMPLE_FRACTION


def wall_mask_available(map_id: str) -> bool:
    """
    Whether wall detection can actually run for this map right now.

    has_clear_line() deliberately FAILS OPEN — a missing source image
    means "nothing to reject this connection with", which is right for an
    admin who is placing points by hand and can see the map. It is exactly
    wrong for automatic placement, where nobody is looking. Callers that
    place points without a human in the loop must check this first and
    refuse when it is False, rather than reading has_clear_line()'s True
    as evidence of a clear path.
    """

    return _get_wall_mask(map_id) is not None


def is_wall_pixel(
    map_id: str,
    x: float,
    y: float,
    radius_px: float = 0.0,
) -> Optional[bool]:
    """
    Is the point (x, y) — in full-resolution source-image pixels — on or
    within radius_px of a detected wall?

    Returns None when it cannot be determined (no source image, so no wall
    mask). None is NOT False: automatic callers must treat it as a refusal.
    A point outside the image is True, matching how has_clear_line() counts
    out-of-bounds samples as blocked.

    Note the mask is built on a downscaled copy of the source image (see
    _get_wall_mask), so radius_px is converted into mask pixels and always
    covers at least the single pixel the point lands on.
    """

    cached = _get_wall_mask(map_id)

    if cached is None:
        return None

    wall_mask, downscale = cached
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

    window = wall_mask[y_start:y_end, x_start:x_end]

    return bool(np.any(window > 0))


async def _points_already_connected(
    map_id: str, point_a_id: str, point_b_id: str
) -> bool:
    existing = await RouteEdge.find_one(
        {
            "map_id": map_id,
            "$or": [
                {
                    "from_point_id": point_a_id,
                    "to_point_id": point_b_id,
                },
                {
                    "from_point_id": point_b_id,
                    "to_point_id": point_a_id,
                },
            ],
        }
    )

    return existing is not None


async def find_connection_candidates(
    point: RoutePoint,
    max_distance_px: float = DEFAULT_MAX_DISTANCE_PX,
) -> List[Tuple[RoutePoint, float]]:
    """
    Same-map, same-floor, active, non-self candidates within
    max_distance_px, sorted nearest-first. Cross-map and cross-floor
    points are never returned — this is the "normal walkway" candidate
    set only; stairs/elevator transitions are explicit admin actions, not
    something auto-connect ever infers.
    """

    query = {
        "map_id": point.map_id,
        "is_active": True,
    }

    if point.floor is not None:
        query["floor"] = point.floor

    all_points = await RoutePoint.find(query).to_list()
    point_id = str(point.id)

    candidates = []

    for other in all_points:
        if str(other.id) == point_id:
            continue

        distance = math.hypot(
            float(other.x) - float(point.x),
            float(other.y) - float(point.y),
        )

        if distance <= max_distance_px:
            candidates.append((other, distance))

    candidates.sort(key=lambda pair: pair[1])
    return candidates


async def auto_connect_point(
    point: RoutePoint,
    mode: str = "nearest",
    max_candidates: int = DEFAULT_MAX_CANDIDATES,
    max_distance_px: float = DEFAULT_MAX_DISTANCE_PX,
) -> dict:
    """
    mode: "off" | "nearest" | "all_valid"

    Returns a summary dict — never raises for an individual rejected
    candidate, so a partial connection attempt always reports full detail
    instead of failing the whole request:
      {
        "edges_created": [...RouteEdge...],
        "neighbors_considered": int,
        "rejected": [{"point_id": ..., "reason": ...}, ...],
      }
    """

    summary = {
        "edges_created": [],
        "neighbors_considered": 0,
        "rejected": [],
    }

    if mode == "off":
        return summary

    # Restore the source image once before evaluating candidates. This
    # prevents an ECS restart from silently disabling wall checks.
    await _ensure_map_source_available(point.map_id)

    candidates = await find_connection_candidates(point, max_distance_px)
    summary["neighbors_considered"] = len(candidates)

    connections_made = 0

    for other, distance in candidates:
        if mode == "nearest" and connections_made >= 1:
            break

        if mode == "all_valid" and connections_made >= max_candidates:
            break

        other_id = str(other.id)
        point_id = str(point.id)

        if await _points_already_connected(point.map_id, point_id, other_id):
            summary["rejected"].append(
                {"point_id": other_id, "reason": "already_connected"}
            )
            continue

        if not has_clear_line(
            point.map_id,
            float(point.x),
            float(point.y),
            float(other.x),
            float(other.y),
        ):
            summary["rejected"].append(
                {"point_id": other_id, "reason": "blocked_by_wall"}
            )
            continue

        new_edge = RouteEdge(
            map_id=point.map_id,
            from_point_id=point_id,
            to_point_id=other_id,
            edge_type="walkway",
            distance=round(distance, 2),
            is_bidirectional=True,
            is_accessible=True,
        )

        await new_edge.insert()
        summary["edges_created"].append(new_edge)
        connections_made += 1

    return summary