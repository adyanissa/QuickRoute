"""
Integration tests against the real FastAPI app + real route/schema/logic
code, backed by an in-memory mongomock database (see conftest.py) instead
of the real MongoDB Atlas cluster. No real network access, no real
credentials, and the real quickroute_db is never touched.

Run with: pytest backend/tests/test_api_integration.py -v
"""


def make_invitation_code(client, code="QR-TESTCODE1", role="regular_user", building_ids=None, all_buildings=False):
    response = client.post(
        "/api/invitation-codes/dev-create",
        json={
            "code": code,
            "role": role,
            "building_ids": building_ids or [],
            "all_buildings": all_buildings,
        },
    )
    assert response.status_code == 200, response.text
    return code


def signup(client, code, email="user@example.com", full_name="Test User", password="password123"):
    response = client.post(
        "/api/auth/signup",
        json={
            "full_name": full_name,
            "email": email,
            "password": password,
            "code": code,
        },
    )
    return response


def create_admin_and_get_token(client, role="super_admin", email="admin@example.com"):
    code = make_invitation_code(client, code=f"QR-{role.upper()[:8]}1", role=role)
    response = signup(client, code, email=email)
    assert response.status_code == 200, response.text
    return response.json()["access_token"], response.json()["user"]


def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------
# Signup / login / invitation codes
# ---------------------------------------------------------

def test_full_signup_and_login_flow(client):
    code = make_invitation_code(client, code="QR-SIGNUP01")

    signup_response = signup(client, code, email="newuser@example.com")
    assert signup_response.status_code == 200

    body = signup_response.json()
    assert body["success"] is True
    assert body["user"]["email"] == "newuser@example.com"
    assert body["user"]["role"] == "regular_user"
    assert body["access_token"]

    login_response = client.post(
        "/api/auth/login",
        json={"email": "newuser@example.com", "password": "password123"},
    )
    assert login_response.status_code == 200
    login_body = login_response.json()
    assert login_body["user"]["email"] == "newuser@example.com"
    assert login_body["access_token"]

    me_response = client.get("/api/auth/me", headers=auth_headers(login_body["access_token"]))
    assert me_response.status_code == 200
    assert me_response.json()["email"] == "newuser@example.com"


def test_login_with_wrong_password_fails(client):
    code = make_invitation_code(client, code="QR-WRONGPW1")
    signup(client, code, email="wrongpw@example.com")

    response = client.post(
        "/api/auth/login",
        json={"email": "wrongpw@example.com", "password": "not-the-password"},
    )
    assert response.status_code == 401


def test_invitation_code_cannot_be_reused(client):
    code = make_invitation_code(client, code="QR-ONETIME1")

    first = signup(client, code, email="first@example.com")
    assert first.status_code == 200

    second = signup(client, code, email="second@example.com")
    assert second.status_code == 400  # already used


def test_signup_with_invalid_code_fails(client):
    response = signup(client, "QR-DOESNOTEXIST", email="nobody@example.com")
    assert response.status_code == 404


def test_me_requires_authentication(client):
    response = client.get("/api/auth/me")
    assert response.status_code == 401


# ---------------------------------------------------------
# Role permission enforcement
# ---------------------------------------------------------

def test_regular_user_cannot_create_building(client):
    code = make_invitation_code(client, code="QR-REGUSER1", role="regular_user")
    signup_response = signup(client, code, email="regular@example.com")
    token = signup_response.json()["access_token"]

    response = client.post(
        "/api/locations/buildings",
        json={"name_en": "Should Fail"},
        headers=auth_headers(token),
    )
    assert response.status_code == 403


def test_unauthenticated_request_cannot_create_building(client):
    response = client.post(
        "/api/locations/buildings",
        json={"name_en": "No Token"},
    )
    assert response.status_code == 401


def test_super_admin_can_create_building(client):
    token, _ = create_admin_and_get_token(client, role="super_admin", email="super@example.com")

    response = client.post(
        "/api/locations/buildings",
        json={"name_en": "Main Hall"},
        headers=auth_headers(token),
    )
    assert response.status_code == 201
    assert response.json()["name_en"] == "Main Hall"


def test_building_manager_cannot_update_unassigned_building(client):
    super_token, _ = create_admin_and_get_token(client, role="super_admin", email="super2@example.com")

    building = client.post(
        "/api/locations/buildings",
        json={"name_en": "Library"},
        headers=auth_headers(super_token),
    ).json()

    bm_code = make_invitation_code(
        client, code="QR-BLDGMGR1", role="building_manager", building_ids=["someone-elses-building"]
    )
    bm_token = signup(client, bm_code, email="bldgmgr@example.com").json()["access_token"]

    response = client.put(
        f"/api/locations/buildings/{building['id']}",
        json={"description": "hijacked"},
        headers=auth_headers(bm_token),
    )
    assert response.status_code == 403


# ---------------------------------------------------------
# Maps, route points, route edges
# ---------------------------------------------------------

def _create_map(client, token, title="Test Campus Map"):
    response = client.post(
        "/api/maps",
        json={"title": title},
        headers=auth_headers(token),
    )
    assert response.status_code == 201, response.text
    return response.json()


def _create_point(client, token, map_id, name, x, y, floor=0, point_type="hallway"):
    response = client.post(
        "/api/route-points",
        json={"map_id": map_id, "name": name, "x": x, "y": y, "floor": floor, "point_type": point_type},
        headers=auth_headers(token),
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_map_upload_metadata_via_json_create(client):
    token, _ = create_admin_and_get_token(client, role="global_manager", email="mapmgr@example.com")

    map_item = _create_map(client, token, title="North Wing")
    assert map_item["title"] == "North Wing"
    assert map_item["processing_status"] in ("not_started", "completed")
    assert map_item["is_current"] is True


def test_route_point_creation_rejects_unknown_map(client):
    token, _ = create_admin_and_get_token(client, role="global_manager", email="ptmgr@example.com")

    response = client.post(
        "/api/route-points",
        json={"map_id": "000000000000000000000000", "name": "Ghost Point", "x": 1, "y": 1},
        headers=auth_headers(token),
    )
    assert response.status_code == 404


def test_route_edge_rejects_points_from_different_maps(client):
    token, _ = create_admin_and_get_token(client, role="global_manager", email="edgemgr@example.com")

    map_a = _create_map(client, token, title="Map A")
    map_b = _create_map(client, token, title="Map B")

    point_a = _create_point(client, token, map_a["id"], "A1", 0, 0)
    point_b = _create_point(client, token, map_b["id"], "B1", 10, 10)

    response = client.post(
        "/api/route-edges",
        json={
            "map_id": map_a["id"],
            "from_point_id": point_a["id"],
            "to_point_id": point_b["id"],
            "edge_type": "walkway",
        },
        headers=auth_headers(token),
    )
    assert response.status_code == 400


def test_route_point_delete_rejected_while_edges_exist(client):
    token, _ = create_admin_and_get_token(client, role="global_manager", email="delmgr@example.com")

    map_item = _create_map(client, token, title="Delete Test Map")
    point_a = _create_point(client, token, map_item["id"], "Point A", 0, 0)
    point_b = _create_point(client, token, map_item["id"], "Point B", 10, 0)

    edge = client.post(
        "/api/route-edges",
        json={
            "map_id": map_item["id"],
            "from_point_id": point_a["id"],
            "to_point_id": point_b["id"],
        },
        headers=auth_headers(token),
    )
    assert edge.status_code == 201

    delete_response = client.delete(
        f"/api/route-points/{point_a['id']}",
        headers=auth_headers(token),
    )
    assert delete_response.status_code == 409


# ---------------------------------------------------------
# Dijkstra navigation
# ---------------------------------------------------------

def test_navigation_route_returns_shortest_path(client):
    token, _ = create_admin_and_get_token(client, role="global_manager", email="navmgr@example.com")

    map_item = _create_map(client, token, title="Nav Map")
    p1 = _create_point(client, token, map_item["id"], "P1", 0, 0)
    p2 = _create_point(client, token, map_item["id"], "P2", 10, 0)
    p3 = _create_point(client, token, map_item["id"], "P3", 20, 0)

    client.post(
        "/api/route-edges",
        json={"map_id": map_item["id"], "from_point_id": p1["id"], "to_point_id": p2["id"]},
        headers=auth_headers(token),
    )
    client.post(
        "/api/route-edges",
        json={"map_id": map_item["id"], "from_point_id": p2["id"], "to_point_id": p3["id"]},
        headers=auth_headers(token),
    )

    response = client.post(
        "/api/navigation/route",
        json={"map_id": map_item["id"], "start_point_id": p1["id"], "end_point_id": p3["id"]},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["path_point_ids"] == [p1["id"], p2["id"], p3["id"]]
    assert body["total_distance"] > 0


def test_navigation_route_returns_404_when_no_route_exists(client):
    token, _ = create_admin_and_get_token(client, role="global_manager", email="noroute@example.com")

    map_item = _create_map(client, token, title="Disconnected Map")
    p1 = _create_point(client, token, map_item["id"], "Island A", 0, 0)
    p2 = _create_point(client, token, map_item["id"], "Island B", 100, 100)
    # No edge created between them.

    response = client.post(
        "/api/navigation/route",
        json={"map_id": map_item["id"], "start_point_id": p1["id"], "end_point_id": p2["id"]},
    )
    assert response.status_code == 404


# ---------------------------------------------------------
# Location codes (QR/barcode starting location)
# ---------------------------------------------------------

def test_location_code_create_and_resolve(client):
    token, _ = create_admin_and_get_token(client, role="global_manager", email="loccode@example.com")

    building = client.post(
        "/api/locations/buildings",
        json={"name_en": "Entrance Hall"},
        headers=auth_headers(token),
    ).json()

    map_item = _create_map(client, token, title="Entrance Map")
    entrance_point = _create_point(
        client, token, map_item["id"], "Main Entrance", 5, 5, point_type="entrance"
    )

    create_response = client.post(
        "/api/location-codes",
        json={
            "code": "QR-KIOSK-01",
            "building_id": building["id"],
            "map_id": map_item["id"],
            "route_point_id": entrance_point["id"],
        },
        headers=auth_headers(token),
    )
    assert create_response.status_code == 201

    resolve_response = client.get("/api/location-codes/resolve/QR-KIOSK-01")
    assert resolve_response.status_code == 200
    resolved = resolve_response.json()
    assert resolved["route_point_id"] == entrance_point["id"]
    assert resolved["map_id"] == map_item["id"]


def test_resolve_unknown_location_code_returns_404(client):
    response = client.get("/api/location-codes/resolve/QR-DOES-NOT-EXIST")
    assert response.status_code == 404


def test_inactive_location_code_cannot_be_resolved(client):
    token, _ = create_admin_and_get_token(client, role="global_manager", email="inactive@example.com")

    building = client.post(
        "/api/locations/buildings",
        json={"name_en": "Inactive Building"},
        headers=auth_headers(token),
    ).json()
    map_item = _create_map(client, token, title="Inactive Map")
    point = _create_point(client, token, map_item["id"], "Point", 0, 0)

    client.post(
        "/api/location-codes",
        json={
            "code": "QR-INACTIVE-1",
            "building_id": building["id"],
            "map_id": map_item["id"],
            "route_point_id": point["id"],
            "is_active": False,
        },
        headers=auth_headers(token),
    )

    response = client.get("/api/location-codes/resolve/QR-INACTIVE-1")
    assert response.status_code == 400


# ---------------------------------------------------------
# Map deletion cascade
# ---------------------------------------------------------

def test_map_deletion_cascades_to_points_and_edges(client):
    token, _ = create_admin_and_get_token(client, role="global_manager", email="cascade@example.com")

    map_item = _create_map(client, token, title="Cascade Map")
    p1 = _create_point(client, token, map_item["id"], "C1", 0, 0)
    p2 = _create_point(client, token, map_item["id"], "C2", 10, 0)

    client.post(
        "/api/route-edges",
        json={"map_id": map_item["id"], "from_point_id": p1["id"], "to_point_id": p2["id"]},
        headers=auth_headers(token),
    )

    delete_response = client.delete(
        f"/api/maps/{map_item['id']}",
        headers=auth_headers(token),
    )
    assert delete_response.status_code == 200
    summary = delete_response.json()
    assert summary["deleted_points"] == 2
    assert summary["deleted_edges"] == 1

    remaining_points = client.get(
        "/api/route-points", params={"map_id": map_item["id"]}
    ).json()
    remaining_edges = client.get(
        "/api/route-edges", params={"map_id": map_item["id"]}
    ).json()

    assert remaining_points == []
    assert remaining_edges == []
