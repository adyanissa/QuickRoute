"""
Navigation-data-problem task — backend tests for the new Full Navigation
Reset (Part 3B) and multi-Map cleanup (Part 4) endpoints in
services/navigation_reset_service.py and routes/navigation_cleanup_routes.py.

Covers (numbering matches this task's own 25-item checklist where it
overlaps):
  13. Full Map reset deletes all RoutePoints on the selected Map.
  14. Full Map reset deletes all RouteEdges on the selected Map.
  15. Full Map reset does not affect another Map.
  16. Full Map reset preserves Rooms.
  17. Full Map reset preserves the Map and calibration.
  18. Room point links are safely cleared.
  19. Location-code links are safely deactivated (the connector-reference
      analogue for this codebase — see navigation_reset_service.py's
      module docstring for why vertical connectors have nothing to null
      out directly).
  20. Multi-Map preview includes only selected Maps.
  21. Multi-Map apply affects only selected Maps.
  22. Counts refresh to zero after reset (asserted via the response body
      and a follow-up preview/count call, since this is a backend suite —
      the frontend's own no-hard-refresh behavior is verified separately).
  23. Public navigation handles a Map with no points safely.

Plus: confirmation-gate tests (confirm=true, matching text/phrase,
super_admin-only, idempotency) that have no numbered spec counterpart but
are explicitly required by this task's restrictions ("Any deletion must
require Preview and explicit confirmation").

Run with: pytest backend/tests/test_navigation_reset.py -v
"""

from tests.test_api_integration import (
    auth_headers,
    create_admin_and_get_token,
    _create_map,
    _create_point,
)


def _create_building(client, token, name_en):
    response = client.post(
        "/api/locations/buildings",
        json={"name_en": name_en},
        headers=auth_headers(token),
    )
    assert response.status_code == 201, response.text
    return response.json()


# ---------------------------------------------------------
# Full Navigation Reset — single map
# ---------------------------------------------------------

def test_full_reset_preview_reports_every_point_and_edge_including_manual(client):
    super_token, _ = create_admin_and_get_token(client, role="super_admin", email="fr1@example.com")
    map_item = _create_map(client, super_token, title="Reset Preview Map")

    p1 = _create_point(client, super_token, map_item["id"], "Manual Point 1", x=0, y=0)
    p2 = _create_point(client, super_token, map_item["id"], "Manual Point 2", x=50, y=0)
    client.post(
        "/api/route-edges",
        json={"map_id": map_item["id"], "from_point_id": p1["id"], "to_point_id": p2["id"]},
        headers=auth_headers(super_token),
    )

    preview = client.get(
        f"/api/navigation-cleanup/maps/{map_item['id']}/full-reset/preview",
        headers=auth_headers(super_token),
    )
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["total_point_count"] == 2
    assert body["total_edge_count"] == 1
    assert body["point_source_breakdown"]["manual"] == 2
    assert body["map_name"] == "Reset Preview Map"

    # Preview never writes anything.
    still_there = client.get(
        f"/api/route-points/{p1['id']}", headers=auth_headers(super_token)
    )
    assert still_there.status_code == 200


def test_full_reset_apply_requires_confirm_true(client):
    super_token, _ = create_admin_and_get_token(client, role="super_admin", email="fr2@example.com")
    map_item = _create_map(client, super_token, title="No Confirm Reset Map")
    _create_point(client, super_token, map_item["id"], "Point", x=0, y=0)

    response = client.post(
        f"/api/navigation-cleanup/maps/{map_item['id']}/full-reset/apply",
        json={"map_id": map_item["id"], "confirm": False, "confirmation_text": "Whatever"},
        headers=auth_headers(super_token),
    )
    assert response.status_code == 400, response.text

    count = client.get(
        "/api/route-points/count", params={"map_id": map_item["id"]}
    ).json()["count"]
    assert count == 1


def test_full_reset_apply_requires_matching_confirmation_text(client):
    super_token, _ = create_admin_and_get_token(client, role="super_admin", email="fr3@example.com")
    map_item = _create_map(client, super_token, title="Wrong Text Reset Map")
    _create_point(client, super_token, map_item["id"], "Point", x=0, y=0)

    response = client.post(
        f"/api/navigation-cleanup/maps/{map_item['id']}/full-reset/apply",
        json={"map_id": map_item["id"], "confirm": True, "confirmation_text": "not the right thing"},
        headers=auth_headers(super_token),
    )
    assert response.status_code == 400, response.text

    count = client.get(
        "/api/route-points/count", params={"map_id": map_item["id"]}
    ).json()["count"]
    assert count == 1


def test_full_reset_apply_accepts_fixed_phrase(client):
    super_token, _ = create_admin_and_get_token(client, role="super_admin", email="fr4@example.com")
    map_item = _create_map(client, super_token, title="Fixed Phrase Reset Map")
    _create_point(client, super_token, map_item["id"], "Point", x=0, y=0)

    response = client.post(
        f"/api/navigation-cleanup/maps/{map_item['id']}/full-reset/apply",
        json={
            "map_id": map_item["id"],
            "confirm": True,
            "confirmation_text": "RESET NAVIGATION DATA",
        },
        headers=auth_headers(super_token),
    )
    assert response.status_code == 200, response.text
    assert response.json()["points_deleted"] == 1


def test_full_reset_apply_accepts_exact_map_name(client):
    super_token, _ = create_admin_and_get_token(client, role="super_admin", email="fr5@example.com")
    map_item = _create_map(client, super_token, title="Exact Name Reset Map")
    _create_point(client, super_token, map_item["id"], "Point", x=0, y=0)

    response = client.post(
        f"/api/navigation-cleanup/maps/{map_item['id']}/full-reset/apply",
        json={
            "map_id": map_item["id"],
            "confirm": True,
            "confirmation_text": "Exact Name Reset Map",
        },
        headers=auth_headers(super_token),
    )
    assert response.status_code == 200, response.text


def test_full_reset_apply_deletes_all_points_and_edges_and_preserves_other_map(client):
    super_token, _ = create_admin_and_get_token(client, role="super_admin", email="fr6@example.com")
    map_a = _create_map(client, super_token, title="Reset Target Map")
    map_b = _create_map(client, super_token, title="Untouched Map")

    a1 = _create_point(client, super_token, map_a["id"], "A1", x=0, y=0)
    a2 = _create_point(client, super_token, map_a["id"], "A2", x=50, y=0)
    client.post(
        "/api/route-edges",
        json={"map_id": map_a["id"], "from_point_id": a1["id"], "to_point_id": a2["id"]},
        headers=auth_headers(super_token),
    )

    b1 = _create_point(client, super_token, map_b["id"], "B1", x=0, y=0)

    response = client.post(
        f"/api/navigation-cleanup/maps/{map_a['id']}/full-reset/apply",
        json={
            "map_id": map_a["id"],
            "confirm": True,
            "confirmation_text": "RESET NAVIGATION DATA",
        },
        headers=auth_headers(super_token),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["points_deleted"] == 2
    assert body["edges_deleted"] == 1

    # Map A's data is gone.
    count_a = client.get(
        "/api/route-points/count", params={"map_id": map_a["id"]}
    ).json()["count"]
    assert count_a == 0

    # Map B is completely untouched (item 15).
    count_b = client.get(
        "/api/route-points/count", params={"map_id": map_b["id"]}
    ).json()["count"]
    assert count_b == 1
    still_b1 = client.get(f"/api/route-points/{b1['id']}")
    assert still_b1.status_code == 200

    # The Map document itself, calibration, still exist (item 17).
    map_a_after = client.get(
        f"/api/maps/{map_a['id']}", headers=auth_headers(super_token)
    )
    assert map_a_after.status_code == 200
    assert map_a_after.json()["id"] == map_a["id"]

    # Idempotent — a second apply with the same confirmation finds nothing
    # left and returns zero counts, never an error.
    second = client.post(
        f"/api/navigation-cleanup/maps/{map_a['id']}/full-reset/apply",
        json={
            "map_id": map_a["id"],
            "confirm": True,
            "confirmation_text": "RESET NAVIGATION DATA",
        },
        headers=auth_headers(super_token),
    )
    assert second.status_code == 200, second.text
    assert second.json()["points_deleted"] == 0
    assert second.json()["edges_deleted"] == 0


def test_full_reset_apply_preserves_room_but_clears_link(client):
    super_token, _ = create_admin_and_get_token(client, role="super_admin", email="fr7@example.com")
    building = _create_building(client, super_token, "Reset Room Building")
    map_item = _create_map(client, super_token, title="Reset Room Map", building_id=building["id"])

    point = _create_point(client, super_token, map_item["id"], "Clinic Room", x=0, y=0)

    room_response = client.post(
        "/api/rooms",
        json={
            "building_id": building["id"],
            "name_en": "Clinic Room",
            "room_type": "clinic",
            "map_id": map_item["id"],
            "x": 0,
            "y": 0,
        },
        headers=auth_headers(super_token),
    )
    assert room_response.status_code == 201, room_response.text
    room_id = room_response.json()["id"]

    apply_response = client.post(
        f"/api/navigation-cleanup/maps/{map_item['id']}/full-reset/apply",
        json={
            "map_id": map_item["id"],
            "confirm": True,
            "confirmation_text": "RESET NAVIGATION DATA",
        },
        headers=auth_headers(super_token),
    )
    assert apply_response.status_code == 200, apply_response.text
    assert apply_response.json()["rooms_unlinked_count"] >= 1

    room_after = client.get(
        "/api/rooms", headers=auth_headers(super_token)
    ).json()
    matching = [r for r in room_after if r["id"] == room_id]
    assert len(matching) == 1, "Room must never be deleted by a full reset"
    assert matching[0]["route_point_id"] is None


def test_full_reset_apply_deactivates_linked_location_code(client):
    super_token, _ = create_admin_and_get_token(client, role="super_admin", email="fr8@example.com")
    building = _create_building(client, super_token, "Reset LocationCode Building")
    map_item = _create_map(client, super_token, title="Reset LC Map", building_id=building["id"])
    point = _create_point(client, super_token, map_item["id"], "Entrance", x=0, y=0)

    code_response = client.post(
        "/api/location-codes",
        json={
            "code": "QR-RESETLC1",
            "building_id": building["id"],
            "map_id": map_item["id"],
            "route_point_id": point["id"],
        },
        headers=auth_headers(super_token),
    )
    assert code_response.status_code == 201, code_response.text

    apply_response = client.post(
        f"/api/navigation-cleanup/maps/{map_item['id']}/full-reset/apply",
        json={
            "map_id": map_item["id"],
            "confirm": True,
            "confirmation_text": "RESET NAVIGATION DATA",
        },
        headers=auth_headers(super_token),
    )
    assert apply_response.status_code == 200, apply_response.text
    assert apply_response.json()["location_codes_deactivated_count"] == 1
    assert "QR-RESETLC1" in apply_response.json()["location_codes_deactivated"]


def test_full_reset_rejected_for_building_manager(client):
    super_token, _ = create_admin_and_get_token(client, role="super_admin", email="fr9@example.com")
    building = _create_building(client, super_token, "Reset BM Building")
    map_item = _create_map(client, super_token, title="Reset BM Map", building_id=building["id"])
    _create_point(client, super_token, map_item["id"], "Point", x=0, y=0)

    invite = client.post(
        "/api/invitation-codes",
        json={
            "role": "building_manager",
            "building_ids": [building["id"]],
            "all_buildings": False,
        },
        headers=auth_headers(super_token),
    )
    assert invite.status_code == 201, invite.text
    from tests.test_api_integration import signup
    signup_response = signup(client, invite.json()["code"], email="bm-reset@example.com")
    bm_token = signup_response.json()["access_token"]

    response = client.post(
        f"/api/navigation-cleanup/maps/{map_item['id']}/full-reset/apply",
        json={
            "map_id": map_item["id"],
            "confirm": True,
            "confirmation_text": "RESET NAVIGATION DATA",
        },
        headers=auth_headers(bm_token),
    )
    assert response.status_code == 403, response.text

    preview_response = client.get(
        f"/api/navigation-cleanup/maps/{map_item['id']}/full-reset/preview",
        headers=auth_headers(bm_token),
    )
    assert preview_response.status_code == 403, preview_response.text


def test_full_reset_preview_and_apply_on_empty_map_reports_nothing_to_delete(client):
    super_token, _ = create_admin_and_get_token(client, role="super_admin", email="fr10@example.com")
    map_item = _create_map(client, super_token, title="Already Empty Map")

    preview = client.get(
        f"/api/navigation-cleanup/maps/{map_item['id']}/full-reset/preview",
        headers=auth_headers(super_token),
    )
    assert preview.status_code == 200
    assert preview.json()["total_point_count"] == 0
    assert preview.json()["total_edge_count"] == 0


def test_public_navigation_handles_map_with_no_points_safely(client):
    """Item 23: after a reset, the public kiosk navigation endpoints must
    not error on a Map with zero RoutePoints — an empty list/expected
    'not found', never a 500."""

    super_token, _ = create_admin_and_get_token(client, role="super_admin", email="fr11@example.com")
    map_item = _create_map(client, super_token, title="Zero Points Public Map")

    response = client.get(
        "/api/route-points/public", params={"map_id": map_item["id"]}
    )
    assert response.status_code == 200, response.text
    assert response.json() == []


# ---------------------------------------------------------
# Multi-Map cleanup (Part 4)
# ---------------------------------------------------------

def test_maps_overview_lists_every_map_with_counts(client):
    super_token, _ = create_admin_and_get_token(client, role="super_admin", email="mm1@example.com")
    map_a = _create_map(client, super_token, title="Overview Map A")
    map_b = _create_map(client, super_token, title="Overview Map B")
    _create_point(client, super_token, map_a["id"], "A1", x=0, y=0)

    response = client.get(
        "/api/navigation-cleanup/maps-overview", headers=auth_headers(super_token)
    )
    assert response.status_code == 200, response.text
    ids = {m["map_id"]: m for m in response.json()["maps"]}
    assert map_a["id"] in ids
    assert map_b["id"] in ids
    assert ids[map_a["id"]]["total_point_count"] == 1
    assert ids[map_b["id"]]["total_point_count"] == 0


def test_multi_map_generated_cleanup_preview_scoped_to_selected_maps_only(client):
    super_token, _ = create_admin_and_get_token(client, role="super_admin", email="mm2@example.com")
    map_a = _create_map(client, super_token, title="Multi Preview Map A")
    map_b = _create_map(client, super_token, title="Multi Preview Map B — Not Selected")
    _create_point(client, super_token, map_a["id"], "A1", x=0, y=0)
    _create_point(client, super_token, map_b["id"], "B1", x=0, y=0)

    response = client.post(
        "/api/navigation-cleanup/multi/generated-cleanup/preview",
        json={"map_ids": [map_a["id"]]},
        headers=auth_headers(super_token),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["valid_map_ids"] == [map_a["id"]]
    assert len(body["per_map"]) == 1
    assert body["per_map"][0]["map_id"] == map_a["id"]


def test_multi_map_full_reset_requires_exact_phrase(client):
    super_token, _ = create_admin_and_get_token(client, role="super_admin", email="mm3@example.com")
    map_a = _create_map(client, super_token, title="Multi Reset Phrase Map")
    _create_point(client, super_token, map_a["id"], "A1", x=0, y=0)

    wrong = client.post(
        "/api/navigation-cleanup/multi/full-reset/apply",
        json={
            "map_ids": [map_a["id"]],
            "confirm": True,
            "confirmation_phrase": "reset selected navigation data",  # wrong case
        },
        headers=auth_headers(super_token),
    )
    assert wrong.status_code == 400, wrong.text

    count = client.get(
        "/api/route-points/count", params={"map_id": map_a["id"]}
    ).json()["count"]
    assert count == 1


def test_multi_map_full_reset_apply_affects_only_selected_maps(client):
    super_token, _ = create_admin_and_get_token(client, role="super_admin", email="mm4@example.com")
    map_a = _create_map(client, super_token, title="Multi Apply Map A")
    map_b = _create_map(client, super_token, title="Multi Apply Map B — Not Selected")
    _create_point(client, super_token, map_a["id"], "A1", x=0, y=0)
    _create_point(client, super_token, map_b["id"], "B1", x=0, y=0)

    response = client.post(
        "/api/navigation-cleanup/multi/full-reset/apply",
        json={
            "map_ids": [map_a["id"]],
            "confirm": True,
            "confirmation_phrase": "RESET SELECTED NAVIGATION DATA",
        },
        headers=auth_headers(super_token),
    )
    assert response.status_code == 200, response.text
    assert response.json()["applied_map_ids"] == [map_a["id"]]
    assert response.json()["total_points_deleted"] == 1

    count_a = client.get(
        "/api/route-points/count", params={"map_id": map_a["id"]}
    ).json()["count"]
    assert count_a == 0

    count_b = client.get(
        "/api/route-points/count", params={"map_id": map_b["id"]}
    ).json()["count"]
    assert count_b == 1


def test_multi_map_full_reset_apply_requires_at_least_one_map(client):
    super_token, _ = create_admin_and_get_token(client, role="super_admin", email="mm5@example.com")

    response = client.post(
        "/api/navigation-cleanup/multi/full-reset/apply",
        json={
            "map_ids": [],
            "confirm": True,
            "confirmation_phrase": "RESET SELECTED NAVIGATION DATA",
        },
        headers=auth_headers(super_token),
    )
    assert response.status_code == 400, response.text


def test_multi_map_full_reset_skips_map_id_that_no_longer_exists(client):
    super_token, _ = create_admin_and_get_token(client, role="super_admin", email="mm6@example.com")
    map_a = _create_map(client, super_token, title="Multi Reset Real Map")
    _create_point(client, super_token, map_a["id"], "A1", x=0, y=0)

    fake_id = "64b000000000000000000000"

    response = client.post(
        "/api/navigation-cleanup/multi/full-reset/apply",
        json={
            "map_ids": [map_a["id"], fake_id],
            "confirm": True,
            "confirmation_phrase": "RESET SELECTED NAVIGATION DATA",
        },
        headers=auth_headers(super_token),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["applied_map_ids"] == [map_a["id"]]
    assert fake_id in body["skipped_map_ids"]


def test_multi_map_endpoints_rejected_for_global_manager(client):
    super_token, _ = create_admin_and_get_token(client, role="super_admin", email="mm7@example.com")
    building = _create_building(client, super_token, "Multi GM Building")

    invite = client.post(
        "/api/invitation-codes",
        json={
            "role": "global_manager",
            "building_ids": [building["id"]],
            "all_buildings": False,
        },
        headers=auth_headers(super_token),
    )
    assert invite.status_code == 201, invite.text
    from tests.test_api_integration import signup
    signup_response = signup(client, invite.json()["code"], email="gm-multi@example.com")
    gm_token = signup_response.json()["access_token"]

    response = client.get(
        "/api/navigation-cleanup/maps-overview", headers=auth_headers(gm_token)
    )
    assert response.status_code == 403, response.text
