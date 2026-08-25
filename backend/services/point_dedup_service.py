"""
Server-side RoutePoint deduplication (Priority 2).

The frontend's marker-click selection (AdminMapScreen.jsx) is the primary
way an admin reuses an existing point, but the backend must not depend on
the frontend getting that right every time — a retried request, a stale
frontend build, or a future API client could all still send a "create"
call for a point that already exists at (or effectively at) the same
physical location. This is the backend's own, independent safety net.
"""

from __future__ import annotations

import math
from typing import Optional, Tuple

from models.route_point_model import RoutePoint


# Default matching tolerance, in the map's own original-image pixels. Not
# tied to real-world units because Map.scale is meters-per-pixel and is
# frequently left at a placeholder value (e.g. 1) before an admin
# calibrates it — a fixed, deliberately small pixel tolerance is safer
# than a real-world-distance tolerance that could silently balloon in
# native pixels on an uncalibrated map. Deliberately tight — this is a
# "essentially the same click" safety net, not a general nearest-neighbor
# snap (that's the frontend's separate, larger, screen-scaled snap
# threshold in geometry.js); two real junctions a few pixels apart on a
# high-resolution map must still be creatable as distinct points.
DEFAULT_COORDINATE_TOLERANCE_PX = 6.0


async def find_duplicate_route_point(
    map_id: str,
    floor: Optional[int],
    x: float,
    y: float,
    point_type: Optional[str] = None,
    tolerance_px: float = DEFAULT_COORDINATE_TOLERANCE_PX,
) -> Optional[RoutePoint]:
    """
    Returns the closest existing active RoutePoint on this map/floor within
    `tolerance_px` of (x, y), or None. Never considers inactive points or
    points on a different map/floor a match — this is deliberately a tight
    "same physical spot" check, not a general nearest-neighbor search, so
    it never accidentally merges two genuinely distinct nearby junctions.
    """

    query = {
        "map_id": map_id,
        "is_active": True,
    }

    if floor is not None:
        query["floor"] = floor

    candidates = await RoutePoint.find(query).to_list()

    closest: Optional[RoutePoint] = None
    closest_distance = float("inf")

    for candidate in candidates:
        # Two explicitly different, non-null point types is a signal these
        # are different physical things that happen to be close together
        # (e.g. an elevator point placed right next to a hallway point at
        # a lobby) — never merge those even within tolerance.
        if (
            point_type
            and candidate.point_type
            and candidate.point_type != point_type
        ):
            continue

        distance = math.hypot(
            float(candidate.x) - x, float(candidate.y) - y
        )

        if distance <= tolerance_px and distance < closest_distance:
            closest = candidate
            closest_distance = distance

    return closest


async def find_or_create_route_point(
    *,
    map_id: str,
    name: str,
    point_type: Optional[str],
    x: float,
    y: float,
    floor: Optional[int],
    building_id: Optional[str],
    room_id: Optional[str],
    is_accessible: bool,
    tolerance_px: float = DEFAULT_COORDINATE_TOLERANCE_PX,
    # Optional semantic-name linkage (see models/route_point_model.py).
    # Kept as keyword-only, defaulted-None additions so every pre-existing
    # caller (e.g. room_routes.py's _place_room_on_map, which never had
    # these to give) keeps working byte-for-byte unchanged. Only ever
    # written onto a GENUINELY NEW point below — a reused point is still
    # never mutated here, exactly as before (reuse means "return the
    # existing document as-is").
    display_name: Optional[str] = None,
    display_name_en: Optional[str] = None,
    display_name_ar: Optional[str] = None,
    display_name_he: Optional[str] = None,
    semantic_publication_id: Optional[str] = None,
    semantic_entity_external_id: Optional[str] = None,
    semantic_entity_type: Optional[str] = None,
) -> Tuple[RoutePoint, bool]:
    """
    Returns (point, was_reused). Inserts a new RoutePoint only when no
    existing active point on this map/floor is within tolerance of
    (x, y) — otherwise returns the existing one untouched.
    """

    existing = await find_duplicate_route_point(
        map_id, floor, x, y, point_type, tolerance_px
    )

    if existing:
        return existing, True

    new_point = RoutePoint(
        map_id=map_id,
        name=name,
        point_type=point_type,
        x=x,
        y=y,
        floor=floor,
        building_id=building_id,
        room_id=room_id,
        is_accessible=is_accessible,
        display_name=display_name,
        display_name_en=display_name_en,
        display_name_ar=display_name_ar,
        display_name_he=display_name_he,
        semantic_publication_id=semantic_publication_id,
        semantic_entity_external_id=semantic_entity_external_id,
        semantic_entity_type=semantic_entity_type,
    )

    await new_point.insert()
    return new_point, False
