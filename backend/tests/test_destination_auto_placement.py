"""
Tests for the hybrid semantic+geometry placement preview:

  POST /api/maps/{map_id}/semantic-analysis/destinations/auto-place/preview

WHAT THESE TESTS ARE DEFENDING
------------------------------
The feature suggests a map position for an accepted semantic room by
matching the room's name to a label PRINTED on the drawing and then
checking a small, bounded set of positions near that label against the
existing wall mask and the existing line-of-sight check.

So the tests are weighted toward REFUSALS and toward the boundaries:

  * it must refuse with no wall mask, rather than trusting
    has_clear_line()'s fail-open True (test 4),
  * it must refuse an ambiguous name rather than pick one (test 6),
  * it must refuse when a wall stands between the room and every corridor
    point (test 8),
  * it must never search beyond the bounded nudge budget (test 10),
  * it must never write anything (test 1),
  * and the position it does suggest must go through the EXISTING apply
    endpoint, not a second write path (test 15).

Label extraction itself is covered by tests/test_map_label_extraction.py;
most tests here inject a known label set so the geometry assertions are
about geometry, not about OCR quality. Test 14 runs the whole thing on a
real generated PDF with no injection at all.

Run with: pytest backend/tests/test_destination_auto_placement.py -v
"""

import math

import cv2
import numpy as np
import pytest
from beanie import PydanticObjectId

from tests.test_api_integration import auth_headers, create_admin_and_get_token
from tests.test_semantic_destinations import _create_publication, _place

from models.map_model import Map
from models.room_model import Room
from models.route_edge_model import RouteEdge
from models.route_point_model import RoutePoint
from services import destination_auto_placement_service as auto_place
from services.graph_connection_service import _WALL_MASK_CACHE
from services.map_image_service import (
    ORIGINALS_DIR,
    PDF_RENDER_DPI,
    SOURCE_DIR,
    ensure_map_directories,
)
from services.map_label_extraction_service import (
    LabelExtractionResult,
    MapLabel,
)


AUTO_PLACE_URL = "/api/maps/{map_id}/semantic-analysis/destinations/auto-place/preview"
DEST_APPLY_URL = "/api/maps/{map_id}/semantic-analysis/destinations/apply"

IMAGE_WIDTH = 800
IMAGE_HEIGHT = 600


# ---------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------


def _create_map(client, token, title="Auto Place Test Map"):
    response = client.post(
        "/api/maps", json={"title": title, "floor": None}, headers=auth_headers(token)
    )
    assert response.status_code == 201, response.text
    return response.json()


def _create_point(client, token, map_id, name, x, y, point_type="hallway"):
    response = client.post(
        "/api/route-points",
        json={
            "map_id": map_id,
            "name": name,
            "x": x,
            "y": y,
            "floor": None,
            "point_type": point_type,
        },
        headers=auth_headers(token),
    )
    assert response.status_code == 201, response.text
    return response.json()


def _blank_plan():
    """A white page with a thick outer boundary — walls, no interior."""

    image = np.full((IMAGE_HEIGHT, IMAGE_WIDTH), 255, dtype=np.uint8)
    cv2.rectangle(image, (20, 20), (IMAGE_WIDTH - 20, IMAGE_HEIGHT - 20), 0, 8)
    return image


def _write_source_image(map_id, image):
    ensure_map_directories()
    path = SOURCE_DIR / f"{map_id}.png"
    cv2.imwrite(str(path), image)
    _WALL_MASK_CACHE.pop(map_id, None)
    return path


async def _record_image_size(map_id, width=IMAGE_WIDTH, height=IMAGE_HEIGHT):
    map_item = await Map.get(PydanticObjectId(map_id))
    map_item.source_width = width
    map_item.source_height = height
    await map_item.save()
    return map_item


def _label(text, center_x, center_y, width=90.0, height=20.0, source="vector_pdf"):
    from services.map_label_extraction_service import _build_label

    label = _build_label(
        text,
        center_x - width / 2.0,
        center_y - height / 2.0,
        center_x + width / 2.0,
        center_y + height / 2.0,
        source,
        1.0,
    )
    assert label is not None
    return label


def _inject_labels(monkeypatch, labels, source="vector_pdf"):
    """
    Replaces label EXTRACTION only — matching, wall checks, line-of-sight
    and every bound are the real implementations.
    """

    result = LabelExtractionResult(labels=list(labels), source=source, scale=1.0)
    monkeypatch.setattr(auto_place, "extract_map_labels", lambda _map_item: result)
    return result


def _no_labels(monkeypatch, reason="No selectable text."):
    monkeypatch.setattr(
        auto_place,
        "extract_map_labels",
        lambda _map_item: LabelExtractionResult(source="unavailable", reason=reason),
    )


def _auto_place(client, token, map_id, **kwargs):
    response = client.post(
        AUTO_PLACE_URL.format(map_id=map_id), json=kwargs, headers=auth_headers(token)
    )
    assert response.status_code == 200, response.text
    return response.json()


def _proposal(result, semantic_item_id):
    for proposal in result["proposals"]:
        if proposal["semantic_item_id"] == semantic_item_id:
            return proposal
    raise AssertionError(f"no proposal for {semantic_item_id}: {result['proposals']}")


async def _standard_scenario(client, token, label_center=(200, 300), corridor=(600, 300)):
    """One room label on open floor, one corridor point, walls only at the
    page boundary — the case that SHOULD place cleanly."""

    map_item = _create_map(client, token)
    map_id = map_item["id"]

    _write_source_image(map_id, _blank_plan())
    await _record_image_size(map_id)
    await _create_publication(map_id, places=[_place("p-428", "Office 428")])
    _create_point(client, token, map_id, "Corridor A", corridor[0], corridor[1])

    return map_id


# ===========================================================
# 1. Read-only
# ===========================================================

async def test_preview_writes_nothing(client, monkeypatch):
    token, _ = create_admin_and_get_token(
        client, role="global_manager", email="ap1@example.com"
    )
    map_id = await _standard_scenario(client, token)
    _inject_labels(monkeypatch, [_label("OFFICE 428", 200, 300)])

    before = (
        await Room.find_all().count(),
        await RoutePoint.find_all().count(),
        await RouteEdge.find_all().count(),
    )

    result = _auto_place(client, token, map_id)
    assert result["summary"]["auto_connectable"] == 1

    after = (
        await Room.find_all().count(),
        await RoutePoint.find_all().count(),
        await RouteEdge.find_all().count(),
    )
    assert before == after

    from models.location_code_model import LocationCode

    assert await LocationCode.find_all().count() == 0


# ===========================================================
# 2-3. The happy path and its evidence
# ===========================================================

async def test_room_on_open_floor_is_auto_connectable(client, monkeypatch):
    token, _ = create_admin_and_get_token(
        client, role="global_manager", email="ap2@example.com"
    )
    map_id = await _standard_scenario(client, token)
    _inject_labels(monkeypatch, [_label("OFFICE 428", 200, 300)])

    proposal = _proposal(_auto_place(client, token, map_id), "p-428")

    assert proposal["status"] == "auto_connectable"
    assert proposal["placement_source"] == "map_label"
    assert proposal["suggested_room_point"] == proposal["suggested_arrival_point"]
    assert proposal["semantic_match_confidence"] == 1.0
    assert proposal["geometry_confidence"] > 0
    assert proposal["matched_graph_element"]["point_type"] == "hallway"


async def test_every_placement_records_its_full_evidence(client, monkeypatch):
    token, _ = create_admin_and_get_token(
        client, role="global_manager", email="ap3@example.com"
    )
    map_id = await _standard_scenario(client, token)
    _inject_labels(monkeypatch, [_label("OFFICE 428", 200, 300)])

    proposal = _proposal(_auto_place(client, token, map_id), "p-428")
    diagnostics = proposal["diagnostics"]

    # Requirement: an admin must be able to see exactly why this position
    # was chosen, and reject it if the drawing says otherwise.
    assert diagnostics["matched_label"] == "OFFICE 428"
    assert diagnostics["label_bbox"] == [155.0, 290.0, 245.0, 310.0]
    assert diagnostics["label_center"] == [200.0, 300.0]
    assert diagnostics["anchor_x"] == 200.0
    assert diagnostics["anchor_y"] == 300.0
    assert diagnostics["matching_rule"] == "exact_normalized"
    assert diagnostics["nudge_distance_px"] is not None
    assert diagnostics["nudge_direction_deg"] is not None
    assert diagnostics["nudge_budget_px"] > 0
    assert diagnostics["nudge_rule"]
    assert diagnostics["wall_mask_available"] is True
    assert diagnostics["candidate_on_wall"] is False
    assert diagnostics["clear_line_passed"] is True
    assert diagnostics["candidates_considered"] == 1
    assert diagnostics["positions_probed"] >= 1


# ===========================================================
# 4. No wall mask -> refuse. has_clear_line() fails OPEN, so this is the
#    single most important refusal in the feature.
# ===========================================================

async def test_no_wall_mask_refuses_instead_of_trusting_fail_open(client, monkeypatch):
    token, _ = create_admin_and_get_token(
        client, role="global_manager", email="ap4@example.com"
    )
    map_item = _create_map(client, token)
    map_id = map_item["id"]

    # Deliberately no source image at all.
    (SOURCE_DIR / f"{map_id}.png").unlink(missing_ok=True)
    await _record_image_size(map_id)
    await _create_publication(map_id, places=[_place("p-428", "Office 428")])
    _create_point(client, token, map_id, "Corridor A", 600, 300)
    _inject_labels(monkeypatch, [_label("OFFICE 428", 200, 300)])

    result = _auto_place(client, token, map_id)
    proposal = _proposal(result, "p-428")

    assert result["wall_mask_available"] is False
    assert proposal["status"] == "needs_arrival_confirmation"
    assert proposal["suggested_room_point"] is None
    assert result["summary"]["auto_connectable"] == 0
    assert any("no processed source image" in w for w in result["warnings"])


# ===========================================================
# 5-7. Name matching refuses more readily than it accepts
# ===========================================================

async def test_no_matching_label_is_reported_not_guessed(client, monkeypatch):
    token, _ = create_admin_and_get_token(
        client, role="global_manager", email="ap5@example.com"
    )
    map_id = await _standard_scenario(client, token)
    _inject_labels(monkeypatch, [_label("CAFETERIA", 200, 300)])

    proposal = _proposal(_auto_place(client, token, map_id), "p-428")

    assert proposal["status"] == "no_label_match"
    assert proposal["suggested_room_point"] is None


async def test_two_equally_matching_labels_are_ambiguous(client, monkeypatch):
    token, _ = create_admin_and_get_token(
        client, role="global_manager", email="ap6@example.com"
    )
    map_id = await _standard_scenario(client, token)
    _inject_labels(
        monkeypatch,
        [_label("OFFICE 428", 200, 200), _label("OFFICE 428", 200, 400)],
    )

    proposal = _proposal(_auto_place(client, token, map_id), "p-428")

    assert proposal["status"] == "ambiguous_label"
    assert proposal["suggested_room_point"] is None
    assert len(proposal["diagnostics"]["tied_label_texts"]) == 2


async def test_a_room_number_alone_can_match_a_differently_worded_label(
    client, monkeypatch
):
    token, _ = create_admin_and_get_token(
        client, role="global_manager", email="ap7@example.com"
    )
    map_id = await _standard_scenario(client, token)
    _inject_labels(monkeypatch, [_label("RM 428", 200, 300)])

    proposal = _proposal(_auto_place(client, token, map_id), "p-428")

    assert proposal["status"] == "auto_connectable"
    assert proposal["diagnostics"]["matching_rule"] == "number_only"
    # A weaker rule must be reported as lower confidence, not laundered.
    assert proposal["semantic_match_confidence"] == 0.75


# ===========================================================
# 8-9. Walls
# ===========================================================

async def test_a_wall_between_room_and_corridor_blocks_placement(
    client, monkeypatch
):
    token, _ = create_admin_and_get_token(
        client, role="global_manager", email="ap8@example.com"
    )
    map_item = _create_map(client, token)
    map_id = map_item["id"]

    image = _blank_plan()
    cv2.line(image, (400, 20), (400, IMAGE_HEIGHT - 20), 0, 60)  # solid wall
    _write_source_image(map_id, image)
    await _record_image_size(map_id)
    await _create_publication(map_id, places=[_place("p-428", "Office 428")])
    _create_point(client, token, map_id, "Corridor A", 600, 300)
    _inject_labels(monkeypatch, [_label("OFFICE 428", 200, 300)])

    proposal = _proposal(_auto_place(client, token, map_id), "p-428")

    assert proposal["status"] == "no_safe_graph_connection"
    assert proposal["suggested_room_point"] is None
    assert any(
        "blocked_by_wall" in rejection
        for rejection in proposal["diagnostics"]["rejections"]
    )


async def test_a_label_centre_on_a_wall_is_nudged_off_it(client, monkeypatch):
    token, _ = create_admin_and_get_token(
        client, role="global_manager", email="ap9@example.com"
    )
    map_item = _create_map(client, token)
    map_id = map_item["id"]

    # A thick wall running THROUGH where the label is printed, with the
    # corridor point below it in open floor.
    image = _blank_plan()
    cv2.line(image, (100, 300), (300, 300), 0, 60)
    _write_source_image(map_id, image)
    await _record_image_size(map_id)
    await _create_publication(map_id, places=[_place("p-428", "Office 428")])
    _create_point(client, token, map_id, "Corridor A", 200, 450)
    _inject_labels(monkeypatch, [_label("OFFICE 428", 200, 300)])

    proposal = _proposal(_auto_place(client, token, map_id), "p-428")

    assert proposal["status"] == "auto_connectable"

    diagnostics = proposal["diagnostics"]
    assert diagnostics["nudge_distance_px"] > 0
    assert any("on_wall" in r for r in diagnostics["rejections"])

    # It moved DOWN, toward the corridor — 180 degrees in image space.
    assert diagnostics["nudge_direction_deg"] == pytest.approx(180.0, abs=1.0)
    assert proposal["suggested_room_point"][1] > 300


# ===========================================================
# 10. The nudge is bounded by construction
# ===========================================================

async def test_the_nudge_never_exceeds_its_budget(client, monkeypatch):
    token, _ = create_admin_and_get_token(
        client, role="global_manager", email="ap10@example.com"
    )
    map_item = _create_map(client, token)
    map_id = map_item["id"]

    # A wall far too thick to step over inside the budget. The search must
    # give up, NOT keep walking toward the corridor.
    image = _blank_plan()
    cv2.rectangle(image, (140, 240), (560, 360), 0, -1)
    _write_source_image(map_id, image)
    await _record_image_size(map_id)
    await _create_publication(map_id, places=[_place("p-428", "Office 428")])
    _create_point(client, token, map_id, "Corridor A", 700, 300)
    _inject_labels(monkeypatch, [_label("OFFICE 428", 200, 300)])

    proposal = _proposal(_auto_place(client, token, map_id), "p-428")

    assert proposal["status"] == "no_safe_graph_connection"

    budget = proposal["diagnostics"]["nudge_budget_px"]
    assert budget <= auto_place.NUDGE_ABSOLUTE_MAX_PX
    # A 20px-high label buys a 60px reach, and nothing else.
    assert budget == pytest.approx(60.0)


def test_probe_positions_all_lie_within_the_budget_of_the_label_box():
    """Unit-level proof of the bound itself, independent of any map."""

    label = _label("OFFICE 428", 200, 300)
    budget = auto_place._nudge_budget_px(label)

    class _FarCandidate:
        x, y = 5000.0, 5000.0

    for _rule, px, py in auto_place._probe_sequence(label, _FarCandidate(), budget):
        assert auto_place._distance_to_box(px, py, label) <= budget + 1e-9


# ===========================================================
# 11-13. Candidate selection rules the feature must not relax
# ===========================================================

async def test_room_and_store_points_are_never_used_as_corridor_targets(
    client, monkeypatch
):
    token, _ = create_admin_and_get_token(
        client, role="global_manager", email="ap11@example.com"
    )
    map_item = _create_map(client, token)
    map_id = map_item["id"]

    _write_source_image(map_id, _blank_plan())
    await _record_image_size(map_id)
    await _create_publication(map_id, places=[_place("p-428", "Office 428")])
    # Only destination-capable points exist — nothing to connect TO.
    _create_point(client, token, map_id, "Shop", 600, 300, point_type="store")
    _create_point(client, token, map_id, "Other Room", 300, 300, point_type="room")
    _inject_labels(monkeypatch, [_label("OFFICE 428", 200, 300)])

    result = _auto_place(client, token, map_id)
    proposal = _proposal(result, "p-428")

    assert proposal["status"] == "no_safe_graph_connection"
    assert proposal["diagnostics"]["candidates_considered"] == 0
    assert any("no hallway or junction" in w for w in result["warnings"])


async def test_a_corridor_point_beyond_the_hard_safety_distance_is_not_used(
    client, monkeypatch
):
    token, _ = create_admin_and_get_token(
        client, role="global_manager", email="ap12@example.com"
    )
    map_id = await _standard_scenario(client, token)

    # 800x600 -> diagonal 1000 -> hard safety ceiling 600px. Put the label
    # more than that from the only corridor point.
    _inject_labels(monkeypatch, [_label("OFFICE 428", 60, 60)])
    await RoutePoint.find({"map_id": map_id}).update(
        {"$set": {"x": 780.0, "y": 560.0}}
    )

    proposal = _proposal(_auto_place(client, token, map_id), "p-428")

    assert math.hypot(780 - 60, 560 - 60) > 600
    assert proposal["status"] == "no_safe_graph_connection"
    assert proposal["diagnostics"]["candidates_considered"] == 0


async def test_an_item_that_already_has_a_location_is_left_alone(
    client, monkeypatch
):
    token, _ = create_admin_and_get_token(
        client, role="global_manager", email="ap13@example.com"
    )
    map_id = await _standard_scenario(client, token)
    _inject_labels(monkeypatch, [_label("OFFICE 428", 200, 300)])

    # Place it first, through the normal apply path.
    apply_response = client.post(
        DEST_APPLY_URL.format(map_id=map_id),
        json={
            "accepted": [
                {"semantic_item_id": "p-428", "entity_kind": "place", "x": 250, "y": 250}
            ]
        },
        headers=auth_headers(token),
    )
    assert apply_response.status_code == 200, apply_response.text
    assert apply_response.json()["rooms_created"] == 1

    result = _auto_place(client, token, map_id)
    proposal = _proposal(result, "p-428")

    assert result["summary"]["already_placed"] == 1
    assert result["summary"]["auto_connectable"] == 0
    assert proposal["suggested_room_point"] is None
    assert "already has a map location" in proposal["message"]


# ===========================================================
# 14. End to end on a real PDF, with nothing injected
# ===========================================================

async def test_a_real_pdf_map_places_its_room_end_to_end(client):
    token, _ = create_admin_and_get_token(
        client, role="global_manager", email="ap14@example.com"
    )
    map_item = _create_map(client, token)
    map_id = map_item["id"]

    import fitz

    ensure_map_directories()

    width_pt, height_pt = 400.0, 300.0
    document = fitz.open()
    page = document.new_page(width=width_pt, height=height_pt)
    page.draw_rect(fitz.Rect(10, 10, width_pt - 10, height_pt - 10), width=3)
    page.insert_text((60.0, 120.0), "OFFICE 428", fontsize=11)
    pdf_path = ORIGINALS_DIR / f"{map_id}.pdf"
    document.save(str(pdf_path))

    # Render page 0 exactly the way the upload pipeline does, so the PNG
    # the wall mask reads and the PDF the labels come from are the same
    # page — which is precisely what the transform check verifies.
    pixmap = page.get_pixmap(dpi=PDF_RENDER_DPI)
    pixmap.save(str(SOURCE_DIR / f"{map_id}.png"))
    document.close()
    _WALL_MASK_CACHE.pop(map_id, None)

    await _record_image_size(map_id, pixmap.width, pixmap.height)
    await _create_publication(map_id, places=[_place("p-428", "Office 428")])

    # A corridor point in open floor, to the right of the label.
    _create_point(client, token, map_id, "Corridor A", 700, 350)

    result = _auto_place(client, token, map_id)
    proposal = _proposal(result, "p-428")

    assert result["label_source"] == "vector_pdf"
    assert result["label_count"] >= 1
    assert result["wall_mask_available"] is True
    assert proposal["status"] == "auto_connectable", proposal["diagnostics"]

    x, y = proposal["suggested_room_point"]
    assert 0 < x < pixmap.width
    assert 0 < y < pixmap.height

    pdf_path.unlink(missing_ok=True)
    (SOURCE_DIR / f"{map_id}.png").unlink(missing_ok=True)


# ===========================================================
# 15. The suggestion is applied through the EXISTING write path
# ===========================================================

async def test_a_suggested_position_is_applied_through_the_existing_endpoint(
    client, monkeypatch
):
    token, _ = create_admin_and_get_token(
        client, role="global_manager", email="ap15@example.com"
    )
    map_id = await _standard_scenario(client, token)
    _inject_labels(monkeypatch, [_label("OFFICE 428", 200, 300)])

    proposal = _proposal(_auto_place(client, token, map_id), "p-428")
    x, y = proposal["suggested_room_point"]

    # Exactly the request the admin's own click would have produced —
    # there is no second apply endpoint for auto-placed rooms.
    apply_response = client.post(
        DEST_APPLY_URL.format(map_id=map_id),
        json={
            "accepted": [
                {"semantic_item_id": "p-428", "entity_kind": "place", "x": x, "y": y}
            ]
        },
        headers=auth_headers(token),
    )
    assert apply_response.status_code == 200, apply_response.text

    body = apply_response.json()
    assert body["rooms_created"] == 1
    assert body["route_points_created"] == 1

    point = await RoutePoint.get(PydanticObjectId(body["created_route_point_ids"][0]))
    assert point.x == pytest.approx(x)
    assert point.y == pytest.approx(y)

    # No RouteEdge was invented along the way: connecting the point to the
    # graph stays the auto-connect feature's job, on its own review step.
    assert await RouteEdge.find({"map_id": map_id}).count() == 0


# ===========================================================
# 16. The semantic contract is untouched
# ===========================================================

def test_the_ai_is_still_forbidden_from_returning_coordinates():
    """
    This feature exists precisely so the LLM never has to be asked for
    geometry. If that separation is ever relaxed, this test fails.
    """

    from schemas.semantic_analysis_schema import FORBIDDEN_ROUTING_FIELD_NAMES

    for field in ("x", "y", "coordinates", "polygon", "bounding_box"):
        assert field in FORBIDDEN_ROUTING_FIELD_NAMES
