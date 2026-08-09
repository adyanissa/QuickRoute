"""
RBAC/dashboard cleanup task (Request 3, Phases 3, 6, 9) — backend tests for:

  - GET /api/route-points/public and GET /api/route-points/public/{id}
    (the new, minimal-field, unauthenticated navigation endpoints that
    IndoorNavigationScreen.jsx now calls instead of the admin
    GET /api/route-points / GET /api/route-points/{id} endpoints).
  - POST /api/route-points/bulk-delete/preview and .../apply (the new
    all-or-nothing bulk-delete workflow).
  - GET /api/locations/buildings and GET /api/rooms now narrowing their
    result to the authenticated admin's accessible buildings, while
    staying fully open (unchanged) for anonymous/regular_user callers.

Uses the same in-memory mongomock TestClient fixtures as
test_api_integration.py / test_rbac_scope_authorization.py (see
conftest.py) — no real MongoDB is ever touched.

Run with: pytest backend/tests/test_route_point_public_and_bulk_delete.py -v

NOTE: written but NOT executed in this session — the sandbox's isolated
Linux environment was unavailable for every tool call attempted (see the
final report). Do not treat this file as "passing" until it has actually
been run.
"""

from tests.test_api_integration import (
    auth_headers,
    create_admin_and_get_token,
    make_invitation_code,
    signup,
)


def _create_building(client, token, name_en):
    response = client.post(
        "/api/locations/buildings",
        json={"name_en": name_en},
        headers=auth_headers(token),
    )
    assert response.status_code == 201, response.text
    return response.json()


def _create_map_for_building(client, token, building_id, title="Scoped Map"):
    response = client.post(
        "/api/maps",
        json={"title": title, "building_id": building_id},
        headers=auth_headers(token),
    )
    assert response.status_code == 201, response.text
    return response.json()


def _create_point(client, token, map_id, name, x=0, y=0, building_id=None):
    payload = {"map_id": map_id, "name": name, "x": x, "y": y, "floor": 0}
    if building_id:
        payload["building_id"] = building_id
    response = client.post(
        "/api/route-points",
        json=payload,
        headers=auth_headers(token),
    )
    assert response.status_code == 201, response.text
    return response.json()


def _signup_with_invite(client, creator_token, *, role, email, code, **scope_kwargs):
    invite_response = client.post(
        "/api/invitation-codes",
        json={
            "role": role,
            "building_ids": scope_kwargs.get("building_ids") or [],
            "all_buildings": scope_kwargs.get("all_buildings", False),
            "map_group_ids": scope_kwargs.get("map_group_ids") or [],
            "map_ids": scope_kwargs.get("map_ids") or [],
        },
        headers=auth_headers(creator_token),
    )
    assert invite_response.status_code == 201, invite_response.text
    minted_code = invite_response.json()["code"]
    signup_response = signup(client, minted_code, email=email)
    assert signup_response.status_code == 200, signup_response.text
    return signup_response.json()["access_token"]


# ---------------------------------------------------------
# Public RoutePoint endpoints (Phase 3)
# ---------------------------------------------------------

def test_public_route_points_reachable_with_no_auth(client):
    super_token, _ = create_admin_and_get_token(client, role="super_admin", email="pub1@example.com")
    building = _create_building(client, super_token, "Public Test Building")
    map_item = _create_map_for_building(client, super_token, building["id"])
    _create_point(client, super_token, map_item["id"], "Entrance", building_id=building["id"])

    response = client.get(
        "/api/route-points/public",
        params={"building_id": building["id"]},
    )
    assert response.status_code == 200, response.text
    points = response.json()
    assert len(points) == 1
    assert points[0]["name"] == "Entrance"


def test_public_route_point_by_id_reachable_with_no_auth(client):
    super_token, _ = create_admin_and_get_token(client, role="super_admin", email="pub2@example.com")
    building = _create_building(client, super_token, "Public Test Building 2")
    map_item = _create_map_for_building(client, super_token, building["id"])
    point = _create_point(client, super_token, map_item["id"], "Lobby", building_id=building["id"])

    response = client.get(f"/api/route-points/public/{point['id']}")
    assert response.status_code == 200, response.text
    assert response.json()["name"] == "Lobby"


def test_public_route_points_requires_map_id_or_building_id(client):
    response = client.get("/api/route-points/public")
    assert response.status_code == 400, response.text


def test_public_route_point_response_excludes_admin_only_fields(client):
    super_token, _ = create_admin_and_get_token(client, role="super_admin", email="pub3@example.com")
    building = _create_building(client, super_token, "Public Test Building 3")
    map_item = _create_map_for_building(client, super_token, building["id"])
    point = _create_point(client, super_token, map_item["id"], "Corridor", building_id=building["id"])

    response = client.get(f"/api/route-points/public/{point['id']}")
    assert response.status_code == 200, response.text
    body = response.json()

    # Provenance/one-shot/semantic-linkage fields must never appear in the
    # public shape — only the admin RoutePointResponse exposes these.
    for admin_only_field in (
        "is_auto_generated",
        "generation_method",
        "generation_confidence",
        "generation_version",
        "source",
        "was_reused",
        "auto_connected_edge_ids",
        "room_sync_action",
        "room_sync_warning",
        "semantic_publication_id",
        "semantic_entity_external_id",
        "semantic_entity_type",
    ):
        assert admin_only_field not in body, f"{admin_only_field} leaked into public response"


# ---------------------------------------------------------
# Bulk delete preview/apply (Phase 6)
# ---------------------------------------------------------

def test_bulk_delete_preview_reports_deletable_points(client):
    super_token, _ = create_admin_and_get_token(client, role="super_admin", email="bulk1@example.com")
    building = _create_building(client, super_token, "Bulk Delete Building")
    map_item = _create_map_for_building(client, super_token, building["id"])
    # NOTE: coordinates must be spaced beyond
    # point_dedup_service.DEFAULT_COORDINATE_TOLERANCE_PX (6.0px) — both
    # points previously defaulted to x=0, y=0 (identical), so production
    # dedup correctly returned the SAME stored RoutePoint for both create
    # calls, collapsing "2 points" down to 1. This was a test-fixture
    # defect, not a bulk-delete evaluator bug.
    p1 = _create_point(client, super_token, map_item["id"], "BD Point 1", x=20, y=20)
    p2 = _create_point(client, super_token, map_item["id"], "BD Point 2", x=100, y=20)
    assert p1["id"] != p2["id"], "expected 2 distinct RoutePoint ids, dedup likely collapsed them"

    response = client.post(
        "/api/route-points/bulk-delete/preview",
        json={"point_ids": [p1["id"], p2["id"]]},
        headers=auth_headers(super_token),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["requested_count"] == 2
    assert body["deletable_count"] == 2
    assert body["blocked_count"] == 0
    assert body["can_apply_all"] is True
    assert set(body["deletable_point_ids"]) == {p1["id"], p2["id"]}


def test_bulk_delete_preview_never_deletes_anything(client):
    super_token, _ = create_admin_and_get_token(client, role="super_admin", email="bulk2@example.com")
    building = _create_building(client, super_token, "Bulk Preview NoOp Building")
    map_item = _create_map_for_building(client, super_token, building["id"])
    p1 = _create_point(client, super_token, map_item["id"], "Preview NoOp Point")

    client.post(
        "/api/route-points/bulk-delete/preview",
        json={"point_ids": [p1["id"]]},
        headers=auth_headers(super_token),
    )

    still_there = client.get(f"/api/route-points/{p1['id']}", headers=auth_headers(super_token))
    assert still_there.status_code == 200, still_there.text


def test_bulk_delete_apply_deletes_all_when_clean(client):
    super_token, _ = create_admin_and_get_token(client, role="super_admin", email="bulk3@example.com")
    building = _create_building(client, super_token, "Bulk Apply Building")
    map_item = _create_map_for_building(client, super_token, building["id"])
    # See the identical dedup-spacing note in
    # test_bulk_delete_preview_reports_deletable_points above.
    p1 = _create_point(client, super_token, map_item["id"], "Apply Point 1", x=20, y=20)
    p2 = _create_point(client, super_token, map_item["id"], "Apply Point 2", x=100, y=20)
    assert p1["id"] != p2["id"], "expected 2 distinct RoutePoint ids, dedup likely collapsed them"

    response = client.post(
        "/api/route-points/bulk-delete/apply",
        json={"point_ids": [p1["id"], p2["id"]]},
        headers=auth_headers(super_token),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["deleted_count"] == 2
    assert set(body["deleted_point_ids"]) == {p1["id"], p2["id"]}

    gone = client.get(f"/api/route-points/{p1['id']}", headers=auth_headers(super_token))
    assert gone.status_code == 404, gone.text


def test_bulk_delete_apply_rejects_whole_batch_if_any_point_has_edges(client):
    """All-or-nothing: one blocked point in the batch must prevent the
    entire batch from being deleted, including the otherwise-deletable
    points in the same request."""

    super_token, _ = create_admin_and_get_token(client, role="super_admin", email="bulk4@example.com")
    building = _create_building(client, super_token, "Bulk AllOrNothing Building")
    map_item = _create_map_for_building(client, super_token, building["id"])
    # See the identical dedup-spacing note in
    # test_bulk_delete_preview_reports_deletable_points above — all 3
    # points previously defaulted to the same (0, 0) coordinate and
    # collapsed into a single stored RoutePoint, which is also why the
    # RouteEdge creation below used to fail with "from_point_id and
    # to_point_id cannot be the same" (edge_point_a and edge_point_b were
    # actually the same document).
    clean_point = _create_point(client, super_token, map_item["id"], "Clean Point", x=20, y=20)
    edge_point_a = _create_point(client, super_token, map_item["id"], "Edge Point A", x=100, y=20)
    edge_point_b = _create_point(client, super_token, map_item["id"], "Edge Point B", x=180, y=20)
    assert len({clean_point["id"], edge_point_a["id"], edge_point_b["id"]}) == 3, (
        "expected 3 distinct RoutePoint ids, dedup likely collapsed them"
    )

    edge_response = client.post(
        "/api/route-edges",
        json={
            "map_id": map_item["id"],
            "from_point_id": edge_point_a["id"],
            "to_point_id": edge_point_b["id"],
        },
        headers=auth_headers(super_token),
    )
    assert edge_response.status_code == 201, edge_response.text

    response = client.post(
        "/api/route-points/bulk-delete/apply",
        json={"point_ids": [clean_point["id"], edge_point_a["id"]]},
        headers=auth_headers(super_token),
    )
    assert response.status_code == 409, response.text

    # Nothing was deleted, including the clean point.
    still_there = client.get(
        f"/api/route-points/{clean_point['id']}", headers=auth_headers(super_token)
    )
    assert still_there.status_code == 200, still_there.text


def test_bulk_delete_apply_rejects_out_of_scope_point_for_building_manager(client):
    super_token, _ = create_admin_and_get_token(client, role="super_admin", email="bulk5@example.com")
    own_building = _create_building(client, super_token, "BM Owned Building")
    other_building = _create_building(client, super_token, "BM Unowned Building")

    own_map = _create_map_for_building(client, super_token, own_building["id"], "Owned Map")
    other_map = _create_map_for_building(client, super_token, other_building["id"], "Unowned Map")

    own_point = _create_point(client, super_token, own_map["id"], "Owned Point")
    other_point = _create_point(client, super_token, other_map["id"], "Unowned Point")

    bm_token = _signup_with_invite(
        client,
        super_token,
        role="building_manager",
        email="bm-bulk@example.com",
        code="QR-BMBULK01",
        building_ids=[own_building["id"]],
    )

    preview = client.post(
        "/api/route-points/bulk-delete/preview",
        json={"point_ids": [own_point["id"], other_point["id"]]},
        headers=auth_headers(bm_token),
    )
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["can_apply_all"] is False
    reasons = {issue["reason"] for issue in body["issues"]}
    assert "out_of_scope" in reasons

    apply_response = client.post(
        "/api/route-points/bulk-delete/apply",
        json={"point_ids": [own_point["id"], other_point["id"]]},
        headers=auth_headers(bm_token),
    )
    assert apply_response.status_code == 409, apply_response.text

    # The in-scope point must still exist — all-or-nothing.
    still_there = client.get(
        f"/api/route-points/{own_point['id']}", headers=auth_headers(super_token)
    )
    assert still_there.status_code == 200, still_there.text


def test_bulk_delete_apply_rejects_not_found_id(client):
    super_token, _ = create_admin_and_get_token(client, role="super_admin", email="bulk6@example.com")

    response = client.post(
        "/api/route-points/bulk-delete/apply",
        json={"point_ids": ["64b000000000000000000000"]},
        headers=auth_headers(super_token),
    )
    assert response.status_code == 409, response.text
    body = response.json()["detail"]
    assert any(issue["reason"] == "not_found" for issue in body["issues"])


def test_bulk_delete_requires_admin_role(client):
    reg_code = make_invitation_code(client, code="QR-BULKREG1", role="regular_user")
    reg_response = signup(client, reg_code, email="reguser-bulk@example.com")
    reg_token = reg_response.json()["access_token"]

    response = client.post(
        "/api/route-points/bulk-delete/preview",
        json={"point_ids": ["64b000000000000000000000"]},
        headers=auth_headers(reg_token),
    )
    assert response.status_code == 403, response.text


# ---------------------------------------------------------
# Buildings / Rooms list scoping (Phase 9 dashboard-correctness fix)
# ---------------------------------------------------------

def test_buildings_list_unrestricted_for_anonymous_caller(client):
    super_token, _ = create_admin_and_get_token(client, role="super_admin", email="scope1@example.com")
    _create_building(client, super_token, "Anon Visible Building A")
    _create_building(client, super_token, "Anon Visible Building B")

    response = client.get("/api/locations/buildings")
    assert response.status_code == 200, response.text
    assert len(response.json()) >= 2


def test_buildings_list_scoped_for_building_manager(client):
    super_token, _ = create_admin_and_get_token(client, role="super_admin", email="scope2@example.com")
    own_building = _create_building(client, super_token, "BM Scope Owned")
    _create_building(client, super_token, "BM Scope Unowned")

    bm_token = _signup_with_invite(
        client,
        super_token,
        role="building_manager",
        email="bm-buildscope@example.com",
        code="QR-BMBLDSC1",
        building_ids=[own_building["id"]],
    )

    response = client.get("/api/locations/buildings", headers=auth_headers(bm_token))
    assert response.status_code == 200, response.text
    ids = [b["id"] for b in response.json()]
    assert ids == [own_building["id"]]


def test_rooms_list_scoped_for_building_manager(client):
    super_token, _ = create_admin_and_get_token(client, role="super_admin", email="scope3@example.com")
    own_building = _create_building(client, super_token, "BM Room Scope Owned")
    other_building = _create_building(client, super_token, "BM Room Scope Unowned")

    client.post(
        "/api/rooms",
        json={"building_id": own_building["id"], "name_en": "Owned Room", "room_type": "clinic"},
        headers=auth_headers(super_token),
    )
    client.post(
        "/api/rooms",
        json={"building_id": other_building["id"], "name_en": "Unowned Room", "room_type": "clinic"},
        headers=auth_headers(super_token),
    )

    bm_token = _signup_with_invite(
        client,
        super_token,
        role="building_manager",
        email="bm-roomscope@example.com",
        code="QR-BMRMSC01",
        building_ids=[own_building["id"]],
    )

    response = client.get("/api/rooms", headers=auth_headers(bm_token))
    assert response.status_code == 200, response.text
    names = [r["name_en"] for r in response.json()]
    assert names == ["Owned Room"]


def test_rooms_list_rejects_explicit_out_of_scope_building_id(client):
    super_token, _ = create_admin_and_get_token(client, role="super_admin", email="scope4@example.com")
    own_building = _create_building(client, super_token, "BM Explicit Scope Owned")
    other_building = _create_building(client, super_token, "BM Explicit Scope Unowned")

    bm_token = _signup_with_invite(
        client,
        super_token,
        role="building_manager",
        email="bm-explicitscope@example.com",
        code="QR-BMEXPSC1",
        building_ids=[own_building["id"]],
    )

    response = client.get(
        "/api/rooms",
        params={"building_id": other_building["id"]},
        headers=auth_headers(bm_token),
    )
    assert response.status_code == 403, response.text
