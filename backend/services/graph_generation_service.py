"""
Automatic walkable-graph generation from a processed map's source image.

Pipeline (Priority 3 of the automatic-setup feature):
  1. Load the source image (original image coordinate system).
  2. Reuse the existing wall/architectural-line mask already built for the
     display-map pipeline (map_image_service._build_navigation_line_mask)
     instead of inventing a second, inconsistent wall detector.
  3. Invert it into a walkable-space candidate mask; drop tiny noise
     regions.
  4. Skeletonize the walkable mask (vectorized Zhang-Suen thinning — no
     scipy/scikit-image dependency, just numpy + the project's existing
     opencv-python).
  5. Extract topological nodes (skeleton endpoints and junctions) and trace
     the skeleton between them to get edges with real pixel-length
     distances.
  6. Score a confidence value from the geometry actually found. Low
     confidence means "don't fabricate a graph" — the map is preserved
     untouched and manual Draw Walkable Path remains the only way to build
     its graph.

This is a heuristic, geometry-only pipeline. It has no semantic
understanding of "this is a shop" vs "this is a corridor" — it only knows
"this pixel region is not enclosed by a detected wall line". See the
module docstring warnings repeated in generate_walkable_graph_for_map's
return note for what this means in practice.
"""

from __future__ import annotations

import asyncio
import math
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

from beanie import PydanticObjectId

from models.map_model import Map
from models.route_edge_model import RouteEdge
from models.route_point_model import RoutePoint
from services.map_image_service import _build_navigation_line_mask


GRAPH_GENERATION_VERSION = 1
GENERATION_METHOD_LOCAL = "auto_local"

# Long-side target for the skeletonization stage. The real uploaded maps in
# this project are rendered at ~200 DPI and can be several thousand pixels
# wide; running Zhang-Suen thinning at full resolution is unnecessary for
# corridor-level topology and meaningfully slower. Extracted node/edge
# coordinates are always scaled back up to the original resolution before
# they are returned, per the "store original image coordinates" rule.
MAX_PROCESSING_DIMENSION = 900

# Confidence below this means "do not apply automatically" — the map and
# any existing manual graph are left completely untouched.
MIN_CONFIDENCE_TO_APPLY = 0.35

# Skeleton pixels within this many pixels of each other (in the downscaled
# working image) are treated as one junction/endpoint node instead of a
# cluster of near-duplicate nodes — Zhang-Suen commonly leaves a small
# blob of 2-4 branching pixels at a true junction rather than one pixel.
NODE_CLUSTER_RADIUS_PX = 4


@dataclass
class GeneratedNode:
    x: float
    y: float
    kind: str  # "endpoint" | "junction"


@dataclass
class GeneratedEdge:
    from_index: int
    to_index: int
    pixel_length: float


@dataclass
class GraphExtractionResult:
    nodes: List[GeneratedNode] = field(default_factory=list)
    edges: List[GeneratedEdge] = field(default_factory=list)
    confidence: float = 0.0
    walkable_fraction: float = 0.0
    component_count: int = 0
    note: str = ""


# =========================================================
# Vectorized Zhang-Suen skeletonization (no scipy/skimage)
# =========================================================

def _shifted_neighbors(
    img: np.ndarray,
) -> Tuple[np.ndarray, ...]:
    """
    Returns P2..P9 (clockwise from north) for every pixel via np.roll.
    Callers must zero the image border first so roll's wraparound never
    contaminates a real interior pixel with data from the opposite edge.
    """

    p2 = np.roll(img, -1, axis=0)          # N
    p6 = np.roll(img, 1, axis=0)           # S
    p4 = np.roll(img, -1, axis=1)          # E
    p8 = np.roll(img, 1, axis=1)           # W
    p3 = np.roll(p2, -1, axis=1)           # NE
    p9 = np.roll(p2, 1, axis=1)            # NW
    p5 = np.roll(p6, -1, axis=1)           # SE
    p7 = np.roll(p6, 1, axis=1)            # SW

    return p2, p3, p4, p5, p6, p7, p8, p9


def _zhang_suen_thin(
    binary: np.ndarray,
    max_iterations: int = 200,
) -> np.ndarray:
    """
    Standard Zhang-Suen thinning, vectorized with numpy instead of a
    per-pixel Python loop so it stays fast without scipy/scikit-image.
    `binary` is any array where >0 means foreground; returns a 0/1 uint8
    skeleton of the same shape.
    """

    img = (binary > 0).astype(np.uint8)
    img[0, :] = 0
    img[-1, :] = 0
    img[:, 0] = 0
    img[:, -1] = 0

    for _ in range(max_iterations):
        changed_this_pass = False

        for sub_iteration in (1, 2):
            p2, p3, p4, p5, p6, p7, p8, p9 = _shifted_neighbors(img)

            neighbor_sum = p2 + p3 + p4 + p5 + p6 + p7 + p8 + p9

            sequence = [p2, p3, p4, p5, p6, p7, p8, p9, p2]
            transitions = np.zeros_like(img, dtype=np.uint8)

            for i in range(8):
                transitions += (
                    (sequence[i] == 0) & (sequence[i + 1] == 1)
                ).astype(np.uint8)

            condition_b = (neighbor_sum >= 2) & (neighbor_sum <= 6)
            condition_a = transitions == 1

            if sub_iteration == 1:
                condition_c = (p2 * p4 * p6) == 0
                condition_d = (p4 * p6 * p8) == 0
            else:
                condition_c = (p2 * p4 * p8) == 0
                condition_d = (p2 * p6 * p8) == 0

            to_delete = (
                (img == 1)
                & condition_b
                & condition_a
                & condition_c
                & condition_d
            )

            if np.any(to_delete):
                img[to_delete] = 0
                changed_this_pass = True

        if not changed_this_pass:
            break

    return img


# =========================================================
# Walkable mask
# =========================================================

def _build_walkable_mask(
    gray_image: np.ndarray,
) -> Tuple[np.ndarray, float, int]:
    """
    Returns (walkable_mask, walkable_fraction, kept_component_count).

    walkable_mask is 0/1 uint8: 1 = candidate open floor space (not a
    detected wall/architectural line, and part of a large-enough
    connected region to not just be scanner/JPEG noise).
    """

    wall_mask = _build_navigation_line_mask(gray_image)
    walkable = cv2.bitwise_not(wall_mask)

    walkable = cv2.morphologyEx(
        walkable,
        cv2.MORPH_OPEN,
        np.ones((3, 3), dtype=np.uint8),
        iterations=1,
    )

    total_pixels = gray_image.shape[0] * gray_image.shape[1]
    minimum_component_area = max(40, int(total_pixels * 0.0008))

    component_count, labels, statistics, _ = cv2.connectedComponentsWithStats(
        walkable, connectivity=8
    )

    kept = np.zeros_like(walkable)
    kept_component_count = 0

    for component_id in range(1, component_count):
        area = int(statistics[component_id, cv2.CC_STAT_AREA])

        if area >= minimum_component_area:
            kept[labels == component_id] = 1
            kept_component_count += 1

    walkable_fraction = (
        float(np.count_nonzero(kept)) / float(total_pixels)
        if total_pixels
        else 0.0
    )

    return kept, walkable_fraction, kept_component_count


# =========================================================
# Skeleton -> graph extraction
# =========================================================

def _count_skeleton_neighbors(skeleton: np.ndarray) -> np.ndarray:
    p2, p3, p4, p5, p6, p7, p8, p9 = _shifted_neighbors(skeleton)
    return p2 + p3 + p4 + p5 + p6 + p7 + p8 + p9


def _get_skeleton_neighbors(
    skeleton_mask: np.ndarray,
    y: int,
    x: int,
) -> List[Tuple[int, int]]:
    height, width = skeleton_mask.shape
    result = []

    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dy == 0 and dx == 0:
                continue

            ny, nx = y + dy, x + dx

            if 0 <= ny < height and 0 <= nx < width and skeleton_mask[ny, nx]:
                result.append((ny, nx))

    return result


def _extract_graph_from_skeleton(
    skeleton: np.ndarray,
) -> Tuple[List[Tuple[float, float, str]], List[Tuple[int, int, float]]]:
    """
    Returns (nodes, edges):
      nodes  = [(row, col, "endpoint" | "junction"), ...]
      edges  = [(node_index_a, node_index_b, pixel_length), ...]

    Coordinates are (row, col) in the *downscaled working* image — the
    caller is responsible for scaling back to the original resolution and
    swapping to (x, y).
    """

    skeleton_mask = skeleton.astype(bool)
    neighbor_count = _count_skeleton_neighbors(skeleton)

    endpoint_mask = skeleton_mask & (neighbor_count == 1)
    junction_mask = skeleton_mask & (neighbor_count >= 3)
    node_candidate_mask = endpoint_mask | junction_mask

    if not np.any(node_candidate_mask):
        return [], []

    dilated = cv2.dilate(
        node_candidate_mask.astype(np.uint8),
        np.ones(
            (NODE_CLUSTER_RADIUS_PX, NODE_CLUSTER_RADIUS_PX),
            dtype=np.uint8,
        ),
    )

    num_labels, labels = cv2.connectedComponents(dilated, connectivity=8)

    nodes: List[Tuple[float, float, str]] = []
    pixel_to_node: Dict[Tuple[int, int], int] = {}

    for label_id in range(1, num_labels):
        cluster_mask = (labels == label_id) & node_candidate_mask
        ys, xs = np.where(cluster_mask)

        if len(ys) == 0:
            continue

        node_index = len(nodes)
        center_y = float(np.mean(ys))
        center_x = float(np.mean(xs))
        kind = "junction" if np.any(junction_mask[ys, xs]) else "endpoint"

        nodes.append((center_y, center_x, kind))

        for y, x in zip(ys.tolist(), xs.tolist()):
            pixel_to_node[(y, x)] = node_index

    edges: List[Tuple[int, int, float]] = []
    seen_edge_keys = set()
    visited_path_pixels = np.zeros_like(skeleton_mask, dtype=bool)

    # Safety cap on path length so a pathological/corrupt skeleton can
    # never turn into an infinite loop — real corridor traces are nowhere
    # near this long even on the largest maps this project handles.
    max_path_pixels = skeleton_mask.size + 10

    for start_index, (start_y, start_x, _kind) in enumerate(nodes):
        start_cluster_pixels = [
            pixel
            for pixel, node_index in pixel_to_node.items()
            if node_index == start_index
        ]

        for start_pixel in start_cluster_pixels:
            for first_step in _get_skeleton_neighbors(
                skeleton_mask, *start_pixel
            ):
                if first_step in pixel_to_node:
                    # Directly touches another node's cluster (or its own)
                    # with no corridor in between — not a meaningful edge
                    # to trace pixel-by-pixel; real same-cluster adjacency
                    # is already merged into one node above.
                    continue

                if visited_path_pixels[first_step]:
                    continue

                path_length_px = 0.0
                previous = start_pixel
                current = first_step
                visited_path_pixels[current] = True
                reached_node = None

                for _ in range(max_path_pixels):
                    path_length_px += math.hypot(
                        current[1] - previous[1],
                        current[0] - previous[0],
                    )

                    neighbors = [
                        p
                        for p in _get_skeleton_neighbors(
                            skeleton_mask, *current
                        )
                        if p != previous
                    ]

                    node_neighbor = next(
                        (p for p in neighbors if p in pixel_to_node),
                        None,
                    )

                    if node_neighbor is not None:
                        path_length_px += math.hypot(
                            node_neighbor[1] - current[1],
                            node_neighbor[0] - current[0],
                        )
                        reached_node = pixel_to_node[node_neighbor]
                        break

                    corridor_neighbors = [
                        p for p in neighbors if p not in pixel_to_node
                    ]

                    if len(corridor_neighbors) != 1:
                        # Dead end, or an unexpected branch that clustering
                        # didn't absorb — stop tracing this path rather
                        # than guess.
                        break

                    next_pixel = corridor_neighbors[0]

                    if visited_path_pixels[next_pixel]:
                        break

                    visited_path_pixels[next_pixel] = True
                    previous, current = current, next_pixel

                if reached_node is not None and reached_node != start_index:
                    edge_key = tuple(
                        sorted((start_index, reached_node))
                    ) + (round(path_length_px, 1),)

                    if edge_key not in seen_edge_keys:
                        seen_edge_keys.add(edge_key)
                        edges.append(
                            (start_index, reached_node, path_length_px)
                        )

    return nodes, edges


# =========================================================
# Post-processing: prune short dead-end spurs
# =========================================================

def _prune_short_spurs(
    nodes: List[Tuple[float, float, str]],
    edges: List[Tuple[int, int, float]],
    min_spur_length_px: float,
    max_passes: int = 6,
) -> Tuple[List[Tuple[float, float, str]], List[Tuple[int, int, float]]]:
    """
    Raw skeletons routinely have small dead-end branches caused by mask
    boundary noise (a doorway notch, a slightly ragged wall edge, text
    interfering with the wall detector) rather than a real corridor
    offshoot. Iteratively drop edges that dead-end (their non-junction
    side has no other edges) and are shorter than `min_spur_length_px` —
    a real corridor branch practically always reaches another junction or
    runs far enough to matter; noise spurs are short by construction.
    Never touches a node/edge that isn't a genuine leaf, so real branching
    junctions and long dead-end corridors (e.g. a corridor ending at a
    single shop) are preserved.
    """

    remaining_edges = list(edges)

    for _ in range(max_passes):
        degree: Dict[int, int] = {}

        for a, b, _length in remaining_edges:
            degree[a] = degree.get(a, 0) + 1
            degree[b] = degree.get(b, 0) + 1

        next_edges = []
        removed_any = False

        for a, b, length in remaining_edges:
            a_is_leaf = degree.get(a, 0) == 1
            b_is_leaf = degree.get(b, 0) == 1

            if (a_is_leaf or b_is_leaf) and length < min_spur_length_px:
                removed_any = True
                continue

            next_edges.append((a, b, length))

        remaining_edges = next_edges

        if not removed_any:
            break

    connected_node_indices = set()

    for a, b, _length in remaining_edges:
        connected_node_indices.add(a)
        connected_node_indices.add(b)

    kept_nodes = []
    old_to_new_index: Dict[int, int] = {}

    for old_index, node in enumerate(nodes):
        if old_index not in connected_node_indices:
            continue

        old_to_new_index[old_index] = len(kept_nodes)
        kept_nodes.append(node)

    kept_edges = [
        (old_to_new_index[a], old_to_new_index[b], length)
        for a, b, length in remaining_edges
    ]

    return kept_nodes, kept_edges


# =========================================================
# Confidence scoring
# =========================================================

def _score_confidence(
    walkable_fraction: float,
    component_count: int,
    node_count: int,
    edge_count: int,
) -> float:
    """
    A deliberately conservative heuristic — there is no ground truth to
    calibrate against, so this is tuned to reject obviously-bad results
    (near-zero or near-total "walkable" area, no usable topology) rather
    than to precisely rank good ones.
    """

    if node_count < 2 or edge_count < 1:
        return 0.0

    # A real floor plan's open/walkable area is rarely under ~8% (a mask
    # that thinks almost everything is a wall found nothing usable) or
    # over ~90% (a mask that thinks almost nothing is a wall — the line
    # detector likely failed on this image).
    if walkable_fraction < 0.08 or walkable_fraction > 0.90:
        area_score = 0.15
    else:
        # Peaks around a plausible mid-range fraction of open corridor
        # space and tapers off toward the rejected extremes.
        distance_from_ideal = abs(walkable_fraction - 0.35)
        area_score = max(0.0, 1.0 - (distance_from_ideal / 0.35))

    # Prefer a small number of dominant open regions (one connected
    # corridor network) over many fragmented ones.
    if component_count <= 3:
        fragmentation_score = 1.0
    elif component_count <= 8:
        fragmentation_score = 0.6
    else:
        fragmentation_score = 0.25

    # A handful of nodes/edges is a real but tiny/likely-incomplete graph;
    # a reasonable corridor network has dozens. Well past a few hundred on
    # a single floor is far more likely to be mask noise (fine text,
    # furniture icons, decorative lines all misread as "walls",
    # fragmenting the walkable space) than a genuinely intricate corridor
    # network, so the score comes back down past that point instead of
    # staying capped at 1.0.
    if node_count <= 12:
        size_score = node_count / 12.0
    elif node_count <= 150:
        size_score = 1.0
    else:
        size_score = max(0.15, 1.0 - ((node_count - 150) / 400.0))

    confidence = (
        0.40 * area_score
        + 0.30 * fragmentation_score
        + 0.30 * size_score
    )

    return round(max(0.0, min(1.0, confidence)), 3)


# =========================================================
# Top-level extraction entry point (pure CV, no DB access)
# =========================================================

def extract_walkable_graph(
    source_image_path: Path,
) -> GraphExtractionResult:
    gray_image = cv2.imread(str(source_image_path), cv2.IMREAD_GRAYSCALE)

    if gray_image is None:
        return GraphExtractionResult(
            note="Could not read the source image for graph generation."
        )

    original_height, original_width = gray_image.shape[:2]
    longest_side = max(original_height, original_width)
    downscale = min(1.0, MAX_PROCESSING_DIMENSION / float(longest_side))

    if downscale < 1.0:
        working_image = cv2.resize(
            gray_image,
            (
                max(1, int(round(original_width * downscale))),
                max(1, int(round(original_height * downscale))),
            ),
            interpolation=cv2.INTER_AREA,
        )
    else:
        working_image = gray_image

    walkable_mask, walkable_fraction, component_count = _build_walkable_mask(
        working_image
    )

    # A small safety margin away from detected walls keeps the skeleton's
    # centerline from hugging wall pixels and producing spurious short
    # branches right along every boundary.
    eroded = cv2.erode(
        walkable_mask,
        np.ones((3, 3), dtype=np.uint8),
        iterations=1,
    )

    # Erosion can fully close very narrow corridors on low-resolution
    # working images; fall back to the un-eroded mask if that happens
    # rather than silently losing most of the network.
    if np.count_nonzero(eroded) < np.count_nonzero(walkable_mask) * 0.3:
        eroded = walkable_mask

    skeleton = _zhang_suen_thin(eroded)

    raw_nodes, raw_edges = _extract_graph_from_skeleton(skeleton)

    # Threshold scales with the map's own size (in original-image pixels,
    # converted into the downscaled working space this function operates
    # in) rather than a fixed pixel count, so it behaves consistently
    # whether the source map is a small single-store floor plan or a
    # multi-thousand-pixel mall scan.
    min_spur_length_original_px = max(25.0, longest_side * 0.02)
    min_spur_length_working_px = min_spur_length_original_px * downscale

    raw_nodes, raw_edges = _prune_short_spurs(
        raw_nodes,
        raw_edges,
        min_spur_length_working_px,
    )

    confidence = _score_confidence(
        walkable_fraction,
        component_count,
        len(raw_nodes),
        len(raw_edges),
    )

    scale_back = (1.0 / downscale) if downscale > 0 else 1.0

    nodes = [
        GeneratedNode(
            x=round(col * scale_back, 2),
            y=round(row * scale_back, 2),
            kind=kind,
        )
        for row, col, kind in raw_nodes
    ]

    edges = [
        GeneratedEdge(
            from_index=a,
            to_index=b,
            pixel_length=round(length_px * scale_back, 2),
        )
        for a, b, length_px in raw_edges
    ]

    if confidence < MIN_CONFIDENCE_TO_APPLY:
        note = (
            "Automatic graph generation produced a low-confidence result "
            f"(confidence={confidence}, walkable_fraction="
            f"{round(walkable_fraction, 3)}, open_regions={component_count}, "
            f"nodes={len(nodes)}, edges={len(edges)}). This is a purely "
            "geometric heuristic with no understanding of which open areas "
            "are actually corridors versus shop interiors, so a low score "
            "here is expected on complex or cluttered floor plans. No "
            "points or edges were created — draw the walkable path "
            "manually for this map."
        )
    else:
        note = (
            f"Automatic graph generation found {len(nodes)} node(s) and "
            f"{len(edges)} edge(s) (confidence={confidence}, "
            f"walkable_fraction={round(walkable_fraction, 3)}, "
            f"open_regions={component_count}). This is a geometric "
            "heuristic (open-space skeleton), not semantic room "
            "understanding — review the generated graph before relying on "
            "it for navigation."
        )

    return GraphExtractionResult(
        nodes=nodes,
        edges=edges,
        confidence=confidence,
        walkable_fraction=round(walkable_fraction, 4),
        component_count=component_count,
        note=note,
    )


# =========================================================
# DB persistence — regeneration-safe, compensating rollback
# =========================================================

@dataclass
class GraphGenerationOutcome:
    applied: bool
    points_created: int
    edges_created: int
    points_cleared: int
    edges_cleared: int
    confidence: float
    note: str


async def _clear_previous_auto_generated_graph(
    map_id: str,
    floor: Optional[int],
) -> Tuple[int, int]:
    """
    Removes this map/floor's previously auto-generated edges, then its
    previously auto-generated points — but only points that no longer have
    ANY edge (manual or auto) still referencing them, so a manual edge an
    admin deliberately drew to a generated point is never silently broken
    by a later regeneration. Returns (points_cleared, edges_cleared).
    """

    edge_query = {
        "map_id": map_id,
        "is_auto_generated": True,
    }

    point_query = {
        "map_id": map_id,
        "is_auto_generated": True,
    }

    if floor is not None:
        # RouteEdge has no floor field of its own; floor scoping for edges
        # happens through their endpoint points below instead.
        point_query["floor"] = floor

    auto_points = await RoutePoint.find(point_query).to_list()
    auto_point_ids = {str(point.id) for point in auto_points}

    if not auto_point_ids:
        return 0, 0

    auto_edges = await RouteEdge.find(edge_query).to_list()
    edges_to_delete = [
        edge
        for edge in auto_edges
        if edge.from_point_id in auto_point_ids
        or edge.to_point_id in auto_point_ids
    ]

    for edge in edges_to_delete:
        await edge.delete()

    edges_cleared = len(edges_to_delete)

    # Re-check which points still have ANY remaining edge (manual edges
    # the admin drew to/from a generated point must keep that point
    # alive) after removing the auto-generated edges above.
    remaining_edges = await RouteEdge.find(
        {
            "map_id": map_id,
            "$or": [
                {"from_point_id": {"$in": list(auto_point_ids)}},
                {"to_point_id": {"$in": list(auto_point_ids)}},
            ],
        }
    ).to_list()

    still_referenced_point_ids = set()
    for edge in remaining_edges:
        still_referenced_point_ids.add(edge.from_point_id)
        still_referenced_point_ids.add(edge.to_point_id)

    points_cleared = 0

    for point in auto_points:
        point_id = str(point.id)

        if point_id in still_referenced_point_ids:
            continue

        await point.delete()
        points_cleared += 1

    return points_cleared, edges_cleared


async def generate_and_apply_walkable_graph(
    map_item: "Map",
    source_image_path: Path,
) -> GraphGenerationOutcome:
    """
    Full Priority 3 flow for one map: extract a graph from its source
    image (CPU-heavy, run off the event loop), clear that map/floor's
    previous auto-generated graph (regeneration must not duplicate),
    then create the new RoutePoints/RouteEdges. If edge creation fails
    partway through, only the records created by THIS run are rolled
    back — never anything that existed before it started.
    """

    extraction = await asyncio.to_thread(
        extract_walkable_graph, source_image_path
    )

    map_id = str(map_item.id)
    floor = map_item.floor if map_item.floor is not None else 0

    if extraction.confidence < MIN_CONFIDENCE_TO_APPLY or not extraction.nodes:
        map_item.graph_generation_status = "low_confidence"
        map_item.graph_generation_confidence = extraction.confidence
        map_item.graph_generation_note = extraction.note
        map_item.graph_generated_at = datetime.utcnow()

        await map_item.save()

        return GraphGenerationOutcome(
            applied=False,
            points_created=0,
            edges_created=0,
            points_cleared=0,
            edges_cleared=0,
            confidence=extraction.confidence,
            note=extraction.note,
        )

    points_cleared, edges_cleared = await _clear_previous_auto_generated_graph(
        map_id, floor
    )

    created_points: List[RoutePoint] = []
    created_point_ids: List[str] = []
    created_edges: List[RouteEdge] = []

    try:
        for index, node in enumerate(extraction.nodes):
            new_point = RoutePoint(
                map_id=map_id,
                name=f"Auto Point {index + 1}",
                point_type="hallway",
                x=node.x,
                y=node.y,
                floor=floor,
                building_id=map_item.building_id,
                is_auto_generated=True,
                generation_method=GENERATION_METHOD_LOCAL,
                generation_confidence=extraction.confidence,
                generation_version=GRAPH_GENERATION_VERSION,
            )

            await new_point.insert()
            created_points.append(new_point)
            created_point_ids.append(str(new_point.id))

        floor_scale = (
            map_item.floor_scales.get(str(floor))
            if map_item.floor_scales
            else None
        )

        if floor_scale is None:
            floor_scale = map_item.scale

        for edge in extraction.edges:
            from_id = created_point_ids[edge.from_index]
            to_id = created_point_ids[edge.to_index]

            if from_id == to_id:
                continue

            new_edge = RouteEdge(
                map_id=map_id,
                from_point_id=from_id,
                to_point_id=to_id,
                edge_type="walkway",
                distance=round(edge.pixel_length * floor_scale, 2),
                is_bidirectional=True,
                is_accessible=True,
                is_auto_generated=True,
                generation_method=GENERATION_METHOD_LOCAL,
                generation_confidence=extraction.confidence,
                generation_version=GRAPH_GENERATION_VERSION,
            )

            await new_edge.insert()
            created_edges.append(new_edge)

    except Exception as error:
        for edge in created_edges:
            try:
                await edge.delete()
            except Exception:
                pass

        for point in created_points:
            try:
                await point.delete()
            except Exception:
                pass

        return GraphGenerationOutcome(
            applied=False,
            points_created=0,
            edges_created=0,
            points_cleared=points_cleared,
            edges_cleared=edges_cleared,
            confidence=extraction.confidence,
            note=(
                f"Graph generation failed while saving records and was "
                f"rolled back: {error}"
            ),
        )

    map_item.graph_generation_status = "applied"
    map_item.graph_generation_confidence = extraction.confidence
    map_item.graph_generation_note = extraction.note
    map_item.graph_generated_at = datetime.utcnow()

    await map_item.save()

    return GraphGenerationOutcome(
        applied=True,
        points_created=len(created_points),
        edges_created=len(created_edges),
        points_cleared=points_cleared,
        edges_cleared=edges_cleared,
        confidence=extraction.confidence,
        note=extraction.note,
    )
