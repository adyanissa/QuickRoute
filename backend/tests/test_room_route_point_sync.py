"""
Tests for the destination data flow feature: a destination-capable
RoutePoint (type "room"/"store") automatically gets a linked Room, so an
admin never has to separately open Add Room and re-type the same name.

See services/room_sync_service.py for the actual sync/matching logic and
routes/route_point_routes.py (create/update/delete) + routes/room_routes.py
(sync_rooms_from_route_points) for where it's wired in.

Run with: pytest backend/tests/test_room_route_point_sync.py -v
"""

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


# ---------------------------------------------------------
# 1 — creating a RoutePoint of type room creates one linked Room
# ---------------------------------------------------------

def test_creating_room_point_auto_creates_one_linked_room(client):
    token, _ = create_admin_and_get_token(client, email="sync1@example.com")
    map_item = _create_map(client, token, title="Sync Map 1", campus="Sync Campus 1")

    response = client.post(
        "/api/route-points",
        json={
            "map_id": map_item["id"],
            "name": "Pharmacy Point",
            "point_type": "room",
            "x": 50,
            "y": 60,
            "floor": 1,
            "display_name_en": "Pharmacy",
        },
        headers=auth_headers(token),
    )
    assert response.status_code == 201, response.text
    point = response.json()

    assert point["room_id"]
    assert point["room_sync_action"] == "created"
    assert point["room_sync_warning"] is None

    room_response = client.get(f"/api/rooms/{point['room_id']}", headers=auth_headers(token))
    assert room_response.status_code == 200, room_response.text
    room = room_response.json()

    assert room["name_en"] == "Pharmacy"
    assert room["building_id"] == map_item["building_id"]
    assert room["map_id"] == map_item["id"]
    assert room["floor"] == 1
    assert room["route_point_id"] == point["id"]
    assert room["is_active"] is True

    # Exactly one Room exists for this point — no duplicate.
    all_rooms = client.get(
        f"/api/rooms?building_id={map_item['building_id']}"
    ).json()
    matching = [r for r in all_rooms if r["route_point_id"] == point["id"]]
    assert len(matching) == 1


def test_store_point_also_auto_creates_a_linked_room(client):
    token, _ = create_admin_and_get_token(client, email="sync1b@example.com")
    map_item = _create_map(client, token, title="Sync Map 1b", campus="Sync Campus 1b")

    response = client.post(
        "/api/route-points",
        json={
            "map_id": map_item["id"],
            "name": "Coffee Kiosk",
            "point_type": "store",
            "x": 10,
            "y": 10,
            "floor": 1,
        },
        headers=auth_headers(token),
    )
    assert response.status_code == 201, response.text
    point = response.json()

    assert point["room_id"]
    assert point["room_sync_action"] == "created"


# ---------------------------------------------------------
# 2 — corridor point does not create a Room
# ---------------------------------------------------------

def test_hallway_point_never_creates_a_room(client):
    token, _ = create_admin_and_get_token(client, email="sync2@example.com")
    map_item = _create_map(client, token, title="Sync Map 2", campus="Sync Campus 2")

    point = _create_point(
        client, token, map_item["id"], "Hallway Junction", 100, 100, floor=1, point_type="hallway"
    )

    assert point["room_id"] is None
    assert point["room_sync_action"] == "skipped_non_destination"

    all_rooms = client.get(
        f"/api/rooms?building_id={map_item['building_id']}"
    ).json()
    assert all_rooms == []


# ---------------------------------------------------------
# 3 — stairs/elevator point does not create a Room
# ---------------------------------------------------------

@pytest.mark.parametrize("point_type", ["stairs", "elevator", "entrance", "junction"])
def test_non_destination_point_types_never_create_a_room(client, point_type):
    token, _ = create_admin_and_get_token(
        client, email=f"sync3-{point_type}@example.com"
    )
    map_item = _create_map(
        client, token, title=f"Sync Map 3 {point_type}", campus=f"Sync Campus 3 {point_type}"
    )

    point = _create_point(
        client, token, map_item["id"], f"{point_type} point", 20, 20, floor=1, point_type=point_type
    )

    assert point["room_id"] is None
    assert point["room_sync_action"] == "skipped_non_destination"


# ---------------------------------------------------------
# 4 — repeated save does not duplicate the Room
# ---------------------------------------------------------

@pytest.mark.asyncio
async def test_repeated_update_of_same_point_never_duplicates_the_room(client):
    token, _ = create_admin_and_get_token(client, email="sync4@example.com")
    map_item = _create_map(client, token, title="Sync Map 4", campus="Sync Campus 4")

    created = client.post(
        "/api/route-points",
        json={
            "map_id": map_item["id"],
            "name": "Radiology Point",
            "point_type": "room",
            "x": 30,
            "y": 30,
            "floor": 1,
        },
        headers=auth_headers(token),
    ).json()

    first_room_id = created["room_id"]
    assert first_room_id

    # Re-save the same point twice (e.g. an admin re-opening and re-saving
    # without moving/renaming it) — must never create a second Room.
    for _ in range(2):
        updated = client.put(
            f"/api/route-points/{created['id']}",
            json={"x": 30, "y": 30},
            headers=auth_headers(token),
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["room_id"] == first_room_id

    rooms_for_point = await Room.find(
        {"route_point_id": created["id"]}
    ).to_list()
    assert len(rooms_for_point) == 1


# ---------------------------------------------------------
# 5 — updating multilingual point names updates the linked Room
# ---------------------------------------------------------

def test_updating_point_translations_updates_the_linked_room(client):
    token, _ = create_admin_and_get_token(client, email="sync5@example.com")
    map_item = _create_map(client, token, title="Sync Map 5", campus="Sync Campus 5")

    created = client.post(
        "/api/route-points",
        json={
            "map_id": map_item["id"],
            "name": "Clinic Point",
            "point_type": "room",
            "x": 40,
            "y": 40,
            "floor": 1,
            "display_name_en": "Clinic",
            "display_name_ar": "عيادة",
        },
        headers=auth_headers(token),
    ).json()

    room_before = client.get(f"/api/rooms/{created['room_id']}").json()
    assert room_before["name_en"] == "Clinic"
    assert room_before["names"]["ar"] == "عيادة"
    assert room_before["names"].get("he") in (None, "")

    updated = client.put(
        f"/api/route-points/{created['id']}",
        json={
            "display_name_en": "Clinic (Updated)",
            "display_name_he": "מרפאה",
        },
        headers=auth_headers(token),
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["room_sync_action"] == "updated"

    room_after = client.get(f"/api/rooms/{created['room_id']}").json()
    assert room_after["name_en"] == "Clinic (Updated)"
    assert room_after["names"]["he"] == "מרפאה"
    # Arabic wasn't part of THIS update — must be preserved, never blanked.
    assert room_after["names"]["ar"] == "عيادة"


# ---------------------------------------------------------
# 6 — deactivated destination point is not listed to users
# ---------------------------------------------------------

def test_deactivating_point_deactivates_the_linked_room(client):
    token, _ = create_admin_and_get_token(client, email="sync6@example.com")
    map_item = _create_map(client, token, title="Sync Map 6", campus="Sync Campus 6")

    created = client.post(
        "/api/route-points",
        json={
            "map_id": map_item["id"],
            "name": "Lab Point",
            "point_type": "room",
            "x": 60,
            "y": 60,
            "floor": 1,
        },
        headers=auth_headers(token),
    ).json()

    room_before = client.get(f"/api/rooms/{created['room_id']}").json()
    assert room_before["is_active"] is True

    updated = client.put(
        f"/api/route-points/{created['id']}",
        json={"is_active": False},
        headers=auth_headers(token),
    )
    assert updated.status_code == 200, updated.text

    room_after = client.get(f"/api/rooms/{created['room_id']}").json()
    # This is exactly the existing active/published behaviour
    # DestinationSelectionScreen.jsx already filters the end-user list on
    # (`rooms.filter(r => r.isActive !== false)`) — a deactivated Room is
    # therefore no longer listed to users at all, not merely disabled.
    assert room_after["is_active"] is False


# ---------------------------------------------------------
# 7 — deleted point does not leave a selectable broken Room
# ---------------------------------------------------------

def test_deleting_point_deactivates_rather_than_orphans_the_room(client):
    token, _ = create_admin_and_get_token(client, email="sync7@example.com")
    map_item = _create_map(client, token, title="Sync Map 7", campus="Sync Campus 7")

    created = client.post(
        "/api/route-points",
        json={
            "map_id": map_item["id"],
            "name": "Isolated Room Point",
            "point_type": "room",
            "x": 70,
            "y": 70,
            "floor": 1,
        },
        headers=auth_headers(token),
    ).json()
    room_id = created["room_id"]
    assert room_id

    # No edges reference this point (never connected), so the existing
    # edge-linkage delete guard doesn't block this — exercises the
    # deactivate-before-delete path specifically.
    delete_response = client.delete(
        f"/api/route-points/{created['id']}",
        headers=auth_headers(token),
    )
    assert delete_response.status_code == 200, delete_response.text

    # The point itself is really gone.
    assert client.get(f"/api/route-points/{created['id']}").status_code == 404

    # The Room was soft-deactivated, never hard-deleted, and never left
    # dangling/selectable.
    room_after = client.get(f"/api/rooms/{room_id}").json()
    assert room_after["is_active"] is False
    assert room_after["is_navigable"] is False
    assert room_after["navigation_unavailable_reason"] == "inactive_destination"


# ---------------------------------------------------------
# 8/9 — bulk sync creates Rooms for existing RoutePoints, and is idempotent
# ---------------------------------------------------------

@pytest.mark.asyncio
async def test_bulk_sync_creates_rooms_for_legacy_route_points(client):
    """
    Simulates data that predates this feature: a "room"-type RoutePoint
    inserted directly (bypassing the route handler entirely, the same way
    a point created before this feature shipped would have no linked Room
    at all).
    """
    token, _ = create_admin_and_get_token(client, email="sync8@example.com")
    map_item = _create_map(client, token, title="Sync Map 8", campus="Sync Campus 8")

    legacy_point = RoutePoint(
        map_id=map_item["id"],
        name="Legacy Room Point",
        point_type="room",
        x=80,
        y=80,
        floor=1,
        building_id=map_item["building_id"],
    )
    await legacy_point.insert()
    assert legacy_point.room_id is None

    response = client.post(
        "/api/rooms/sync-from-route-points",
        json={"building_id": map_item["building_id"]},
        headers=auth_headers(token),
    )
    assert response.status_code == 200, response.text
    summary = response.json()

    assert summary["scanned"] == 1
    assert summary["created"] == 1
    assert summary["updated"] == 0
    assert summary["skipped"] == 0
    assert summary["failed"] == 0

    refreshed_point = await RoutePoint.get(legacy_point.id)
    assert refreshed_point.room_id

    linked_room = await Room.get(refreshed_point.room_id)
    assert linked_room is not None
    assert linked_room.route_point_id == str(legacy_point.id)
    assert linked_room.name_en == "Legacy Room Point"


@pytest.mark.asyncio
async def test_bulk_sync_is_idempotent(client):
    token, _ = create_admin_and_get_token(client, email="sync9@example.com")
    map_item = _create_map(client, token, title="Sync Map 9", campus="Sync Campus 9")

    legacy_point = RoutePoint(
        map_id=map_item["id"],
        name="Idempotent Point",
        point_type="room",
        x=90,
        y=90,
        floor=1,
        building_id=map_item["building_id"],
    )
    await legacy_point.insert()

    body = {"building_id": map_item["building_id"]}

    first = client.post(
        "/api/rooms/sync-from-route-points", json=body, headers=auth_headers(token)
    ).json()
    assert first["created"] == 1

    second = client.post(
        "/api/rooms/sync-from-route-points", json=body, headers=auth_headers(token)
    ).json()
    assert second["created"] == 0
    assert second["scanned"] == 1

    all_rooms = await Room.find(
        {"route_point_id": str(legacy_point.id)}
    ).to_list()
    assert len(all_rooms) == 1


# ---------------------------------------------------------
# 10 — ambiguous legacy matches are skipped
# ---------------------------------------------------------

@pytest.mark.asyncio
async def test_bulk_sync_skips_ambiguous_legacy_name_matches(client):
    token, _ = create_admin_and_get_token(client, email="sync10@example.com")
    map_item = _create_map(client, token, title="Sync Map 10", campus="Sync Campus 10")

    legacy_point = RoutePoint(
        map_id=map_item["id"],
        name="Shared Name Point",
        point_type="room",
        display_name_en="Shared Name",
        x=15,
        y=15,
        floor=1,
        building_id=map_item["building_id"],
    )
    await legacy_point.insert()

    # Two pre-existing, completely unlinked Rooms with the exact same
    # normalized name in the same building — genuinely ambiguous, must
    # never be silently merged into one.
    room_a = Room(
        building_id=map_item["building_id"], name_en="Shared Name"
    )
    room_b = Room(
        building_id=map_item["building_id"], name_en="shared name"
    )
    await room_a.insert()
    await room_b.insert()

    response = client.post(
        "/api/rooms/sync-from-route-points",
        json={"building_id": map_item["building_id"]},
        headers=auth_headers(token),
    )
    assert response.status_code == 200, response.text
    summary = response.json()

    assert summary["created"] == 0
    assert summary["skipped"] == 1
    assert len(summary["warnings"]) == 1

    # Neither pre-existing Room was touched/linked.
    refreshed_a = await Room.get(room_a.id)
    refreshed_b = await Room.get(room_b.id)
    assert refreshed_a.route_point_id is None
    assert refreshed_b.route_point_id is None

    refreshed_point = await RoutePoint.get(legacy_point.id)
    assert refreshed_point.room_id is None

    # And no third, guessed Room was created either.
    all_rooms = await Room.find(
        {"building_id": map_item["building_id"]}
    ).to_list()
    assert len(all_rooms) == 2


# ---------------------------------------------------------
# 11 — QR destination list includes synced Rooms from connected floors
# ---------------------------------------------------------

def test_destination_list_includes_rooms_from_multiple_floors_in_same_building(client):
    token, _ = create_admin_and_get_token(client, email="sync11@example.com")

    map_floor1 = _create_map(client, token, title="Sync Map 11 Floor 1", campus="Sync Campus 11")
    building_id = map_floor1["building_id"]
    # Second floor's map, explicitly reusing the SAME building — mirrors a
    # real Map Group's multiple floor maps.
    map_floor2 = _create_map(client, token, title="Sync Map 11 Floor 2", building_id=building_id)

    point_floor1 = client.post(
        "/api/route-points",
        json={
            "map_id": map_floor1["id"],
            "name": "Ground Floor Cafe",
            "point_type": "store",
            "x": 5,
            "y": 5,
            "floor": 0,
        },
        headers=auth_headers(token),
    ).json()

    point_floor2 = client.post(
        "/api/route-points",
        json={
            "map_id": map_floor2["id"],
            "name": "Second Floor Clinic",
            "point_type": "room",
            "x": 5,
            "y": 5,
            "floor": 1,
        },
        headers=auth_headers(token),
    ).json()

    assert point_floor1["room_id"] and point_floor2["room_id"]

    destinations = client.get(f"/api/rooms?building_id={building_id}").json()
    destination_route_point_ids = {r["route_point_id"] for r in destinations}

    assert point_floor1["id"] in destination_route_point_ids
    assert point_floor2["id"] in destination_route_point_ids

    # A purely technical/corridor point must never show up as a
    # destination, on any floor.
    hallway_point = _create_point(
        client, token, map_floor1["id"], "Some Hallway", 1, 1, floor=0, point_type="hallway"
    )
    destinations_after = client.get(f"/api/rooms?building_id={building_id}").json()
    assert all(
        r["route_point_id"] != hallway_point["id"] for r in destinations_after
    )


# ---------------------------------------------------------
# 12 — Dijkstra and route graph tests remain unchanged and pass
# ---------------------------------------------------------

def test_navigation_still_computes_a_correct_route_through_an_auto_linked_room(client):
    """
    Regression sentinel: creating a destination via a "room"-type
    RoutePoint (the new flow) still connects to and routes through the
    walkable graph exactly like the pre-existing Room-first placement flow
    already tested in test_destination_placement.py — this feature never
    touches Dijkstra, edge weights, or path selection.
    """
    token, _ = create_admin_and_get_token(client, email="sync12@example.com")
    map_item = _create_map(client, token, title="Sync Map 12", campus="Sync Campus 12")

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

    room_point = client.post(
        "/api/route-points",
        json={
            "map_id": map_item["id"],
            "name": "Destination Room Point",
            "point_type": "room",
            "x": 140,
            "y": 0,
            "floor": 1,
        },
        headers=auth_headers(token),
    ).json()
    assert room_point["room_id"]

    client.post(
        "/api/route-edges",
        json={
            "map_id": map_item["id"],
            "from_point_id": hallway["id"],
            "to_point_id": room_point["id"],
        },
        headers=auth_headers(token),
    )

    route_response = client.post(
        "/api/navigation/route",
        json={
            "map_id": map_item["id"],
            "start_point_id": entrance["id"],
            "end_point_id": room_point["id"],
        },
    )
    assert route_response.status_code == 200, route_response.text
    route = route_response.json()

    assert route["path_point_ids"][0] == entrance["id"]
    assert route["path_point_ids"][-1] == room_point["id"]
    assert route["total_distance"] > 0
