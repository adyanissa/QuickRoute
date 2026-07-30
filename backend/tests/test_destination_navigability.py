"""
Tests for the normal-user destination availability fix: `is_navigable` /
`navigation_unavailable_reason` on RoomResponse must be computed LIVE from
the actual current RoutePoint/RouteEdge state on every single response
(list/get/create/update alike) — never trusted from the old
`route_point_connected` one-shot signal, which the backend has always
returned as False on a plain GET (see schemas/room_schema.py). That stale
default was the exact bug: Admin correctly reported "CONNECTED TO WALKABLE
GRAPH" right after creating the RouteEdge, but DestinationSelectionScreen's
own GET /api/rooms kept reporting not-connected forever after.

Run with: pytest backend/tests/test_destination_navigability.py -v
"""

import pytest

from tests.test_api_integration import auth_headers, create_admin_and_get_token, _create_map, _create_point

from models.room_model import Room
from models.route_point_model import RoutePoint
from models.route_edge_model import RouteEdge


def _create_room_on_map(client, token, *, building_id, map_id, name, x, y, floor=1):
    return client.post(
        "/api/rooms",
        json={
            "building_id": building_id,
            "name_en": name,
            "room_type": "store",
            "floor": floor,
            "map_id": map_id,
            "x": x,
            "y": y,
        },
        headers=auth_headers(token),
    )


def _create_manual_room(client, token, *, building_id, name):
    return client.post(
        "/api/rooms",
        json={
            "building_id": building_id,
            "name_en": name,
            "room_type": "store",
        },
        headers=auth_headers(token),
    )


# ---------------------------------------------------------
# 1 — a genuinely connected Room returns is_navigable=true
# ---------------------------------------------------------

def test_connected_room_returns_is_navigable_true(client):
    token, _ = create_admin_and_get_token(client, email="nav1@example.com")
    map_item = _create_map(client, token, title="Nav Map 1", campus="Nav Campus 1")

    corridor = _create_point(
        client, token, map_item["id"], "Corridor", 100, 100, floor=1, point_type="hallway"
    )

    created = _create_room_on_map(
        client, token,
        building_id=map_item["building_id"],
        map_id=map_item["id"],
        name="Sakara",
        x=140, y=100,
    )
    assert created.status_code == 201, created.text
    room = created.json()
    assert room["route_point_connected"] is True  # the one-shot create signal
    assert room["is_navigable"] is True
    assert room["navigation_unavailable_reason"] is None

    # The real bug: a PLAIN GET (exactly what DestinationSelectionScreen
    # calls) must ALSO report is_navigable=True — not fall back to the
    # one-shot field's stale False default.
    fetched = client.get(f"/api/rooms/{room['id']}")
    assert fetched.status_code == 200
    fetched_body = fetched.json()
    assert fetched_body["route_point_connected"] is False  # one-shot: always false on GET
    assert fetched_body["is_navigable"] is True  # live: correctly true anyway
    assert fetched_body["navigation_unavailable_reason"] is None

    listed = client.get(f"/api/rooms?building_id={map_item['building_id']}").json()
    listed_room = next(r for r in listed if r["id"] == room["id"])
    assert listed_room["is_navigable"] is True

    assert corridor["id"]  # sanity: the corridor point was real


# ---------------------------------------------------------
# 2 — a Room with no route_point_id returns false
# ---------------------------------------------------------

def test_room_with_no_route_point_returns_false(client):
    token, _ = create_admin_and_get_token(client, email="nav2@example.com")
    building = client.post(
        "/api/locations/buildings",
        json={"name_en": "Nav Building 2"},
        headers=auth_headers(token),
    ).json()

    created = _create_manual_room(client, token, building_id=building["id"], name="Manual Only Room")
    assert created.status_code == 201, created.text
    room = created.json()
    assert room["route_point_id"] is None
    assert room["is_navigable"] is False
    assert room["navigation_unavailable_reason"] == "missing_route_point"

    fetched = client.get(f"/api/rooms/{room['id']}").json()
    assert fetched["is_navigable"] is False
    assert fetched["navigation_unavailable_reason"] == "missing_route_point"


# ---------------------------------------------------------
# 3 — a Room with an isolated (unconnected) RoutePoint returns false
# ---------------------------------------------------------

def test_room_with_isolated_route_point_returns_false(client):
    token, _ = create_admin_and_get_token(client, email="nav3@example.com")
    map_item = _create_map(client, token, title="Nav Map 3", campus="Nav Campus 3")

    # No nearby point at all — auto_connect_point has nothing valid to
    # link to, so the new RoutePoint is created but stays isolated.
    created = _create_room_on_map(
        client, token,
        building_id=map_item["building_id"],
        map_id=map_item["id"],
        name="Isolated Kiosk",
        x=900, y=900,
    )
    assert created.status_code == 201, created.text
    room = created.json()
    assert room["route_point_id"]
    assert room["route_point_connected"] is False

    fetched = client.get(f"/api/rooms/{room['id']}").json()
    assert fetched["is_navigable"] is False
    assert fetched["navigation_unavailable_reason"] == "disconnected_from_graph"


# ---------------------------------------------------------
# 4 — adding an edge changes the NEXT GET response to true
# ---------------------------------------------------------

def test_adding_an_edge_flips_the_next_get_to_navigable(client):
    token, _ = create_admin_and_get_token(client, email="nav4@example.com")
    map_item = _create_map(client, token, title="Nav Map 4", campus="Nav Campus 4")

    isolated = _create_room_on_map(
        client, token,
        building_id=map_item["building_id"],
        map_id=map_item["id"],
        name="Newly Isolated Store",
        x=700, y=700,
    ).json()
    assert isolated["is_navigable"] is False

    before = client.get(f"/api/rooms/{isolated['id']}").json()
    assert before["is_navigable"] is False
    assert before["navigation_unavailable_reason"] == "disconnected_from_graph"

    # A corridor point placed afterwards and manually wired up — exactly
    # what "Draw Walkable Path" in Admin does after the fact. Deliberately
    # created via a raw POST with no `floor` key (rather than the
    # `_create_point` helper, which always sends one) so its floor
    # resolves to the same None this map's own points get (this test map
    # has no explicit floor set) — this isolated room's point already got
    # floor=None the same way, and a walkway edge is only accepted between
    # points the backend considers same-floor.
    corridor_response = client.post(
        "/api/route-points",
        json={
            "map_id": map_item["id"],
            "name": "Late Corridor",
            "x": 720, "y": 700,
            "point_type": "hallway",
        },
        headers=auth_headers(token),
    )
    assert corridor_response.status_code == 201, corridor_response.text
    corridor = corridor_response.json()

    edge_response = client.post(
        "/api/route-edges",
        json={
            "map_id": map_item["id"],
            "from_point_id": isolated["route_point_id"],
            "to_point_id": corridor["id"],
        },
        headers=auth_headers(token),
    )
    assert edge_response.status_code == 201, edge_response.text

    after = client.get(f"/api/rooms/{isolated['id']}").json()
    assert after["is_navigable"] is True
    assert after["navigation_unavailable_reason"] is None

    listed = client.get(f"/api/rooms?building_id={map_item['building_id']}").json()
    listed_room = next(r for r in listed if r["id"] == isolated["id"])
    assert listed_room["is_navigable"] is True


# ---------------------------------------------------------
# 5 — the remaining unavailable reasons: route_point_not_found,
#     inactive_route_point, inactive_destination
# ---------------------------------------------------------

@pytest.mark.asyncio
async def test_route_point_not_found_reason(client):
    token, _ = create_admin_and_get_token(client, email="nav5@example.com")
    building = client.post(
        "/api/locations/buildings",
        json={"name_en": "Nav Building 5"},
        headers=auth_headers(token),
    ).json()

    # Bypasses the normal placement flow entirely to simulate genuinely
    # orphaned data (e.g. a point deleted out-of-band) — the real Room
    # routes never allow a dangling id like this to be created directly.
    room = Room(
        building_id=building["id"],
        name_en="Dangling Reference Room",
        route_point_id="000000000000000000000000",
    )
    await room.insert()

    fetched = client.get(f"/api/rooms/{room.id}").json()
    assert fetched["is_navigable"] is False
    assert fetched["navigation_unavailable_reason"] == "route_point_not_found"


def test_inactive_route_point_reason(client):
    token, _ = create_admin_and_get_token(client, email="nav6@example.com")
    map_item = _create_map(client, token, title="Nav Map 6", campus="Nav Campus 6")

    corridor = _create_point(
        client, token, map_item["id"], "Corridor6", 100, 100, floor=1, point_type="hallway"
    )
    room = _create_room_on_map(
        client, token,
        building_id=map_item["building_id"],
        map_id=map_item["id"],
        name="Deactivatable Room",
        x=140, y=100,
    ).json()
    assert room["is_navigable"] is True

    deactivate = client.put(
        f"/api/route-points/{room['route_point_id']}",
        json={"is_active": False},
        headers=auth_headers(token),
    )
    assert deactivate.status_code == 200, deactivate.text

    fetched = client.get(f"/api/rooms/{room['id']}").json()
    assert fetched["is_navigable"] is False
    assert fetched["navigation_unavailable_reason"] == "inactive_route_point"

    assert corridor["id"]


def test_inactive_destination_reason(client):
    token, _ = create_admin_and_get_token(client, email="nav7@example.com")
    map_item = _create_map(client, token, title="Nav Map 7", campus="Nav Campus 7")

    _create_point(client, token, map_item["id"], "Corridor7", 100, 100, floor=1, point_type="hallway")
    room = _create_room_on_map(
        client, token,
        building_id=map_item["building_id"],
        map_id=map_item["id"],
        name="Room Going Inactive",
        x=140, y=100,
    ).json()
    assert room["is_navigable"] is True

    deactivate = client.put(
        f"/api/rooms/{room['id']}",
        json={"is_active": False},
        headers=auth_headers(token),
    )
    assert deactivate.status_code == 200, deactivate.text
    assert deactivate.json()["is_navigable"] is False
    assert deactivate.json()["navigation_unavailable_reason"] == "inactive_destination"


# ---------------------------------------------------------
# 6 — unrelated-building destinations remain excluded from the filtered
#     list regardless of their own navigability
# ---------------------------------------------------------

def test_unrelated_building_destinations_remain_excluded(client):
    token, _ = create_admin_and_get_token(client, email="nav8@example.com")

    map_a = _create_map(client, token, title="Nav Map 8A", campus="Nav Campus 8A")
    map_b = _create_map(client, token, title="Nav Map 8B", campus="Nav Campus 8B")

    _create_point(client, token, map_a["id"], "Corridor A", 100, 100, floor=1, point_type="hallway")
    _create_point(client, token, map_b["id"], "Corridor B", 100, 100, floor=1, point_type="hallway")

    room_a = _create_room_on_map(
        client, token, building_id=map_a["building_id"], map_id=map_a["id"],
        name="Building A Store", x=140, y=100,
    ).json()
    room_b = _create_room_on_map(
        client, token, building_id=map_b["building_id"], map_id=map_b["id"],
        name="Building B Store", x=140, y=100,
    ).json()
    assert room_a["is_navigable"] is True
    assert room_b["is_navigable"] is True

    listed_for_a = client.get(f"/api/rooms?building_id={map_a['building_id']}").json()
    ids_for_a = {r["id"] for r in listed_for_a}
    assert room_a["id"] in ids_for_a
    assert room_b["id"] not in ids_for_a
