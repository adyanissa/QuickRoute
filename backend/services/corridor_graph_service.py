"""
Corridor centreline extraction — the hidden transit graph, derived from
the drawing rather than drawn by an admin.

IN-MEMORY ONLY. Nothing in this module constructs a Beanie document,
touches the database, or persists anything. It produces a validated graph
object; deciding whether to store it is Phase B's problem.

TWO RESOLUTIONS, ON PURPOSE
---------------------------
Zhang-Suen thinning runs up to 200 passes of ~10 full-array numpy shifts.
On a 4000x3000 mask that is not viable, and it is not necessary either:
corridor topology is a coarse question. So the skeleton is traced at a
bounded WORKING resolution, and every edge it proposes is then re-proven
at STRICT resolution against the unmodified wall mask. Topology is cheap
and approximate; the safety proof is expensive and exact.

TWO BUGS IN THE OLD GENERATOR THIS DELIBERATELY DOES NOT INHERIT
-----------------------------------------------------------------
1. graph_generation_service.py:865 stores
   `distance = edge.pixel_length * floor_scale`, where `pixel_length` is
   the TRACED skeleton path length — while `from_point_id`/`to_point_id`
   are its two endpoints and every consumer (the router, the admin map)
   treats the edge as a straight chord. A stored edge could therefore be
   far longer than the line drawn, and could cut through a wall the
   skeleton carefully went around. Here, an edge's length is always the
   straight-line distance between its two stored endpoints, and where the
   traced path curves away from that chord the edge is SUBDIVIDED at
   retained polyline vertices until every straight piece is both short
   enough to be honest and provably clear.

2. graph_generation_service._build_walkable_mask keeps every connected
   component above a small area floor — not the largest, not the
   building. The white interior of a title block qualifies. Here the
   walkable mask is intersected with the interior region decided by
   building_region_service before anything is traced.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

import cv2
import numpy as np

from services.graph_generation_service import _zhang_suen_thin
from services.strict_geometry_service import _clear_line_on_mask


# Longest side the skeleton is traced at. Topology only.
TOPOLOGY_MAX_EDGE_PX = 1200

# Douglas-Peucker tolerance for collapsing a traced corridor polyline into
# straight runs, as a fraction of the working image's longest side. A
# straight 400 px corridor should become one edge, not forty.
SIMPLIFY_TOLERANCE_FRACTION = 0.004
MIN_SIMPLIFY_TOLERANCE_PX = 2.0

# Dead-end spurs shorter than this fraction of the longest side are mask
# noise (a doorway notch, a ragged wall edge), not corridor branches.
SPUR_LENGTH_FRACTION = 0.02
MIN_SPUR_LENGTH_PX = 12.0

# An edge longer than this fraction of the image diagonal is refused
# outright, however clear it looks — a single hop across half the floor is
# never a real corridor segment and would make instructions nonsense.
MAX_EDGE_DIAGONAL_FRACTION = 0.45

# When a chord fails validation, the traced polyline is reinstated between
# its endpoints. This bounds how many pieces one edge may be cut into
# before it is abandoned.
MAX_SUBDIVISIONS_PER_EDGE = 24

# Erode the walkable mask by this multiple of the wall stroke thickness
# before thinning, so the centreline sits away from wall faces.
WALKABLE_EROSION_THICKNESS_MULTIPLE = 0.5

# A thinned skeleton represents one physical junction as a small blob of
# adjacent high-degree pixels. Dilating by this before labelling merges
# that blob into a single node.
NODE_CLUSTER_KERNEL_PX = 5


@dataclass
class GraphNode:
    """A hidden transit node. Coordinates in FULL-RESOLUTION source px."""

    index: int
    x: float
    y: float
    kind: str = "junction"        # junction | endpoint | waypoint

    def to_dict(self) -> Dict[str, Any]:
        return {
            "index": self.index,
            "x": round(self.x, 1),
            "y": round(self.y, 1),
            "kind": self.kind,
        }


@dataclass
class GraphEdge:
    from_index: int
    to_index: int
    length_px: float              # straight line between the two endpoints
    subdivided_from: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "from_index": self.from_index,
            "to_index": self.to_index,
            "length_px": round(self.length_px, 1),
            "subdivided": self.subdivided_from is not None,
        }


@dataclass
class RejectedEdge:
    from_xy: Tuple[float, float]
    to_xy: Tuple[float, float]
    reason: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "from": [round(self.from_xy[0], 1), round(self.from_xy[1], 1)],
            "to": [round(self.to_xy[0], 1), round(self.to_xy[1], 1)],
            "reason": self.reason,
        }


@dataclass
class CorridorGraph:
    nodes: List[GraphNode] = field(default_factory=list)
    edges: List[GraphEdge] = field(default_factory=list)
    rejected_edges: List[RejectedEdge] = field(default_factory=list)

    skeleton_node_count: int = 0        # before simplification
    simplified_node_count: int = 0
    subdivided_edge_count: int = 0
    pruned_component_count: int = 0
    pruned_node_count: int = 0
    working_width: int = 0
    working_height: int = 0

    available: bool = False
    reason: Optional[str] = None

    def adjacency(self) -> Dict[int, Set[int]]:
        adjacency: Dict[int, Set[int]] = {n.index: set() for n in self.nodes}
        for edge in self.edges:
            adjacency.setdefault(edge.from_index, set()).add(edge.to_index)
            adjacency.setdefault(edge.to_index, set()).add(edge.from_index)
        return adjacency

    def diagnostics(self) -> Dict[str, Any]:
        return {
            "available": self.available,
            "reason": self.reason,
            "topology_working_resolution": {
                "width": self.working_width,
                "height": self.working_height,
            },
            "skeleton_node_count_before_simplification": self.skeleton_node_count,
            "proposed_node_count": len(self.nodes),
            "proposed_edge_count": len(self.edges),
            "subdivided_edge_count": self.subdivided_edge_count,
            "rejected_edge_count": len(self.rejected_edges),
            "rejected_edges": [e.to_dict() for e in self.rejected_edges[:80]],
            "pruned_component_count": self.pruned_component_count,
            "pruned_node_count": self.pruned_node_count,
        }


# =========================================================
# Skeleton tracing that KEEPS the polyline
# =========================================================


def _neighbors(mask: np.ndarray, y: int, x: int) -> List[Tuple[int, int]]:
    height, width = mask.shape
    found = []
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dy == 0 and dx == 0:
                continue
            ny, nx = y + dy, x + dx
            if 0 <= ny < height and 0 <= nx < width and mask[ny, nx]:
                found.append((ny, nx))
    return found


def _trace_polylines(
    skeleton: np.ndarray,
) -> Tuple[List[Tuple[int, int]], List[Tuple[int, int, List[Tuple[int, int]]]]]:
    """
    Walks the skeleton and returns (node_pixels, branches), where each
    branch is (node_a, node_b, [(y, x), ...]) INCLUDING the full traced
    path between the two nodes.

    Two things this does that matter:

    1. JUNCTION CLUSTERING. In a thinned skeleton a single physical
       junction is normally a small blob of adjacent pixels that each have
       three or more neighbours. Treating every one of them as its own
       node turns one corridor crossing into a knot of nodes joined by
       one-pixel edges — on a real floor plan that inflates the graph by
       an order of magnitude. Adjacent node pixels are therefore dilated
       and connected-component labelled into ONE node at their centroid.

    2. IT KEEPS THE PATH. graph_generation_service's equivalent returns
       only a scalar length and discards the traced route, but the route
       is exactly what is needed to subdivide an edge whose straight chord
       fails the wall check.
    """

    mask = skeleton.astype(bool)
    height, width = mask.shape

    degree = np.zeros_like(mask, dtype=np.int32)
    padded = np.pad(mask.astype(np.int32), 1)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dy == 0 and dx == 0:
                continue
            degree += padded[1 + dy : height + 1 + dy, 1 + dx : width + 1 + dx]
    degree[~mask] = 0

    node_pixel_mask = (mask & ((degree == 1) | (degree >= 3))).astype(np.uint8)

    if not np.any(node_pixel_mask):
        return [], []

    # --- cluster adjacent node pixels into single nodes ---------------
    grown = cv2.dilate(
        node_pixel_mask,
        np.ones((NODE_CLUSTER_KERNEL_PX, NODE_CLUSTER_KERNEL_PX), dtype=np.uint8),
        iterations=1,
    )
    cluster_zone = (grown > 0) & mask

    cluster_count, cluster_labels = cv2.connectedComponents(
        cluster_zone.astype(np.uint8), connectivity=8
    )

    if cluster_count <= 1:
        return [], []

    node_pixels: List[Tuple[int, int]] = []
    for cluster_id in range(1, cluster_count):
        ys, xs = np.nonzero(cluster_labels == cluster_id)
        if ys.size == 0:
            node_pixels.append((0, 0))
            continue
        node_pixels.append((int(round(ys.mean())), int(round(xs.mean()))))

    def cluster_of(pixel: Tuple[int, int]) -> int:
        return int(cluster_labels[pixel[0], pixel[1]])

    branches: List[Tuple[int, int, List[Tuple[int, int]]]] = []
    seen_steps: Set[Tuple[Tuple[int, int], Tuple[int, int]]] = set()

    # Start from every skeleton pixel that sits in a cluster and has a
    # neighbour outside every cluster — those are the corridor mouths.
    cluster_ys, cluster_xs = np.nonzero(cluster_zone)

    for y, x in zip(cluster_ys, cluster_xs):
        start_cluster = int(cluster_labels[y, x])

        for step in _neighbors(mask, int(y), int(x)):
            if cluster_labels[step[0], step[1]] != 0:
                continue  # still inside a junction blob
            if ((int(y), int(x)), step) in seen_steps:
                continue

            path = [(int(y), int(x)), step]
            seen_steps.add(((int(y), int(x)), step))
            previous = (int(y), int(x))
            current = step

            while cluster_labels[current[0], current[1]] == 0:
                options = [p for p in _neighbors(mask, *current) if p != previous]

                if not options:
                    break

                nxt = options[0]
                seen_steps.add((current, nxt))
                seen_steps.add((nxt, current))
                previous, current = current, nxt
                path.append(current)

                if len(path) > mask.size:
                    break

            end_cluster = int(cluster_labels[current[0], current[1]])

            if end_cluster == 0 or end_cluster == start_cluster:
                continue

            seen_steps.add((current, previous))

            # Snap the path ends onto the two cluster centroids so an edge
            # runs centre-to-centre rather than mouth-to-mouth.
            path[0] = node_pixels[start_cluster - 1]
            path[-1] = node_pixels[end_cluster - 1]

            branches.append((start_cluster - 1, end_cluster - 1, path))

    unique: Dict[Tuple[int, int], Tuple[int, int, List[Tuple[int, int]]]] = {}
    for a, b, path in branches:
        key = (min(a, b), max(a, b))
        if key not in unique or len(path) < len(unique[key][2]):
            unique[key] = (a, b, path)

    return node_pixels, list(unique.values())


def _densify(
    points: List[Tuple[int, int]], max_step: float
) -> List[Tuple[int, int]]:
    """
    Insert intermediate vertices so no consecutive pair is further apart
    than `max_step`.

    A long STRAIGHT corridor simplifies to exactly two vertices, so if the
    chord between them exceeds the edge-length ceiling there is nothing to
    subdivide at and the corridor would be dropped entirely — a real floor
    would lose its main spine. Splitting a straight run into equal pieces
    keeps the geometry identical while respecting the ceiling.
    """

    if max_step <= 0 or len(points) < 2:
        return list(points)

    result: List[Tuple[int, int]] = [points[0]]

    for previous, current in zip(points[:-1], points[1:]):
        distance = math.hypot(current[0] - previous[0], current[1] - previous[1])

        if distance > max_step:
            steps = int(math.ceil(distance / max_step))
            for step in range(1, steps):
                t = step / steps
                result.append(
                    (
                        int(round(previous[0] + (current[0] - previous[0]) * t)),
                        int(round(previous[1] + (current[1] - previous[1]) * t)),
                    )
                )

        result.append(current)

    return result


def _simplify_polyline(
    path: Sequence[Tuple[int, int]], tolerance_px: float
) -> List[Tuple[int, int]]:
    """Douglas-Peucker via cv2.approxPolyDP, endpoints always preserved."""

    if len(path) <= 2:
        return list(path)

    points = np.array([[[float(x), float(y)]] for (y, x) in path], dtype=np.float32)
    approximated = cv2.approxPolyDP(points, tolerance_px, False)

    simplified = [(int(round(p[0][1])), int(round(p[0][0]))) for p in approximated]

    if simplified[0] != tuple(path[0]):
        simplified.insert(0, tuple(path[0]))
    if simplified[-1] != tuple(path[-1]):
        simplified.append(tuple(path[-1]))

    return simplified


# =========================================================
# Extraction
# =========================================================


def _prune_spur_branches(
    branches: List[Tuple[int, int, List[Tuple[int, int]]]],
    min_length_px: float,
    max_passes: int = 6,
) -> List[Tuple[int, int, List[Tuple[int, int]]]]:
    remaining = list(branches)

    for _ in range(max_passes):
        degree: Dict[int, int] = {}
        for a, b, _path in remaining:
            degree[a] = degree.get(a, 0) + 1
            degree[b] = degree.get(b, 0) + 1

        kept = []
        removed = False

        for a, b, path in remaining:
            traced = sum(
                math.hypot(path[i + 1][0] - path[i][0], path[i + 1][1] - path[i][1])
                for i in range(len(path) - 1)
            )
            is_leaf = degree.get(a, 0) == 1 or degree.get(b, 0) == 1

            if is_leaf and traced < min_length_px:
                removed = True
                continue

            kept.append((a, b, path))

        remaining = kept

        if not removed:
            break

    return remaining


def extract_corridor_graph(
    wall_mask: np.ndarray,
    interior_mask: np.ndarray,
    *,
    mask_scale: float,
    stroke_thickness_px: float,
    map_id: str,
    strict_mask: np.ndarray,
    strict_downscale: float,
) -> CorridorGraph:
    """
    Build and fully validate a corridor graph.

    `wall_mask` / `interior_mask` are at region-analysis resolution and
    `mask_scale` converts full-resolution source pixels into that space.
    `strict_mask` / `strict_downscale` are the strict validator's own mask,
    used for every clear-line proof.

    Every returned edge has been proven clear at strict resolution. Every
    returned length is the straight-line distance between its own two
    stored endpoints.
    """

    graph = CorridorGraph()

    if interior_mask is None or not np.any(interior_mask):
        graph.reason = "No building interior was identified, so no corridors were traced."
        return graph

    height, width = wall_mask.shape[:2]

    # --- walkable, restricted to the interior region ------------------
    walkable = ((wall_mask == 0) & (interior_mask > 0)).astype(np.uint8)

    erosion_px = max(
        1, int(round(stroke_thickness_px * WALKABLE_EROSION_THICKNESS_MULTIPLE))
    )
    eroded = cv2.erode(
        walkable,
        cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE, (2 * erosion_px + 1, 2 * erosion_px + 1)
        ),
        iterations=1,
    )

    # Erosion can wipe out a genuinely narrow corridor; fall back rather
    # than silently losing it (same defensive shape the old generator used).
    if np.count_nonzero(eroded) < 0.3 * np.count_nonzero(walkable):
        eroded = walkable

    # --- topology at a bounded working resolution ---------------------
    longest = max(height, width)
    topology_scale = min(1.0, float(TOPOLOGY_MAX_EDGE_PX) / float(longest))

    if topology_scale < 1.0:
        working = cv2.resize(
            eroded,
            (
                max(1, int(round(width * topology_scale))),
                max(1, int(round(height * topology_scale))),
            ),
            interpolation=cv2.INTER_NEAREST,
        )
    else:
        working = eroded

    graph.working_width = int(working.shape[1])
    graph.working_height = int(working.shape[0])

    skeleton = _zhang_suen_thin(working)

    node_pixels, branches = _trace_polylines(skeleton)
    graph.skeleton_node_count = len(node_pixels)

    if not branches:
        graph.reason = (
            "No corridor centrelines could be traced inside the building "
            "region — the open space may be too fragmented or too narrow."
        )
        return graph

    working_longest = max(working.shape[0], working.shape[1])
    spur_length = max(MIN_SPUR_LENGTH_PX, working_longest * SPUR_LENGTH_FRACTION)
    branches = _prune_spur_branches(branches, spur_length)

    if not branches:
        graph.reason = "Every traced corridor was a short dead-end spur; nothing survived pruning."
        return graph

    tolerance = max(
        MIN_SIMPLIFY_TOLERANCE_PX, working_longest * SIMPLIFY_TOLERANCE_FRACTION
    )

    # working px -> full-resolution source px
    to_source = (1.0 / topology_scale if topology_scale else 1.0) * (
        1.0 / mask_scale if mask_scale else 1.0
    )

    nodes: List[GraphNode] = []
    node_at_source: Dict[Tuple[int, int], int] = {}

    def node_for(pixel_yx: Tuple[int, int], kind: str) -> int:
        key = (int(pixel_yx[0]), int(pixel_yx[1]))
        if key in node_at_source:
            return node_at_source[key]
        index = len(nodes)
        nodes.append(
            GraphNode(
                index=index,
                x=float(pixel_yx[1]) * to_source,
                y=float(pixel_yx[0]) * to_source,
                kind=kind,
            )
        )
        node_at_source[key] = index
        return index

    edges: List[GraphEdge] = []
    rejected: List[RejectedEdge] = []
    subdivided = 0

    diagonal_source = math.hypot(height, width) * (
        1.0 / mask_scale if mask_scale else 1.0
    )
    max_edge_px = diagonal_source * MAX_EDGE_DIAGONAL_FRACTION

    def clear(ax: float, ay: float, bx: float, by: float) -> bool:
        return _clear_line_on_mask(strict_mask, strict_downscale, ax, ay, bx, by)

    def to_xy(pixel: Tuple[int, int]) -> Tuple[float, float]:
        return (float(pixel[1]) * to_source, float(pixel[0]) * to_source)

    for a_node, b_node, path in branches:
        # CHORD FIRST. A straight corridor must become ONE edge between two
        # nodes, not one edge per traced vertex — the old generator's node
        # explosion is what made an automatic graph unusable in the admin
        # UI. Only when the straight chord cannot be proven clear is the
        # traced polyline reinstated, and then only as far as necessary.
        ax, ay = to_xy(path[0])
        bx, by = to_xy(path[-1])
        chord = math.hypot(bx - ax, by - ay)

        if 0 < chord <= max_edge_px and clear(ax, ay, bx, by):
            from_index = node_for(path[0], "junction")
            to_index = node_for(path[-1], "junction")
            if from_index != to_index:
                edges.append(
                    GraphEdge(
                        from_index=from_index,
                        to_index=to_index,
                        length_px=chord,
                    )
                )
            continue

        # The chord is blocked or too long: keep the shape of the corridor,
        # then make sure no single piece exceeds the length ceiling.
        simplified = _simplify_polyline(path, tolerance)
        max_step_working = max_edge_px / to_source if to_source else max_edge_px
        simplified = _densify(simplified, max_step_working * 0.9)
        pieces = list(zip(simplified[:-1], simplified[1:]))

        if len(pieces) > MAX_SUBDIVISIONS_PER_EDGE:
            rejected.append(
                RejectedEdge((ax, ay), (bx, by), "too_many_subdivisions")
            )
            continue

        piece_edges: List[Tuple[Tuple[int, int], Tuple[int, int], float]] = []
        failed = False

        for p0, p1 in pieces:
            px0, py0 = to_xy(p0)
            px1, py1 = to_xy(p1)
            length = math.hypot(px1 - px0, py1 - py0)

            if length <= 0:
                continue

            if length > max_edge_px:
                rejected.append(
                    RejectedEdge((px0, py0), (px1, py1), "exceeds_max_edge_length")
                )
                failed = True
                break

            # THE STRICT PROOF. Nothing reaches the output without it.
            if not clear(px0, py0, px1, py1):
                rejected.append(
                    RejectedEdge((px0, py0), (px1, py1), "blocked_by_wall_strict")
                )
                failed = True
                break

            piece_edges.append((p0, p1, length))

        if failed or not piece_edges:
            continue

        subdivided += 1

        for position, (p0, p1, length) in enumerate(piece_edges):
            from_kind = "junction" if position == 0 else "waypoint"
            to_kind = (
                "junction" if position == len(piece_edges) - 1 else "waypoint"
            )
            from_index = node_for(p0, from_kind)
            to_index = node_for(p1, to_kind)

            if from_index == to_index:
                continue

            edges.append(
                GraphEdge(
                    from_index=from_index,
                    to_index=to_index,
                    length_px=length,
                    subdivided_from=a_node,
                )
            )

    graph.subdivided_edge_count = subdivided
    graph.rejected_edges = rejected
    graph.simplified_node_count = len(nodes)

    if not edges:
        graph.nodes = []
        graph.reason = (
            "Every traced corridor segment failed the strict wall check, so "
            "no corridor graph could be proposed."
        )
        return graph

    nodes, edges = _dissolve_degree_two_nodes(
        nodes, edges, clear, max_edge_px
    )

    nodes, edges, pruned_components, pruned_nodes = _prune_isolated_components(
        nodes, edges
    )

    graph.nodes = nodes
    graph.edges = edges
    graph.pruned_component_count = pruned_components
    graph.pruned_node_count = pruned_nodes
    graph.available = bool(edges)

    if not graph.available:
        graph.reason = "No connected corridor network survived pruning."

    return graph


def _dissolve_degree_two_nodes(
    nodes: List[GraphNode],
    edges: List[GraphEdge],
    clear,
    max_edge_px: float,
    max_passes: int = 8,
) -> Tuple[List[GraphNode], List[GraphEdge]]:
    """
    Collapse a node that merely sits in the middle of a straight run.

    Skeletonizing a wide corridor or an open room produces many spurious
    degree-2 junctions. Each one would become a persisted transit node in
    Phase B and an extra "continue straight" step in the instructions. A
    degree-2 node is dissolved whenever the direct line between its two
    neighbours is itself provably clear and within the length ceiling —
    so simplification can never introduce an unvalidated edge.
    """

    current_edges = list(edges)

    for _ in range(max_passes):
        incident: Dict[int, List[int]] = {}
        for position, edge in enumerate(current_edges):
            incident.setdefault(edge.from_index, []).append(position)
            incident.setdefault(edge.to_index, []).append(position)

        by_index = {node.index: node for node in nodes}
        removed_edges: Set[int] = set()
        added: List[GraphEdge] = []
        dissolved: Set[int] = set()

        for node_index, positions in incident.items():
            if len(positions) != 2 or node_index in dissolved:
                continue

            first, second = positions

            if first in removed_edges or second in removed_edges:
                continue

            edge_a = current_edges[first]
            edge_b = current_edges[second]

            other_a = edge_a.to_index if edge_a.from_index == node_index else edge_a.from_index
            other_b = edge_b.to_index if edge_b.from_index == node_index else edge_b.from_index

            if other_a == other_b or other_a in dissolved or other_b in dissolved:
                continue

            node_a = by_index.get(other_a)
            node_b = by_index.get(other_b)

            if node_a is None or node_b is None:
                continue

            length = math.hypot(node_b.x - node_a.x, node_b.y - node_a.y)

            if length <= 0 or length > max_edge_px:
                continue

            if not clear(node_a.x, node_a.y, node_b.x, node_b.y):
                continue

            removed_edges.add(first)
            removed_edges.add(second)
            dissolved.add(node_index)
            added.append(
                GraphEdge(
                    from_index=other_a,
                    to_index=other_b,
                    length_px=length,
                    subdivided_from=edge_a.subdivided_from,
                )
            )

        if not dissolved:
            break

        current_edges = [
            edge
            for position, edge in enumerate(current_edges)
            if position not in removed_edges
        ] + added

    kept_indices = set()
    for edge in current_edges:
        kept_indices.add(edge.from_index)
        kept_indices.add(edge.to_index)

    return [node for node in nodes if node.index in kept_indices], current_edges


def _prune_isolated_components(
    nodes: List[GraphNode], edges: List[GraphEdge]
) -> Tuple[List[GraphNode], List[GraphEdge], int, int]:
    """
    Keep only the largest connected subgraph. An island of three nodes in
    a corner is noise, and the old generator kept every one of them — it
    only lowered a confidence score.
    """

    if not edges:
        return [], [], 0, len(nodes)

    adjacency: Dict[int, Set[int]] = {}
    for edge in edges:
        adjacency.setdefault(edge.from_index, set()).add(edge.to_index)
        adjacency.setdefault(edge.to_index, set()).add(edge.from_index)

    seen: Set[int] = set()
    components: List[Set[int]] = []

    for start in adjacency:
        if start in seen:
            continue
        stack = [start]
        component: Set[int] = set()
        while stack:
            current = stack.pop()
            if current in component:
                continue
            component.add(current)
            seen.add(current)
            stack.extend(adjacency.get(current, set()) - component)
        components.append(component)

    if not components:
        return [], [], 0, len(nodes)

    largest = max(components, key=len)
    dropped_components = len(components) - 1
    dropped_nodes = len(nodes) - len(largest)

    remap: Dict[int, int] = {}
    kept_nodes: List[GraphNode] = []

    for node in nodes:
        if node.index not in largest:
            continue
        remap[node.index] = len(kept_nodes)
        kept_nodes.append(
            GraphNode(
                index=len(kept_nodes), x=node.x, y=node.y, kind=node.kind
            )
        )

    kept_edges = [
        GraphEdge(
            from_index=remap[edge.from_index],
            to_index=remap[edge.to_index],
            length_px=edge.length_px,
            subdivided_from=edge.subdivided_from,
        )
        for edge in edges
        if edge.from_index in remap and edge.to_index in remap
    ]

    return kept_nodes, kept_edges, dropped_components, dropped_nodes
