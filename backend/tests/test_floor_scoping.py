"""
Floor isolation: one Map IS one floor, and every floor-scoped query must
return only that map's data.

The reported symptom: a building whose Ground Floor had ~8 rooms/codes and
whose upper floor had ~27 showed all 35 while the admin was looking at the
Ground Floor, which reads as "the other floor replaced my codes".

Nothing was ever replaced. This file pins down both halves of that:

  1. the READ path can now actually be scoped — GET /api/rooms accepts
     map_id, which is the only exact floor scope (`floor` alone is
     ambiguous when a building holds two maps for one floor number);

  2. the WRITE paths never touch another floor — creating rooms and codes
     on one map leaves every other map's rooms, codes and route points
     byte-for-byte unchanged, including their is_active flags.

Run with: pytest backend/tests/test_floor_scoping.py -v
"""

import pytest

from tests.test_api_integration import auth_headers, create_admin_and_get_token

from models.location_code_model import LocationCode
from models.room_model import Room


# ---------------------------------------------------------
# Helpers (local copies, matching the established per-file convention).
# ---------------------------------------------------------

def _create_building(client, token, name):
    response = client.post(
        "/api/locations/buildings",
        json={"name_en": name},
        headers=auth_headers(token),
    )
    assert response.status_code == 201, response.text
    return response.json()


def _create_map(client, token, title, building_id=None, floor=0):
    payload = {"title": title, "floor": floor}
    if building_id:
        payload["building_id"] = building_id
    response = client.post("/api/maps", json=payload, headers=auth_headers(token))
    assert response.status_code == 201, response.text
    return response.json()


def _create_point(client, token, map_id, name, x, y, floor=0, point_type="hallway"):
    response = client.post(
        "/api/route-points",
        json={
            "map_id": map_id,
            "name": name,
            "x": x,
            "y": y,
            "floor": floor,
            "point_type": point_type,
        },
        headers=auth_headers(token),
    )
    assert response.status_code == 201, response.text
    return response.json()


def _create_edge(client, token, map_id, a, b):
    response = client.post(
        "/api/route-edges",
        json={
            "map_id": map_id,
            "from_point_id": a,
            "to_point_id": b,
            "edge_type": "walkway",
        },
        headers=auth_headers(token),
    )
    assert response.status_code == 201, response.text
    return response.json()


def _create_room_on_map(client, token, building_id, map_id, name, x, y, floor=0):
    response = client.post(
        "/api/rooms",
        json={
            "building_id": building_id,
            "name_en": name,
            "room_type": "room",
            "floor": floor,
            "map_id": map_id,
            "x": x,
            "y": y,
        },
        headers=auth_headers(token),
    )
    assert response.status_code == 201, response.text
    return response.json()


def _get_rooms(client, token, **filters):
    response = client.get(
        "/api/rooms", params=filters, headers=auth_headers(token)
    )
    assert response.status_code == 200, response.text
    return response.json()


def _get_codes(client, token, **filters):
    response = client.get(
        "/api/location-codes", params=filters, headers=auth_headers(token)
    )
    assert response.status_code == 200, response.text
    return response.json()


def _two_floor_building(client, token, label):
    """One building, two floor maps, each with its own corridor and one
    connected room — the smallest shape that can leak."""
    building = _create_building(client, token, f"{label} Building")

    ground = _create_map(client, token, f"{label} Ground", building["id"], floor=0)
    upper = _create_map(client, token, f"{label} Floor 1", building["id"], floor=1)

    for map_item, floor in ((ground, 0), (upper, 1)):
        hall_a = _create_point(
            client, token, map_item["id"], "Hall A", 100, 100, floor=floor
        )
        hall_b = _create_point(
            client, token, map_item["id"], "Hall B", 400, 100, floor=floor
        )
        _create_edge(client, token, map_item["id"], hall_a["id"], hall_b["id"])

    return building, ground, upper


# =========================================================
# 1. Rooms are scoped to one map.
# =========================================================

def test_rooms_can_be_scoped_to_exactly_one_floor_map(client):
    token, _ = create_admin_and_get_token(client, email="fs1@example.com")
    building, ground, upper = _two_floor_building(client, token, "FS1")

    _create_room_on_map(
        client, token, building["id"], ground["id"], "Ground Room", 110, 160, floor=0
    )
    _create_room_on_map(
        client, token, building["id"], upper["id"], "Upper Room A", 110, 160, floor=1
    )
    _create_room_on_map(
        client, token, building["id"], upper["id"], "Upper Room B", 210, 160, floor=1
    )

    ground_rooms = _get_rooms(client, token, map_id=ground["id"])
    upper_rooms = _get_rooms(client, token, map_id=upper["id"])

    assert [r["name_en"] for r in ground_rooms] == ["Ground Room"]
    assert sorted(r["name_en"] for r in upper_rooms) == [
        "Upper Room A",
        "Upper Room B",
    ]

    # Every returned room really does belong to the requested map.
    assert all(r["map_id"] == ground["id"] for r in ground_rooms)
    assert all(r["map_id"] == upper["id"] for r in upper_rooms)


def test_unscoped_room_listing_still_returns_the_building(client):
    # The filter is additive: an existing caller that passes no map_id
    # keeps the behaviour it had.
    token, _ = create_admin_and_get_token(client, email="fs2@example.com")
    building, ground, upper = _two_floor_building(client, token, "FS2")

    _create_room_on_map(
        client, token, building["id"], ground["id"], "Ground", 110, 160, floor=0
    )
    _create_room_on_map(
        client, token, building["id"], upper["id"], "Upper", 110, 160, floor=1
    )

    all_rooms = _get_rooms(client, token, building_id=building["id"])
    assert len(all_rooms) == 2


def test_map_id_scope_beats_an_ambiguous_floor_number(client):
    # Two maps for the SAME floor number in one building — a superseded
    # upload, or two wings. `floor` cannot tell them apart; map_id can.
    token, _ = create_admin_and_get_token(client, email="fs3@example.com")
    building = _create_building(client, token, "FS3 Building")

    old_map = _create_map(client, token, "FS3 Ground (old)", building["id"], floor=0)
    new_map = _create_map(client, token, "FS3 Ground (new)", building["id"], floor=0)

    _create_room_on_map(
        client, token, building["id"], old_map["id"], "Old Upload Room", 100, 100
    )
    _create_room_on_map(
        client, token, building["id"], new_map["id"], "New Upload Room", 100, 100
    )

    by_floor = _get_rooms(client, token, building_id=building["id"], floor=0)
    assert len(by_floor) == 2, "floor alone cannot disambiguate two maps"

    by_map = _get_rooms(client, token, map_id=new_map["id"])
    assert [r["name_en"] for r in by_map] == ["New Upload Room"]


# =========================================================
# 2. Location codes are scoped to one map.
# =========================================================

@pytest.mark.asyncio
async def test_location_codes_are_scoped_to_one_floor_map(client):
    token, _ = create_admin_and_get_token(client, email="fs4@example.com")
    building, ground, upper = _two_floor_building(client, token, "FS4")

    _create_room_on_map(
        client, token, building["id"], ground["id"], "Ground Room", 110, 160, floor=0
    )
    for index in range(3):
        _create_room_on_map(
            client, token, building["id"], upper["id"],
            f"Upper Room {index}", 110 + index * 30, 160, floor=1,
        )

    # Issue codes for each floor independently, exactly as an apply does.
    from services.room_location_code_service import ensure_room_location_codes

    await ensure_room_location_codes(ground["id"])
    await ensure_room_location_codes(upper["id"])

    ground_codes = _get_codes(client, token, map_id=ground["id"])
    upper_codes = _get_codes(client, token, map_id=upper["id"])

    assert len(ground_codes) >= 1
    assert all(c["map_id"] == ground["id"] for c in ground_codes)
    assert all(c["map_id"] == upper["id"] for c in upper_codes)

    ground_ids = {c["id"] for c in ground_codes}
    upper_ids = {c["id"] for c in upper_codes}
    assert ground_ids.isdisjoint(upper_ids)


# =========================================================
# 3. Creating one floor's data never disturbs another floor's.
# =========================================================

@pytest.mark.asyncio
async def test_creating_upper_floor_codes_leaves_ground_floor_codes_untouched(client):
    # The exact reported fear: "creating Floor 2 rooms must not affect
    # Floor 1 QR codes."
    token, _ = create_admin_and_get_token(client, email="fs5@example.com")
    building, ground, upper = _two_floor_building(client, token, "FS5")

    _create_room_on_map(
        client, token, building["id"], ground["id"], "Ground Room", 110, 160, floor=0
    )

    from services.room_location_code_service import ensure_room_location_codes

    await ensure_room_location_codes(ground["id"])

    before = await LocationCode.find({"map_id": ground["id"]}).to_list()
    assert before, "the ground floor should have a code to protect"
    snapshot = {
        str(c.id): (c.code, c.route_point_id, c.map_id, c.building_id, c.is_active)
        for c in before
    }

    # Now build out the whole upper floor and issue its codes.
    for index in range(5):
        _create_room_on_map(
            client, token, building["id"], upper["id"],
            f"Upper Room {index}", 110 + index * 30, 160, floor=1,
        )
    await ensure_room_location_codes(upper["id"])

    after = await LocationCode.find({"map_id": ground["id"]}).to_list()
    assert {
        str(c.id): (c.code, c.route_point_id, c.map_id, c.building_id, c.is_active)
        for c in after
    } == snapshot

    # ...and specifically nothing was deactivated.
    assert all(c.is_active for c in after)


@pytest.mark.asyncio
async def test_issuing_codes_for_one_map_never_reassigns_another_maps_rooms(client):
    token, _ = create_admin_and_get_token(client, email="fs6@example.com")
    building, ground, upper = _two_floor_building(client, token, "FS6")

    ground_room = _create_room_on_map(
        client, token, building["id"], ground["id"], "Ground Room", 110, 160, floor=0
    )
    _create_room_on_map(
        client, token, building["id"], upper["id"], "Upper Room", 110, 160, floor=1
    )

    stored = await Room.get(ground_room["id"])
    before = (stored.map_id, stored.route_point_id, stored.floor, stored.is_active)

    from services.room_location_code_service import ensure_room_location_codes

    await ensure_room_location_codes(upper["id"])

    stored_after = await Room.get(ground_room["id"])
    assert (
        stored_after.map_id,
        stored_after.route_point_id,
        stored_after.floor,
        stored_after.is_active,
    ) == before


def test_two_buildings_stay_isolated(client):
    token, _ = create_admin_and_get_token(client, email="fs7@example.com")

    building_a, ground_a, _ = _two_floor_building(client, token, "FS7A")
    building_b, ground_b, _ = _two_floor_building(client, token, "FS7B")

    _create_room_on_map(
        client, token, building_a["id"], ground_a["id"], "A Room", 110, 160
    )
    _create_room_on_map(
        client, token, building_b["id"], ground_b["id"], "B Room", 110, 160
    )

    assert [r["name_en"] for r in _get_rooms(client, token, map_id=ground_a["id"])] == [
        "A Room"
    ]
    assert [r["name_en"] for r in _get_rooms(client, token, map_id=ground_b["id"])] == [
        "B Room"
    ]


# =========================================================
# 4. One authoritative connected-status, shared by every surface.
# =========================================================

@pytest.mark.asyncio
async def test_rooms_page_and_auto_connect_agree_on_connected(client):
    # The reported mismatch: Auto Connect said "already connected: 7" while
    # the Rooms page showed several of those as having no valid graph
    # connection. Both now ask services/graph_connectivity_service.
    token, _ = create_admin_and_get_token(client, email="fs8@example.com")
    building, ground, _ = _two_floor_building(client, token, "FS8")

    room = _create_room_on_map(
        client, token, building["id"], ground["id"], "Connected Room", 110, 160
    )

    preview = client.post(
        "/api/route-edges/auto-connect-destinations/preview",
        json={"map_id": ground["id"]},
        headers=auth_headers(token),
    )
    assert preview.status_code == 200, preview.text
    result = preview.json()

    fetched = client.get(f"/api/rooms/{room['id']}").json()

    proposal = next(
        (
            p
            for p in result["proposals"]
            if p["destination_point_id"] == fetched["route_point_id"]
        ),
        None,
    )

    if proposal is None:
        # Auto Connect skipped it as already connected — the Rooms page
        # must agree.
        assert result["summary"]["already_connected"] >= 1
        assert fetched["is_navigable"] is True
    else:
        # Auto Connect wants to connect it — the Rooms page must NOT be
        # calling it navigable.
        assert fetched["is_navigable"] is False


@pytest.mark.asyncio
async def test_a_room_attached_only_to_another_room_is_not_called_navigable(client):
    # Legacy data shape: a stale Room-to-Room walkway edge. It used to
    # satisfy "has any active edge", so the room was advertised as
    # navigable and issued a QR, and then produced no route.
    token, _ = create_admin_and_get_token(client, email="fs9@example.com")
    building, ground, _ = _two_floor_building(client, token, "FS9")

    room_a = _create_room_on_map(
        client, token, building["id"], ground["id"], "Room A", 800, 800
    )
    room_b = _create_room_on_map(
        client, token, building["id"], ground["id"], "Room B", 860, 800
    )

    fetched_a = client.get(f"/api/rooms/{room_a['id']}").json()
    fetched_b = client.get(f"/api/rooms/{room_b['id']}").json()

    _create_edge(
        client, token, ground["id"],
        fetched_a["route_point_id"], fetched_b["route_point_id"],
    )

    after = client.get(f"/api/rooms/{room_a['id']}").json()

    assert after["is_navigable"] is False
    assert after["navigation_unavailable_reason"] == "only_invalid_edges"


@pytest.mark.asyncio
async def test_a_room_attached_only_to_another_room_gets_no_qr(client):
    token, _ = create_admin_and_get_token(client, email="fs10@example.com")
    building, ground, _ = _two_floor_building(client, token, "FS10")

    room_a = _create_room_on_map(
        client, token, building["id"], ground["id"], "Room A", 800, 800
    )
    room_b = _create_room_on_map(
        client, token, building["id"], ground["id"], "Room B", 860, 800
    )
    fetched_a = client.get(f"/api/rooms/{room_a['id']}").json()
    fetched_b = client.get(f"/api/rooms/{room_b['id']}").json()
    _create_edge(
        client, token, ground["id"],
        fetched_a["route_point_id"], fetched_b["route_point_id"],
    )

    from services.room_location_code_service import ensure_room_location_codes

    summary = await ensure_room_location_codes(ground["id"])

    # Neither room is reachable, so neither is issued a code.
    assert summary["qr_codes_created"] == 0
    assert summary["rooms_unconnected"] >= 2
