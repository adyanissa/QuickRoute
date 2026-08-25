"""
Explicit RBAC/scope authorization tests for the Auto Connect Destinations
endpoints:
  POST /api/route-edges/auto-connect-destinations/preview

Kept deliberately separate from tests/test_auto_connect_destinations.py and
tests/test_auto_connect_corridor_types.py, which use a super_admin token for
every test (bypassing scope checks) so they can focus purely on candidate-
selection/reason-code business logic. This file exists specifically to prove
the authorization boundary itself, following the same
_create_building/_invite_and_signup/_signup_with_invite pattern already
established in tests/test_rbac_scope_authorization.py.

Covers:
  1. An authorized, in-scope global_manager CAN preview Auto Connect for a
     map inside their assigned building_ids.
  2. An out-of-scope global_manager (same role, wrong building_ids) gets 403
     with the exact FORBIDDEN_MAP_SCOPE detail (core/errors.py).
  3. An anonymous caller (no Authorization header) gets 401, matching the
     existing NOT_AUTHENTICATED convention (core/auth_deps.py).

Run with: pytest backend/tests/test_auto_connect_authorization.py -v

NOTE: this file was written but could NOT be executed in this session —
the sandbox's isolated Linux environment was unavailable for every tool call
attempted. Do not treat this file as "passing" until it has actually been run.
"""

from tests.test_api_integration import auth_headers, create_admin_and_get_token, signup


PREVIEW_URL = "/api/route-edges/auto-connect-destinations/preview"


# ---------------------------------------------------------
# Local helpers (same pattern as tests/test_rbac_scope_authorization.py)
# ---------------------------------------------------------

def _create_building(client, token, name_en):
    response = client.post(
        "/api/locations/buildings",
        json={"name_en": name_en},
        headers=auth_headers(token),
    )
    assert response.status_code == 201, response.text
    return response.json()


def _invite_and_signup(
    client,
    creator_token,
    *,
    role,
    building_ids=None,
    all_buildings=False,
    map_group_ids=None,
    map_ids=None,
    email,
    code,
):
    response = client.post(
        "/api/invitation-codes",
        json={
            "role": role,
            "building_ids": building_ids or [],
            "all_buildings": all_buildings,
            "map_group_ids": map_group_ids or [],
            "map_ids": map_ids or [],
        },
        headers=auth_headers(creator_token),
    )
    return response, code, email


def _signup_with_invite(client, creator_token, *, role, email, code, **scope_kwargs):
    invite_response, code, email = _invite_and_signup(
        client, creator_token, role=role, email=email, code=code, **scope_kwargs
    )
    assert invite_response.status_code == 201, invite_response.text
    minted_code = invite_response.json()["code"]
    signup_response = signup(client, minted_code, email=email)
    assert signup_response.status_code == 200, signup_response.text
    return signup_response.json()["access_token"]


def _create_map(client, token, building_id, title="Auto Connect Scope Map"):
    response = client.post(
        "/api/maps",
        json={"title": title, "building_id": building_id},
        headers=auth_headers(token),
    )
    assert response.status_code == 201, response.text
    return response.json()


def _create_point(client, token, map_id, name, x, y, point_type="hallway"):
    response = client.post(
        "/api/route-points",
        json={"map_id": map_id, "name": name, "x": x, "y": y, "point_type": point_type},
        headers=auth_headers(token),
    )
    assert response.status_code == 201, response.text
    return response.json()


# ---------------------------------------------------------
# 1. Authorized, in-scope manager CAN preview.
# ---------------------------------------------------------

def test_scoped_global_manager_can_preview_in_scope_map(client):
    super_token, _ = create_admin_and_get_token(client, role="super_admin", email="authz-s1@example.com")
    building = _create_building(client, super_token, "Authz In-Scope Building")
    map_item = _create_map(client, super_token, building["id"])
    _create_point(client, super_token, map_item["id"], "Main Hallway", 100, 100, point_type="hallway")
    _create_point(client, super_token, map_item["id"], "Conference Room", 130, 100, point_type="room")

    gm_token = _signup_with_invite(
        client,
        super_token,
        role="global_manager",
        email="authz-gm-inscope@example.com",
        code="QR-AUTHZIN001",
        building_ids=[building["id"]],
    )

    response = client.post(
        PREVIEW_URL,
        json={"map_id": map_item["id"]},
        headers=auth_headers(gm_token),
    )
    assert response.status_code == 200, response.text
    assert len(response.json()["proposals"]) >= 1


# ---------------------------------------------------------
# 2. Out-of-scope manager gets 403 (FORBIDDEN_MAP_SCOPE).
# ---------------------------------------------------------

def test_out_of_scope_manager_cannot_preview(client):
    super_token, _ = create_admin_and_get_token(client, role="super_admin", email="authz-s2@example.com")
    in_scope_building = _create_building(client, super_token, "Authz Manager's Building")
    other_building = _create_building(client, super_token, "Authz Other Building")
    other_map = _create_map(client, super_token, other_building["id"], title="Other Building Map")
    _create_point(client, super_token, other_map["id"], "Other Hallway", 100, 100, point_type="hallway")
    _create_point(client, super_token, other_map["id"], "Other Room", 130, 100, point_type="room")

    gm_token = _signup_with_invite(
        client,
        super_token,
        role="global_manager",
        email="authz-gm-outscope@example.com",
        code="QR-AUTHZOUT001",
        building_ids=[in_scope_building["id"]],
    )

    response = client.post(
        PREVIEW_URL,
        json={"map_id": other_map["id"]},
        headers=auth_headers(gm_token),
    )
    assert response.status_code == 403, response.text
    assert response.json()["detail"] == "You do not have permission to access this map"


# ---------------------------------------------------------
# 3. Anonymous caller gets 401 (NOT_AUTHENTICATED).
# ---------------------------------------------------------

def test_anonymous_caller_cannot_preview(client):
    super_token, _ = create_admin_and_get_token(client, role="super_admin", email="authz-s3@example.com")
    building = _create_building(client, super_token, "Authz Anonymous Building")
    map_item = _create_map(client, super_token, building["id"])
    _create_point(client, super_token, map_item["id"], "Anon Hallway", 100, 100, point_type="hallway")
    _create_point(client, super_token, map_item["id"], "Anon Room", 130, 100, point_type="room")

    response = client.post(PREVIEW_URL, json={"map_id": map_item["id"]})
    assert response.status_code == 401, response.text
    assert response.json()["detail"] == "Not authenticated"
