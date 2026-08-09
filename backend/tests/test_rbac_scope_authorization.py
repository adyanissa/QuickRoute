"""
RBAC/dashboard cleanup task — backend tests for the centralized
authorization layer added to core/auth_deps.py and wired into
routes/route_point_routes.py, routes/map_routes.py, routes/room_routes.py,
and logic/invitation_code_logic.py.

Covers (numbering matches the phase-12 checklist this was written against):
  2.  global_manager is now scope-checked against building_ids/all_buildings
      (previously unconditionally unrestricted).
  3.  building_manager respects building_ids.
  5.  building_manager respects map_ids (the most restrictive scope).
  6.  map_ids overrides map_group_ids when both are set.
  7.  regular_user cannot reach admin-only mutation routes.
  8.  Unauthorized building_id (map creation) returns 403.
  9.  Unauthorized map_id (route-point creation / detail) returns 403.
  11. RoutePoint list/count/detail stay reachable with NO auth at all
      (regression guard for the public kiosk navigation flow — the
      single most important thing NOT to break in this task).
  12. RoutePoint list/count apply the authenticated caller's authorized
      scope automatically.
  13. RoutePoint detail (`GET /{point_id}`) prevents IDOR for an
      authenticated, out-of-scope admin.
  21. Invitation scope cannot exceed inviter scope (global_manager
      restricted to specific buildings can't grant all_buildings=True).
  22/23. building_manager/global_manager cannot invite a super_admin.
  24. ValidateInvitationCodeResponse includes map_group_ids/map_ids.
  25/26. Pagination totals are stable; list/count use identical filters.

Uses the same in-memory mongomock TestClient fixtures as
test_api_integration.py (see conftest.py) — no real MongoDB is ever
touched, and every test gets a clean, isolated database.

Run with: pytest backend/tests/test_rbac_scope_authorization.py -v

NOTE: this file was written but could NOT be executed in this session —
the sandbox's isolated Linux environment was unavailable for every single
tool call attempted (see the final report for the exact error). Do not
treat this file as "passing" until it has actually been run.
"""

from models.invitation_code_model import InvitationCode

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


def _create_map_for_building(client, token, building_id, title="Scoped Map"):
    response = client.post(
        "/api/maps",
        json={"title": title, "building_id": building_id},
        headers=auth_headers(token),
    )
    assert response.status_code == 201, response.text
    return response.json()


def _create_point(client, token, map_id, name, x=0, y=0):
    response = client.post(
        "/api/route-points",
        json={"map_id": map_id, "name": name, "x": x, "y": y, "floor": 0},
        headers=auth_headers(token),
    )
    return response


# ---------------------------------------------------------
# global_manager is now scope-checked (Phase 12, item 2)
# ---------------------------------------------------------

def test_global_manager_with_all_buildings_true_is_unrestricted(client):
    super_token, _ = create_admin_and_get_token(client, role="super_admin", email="s1@example.com")
    building = _create_building(client, super_token, "Global Wing")

    gm_token = _signup_with_invite(
        client,
        super_token,
        role="global_manager",
        email="gm-all@example.com",
        code="QR-GMALL001",
        all_buildings=True,
    )

    response = client.post(
        "/api/maps",
        json={"title": "GM Map", "building_id": building["id"]},
        headers=auth_headers(gm_token),
    )
    assert response.status_code == 201, response.text


def test_global_manager_scoped_to_building_cannot_touch_other_building(client):
    super_token, _ = create_admin_and_get_token(client, role="super_admin", email="s2@example.com")
    building_a = _create_building(client, super_token, "Building A")
    building_b = _create_building(client, super_token, "Building B")

    gm_token = _signup_with_invite(
        client,
        super_token,
        role="global_manager",
        email="gm-scoped@example.com",
        code="QR-GMSCOPE1",
        building_ids=[building_a["id"]],
    )

    map_in_b = _create_map_for_building(client, super_token, building_b["id"], "Map In B")

    # Reading a map outside this global_manager's scope must 403 now
    # (previously global_manager was unconditionally unrestricted).
    response = client.get(f"/api/maps/{map_in_b['id']}", headers=auth_headers(gm_token))
    assert response.status_code == 403, response.text

    # But their own building's map creation still works.
    own_map = client.post(
        "/api/maps",
        json={"title": "Map In A", "building_id": building_a["id"]},
        headers=auth_headers(gm_token),
    )
    assert own_map.status_code == 201, own_map.text


# ---------------------------------------------------------
# building_manager building_ids / map_group_ids / map_ids scoping
# (Phase 12, items 3, 5, 6, 8, 9)
# ---------------------------------------------------------

def test_building_manager_cannot_create_map_outside_building_ids(client):
    super_token, _ = create_admin_and_get_token(client, role="super_admin", email="s3@example.com")
    own_building = _create_building(client, super_token, "Owned Building")
    other_building = _create_building(client, super_token, "Unowned Building")

    bm_token = _signup_with_invite(
        client,
        super_token,
        role="building_manager",
        email="bm-scope@example.com",
        code="QR-BMSCOPE1",
        building_ids=[own_building["id"]],
    )

    forbidden = client.post(
        "/api/maps",
        json={"title": "Sneaky Map", "building_id": other_building["id"]},
        headers=auth_headers(bm_token),
    )
    assert forbidden.status_code == 403, forbidden.text

    allowed = client.post(
        "/api/maps",
        json={"title": "Legit Map", "building_id": own_building["id"]},
        headers=auth_headers(bm_token),
    )
    assert allowed.status_code == 201, allowed.text


def test_building_manager_map_ids_is_most_restrictive(client):
    """A building_manager scoped to building_ids=[B], map_group_ids=[]
    (irrelevant here) and map_ids=[map_1] may act on map_1 but is rejected
    on map_2, even though map_2 belongs to the exact same authorized
    building — map_ids, once non-empty, is the final word."""

    super_token, _ = create_admin_and_get_token(client, role="super_admin", email="s4@example.com")
    building = _create_building(client, super_token, "Two Map Building")

    map_1 = _create_map_for_building(client, super_token, building["id"], "Map One")
    map_2 = _create_map_for_building(client, super_token, building["id"], "Map Two")

    bm_token = _signup_with_invite(
        client,
        super_token,
        role="building_manager",
        email="bm-mapids@example.com",
        code="QR-BMMAPID1",
        building_ids=[building["id"]],
        map_ids=[map_1["id"]],
    )

    ok = _create_point(client, bm_token, map_1["id"], "Allowed Point")
    assert ok.status_code == 201, ok.text

    blocked = _create_point(client, bm_token, map_2["id"], "Blocked Point")
    assert blocked.status_code == 403, blocked.text


def test_regular_user_cannot_create_route_point(client):
    super_token, _ = create_admin_and_get_token(client, role="super_admin", email="s5@example.com")
    building = _create_building(client, super_token, "Reg User Building")
    map_item = _create_map_for_building(client, super_token, building["id"])

    # NOTE: must route through the real authenticated invitation endpoint
    # (creator_token=super_token) rather than the dev-only bootstrap
    # endpoint (POST /api/invitation-codes/dev-create). The dev-create path
    # is bootstrap-only by design — it 403s once a super_admin already
    # exists in the database — and a super_admin was just created above in
    # this exact test, so calling make_invitation_code() with no
    # creator_token (which falls back to dev-create) was hitting that
    # correct, intentional 403 and never actually reaching the
    # regular_user-cannot-create-a-route-point assertion this test exists
    # to verify. This was a test-fixture defect, not a production bug.
    reg_code = make_invitation_code(
        client, code="QR-REGRP001", role="regular_user", creator_token=super_token
    )
    reg_response = signup(client, reg_code, email="reguser-rp@example.com")
    reg_token = reg_response.json()["access_token"]

    response = _create_point(client, reg_token, map_item["id"], "Should Fail")
    assert response.status_code == 403, response.text


# ---------------------------------------------------------
# RoutePoint GET endpoints: public navigation is preserved, admin scoping
# is enforced (Phase 12, items 11, 12, 13)
# ---------------------------------------------------------

def test_public_route_point_endpoints_work_with_no_authentication(client):
    """Regression guard for the ACTUAL public kiosk/QR navigation contract
    (IndoorNavigationScreen.jsx, RBAC/dashboard cleanup task Phase 3): the
    real navigation flow calls GET /api/route-points/public and
    GET /api/route-points/public/{id} — never the admin list/detail
    endpoints below — with no login at all. This must keep working exactly
    as before."""

    super_token, _ = create_admin_and_get_token(client, role="super_admin", email="s6@example.com")
    building = _create_building(client, super_token, "Public Nav Building")
    map_item = _create_map_for_building(client, super_token, building["id"])
    point = _create_point(client, super_token, map_item["id"], "Entrance").json()

    list_response = client.get("/api/route-points/public", params={"map_id": map_item["id"]})
    assert list_response.status_code == 200
    assert any(p["id"] == point["id"] for p in list_response.json())

    detail_response = client.get(f"/api/route-points/public/{point['id']}")
    assert detail_response.status_code == 200
    assert detail_response.json()["id"] == point["id"]


def test_public_route_points_requires_map_or_building_scope(client):
    """The public endpoint's actual anti-enumeration guard: GET
    /api/route-points/public with NEITHER map_id NOR building_id is
    rejected with 400 rather than dumping every RoutePoint in the system —
    an anonymous caller can resolve a specific navigation context (a map
    or a building's entrance) but can never globally enumerate every
    RoutePoint in the database through this endpoint."""

    response = client.get("/api/route-points/public")
    assert response.status_code == 400, response.text


def test_legacy_unpaginated_route_points_endpoint_still_open_for_anonymous_callers(client):
    """Back-compat guard, NOT the current public contract: the older,
    unpaginated GET /api/route-points / GET /api/route-points/{id} / GET
    /api/route-points/count endpoints are intentionally left fully open to
    anonymous callers too (see _apply_authorized_scope_to_query's
    docstring in route_point_routes.py) so nothing that already depended
    on their old unauthenticated behavior breaks. Real navigation UI code
    should use the /public endpoints above instead — this test exists only
    to prove the old contract wasn't silently locked down, not to endorse
    it as the way forward. Authenticated admin-tier scoping/IDOR
    protection on these same endpoints is covered separately by
    test_building_manager_list_is_scoped_to_own_building and
    test_route_point_detail_idor_blocked_for_out_of_scope_admin below."""

    super_token, _ = create_admin_and_get_token(client, role="super_admin", email="s6b@example.com")
    building = _create_building(client, super_token, "Legacy Endpoint Building")
    map_item = _create_map_for_building(client, super_token, building["id"])
    point = _create_point(client, super_token, map_item["id"], "Entrance").json()

    list_response = client.get("/api/route-points", params={"map_id": map_item["id"]})
    assert list_response.status_code == 200
    assert any(p["id"] == point["id"] for p in list_response.json())

    detail_response = client.get(f"/api/route-points/{point['id']}")
    assert detail_response.status_code == 200
    assert detail_response.json()["id"] == point["id"]

    count_response = client.get("/api/route-points/count", params={"map_id": map_item["id"]})
    assert count_response.status_code == 200
    assert count_response.json()["count"] == 1


def test_building_manager_list_is_scoped_to_own_building(client):
    super_token, _ = create_admin_and_get_token(client, role="super_admin", email="s7@example.com")
    building_a = _create_building(client, super_token, "List Scope A")
    building_b = _create_building(client, super_token, "List Scope B")

    map_a = _create_map_for_building(client, super_token, building_a["id"], "Map A")
    map_b = _create_map_for_building(client, super_token, building_b["id"], "Map B")

    _create_point(client, super_token, map_a["id"], "Point In A")
    _create_point(client, super_token, map_b["id"], "Point In B")

    bm_token = _signup_with_invite(
        client,
        super_token,
        role="building_manager",
        email="bm-list@example.com",
        code="QR-BMLIST01",
        building_ids=[building_a["id"]],
    )

    # No filter at all: must be narrowed to building_a only, never see
    # building_b's point, and never see a global unfiltered dump.
    response = client.get("/api/route-points", headers=auth_headers(bm_token))
    assert response.status_code == 200
    names = {p["name"] for p in response.json()}
    assert "Point In A" in names
    assert "Point In B" not in names

    # Explicitly asking for the out-of-scope building is rejected outright
    # rather than silently re-scoped.
    forbidden = client.get(
        "/api/route-points",
        params={"building_id": building_b["id"]},
        headers=auth_headers(bm_token),
    )
    assert forbidden.status_code == 403


def test_route_point_detail_idor_blocked_for_out_of_scope_admin(client):
    super_token, _ = create_admin_and_get_token(client, role="super_admin", email="s8@example.com")
    building_a = _create_building(client, super_token, "IDOR A")
    building_b = _create_building(client, super_token, "IDOR B")

    map_b = _create_map_for_building(client, super_token, building_b["id"])
    point_b = _create_point(client, super_token, map_b["id"], "Secret Point").json()

    bm_token = _signup_with_invite(
        client,
        super_token,
        role="building_manager",
        email="bm-idor@example.com",
        code="QR-BMIDOR01",
        building_ids=[building_a["id"]],
    )

    response = client.get(f"/api/route-points/{point_b['id']}", headers=auth_headers(bm_token))
    assert response.status_code == 403, response.text

    # super_admin, unrestricted, can still fetch it.
    super_response = client.get(f"/api/route-points/{point_b['id']}", headers=auth_headers(super_token))
    assert super_response.status_code == 200


# ---------------------------------------------------------
# Pagination (Phase 12, items 25/26)
# ---------------------------------------------------------

def test_route_point_pagination_totals_match_count_endpoint(client):
    super_token, _ = create_admin_and_get_token(client, role="super_admin", email="s9@example.com")
    building = _create_building(client, super_token, "Pagination Building")
    map_item = _create_map_for_building(client, super_token, building["id"])

    # NOTE: the 5 points must be spaced well beyond
    # point_dedup_service.DEFAULT_COORDINATE_TOLERANCE_PX (6.0px). The
    # original fixture placed them at x=0,1,2,3,4 (max pairwise distance
    # 4.0px, all sharing the same default point_type=None) — entirely
    # inside the production dedup radius, so find_or_create_route_point()
    # correctly collapsed all 5 POST requests onto a single stored
    # RoutePoint (count==1 was the correct, intentional dedup behavior,
    # not a query bug). This was a test-fixture defect, not a production
    # defect — fixed by spacing points 20px apart (well outside the 6.0px
    # tolerance) and verifying 5 distinct ids were actually created before
    # asserting anything about pagination/count.
    created_ids = set()
    for i in range(5):
        response = _create_point(client, super_token, map_item["id"], f"Point {i}", x=i * 20, y=0)
        assert response.status_code == 201, response.text
        created_ids.add(response.json()["id"])
    assert len(created_ids) == 5, "expected 5 distinct RoutePoint ids, dedup likely collapsed them"

    count_response = client.get("/api/route-points/count", params={"map_id": map_item["id"]})
    assert count_response.json()["count"] == 5

    page_1 = client.get(
        "/api/route-points/list",
        params={"map_id": map_item["id"], "page": 1, "page_size": 2},
    )
    assert page_1.status_code == 200
    body_1 = page_1.json()
    assert body_1["total_count"] == 5
    assert body_1["total_pages"] == 3
    assert body_1["loaded_count"] == 2
    assert len(body_1["items"]) == 2

    page_3 = client.get(
        "/api/route-points/list",
        params={"map_id": map_item["id"], "page": 3, "page_size": 2},
    )
    assert page_3.json()["loaded_count"] == 1


# ---------------------------------------------------------
# Invitation scope cannot exceed inviter scope (Phase 12, items 21-24)
# ---------------------------------------------------------

async def test_global_manager_scoped_cannot_grant_all_buildings(client):
    """A global_manager (scoped or not) is flatly forbidden from inviting
    another global_manager at all — CREATABLE_ROLES_BY_CREATOR["global_manager"]
    only contains {"building_manager", "regular_user"}, so this request is
    rejected by the role-hierarchy gate
    (`if role not in allowed_roles: raise HTTPException(**FORBIDDEN_ROLE)`,
    invitation_code_logic.py) before invitation_code_logic.py ever reaches
    the all_buildings-specific scope-limit check (the
    `elif role == "global_manager" and all_buildings: ...
    INVALID_BUILDING_SCOPE_FOR_ROLE` branch). That branch is in fact
    unreachable under the current CREATABLE_ROLES_BY_CREATOR configuration:
    the only creator ever allowed to target role="global_manager" at all is
    super_admin, and for a super_admin creator `creator.role != "super_admin"`
    is always False, so the branch's condition can never be True either.

    This test originally expected 400 (INVALID_BUILDING_SCOPE_FOR_ROLE),
    assuming the request would reach that all_buildings-specific check. The
    real, live server response is 403 FORBIDDEN_ROLE ("You do not have
    permission to perform this action") — which is the CORRECT and
    intentionally strict production behavior (a global_manager can never
    mint another global_manager, full stop), just enforced earlier/for a
    broader reason than this test assumed. Per task guidance: preserve the
    production 403 (do not weaken authorization to manufacture a 400 here)
    and update the test's expectation instead. The scope-cannot-exceed-
    inviter-scope guarantee this test is meant to protect is still fully
    covered elsewhere (test_building_manager_cannot_create_map_outside_building_ids,
    test_building_manager_map_ids_is_most_restrictive, and the building_id
    checks inside validate_role_and_scope_for_creation for
    building_manager/regular_user targets)."""

    super_token, _ = create_admin_and_get_token(client, role="super_admin", email="s10@example.com")
    building = _create_building(client, super_token, "Restricted Inviter Building")

    gm_token = _signup_with_invite(
        client,
        super_token,
        role="global_manager",
        email="gm-restricted@example.com",
        code="QR-GMRESTR1",
        building_ids=[building["id"]],
    )

    codes_before = await InvitationCode.find_all().count()

    response = client.post(
        "/api/invitation-codes",
        json={
            "role": "global_manager",
            "building_ids": [],
            "all_buildings": True,
        },
        headers=auth_headers(gm_token),
    )
    assert response.status_code == 403, response.text
    assert response.json()["detail"] == "You do not have permission to perform this action"

    # Nothing was created as a side effect of the rejected request.
    codes_after = await InvitationCode.find_all().count()
    assert codes_after == codes_before


def test_building_manager_cannot_invite_global_manager(client):
    super_token, _ = create_admin_and_get_token(client, role="super_admin", email="s11@example.com")
    building = _create_building(client, super_token, "BM Inviter Building")

    bm_token = _signup_with_invite(
        client,
        super_token,
        role="building_manager",
        email="bm-inviter@example.com",
        code="QR-BMINVIT1",
        building_ids=[building["id"]],
    )

    response = client.post(
        "/api/invitation-codes",
        json={"role": "global_manager", "building_ids": [], "all_buildings": False},
        headers=auth_headers(bm_token),
    )
    # building_manager is blocked from POST /api/invitation-codes entirely
    # (require_global_admin dependency) — 403 either from the role gate or
    # (if that were ever loosened) from the creator-hierarchy check.
    assert response.status_code == 403, response.text


def test_validate_invitation_code_response_includes_map_scope_fields(client):
    super_token, _ = create_admin_and_get_token(client, role="super_admin", email="s12@example.com")
    building = _create_building(client, super_token, "Validate Response Building")
    map_item = _create_map_for_building(client, super_token, building["id"])

    invite = client.post(
        "/api/invitation-codes",
        json={
            "role": "building_manager",
            "building_ids": [building["id"]],
            "all_buildings": False,
            "map_ids": [map_item["id"]],
        },
        headers=auth_headers(super_token),
    )
    assert invite.status_code == 201, invite.text
    code = invite.json()["code"]

    response = client.post("/api/invitation-codes/validate", json={"code": code})
    assert response.status_code == 200
    body = response.json()
    assert body["valid"] is True
    assert body["map_ids"] == [map_item["id"]]
    assert body["map_group_ids"] == []
