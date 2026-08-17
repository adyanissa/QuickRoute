"""
Tests for services/building_region_service and
services/page_furniture_service — deciding which free space on a drawing
sheet is actually inside the building.

Two tests here are acceptance criteria for explicit design constraints and
should be read before the rest:

  test_a_building_with_an_entrance_is_still_interior
      A real building has entrance openings, so its interior free space is
      routinely CONNECTED to the page exterior through the doorway. Any
      design that treats border-connectivity as decisive classifies the
      whole corridor network as outside and silently discards the floor.
      This test fails on such a design.

  test_label_boxes_alone_cannot_promote_a_component
      A room label's bounding box sits inside the room it names, which
      says nothing about whether the surrounding free space is the
      building's circulation network — and a dense cluster of labels is at
      least as likely to be a legend. Labels may support a score; they may
      never carry it.

Run with: pytest backend/tests/test_building_region.py -v
"""

import cv2
import numpy as np
import pytest

from services.building_region_service import (
    ENCLOSURE_MIN_SCORE,
    build_topology_mask,
    classify_regions,
    compute_enclosure_field,
    region_contours,
)
from services.map_image_service import _build_navigation_line_mask
from services.page_furniture_service import detect_page_furniture
from services.strict_geometry_service import measure_wall_stroke_thickness


WIDTH, HEIGHT = 1600, 1200
WALL = 8


def _blank():
    return np.full((HEIGHT, WIDTH), 255, dtype=np.uint8)


def _building(image, entrance_gap=True):
    """A rectangular building with a corridor spine and rooms either side."""

    cv2.line(image, (200, 150), (1400, 150), 0, WALL)
    cv2.line(image, (200, 150), (200, 1000), 0, WALL)
    cv2.line(image, (1400, 150), (1400, 1000), 0, WALL)

    if entrance_gap:
        # A 120 px doorway in the south wall — the interior leaks to the
        # page exterior through it, exactly as a real entrance does.
        cv2.line(image, (200, 1000), (700, 1000), 0, WALL)
        cv2.line(image, (820, 1000), (1400, 1000), 0, WALL)
    else:
        cv2.line(image, (200, 1000), (1400, 1000), 0, WALL)

    # Corridor spine between two ranks of rooms.
    cv2.line(image, (200, 520), (1400, 520), 0, WALL)
    cv2.line(image, (200, 680), (1400, 680), 0, WALL)

    for x in range(500, 1400, 300):
        cv2.line(image, (x, 150), (x, 520), 0, WALL)
        cv2.line(image, (x, 680), (x, 1000), 0, WALL)

    # Room doors onto the corridor.
    for x in range(350, 1400, 300):
        cv2.line(image, (x - 45, 520), (x + 45, 520), 255, WALL + 8)
        cv2.line(image, (x - 45, 680), (x + 45, 680), 255, WALL + 8)

    return image


def _title_block(image, labels_out=None):
    cv2.rectangle(image, (1430, 900), (1585, 1185), 0, 3)
    boxes = []
    for i in range(9):
        y = 930 + i * 28
        cv2.putText(image, "TEXT %d" % i, (1440, y), cv2.FONT_HERSHEY_SIMPLEX, 0.4, 0, 1)
        boxes.append((1440.0, float(y - 14), 1530.0, float(y + 6)))
    if labels_out is not None:
        labels_out.extend(boxes)
    return image


def _analyse(image, **kwargs):
    mask = _build_navigation_line_mask(image)
    thickness = measure_wall_stroke_thickness(mask)
    return mask, thickness, classify_regions(mask, thickness, **kwargs)


# ===========================================================
# THE ENTRANCE ACCEPTANCE CRITERION
# ===========================================================

# 1.
def test_a_building_with_an_entrance_is_still_interior():
    image = _building(_blank(), entrance_gap=True)
    _mask, _thickness, result = _analyse(image)

    assert result.available, result.reason

    interior = result.interior_components
    assert interior, "the floor was discarded because of its entrance"

    biggest = max(interior, key=lambda component: component.area)
    # The building occupies roughly half this sheet.
    assert biggest.area_fraction > 0.25

    # And the interior mask really covers the corridor, not just a room.
    assert result.interior_mask[600, 800] > 0


# 2. The same building with no entrance must behave the same way, so the
#    result is not accidentally depending on the opening.
def test_a_sealed_building_is_also_interior():
    image = _building(_blank(), entrance_gap=False)
    _mask, _thickness, result = _analyse(image)

    assert result.available
    assert result.interior_mask[600, 800] > 0


# 3. The page margin outside the building is never interior.
def test_the_page_margin_is_rejected():
    image = _building(_blank(), entrance_gap=True)
    _mask, _thickness, result = _analyse(image)

    assert result.available
    # A point out in the sheet margin, well clear of the building.
    assert result.interior_mask[60, 60] == 0


# ===========================================================
# THE LABEL ACCEPTANCE CRITERION
# ===========================================================

# 4.
def test_label_boxes_alone_cannot_promote_a_component():
    """
    Put labels out in the page margin. The margin is open in most
    directions, so it must stay rejected no matter how much label support
    it has.
    """

    image = _building(_blank(), entrance_gap=True)

    margin_labels = [(40.0, 40.0 + i * 30, 160.0, 60.0 + i * 30) for i in range(12)]

    _mask, _thickness, result = _analyse(image, label_boxes=margin_labels)

    assert result.available
    assert result.interior_mask[60, 60] == 0

    for component in result.components:
        if component.label_box_count > 0 and component.decision == "interior":
            # Any component labels helped promote must have cleared the
            # enclosure floor on its own merits too.
            assert component.enclosure >= 0.70


# 5. A validated arrival point IS strong enough on its own.
def test_a_validated_arrival_point_promotes_a_component():
    image = _blank()
    # A small enclosed side pocket that the size rule would otherwise drop.
    cv2.rectangle(image, (200, 200), (1400, 900), 0, WALL)
    cv2.rectangle(image, (100, 1000), (330, 1150), 0, WALL)

    _m, _t, without = _analyse(image)
    _m2, _t2, with_arrival = _analyse(image, arrival_points=[(215.0, 1075.0)])

    pocket_without = [
        c for c in without.components if c.bbox[0] < 200 and c.bbox[1] > 950
    ]
    pocket_with = [
        c for c in with_arrival.components if c.bbox[0] < 200 and c.bbox[1] > 950
    ]

    assert pocket_with, "the pocket component was not found at all"
    assert pocket_with[0].decision == "interior"
    assert pocket_with[0].promoted_by == "arrival_points"

    if pocket_without:
        assert pocket_without[0].promoted_by != "arrival_points"


# ===========================================================
# Page furniture
# ===========================================================

# 6.
def test_a_corner_title_block_is_detected():
    labels = []
    image = _title_block(_building(_blank()), labels)
    mask = _build_navigation_line_mask(image)

    furniture = detect_page_furniture(mask, labels, mask_scale=1.0)
    kinds = {item.kind for item in furniture}

    assert "title_block" in kinds or "legend" in kinds


# 7. Geometry alone is not enough — a big plain room against the sheet
#    edge must not be mistaken for a title block.
def test_a_plain_rectangle_with_no_text_is_not_furniture():
    image = _blank()
    cv2.rectangle(image, (20, 700), (400, 1150), 0, 4)

    mask = _build_navigation_line_mask(image)
    furniture = detect_page_furniture(mask, [], mask_scale=1.0)

    assert not [item for item in furniture if item.excludes_interior]


# 8. Text alone is not enough either.
def test_dense_text_without_a_rectangle_is_not_furniture():
    image = _blank()
    labels = []
    for i in range(12):
        y = 200 + i * 30
        cv2.putText(image, "ROOM %d" % i, (300, y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, 0, 1)
        labels.append((300.0, float(y - 16), 420.0, float(y + 6)))

    mask = _build_navigation_line_mask(image)
    furniture = detect_page_furniture(mask, labels, mask_scale=1.0)

    assert not [item for item in furniture if item.excludes_interior]


# 9. A title block's interior must not become part of the building.
def test_the_inside_of_a_title_block_is_not_interior():
    labels = []
    image = _title_block(_building(_blank()), labels)
    mask = _build_navigation_line_mask(image)
    thickness = measure_wall_stroke_thickness(mask)
    furniture = detect_page_furniture(mask, labels, mask_scale=1.0)

    result = classify_regions(
        mask, thickness, label_boxes=labels, furniture=furniture, mask_scale=1.0
    )

    assert result.available
    assert result.interior_mask[1050, 1500] == 0


# ===========================================================
# Signals and refusals
# ===========================================================

# 10.
def test_enclosure_is_high_inside_and_low_outside():
    image = _building(_blank(), entrance_gap=True)
    mask = _build_navigation_line_mask(image)

    field, scale = compute_enclosure_field(mask)

    def at(x, y):
        return float(field[int(round(y * scale)), int(round(x * scale))])

    assert at(800, 600) >= ENCLOSURE_MIN_SCORE     # corridor
    assert at(60, 60) < ENCLOSURE_MIN_SCORE        # sheet corner


# 11. Gap sealing must not bridge a corridor shut.
def test_gap_sealing_backs_off_rather_than_closing_a_corridor():
    image = _building(_blank(), entrance_gap=True)
    mask = _build_navigation_line_mask(image)
    thickness = measure_wall_stroke_thickness(mask)

    closed, kernel, _backoffs = build_topology_mask(mask, thickness)

    free_before = int(np.count_nonzero(mask == 0))
    free_after = int(np.count_nonzero(closed == 0))

    assert kernel >= 3
    assert free_after > free_before * 0.5
    # The corridor centre is still open space after sealing.
    assert closed[600, 800] == 0


# 12. A drawing with nothing enclosed refuses rather than inventing a floor.
def test_a_blank_sheet_is_refused():
    _mask, _thickness, result = _analyse(_blank())

    assert result.available is False
    assert result.reason


# 13. A sheet containing only a title block refuses.
def test_a_sheet_with_only_a_title_block_is_refused():
    labels = []
    image = _title_block(_blank(), labels)
    mask = _build_navigation_line_mask(image)
    thickness = measure_wall_stroke_thickness(mask)
    furniture = detect_page_furniture(mask, labels, mask_scale=1.0)

    result = classify_regions(
        mask, thickness, label_boxes=labels, furniture=furniture, mask_scale=1.0
    )

    assert result.available is False


# 14. Every rejection carries a machine-readable reason.
def test_rejections_are_always_named():
    labels = []
    image = _title_block(_building(_blank()), labels)
    mask = _build_navigation_line_mask(image)
    thickness = measure_wall_stroke_thickness(mask)
    furniture = detect_page_furniture(mask, labels, mask_scale=1.0)

    result = classify_regions(
        mask, thickness, label_boxes=labels, furniture=furniture, mask_scale=1.0
    )

    for component in result.rejected_components:
        assert component.reason
        assert component.reason in {
            "page_furniture",
            "not_enclosed",
            "page_margin",
            "ring_shaped",
            "too_small_relative_to_main_floor",
        }


# 15. Contours come back in full-resolution source pixels, ready to draw.
def test_region_contours_are_in_source_pixels():
    image = _building(_blank(), entrance_gap=True)
    _mask, _thickness, result = _analyse(image)

    polygons = region_contours(result.interior_mask, 1.0)

    assert polygons
    for polygon in polygons:
        for x, y in polygon:
            assert 0 <= x <= WIDTH
            assert 0 <= y <= HEIGHT
