"""
Tests for the "admin, navigation-data, permissions, and dashboard cleanup"
task — the parts actually implemented in this pass:

  Problem 1 (semantic analysis / graph generation must not auto-mutate
  navigation data):
    - process_map_in_background no longer applies a walkable graph
      automatically, even when auto_generate_graph=True is explicitly
      passed (the exact flag that used to trigger the bug).
    - POST /{map_id}/generate-graph/preview never writes anything.
    - POST /{map_id}/generate-graph requires confirm=true.
    - GET /{map_id}/generate-graph/cleanup/preview only ever reports
      records proven auto-generated (is_auto_generated=True) — manual
      points are never included.
    - POST /{map_id}/generate-graph/cleanup/apply requires confirm=true,
      deletes only proven-generated records, and is idempotent.

  Problem 2 (RoutePoint counts/scoping):
    - GET /api/route-points/count uses the exact same query builder as
      GET /api/route-points, so a count can never disagree with the
      paired list for the same filters.
    - GET /api/route-points?source=... correctly partitions manual /
      generated / semantic_destination / vertical_connector points using
      authoritative provenance fields, never name guessing.

  Regression: existing navigation/Dijkstra route calculation is
  unaffected by any of the above.

Run with: pytest backend/tests/test_navigation_data_cleanup.py -v
"""

from pathlib import Path

import cv2
import numpy as np
import pytest
from beanie import PydanticObjectId

from tests.test_api_integration import (
    auth_headers,
    create_admin_and_get_token,
    _create_map,
    _create_point,
)

from models.map_model import Map
from models.route_point_model import RoutePoint
from models.route_edge_model import RouteEdge
from services.map_image_service import SOURCE_DIR
from routes.map_routes import process_map_in_background


# ---------------------------------------------------------
# Shared fixture: a synthetic corridor image that reliably produces a
# high-confidence walkable graph if graph generation were to run — same
# helper convention as tests/test_automatic_setup.py's
# _write_synthetic_corridor_image, duplicated locally per this test
# suite's established per-file convention.
# ---------------------------------------------------------

def _write_synthetic_corridor_image(path: Path) -> None:
    image = np.full((500, 800), 255, dtype=np.uint8)

    def wall(x1, y1, x2, y2):
        cv2.rectangle(image, (x1, y1), (x2, y2), 0, thickness=-1)

    wall(50, 150, 750, 160)
    wall(50, 260, 750, 270)
    wall(380, 270, 390, 450)
    wall(460, 270, 470, 450)
    wall(50, 150, 60, 270)
    wall(740, 150, 750, 270)
    wall(380, 440, 470, 450)

    cv2.imwrite(str(path), image)


async def _make_completed_map_with_source_image(client, token, title) -> dict:
    """
    A Map whose processing_status is "completed" and whose source image
    already exists on local disk at the exact path
    generate-graph/preview/apply expect — built via direct Beanie
    manipulation (the plain JSON POST /api/maps used by _create_map has
    no real image pipeline behind it) rather than running the real
    multipart upload + background image-processing pipeline, which is
    unnecessary for exercising the preview/apply/cleanup endpoints
    themselves.
    """

    map_item = _create_map(client, token, title=title)
    map_doc = await Map.get(PydanticObjectId(map_item["id"]))
    map_doc.processing_status = "completed"
    await map_doc.save()

    SOURCE_DIR.mkdir(parents=True, exist_ok=True)
    _write_synthetic_corridor_image(SOURCE_DIR / f"{map_item['id']}.png")

    return map_item


# ===========================================================
# Problem 1.1/1.2 — process_map_in_background no longer auto-applies a
# graph, even when explicitly asked to.
# ===========================================================
@pytest.mark.asyncio
async def test_upload_background_processing_never_auto_creates_route_points_or_edges(
    tmp_path,
):
    map_item = Map(title="Upload Safety Map", scale=1.0, floor=0)
    await map_item.insert()
    map_id = str(map_item.id)

    upload_path = tmp_path / "uploaded.png"
    _write_synthetic_corridor_image(upload_path)

    # auto_generate_graph=True is the EXACT flag that used to trigger the
    # bug (it was the Form default on the real upload endpoint). Passing
    # it explicitly here proves the fix holds even in the worst case,
    # regardless of what any caller (old cached frontend, direct API
    # client, or a test) sends.
    await process_map_in_background(
        map_id, str(upload_path), use_openai=False, auto_generate_graph=True
    )

    points = await RoutePoint.find({"map_id": map_id}).to_list()
    edges = await RouteEdge.find({"map_id": map_id}).to_list()
    assert points == []
    assert edges == []

    refreshed = await Map.get(PydanticObjectId(map_id))
    assert refreshed.processing_status == "completed"
    assert refreshed.graph_generation_status == "pending_manual_preview"


@pytest.mark.asyncio
async def test_upload_background_processing_never_creates_graph_when_flag_false(
    tmp_path,
):
    map_item = Map(title="Upload Safety Map 2", scale=1.0, floor=0)
    await map_item.insert()
    map_id = str(map_item.id)

    upload_path = tmp_path / "uploaded2.png"
    _write_synthetic_corridor_image(upload_path)

    await process_map_in_background(
        map_id, str(upload_path), use_openai=False, auto_generate_graph=False
    )

    points = await RoutePoint.find({"map_id": map_id}).to_list()
    assert points == []


# ===========================================================
# Problem 1.3 — explicit preview never writes; apply requires confirm.
# ===========================================================
@pytest.mark.asyncio
async def test_generate_graph_preview_never_writes_anything(client):
    token, _ = create_admin_and_get_token(client, role="super_admin", email="gg1@example.com")
    map_item = await _make_completed_map_with_source_image(client, token, "Preview Map")

    response = client.post(
        f"/api/maps/{map_item['id']}/generate-graph/preview",
        headers=auth_headers(token),
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["map_id"] == map_item["id"]
    assert len(body["nodes"]) > 0
    assert len(body["edges"]) > 0
    assert body["meets_confidence_threshold"] is True

    points = await RoutePoint.find({"map_id": map_item["id"]}).to_list()
    edges = await RouteEdge.find({"map_id": map_item["id"]}).to_list()
    assert points == []
    assert edges == []


@pytest.mark.asyncio
async def test_generate_graph_apply_without_confirm_is_rejected_and_writes_nothing(client):
    token, _ = create_admin_and_get_token(client, role="super_admin", email="gg2@example.com")
    map_item = await _make_completed_map_with_source_image(client, token, "No Confirm Map")

    response = client.post(
        f"/api/maps/{map_item['id']}/generate-graph",
        json={},
        headers=auth_headers(token),
    )
    assert response.status_code == 400, response.text

    points = await RoutePoint.find({"map_id": map_item["id"]}).to_list()
    assert points == []


@pytest.mark.asyncio
async def test_generate_graph_apply_with_confirm_true_creates_the_previewed_graph(client):
    token, _ = create_admin_and_get_token(client, role="super_admin", email="gg3@example.com")
    map_item = await _make_completed_map_with_source_image(client, token, "Confirm Map")

    preview = client.post(
        f"/api/maps/{map_item['id']}/generate-graph/preview",
        headers=auth_headers(token),
    ).json()

    response = client.post(
        f"/api/maps/{map_item['id']}/generate-graph",
        json={"confirm": True},
        headers=auth_headers(token),
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["graph_applied"] is True
    assert body["graph_points_created"] == len(preview["nodes"])

    points = await RoutePoint.find({"map_id": map_item["id"]}).to_list()
    assert len(points) == len(preview["nodes"])
    for point in points:
        assert point.is_auto_generated is True


# ===========================================================
# Problem 1.6 — cleanup preview/apply.
# ===========================================================
@pytest.mark.asyncio
async def test_cleanup_preview_only_includes_proven_generated_records(client):
    token, _ = create_admin_and_get_token(client, role="super_admin", email="cu1@example.com")
    map_item = _create_map(client, token, title="Cleanup Preview Map")
    map_id = map_item["id"]

    manual_point = RoutePoint(
        map_id=map_id, name="Manual Point", point_type="hallway",
        x=1, y=1, floor=0, is_auto_generated=False,
    )
    await manual_point.insert()

    generated_point = RoutePoint(
        map_id=map_id, name="Auto Point 1", point_type="hallway",
        x=2, y=2, floor=0, is_auto_generated=True,
        generation_method="auto_local", generation_confidence=0.9, generation_version=1,
    )
    await generated_point.insert()

    # RouteEdge.distance is a required field (final calculated distance in
    # meters) with no default — derive a realistic positive value from the
    # two points' own coordinates (Euclidean distance from (1,1) to (2,2))
    # rather than an arbitrary placeholder, matching how a real edge's
    # distance is actually computed.
    edge_distance = ((generated_point.x - manual_point.x) ** 2 + (generated_point.y - manual_point.y) ** 2) ** 0.5

    generated_edge = RouteEdge(
        map_id=map_id,
        from_point_id=str(manual_point.id),
        to_point_id=str(generated_point.id),
        edge_type="walkway",
        distance=edge_distance,
        is_auto_generated=True,
        generation_method="auto_local", generation_confidence=0.9, generation_version=1,
    )
    await generated_edge.insert()

    response = client.get(
        f"/api/maps/{map_id}/generate-graph/cleanup/preview",
        headers=auth_headers(token),
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["generated_point_count"] == 1
    assert str(generated_point.id) in body["generated_point_ids"]
    assert str(manual_point.id) not in body["generated_point_ids"]
    assert body["generated_edge_count"] == 1
    assert body["unknown_legacy_point_count"] == 0


@pytest.mark.asyncio
async def test_cleanup_apply_requires_confirmation(client):
    token, _ = create_admin_and_get_token(client, role="super_admin", email="cu2@example.com")
    map_item = _create_map(client, token, title="Cleanup No Confirm Map")
    map_id = map_item["id"]

    generated_point = RoutePoint(
        map_id=map_id, name="Auto Point 1", point_type="hallway",
        x=2, y=2, floor=0, is_auto_generated=True,
    )
    await generated_point.insert()

    response = client.post(
        f"/api/maps/{map_id}/generate-graph/cleanup/apply",
        json={},
        headers=auth_headers(token),
    )
    assert response.status_code == 400, response.text

    still_there = await RoutePoint.get(generated_point.id)
    assert still_there is not None


@pytest.mark.asyncio
async def test_cleanup_apply_deletes_only_generated_records_and_is_idempotent(client):
    token, _ = create_admin_and_get_token(client, role="super_admin", email="cu3@example.com")
    map_item = _create_map(client, token, title="Cleanup Apply Map")
    map_id = map_item["id"]

    manual_point = RoutePoint(
        map_id=map_id, name="Manual Point", point_type="hallway",
        x=1, y=1, floor=0, is_auto_generated=False,
    )
    await manual_point.insert()

    generated_point = RoutePoint(
        map_id=map_id, name="Auto Point 1", point_type="hallway",
        x=2, y=2, floor=0, is_auto_generated=True,
    )
    await generated_point.insert()

    first = client.post(
        f"/api/maps/{map_id}/generate-graph/cleanup/apply",
        json={"confirm": True},
        headers=auth_headers(token),
    )
    assert first.status_code == 200, first.text
    assert first.json()["points_deleted"] == 1

    assert await RoutePoint.get(manual_point.id) is not None
    assert await RoutePoint.get(generated_point.id) is None

    # Idempotent — nothing left to delete the second time.
    second = client.post(
        f"/api/maps/{map_id}/generate-graph/cleanup/apply",
        json={"confirm": True},
        headers=auth_headers(token),
    )
    assert second.status_code == 200, second.text
    assert second.json()["points_deleted"] == 0
    assert second.json()["edges_deleted"] == 0


# ===========================================================
# Problem 2.1 — count endpoint matches list endpoint for the same filters.
# ===========================================================
def test_route_point_count_matches_list_for_the_same_filters(client):
    token, _ = create_admin_and_get_token(client, role="super_admin", email="cnt1@example.com")
    map_a = _create_map(client, token, title="Count Map A")
    map_b = _create_map(client, token, title="Count Map B")

    _create_point(client, token, map_a["id"], "A1", 0, 0)
    _create_point(client, token, map_a["id"], "A2", 10, 0)
    _create_point(client, token, map_b["id"], "B1", 0, 0)

    scoped_list = client.get(
        "/api/route-points", params={"map_id": map_a["id"]}
    ).json()
    scoped_count = client.get(
        "/api/route-points/count", params={"map_id": map_a["id"]}
    ).json()

    assert scoped_count["count"] == len(scoped_list)
    assert scoped_count["count"] == 2
    assert scoped_count["is_global"] is False
    assert scoped_count["map_id"] == map_a["id"]

    global_list = client.get("/api/route-points").json()
    global_count = client.get("/api/route-points/count").json()

    assert global_count["count"] == len(global_list)
    assert global_count["is_global"] is True
    # The global (unfiltered) count must be >= the one-map count — this is
    # the exact "492 vs 28" relationship, now both computed the same way
    # and both explicitly labeled with their own scope.
    assert global_count["count"] >= scoped_count["count"]


def test_route_point_count_for_one_building_excludes_another_building(client):
    token, _ = create_admin_and_get_token(client, role="super_admin", email="cnt2@example.com")
    building_a = client.post(
        "/api/locations/buildings", json={"name_en": "Count Building A"},
        headers=auth_headers(token),
    ).json()
    building_b = client.post(
        "/api/locations/buildings", json={"name_en": "Count Building B"},
        headers=auth_headers(token),
    ).json()

    map_a = _create_map(client, token, title="Bldg A Map", building_id=building_a["id"])
    map_b = _create_map(client, token, title="Bldg B Map", building_id=building_b["id"])

    _create_point(client, token, map_a["id"], "A1", 0, 0)
    _create_point(client, token, map_b["id"], "B1", 0, 0)
    _create_point(client, token, map_b["id"], "B2", 10, 0)

    count_a = client.get(
        "/api/route-points/count", params={"building_id": building_a["id"]}
    ).json()
    count_b = client.get(
        "/api/route-points/count", params={"building_id": building_b["id"]}
    ).json()

    assert count_a["count"] == 1
    assert count_b["count"] == 2


# ===========================================================
# Problem 2.3 — source classification via the list endpoint's filter.
# ===========================================================
@pytest.mark.asyncio
async def test_route_point_source_filter_partitions_by_authoritative_provenance(client):
    token, _ = create_admin_and_get_token(client, role="super_admin", email="src1@example.com")
    map_item = _create_map(client, token, title="Source Filter Map")
    map_id = map_item["id"]

    manual_point = RoutePoint(
        map_id=map_id, name="Manual", point_type="hallway", x=1, y=1, floor=0,
    )
    await manual_point.insert()

    generated_point = RoutePoint(
        map_id=map_id, name="Auto Point 5", point_type="hallway", x=2, y=2, floor=0,
        is_auto_generated=True,
    )
    await generated_point.insert()

    semantic_point = RoutePoint(
        map_id=map_id, name="Semantic Dest", point_type="room", x=3, y=3, floor=0,
        semantic_entity_external_id="sem-1", semantic_entity_type="place",
    )
    await semantic_point.insert()

    connector_point = RoutePoint(
        map_id=map_id, name="Elevator Stop", point_type="hallway", x=4, y=4, floor=0,
        connector_id="conn-1", connector_code="ELEVATOR-A",
    )
    await connector_point.insert()

    # Legacy-looking name but NO provenance flag set — must be classified
    # unknown_legacy, never silently treated as "generated" from the name
    # alone.
    legacy_point = RoutePoint(
        map_id=map_id, name="Auto Point 99", point_type="hallway", x=5, y=5, floor=0,
    )
    await legacy_point.insert()

    def _ids_for(source):
        result = client.get(
            "/api/route-points", params={"map_id": map_id, "source": source}
        ).json()
        return {item["id"] for item in result}

    assert _ids_for("manual") == {str(manual_point.id)}
    assert _ids_for("generated") == {str(generated_point.id)}
    assert _ids_for("semantic_destination") == {str(semantic_point.id)}
    assert _ids_for("vertical_connector") == {str(connector_point.id)}
    assert _ids_for("unknown_legacy") == {str(legacy_point.id)}


# ===========================================================
# Regression — existing navigation/Dijkstra route calculation unaffected.
# ===========================================================
def test_existing_navigation_route_calculation_is_unaffected(client):
    token, _ = create_admin_and_get_token(client, role="super_admin", email="nav1@example.com")
    map_item = _create_map(client, token, title="Nav Regression Map")

    point_a = _create_point(client, token, map_item["id"], "Point A", 0, 0)
    point_b = _create_point(client, token, map_item["id"], "Point B", 10, 0)
    client.post(
        "/api/route-edges",
        json={
            "map_id": map_item["id"],
            "from_point_id": point_a["id"],
            "to_point_id": point_b["id"],
            "edge_type": "walkway",
        },
        headers=auth_headers(token),
    )

    response = client.post(
        "/api/navigation/route",
        json={
            "map_id": map_item["id"],
            "start_point_id": point_a["id"],
            "end_point_id": point_b["id"],
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["path_point_ids"] == [point_a["id"], point_b["id"]]
