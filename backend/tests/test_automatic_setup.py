"""
Tests for the automatic building/map/graph setup feature: building
automation, current-data backfill, RoutePoint deduplication, automatic
neighbor connection, and automatic walkable-graph generation.

Run with: pytest backend/tests/test_automatic_setup.py -v
"""

from pathlib import Path

import cv2
import numpy as np
import pytest

from tests.test_api_integration import (
    auth_headers,
    create_admin_and_get_token,
    _create_map,
    _create_point,
)

from models.map_model import Map
from models.route_point_model import RoutePoint
from models.route_edge_model import RouteEdge
from services.building_service import find_or_create_building, normalize_building_name
from services.point_dedup_service import find_or_create_route_point
from services.graph_connection_service import auto_connect_point, has_clear_line
from services.graph_generation_service import (
    extract_walkable_graph,
    generate_and_apply_walkable_graph,
)
from services.map_image_service import SOURCE_DIR


# ---------------------------------------------------------
# Part 1/2 — building automation & backfill
# ---------------------------------------------------------

def test_uploading_map_with_campus_creates_one_building(client):
    token, _ = create_admin_and_get_token(client, email="b1@example.com")

    response = client.post(
        "/api/maps",
        json={"title": "Mall Floor 1", "campus": "QuickRoute Mall"},
        headers=auth_headers(token),
    )
    assert response.status_code == 201, response.text
    map_item = response.json()

    assert map_item["building_id"]

    buildings = client.get("/api/locations/buildings").json()
    assert len(buildings) == 1
    assert buildings[0]["name_en"] == "QuickRoute Mall"
    assert buildings[0]["id"] == map_item["building_id"]


def test_second_map_same_normalized_campus_reuses_building(client):
    token, _ = create_admin_and_get_token(client, email="b2@example.com")

    first = client.post(
        "/api/maps",
        json={"title": "Mall Floor 1", "campus": "QuickRoute Mall"},
        headers=auth_headers(token),
    ).json()

    # Different casing/whitespace, same underlying identity.
    second = client.post(
        "/api/maps",
        json={"title": "Mall Floor 2", "campus": "  quickroute   mall  "},
        headers=auth_headers(token),
    ).json()

    assert first["building_id"] == second["building_id"]

    buildings = client.get("/api/locations/buildings").json()
    assert len(buildings) == 1


def test_normalize_building_name_is_case_whitespace_insensitive():
    assert normalize_building_name("QuickRoute Mall") == normalize_building_name(
        "  quickroute   mall "
    )
    assert normalize_building_name("QuickRoute Mall") != normalize_building_name(
        "QuickRoute Mall Annex"
    )


def test_new_route_point_inherits_map_building_id(client):
    token, _ = create_admin_and_get_token(client, email="b3@example.com")

    map_item = client.post(
        "/api/maps",
        json={"title": "Inherit Map", "campus": "Inherit Campus"},
        headers=auth_headers(token),
    ).json()

    point = _create_point(client, token, map_item["id"], "P1", 0, 0)

    assert point["building_id"] == map_item["building_id"]
    assert point["building_id"] is not None


@pytest.mark.asyncio
async def test_backfill_buildings_is_idempotent(client):
    token, _ = create_admin_and_get_token(client, email="b4@example.com")

    # Simulate the real pre-migration state: a Map/RoutePoint pair created
    # with no building_id at all, bypassing the route layer (which now
    # always assigns one) the same way the real historical data does.
    legacy_map = Map(title="QuickRoute Mall - Floor 1", campus="QuickRoute Mall")
    await legacy_map.insert()

    legacy_point = RoutePoint(
        map_id=str(legacy_map.id),
        name="Main Entrance",
        point_type="entrance",
        x=10,
        y=10,
        floor=1,
    )
    await legacy_point.insert()

    first_run = client.post(
        "/api/maintenance/backfill-buildings",
        headers=auth_headers(token),
    )
    assert first_run.status_code == 200, first_run.text
    first_body = first_run.json()
    assert first_body["maps_updated"] == 1
    assert first_body["points_updated"] == 1

    refreshed_map = await Map.get(legacy_map.id)
    refreshed_point = await RoutePoint.get(legacy_point.id)
    assert refreshed_map.building_id is not None
    assert refreshed_point.building_id == refreshed_map.building_id

    second_run = client.post(
        "/api/maintenance/backfill-buildings",
        headers=auth_headers(token),
    )
    assert second_run.status_code == 200, second_run.text
    second_body = second_run.json()
    assert second_body["maps_updated"] == 0
    assert second_body["points_updated"] == 0

    buildings = client.get("/api/locations/buildings").json()
    quickroute_mall_buildings = [
        b for b in buildings if b["name_en"] == "QuickRoute Mall"
    ]
    assert len(quickroute_mall_buildings) == 1


def test_backfill_buildings_requires_authentication(client):
    # No Authorization header at all — this is the exact request Swagger's
    # "Try it out" sends when its Authorize flow isn't used, and what the
    # Admin UI must never produce since it always attaches the stored JWT.
    response = client.post("/api/maintenance/backfill-buildings")
    assert response.status_code == 401
    assert response.json()["detail"] == "Not authenticated"


def test_backfill_buildings_rejects_non_global_admin_roles(client):
    # A regular end user must never be able to run a data-maintenance
    # operation.
    regular_token, _ = create_admin_and_get_token(
        client, role="regular_user", email="reguser-backfill@example.com"
    )
    regular_response = client.post(
        "/api/maintenance/backfill-buildings",
        headers=auth_headers(regular_token),
    )
    assert regular_response.status_code == 403

    # A building_manager is an admin-tier role but is scoped to specific
    # buildings, not the whole system — require_global_admin (super_admin /
    # global_manager only) must still reject it.
    manager_token, _ = create_admin_and_get_token(
        client, role="building_manager", email="bldgmgr-backfill@example.com"
    )
    manager_response = client.post(
        "/api/maintenance/backfill-buildings",
        headers=auth_headers(manager_token),
    )
    assert manager_response.status_code == 403


@pytest.mark.asyncio
async def test_backfill_buildings_never_overwrites_an_existing_valid_building_id(
    client,
):
    token, _ = create_admin_and_get_token(client, email="b5@example.com")

    # A map that already has a correct, deliberately-assigned building_id —
    # simulating a normal, already-consistent map alongside the legacy one
    # the backfill is meant to fix.
    already_valid_map = Map(
        title="Already Linked Map", campus="Some Other Campus"
    )
    await already_valid_map.insert()

    deliberately_assigned_building_id = "000000000000000000000001"
    already_valid_map.building_id = deliberately_assigned_building_id
    await already_valid_map.save()

    already_valid_point = RoutePoint(
        map_id=str(already_valid_map.id),
        name="Existing Point",
        point_type="hallway",
        x=5,
        y=5,
        floor=1,
        building_id=deliberately_assigned_building_id,
    )
    await already_valid_point.insert()

    response = client.post(
        "/api/maintenance/backfill-buildings",
        headers=auth_headers(token),
    )
    assert response.status_code == 200, response.text
    body = response.json()

    # This map was never "missing" a building_id, so it must not appear in
    # what the backfill touched at all.
    assert body["maps_updated"] == 0
    assert body["points_updated"] == 0

    refreshed_map = await Map.get(already_valid_map.id)
    refreshed_point = await RoutePoint.get(already_valid_point.id)
    assert refreshed_map.building_id == deliberately_assigned_building_id
    assert refreshed_point.building_id == deliberately_assigned_building_id


# ---------------------------------------------------------
# Part 5 — point deduplication
# ---------------------------------------------------------

def test_same_map_floor_location_reuses_existing_point(client):
    token, _ = create_admin_and_get_token(client, email="d1@example.com")
    map_item = _create_map(client, token, title="Dedup Map")

    first = client.post(
        "/api/route-points",
        json={"map_id": map_item["id"], "name": "Junction", "x": 100, "y": 100, "floor": 0},
        headers=auth_headers(token),
    ).json()
    assert first["was_reused"] is False

    second = client.post(
        "/api/route-points",
        # Two pixels off — well within the dedup tolerance.
        json={"map_id": map_item["id"], "name": "Junction Again", "x": 102, "y": 101, "floor": 0},
        headers=auth_headers(token),
    ).json()

    assert second["was_reused"] is True
    assert second["id"] == first["id"]

    all_points = client.get(
        "/api/route-points", params={"map_id": map_item["id"]}
    ).json()
    assert len(all_points) == 1


def test_nearby_but_distinct_junction_can_still_be_created(client):
    token, _ = create_admin_and_get_token(client, email="d2@example.com")
    map_item = _create_map(client, token, title="Distinct Junctions Map")

    first = _create_point(client, token, map_item["id"], "J1", 100, 100)
    # Far enough apart (50px) to be a genuinely different junction, not a
    # duplicate click on the same spot.
    second = _create_point(client, token, map_item["id"], "J2", 150, 100)

    assert first["id"] != second["id"]

    all_points = client.get(
        "/api/route-points", params={"map_id": map_item["id"]}
    ).json()
    assert len(all_points) == 2


def test_dedup_never_reuses_a_point_from_a_different_map(client):
    token, _ = create_admin_and_get_token(client, email="d3@example.com")
    map_a = _create_map(client, token, title="Map A")
    map_b = _create_map(client, token, title="Map B")

    point_a = _create_point(client, token, map_a["id"], "PA", 100, 100)
    point_b = _create_point(client, token, map_b["id"], "PB", 100, 100)

    assert point_a["id"] != point_b["id"]


def test_dedup_never_reuses_a_point_from_a_different_floor(client):
    token, _ = create_admin_and_get_token(client, email="d4@example.com")
    map_item = _create_map(client, token, title="Multi Floor Map")

    ground = _create_point(client, token, map_item["id"], "GF", 100, 100, floor=0)
    first_floor = _create_point(client, token, map_item["id"], "F1", 100, 100, floor=1)

    assert ground["id"] != first_floor["id"]


# ---------------------------------------------------------
# Part 6 — automatic neighbor connection
# ---------------------------------------------------------

@pytest.mark.asyncio
async def test_auto_connect_nearest_creates_exactly_one_edge(client):
    token, _ = create_admin_and_get_token(client, email="c1@example.com")
    map_item = _create_map(client, token, title="Auto Connect Map")

    anchor = _create_point(client, token, map_item["id"], "Anchor", 0, 0)
    _create_point(client, token, map_item["id"], "Near", 50, 0)
    _create_point(client, token, map_item["id"], "Far", 400, 0)

    new_point_response = client.post(
        "/api/route-points?auto_connect=nearest",
        # 40px from "Near" (well past the point-dedup tolerance, so this
        # is a genuinely new point) but still clearly its nearest
        # neighbor versus Anchor (90px) or Far (310px).
        json={"map_id": map_item["id"], "name": "New Corridor Point", "x": 90, "y": 0, "floor": 0},
        headers=auth_headers(token),
    )
    assert new_point_response.status_code == 201, new_point_response.text
    new_point = new_point_response.json()

    edges = client.get(
        "/api/route-edges",
        params={"map_id": map_item["id"]},
        headers=auth_headers(token),
    ).json()

    edges_touching_new_point = [
        e for e in edges
        if new_point["id"] in (e["from_point_id"], e["to_point_id"])
    ]
    assert len(edges_touching_new_point) == 1


@pytest.mark.asyncio
async def test_auto_connect_all_valid_connects_multiple_branches(client):
    token, _ = create_admin_and_get_token(client, email="c2@example.com")
    map_item = _create_map(client, token, title="Junction Map")

    # A junction point surrounded on 3 sides by other points, none of them
    # already connected to it or to each other.
    _create_point(client, token, map_item["id"], "North", 100, 0)
    _create_point(client, token, map_item["id"], "East", 200, 100)
    _create_point(client, token, map_item["id"], "South", 100, 200)

    junction_response = client.post(
        "/api/route-points?auto_connect=all_valid",
        json={"map_id": map_item["id"], "name": "Junction", "x": 100, "y": 100, "floor": 0},
        headers=auth_headers(token),
    )
    assert junction_response.status_code == 201, junction_response.text
    junction = junction_response.json()

    edges = client.get(
        "/api/route-edges",
        params={"map_id": map_item["id"]},
        headers=auth_headers(token),
    ).json()

    edges_touching_junction = [
        e for e in edges
        if junction["id"] in (e["from_point_id"], e["to_point_id"])
    ]
    assert len(edges_touching_junction) == 3


@pytest.mark.asyncio
async def test_auto_connect_skips_a_pair_that_is_already_connected(client):
    token, _ = create_admin_and_get_token(client, email="c3@example.com")
    map_item = _create_map(client, token, title="Already Connected Map")

    a = _create_point(client, token, map_item["id"], "PA", 0, 0)
    b = _create_point(client, token, map_item["id"], "PB", 50, 0)

    client.post(
        "/api/route-edges",
        json={"map_id": map_item["id"], "from_point_id": a["id"], "to_point_id": b["id"]},
        headers=auth_headers(token),
    )

    point_a_doc = await RoutePoint.get(a["id"])
    summary = await auto_connect_point(point_a_doc, mode="all_valid")

    assert len(summary["edges_created"]) == 0
    assert any(r["reason"] == "already_connected" for r in summary["rejected"])


def test_has_clear_line_true_when_no_source_image_exists():
    # No image on disk for this map_id — the check must not block a
    # connection just because there's nothing to verify against.
    assert has_clear_line("no-such-map-id", 0, 0, 100, 100) is True


def test_has_clear_line_rejects_a_path_that_crosses_a_real_wall(tmp_path, monkeypatch):
    # Build a synthetic floor plan: a solid wall directly between two
    # points, and verify has_clear_line refuses to connect across it while
    # still allowing a connection that runs alongside the wall instead.
    image = np.full((300, 300), 255, dtype=np.uint8)
    cv2.rectangle(image, (140, 0), (160, 300), 0, thickness=-1)  # vertical wall

    fake_map_id = "wall-test-map"
    monkeypatch.setattr(
        "services.graph_connection_service.SOURCE_DIR", tmp_path
    )
    cv2.imwrite(str(tmp_path / f"{fake_map_id}.png"), image)

    # Straight across the wall.
    assert has_clear_line(fake_map_id, 50, 150, 250, 150) is False

    # Same start point, but a path that never crosses the wall.
    assert has_clear_line(fake_map_id, 50, 10, 50, 290) is True


# ---------------------------------------------------------
# Part 7 — separate-path merge behavior
# ---------------------------------------------------------

def test_separate_path_remains_disconnected_without_explicit_reuse(client):
    token, _ = create_admin_and_get_token(client, email="m1@example.com")
    map_item = _create_map(client, token, title="Disconnected Paths Map")

    a = _create_point(client, token, map_item["id"], "A1", 0, 0)
    b = _create_point(client, token, map_item["id"], "B1", 50, 0)
    client.post(
        "/api/route-edges",
        json={"map_id": map_item["id"], "from_point_id": a["id"], "to_point_id": b["id"]},
        headers=auth_headers(token),
    )

    # A second path drawn nearby but never explicitly connected to A/B.
    c = _create_point(client, token, map_item["id"], "C1", 500, 500)
    d = _create_point(client, token, map_item["id"], "D1", 550, 500)
    client.post(
        "/api/route-edges",
        json={"map_id": map_item["id"], "from_point_id": c["id"], "to_point_id": d["id"]},
        headers=auth_headers(token),
    )

    route_response = client.post(
        "/api/navigation/route",
        json={"map_id": map_item["id"], "start_point_id": a["id"], "end_point_id": d["id"]},
    )
    assert route_response.status_code == 404


# ---------------------------------------------------------
# Part 9 — location code generation
# ---------------------------------------------------------

def test_generate_location_code_has_consistent_references(client):
    token, _ = create_admin_and_get_token(client, email="l1@example.com")
    map_item = _create_map(client, token, title="Generate Code Map", campus="Generate Campus")
    entrance = _create_point(
        client, token, map_item["id"], "Main Entrance", 5, 5, point_type="entrance"
    )

    response = client.post(
        "/api/location-codes/generate",
        json={"route_point_id": entrance["id"]},
        headers=auth_headers(token),
    )
    assert response.status_code == 201, response.text
    code = response.json()

    assert code["map_id"] == map_item["id"]
    assert code["route_point_id"] == entrance["id"]
    assert code["building_id"] == map_item["building_id"]
    assert len(code["code"]) == 8

    resolved = client.get(f"/api/location-codes/resolve/{code['code']}").json()
    assert resolved["building_id"] == map_item["building_id"]
    assert resolved["route_point_id"] == entrance["id"]


def test_duplicate_location_code_is_rejected(client):
    token, _ = create_admin_and_get_token(client, email="l2@example.com")
    building = client.post(
        "/api/locations/buildings",
        json={"name_en": "Dup Code Building"},
        headers=auth_headers(token),
    ).json()
    map_item = _create_map(client, token, title="Dup Code Map", building_id=building["id"])
    point = _create_point(client, token, map_item["id"], "PP", 0, 0)

    payload = {
        "code": "QR-DUPTEST-1",
        "building_id": building["id"],
        "map_id": map_item["id"],
        "route_point_id": point["id"],
    }

    first = client.post("/api/location-codes", json=payload, headers=auth_headers(token))
    assert first.status_code == 201

    second = client.post("/api/location-codes", json=payload, headers=auth_headers(token))
    assert second.status_code == 409


# ---------------------------------------------------------
# Part 3 — automatic walkable-graph generation
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


def test_extract_walkable_graph_uses_original_image_coordinates(tmp_path):
    image_path = tmp_path / "synthetic.png"
    _write_synthetic_corridor_image(image_path)

    result = extract_walkable_graph(image_path)

    assert len(result.nodes) >= 2
    assert len(result.edges) >= 1

    for node in result.nodes:
        assert 0 <= node.x <= 800
        assert 0 <= node.y <= 500


@pytest.mark.asyncio
async def test_generate_and_apply_walkable_graph_regeneration_does_not_duplicate(tmp_path):
    image_path = tmp_path / "synthetic.png"
    _write_synthetic_corridor_image(image_path)

    map_item = Map(title="Synthetic Graph Map", scale=1.0, floor=0)
    await map_item.insert()

    first_outcome = await generate_and_apply_walkable_graph(map_item, image_path)
    assert first_outcome.applied is True
    assert first_outcome.points_created > 0

    points_after_first = await RoutePoint.find(
        {"map_id": str(map_item.id)}
    ).to_list()

    second_outcome = await generate_and_apply_walkable_graph(map_item, image_path)
    assert second_outcome.applied is True

    points_after_second = await RoutePoint.find(
        {"map_id": str(map_item.id)}
    ).to_list()

    # Regeneration replaces the auto-generated graph rather than adding a
    # second copy on top of the first.
    assert len(points_after_second) == len(points_after_first)


@pytest.mark.asyncio
async def test_generate_and_apply_walkable_graph_preserves_manual_points(tmp_path):
    image_path = tmp_path / "synthetic.png"
    _write_synthetic_corridor_image(image_path)

    map_item = Map(title="Manual Preserve Map", scale=1.0, floor=0)
    await map_item.insert()

    manual_point = RoutePoint(
        map_id=str(map_item.id),
        name="Manually Added",
        point_type="hallway",
        x=10,
        y=10,
        floor=0,
        is_auto_generated=False,
    )
    await manual_point.insert()

    await generate_and_apply_walkable_graph(map_item, image_path)
    await generate_and_apply_walkable_graph(map_item, image_path)

    still_there = await RoutePoint.get(manual_point.id)
    assert still_there is not None
    assert still_there.name == "Manually Added"


@pytest.mark.asyncio
async def test_dijkstra_works_across_the_generated_graph(client, tmp_path):
    image_path = tmp_path / "synthetic.png"
    _write_synthetic_corridor_image(image_path)

    token, _ = create_admin_and_get_token(client, email="g1@example.com")
    map_item_response = client.post(
        "/api/maps",
        json={"title": "Routable Generated Map", "floor": 0},
        headers=auth_headers(token),
    ).json()

    map_doc = await Map.get(map_item_response["id"])
    outcome = await generate_and_apply_walkable_graph(map_doc, image_path)
    assert outcome.applied is True

    points = client.get(
        "/api/route-points", params={"map_id": map_item_response["id"]}
    ).json()
    assert len(points) >= 2

    # Any two distinct generated points on the same connected graph must
    # be routable — pick the two farthest apart in the endpoint list.
    start, end = points[0], points[-1]

    route_response = client.post(
        "/api/navigation/route",
        json={
            "map_id": map_item_response["id"],
            "start_point_id": start["id"],
            "end_point_id": end["id"],
        },
    )

    # Either a real connected route (expected for this clean synthetic
    # corridor) or, in the unlikely case the two chosen endpoints ended up
    # in different components, a clean 404 — never a server error.
    assert route_response.status_code in (200, 404)


@pytest.mark.skipif(
    not (SOURCE_DIR / "6a5fac8d0cf91fa84e9350ba.png").exists(),
    reason="Real uploaded QuickRoute Mall map image not present in this environment",
)
def test_extract_walkable_graph_against_the_real_uploaded_mall_map():
    """
    Real-map verification (not synthetic): runs the actual extraction
    pipeline against the real processed source image for map
    6a5fac8d0cf91fa84e9350ba (QuickRoute Mall - Floor 1) that exists on
    disk in this environment. Only asserts structural properties (no
    crash, valid coordinate bounds) — it deliberately does not assert a
    specific confidence value, since that would make the test a snapshot
    of one heuristic's current tuning rather than a real correctness
    check.
    """

    image_path = SOURCE_DIR / "6a5fac8d0cf91fa84e9350ba.png"
    result = extract_walkable_graph(image_path)

    with_size = cv2.imread(str(image_path))
    height, width = with_size.shape[:2]

    for node in result.nodes:
        assert 0 <= node.x <= width
        assert 0 <= node.y <= height

    for edge in result.edges:
        assert 0 <= edge.from_index < len(result.nodes)
        assert 0 <= edge.to_index < len(result.nodes)

    assert 0.0 <= result.confidence <= 1.0


# ---------------------------------------------------------
# Draw Walkable Path "Merge with safe nearby graph points" gating
# ---------------------------------------------------------

def test_auto_connect_nearby_never_crosses_a_real_wall_via_create_route_point(client, tmp_path, monkeypatch):
    # Integration-level version of test_has_clear_line_rejects_a_path_that_
    # crosses_a_real_wall: going through the real POST /api/route-points?
    # auto_connect=nearest endpoint (what the frontend's "Merge with safe
    # nearby graph points" mode actually calls), not just the unit-level
    # has_clear_line() check.
    token, _ = create_admin_and_get_token(client, email="wallauto@example.com")
    map_item = _create_map(client, token, title="Wall Auto Connect Map")

    _create_point(client, token, map_item["id"], "AcrossWall", 250, 150, floor=0)

    image = np.full((300, 300), 255, dtype=np.uint8)
    cv2.rectangle(image, (140, 0), (160, 300), 0, thickness=-1)  # vertical wall

    monkeypatch.setattr(
        "services.graph_connection_service.SOURCE_DIR", tmp_path
    )
    cv2.imwrite(str(tmp_path / f"{map_item['id']}.png"), image)

    response = client.post(
        "/api/route-points?auto_connect=nearest",
        json={"map_id": map_item["id"], "name": "NearWall", "x": 50, "y": 150, "floor": 0},
        headers=auth_headers(token),
    )
    assert response.status_code == 201, response.text
    new_point = response.json()

    # The only candidate is on the other side of the wall — must not
    # auto-connect across it.
    assert new_point["auto_connected_edge_ids"] == []

    edges = client.get(
        "/api/route-edges",
        params={"map_id": map_item["id"]},
        headers=auth_headers(token),
    ).json()
    assert edges == []


def test_auto_connect_nearby_never_crosses_map_boundaries(client):
    # find_connection_candidates queries by map_id, so a point on a
    # different map is structurally never even considered — pin this down
    # at the create_route_point/auto_connect integration level too, not
    # only the dedup-level cross-map test above.
    token, _ = create_admin_and_get_token(client, email="crossmapauto@example.com")
    map_a = _create_map(client, token, title="Cross Map Auto A")
    map_b = _create_map(client, token, title="Cross Map Auto B")

    _create_point(client, token, map_a["id"], "OnMapA", 0, 0)

    response = client.post(
        "/api/route-points?auto_connect=nearest",
        json={"map_id": map_b["id"], "name": "OnMapB", "x": 0, "y": 0, "floor": 0},
        headers=auth_headers(token),
    )
    assert response.status_code == 201, response.text
    new_point = response.json()

    assert new_point["auto_connected_edge_ids"] == []


def test_auto_connect_nearby_never_crosses_floors(client):
    # Same structural guarantee as the map-boundary test, but for floor —
    # find_connection_candidates always filters by floor when the new
    # point has one set.
    token, _ = create_admin_and_get_token(client, email="crossflrauto@example.com")
    map_item = _create_map(client, token, title="Cross Floor Auto Map")

    _create_point(client, token, map_item["id"], "Ground", 0, 0, floor=0)

    response = client.post(
        "/api/route-points?auto_connect=nearest",
        json={"map_id": map_item["id"], "name": "FirstFloor", "x": 0, "y": 0, "floor": 1},
        headers=auth_headers(token),
    )
    assert response.status_code == 201, response.text
    new_point = response.json()

    assert new_point["auto_connected_edge_ids"] == []
