"""
Tests for the automatic navigation build preview (Phase A):

  POST /api/maps/{map_id}/navigation-build/preview

The three that matter most:

  test_preview_writes_nothing
      Phase A is read-only, completely. Room, RoutePoint, RouteEdge AND
      LocationCode counts must be identical across a successful run.

  test_rooms_are_positioned_with_no_pre_existing_corridor_points
      THE CHICKEN-AND-EGG. destination_auto_placement_service can only
      validate an arrival point against corridor RoutePoints that already
      exist, and a freshly uploaded map has none — so without the
      provisional-graph pass the zero-touch flow cannot start at all. This
      test proves it starts.

  test_no_provisional_identifier_survives_into_the_response
      PROVISIONAL EVIDENCE MUST NEVER BECOME FINAL EVIDENCE. The
      provisional graph exists only to obtain arrival points for the
      region decision; the final graph is rebuilt from the refined region
      and every attachment is recomputed against it. No provisional node
      id, edge or attachment may appear in the output.

Run with: pytest backend/tests/test_navigation_build_preview.py -v
"""

import cv2
import numpy as np
import pytest
from beanie import PydanticObjectId

from tests.test_api_integration import auth_headers, create_admin_and_get_token
from tests.test_semantic_destinations import _create_publication, _place

from models.location_code_model import LocationCode
from models.map_model import Map
from models.room_model import Room
from models.route_edge_model import RouteEdge
from models.route_point_model import RoutePoint
from services import navigation_build_preview_service as build_service
from services.graph_connection_service import _WALL_MASK_CACHE
from services.map_image_service import SOURCE_DIR, ensure_map_directories
from services.map_label_extraction_service import (
    LabelExtractionResult,
    _build_label,
)
from services.strict_geometry_service import clear_strict_mask_cache


PREVIEW_URL = "/api/maps/{map_id}/navigation-build/preview"

WIDTH, HEIGHT = 1600, 1200
WALL = 8

# Room label positions, matched to the semantic items created below. Each
# sits INSIDE its room, which is exactly why a label centre is not itself
# a usable arrival point.
ROOM_LABELS = [
    ("OFFICE 101", 350, 340),
    ("OFFICE 102", 650, 340),
    ("OFFICE 103", 950, 340),
    ("OFFICE 201", 350, 860),
    ("OFFICE 202", 650, 860),
]


def _floor_plan():
    """A building with a central corridor, rooms either side, and a real
    entrance opening in the south wall."""

    image = np.full((HEIGHT, WIDTH), 255, dtype=np.uint8)

    cv2.line(image, (200, 150), (1400, 150), 0, WALL)
    cv2.line(image, (200, 150), (200, 1000), 0, WALL)
    cv2.line(image, (1400, 150), (1400, 1000), 0, WALL)
    cv2.line(image, (200, 1000), (700, 1000), 0, WALL)
    cv2.line(image, (820, 1000), (1400, 1000), 0, WALL)   # 120 px entrance

    cv2.line(image, (200, 520), (1400, 520), 0, WALL)
    cv2.line(image, (200, 680), (1400, 680), 0, WALL)

    for x in range(500, 1400, 300):
        cv2.line(image, (x, 150), (x, 520), 0, WALL)
        cv2.line(image, (x, 680), (x, 1000), 0, WALL)

    for x in range(350, 1400, 300):
        cv2.line(image, (x - 45, 520), (x + 45, 520), 255, WALL + 8)
        cv2.line(image, (x - 45, 680), (x + 45, 680), 255, WALL + 8)

    return image


def _write_source(map_id):
    ensure_map_directories()
    path = SOURCE_DIR / f"{map_id}.png"
    cv2.imwrite(str(path), _floor_plan())
    _WALL_MASK_CACHE.pop(map_id, None)
    clear_strict_mask_cache()
    return path


def _synthetic_labels():
    """
    Injected in place of real extraction so these tests exercise the
    BUILD pipeline rather than OCR quality. Label extraction has its own
    suite in tests/test_map_label_extraction.py.
    """

    labels = []
    for text, cx, cy in ROOM_LABELS:
        labels.append(
            _build_label(text, cx - 70, cy - 12, cx + 70, cy + 12, "vector_pdf", 1.0)
        )
    return LabelExtractionResult(labels=labels, source="vector_pdf", scale=1.0)


def _create_map(client, token, title="Navigation Build Test Map"):
    response = client.post(
        "/api/maps", json={"title": title, "floor": None}, headers=auth_headers(token)
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _scenario(client, token, monkeypatch, *, with_labels=True):
    map_item = _create_map(client, token)
    map_id = map_item["id"]

    path = _write_source(map_id)

    document = await Map.get(PydanticObjectId(map_id))
    document.source_width = WIDTH
    document.source_height = HEIGHT
    await document.save()

    await _create_publication(
        map_id,
        places=[
            _place(f"p-{index}", text.title())
            for index, (text, _cx, _cy) in enumerate(ROOM_LABELS)
        ],
    )

    if with_labels:
        labels = _synthetic_labels()
        monkeypatch.setattr(
            build_service, "extract_map_labels", lambda _map_item: labels
        )
        import services.destination_auto_placement_service as placement

        monkeypatch.setattr(
            placement, "extract_map_labels", lambda _map_item: labels
        )

    return map_id, path


def _preview(client, token, map_id, **kwargs):
    response = client.post(
        PREVIEW_URL.format(map_id=map_id), json=kwargs, headers=auth_headers(token)
    )
    assert response.status_code == 200, response.text
    return response.json()


# ===========================================================
# 1. READ-ONLY
# ===========================================================

async def test_preview_writes_nothing(client, monkeypatch):
    token, _ = create_admin_and_get_token(
        client, role="global_manager", email="nb1@example.com"
    )
    map_id, path = await _scenario(client, token, monkeypatch)

    try:
        before = (
            await Room.find_all().count(),
            await RoutePoint.find_all().count(),
            await RouteEdge.find_all().count(),
            await LocationCode.find_all().count(),
        )

        result = _preview(client, token, map_id)
        assert result["available"] is True, result.get("reason")

        after = (
            await Room.find_all().count(),
            await RoutePoint.find_all().count(),
            await RouteEdge.find_all().count(),
            await LocationCode.find_all().count(),
        )

        assert before == after
    finally:
        path.unlink(missing_ok=True)


# ===========================================================
# 2. THE CHICKEN-AND-EGG
# ===========================================================

async def test_rooms_are_positioned_with_no_pre_existing_corridor_points(
    client, monkeypatch
):
    token, _ = create_admin_and_get_token(
        client, role="global_manager", email="nb2@example.com"
    )
    map_id, path = await _scenario(client, token, monkeypatch)

    try:
        # The premise: this map has NO corridor route points at all.
        assert await RoutePoint.find({"map_id": map_id}).count() == 0

        result = _preview(client, token, map_id)

        assert result["available"] is True, result.get("reason")
        assert result["graph_nodes"], "no transit graph was proposed"
        assert result["graph_edges"]

        positioned = [room for room in result["rooms"] if room["arrival_point"]]
        assert positioned, "no room was positioned without pre-existing corridors"

        diagnostics = result["diagnostics"]
        assert diagnostics["provisional_node_count"] > 0
        assert diagnostics["final_auto_positioned_room_count"] > 0
    finally:
        path.unlink(missing_ok=True)


# ===========================================================
# 3. PROVISIONAL EVIDENCE NEVER BECOMES FINAL EVIDENCE
# ===========================================================

async def test_no_provisional_identifier_survives_into_the_response(
    client, monkeypatch
):
    token, _ = create_admin_and_get_token(
        client, role="global_manager", email="nb3@example.com"
    )
    map_id, path = await _scenario(client, token, monkeypatch)

    try:
        result = _preview(client, token, map_id)
        assert result["available"] is True

        payload = repr(result)
        assert "provisional-" not in payload, (
            "a provisional node id leaked into the preview output"
        )

        assert result["diagnostics"]["provisional_graph_discarded"] is True

        # Every attachment points at a node index that exists in the FINAL
        # node list — never at something inherited from the earlier pass.
        final_indices = {node["index"] for node in result["graph_nodes"]}

        for room in result["rooms"]:
            attachment = room.get("attachment")
            if attachment and attachment.get("node_index") is not None:
                assert attachment["node_index"] in final_indices
    finally:
        path.unlink(missing_ok=True)


async def test_the_final_graph_is_rebuilt_not_inherited(client, monkeypatch):
    """
    The final graph must come from a second, independent extraction against
    the refined region — not from filtering the provisional one.
    """

    token, _ = create_admin_and_get_token(
        client, role="global_manager", email="nb4@example.com"
    )
    map_id, path = await _scenario(client, token, monkeypatch)

    calls = {"count": 0}
    original = build_service.extract_corridor_graph

    def counting(*args, **kwargs):
        calls["count"] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(build_service, "extract_corridor_graph", counting)

    try:
        result = _preview(client, token, map_id)
        assert result["available"] is True
        assert calls["count"] == 2, (
            "expected a provisional extraction and an independent final one"
        )
    finally:
        path.unlink(missing_ok=True)


async def test_region_is_classified_twice_with_and_without_arrival_evidence(
    client, monkeypatch
):
    token, _ = create_admin_and_get_token(
        client, role="global_manager", email="nb5@example.com"
    )
    map_id, path = await _scenario(client, token, monkeypatch)

    seen = []
    original = build_service.classify_regions

    def recording(*args, **kwargs):
        seen.append(len(kwargs.get("arrival_points") or ()))
        return original(*args, **kwargs)

    monkeypatch.setattr(build_service, "classify_regions", recording)

    try:
        result = _preview(client, token, map_id)
        assert result["available"] is True

        assert len(seen) == 2
        # Pass 1 sees no arrival evidence at all; pass 4 is the refinement.
        assert seen[0] == 0
    finally:
        path.unlink(missing_ok=True)


# ===========================================================
# 4. Strict geometry is what proves the output
# ===========================================================

async def test_the_strict_validator_is_used_not_the_legacy_one(
    client, monkeypatch
):
    token, _ = create_admin_and_get_token(
        client, role="global_manager", email="nb6@example.com"
    )
    map_id, path = await _scenario(client, token, monkeypatch)

    strict_calls = {"count": 0}
    import services.strict_geometry_service as strict

    original = strict.strict_has_clear_line

    def counting(*args, **kwargs):
        strict_calls["count"] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(strict, "strict_has_clear_line", counting)
    monkeypatch.setattr(build_service, "strict_has_clear_line", counting)

    try:
        result = _preview(client, token, map_id)
        assert result["available"] is True
        assert strict_calls["count"] > 0, "room attachment did not use strict geometry"
    finally:
        path.unlink(missing_ok=True)


async def test_no_source_image_refuses_at_the_geometry_stage(client, monkeypatch):
    token, _ = create_admin_and_get_token(
        client, role="global_manager", email="nb7@example.com"
    )
    map_item = _create_map(client, token)
    map_id = map_item["id"]

    (SOURCE_DIR / f"{map_id}.png").unlink(missing_ok=True)
    clear_strict_mask_cache()

    result = _preview(client, token, map_id)

    assert result["available"] is False
    assert result["failed_stage"] == "strict_geometry"
    assert result["reason"]
    assert result["graph_nodes"] == []


# ===========================================================
# 5. Diagnostics
# ===========================================================

async def test_every_required_diagnostic_is_present(client, monkeypatch):
    token, _ = create_admin_and_get_token(
        client, role="global_manager", email="nb8@example.com"
    )
    map_id, path = await _scenario(client, token, monkeypatch)

    try:
        diagnostics = _preview(client, token, map_id)["diagnostics"]

        for key in (
            "topology_working_resolution",
            "strict_geometry_resolution",
            "wall_stroke_thickness_px",
            "topology_closing_kernel_px",
            "region_component_count",
            "interior_component_count",
            "rejected_component_count",
            "region_components",
            "skeleton_node_count_before_simplification",
            "proposed_node_count",
            "proposed_edge_count",
            "subdivided_edge_count",
            "rejected_edge_count",
            "accepted_semantic_room_count",
            "label_source",
            "label_count",
            "provisional_arrival_count",
            "final_auto_positioned_room_count",
            "final_auto_connected_room_count",
            "rooms_requiring_review",
            "ocr_available",
        ):
            assert key in diagnostics, f"missing diagnostic: {key}"

        assert diagnostics["strict_geometry_resolution"]["width"] > 0
        assert diagnostics["wall_stroke_thickness_px"] > 0
        assert diagnostics["label_source"] in {"vector_pdf", "ocr", "unavailable"}
    finally:
        path.unlink(missing_ok=True)


async def test_rooms_needing_review_are_named_with_reasons(client, monkeypatch):
    token, _ = create_admin_and_get_token(
        client, role="global_manager", email="nb9@example.com"
    )
    map_id, path = await _scenario(client, token, monkeypatch)

    try:
        result = _preview(client, token, map_id)

        for entry in result["diagnostics"]["rooms_requiring_review"]:
            assert entry["semantic_item_id"]
            assert entry["status"]
            assert entry["reason"]
            assert entry["status"] != "auto_connectable"
    finally:
        path.unlink(missing_ok=True)


async def test_rejected_regions_are_reported_for_inspection(client, monkeypatch):
    """
    Seeing what the pipeline threw away is how an operator judges it on a
    real drawing. Rejected components come back as polygons with reasons.
    """

    token, _ = create_admin_and_get_token(
        client, role="global_manager", email="nb10@example.com"
    )
    map_id, path = await _scenario(client, token, monkeypatch)

    try:
        result = _preview(client, token, map_id)

        decisions = {polygon["decision"] for polygon in result["region_polygons"]}
        assert "interior" in decisions

        for polygon in result["region_polygons"]:
            if polygon["decision"] == "rejected":
                assert polygon["reason"]
    finally:
        path.unlink(missing_ok=True)


# ===========================================================
# 6. QR accounting without creating anything
# ===========================================================

async def test_qr_count_is_reported_and_nothing_is_minted(client, monkeypatch):
    token, _ = create_admin_and_get_token(
        client, role="global_manager", email="nb11@example.com"
    )
    map_id, path = await _scenario(client, token, monkeypatch)

    try:
        result = _preview(client, token, map_id)

        assert isinstance(result["location_codes_would_be_created"], int)
        assert result["location_codes_would_be_created"] >= 0
        assert await LocationCode.find_all().count() == 0

        connectable = [
            room for room in result["rooms"] if room["status"] == "auto_connectable"
        ]
        assert result["location_codes_would_be_created"] <= len(connectable)
    finally:
        path.unlink(missing_ok=True)


# ===========================================================
# 7. OCR is optional
# ===========================================================

async def test_missing_ocr_is_reported_not_silently_empty(client, monkeypatch):
    """
    The target environment has no tesseract binary. A raster-only map must
    say so, rather than behaving as though the drawing had no text.
    """

    token, _ = create_admin_and_get_token(
        client, role="global_manager", email="nb12@example.com"
    )
    map_id, path = await _scenario(client, token, monkeypatch, with_labels=False)

    import services.ocr_service as ocr

    monkeypatch.setattr(ocr, "is_ocr_available", lambda: False)

    try:
        result = _preview(client, token, map_id)

        diagnostics = result["diagnostics"]
        assert diagnostics["ocr_available"] is False
        assert diagnostics["label_source"] == "unavailable"
        assert diagnostics["label_source_reason"], (
            "a map with no labels must say WHY, not just report zero"
        )
        assert diagnostics["label_count"] == 0
    finally:
        path.unlink(missing_ok=True)


# ===========================================================
# 8. Authorization
# ===========================================================

async def test_preview_requires_an_admin(client):
    response = client.post(PREVIEW_URL.format(map_id="6a679554b57d02fea449b1fd"), json={})
    assert response.status_code in (401, 403)


async def test_unknown_map_is_404(client):
    token, _ = create_admin_and_get_token(
        client, role="global_manager", email="nb13@example.com"
    )

    response = client.post(
        PREVIEW_URL.format(map_id="not-an-object-id"),
        json={},
        headers=auth_headers(token),
    )
    assert response.status_code == 404


# ===========================================================
# 9. Nothing outside the building
# ===========================================================

async def test_no_proposed_node_lands_outside_the_building(client, monkeypatch):
    token, _ = create_admin_and_get_token(
        client, role="global_manager", email="nb14@example.com"
    )
    map_id, path = await _scenario(client, token, monkeypatch)

    try:
        result = _preview(client, token, map_id)
        assert result["available"] is True

        for node in result["graph_nodes"]:
            assert 200 <= node["x"] <= 1400, node
            assert 150 <= node["y"] <= 1000, node
    finally:
        path.unlink(missing_ok=True)
