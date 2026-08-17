"""
Backend tests for multi-floor Map Groups — POST /api/map-groups and
friends (routes/map_groups_routes.py), plus the ripple effects on
RouteEdge cross-floor validation, Room/LocationCode floor resolution, and
the backward-compatibility backfill endpoint.

Run with: pytest backend/tests/test_map_groups.py -v
"""


# NOTE (admin dashboard scope-isolation task): GET /api/map-groups and
# GET /api/map-groups/{id} used to have no dependency at all, so these
# assertions could read a group back anonymously. Both endpoints are now
# admin-only and scope-narrowed (see routes/map_groups_routes.py), so the
# read-backs below authenticate with the same admin token that created the
# group. Nothing else about what these tests assert has changed.

import base64
import io

# A real, tiny (1x1 transparent) PNG — small enough to upload instantly,
# but a genuinely valid image file so the same validation/processing code
# path a real map upload takes (extension check, temp-file save, and the
# background image-processing task the TestClient runs synchronously) is
# actually exercised, rather than short-circuited by an invalid file.
_TINY_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8A"
    "AQUBAScY42YAAAAASUVORK5CYII="
)
TINY_PNG_BYTES = base64.b64decode(_TINY_PNG_B64)


def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


def make_invitation_code(
    client,
    code="QR-TESTCODE1",
    role="regular_user",
    building_ids=None,
    all_buildings=False,
    creator_token=None,
):
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
    return client.post(
        "/api/auth/signup",
        json={
            "full_name": full_name,
            "email": email,
            "password": password,
            "code": code,
        },
    )


def create_admin_and_get_token(client, role="super_admin", email="admin@example.com"):
    code = make_invitation_code(client, code=f"QR-{role.upper()[:8]}1", role=role)
    response = signup(client, code, email=email)
    assert response.status_code == 200, response.text
    return response.json()["access_token"], response.json()["user"]


def _floor_file(name="floor.png"):
    return (name, io.BytesIO(TINY_PNG_BYTES), "image/png")


def create_map_group(
    client,
    token,
    *,
    name="QuickRoute Mall Indoor Map",
    code=None,
    building_id=None,
    floors=None,
):
    """
    floors: list of dicts like {"title": ..., "floor": 0, "floor_label": "Ground Floor"}.
    Defaults to a standard 3-floor batch (0, 1, 2) when omitted.
    """

    if floors is None:
        floors = [
            {"title": "Ground Floor", "floor": 0, "floor_label": "Ground Floor"},
            {"title": "First Floor", "floor": 1, "floor_label": "First Floor"},
            {"title": "Second Floor", "floor": 2, "floor_label": "Second Floor"},
        ]

    import json

    data = {
        "name": name,
        "floors_json": json.dumps(floors),
    }
    if code:
        data["code"] = code
    if building_id:
        data["building_id"] = building_id

    files = [
        ("files", _floor_file(f"floor-{entry['floor']}.png")) for entry in floors
    ]

    return client.post(
        "/api/map-groups",
        data=data,
        files=files,
        headers=auth_headers(token),
    )


def add_floor(client, token, group_id, floor_entry):
    import json

    return client.post(
        f"/api/map-groups/{group_id}/floors",
        data={"floors_json": json.dumps([floor_entry])},
        files=[("files", _floor_file(f"floor-{floor_entry['floor']}.png"))],
        headers=auth_headers(token),
    )


def create_route_point(client, token, map_id, name, x, y, floor, point_type="hallway"):
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


# ---------------------------------------------------------
# 1-6: Basic multi-floor group creation
# ---------------------------------------------------------

def test_create_multi_floor_group_creates_one_group_and_three_maps(client):
    token, _ = create_admin_and_get_token(client, email="mg1@example.com")

    response = create_map_group(client, token, code="QRMALL-001")
    assert response.status_code == 201, response.text

    body = response.json()
    assert body["code"] == "QRMALL-001"
    assert body["name"] == "QuickRoute Mall Indoor Map"
    assert body["floor_count"] == 3
    assert len(body["floors"]) == 3

    # 3. Every floor shares one map_group_id.
    group_id = body["id"]
    assert all(f["map_group_id"] == group_id for f in body["floors"])
    assert all(f["map_group_code"] == "QRMALL-001" for f in body["floors"])

    # 4. Every floor shares one building_id.
    building_ids = {f["building_id"] for f in body["floors"]}
    assert len(building_ids) == 1

    # 5. Every floor map has a unique map_id.
    map_ids = {f["id"] for f in body["floors"]}
    assert len(map_ids) == 3

    # 6. Floor numbers remain distinct, sorted ascending.
    assert [f["floor"] for f in body["floors"]] == [0, 1, 2]
    assert [f["floor_label"] for f in body["floors"]] == [
        "Ground Floor", "First Floor", "Second Floor",
    ]


def test_group_listing_and_get_by_id_return_the_same_group(client):
    token, _ = create_admin_and_get_token(client, email="mg2@example.com")
    created = create_map_group(client, token, code="QRMALL-002").json()

    list_response = client.get("/api/map-groups", headers=auth_headers(token))
    assert list_response.status_code == 200
    assert any(g["id"] == created["id"] for g in list_response.json())

    get_response = client.get(
        f"/api/map-groups/{created['id']}", headers=auth_headers(token)
    )
    assert get_response.status_code == 200
    assert get_response.json()["code"] == "QRMALL-002"


# ---------------------------------------------------------
# 7-8: Duplicate rejection
# ---------------------------------------------------------

def test_duplicate_floor_number_in_same_batch_is_rejected(client):
    token, _ = create_admin_and_get_token(client, email="mg3@example.com")

    response = create_map_group(
        client, token, code="QRDUPFLOOR",
        floors=[
            {"title": "Ground", "floor": 0},
            {"title": "Also Ground", "floor": 0},
        ],
    )
    assert response.status_code == 400, response.text

    # Nothing should have been persisted — duplicate-floor validation runs
    # before any file is saved or any document is written.
    groups = client.get("/api/map-groups", headers=auth_headers(token)).json()
    assert all(g["code"] != "QRDUPFLOOR" for g in groups)


def test_duplicate_group_code_is_rejected(client):
    token, _ = create_admin_and_get_token(client, email="mg4@example.com")

    first = create_map_group(client, token, code="QRDUPCODE-1")
    assert first.status_code == 201

    second = create_map_group(
        client, token, code="QRDUPCODE-1",
        floors=[{"title": "Somewhere Else", "floor": 0}],
    )
    assert second.status_code == 409, second.text


# ---------------------------------------------------------
# 9-10: Adding a floor later reuses the group
# ---------------------------------------------------------

def test_adding_a_floor_later_reuses_the_same_group_and_code(client):
    token, _ = create_admin_and_get_token(client, email="mg5@example.com")
    group = create_map_group(client, token, code="QRMALL-005").json()

    add_response = add_floor(
        client, token, group["id"],
        {"title": "Third Floor", "floor": 3, "floor_label": "Third Floor"},
    )
    assert add_response.status_code == 201, add_response.text

    updated = add_response.json()
    assert updated["id"] == group["id"]
    assert updated["code"] == "QRMALL-005"  # 2. reuses the same group code
    assert updated["floor_count"] == 4

    # 10. Existing floors remain unchanged (same ids, same floors present).
    original_ids = {f["id"] for f in group["floors"]}
    updated_ids = {f["id"] for f in updated["floors"]}
    assert original_ids.issubset(updated_ids)
    assert [f["floor"] for f in updated["floors"]] == [0, 1, 2, 3]


def test_adding_a_floor_with_a_number_already_used_is_rejected(client):
    token, _ = create_admin_and_get_token(client, email="mg6@example.com")
    group = create_map_group(client, token, code="QRMALL-006").json()

    response = add_floor(
        client, token, group["id"],
        {"title": "Duplicate Ground", "floor": 0},
    )
    assert response.status_code == 409, response.text

    # The group must still have exactly its original 3 floors.
    refreshed = client.get(
        f"/api/map-groups/{group['id']}", headers=auth_headers(token)
    ).json()
    assert refreshed["floor_count"] == 3


# ---------------------------------------------------------
# 11: Rollback on partial failure
# ---------------------------------------------------------

def test_initial_group_upload_failure_rolls_back_everything(client):
    token, _ = create_admin_and_get_token(client, email="mg7@example.com")

    import json

    # Second file has a disallowed extension — save_upload_to_temporary_file
    # rejects it (ValueError -> 400) after the first (valid) file has
    # already been saved to temp storage, exercising the rollback path in
    # _save_floor_files.
    files = [
        ("files", _floor_file("floor-0.png")),
        ("files", ("floor-1.txt", io.BytesIO(b"not an image"), "text/plain")),
    ]
    data = {
        "name": "Should Not Exist",
        "code": "QRROLLBACK",
        "floors_json": json.dumps([
            {"title": "Ground", "floor": 0},
            {"title": "First", "floor": 1},
        ]),
    }

    response = client.post(
        "/api/map-groups", data=data, files=files, headers=auth_headers(token),
    )
    assert response.status_code == 400, response.text

    groups = client.get("/api/map-groups", headers=auth_headers(token)).json()
    assert all(g["code"] != "QRROLLBACK" for g in groups)

    maps = client.get("/api/maps", headers=auth_headers(token)).json()
    assert all(m["title"] not in ("Ground", "First") for m in maps)


# ---------------------------------------------------------
# 12-13: Deleting a floor vs. deleting a group
# ---------------------------------------------------------

def test_deleting_one_floor_does_not_delete_the_whole_group(client):
    token, _ = create_admin_and_get_token(client, email="mg8@example.com")
    group = create_map_group(client, token, code="QRMALL-008").json()
    floor_to_delete = group["floors"][0]["id"]

    delete_response = client.delete(
        f"/api/map-groups/{group['id']}/floors/{floor_to_delete}",
        headers=auth_headers(token),
    )
    assert delete_response.status_code == 200, delete_response.text

    refreshed = client.get(
        f"/api/map-groups/{group['id']}", headers=auth_headers(token)
    )
    assert refreshed.status_code == 200
    assert refreshed.json()["floor_count"] == 2
    assert all(f["id"] != floor_to_delete for f in refreshed.json()["floors"])


def test_deleting_a_group_cascades_to_every_floor(client):
    token, _ = create_admin_and_get_token(client, email="mg9@example.com")
    group = create_map_group(client, token, code="QRMALL-009").json()
    floor_ids = [f["id"] for f in group["floors"]]

    delete_response = client.delete(
        f"/api/map-groups/{group['id']}", headers=auth_headers(token),
    )
    assert delete_response.status_code == 200
    assert delete_response.json()["deleted_floor_count"] == 3

    assert (
        client.get(
            f"/api/map-groups/{group['id']}", headers=auth_headers(token)
        ).status_code
        == 404
    )

    for map_id in floor_ids:
        assert client.get(f"/api/maps/{map_id}").status_code == 404


# ---------------------------------------------------------
# 14: Old single-floor maps still work
# ---------------------------------------------------------

def test_old_single_floor_map_creation_still_works_ungrouped(client):
    token, _ = create_admin_and_get_token(client, role="global_manager", email="mg10@example.com")

    response = client.post(
        "/api/maps",
        json={"title": "Legacy Single Floor Map"},
        headers=auth_headers(token),
    )
    assert response.status_code == 201, response.text

    body = response.json()
    assert body["map_group_id"] is None
    assert body["map_group_code"] is None


# ---------------------------------------------------------
# 15-16: Backfill idempotency
# ---------------------------------------------------------

def test_backfill_map_groups_creates_one_floor_group_and_is_idempotent(client):
    token, _ = create_admin_and_get_token(client, email="mg11@example.com")

    legacy_map = client.post(
        "/api/maps",
        json={"title": "Old Map", "campus": "Old Campus"},
        headers=auth_headers(token),
    ).json()
    assert legacy_map["map_group_id"] is None

    first_run = client.post(
        "/api/maintenance/backfill-map-groups", headers=auth_headers(token),
    )
    assert first_run.status_code == 200, first_run.text
    assert first_run.json()["groups_created"] == 1
    assert first_run.json()["maps_updated"] == 1

    refreshed_map = client.get(f"/api/maps/{legacy_map['id']}").json()
    assert refreshed_map["map_group_id"] is not None
    assert refreshed_map["map_group_code"] is not None
    assert refreshed_map["floor"] == 0  # defaulted since it had none

    # 16. Idempotent — a second run touches nothing new.
    second_run = client.post(
        "/api/maintenance/backfill-map-groups", headers=auth_headers(token),
    )
    assert second_run.status_code == 200
    assert second_run.json()["groups_created"] == 0
    assert second_run.json()["maps_updated"] == 0

    still_same_group = client.get(f"/api/maps/{legacy_map['id']}").json()
    assert still_same_group["map_group_id"] == refreshed_map["map_group_id"]


# ---------------------------------------------------------
# 17: RoutePoints stay isolated by floor map
# ---------------------------------------------------------

def test_route_points_stay_isolated_per_floor_map(client):
    token, _ = create_admin_and_get_token(client, email="mg12@example.com")
    group = create_map_group(client, token, code="QRMALL-012").json()
    floor0_id = group["floors"][0]["id"]
    floor1_id = group["floors"][1]["id"]

    create_route_point(client, token, floor0_id, "Floor 0 Point", 10, 10, floor=0)
    create_route_point(client, token, floor1_id, "Floor 1 Point A", 20, 20, floor=1)
    create_route_point(client, token, floor1_id, "Floor 1 Point B", 30, 30, floor=1)

    floor0_points = client.get(
        "/api/route-points", params={"map_id": floor0_id}
    ).json()
    floor1_points = client.get(
        "/api/route-points", params={"map_id": floor1_id}
    ).json()

    assert len(floor0_points) == 1
    assert len(floor1_points) == 2
    assert all(p["map_id"] == floor0_id for p in floor0_points)
    assert all(p["map_id"] == floor1_id for p in floor1_points)


# ---------------------------------------------------------
# 18: Hallway cross-floor edges are rejected; stairs/elevator allowed
# ---------------------------------------------------------

def test_hallway_edge_between_two_different_floor_maps_is_rejected(client):
    token, _ = create_admin_and_get_token(client, email="mg13@example.com")
    group = create_map_group(client, token, code="QRMALL-013").json()
    floor0_id = group["floors"][0]["id"]
    floor1_id = group["floors"][1]["id"]

    point_a = create_route_point(client, token, floor0_id, "Point A", 10, 10, floor=0)
    point_b = create_route_point(client, token, floor1_id, "Point B", 10, 10, floor=1)

    response = client.post(
        "/api/route-edges",
        json={
            "map_id": floor0_id,
            "from_point_id": point_a["id"],
            "to_point_id": point_b["id"],
            "edge_type": "walkway",
        },
        headers=auth_headers(token),
    )
    assert response.status_code == 400, response.text


def test_stairs_edge_between_two_floors_of_the_same_group_is_allowed(client):
    token, _ = create_admin_and_get_token(client, email="mg14@example.com")
    group = create_map_group(client, token, code="QRMALL-014").json()
    floor0_id = group["floors"][0]["id"]
    floor1_id = group["floors"][1]["id"]

    point_a = create_route_point(client, token, floor0_id, "Stairs A", 10, 10, floor=0)
    point_b = create_route_point(client, token, floor1_id, "Stairs B", 10, 10, floor=1)

    response = client.post(
        "/api/route-edges",
        json={
            "map_id": floor0_id,
            "from_point_id": point_a["id"],
            "to_point_id": point_b["id"],
            "edge_type": "stairs",
            "distance_override": 5,
        },
        headers=auth_headers(token),
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["map_id"] == floor0_id
    assert body["to_map_id"] == floor1_id


def test_stairs_edge_across_unrelated_maps_without_a_shared_group_is_rejected(client):
    token, _ = create_admin_and_get_token(client, email="mg15@example.com")

    map_a = client.post(
        "/api/maps", json={"title": "Unrelated Map A"}, headers=auth_headers(token),
    ).json()
    map_b = client.post(
        "/api/maps", json={"title": "Unrelated Map B"}, headers=auth_headers(token),
    ).json()

    point_a = create_route_point(client, token, map_a["id"], "Point A", 5, 5, floor=0)
    point_b = create_route_point(client, token, map_b["id"], "Point B", 5, 5, floor=1)

    response = client.post(
        "/api/route-edges",
        json={
            "map_id": map_a["id"],
            "from_point_id": point_a["id"],
            "to_point_id": point_b["id"],
            "edge_type": "elevator",
            "distance_override": 5,
        },
        headers=auth_headers(token),
    )
    assert response.status_code == 400, response.text


# ---------------------------------------------------------
# 19: Rooms resolve the correct floor map
# ---------------------------------------------------------

def test_room_resolves_map_group_id_and_floor_from_its_map(client):
    token, _ = create_admin_and_get_token(client, email="mg16@example.com")
    group = create_map_group(client, token, code="QRMALL-016").json()
    floor1 = group["floors"][1]

    response = client.post(
        "/api/rooms",
        json={
            "building_id": group["building_id"],
            "name_en": "Super-Pharm",
            "floor": 1,
            "map_id": floor1["id"],
            "x": 50,
            "y": 60,
        },
        headers=auth_headers(token),
    )
    assert response.status_code == 201, response.text

    body = response.json()
    assert body["map_id"] == floor1["id"]
    assert body["floor"] == 1
    assert body["map_group_id"] == group["id"]


# ---------------------------------------------------------
# 20: Location Codes resolve an exact floor and RoutePoint
# ---------------------------------------------------------

def test_location_code_resolves_exact_floor_map_and_route_point(client):
    token, _ = create_admin_and_get_token(client, email="mg17@example.com")
    group = create_map_group(client, token, code="QRMALL-017").json()
    floor0 = group["floors"][0]

    entrance = create_route_point(
        client, token, floor0["id"], "Main Entrance", 5, 5, floor=0,
        point_type="entrance",
    )

    create_response = client.post(
        "/api/location-codes",
        json={
            "code": "QRMALL-ENTRANCE-01",
            "building_id": group["building_id"],
            "map_id": floor0["id"],
            "route_point_id": entrance["id"],
            "label": "Main Entrance",
        },
        headers=auth_headers(token),
    )
    assert create_response.status_code == 201, create_response.text
    assert create_response.json()["map_group_id"] == group["id"]
    assert create_response.json()["floor"] == 0

    resolved = client.get("/api/location-codes/resolve/QRMALL-ENTRANCE-01")
    assert resolved.status_code == 200
    resolved_body = resolved.json()
    assert resolved_body["map_id"] == floor0["id"]
    assert resolved_body["route_point_id"] == entrance["id"]
    assert resolved_body["map_group_id"] == group["id"]
    assert resolved_body["floor"] == 0
