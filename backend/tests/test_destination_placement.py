"""
Tests for map-based Room/Destination placement: clicking a real location on
the map (in original-image coordinates), creating/reusing a destination
RoutePoint there, auto-connecting it to the walkable graph, and having the
end-user flow resolve that exact RoutePoint — plus the OCR name-suggestion
endpoint, which must never save anything on its own.

Run with: pytest backend/tests/test_destination_placement.py -v
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
from models.room_model import Room
from models.route_point_model import RoutePoint
from models.route_edge_model import RouteEdge
from services import ocr_service


# ---------------------------------------------------------
# Helpers
# ---------------------------------------------------------

def _create_room_on_map(client, token, *, building_id, map_id, name, x, y, floor=1, room_type="clinic"):
    return client.post(
        "/api/rooms",
        json={
            "building_id": building_id,
            "name_en": name,
            "room_type": room_type,
            "floor": floor,
            "map_id": map_id,
            "x": x,
            "y": y,
        },
        headers=auth_headers(token),
    )


# ---------------------------------------------------------
# 1/2 — coordinate storage + building/map linkage
# ---------------------------------------------------------

def test_map_placement_stores_original_image_coordinates(client):
    token, _ = create_admin_and_get_token(client, email="dest1@example.com")
    map_item = _create_map(client, token, title="Dest Map 1", campus="Dest Campus 1")

    response = _create_room_on_map(
        client, token,
        building_id=map_item["building_id"],
        map_id=map_item["id"],
        name="Pharmacy Corner",
        x=812.0,
        y=345.0,
    )
    assert response.status_code == 201, response.text
    room = response.json()

    # Exactly the coordinates that were clicked — not a browser-scaled or
    # otherwise transformed value.
    assert room["x"] == 812.0
    assert room["y"] == 345.0
    assert room["map_id"] == map_item["id"]


def test_map_placement_links_correct_building_and_map(client):
    token, _ = create_admin_and_get_token(client, email="dest2@example.com")
    map_item = _create_map(client, token, title="Dest Map 2", campus="Dest Campus 2")

    response = _create_room_on_map(
        client, token,
        building_id=map_item["building_id"],
        map_id=map_item["id"],
        name="Radiology",
        x=100, y=100,
    )
    assert response.status_code == 201, response.text
    room = response.json()

    assert room["building_id"] == map_item["building_id"]
    assert room["map_id"] == map_item["id"]


def test_map_placement_rejects_map_from_a_different_building(client):
    token, _ = create_admin_and_get_token(client, email="dest2b@example.com")
    map_a = _create_map(client, token, title="Building A Map", campus="Building A")
    map_b = _create_map(client, token, title="Building B Map", campus="Building B")

    # Room says it belongs to building A, but the map given belongs to B.
    response = _create_room_on_map(
        client, token,
        building_id=map_a["building_id"],
        map_id=map_b["id"],
        name="Mismatched Room",
        x=10, y=10,
    )
    assert response.status_code == 400, response.text

    # And the room itself must not have been left behind (rollback).
    all_rooms = client.get("/api/rooms").json()
    assert all(r["name_en"] != "Mismatched Room" for r in all_rooms)


# ---------------------------------------------------------
# 3/4 — RoutePoint creation + reuse
# ---------------------------------------------------------

@pytest.mark.asyncio
async def test_map_placement_creates_a_destination_route_point(client):
    token, _ = create_admin_and_get_token(client, email="dest3@example.com")
    map_item = _create_map(client, token, title="Dest Map 3", campus="Dest Campus 3")

    response = _create_room_on_map(
        client, token,
        building_id=map_item["building_id"],
        map_id=map_item["id"],
        name="Emergency Ward",
        x=200, y=200,
    )
    assert response.status_code == 201, response.text
    room = response.json()

    assert room["route_point_id"]
    assert room["route_point_was_reused"] is False

    point = await RoutePoint.get(room["route_point_id"])
    assert point is not None
    assert point.point_type == "room"
    assert point.room_id == room["id"]
    assert point.x == 200
    assert point.y == 200


def test_map_placement_reuses_an_existing_nearby_route_point(client):
    token, _ = create_admin_and_get_token(client, email="dest4@example.com")
    map_item = _create_map(client, token, title="Dest Map 4", campus="Dest Campus 4")

    # A corridor/junction point manually placed first at (300, 300), with
    # NO point_type given (None) — deliberately, for two reasons that both
    # matter here:
    #
    # 1. It must NOT be "room"/"store": the destination data flow feature
    #    (see services/room_sync_service.py) now auto-creates a linked
    #    Room for any "room"/"store" point the instant it's created via
    #    POST /api/route-points. If this point were type "room", it would
    #    already own an auto-created Room ("Junction") by the time
    #    _create_room_on_map() below tries to reuse it for a SECOND,
    #    differently-named Room ("Reused Spot Room") — and that correctly
    #    409s now (see test_map_placement_conflicts_when_reused_point_
    #    belongs_to_another_room for that exact, intentional guard) rather
    #    than the plain reuse this test is actually about. That 409 is not
    #    a bug: RoutePoint.room_id already disagreeing with the new Room's
    #    id is precisely the "two Rooms claiming one physical point" case
    #    Section 5's uniqueness guard exists to catch — see
    #    services/room_sync_service.py's module docstring and
    #    room_routes.py's _place_room_on_map conflict check.
    #
    # 2. It also must NOT be an arbitrary *other* concrete type like
    #    "hallway": _place_room_on_map always dedup-matches with
    #    point_type="room" (see room_routes.py), and point_dedup_service's
    #    find_duplicate_route_point() only reuses a candidate whose
    #    point_type is EITHER unset OR equal to the requested type —
    #    "hallway" vs "room" are treated as two different physical things
    #    and correctly never merged. Only leaving this point's type unset
    #    (None) — matching what "a point manually placed without picking a
    #    type yet" would look like — keeps it eligible for that dedup
    #    match, which is the actual behaviour this test exists to verify.
    existing = _create_point(
        client, token, map_item["id"], "Junction", 300, 300, floor=1, point_type=None
    )

    # Clicking essentially the same spot (well within the server-side
    # dedup tolerance) must reuse it, not create a second RoutePoint.
    response = _create_room_on_map(
        client, token,
        building_id=map_item["building_id"],
        map_id=map_item["id"],
        name="Reused Spot Room",
        x=302, y=301,
    )
    assert response.status_code == 201, response.text
    room = response.json()

    assert room["route_point_id"] == existing["id"]
    assert room["route_point_was_reused"] is True

    all_points_here = client.get(
        f"/api/route-points?map_id={map_item['id']}&floor=1"
    ).json()
    assert len(all_points_here) == 1


def test_map_placement_conflicts_when_reused_point_belongs_to_another_room(client):
    token, _ = create_admin_and_get_token(client, email="dest4b@example.com")
    map_item = _create_map(client, token, title="Dest Map 4b", campus="Dest Campus 4b")

    first = _create_room_on_map(
        client, token,
        building_id=map_item["building_id"],
        map_id=map_item["id"],
        name="First Room",
        x=400, y=400,
    ).json()
    assert first["route_point_id"]

    # A second, different room trying to claim the exact same spot must be
    # rejected rather than silently stealing the first room's RoutePoint.
    second_response = _create_room_on_map(
        client, token,
        building_id=map_item["building_id"],
        map_id=map_item["id"],
        name="Second Room",
        x=401, y=400,
    )
    assert second_response.status_code == 409, second_response.text


# ---------------------------------------------------------
# 5/6/7 — graph connection: valid neighbor, wall-blocked, no duplicate edges
# ---------------------------------------------------------

def test_destination_connects_to_a_valid_nearby_corridor_point(client):
    token, _ = create_admin_and_get_token(client, email="dest5@example.com")
    map_item = _create_map(client, token, title="Dest Map 5", campus="Dest Campus 5")

    corridor = _create_point(
        client, token, map_item["id"], "Corridor", 100, 100, floor=1, point_type="hallway"
    )

    response = _create_room_on_map(
        client, token,
        building_id=map_item["building_id"],
        map_id=map_item["id"],
        name="Nearby Clinic",
        x=140, y=100,
    )
    assert response.status_code == 201, response.text
    room = response.json()

    assert room["route_point_connected"] is True

    edges = client.get(
        f"/api/route-edges?map_id={map_item['id']}",
        headers=auth_headers(token),
    ).json()
    assert len(edges) == 1
    edge = edges[0]
    assert {edge["from_point_id"], edge["to_point_id"]} == {
        corridor["id"], room["route_point_id"]
    }


@pytest.mark.asyncio
async def test_destination_placement_never_connects_across_a_real_wall(client, tmp_path, monkeypatch):
    token, _ = create_admin_and_get_token(client, email="dest6@example.com")
    map_item = _create_map(client, token, title="Dest Map 6", campus="Dest Campus 6")

    corridor = _create_point(
        client, token, map_item["id"], "Corridor6", 50, 150, floor=1, point_type="hallway"
    )

    # A solid vertical wall between x=140 and x=160 — same synthetic-image
    # technique used by the existing has_clear_line wall test.
    image = np.full((300, 300), 255, dtype=np.uint8)
    cv2.rectangle(image, (140, 0), (160, 300), 0, thickness=-1)

    monkeypatch.setattr(
        "services.graph_connection_service.SOURCE_DIR", tmp_path
    )
    cv2.imwrite(str(tmp_path / f"{map_item['id']}.png"), image)

    response = _create_room_on_map(
        client, token,
        building_id=map_item["building_id"],
        map_id=map_item["id"],
        name="Room Behind Wall",
        x=250, y=150,
    )
    assert response.status_code == 201, response.text
    room = response.json()

    # The only candidate neighbor is across the wall — must not connect.
    assert room["route_point_connected"] is False

    edges = client.get(
        f"/api/route-edges?map_id={map_item['id']}",
        headers=auth_headers(token),
    ).json()
    assert len(edges) == 0

    # Sanity check: the corridor point itself is untouched/still there.
    assert corridor["id"]


def test_reusing_an_already_connected_point_does_not_duplicate_edges(client):
    token, _ = create_admin_and_get_token(client, email="dest7@example.com")
    map_item = _create_map(client, token, title="Dest Map 7", campus="Dest Campus 7")

    corridor = _create_point(
        client, token, map_item["id"], "Corridor7", 500, 500, floor=1, point_type="hallway"
    )

    first = _create_room_on_map(
        client, token,
        building_id=map_item["building_id"],
        map_id=map_item["id"],
        name="First Placement",
        x=540, y=500,
    ).json()
    assert first["route_point_connected"] is True

    edges_after_first = client.get(
        f"/api/route-edges?map_id={map_item['id']}",
        headers=auth_headers(token),
    ).json()
    assert len(edges_after_first) == 1

    # Editing the same room again with the same map/x/y (e.g. the admin
    # re-opens and re-saves the destination without moving it) must reuse
    # the same point/edge instead of creating a duplicate.
    update_response = client.put(
        f"/api/rooms/{first['id']}",
        json={"map_id": map_item["id"], "x": 540, "y": 500},
        headers=auth_headers(token),
    )
    assert update_response.status_code == 200, update_response.text
    updated = update_response.json()

    assert updated["route_point_id"] == first["route_point_id"]
    assert updated["route_point_was_reused"] is True
    assert updated["route_point_connected"] is True

    edges_after_second = client.get(
        f"/api/route-edges?map_id={map_item['id']}",
        headers=auth_headers(token),
    ).json()
    assert len(edges_after_second) == 1


# ---------------------------------------------------------
# 8/9 — OCR suggestion: never saves, low confidence stays editable
# ---------------------------------------------------------

def test_ocr_suggest_never_creates_or_modifies_any_room(client):
    token, _ = create_admin_and_get_token(client, email="dest8@example.com")
    map_item = _create_map(client, token, title="Dest Map 8", campus="Dest Campus 8")

    # No source image at all for this map — a common real case (map still
    # processing, or created via the plain JSON endpoint) — the endpoint
    # must degrade gracefully rather than error.
    rooms_before = client.get("/api/rooms").json()
    points_before = client.get("/api/route-points").json()

    response = client.post(
        f"/api/maps/{map_item['id']}/ocr-suggest",
        json={"x": 100, "y": 100},
        headers=auth_headers(token),
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["available"] is False
    assert body["text"] == ""

    rooms_after = client.get("/api/rooms").json()
    points_after = client.get("/api/route-points").json()

    assert rooms_after == rooms_before
    assert points_after == points_before


def test_ocr_suggest_low_confidence_flag_reflects_service_result(client, tmp_path, monkeypatch):
    # Directly exercises ocr_service against a blank (textless) synthetic
    # image — real OCR engine, no mocking of the recognition step itself,
    # but a deterministic "no legible text" case so this test doesn't
    # depend on tesseract actually being installed in every environment.
    fake_map_id = "ocr-test-map"
    blank_image = np.full((400, 400, 3), 255, dtype=np.uint8)

    monkeypatch.setattr(ocr_service, "SOURCE_DIR", tmp_path)
    cv2.imwrite(str(tmp_path / f"{fake_map_id}.png"), blank_image)

    result = ocr_service.suggest_destination_name(fake_map_id, 200, 200)

    # Whether or not tesseract is installed in this environment, a blank
    # image must never produce a confident, ready-to-save suggestion.
    assert result.low_confidence is True
    assert result.confidence < ocr_service.LOW_CONFIDENCE_THRESHOLD

    if not ocr_service.is_ocr_available():
        assert result.available is False
        assert result.text == ""
    else:
        # OCR ran but found nothing legible on a blank image.
        assert result.text == ""


def test_ocr_suggest_out_of_bounds_point_is_handled_safely(tmp_path, monkeypatch):
    fake_map_id = "ocr-bounds-map"
    image = np.full((100, 100, 3), 255, dtype=np.uint8)

    monkeypatch.setattr(ocr_service, "SOURCE_DIR", tmp_path)
    cv2.imwrite(str(tmp_path / f"{fake_map_id}.png"), image)

    # Way outside the 100x100 image.
    result = ocr_service.suggest_destination_name(fake_map_id, 5000, 5000)

    assert result.text == ""
    assert result.low_confidence is True


# ---------------------------------------------------------
# 10/11 — end-user resolution + full navigation
# ---------------------------------------------------------

def test_room_response_route_point_id_resolves_to_the_real_linked_point(client):
    token, _ = create_admin_and_get_token(client, email="dest10@example.com")
    map_item = _create_map(client, token, title="Dest Map 10", campus="Dest Campus 10")

    room = _create_room_on_map(
        client, token,
        building_id=map_item["building_id"],
        map_id=map_item["id"],
        name="Lookup Room",
        x=333, y=444,
    ).json()

    # Simulates exactly what IndoorNavigationScreen.jsx now does: fetch the
    # Room, then fetch the RoutePoint by the id it directly stored — no
    # "first point matching this room_id" search involved.
    fetched_room = client.get(f"/api/rooms/{room['id']}").json()
    point_response = client.get(
        f"/api/route-points/{fetched_room['route_point_id']}"
    )
    assert point_response.status_code == 200
    point = point_response.json()

    assert point["room_id"] == room["id"]
    assert point["map_id"] == map_item["id"]
    assert point["x"] == 333
    assert point["y"] == 444


def test_navigation_from_location_code_start_point_to_destination_succeeds(client):
    token, _ = create_admin_and_get_token(client, email="dest11@example.com")
    map_item = _create_map(client, token, title="Dest Map 11", campus="Dest Campus 11")

    entrance = _create_point(
        client, token, map_item["id"], "Main Entrance", 0, 0, floor=1, point_type="entrance"
    )
    hallway = _create_point(
        client, token, map_item["id"], "Hallway", 100, 0, floor=1, point_type="hallway"
    )
    client.post(
        "/api/route-edges",
        json={
            "map_id": map_item["id"],
            "from_point_id": entrance["id"],
            "to_point_id": hallway["id"],
        },
        headers=auth_headers(token),
    )

    # Destination placed right next to the hallway so auto-connect links
    # the two.
    room = _create_room_on_map(
        client, token,
        building_id=map_item["building_id"],
        map_id=map_item["id"],
        name="Destination Clinic",
        x=140, y=0,
    ).json()
    assert room["route_point_connected"] is True

    code_response = client.post(
        "/api/location-codes/generate",
        json={"route_point_id": entrance["id"]},
        headers=auth_headers(token),
    )
    assert code_response.status_code == 201, code_response.text
    location_code = code_response.json()

    resolved = client.get(f"/api/location-codes/resolve/{location_code['code']}")
    assert resolved.status_code == 200, resolved.text
    resolved_body = resolved.json()
    assert resolved_body["route_point_id"] == entrance["id"]

    route_response = client.post(
        "/api/navigation/route",
        json={
            "map_id": map_item["id"],
            "start_point_id": resolved_body["route_point_id"],
            "end_point_id": room["route_point_id"],
        },
    )
    assert route_response.status_code == 200, route_response.text
    route = route_response.json()

    assert route["path_point_ids"][0] == entrance["id"]
    assert route["path_point_ids"][-1] == room["route_point_id"]
    assert route["total_distance"] > 0
