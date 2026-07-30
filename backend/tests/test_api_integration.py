"""
Integration tests against the real FastAPI app + real route/schema/logic
code, backed by an in-memory mongomock database (see conftest.py) instead
of the real MongoDB Atlas cluster. No real network access, no real
credentials, and the real quickroute_db is never touched.

Run with: pytest backend/tests/test_api_integration.py -v
"""


def make_invitation_code(
    client,
    code="QR-TESTCODE1",
    role="regular_user",
    building_ids=None,
    all_buildings=False,
    creator_token=None,
):
    """
    Two paths, matching the real system:
      - creator_token given: goes through the real authenticated
        POST /api/invitation-codes endpoint (creator permission hierarchy
        + building-scope validation enforced, exactly as the Admin UI
        would call it).
      - no creator_token: goes through the dev-only bootstrap endpoint,
        which only works when no super_admin exists yet in the (fresh,
        per-test) database — i.e. only for the very first admin account
        of a test. conftest.py enables this endpoint for the test process
        only via ALLOW_DEV_INVITATION_ENDPOINTS.
    """

    if creator_token:
        response = client.post(
            "/api/invitation-codes",
            json={
                "code": code,
                "role": role,
                "building_ids": building_ids or [],
                "all_buildings": all_buildings,
            },
            headers=auth_headers(creator_token),
        )
        assert response.status_code == 201, response.text
        return response.json()["code"]

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

    # A second, real building the building_manager is NOT assigned to —
    # used instead of a fake placeholder id now that invitation-code
    # creation validates every assigned building_id actually exists.
    other_building = client.post(
        "/api/locations/buildings",
        json={"name_en": "Other Building"},
        headers=auth_headers(super_token),
    ).json()

    bm_code = make_invitation_code(
        client,
        code="QR-BLDGMGR1",
        role="building_manager",
        building_ids=[other_building["id"]],
        creator_token=super_token,
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

def _create_map(client, token, title="Test Campus Map", building_id=None, campus=None):
    payload = {"title": title}
    if building_id:
        payload["building_id"] = building_id
    if campus:
        payload["campus"] = campus

    response = client.post(
        "/api/maps",
        json=payload,
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
# Draw Walkable Path graph-merging: reusing an existing point as the join
# between two separately-saved paths (regression coverage for the bug where
# every saved path stayed an isolated graph component).
# ---------------------------------------------------------

def test_route_edge_between_two_existing_points_succeeds(client):
    # Simulates connecting two points that were both already saved earlier
    # (e.g. two points snapped in from prior drafts) — an "existing ->
    # existing" edge, not just "new -> new".
    token, _ = create_admin_and_get_token(client, role="global_manager", email="existtoexist@example.com")

    map_item = _create_map(client, token, title="Existing To Existing Map")
    point_a = _create_point(client, token, map_item["id"], "A1", 0, 0)
    point_b = _create_point(client, token, map_item["id"], "B1", 15, 0)

    response = client.post(
        "/api/route-edges",
        json={"map_id": map_item["id"], "from_point_id": point_a["id"], "to_point_id": point_b["id"]},
        headers=auth_headers(token),
    )
    assert response.status_code == 201, response.text


def test_creating_edge_between_same_point_twice_is_rejected(client):
    token, _ = create_admin_and_get_token(client, role="global_manager", email="selfedge@example.com")

    map_item = _create_map(client, token, title="Self Edge Map")
    point_a = _create_point(client, token, map_item["id"], "A1", 0, 0)

    response = client.post(
        "/api/route-edges",
        json={"map_id": map_item["id"], "from_point_id": point_a["id"], "to_point_id": point_a["id"]},
        headers=auth_headers(token),
    )
    assert response.status_code == 400


def test_duplicate_route_edge_between_same_points_is_rejected(client):
    token, _ = create_admin_and_get_token(client, role="global_manager", email="dupedge@example.com")

    map_item = _create_map(client, token, title="Duplicate Edge Map")
    point_a = _create_point(client, token, map_item["id"], "A1", 0, 0)
    point_b = _create_point(client, token, map_item["id"], "B1", 10, 0)

    first = client.post(
        "/api/route-edges",
        json={"map_id": map_item["id"], "from_point_id": point_a["id"], "to_point_id": point_b["id"]},
        headers=auth_headers(token),
    )
    assert first.status_code == 201, first.text

    # Same pair, reversed direction — still the same "identical" walkway
    # connection and must also be rejected, not just the exact from/to order.
    second = client.post(
        "/api/route-edges",
        json={"map_id": map_item["id"], "from_point_id": point_b["id"], "to_point_id": point_a["id"]},
        headers=auth_headers(token),
    )
    assert second.status_code == 409


def test_route_edge_to_inactive_point_is_rejected(client):
    token, _ = create_admin_and_get_token(client, role="global_manager", email="inactivept@example.com")

    map_item = _create_map(client, token, title="Inactive Point Map")
    point_a = _create_point(client, token, map_item["id"], "A1", 0, 0)
    point_b = _create_point(client, token, map_item["id"], "B1", 10, 0)

    deactivate = client.put(
        f"/api/route-points/{point_b['id']}",
        json={"is_active": False},
        headers=auth_headers(token),
    )
    assert deactivate.status_code == 200, deactivate.text

    response = client.post(
        "/api/route-edges",
        json={"map_id": map_item["id"], "from_point_id": point_a["id"], "to_point_id": point_b["id"]},
        headers=auth_headers(token),
    )
    assert response.status_code == 400


def test_second_saved_path_reuses_existing_point_and_merges_graph(client):
    # Reproduces the exact acceptance scenario: save path A (A -> B -> C),
    # then save a second path that starts by reusing C (not creating a
    # duplicate point near it) and continues C -> D -> E. Dijkstra must
    # then find a single route all the way from A to E, crossing both
    # saved segments through the shared junction point C.
    token, _ = create_admin_and_get_token(client, role="global_manager", email="mergegraph@example.com")

    map_item = _create_map(client, token, title="Merge Graph Map")

    point_a = _create_point(client, token, map_item["id"], "A1", 0, 0)
    point_b = _create_point(client, token, map_item["id"], "B1", 10, 0)
    point_c = _create_point(client, token, map_item["id"], "C1", 20, 0)

    edge_ab = client.post(
        "/api/route-edges",
        json={"map_id": map_item["id"], "from_point_id": point_a["id"], "to_point_id": point_b["id"]},
        headers=auth_headers(token),
    )
    assert edge_ab.status_code == 201, edge_ab.text

    edge_bc = client.post(
        "/api/route-edges",
        json={"map_id": map_item["id"], "from_point_id": point_b["id"], "to_point_id": point_c["id"]},
        headers=auth_headers(token),
    )
    assert edge_bc.status_code == 201, edge_bc.text

    # Second draft: total route-points count before this draft must not
    # grow by reusing C — only D and E are genuinely new.
    points_before_second_draft = client.get(
        "/api/route-points", params={"map_id": map_item["id"]}
    ).json()
    assert len(points_before_second_draft) == 3

    point_d = _create_point(client, token, map_item["id"], "D1", 30, 0)
    point_e = _create_point(client, token, map_item["id"], "E1", 40, 0)

    points_after_second_draft = client.get(
        "/api/route-points", params={"map_id": map_item["id"]}
    ).json()
    # Exactly two new points (D, E) — C was reused by ID, never recreated.
    assert len(points_after_second_draft) == 5

    edge_cd = client.post(
        "/api/route-edges",
        json={"map_id": map_item["id"], "from_point_id": point_c["id"], "to_point_id": point_d["id"]},
        headers=auth_headers(token),
    )
    assert edge_cd.status_code == 201, edge_cd.text

    edge_de = client.post(
        "/api/route-edges",
        json={"map_id": map_item["id"], "from_point_id": point_d["id"], "to_point_id": point_e["id"]},
        headers=auth_headers(token),
    )
    assert edge_de.status_code == 201, edge_de.text

    # Before the fix, A and E would be in two disconnected graph components
    # (404 "No route found"). After the fix, one continuous route exists.
    response = client.post(
        "/api/navigation/route",
        json={"map_id": map_item["id"], "start_point_id": point_a["id"], "end_point_id": point_e["id"]},
    )
    assert response.status_code == 200, response.text

    body = response.json()
    assert body["path_point_ids"] == [
        point_a["id"],
        point_b["id"],
        point_c["id"],
        point_d["id"],
        point_e["id"],
    ]
    assert body["total_distance"] == 40


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

    map_item = _create_map(client, token, title="Entrance Map", building_id=building["id"])
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
    map_item = _create_map(client, token, title="Inactive Map", building_id=building["id"])
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


# ---------------------------------------------------------
# Multi-path graph merging (Draw Walkable Path acceptance scenario)
# ---------------------------------------------------------

def test_full_two_path_save_merges_six_point_graph_a_to_f(client):
    # Exact spec scenario: first saved path A-B-C-D, second saved path
    # reuses B, C, D by their real ids and continues D-E-F. Total unique
    # points must be exactly 6 (never a duplicate B/C/D), the already-saved
    # B-C and C-D edges must not be duplicated when "redrawn", and Dijkstra
    # must find one continuous route all the way from A to F.
    token, _ = create_admin_and_get_token(client, role="global_manager", email="sixpoint@example.com")
    map_item = _create_map(client, token, title="Six Point Merge Map")

    point_a = _create_point(client, token, map_item["id"], "A1", 0, 0)
    point_b = _create_point(client, token, map_item["id"], "B1", 10, 0)
    point_c = _create_point(client, token, map_item["id"], "C1", 20, 0)
    point_d = _create_point(client, token, map_item["id"], "D1", 30, 0)

    for from_point, to_point in [(point_a, point_b), (point_b, point_c), (point_c, point_d)]:
        response = client.post(
            "/api/route-edges",
            json={
                "map_id": map_item["id"],
                "from_point_id": from_point["id"],
                "to_point_id": to_point["id"],
            },
            headers=auth_headers(token),
        )
        assert response.status_code == 201, response.text

    # Second draft "redraws" B-C-D-E-F: B, C, D are reused by their real
    # ids (never recreated) — only E and F are genuinely new points.
    point_e = _create_point(client, token, map_item["id"], "E1", 40, 0)
    point_f = _create_point(client, token, map_item["id"], "F1", 50, 0)

    all_points = client.get(
        "/api/route-points", params={"map_id": map_item["id"]}
    ).json()
    assert len(all_points) == 6  # A, B, C, D, E, F — never a duplicate B/C/D

    # Re-"drawing" over the already-connected B-C and C-D segments must be
    # rejected as duplicates, not silently double up the graph.
    dup_bc = client.post(
        "/api/route-edges",
        json={"map_id": map_item["id"], "from_point_id": point_b["id"], "to_point_id": point_c["id"]},
        headers=auth_headers(token),
    )
    assert dup_bc.status_code == 409

    dup_cd = client.post(
        "/api/route-edges",
        json={"map_id": map_item["id"], "from_point_id": point_c["id"], "to_point_id": point_d["id"]},
        headers=auth_headers(token),
    )
    assert dup_cd.status_code == 409

    # D-E and E-F are the only genuinely new edges this second draft needs.
    for from_point, to_point in [(point_d, point_e), (point_e, point_f)]:
        response = client.post(
            "/api/route-edges",
            json={
                "map_id": map_item["id"],
                "from_point_id": from_point["id"],
                "to_point_id": to_point["id"],
            },
            headers=auth_headers(token),
        )
        assert response.status_code == 201, response.text

    all_edges = client.get(
        "/api/route-edges", params={"map_id": map_item["id"]}
    ).json()
    assert len(all_edges) == 5  # A-B, B-C, C-D, D-E, E-F — no duplicates

    a_to_f = client.post(
        "/api/navigation/route",
        json={"map_id": map_item["id"], "start_point_id": point_a["id"], "end_point_id": point_f["id"]},
    )
    assert a_to_f.status_code == 200, a_to_f.text
    assert a_to_f.json()["path_point_ids"] == [
        point_a["id"], point_b["id"], point_c["id"],
        point_d["id"], point_e["id"], point_f["id"],
    ]

    # Bidirectional by default — F -> A must also succeed.
    f_to_a = client.post(
        "/api/navigation/route",
        json={"map_id": map_item["id"], "start_point_id": point_f["id"], "end_point_id": point_a["id"]},
    )
    assert f_to_a.status_code == 200, f_to_a.text

    # The original A-D segment must still work on its own too.
    a_to_d = client.post(
        "/api/navigation/route",
        json={"map_id": map_item["id"], "start_point_id": point_a["id"], "end_point_id": point_d["id"]},
    )
    assert a_to_d.status_code == 200, a_to_d.text

    # And a route entirely within the second segment.
    b_to_f = client.post(
        "/api/navigation/route",
        json={"map_id": map_item["id"], "start_point_id": point_b["id"], "end_point_id": point_f["id"]},
    )
    assert b_to_f.status_code == 200, b_to_f.text


def test_branch_path_preserves_existing_edges_and_supports_new_routes(client):
    # Existing A-B-C-D, then a new branch C-G-H off the shared point C.
    # The original A-D segment's edges must remain completely intact, and
    # Dijkstra must be able to route across the branch point in every
    # direction (A->H, D->H, H->B), never flattening the graph into a
    # single path.
    token, _ = create_admin_and_get_token(client, role="global_manager", email="branch@example.com")
    map_item = _create_map(client, token, title="Branch Map")

    point_a = _create_point(client, token, map_item["id"], "A1", 0, 0)
    point_b = _create_point(client, token, map_item["id"], "B1", 10, 0)
    point_c = _create_point(client, token, map_item["id"], "C1", 20, 0)
    point_d = _create_point(client, token, map_item["id"], "D1", 30, 0)

    for from_point, to_point in [(point_a, point_b), (point_b, point_c), (point_c, point_d)]:
        response = client.post(
            "/api/route-edges",
            json={
                "map_id": map_item["id"],
                "from_point_id": from_point["id"],
                "to_point_id": to_point["id"],
            },
            headers=auth_headers(token),
        )
        assert response.status_code == 201, response.text

    point_g = _create_point(client, token, map_item["id"], "G1", 20, 10)
    point_h = _create_point(client, token, map_item["id"], "H1", 20, 20)

    for from_point, to_point in [(point_c, point_g), (point_g, point_h)]:
        response = client.post(
            "/api/route-edges",
            json={
                "map_id": map_item["id"],
                "from_point_id": from_point["id"],
                "to_point_id": to_point["id"],
            },
            headers=auth_headers(token),
        )
        assert response.status_code == 201, response.text

    all_edges = client.get(
        "/api/route-edges", params={"map_id": map_item["id"]}
    ).json()
    # Original 3 (A-B, B-C, C-D) + 2 new branch edges (C-G, G-H) = 5. The
    # branch never replaced or removed any of the original edges.
    assert len(all_edges) == 5
    original_pairs = {
        frozenset([point_a["id"], point_b["id"]]),
        frozenset([point_b["id"], point_c["id"]]),
        frozenset([point_c["id"], point_d["id"]]),
    }
    saved_pairs = {
        frozenset([edge["from_point_id"], edge["to_point_id"]]) for edge in all_edges
    }
    assert original_pairs.issubset(saved_pairs)

    for start, end in [(point_a, point_h), (point_d, point_h), (point_h, point_b)]:
        response = client.post(
            "/api/navigation/route",
            json={"map_id": map_item["id"], "start_point_id": start["id"], "end_point_id": end["id"]},
        )
        assert response.status_code == 200, response.text


# ---------------------------------------------------------
# Edge validation edge cases
# ---------------------------------------------------------

def test_edge_from_point_to_itself_is_rejected(client):
    token, _ = create_admin_and_get_token(client, role="global_manager", email="selfedge@example.com")
    map_item = _create_map(client, token, title="Self Edge Map")
    point_a = _create_point(client, token, map_item["id"], "A1", 0, 0)

    response = client.post(
        "/api/route-edges",
        json={"map_id": map_item["id"], "from_point_id": point_a["id"], "to_point_id": point_a["id"]},
        headers=auth_headers(token),
    )
    assert response.status_code == 400


def test_walkway_edge_rejects_points_on_different_floors(client):
    token, _ = create_admin_and_get_token(client, role="global_manager", email="crossfloor@example.com")
    map_item = _create_map(client, token, title="Cross Floor Map")

    ground = _create_point(client, token, map_item["id"], "GF", 0, 0, floor=0)
    first_floor = _create_point(client, token, map_item["id"], "F1", 0, 0, floor=1)

    response = client.post(
        "/api/route-edges",
        json={
            "map_id": map_item["id"],
            "from_point_id": ground["id"],
            "to_point_id": first_floor["id"],
            "edge_type": "walkway",
        },
        headers=auth_headers(token),
    )
    assert response.status_code == 400


# ---------------------------------------------------------
# Automatic nearby merging option (create_route_point ?auto_connect=)
# ---------------------------------------------------------

def test_create_route_point_default_auto_connect_off_creates_no_surprise_edges(client):
    # Matches the frontend's default "Reuse selected existing points only"
    # merge mode — a brand new point placed near other points must not
    # get any edges unless auto_connect is explicitly requested.
    token, _ = create_admin_and_get_token(client, role="global_manager", email="noauto@example.com")
    map_item = _create_map(client, token, title="No Auto Connect Map")

    _create_point(client, token, map_item["id"], "Near1", 0, 0)
    _create_point(client, token, map_item["id"], "Near2", 30, 0)

    new_point = _create_point(client, token, map_item["id"], "New", 15, 0)
    assert new_point["auto_connected_edge_ids"] == []

    edges = client.get(
        "/api/route-edges", params={"map_id": map_item["id"]}
    ).json()
    assert edges == []


def test_create_route_point_nearby_mode_returns_auto_connected_edge_ids(client):
    # Matches the frontend's "Merge with safe nearby graph points" mode —
    # the response must report exactly which edge(s) it created so the
    # caller (Save Path's rollback logic) can track/undo them if the save
    # fails later.
    token, _ = create_admin_and_get_token(client, role="global_manager", email="nearbymode@example.com")
    map_item = _create_map(client, token, title="Nearby Mode Map")

    anchor = _create_point(client, token, map_item["id"], "Anchor", 0, 0)

    response = client.post(
        "/api/route-points?auto_connect=nearest",
        json={"map_id": map_item["id"], "name": "New Corridor Point", "x": 40, "y": 0, "floor": 0},
        headers=auth_headers(token),
    )
    assert response.status_code == 201, response.text
    new_point = response.json()

    assert len(new_point["auto_connected_edge_ids"]) == 1

    edges = client.get(
        "/api/route-edges", params={"map_id": map_item["id"]}
    ).json()
    edge_ids = {edge["id"] for edge in edges}
    assert set(new_point["auto_connected_edge_ids"]).issubset(edge_ids)

    touching_new_point = [
        e for e in edges
        if new_point["id"] in (e["from_point_id"], e["to_point_id"])
        and anchor["id"] in (e["from_point_id"], e["to_point_id"])
    ]
    assert len(touching_new_point) == 1


def test_create_route_point_reused_point_never_gets_auto_connected_edges(client):
    # A reused point (was_reused=True) must never trigger auto_connect —
    # it isn't a new point, so auto-connecting it would risk creating
    # edges the admin never asked for on a point that may already be
    # fully wired up correctly.
    token, _ = create_admin_and_get_token(client, role="global_manager", email="reuseauto@example.com")
    map_item = _create_map(client, token, title="Reuse No Auto Map")

    _create_point(client, token, map_item["id"], "Neighbor", 40, 0)

    first = _create_point(client, token, map_item["id"], "Anchor", 0, 0)

    # Same map/floor, essentially the same coordinates (well within the
    # server-side dedup tolerance) — this must reuse `first`, not create a
    # new point, even with auto_connect requested.
    response = client.post(
        "/api/route-points?auto_connect=nearest",
        json={"map_id": map_item["id"], "name": "Anchor Again", "x": 0, "y": 0, "floor": 0},
        headers=auth_headers(token),
    )
    assert response.status_code == 201, response.text
    reused = response.json()

    assert reused["id"] == first["id"]
    assert reused["was_reused"] is True
    assert reused["auto_connected_edge_ids"] == []


def test_force_create_bypasses_dedup_for_off_merge_mode(client):
    # Matches the frontend's "Off" merge mode, which sends force_create so
    # even a click at essentially the same spot always makes a genuinely
    # separate point rather than silently reusing one.
    token, _ = create_admin_and_get_token(client, role="global_manager", email="forcecreate@example.com")
    map_item = _create_map(client, token, title="Force Create Map")

    first = _create_point(client, token, map_item["id"], "P1", 100, 100)

    response = client.post(
        "/api/route-points",
        json={
            "map_id": map_item["id"], "name": "P1 Again", "x": 100, "y": 100,
            "floor": 0, "force_create": True,
        },
        headers=auth_headers(token),
    )
    assert response.status_code == 201, response.text
    second = response.json()

    assert second["id"] != first["id"]
    assert second["was_reused"] is False

    all_points = client.get(
        "/api/route-points", params={"map_id": map_item["id"]}
    ).json()
    assert len(all_points) == 2


# ---------------------------------------------------------
# RoutePoint custom naming (Draw Walkable Path admin-entered names)
# ---------------------------------------------------------

def test_route_point_accepts_arabic_hebrew_and_english_names(client):
    token, _ = create_admin_and_get_token(client, role="global_manager", email="utf8names@example.com")
    map_item = _create_map(client, token, title="UTF8 Names Map")

    names = {
        "en": "Coffee Junction",
        "ar": "تقاطع القهوة",
        "he": "צומת הקפה",
    }

    created = {}
    x = 0
    for lang, name in names.items():
        response = client.post(
            "/api/route-points",
            json={"map_id": map_item["id"], "name": name, "x": x, "y": 0, "floor": 0},
            headers=auth_headers(token),
        )
        assert response.status_code == 201, response.text
        created[lang] = response.json()
        x += 50

    for lang, name in names.items():
        fetched = client.get(f"/api/route-points/{created[lang]['id']}").json()
        assert fetched["name"] == name


def test_route_point_name_too_short_is_rejected(client):
    token, _ = create_admin_and_get_token(client, role="global_manager", email="shortname@example.com")
    map_item = _create_map(client, token, title="Short Name Map")

    response = client.post(
        "/api/route-points",
        json={"map_id": map_item["id"], "name": "A", "x": 0, "y": 0, "floor": 0},
        headers=auth_headers(token),
    )
    assert response.status_code == 422


def test_route_point_name_too_long_is_rejected(client):
    token, _ = create_admin_and_get_token(client, role="global_manager", email="longname@example.com")
    map_item = _create_map(client, token, title="Long Name Map")

    response = client.post(
        "/api/route-points",
        json={"map_id": map_item["id"], "name": "X" * 121, "x": 0, "y": 0, "floor": 0},
        headers=auth_headers(token),
    )
    assert response.status_code == 422


def test_route_point_reuse_preserves_original_custom_name(client):
    # Matches the naming spec's explicit safety rule: if a "new" draft
    # point is actually a dedup match for an existing point, the existing
    # point's own custom name must never be silently overwritten by
    # whatever name the (unaware) draft happened to carry.
    token, _ = create_admin_and_get_token(client, role="global_manager", email="reusename@example.com")
    map_item = _create_map(client, token, title="Reuse Name Map")

    original = client.post(
        "/api/route-points",
        json={"map_id": map_item["id"], "name": "Main Corridor", "x": 100, "y": 100, "floor": 0},
        headers=auth_headers(token),
    )
    assert original.status_code == 201, original.text
    original_point = original.json()

    # Well within the server-side dedup tolerance — same physical spot,
    # different (draft-default-style) name.
    reused = client.post(
        "/api/route-points",
        json={"map_id": map_item["id"], "name": "Point 1", "x": 101, "y": 100, "floor": 0},
        headers=auth_headers(token),
    )
    assert reused.status_code == 201, reused.text
    reused_point = reused.json()

    assert reused_point["id"] == original_point["id"]
    assert reused_point["was_reused"] is True
    assert reused_point["name"] == "Main Corridor"

    fetched = client.get(f"/api/route-points/{original_point['id']}").json()
    assert fetched["name"] == "Main Corridor"


def test_saving_path_with_custom_names_stores_all_names_and_routes_by_id(client):
    # Full A-B-C acceptance scenario from the spec: three points saved
    # with meaningful custom names, then verify Dijkstra/Test Route still
    # operates on ids — the names are never used as graph keys.
    token, _ = create_admin_and_get_token(client, role="global_manager", email="pathnames@example.com")
    map_item = _create_map(client, token, title="Path Names Map")

    point_a = _create_point(client, token, map_item["id"], "Main Corridor", 0, 0)
    point_b = _create_point(client, token, map_item["id"], "Coffee Junction", 10, 0)
    point_c = _create_point(client, token, map_item["id"], "East Hall", 20, 0)

    for from_point, to_point in [(point_a, point_b), (point_b, point_c)]:
        response = client.post(
            "/api/route-edges",
            json={
                "map_id": map_item["id"],
                "from_point_id": from_point["id"],
                "to_point_id": to_point["id"],
            },
            headers=auth_headers(token),
        )
        assert response.status_code == 201, response.text

    all_points = client.get(
        "/api/route-points", params={"map_id": map_item["id"]}
    ).json()
    names_by_id = {p["id"]: p["name"] for p in all_points}
    assert names_by_id[point_a["id"]] == "Main Corridor"
    assert names_by_id[point_b["id"]] == "Coffee Junction"
    assert names_by_id[point_c["id"]] == "East Hall"

    route = client.post(
        "/api/navigation/route",
        json={"map_id": map_item["id"], "start_point_id": point_a["id"], "end_point_id": point_c["id"]},
    )
    assert route.status_code == 200, route.text
    # Routing is entirely by id — names never appear in the path itself.
    assert route.json()["path_point_ids"] == [point_a["id"], point_b["id"], point_c["id"]]


def test_duplicate_point_names_do_not_corrupt_the_graph(client):
    # Two distinct points (far enough apart to never dedup-match) sharing
    # the exact same name must remain two separate, independently
    # addressable points — identified only by id.
    token, _ = create_admin_and_get_token(client, role="global_manager", email="dupname@example.com")
    map_item = _create_map(client, token, title="Duplicate Name Map")

    first = _create_point(client, token, map_item["id"], "Junction", 0, 0)
    second = _create_point(client, token, map_item["id"], "Junction", 500, 500)

    assert first["id"] != second["id"]

    edge = client.post(
        "/api/route-edges",
        json={"map_id": map_item["id"], "from_point_id": first["id"], "to_point_id": second["id"]},
        headers=auth_headers(token),
    )
    assert edge.status_code == 201, edge.text

    route = client.post(
        "/api/navigation/route",
        json={"map_id": map_item["id"], "start_point_id": first["id"], "end_point_id": second["id"]},
    )
    assert route.status_code == 200, route.text
    assert route.json()["path_point_ids"] == [first["id"], second["id"]]
