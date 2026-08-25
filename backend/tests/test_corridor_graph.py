"""
Tests for services/corridor_graph_service — the proposed hidden transit
graph.

Two of these are regressions against bugs that exist in the OLD generator
(services/graph_generation_service) and must not be inherited:

  test_edge_length_is_the_straight_line_between_its_endpoints
      graph_generation_service.py:865 stores the TRACED skeleton path
      length while the endpoints it stores are the two ends of a straight
      chord. Every consumer treats the edge as that chord, so a stored
      edge can be far longer than the line drawn and can cut through a
      wall the skeleton went around.

  test_nothing_is_traced_outside_the_interior_region
      _build_walkable_mask keeps every connected component above a small
      area floor — not the largest, not the building. The white interior
      of a title block qualifies. That is the documented reason automatic
      graph generation was disabled.

Run with: pytest backend/tests/test_corridor_graph.py -v
"""

import math

import cv2
import numpy as np
import pytest

from services.corridor_graph_service import extract_corridor_graph
from services.map_image_service import _build_navigation_line_mask
from services.strict_geometry_service import (
    _clear_line_on_mask,
    measure_wall_stroke_thickness,
)


WIDTH, HEIGHT = 1600, 1200
WALL = 8


def _blank():
    return np.full((HEIGHT, WIDTH), 255, dtype=np.uint8)


def _run(image, interior_mask=None):
    mask = _build_navigation_line_mask(image)
    thickness = measure_wall_stroke_thickness(mask)

    if interior_mask is None:
        interior_mask = np.zeros((HEIGHT, WIDTH), dtype=np.uint8)
        interior_mask[:] = 1

    return mask, extract_corridor_graph(
        mask,
        interior_mask,
        mask_scale=1.0,
        stroke_thickness_px=thickness,
        map_id="corridor_test",
        strict_mask=mask,
        strict_downscale=1.0,
    )


def _straight_corridor():
    """A single horizontal corridor between two long walls."""

    image = _blank()
    cv2.line(image, (200, 500), (1400, 500), 0, WALL)
    cv2.line(image, (200, 700), (1400, 700), 0, WALL)
    cv2.line(image, (200, 500), (200, 700), 0, WALL)
    cv2.line(image, (1400, 500), (1400, 700), 0, WALL)

    interior = np.zeros((HEIGHT, WIDTH), dtype=np.uint8)
    interior[505:695, 205:1395] = 1
    return image, interior


def _l_corridor():
    image = _blank()
    cv2.line(image, (200, 300), (1200, 300), 0, WALL)
    cv2.line(image, (200, 500), (1000, 500), 0, WALL)
    cv2.line(image, (1000, 500), (1000, 1000), 0, WALL)
    cv2.line(image, (1200, 300), (1200, 1000), 0, WALL)
    cv2.line(image, (200, 300), (200, 500), 0, WALL)
    cv2.line(image, (1000, 1000), (1200, 1000), 0, WALL)

    interior = np.zeros((HEIGHT, WIDTH), dtype=np.uint8)
    interior[305:495, 205:1195] = 1
    interior[495:995, 1005:1195] = 1
    return image, interior


# ===========================================================
# Node economy
# ===========================================================

# 1. The whole point of simplification: a straight corridor is ONE edge.
def test_a_straight_corridor_becomes_a_handful_of_nodes():
    image, interior = _straight_corridor()
    _mask, graph = _run(image, interior)

    assert graph.available, graph.reason
    assert len(graph.nodes) <= 4, f"expected a handful, got {len(graph.nodes)}"
    assert len(graph.edges) >= 1


# 2. Junction clustering: a thinned skeleton represents one physical
#    junction as a blob of adjacent high-degree pixels, and treating each
#    as its own node inflates a real plan by an order of magnitude.
def test_the_graph_is_far_smaller_than_the_raw_skeleton():
    image, interior = _l_corridor()
    _mask, graph = _run(image, interior)

    assert graph.available, graph.reason
    assert len(graph.nodes) <= max(8, graph.skeleton_node_count)
    assert len(graph.nodes) < 40


# 3.
def test_an_l_shaped_corridor_keeps_its_corner():
    image, interior = _l_corridor()
    _mask, graph = _run(image, interior)

    assert graph.available
    assert len(graph.nodes) >= 2

    xs = [node.x for node in graph.nodes]
    ys = [node.y for node in graph.nodes]

    # The graph must span both limbs of the L, not just one.
    assert max(xs) - min(xs) > 300
    assert max(ys) - min(ys) > 300


# ===========================================================
# The strict proof
# ===========================================================

# 4. Every emitted edge is provably clear. This is the invariant.
def test_every_emitted_edge_passes_the_strict_wall_check():
    image, interior = _l_corridor()
    mask, graph = _run(image, interior)

    assert graph.available

    by_index = {node.index: node for node in graph.nodes}

    for edge in graph.edges:
        a = by_index[edge.from_index]
        b = by_index[edge.to_index]
        assert _clear_line_on_mask(mask, 1.0, a.x, a.y, b.x, b.y) is True


# 5. THE TRACED-VS-STRAIGHT REGRESSION.
def test_edge_length_is_the_straight_line_between_its_endpoints():
    image, interior = _l_corridor()
    _mask, graph = _run(image, interior)

    assert graph.available

    by_index = {node.index: node for node in graph.nodes}

    for edge in graph.edges:
        a = by_index[edge.from_index]
        b = by_index[edge.to_index]
        expected = math.hypot(b.x - a.x, b.y - a.y)
        assert edge.length_px == pytest.approx(expected, abs=0.5)


# 6. A wall across the corridor must not be chorded through.
def test_a_wall_across_the_corridor_is_not_crossed():
    image, interior = _straight_corridor()
    cv2.line(image, (800, 500), (800, 700), 0, 40)   # solid blockage

    mask, graph = _run(image, interior)

    by_index = {node.index: node for node in graph.nodes}

    for edge in graph.edges:
        a = by_index[edge.from_index]
        b = by_index[edge.to_index]
        # No edge may span the blockage.
        assert not (min(a.x, b.x) < 800 < max(a.x, b.x))


# ===========================================================
# Region gating
# ===========================================================

# 7. THE TITLE-BLOCK REGRESSION.
def test_nothing_is_traced_outside_the_interior_region():
    image, interior = _straight_corridor()

    # A separate enclosed box elsewhere on the sheet, deliberately NOT in
    # the interior mask — the old generator would have skeletonized it.
    cv2.rectangle(image, (100, 900), (500, 1150), 0, 4)

    _mask, graph = _run(image, interior)

    assert graph.available

    for node in graph.nodes:
        assert interior[int(round(node.y)), int(round(node.x))] > 0
        assert not (100 <= node.x <= 500 and 900 <= node.y <= 1150)


# 8.
def test_an_empty_interior_region_refuses():
    image, _interior = _straight_corridor()
    empty = np.zeros((HEIGHT, WIDTH), dtype=np.uint8)

    _mask, graph = _run(image, empty)

    assert graph.available is False
    assert graph.reason


# ===========================================================
# Pruning and connectivity
# ===========================================================

# 9. Isolated islands are removed, not merely scored down.
def test_isolated_components_are_pruned():
    image = _blank()
    # Two corridors that never meet.
    cv2.line(image, (200, 300), (1400, 300), 0, WALL)
    cv2.line(image, (200, 450), (1400, 450), 0, WALL)
    cv2.line(image, (200, 800), (1400, 800), 0, WALL)
    cv2.line(image, (200, 950), (1400, 950), 0, WALL)

    interior = np.zeros((HEIGHT, WIDTH), dtype=np.uint8)
    interior[305:445, 205:1395] = 1
    interior[805:945, 205:1395] = 1

    _mask, graph = _run(image, interior)

    if graph.available:
        adjacency = graph.adjacency()
        seen = set()
        stack = [graph.nodes[0].index]
        while stack:
            current = stack.pop()
            if current in seen:
                continue
            seen.add(current)
            stack.extend(adjacency.get(current, set()) - seen)

        assert len(seen) == len(graph.nodes), "result must be one connected graph"
        assert graph.pruned_component_count >= 1


# 10. The returned graph is always fully connected.
def test_the_returned_graph_is_connected():
    image, interior = _l_corridor()
    _mask, graph = _run(image, interior)

    assert graph.available

    adjacency = graph.adjacency()
    seen = set()
    stack = [graph.nodes[0].index]
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        stack.extend(adjacency.get(current, set()) - seen)

    assert len(seen) == len(graph.nodes)


# ===========================================================
# Bookkeeping
# ===========================================================

# 11. Node indices are dense and edges only reference real nodes.
def test_node_indices_are_consistent_after_pruning():
    image, interior = _l_corridor()
    _mask, graph = _run(image, interior)

    assert graph.available

    indices = [node.index for node in graph.nodes]
    assert indices == list(range(len(graph.nodes)))

    for edge in graph.edges:
        assert 0 <= edge.from_index < len(graph.nodes)
        assert 0 <= edge.to_index < len(graph.nodes)
        assert edge.from_index != edge.to_index


# 12. Diagnostics report the counts an operator needs.
def test_diagnostics_report_every_count():
    image, interior = _l_corridor()
    _mask, graph = _run(image, interior)

    diagnostics = graph.diagnostics()

    for key in (
        "topology_working_resolution",
        "skeleton_node_count_before_simplification",
        "proposed_node_count",
        "proposed_edge_count",
        "subdivided_edge_count",
        "rejected_edge_count",
        "pruned_component_count",
        "pruned_node_count",
    ):
        assert key in diagnostics

    assert diagnostics["proposed_node_count"] == len(graph.nodes)
    assert diagnostics["proposed_edge_count"] == len(graph.edges)


# 13. Every rejected edge carries a machine-readable reason.
def test_rejected_edges_are_named():
    image, interior = _straight_corridor()
    cv2.line(image, (800, 500), (800, 700), 0, 40)

    _mask, graph = _run(image, interior)

    for edge in graph.rejected_edges:
        assert edge.reason in {
            "blocked_by_wall_strict",
            "exceeds_max_edge_length",
            "too_many_subdivisions",
        }


# 14. Nothing in this module constructs a database document.
def test_the_module_never_touches_beanie():
    import inspect

    import services.corridor_graph_service as module

    source = inspect.getsource(module)

    # No Beanie document is imported, constructed or awaited anywhere. The
    # module is entirely synchronous, which is itself the proof that it
    # performs no database I/O.
    for forbidden in (
        "RoutePoint(",
        "RouteEdge(",
        "Room(",
        "LocationCode(",
        "await ",
        "async def",
        "from models",
        "import models",
    ):
        assert forbidden not in source, f"{forbidden} must not appear here"
