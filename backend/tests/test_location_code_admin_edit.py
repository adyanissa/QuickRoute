"""
Tests for:
  1. The Location Code floor-authoritative fix — resolve_location_code and
     the admin LocationCodeResponse must both prefer Map.floor over a
     possibly-stale/null RoutePoint.floor, exactly like the existing
     RoutePoint/RouteEdge "Map.floor is authoritative" rule elsewhere in
     this codebase. This is the actual root cause behind "the code card
     says Floor 1 but Current floor: — on the user navigation screen".
  2. The Admin Location Codes "Edit" action's backend contract —
     PUT /api/location-codes/{id} reassigning building_id/map_id/
     route_point_id/label/is_active, including the exact "Main Entrance
     QR reassigned to a different connected RoutePoint on the same floor
     map" scenario.

Run with: pytest backend/tests/test_location_code_admin_edit.py -v
"""

import pytest

from tests.test_api_integration import auth_headers, create_admin_and_get_token

from models.route_point_model import RoutePoint


def _create_building(client, token, name="Nav Location Building"):
    response = client.post(
        "/api/locations/buildings",
        json={"name_en": name},
        headers=auth_headers(token),
    )
    assert response.status_code == 201, response.text
    return response.json()


def _create_map_with_floor(client, token, *, title, building_id, floor):
    response = client.post(
        "/api/maps",
        json={"title": title, "building_id": building_id, "floor": floor},
        headers=auth_headers(token),
    )
    assert response.status_code == 201, response.text
    return response.json()


def _create_active_point(client, token, *, map_id, name, x=10, y=10, point_type="entrance"):
    response = client.post(
        "/api/route-points",
        json={"map_id": map_id, "name": name, "x": x, "y": y, "point_type": point_type},
        headers=auth_headers(token),
    )
    assert response.status_code == 201, response.text
    return response.json()


# ---------------------------------------------------------
# 1 — Map.floor is authoritative for a Location Code's resolved floor
# ---------------------------------------------------------

@pytest.mark.asyncio
async def test_resolve_prefers_map_floor_over_a_stale_null_route_point_floor(client):
    """
    The exact repro: RoutePoint.floor is None (a legacy/never-backfilled
    point) while its Map.floor is correctly 1 — the resolve endpoint must
    still report floor=1, matching what the admin list already showed via
    its own `entry.floor ?? map?.floor` fallback, instead of leaving the
    end-user "Current floor" blank.
    """
    token, _ = create_admin_and_get_token(client, email="loc-floor1@example.com")
    building = _create_building(client, token)
    map_item = _create_map_with_floor(
        client, token, title="QuickRoute Mall - Floor 1", building_id=building["id"], floor=1
    )

    # Bypasses the normal create-route-point endpoint (which would force
    # floor to match the map) to simulate genuinely stale legacy data: a
    # RoutePoint whose own `floor` was never backfilled.
    point = RoutePoint(
        map_id=map_item["id"],
        name="Main Entrance",
        point_type="entrance",
        x=10, y=10,
        floor=None,
        building_id=building["id"],
    )
    await point.insert()

    code_response = client.post(
        "/api/location-codes",
        json={
            "code": "QR-MAIN-FLOOR-TEST",
            "building_id": building["id"],
            "map_id": map_item["id"],
            "route_point_id": str(point.id),
            "label": "Main Entrance",
        },
        headers=auth_headers(token),
    )
    assert code_response.status_code == 201, code_response.text
    created = code_response.json()
    # Even the create response itself must already report the correct,
    # authoritative floor — not wait for a later GET/resolve.
    assert created["floor"] == 1

    resolved = client.get("/api/location-codes/resolve/QR-MAIN-FLOOR-TEST")
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["floor"] == 1
    assert resolved.json()["map_id"] == map_item["id"]
    assert resolved.json()["route_point_id"] == str(point.id)
    assert resolved.json()["building_id"] == building["id"]

    # The admin list/get response uses the exact same shared derivation.
    listed = client.get(
        f"/api/location-codes?building_id={building['id']}",
        headers=auth_headers(token),
    ).json()
    listed_entry = next(c for c in listed if c["code"] == "QR-MAIN-FLOOR-TEST")
    assert listed_entry["floor"] == 1


@pytest.mark.asyncio
async def test_resolve_falls_back_to_route_point_floor_when_map_has_no_floor(client):
    """
    A legacy, ungrouped Map that predates floor tracking entirely
    (Map.floor is None) — there is nothing authoritative to prefer, so
    the RoutePoint's own floor is used, exactly as before this fix.
    """
    token, _ = create_admin_and_get_token(client, email="loc-floor2@example.com")
    building = _create_building(client, token)

    # No floor passed — this map genuinely has none recorded.
    map_response = client.post(
        "/api/maps",
        json={"title": "Legacy Ungrouped Map", "building_id": building["id"]},
        headers=auth_headers(token),
    )
    assert map_response.status_code == 201, map_response.text
    map_item = map_response.json()
    assert map_item["floor"] is None

    point = RoutePoint(
        map_id=map_item["id"], name="Legacy Entrance", point_type="entrance",
        x=5, y=5, floor=2, building_id=building["id"],
    )
    await point.insert()

    code_response = client.post(
        "/api/location-codes",
        json={
            "code": "QR-LEGACY-FLOOR-TEST",
            "building_id": building["id"],
            "map_id": map_item["id"],
            "route_point_id": str(point.id),
        },
        headers=auth_headers(token),
    )
    assert code_response.status_code == 201, code_response.text
    assert code_response.json()["floor"] == 2

    resolved = client.get("/api/location-codes/resolve/QR-LEGACY-FLOOR-TEST").json()
    assert resolved["floor"] == 2


# ---------------------------------------------------------
# 2 — Admin Edit action backend contract (PUT /api/location-codes/{id})
# ---------------------------------------------------------

def test_edit_reassigns_main_entrance_qr_to_a_different_connected_point_on_the_same_map(client):
    """
    The exact "Main Entrance QR reassignment" scenario: an admin verifies
    the code and reassigns it to the real, currently-connected Main
    Entrance RoutePoint on QuickRoute Mall - Floor 1 — a different point
    on the SAME map, via the Edit action's PUT call.
    """
    token, _ = create_admin_and_get_token(client, email="loc-edit1@example.com")
    building = _create_building(client, token)
    map_item = _create_map_with_floor(
        client, token, title="QuickRoute Mall - Floor 1", building_id=building["id"], floor=1
    )

    stale_point = _create_active_point(client, token, map_id=map_item["id"], name="Old Entrance Point", x=1, y=1)
    real_point = _create_active_point(client, token, map_id=map_item["id"], name="Main Entrance (Connected)", x=50, y=50)

    created = client.post(
        "/api/location-codes",
        json={
            "code": "QR-MAIN-ENTRANCE",
            "building_id": building["id"],
            "map_id": map_item["id"],
            "route_point_id": stale_point["id"],
            "label": "Main Entrance",
        },
        headers=auth_headers(token),
    ).json()
    assert created["route_point_id"] == stale_point["id"]

    edit_response = client.put(
        f"/api/location-codes/{created['id']}",
        json={"route_point_id": real_point["id"]},
        headers=auth_headers(token),
    )
    assert edit_response.status_code == 200, edit_response.text
    edited = edit_response.json()
    assert edited["route_point_id"] == real_point["id"]
    assert edited["map_id"] == map_item["id"]
    assert edited["building_id"] == building["id"]
    assert edited["floor"] == 1

    # And it round-trips through the public resolve endpoint too — the
    # normal-user flow immediately sees the reassignment.
    resolved = client.get("/api/location-codes/resolve/QR-MAIN-ENTRANCE").json()
    assert resolved["route_point_id"] == real_point["id"]
    assert resolved["floor"] == 1


def test_edit_updates_label_and_active_status_independently(client):
    token, _ = create_admin_and_get_token(client, email="loc-edit2@example.com")
    building = _create_building(client, token)
    map_item = _create_map_with_floor(client, token, title="Edit Map", building_id=building["id"], floor=0)
    point = _create_active_point(client, token, map_id=map_item["id"], name="Entrance")

    created = client.post(
        "/api/location-codes",
        json={
            "code": "QR-LABEL-TEST",
            "building_id": building["id"],
            "map_id": map_item["id"],
            "route_point_id": point["id"],
            "label": "Old Label",
        },
        headers=auth_headers(token),
    ).json()
    assert created["is_active"] is True

    edited = client.put(
        f"/api/location-codes/{created['id']}",
        json={"label": "New Label", "is_active": False},
        headers=auth_headers(token),
    )
    assert edited.status_code == 200, edited.text
    body = edited.json()
    assert body["label"] == "New Label"
    assert body["is_active"] is False
    # Reassignment fields untouched by an edit that didn't send them.
    assert body["route_point_id"] == point["id"]
    assert body["map_id"] == map_item["id"]


def test_edit_rejects_reassigning_to_a_point_on_a_different_map(client):
    token, _ = create_admin_and_get_token(client, email="loc-edit3@example.com")
    building = _create_building(client, token)
    map_a = _create_map_with_floor(client, token, title="Map A", building_id=building["id"], floor=0)
    map_b = _create_map_with_floor(client, token, title="Map B", building_id=building["id"], floor=1)

    point_a = _create_active_point(client, token, map_id=map_a["id"], name="Entrance A")
    point_b = _create_active_point(client, token, map_id=map_b["id"], name="Entrance B")

    created = client.post(
        "/api/location-codes",
        json={
            "code": "QR-MISMATCH-TEST",
            "building_id": building["id"],
            "map_id": map_a["id"],
            "route_point_id": point_a["id"],
        },
        headers=auth_headers(token),
    ).json()

    # Sending map_id unchanged (still map_a) but a route_point_id that
    # actually belongs to map_b must be rejected — never silently saved.
    edit_response = client.put(
        f"/api/location-codes/{created['id']}",
        json={"route_point_id": point_b["id"]},
        headers=auth_headers(token),
    )
    assert edit_response.status_code == 400, edit_response.text

    unchanged = client.get(
        f"/api/location-codes/{created['id']}", headers=auth_headers(token)
    ).json()
    assert unchanged["route_point_id"] == point_a["id"]


def test_edit_does_not_write_anything_until_the_put_request_is_actually_sent(client):
    """
    Sanity check for "do not modify MongoDB data until the admin
    explicitly presses Save": merely fetching/inspecting a code (GET) must
    never itself mutate updated_at or any field.
    """
    token, _ = create_admin_and_get_token(client, email="loc-edit4@example.com")
    building = _create_building(client, token)
    map_item = _create_map_with_floor(client, token, title="No-op Map", building_id=building["id"], floor=0)
    point = _create_active_point(client, token, map_id=map_item["id"], name="Entrance")

    created = client.post(
        "/api/location-codes",
        json={
            "code": "QR-NOOP-TEST",
            "building_id": building["id"],
            "map_id": map_item["id"],
            "route_point_id": point["id"],
        },
        headers=auth_headers(token),
    ).json()

    before = client.get(
        f"/api/location-codes/{created['id']}", headers=auth_headers(token)
    ).json()
    again = client.get(
        f"/api/location-codes/{created['id']}", headers=auth_headers(token)
    ).json()
    assert before == again
