"""
Separating shared circulation from room interiors, so the transit graph
follows corridors instead of wandering through the middle of a storage
room.

THE BUG THIS FIXES
------------------
Phase A originally skeletonised `walkable AND interior_region`. Room
interiors ARE interior, so the skeleton ran straight through offices,
meeting rooms and storage. The geometry was treating

    all interior free space == candidate corridor space

which is exactly wrong: a room is a destination, not a passage.

THE MECHANISM — CONSTRICTION SPLITTING, NOT RECTANGLES
-------------------------------------------------------
The separation is derived from real wall geometry, never from a box drawn
around a label.

A doorway is the narrowest thing in the free space: narrower than the room
it serves and narrower than the corridor it opens onto. So eroding the
free space by a radius slightly over half a door width pinches every
doorway shut while leaving rooms and corridors intact as separate cores.

The radius is not guessed. It is SWEPT upward from the wall stroke
thickness and the FIRST radius that actually decomposes the interior is
taken. Sweeping upward matters: an over-large radius erodes the corridor
away too, and then every room appears to touch everything through the
hole where the corridor used to be. Taking the first radius that works
makes that impossible by construction.

The eroded cores are then expanded back over the full free space by a
nearest-core (Voronoi) assignment, so every free pixel belongs to exactly
one cell and the boundary between two cells falls exactly at the doorway
that joins them. Cells that share a boundary are adjacent, which gives a
door-adjacency graph, and then:

    the circulation cell is the one that collects the doors of many cells

That is the functional definition of a corridor, computed rather than
guessed, and it needs no coordinates from the AI.

SEMANTICS ARE A PRIOR, NEVER AN OVERRIDE
-----------------------------------------
Semantic evidence refines the decomposition; it cannot create geometry:

  * a cell containing an accepted ROOM or FACILITY anchor is forced to
    room, whatever its degree — negative evidence,
  * a cell containing a matched CIRCULATION anchor (a public_area whose
    area_type is corridor-like) is preferred as the seed — positive
    evidence.

Both are optional. With no semantic evidence at all the door-adjacency
rule still works, which matters because on a raster map with no readable
labels there is no semantic evidence to be had.

Nothing here validates an edge. Every edge is still proven afterwards by
strict_geometry_service against the UNMODIFIED wall mask, so a semantic
prior can never talk the pipeline through a wall.

FAILING CONSERVATIVELY
----------------------
If the cells cannot be separated — no radius in the sweep decomposes the
interior, or nothing opens onto two or more other cells — this refuses
with a named reason rather than falling back to "the whole interior is
corridor", because that fallback IS the bug.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

import cv2
import numpy as np


# A cell must connect to at least this many other cells to be considered
# circulation at all. Two is the minimum that means "passage between"
# rather than "room with a door".
MIN_CIRCULATION_DEGREE = 2

# A cell joined to the primary circulation cell is absorbed into the
# circulation network when it reaches this degree — a side hallway that
# serves two or more rooms. Lower than the primary bar on purpose: a short
# branch corridor is still circulation.
MIN_BRANCH_DEGREE = 2

# Ignore specks. Fraction of the interior area.
MIN_CELL_AREA_FRACTION = 0.002

# A decomposition is only meaningful when it produces at least this many
# cells and no single cell still dominates the interior.
MIN_CELLS_FOR_DECOMPOSITION = 3
MAX_DOMINANT_CELL_FRACTION = 0.80

# The erosion sweep starts at the measured wall stroke thickness and
# climbs geometrically. The CEILING is derived from the drawing itself —
# the widest open space it contains, via the distance transform — because
# an image-relative cap is meaningless: what matters is how wide the
# rooms and corridors actually are, not how big the sheet is. Eroding
# past the widest half-width erases every space, so there is nothing to
# learn beyond it.
SWEEP_STEPS = 14
SWEEP_CEILING_OF_WIDEST = 0.9
MIN_SWEEP_RADIUS_PX = 2

# Two cells count as adjacent when their Voronoi regions share at least
# this many boundary pixels — one stray pixel of contact is not a door.
MIN_SHARED_BOUNDARY_PX = 3


@dataclass
class CirculationCell:
    index: int
    area: int
    degree: int
    bbox: Tuple[int, int, int, int]
    room_anchor_count: int = 0
    circulation_anchor_count: int = 0
    decision: str = "room"          # circulation | room
    reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "index": self.index,
            "area": self.area,
            "door_degree": self.degree,
            "bbox": list(self.bbox),
            "room_anchors": self.room_anchor_count,
            "circulation_anchors": self.circulation_anchor_count,
            "decision": self.decision,
            "reason": self.reason,
        }


@dataclass
class CirculationResult:
    available: bool = False
    reason: Optional[str] = None
    circulation_mask: Optional[np.ndarray] = None
    cells: List[CirculationCell] = field(default_factory=list)
    door_count: int = 0
    split_radius_px: int = 0
    radii_tried: int = 0
    excluded_room_cell_count: int = 0
    circulation_cell_count: int = 0

    def diagnostics(self) -> Dict[str, Any]:
        return {
            "available": self.available,
            "reason": self.reason,
            "cell_count": len(self.cells),
            "circulation_cell_count": self.circulation_cell_count,
            "excluded_room_cell_count": self.excluded_room_cell_count,
            "doorways_detected": self.door_count,
            "split_radius_px": self.split_radius_px,
            "radii_tried": self.radii_tried,
            "cells": [cell.to_dict() for cell in self.cells],
        }


def _sweep_radii(free: np.ndarray, stroke_thickness_px: float) -> List[int]:
    """
    Increasing erosion radii, from the wall stroke thickness up to a
    ceiling set by the widest open space in this drawing.

    The ceiling has to come from the drawing. A door in a hospital
    corridor and a door in a small clinic occupy wildly different pixel
    counts at the same DPI, and a cap expressed as a fraction of the sheet
    would refuse the first and over-erode the second. The distance
    transform's maximum is half the width of the widest open space, so
    nothing above it can separate anything — it only erases.
    """

    distance = cv2.distanceTransform((free > 0).astype(np.uint8), cv2.DIST_L2, 3)
    widest_half_width = float(distance.max()) if distance.size else 0.0

    ceiling = int(widest_half_width * SWEEP_CEILING_OF_WIDEST)
    start = max(MIN_SWEEP_RADIUS_PX, int(round(max(1.0, stroke_thickness_px))))

    if ceiling <= start:
        return [start]

    radii: List[int] = []
    for step in range(SWEEP_STEPS):
        ratio = step / max(1, SWEEP_STEPS - 1)
        radius = int(round(start + (ceiling - start) * (ratio ** 1.4)))
        if radius not in radii:
            radii.append(radius)

    return radii


def _cores_at(free: np.ndarray, radius: int) -> Tuple[int, np.ndarray, np.ndarray]:
    element = cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE, (2 * radius + 1, 2 * radius + 1)
    )
    eroded = cv2.erode(free, element, iterations=1)
    return cv2.connectedComponentsWithStats(eroded, connectivity=8)[:3]


def _expand_cores(cores: np.ndarray, free: np.ndarray) -> np.ndarray:
    """
    Assign every free pixel to its nearest core — a Voronoi partition of
    the free space seeded by the eroded cores.

    cv2.distanceTransform with DIST_LABEL_CCOMP gives, for each pixel, the
    label of the nearest ZERO-valued connected component. Feeding it the
    inverse of the cores therefore labels each pixel with its nearest
    core. The boundary between two labels lands exactly at the
    constriction between them, which is the doorway.
    """

    seed = (cores == 0).astype(np.uint8)
    _distance, nearest = cv2.distanceTransformWithLabels(
        seed, cv2.DIST_L2, 3, labelType=cv2.DIST_LABEL_CCOMP
    )

    # cv2's own component numbering differs from ours, so translate via a
    # representative pixel of each core.
    translation: Dict[int, int] = {}
    for core_id in range(1, int(cores.max()) + 1):
        ys, xs = np.nonzero(cores == core_id)
        if ys.size == 0:
            continue
        translation[int(nearest[ys[0], xs[0]])] = core_id

    assigned = np.zeros_like(cores, dtype=np.int32)
    for cv_label, core_id in translation.items():
        assigned[nearest == cv_label] = core_id

    assigned[free == 0] = 0
    return assigned


def identify_circulation(
    wall_mask: np.ndarray,
    interior_mask: np.ndarray,
    *,
    stroke_thickness_px: float,
    room_anchors: Sequence[Tuple[float, float]] = (),
    circulation_anchors: Sequence[Tuple[float, float]] = (),
    mask_scale: float = 1.0,
) -> CirculationResult:
    """
    `wall_mask` is the UNMODIFIED strict mask and `interior_mask` is the
    building region from building_region_service.

    Anchors are in FULL-RESOLUTION source pixels; `mask_scale` converts
    them to mask pixels. Both anchor lists are optional — the geometry
    works without either, which matters because a raster map with no
    readable labels supplies neither.
    """

    result = CirculationResult()

    if wall_mask is None or interior_mask is None or not np.any(interior_mask):
        result.reason = "No building interior was available to separate."
        return result

    height, width = wall_mask.shape[:2]
    interior_area = float(np.count_nonzero(interior_mask))
    free = ((wall_mask == 0) & (interior_mask > 0)).astype(np.uint8)

    min_cell_area = max(20, int(interior_area * MIN_CELL_AREA_FRACTION))

    # ---- sweep upward for the first radius that separates -----------
    chosen: Optional[Tuple[int, np.ndarray, List[int]]] = None

    for radius in _sweep_radii(free, stroke_thickness_px):
        result.radii_tried += 1
        count, cores, stats = _cores_at(free, radius)

        if count <= 1:
            continue

        keep = [
            core_id
            for core_id in range(1, count)
            if int(stats[core_id, cv2.CC_STAT_AREA]) >= min_cell_area
        ]

        if len(keep) < MIN_CELLS_FOR_DECOMPOSITION:
            continue

        largest = max(int(stats[core_id, cv2.CC_STAT_AREA]) for core_id in keep)
        if largest / max(1.0, interior_area) > MAX_DOMINANT_CELL_FRACTION:
            continue

        filtered = np.zeros_like(cores)
        for new_id, core_id in enumerate(keep, start=1):
            filtered[cores == core_id] = new_id

        chosen = (radius, filtered, list(range(1, len(keep) + 1)))
        break

    if chosen is None:
        result.reason = (
            "The building interior could not be separated into rooms and "
            "circulation. No erosion radius pinched the doorways shut "
            "without also erasing the corridors, which usually means the "
            "drawing is too low-resolution or its walls are too faint."
        )
        return result

    radius, cores, cell_ids = chosen
    result.split_radius_px = radius

    cell_labels = _expand_cores(cores, free)

    # ---- adjacency: cells whose Voronoi regions touch ---------------
    adjacency: Dict[int, Set[int]] = {cell_id: set() for cell_id in cell_ids}
    contact: Dict[Tuple[int, int], int] = {}

    right = cell_labels[:, :-1], cell_labels[:, 1:]
    down = cell_labels[:-1, :], cell_labels[1:, :]

    for a_side, b_side in (right, down):
        differing = (a_side != b_side) & (a_side > 0) & (b_side > 0)
        if not np.any(differing):
            continue
        pairs = np.stack([a_side[differing], b_side[differing]], axis=1)
        pairs.sort(axis=1)
        unique, counts = np.unique(pairs, axis=0, return_counts=True)
        for (low, high), shared in zip(unique, counts):
            key = (int(low), int(high))
            contact[key] = contact.get(key, 0) + int(shared)

    for (low, high), shared in contact.items():
        if shared < MIN_SHARED_BOUNDARY_PX:
            continue
        adjacency[low].add(high)
        adjacency[high].add(low)

    result.door_count = sum(
        1 for shared in contact.values() if shared >= MIN_SHARED_BOUNDARY_PX
    )

    if result.door_count == 0:
        result.reason = (
            "No doorway openings were found between the enclosed areas on "
            "this map, so which area is the shared corridor cannot be "
            "determined."
        )
        return result

    # ---- semantic anchors -------------------------------------------
    def cell_at(point: Tuple[float, float]) -> Optional[int]:
        mx = int(round(point[0] * mask_scale))
        my = int(round(point[1] * mask_scale))
        if not (0 <= mx < width and 0 <= my < height):
            return None
        cell_id = int(cell_labels[my, mx])
        return cell_id if cell_id > 0 else None

    room_hits: Dict[int, int] = {}
    for point in room_anchors:
        cell_id = cell_at(point)
        if cell_id is not None:
            room_hits[cell_id] = room_hits.get(cell_id, 0) + 1

    circulation_hits: Dict[int, int] = {}
    for point in circulation_anchors:
        cell_id = cell_at(point)
        if cell_id is not None:
            circulation_hits[cell_id] = circulation_hits.get(cell_id, 0) + 1

    cells: Dict[int, CirculationCell] = {}
    for cell_id in cell_ids:
        ys, xs = np.nonzero(cell_labels == cell_id)
        if ys.size == 0:
            continue
        cells[cell_id] = CirculationCell(
            index=cell_id,
            area=int(ys.size),
            degree=len(adjacency[cell_id]),
            bbox=(int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())),
            room_anchor_count=room_hits.get(cell_id, 0),
            circulation_anchor_count=circulation_hits.get(cell_id, 0),
        )

    # A cell holding an accepted room or facility is a ROOM, whatever its
    # door degree. This is the negative evidence, and it wins.
    forced_rooms = {
        cell_id for cell_id, cell in cells.items() if cell.room_anchor_count > 0
    }
    for cell_id in forced_rooms:
        cells[cell_id].reason = "semantic_room_anchor"

    eligible = [
        cell_id
        for cell_id in cells
        if cell_id not in forced_rooms
        and cells[cell_id].degree >= MIN_CIRCULATION_DEGREE
    ]

    if not eligible:
        result.cells = sorted(cells.values(), key=lambda c: -c.area)
        result.reason = (
            "No enclosed area on this map opens onto two or more others, so "
            "none of them behaves like a shared corridor."
        )
        return result

    semantic_seeds = [
        cell_id for cell_id in eligible if cells[cell_id].circulation_anchor_count > 0
    ]
    pool = semantic_seeds or eligible

    primary = max(pool, key=lambda cid: (cells[cid].degree, cells[cid].area))

    selected: Set[int] = {primary}
    frontier = [primary]

    while frontier:
        current = frontier.pop()
        for neighbour in adjacency[current]:
            if neighbour in selected or neighbour in forced_rooms:
                continue
            neighbour_cell = cells.get(neighbour)
            if neighbour_cell is None:
                continue
            if (
                neighbour_cell.degree >= MIN_BRANCH_DEGREE
                or neighbour_cell.circulation_anchor_count > 0
            ):
                selected.add(neighbour)
                frontier.append(neighbour)

    circulation_mask = np.zeros((height, width), dtype=np.uint8)
    for cell_id in selected:
        circulation_mask[cell_labels == cell_id] = 1
        cells[cell_id].decision = "circulation"
        cells[cell_id].reason = (
            "semantic_circulation_anchor"
            if cells[cell_id].circulation_anchor_count > 0
            else "door_degree"
        )

    for cell_id, cell in cells.items():
        if cell.decision != "circulation" and not cell.reason:
            cell.reason = "not_circulation_by_door_degree"

    result.cells = sorted(cells.values(), key=lambda c: -c.area)
    result.circulation_mask = circulation_mask
    result.circulation_cell_count = len(selected)
    result.excluded_room_cell_count = len(cells) - len(selected)
    result.available = bool(np.any(circulation_mask))

    if not result.available:
        result.reason = "The identified circulation area was empty."

    return result
