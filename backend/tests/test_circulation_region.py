"""
Room interiors versus shared circulation — the fix for the real-map
failure where the transit graph ran through Central Storage.

THE FAILURE THIS SUITE GUARDS
-----------------------------
Phase A skeletonised `walkable AND interior_region`. Room interiors are
interior, so the graph wandered through offices, meeting rooms and
storage. The geometry was treating

    all interior free space == candidate corridor space

Every test below is about that not happening again, and about the fix
failing conservatively rather than guessing when the drawing does not
support a decision.

WHY THERE IS NO SEMANTIC POLYGON ANYWHERE IN HERE
--------------------------------------------------
The semantic contract carries no coordinates, deliberately, and that is
not being relaxed. Semantic evidence reaches the geometry only as ANCHOR
POINTS derived by matching an entity's name to a label actually printed
on the map. So the separation must work with no semantic input at all —
which is exactly the situation on a raster map with no readable text —
and merely improve when anchors exist.

Run with: pytest backend/tests/test_circulation_region.py -v
"""

import cv2
import numpy as np
import pytest

from services.building_region_service import classify_regions
from services.circulation_region_service import identify_circulation
from services.corridor_graph_service import extract_corridor_graph
from services.map_image_service import _build_navigation_line_mask
from services.strict_geometry_service import (
    _clear_line_on_mask,
    measure_wall_stroke_thickness,
)


WIDTH, HEIGHT = 1600, 1200
WALL = 8

# The corridor band in the standard fixture below.
CORRIDOR_TOP, CORRIDOR_BOTTOM = 520, 680


def _blank():
    return np.full((HEIGHT, WIDTH), 255, dtype=np.uint8)


def _plan_with_central_corridor(door=50):
    """
    A central east-west corridor with a rank of four-wall rooms above and
    another below, each opening onto the corridor through one door.
    """

    image = _blank()

    cv2.line(image, (200, 150), (1400, 150), 0, WALL)
    cv2.line(image, (200, 150), (200, 1000), 0, WALL)
    cv2.line(image, (1400, 150), (1400, 1000), 0, WALL)
    cv2.line(image, (200, 1000), (1400, 1000), 0, WALL)

    cv2.line(image, (200, CORRIDOR_TOP), (1400, CORRIDOR_TOP), 0, WALL)
    cv2.line(image, (200, CORRIDOR_BOTTOM), (1400, CORRIDOR_BOTTOM), 0, WALL)

    for x in range(500, 1400, 300):
        cv2.line(image, (x, 150), (x, CORRIDOR_TOP), 0, WALL)
        cv2.line(image, (x, CORRIDOR_BOTTOM), (x, 1000), 0, WALL)

    half = door // 2
    for x in range(350, 1400, 300):
        cv2.line(image, (x - half, CORRIDOR_TOP), (x + half, CORRIDOR_TOP), 255, WALL + 8)
        cv2.line(
            image, (x - half, CORRIDOR_BOTTOM), (x + half, CORRIDOR_BOTTOM), 255, WALL + 8
        )

    return image


def _analyse(image, *, room_anchors=(), circulation_anchors=()):
    mask = _build_navigation_line_mask(image)
    thickness = measure_wall_stroke_thickness(mask)
    region = classify_regions(mask, thickness, mask_scale=1.0)

    assert region.available, region.reason

    circulation = identify_circulation(
        mask,
        region.interior_mask,
        stroke_thickness_px=thickness,
        room_anchors=room_anchors,
        circulation_anchors=circulation_anchors,
        mask_scale=1.0,
    )
    return mask, thickness, region, circulation


def _graph_on(mask, thickness, circulation):
    return extract_corridor_graph(
        mask,
        circulation.circulation_mask,
        mask_scale=1.0,
        stroke_thickness_px=thickness,
        map_id="circulation_test",
        strict_mask=mask,
        strict_downscale=1.0,
    )


def _in_corridor_band(node):
    return CORRIDOR_TOP < node.y < CORRIDOR_BOTTOM


# ===========================================================
# 1. A central corridor surrounded by four-wall rooms
# ===========================================================

def test_a_central_corridor_is_separated_from_its_rooms():
    _mask, _thickness, _region, circulation = _analyse(_plan_with_central_corridor())

    assert circulation.available, circulation.reason

    # Eight rooms plus one corridor.
    assert len(circulation.cells) >= 9
    assert circulation.circulation_cell_count >= 1
    assert circulation.excluded_room_cell_count >= 8

    corridor_cells = [
        cell for cell in circulation.cells if cell.decision == "circulation"
    ]
    # The corridor is the cell that collects the doors of many rooms.
    assert max(cell.degree for cell in corridor_cells) >= 6

    for cell in circulation.cells:
        if cell.decision == "room":
            assert cell.degree <= 2


def test_the_graph_follows_the_corridor_and_leaves_the_rooms_alone():
    mask, thickness, _region, circulation = _analyse(_plan_with_central_corridor())
    graph = _graph_on(mask, thickness, circulation)

    assert graph.available, graph.reason
    assert graph.nodes

    for node in graph.nodes:
        assert _in_corridor_band(node), f"node escaped into a room: {node}"


# ===========================================================
# 2. Storage room beside a corridor
# ===========================================================

def test_the_graph_stays_out_of_a_storage_room():
    """
    The literal real-map failure: a large enclosed store beside the
    corridor, which the old pipeline skeletonised straight through.
    """

    image = _plan_with_central_corridor()

    # Widen one upper room into a big storage space by removing a divider.
    cv2.line(image, (800, 150), (800, CORRIDOR_TOP), 255, WALL + 6)

    mask, thickness, _region, circulation = _analyse(image)
    assert circulation.available, circulation.reason

    graph = _graph_on(mask, thickness, circulation)
    assert graph.available, graph.reason

    storage = (500, 160, 1100, CORRIDOR_TOP - 10)

    for node in graph.nodes:
        inside_storage = (
            storage[0] < node.x < storage[2] and storage[1] < node.y < storage[3]
        )
        assert not inside_storage, f"node inside the storage room: {node}"


# ===========================================================
# 3. Meeting room with a large open interior
# ===========================================================

def test_a_large_open_meeting_room_is_still_excluded():
    """
    Size is not corridor-ness. A meeting room that is wide, empty and has
    more than one door is still a destination, and the graph must stay
    out of it.
    """

    image = _plan_with_central_corridor()

    # Merge three upper rooms into one very large open meeting room by
    # removing the dividers between them. It is now bigger than the
    # corridor and has three doors onto it.
    for x in (800, 1100):
        cv2.line(image, (x, 150), (x, CORRIDOR_TOP), 255, WALL + 6)

    mask, thickness, _region, circulation = _analyse(image)
    assert circulation.available, circulation.reason

    graph = _graph_on(mask, thickness, circulation)
    assert graph.available, graph.reason

    # The merged room spans x 500..1400 above the corridor.
    for node in graph.nodes:
        inside_meeting_room = (
            510 < node.x < 1390 and 160 < node.y < CORRIDOR_TOP - 10
        )
        assert not inside_meeting_room, f"node inside the meeting room: {node}"

    # And it really is the biggest cell on the plan, so this is not
    # passing merely because the room was small.
    biggest = max(circulation.cells, key=lambda cell: cell.area)
    assert biggest.decision == "room" or biggest.degree >= 6


# ===========================================================
# 4. The doorway allowance
# ===========================================================

def test_a_room_can_still_be_reached_across_its_doorway():
    """
    Excluding room interiors must not make rooms unreachable. A point
    inside a room has to retain a clear line to the corridor graph
    through its own doorway.
    """

    mask, thickness, _region, circulation = _analyse(_plan_with_central_corridor())
    graph = _graph_on(mask, thickness, circulation)

    assert graph.available

    # A point inside the first upper room, just above its door at x=350.
    room_point = (350.0, 460.0)

    reachable = [
        node
        for node in graph.nodes
        if _clear_line_on_mask(
            mask, 1.0, room_point[0], room_point[1], node.x, node.y
        )
    ]

    assert reachable, "the room lost line of sight to the corridor graph"


def test_the_room_interior_itself_is_not_part_of_the_circulation_mask():
    _mask, _thickness, _region, circulation = _analyse(_plan_with_central_corridor())

    assert circulation.available

    # Deep inside an upper room.
    assert circulation.circulation_mask[300, 350] == 0
    # ...and in the corridor.
    assert circulation.circulation_mask[600, 800] == 1


# ===========================================================
# 5. Semantics are a prior, never an override
# ===========================================================

def test_a_semantic_room_anchor_excludes_a_cell_whatever_its_geometry():
    """Negative evidence wins: a cell holding an accepted room is a room."""

    image = _plan_with_central_corridor()
    _mask, _thickness, _region, plain = _analyse(image)

    assert plain.available
    corridor_cell = next(
        cell for cell in plain.cells if cell.decision == "circulation"
    )

    # Now claim an accepted ROOM sits in the middle of that corridor.
    corridor_centre = (
        float((corridor_cell.bbox[0] + corridor_cell.bbox[2]) / 2),
        float((corridor_cell.bbox[1] + corridor_cell.bbox[3]) / 2),
    )

    _m2, _t2, _r2, overridden = _analyse(image, room_anchors=[corridor_centre])

    marked = [
        cell for cell in overridden.cells if cell.reason == "semantic_room_anchor"
    ]
    assert marked, "the room anchor was ignored"
    for cell in marked:
        assert cell.decision == "room"


def test_semantic_circulation_guidance_cannot_open_a_wall():
    """
    THE SAFETY INVARIANT. Semantic evidence may steer which region is
    searched; it can never talk an edge through a wall, because the edge
    proof is a separate strict check against the unmodified wall mask.
    """

    image = _plan_with_central_corridor()
    # Seal the corridor solidly in the middle.
    cv2.line(image, (800, CORRIDOR_TOP), (800, CORRIDOR_BOTTOM), 0, 40)

    # Claim circulation on BOTH sides of the new wall.
    mask, thickness, _region, circulation = _analyse(
        image, circulation_anchors=[(400.0, 600.0), (1200.0, 600.0)]
    )

    if not circulation.available:
        assert circulation.reason
        return

    graph = _graph_on(mask, thickness, circulation)
    by_index = {node.index: node for node in graph.nodes}

    for edge in graph.edges:
        a = by_index[edge.from_index]
        b = by_index[edge.to_index]
        # Nothing may span the sealed section...
        assert not (min(a.x, b.x) < 800 < max(a.x, b.x))
        # ...and every surviving edge is still strictly proven.
        assert _clear_line_on_mask(mask, 1.0, a.x, a.y, b.x, b.y) is True


def test_circulation_anchors_are_optional():
    """
    The whole mechanism must work with no semantic input, because a
    raster map with no OCR supplies none.
    """

    _mask, _thickness, _region, circulation = _analyse(_plan_with_central_corridor())

    assert circulation.available
    assert circulation.circulation_cell_count >= 1
    for cell in circulation.cells:
        assert cell.circulation_anchor_count == 0
        assert cell.room_anchor_count == 0


# ===========================================================
# 6. Failing conservatively
# ===========================================================

def test_an_undivided_open_hall_refuses_rather_than_guessing():
    """
    One big open space has no rooms to distinguish from a corridor. The
    honest answer is a named refusal, not "all of it is corridor".
    """

    image = _blank()
    cv2.rectangle(image, (200, 200), (1400, 1000), 0, WALL)

    mask = _build_navigation_line_mask(image)
    thickness = measure_wall_stroke_thickness(mask)
    region = classify_regions(mask, thickness, mask_scale=1.0)

    circulation = identify_circulation(
        mask, region.interior_mask, stroke_thickness_px=thickness, mask_scale=1.0
    )

    assert circulation.available is False
    assert circulation.reason
    assert circulation.circulation_mask is None


def test_a_missing_interior_region_refuses():
    image = _plan_with_central_corridor()
    mask = _build_navigation_line_mask(image)
    thickness = measure_wall_stroke_thickness(mask)

    circulation = identify_circulation(
        mask,
        np.zeros((HEIGHT, WIDTH), dtype=np.uint8),
        stroke_thickness_px=thickness,
        mask_scale=1.0,
    )

    assert circulation.available is False
    assert circulation.reason


def test_every_cell_carries_a_machine_readable_reason():
    _mask, _thickness, _region, circulation = _analyse(_plan_with_central_corridor())

    assert circulation.available

    for cell in circulation.cells:
        assert cell.reason in {
            "door_degree",
            "semantic_circulation_anchor",
            "semantic_room_anchor",
            "not_circulation_by_door_degree",
        }, cell.reason

    diagnostics = circulation.diagnostics()
    for key in (
        "cell_count",
        "circulation_cell_count",
        "excluded_room_cell_count",
        "doorways_detected",
        "split_radius_px",
        "radii_tried",
        "cells",
    ):
        assert key in diagnostics


# ===========================================================
# 7. Vector PDF text survives a crop
# ===========================================================

def test_vector_pdf_text_survives_the_roi_coordinate_transform(tmp_path):
    """
    Cropping must not throw away selectable text and then require OCR to
    recover what was already there. With an ROI, the words come back in
    the CROPPED image's own coordinate system.
    """

    import fitz

    from services.map_image_service import PDF_RENDER_DPI
    from services.map_label_extraction_service import (
        POINTS_PER_INCH,
        extract_labels_from_pdf,
    )

    scale = PDF_RENDER_DPI / POINTS_PER_INCH

    document = fitz.open()
    page = document.new_page(width=400.0, height=300.0)
    page.insert_text((60.0, 80.0), "OFFICE 428", fontsize=11)     # upper left
    page.insert_text((300.0, 250.0), "STORAGE 9", fontsize=11)    # lower right
    pdf_path = tmp_path / "plan.pdf"
    document.save(str(pdf_path))
    document.close()

    # A crop covering the upper-left quadrant only, in rendered pixels.
    roi = (0.0, 0.0, 200.0 * scale, 150.0 * scale)
    crop_width = int(round(roi[2] - roi[0]))
    crop_height = int(round(roi[3] - roi[1]))

    result = extract_labels_from_pdf(
        pdf_path,
        source_width=crop_width,
        source_height=crop_height,
        roi=roi,
    )

    assert result.available, result.reason
    assert result.source == "vector_pdf"

    texts = {label.normalized for label in result.labels}
    assert any("428" in text for text in texts), texts
    # The label outside the crop must not appear.
    assert not any("STORAGE" in text for text in texts), texts

    # ...and the surviving label is positioned within the CROP, not the page.
    label = next(label for label in result.labels if "428" in label.normalized)
    assert 0 <= label.x0 < crop_width
    assert 0 <= label.y0 < crop_height
    assert label.x0 == pytest.approx(60.0 * scale, abs=3.0)


def test_a_crop_whose_recorded_size_disagrees_is_refused(tmp_path):
    import fitz

    from services.map_image_service import PDF_RENDER_DPI
    from services.map_label_extraction_service import (
        POINTS_PER_INCH,
        extract_labels_from_pdf,
    )

    scale = PDF_RENDER_DPI / POINTS_PER_INCH

    document = fitz.open()
    page = document.new_page(width=400.0, height=300.0)
    page.insert_text((60.0, 80.0), "OFFICE 428", fontsize=11)
    pdf_path = tmp_path / "plan.pdf"
    document.save(str(pdf_path))
    document.close()

    roi = (0.0, 0.0, 200.0 * scale, 150.0 * scale)

    result = extract_labels_from_pdf(
        pdf_path,
        source_width=int(round(roi[2])) + 250,   # wrong on purpose
        source_height=int(round(roi[3])),
        roi=roi,
    )

    assert result.available is False
    assert "does not match the crop region" in (result.reason or "")


# ===========================================================
# 8. Image-only input with no OCR reports the reason honestly
# ===========================================================

def test_a_raster_original_with_no_ocr_reports_why(tmp_path, monkeypatch):
    """
    The real cropped map is a JPEG, so there is no vector text at all.
    With no tesseract either, the pipeline must SAY so rather than behave
    as though the drawing had no writing on it.
    """

    import services.ocr_service as ocr
    from services.map_image_service import SOURCE_DIR, ensure_map_directories
    from services.map_label_extraction_service import extract_map_labels

    monkeypatch.setattr(ocr, "is_ocr_available", lambda: False)

    ensure_map_directories()
    map_id = "raster_only_no_ocr"
    source_path = SOURCE_DIR / f"{map_id}.png"
    cv2.imwrite(str(source_path), _plan_with_central_corridor())

    class RasterMap:
        id = map_id
        source_width = WIDTH
        source_height = HEIGHT
        analysis_source_type = "image"

    try:
        result = extract_map_labels(RasterMap())

        assert result.available is False
        assert result.source == "unavailable"
        assert result.labels == []
        assert "tesseract" in (result.reason or "").lower()
    finally:
        source_path.unlink(missing_ok=True)
