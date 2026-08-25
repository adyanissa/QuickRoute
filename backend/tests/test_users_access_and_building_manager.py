"""
Final administrative user/access model — backend tests.

Covers, in one place, the four product requirements this feature exists
for:

  A. full_name genuinely round-trips signup -> MongoDB -> login -> /me
     (verification of the EXISTING field, not a new one).
  B. Users & Access: authorization, role hierarchy, super-admin
     protection, last-super-admin protection, self-delete protection.
  C. Invitation codes: regular_user is no longer an admin-creatable role,
     and a Building Manager invitation assigns exactly one building.
  D. Building Manager as a FULL operational administrator of ONE building
     — including the mandatory SIBLING BUILDING test, where two buildings
     share the same site and only one is assigned.

Uses the same in-memory mongomock fixtures as the rest of the suite.

Run with: pytest backend/tests/test_users_access_and_building_manager.py -v
"""

import pytest

from tests.test_api_integration import (
    auth_headers,
    create_admin_and_get_token,
    make_invitation_code,
    signup,
)
from tests.test_rbac_scope_authorization import _create_building


# ─────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────


def _invite(client, creator_token, *, role, building_ids=None, all_buildings=False):
    return client.post(
        "/api/invitation-codes",
        json={
            "role": role,
            "building_ids": building_ids or [],
            "all_buildings": all_buildings,
            "map_group_ids": [],
            "map_ids": [],
        },
        headers=auth_headers(creator_token),
    )


def _invite_and_signup(client, creator_token, *, role, email, full_name, **scope):
    response = _invite(client, creator_token, role=role, **scope)
    assert response.status_code == 201, response.text
    code = response.json()["code"]
    signed = signup(client, code, email=email, full_name=full_name)
    assert signed.status_code == 200, signed.text
    return signed.json()


def _create_map(client, token, building_id, title):
    response = client.post(
        "/api/maps",
        json={"title": title, "building_id": building_id},
        headers=auth_headers(token),
    )
    assert response.status_code == 201, response.text
    return response.json()


def _same_site_two_buildings(client):
    """THE fixture this feature is really about: one site, two buildings,
    a manager assigned to only one of them."""
    token, _admin = create_admin_and_get_token(client)

    assigned = client.post(
        "/api/locations/buildings",
        json={"name_en": "Engineering Building", "campus": "Meir Hospital"},
        headers=auth_headers(token),
    ).json()
    sibling = client.post(
        "/api/locations/buildings",
        json={"name_en": "Emergency Wing", "campus": "Meir Hospital"},
        headers=auth_headers(token),
    ).json()

    manager = _invite_and_signup(
        client,
        token,
        role="building_manager",
        building_ids=[assigned["id"]],
        email="building.manager@example.com",
        full_name="Ahmad Ali",
    )
    return token, assigned, sibling, manager["access_token"], manager["user"]


# ─────────────────────────────────────────────────────────────────────────
# A. Full name round-trip (existing field — verification, not a new one)
# ─────────────────────────────────────────────────────────────────────────


def test_full_name_persists_through_signup_login_and_me(client):
    token, _ = create_admin_and_get_token(client)

    signed = _invite_and_signup(
        client,
        token,
        role="global_manager",
        email="layal@example.com",
        full_name="Layal Zoubi",
    )

    # 1. the signup response carries it
    assert signed["user"]["full_name"] == "Layal Zoubi"

    # 2. it is genuinely stored (a fresh login re-reads the document)
    login = client.post(
        "/api/auth/login",
        json={"email": "layal@example.com", "password": "password123"},
    )
    assert login.status_code == 200, login.text
    assert login.json()["user"]["full_name"] == "Layal Zoubi"
    assert login.json()["user"]["role"] == "global_manager"

    # 3. /me returns it for the authenticated session
    me = client.get(
        "/api/auth/me", headers=auth_headers(login.json()["access_token"])
    )
    assert me.status_code == 200
    assert me.json()["full_name"] == "Layal Zoubi"

    # 4. and no password material is ever returned anywhere
    for payload in (signed["user"], login.json()["user"], me.json()):
        assert "password" not in payload


def test_two_different_accounts_report_their_own_names(client):
    token, admin = create_admin_and_get_token(client)
    second = _invite_and_signup(
        client,
        token,
        role="global_manager",
        email="second@example.com",
        full_name="Second Person",
    )
    # The identity is per-account, never a shared/default value.
    assert second["user"]["full_name"] == "Second Person"
    assert admin["full_name"] != second["user"]["full_name"]


# ─────────────────────────────────────────────────────────────────────────
# B. Users & Access
# ─────────────────────────────────────────────────────────────────────────


def test_users_access_requires_an_admin_manager_role(client):
    token, _ = create_admin_and_get_token(client)
    building = _create_building(client, token, "Some Building")

    manager = _invite_and_signup(
        client,
        token,
        role="building_manager",
        building_ids=[building["id"]],
        email="bm@example.com",
        full_name="Building Manager",
    )

    # building_manager: no access at all
    assert client.get(
        "/api/admin/users", headers=auth_headers(manager["access_token"])
    ).status_code == 403

    # anonymous: no access at all
    assert client.get("/api/admin/users").status_code == 401

    # super_admin: allowed
    assert client.get("/api/admin/users", headers=auth_headers(token)).status_code == 200


def test_regular_user_cannot_reach_users_access(client):
    token, _ = create_admin_and_get_token(client)
    # regular_user accounts come from the public self-registration flow.
    registered = client.post(
        "/api/auth/register",
        json={
            "full_name": "Plain Visitor",
            "email": "visitor@example.com",
            "password": "password123",
        },
    )
    assert registered.status_code == 200, registered.text
    user_token = registered.json()["access_token"]

    assert client.get(
        "/api/admin/users", headers=auth_headers(user_token)
    ).status_code == 403


def test_user_list_shows_administrators_with_resolved_responsibility(client):
    token, assigned, _sibling, _mtoken, _muser = _same_site_two_buildings(client)

    users = client.get("/api/admin/users", headers=auth_headers(token)).json()
    by_role = {u["role"]: u for u in users}

    assert by_role["super_admin"]["scope_kind"] == "system_wide"

    manager = by_role["building_manager"]
    assert manager["full_name"] == "Ahmad Ali"
    assert manager["scope_kind"] == "building"
    # Responsibility is resolved to real names, not raw ObjectIds.
    assert manager["assigned_building"]["name"] == "Engineering Building"
    assert manager["assigned_building"]["site"] == "Meir Hospital"

    # No password material in any record.
    for record in users:
        assert "password" not in record

    # regular_user accounts are not administered by this feature at all.
    assert all(u["role"] != "regular_user" for u in users)


def test_user_list_supports_search_and_role_filter(client):
    token, _assigned, _sibling, _mtoken, _muser = _same_site_two_buildings(client)

    by_name = client.get(
        "/api/admin/users?search=ahmad", headers=auth_headers(token)
    ).json()
    assert [u["full_name"] for u in by_name] == ["Ahmad Ali"]

    by_email = client.get(
        "/api/admin/users?search=building.manager@", headers=auth_headers(token)
    ).json()
    assert [u["full_name"] for u in by_email] == ["Ahmad Ali"]

    filtered = client.get(
        "/api/admin/users?role=building_manager", headers=auth_headers(token)
    ).json()
    assert {u["role"] for u in filtered} == {"building_manager"}


def test_super_admin_can_rename_and_reassign_a_building_manager(client):
    token, assigned, sibling, manager_token, manager = _same_site_two_buildings(client)

    response = client.put(
        f"/api/admin/users/{manager['id']}",
        json={"full_name": "Ahmad Nasser", "building_id": sibling["id"]},
        headers=auth_headers(token),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["full_name"] == "Ahmad Nasser"
    assert body["building_ids"] == [sibling["id"]]
    assert body["assigned_building"]["name"] == "Emergency Wing"


def test_reassignment_takes_effect_on_the_next_request_with_no_relogin(client):
    """The manager keeps the SAME token across the reassignment: scope is
    read from the User document on every request, never from the JWT, so
    there is no stale-permission window."""
    token, assigned, sibling, manager_token, manager = _same_site_two_buildings(client)

    assigned_map = _create_map(client, token, assigned["id"], "Assigned Map")
    sibling_map = _create_map(client, token, sibling["id"], "Sibling Map")

    # Before: A reachable, B refused.
    assert client.get(
        f"/api/maps/{assigned_map['id']}", headers=auth_headers(manager_token)
    ).status_code == 200
    assert client.get(
        f"/api/maps/{sibling_map['id']}", headers=auth_headers(manager_token)
    ).status_code == 403

    client.put(
        f"/api/admin/users/{manager['id']}",
        json={"building_id": sibling["id"]},
        headers=auth_headers(token),
    )

    # After, with the very same token: exactly inverted.
    assert client.get(
        f"/api/maps/{sibling_map['id']}", headers=auth_headers(manager_token)
    ).status_code == 200
    assert client.get(
        f"/api/maps/{assigned_map['id']}", headers=auth_headers(manager_token)
    ).status_code == 403


def test_role_change_clears_the_previous_roles_scope(client):
    token, assigned, _sibling, _mtoken, manager = _same_site_two_buildings(client)

    promoted = client.put(
        f"/api/admin/users/{manager['id']}",
        json={"role": "global_manager"},
        headers=auth_headers(token),
    )
    assert promoted.status_code == 200, promoted.text
    body = promoted.json()
    # No stale building/map narrowing left behind.
    assert body["building_ids"] == []
    assert body["map_group_ids"] == []
    assert body["map_ids"] == []
    assert body["all_buildings"] is False

    # Demoting back requires a building again.
    missing = client.put(
        f"/api/admin/users/{manager['id']}",
        json={"role": "building_manager"},
        headers=auth_headers(token),
    )
    assert missing.status_code == 400

    ok = client.put(
        f"/api/admin/users/{manager['id']}",
        json={"role": "building_manager", "building_id": assigned["id"]},
        headers=auth_headers(token),
    )
    assert ok.status_code == 200
    assert ok.json()["building_ids"] == [assigned["id"]]


def test_legacy_map_scoped_manager_is_reported_honestly_and_normalized_on_edit(client):
    """Existing accounts narrowed by map_ids predate the one-building rule.
    They are displayed accurately and are only normalized when an admin
    explicitly saves them — never silently rewritten."""
    token, assigned, _sibling, _mtoken, manager = _same_site_two_buildings(client)
    legacy_map = _create_map(client, token, assigned["id"], "Legacy Map")

    import asyncio

    from models.user_model import User
    from beanie import PydanticObjectId

    async def _make_legacy():
        record = await User.get(PydanticObjectId(manager["id"]))
        record.map_ids = [legacy_map["id"]]
        await record.save()

    asyncio.get_event_loop().run_until_complete(_make_legacy())

    listed = client.get("/api/admin/users", headers=auth_headers(token)).json()
    legacy = next(u for u in listed if u["id"] == manager["id"])
    assert legacy["scope_kind"] == "legacy_maps"
    assert legacy["map_ids"] == [legacy_map["id"]]

    saved = client.put(
        f"/api/admin/users/{manager['id']}",
        json={"building_id": assigned["id"]},
        headers=auth_headers(token),
    ).json()
    assert saved["map_ids"] == []
    assert saved["building_ids"] == [assigned["id"]]
    assert saved["scope_kind"] == "building"


# ── Privilege escalation / self protection ──────────────────────────────


def _make_global_manager(client, super_token, email="gm@example.com"):
    return _invite_and_signup(
        client,
        super_token,
        role="global_manager",
        email=email,
        full_name="Global Manager",
    )


def test_global_manager_cannot_touch_a_super_admin(client):
    token, super_admin = create_admin_and_get_token(client)
    gm = _make_global_manager(client, token)
    gm_token = gm["access_token"]

    # It may list (seeing who administers the system is not a privilege)…
    listed = client.get("/api/admin/users", headers=auth_headers(gm_token))
    assert listed.status_code == 200
    super_record = next(u for u in listed.json() if u["role"] == "super_admin")
    # …but the record is reported as untouchable, and the API agrees.
    assert super_record["can_edit"] is False
    assert super_record["can_delete"] is False

    assert client.put(
        f"/api/admin/users/{super_admin['id']}",
        json={"full_name": "Hijacked"},
        headers=auth_headers(gm_token),
    ).status_code == 403

    assert client.delete(
        f"/api/admin/users/{super_admin['id']}", headers=auth_headers(gm_token)
    ).status_code == 403


def test_global_manager_cannot_promote_anyone_to_super_admin(client):
    token, _super_admin = create_admin_and_get_token(client)
    building = _create_building(client, token, "Scoped Building")
    gm = _make_global_manager(client, token)
    manager = _invite_and_signup(
        client,
        token,
        role="building_manager",
        building_ids=[building["id"]],
        email="target@example.com",
        full_name="Target Manager",
    )

    # …someone else
    assert client.put(
        f"/api/admin/users/{manager['user']['id']}",
        json={"role": "super_admin"},
        headers=auth_headers(gm["access_token"]),
    ).status_code == 403

    # …or itself
    assert client.put(
        f"/api/admin/users/{gm['user']['id']}",
        json={"role": "super_admin"},
        headers=auth_headers(gm["access_token"]),
    ).status_code == 403

    # not even to global_manager, which it is also not allowed to assign
    assert client.put(
        f"/api/admin/users/{manager['user']['id']}",
        json={"role": "global_manager"},
        headers=auth_headers(gm["access_token"]),
    ).status_code == 403


def test_last_super_admin_cannot_be_deleted_or_demoted(client):
    token, super_admin = create_admin_and_get_token(client)
    gm = _make_global_manager(client, token)

    # Deleting it (as itself) is refused by the self-delete guard first…
    self_delete = client.delete(
        f"/api/admin/users/{super_admin['id']}", headers=auth_headers(token)
    )
    assert self_delete.status_code == 409

    # …and demoting the only super_admin is refused too.
    demote = client.put(
        f"/api/admin/users/{super_admin['id']}",
        json={"role": "global_manager"},
        headers=auth_headers(token),
    )
    assert demote.status_code == 409

    # The account survives both attempts.
    assert client.get(
        f"/api/admin/users/{super_admin['id']}", headers=auth_headers(token)
    ).json()["role"] == "super_admin"


def test_super_admin_can_delete_another_administrator(client):
    token, _ = create_admin_and_get_token(client)
    gm = _make_global_manager(client, token, email="removable@example.com")

    response = client.delete(
        f"/api/admin/users/{gm['user']['id']}", headers=auth_headers(token)
    )
    assert response.status_code == 200, response.text

    # Gone from the list, and its own token no longer resolves to a user.
    remaining = client.get("/api/admin/users", headers=auth_headers(token)).json()
    assert all(u["id"] != gm["user"]["id"] for u in remaining)
    assert client.get(
        "/api/auth/me", headers=auth_headers(gm["access_token"])
    ).status_code == 401


def test_deleting_an_administrator_preserves_the_invitation_audit_trail(client):
    """Hard deletion is only safe because the code it issued keeps a
    denormalized creator name."""
    token, _ = create_admin_and_get_token(client)
    gm = _make_global_manager(client, token, email="issuer@example.com")
    building = _create_building(client, token, "Audited Building")

    created = _invite(
        client,
        gm["access_token"],
        role="building_manager",
        building_ids=[building["id"]],
    )
    assert created.status_code == 201, created.text

    client.delete(
        f"/api/admin/users/{gm['user']['id']}", headers=auth_headers(token)
    )

    codes = client.get("/api/invitation-codes", headers=auth_headers(token)).json()
    audited = next(c for c in codes if c["id"] == created.json()["id"])
    assert audited["created_by_name"] == "Global Manager"


# ─────────────────────────────────────────────────────────────────────────
# C. Invitation role choices
# ─────────────────────────────────────────────────────────────────────────


def test_ordinary_visitors_are_created_by_self_registration_not_invitations(client):
    """`regular_user` is gone from the ADMIN invitation UI (asserted in the
    frontend contract test), but it stays creatable on the backend: it is
    not a privileged role, historical codes must keep validating, and the
    flow that actually creates ordinary visitors is self-registration —
    which needs no invitation code at all and is untouched by this
    feature."""
    token, _ = create_admin_and_get_token(client)

    response = _invite(client, token, role="regular_user")
    assert response.status_code == 201, response.text
    registered = client.post(
        "/api/auth/register",
        json={
            "full_name": "Ordinary Visitor",
            "email": "ordinary@example.com",
            "password": "password123",
        },
    )
    assert registered.status_code == 200
    assert registered.json()["user"]["role"] == "regular_user"


def test_building_manager_invitation_requires_exactly_one_building(client):
    token, _ = create_admin_and_get_token(client)
    first = _create_building(client, token, "First Building")
    second = _create_building(client, token, "Second Building")

    assert _invite(client, token, role="building_manager", building_ids=[]).status_code == 400
    assert _invite(
        client, token, role="building_manager", building_ids=[first["id"], second["id"]]
    ).status_code == 400
    assert _invite(
        client, token, role="building_manager", building_ids=[first["id"]]
    ).status_code == 201


def test_signing_up_with_a_building_manager_code_applies_the_assignment(client):
    token, _ = create_admin_and_get_token(client)
    building = _create_building(client, token, "Invited Building")

    signed = _invite_and_signup(
        client,
        token,
        role="building_manager",
        building_ids=[building["id"]],
        email="invited@example.com",
        full_name="Invited Manager",
    )

    assert signed["user"]["full_name"] == "Invited Manager"
    assert signed["user"]["role"] == "building_manager"
    assert signed["user"]["building_ids"] == [building["id"]]
    assert signed["user"]["all_buildings"] is False
    # No manual post-signup step is required.


def test_a_global_manager_cannot_invite_a_building_it_cannot_reach(client):
    token, _ = create_admin_and_get_token(client)
    mine = _create_building(client, token, "In Scope")
    theirs = _create_building(client, token, "Out Of Scope")

    scoped_gm = _invite_and_signup(
        client,
        token,
        role="global_manager",
        building_ids=[mine["id"]],
        email="scoped.gm@example.com",
        full_name="Scoped Global Manager",
    )

    assert _invite(
        client,
        scoped_gm["access_token"],
        role="building_manager",
        building_ids=[theirs["id"]],
    ).status_code == 403


# ─────────────────────────────────────────────────────────────────────────
# D. Building Manager — full administrator of ONE building
#    (the mandatory same-site sibling test)
# ─────────────────────────────────────────────────────────────────────────


def test_building_manager_can_fully_administer_its_own_building(client):
    token, assigned, _sibling, manager_token, _manager = _same_site_two_buildings(client)

    # Maps: upload/create inside the assigned building
    created = client.post(
        "/api/maps",
        json={"title": "Ground Floor", "building_id": assigned["id"]},
        headers=auth_headers(manager_token),
    )
    assert created.status_code == 201, created.text
    map_id = created.json()["id"]

    # Rooms
    room = client.post(
        "/api/rooms",
        json={"building_id": assigned["id"], "name_en": "Lab 1"},
        headers=auth_headers(manager_token),
    )
    assert room.status_code in (200, 201), room.text

    # Route points
    point = client.post(
        "/api/route-points",
        json={"map_id": map_id, "name": "Corridor", "x": 1, "y": 1, "floor": 0},
        headers=auth_headers(manager_token),
    )
    assert point.status_code == 201, point.text

    # …and it sees its own map in the scoped listing
    maps = client.get("/api/maps", headers=auth_headers(manager_token)).json()
    assert [m["id"] for m in maps] == [map_id]


def test_building_manager_may_create_a_map_group_only_in_its_own_building(client):
    token, assigned, sibling, manager_token, _manager = _same_site_two_buildings(client)

    files = {"files": ("floor.png", b"not-a-real-image", "image/png")}
    data = {
        "name": "Tower",
        "floors_json": '[{"title": "Ground", "floor": 0}]',
        "building_id": sibling["id"],
    }

    # Sibling building: refused BEFORE anything is created.
    forbidden = client.post(
        "/api/map-groups",
        data=data,
        files=files,
        headers=auth_headers(manager_token),
    )
    assert forbidden.status_code == 403, forbidden.text

    # Its own building: authorization passes (the request then proceeds to
    # real image processing, which this fake PNG legitimately fails — the
    # point of this assertion is that it is no longer a 403).
    data["building_id"] = assigned["id"]
    allowed = client.post(
        "/api/map-groups",
        data=data,
        files={"files": ("floor.png", b"not-a-real-image", "image/png")},
        headers=auth_headers(manager_token),
    )
    assert allowed.status_code != 403, allowed.text


def test_a_scoped_admin_cannot_auto_create_a_building_by_omitting_building_id(client):
    """The find-or-create fallback would mint a brand new building from the
    campus/title text — an account silently widening its own scope."""
    _token, _assigned, _sibling, manager_token, _manager = _same_site_two_buildings(client)

    response = client.post(
        "/api/map-groups",
        data={
            "name": "Sneaky Group",
            "floors_json": '[{"title": "Ground", "floor": 0}]',
            "campus": "Brand New Campus",
        },
        files={"files": ("floor.png", b"not-a-real-image", "image/png")},
        headers=auth_headers(manager_token),
    )
    assert response.status_code == 400, response.text


def test_building_manager_is_refused_on_every_sibling_building_resource(client):
    token, assigned, sibling, manager_token, _manager = _same_site_two_buildings(client)

    sibling_map = _create_map(client, token, sibling["id"], "Sibling Ground Floor")
    sibling_room = client.post(
        "/api/rooms",
        json={"building_id": sibling["id"], "name_en": "Sibling Room"},
        headers=auth_headers(token),
    ).json()

    headers = auth_headers(manager_token)

    # Direct map access / mutation (delete is refused for a
    # building_manager on ANY map — see the delete-permission tests
    # below — so this asserts the read/scope boundary specifically).
    assert client.get(f"/api/maps/{sibling_map['id']}", headers=headers).status_code == 403

    # Creating a map in the sibling building
    assert client.post(
        "/api/maps",
        json={"title": "Intruder", "building_id": sibling["id"]},
        headers=headers,
    ).status_code == 403

    # Room mutation in the sibling building
    assert client.put(
        f"/api/rooms/{sibling_room['id']}",
        json={"building_id": sibling["id"], "name_en": "Renamed"},
        headers=headers,
    ).status_code == 403

    # Rooms listing is narrowed, so the sibling's room never appears
    rooms = client.get("/api/rooms", headers=headers).json()
    assert all(r["building_id"] != sibling["id"] for r in rooms)


def test_sibling_building_never_leaks_through_any_admin_payload(client):
    """The mandatory same-site test: two buildings under ONE site, only one
    assigned. The other must not appear anywhere — not by name, not by id,
    not as a count."""
    token, assigned, sibling, manager_token, _manager = _same_site_two_buildings(client)
    _create_map(client, token, sibling["id"], "Sibling Ground Floor")
    _create_map(client, token, assigned["id"], "Assigned Ground Floor")

    headers = auth_headers(manager_token)

    buildings = client.get("/api/locations/buildings", headers=headers).json()
    maps = client.get("/api/maps", headers=headers).json()
    groups = client.get("/api/map-groups", headers=headers).json()

    combined = repr(buildings) + repr(maps) + repr(groups)

    # Count is the AUTHORIZED count, never the site's true total of 2.
    assert len(buildings) == 1
    assert buildings[0]["id"] == assigned["id"]

    assert sibling["id"] not in combined
    assert "Emergency Wing" not in combined
    assert "Sibling Ground Floor" not in combined

    # The shared site name is still present as parent context — that is
    # allowed, and is not access.
    assert buildings[0]["campus"] == "Meir Hospital"


def test_building_manager_cannot_create_or_delete_buildings(client):
    token, assigned, _sibling, manager_token, _manager = _same_site_two_buildings(client)
    headers = auth_headers(manager_token)

    # Creating another building would be inventing its own new scope.
    assert client.post(
        "/api/locations/buildings", json={"name_en": "My Own Building"}, headers=headers
    ).status_code == 403

    # Deleting the assigned building would destroy the scope boundary.
    assert client.delete(
        f"/api/locations/buildings/{assigned['id']}", headers=headers
    ).status_code == 403


def test_building_manager_cannot_reach_global_administration(client):
    _token, _assigned, _sibling, manager_token, _manager = _same_site_two_buildings(client)
    headers = auth_headers(manager_token)

    assert client.get("/api/admin/users", headers=headers).status_code == 403
    assert client.get("/api/invitation-codes", headers=headers).status_code == 403
    assert client.post(
        "/api/invitation-codes",
        json={"role": "building_manager", "building_ids": [], "all_buildings": False},
        headers=headers,
    ).status_code == 403


# ─────────────────────────────────────────────────────────────────────────
# E. Permanent structural deletion — global tier only
#
# A building_manager stays a full OPERATIONAL administrator of its
# assigned building (upload, create group, add floor, update metadata all
# stay allowed and are asserted here alongside the refusals), but it may
# not permanently destroy a Map, a Map Group or an uploaded Floor: those
# deletes cascade and are unrecoverable.
# ─────────────────────────────────────────────────────────────────────────


def _seed_group_with_floor(client, token, building_id):
    """MapGroup + one Map floor, created directly against the models —
    these tests are about authorization, not image processing, and
    POST /api/maps deliberately does not accept a map_group_id."""
    import asyncio

    from models.map_group_model import MapGroup
    from models.map_model import Map

    async def _seed():
        group = MapGroup(building_id=building_id, name="Tower", code="DEL-TEST-01")
        await group.insert()
        floor = Map(
            title="Ground Floor",
            building_id=building_id,
            map_group_id=str(group.id),
            floor=0,
        )
        await floor.insert()
        return str(group.id), str(floor.id)

    return asyncio.get_event_loop().run_until_complete(_seed())


def test_building_manager_may_still_create_and_edit_but_never_delete(client):
    token, assigned, _sibling, manager_token, _manager = _same_site_two_buildings(client)
    group_id, floor_id = _seed_group_with_floor(client, token, assigned["id"])
    headers = auth_headers(manager_token)

    # ── still allowed: the whole operational surface ──────────────────
    assert client.post(
        "/api/maps",
        json={"title": "Uploaded Floor", "building_id": assigned["id"]},
        headers=headers,
    ).status_code == 201

    created_group = client.post(
        "/api/map-groups",
        data={
            "name": "Operational Group",
            "floors_json": '[{"title": "Ground", "floor": 0}]',
            "building_id": assigned["id"],
        },
        files={"files": ("floor.png", b"not-a-real-image", "image/png")},
        headers=headers,
    )
    assert created_group.status_code != 403, created_group.text

    added_floor = client.post(
        f"/api/map-groups/{group_id}/floors",
        data={"floors_json": '[{"title": "First", "floor": 1}]'},
        files={"files": ("floor.png", b"not-a-real-image", "image/png")},
        headers=headers,
    )
    assert added_floor.status_code != 403, added_floor.text

    assert client.put(
        f"/api/map-groups/{group_id}",
        json={"name": "Renamed By Manager"},
        headers=headers,
    ).status_code == 200

    # ── refused: permanent structural deletion, even inside its OWN
    #    building. Not a scope failure — a role boundary.
    assert client.delete(f"/api/maps/{floor_id}", headers=headers).status_code == 403
    assert client.delete(
        f"/api/map-groups/{group_id}/floors/{floor_id}", headers=headers
    ).status_code == 403
    assert client.delete(f"/api/map-groups/{group_id}", headers=headers).status_code == 403

    # ...and nothing was actually destroyed by the attempts.
    assert client.get(
        f"/api/map-groups/{group_id}", headers=auth_headers(token)
    ).status_code == 200


def test_super_admin_may_delete_maps_groups_and_floors(client):
    token, _admin = create_admin_and_get_token(client)
    building = _create_building(client, token, "Deletable Building")
    headers = auth_headers(token)

    standalone = _create_map(client, token, building["id"], "Standalone Map")
    assert client.delete(f"/api/maps/{standalone['id']}", headers=headers).status_code == 200

    group_id, floor_id = _seed_group_with_floor(client, token, building["id"])
    assert client.delete(
        f"/api/map-groups/{group_id}/floors/{floor_id}", headers=headers
    ).status_code == 200
    assert client.delete(f"/api/map-groups/{group_id}", headers=headers).status_code == 200


def test_global_manager_may_delete_in_scope_and_is_refused_out_of_scope(client):
    token, _admin = create_admin_and_get_token(client)
    mine = _create_building(client, token, "In Scope Building")
    theirs = _create_building(client, token, "Out Of Scope Building")

    gm = _invite_and_signup(
        client,
        token,
        role="global_manager",
        building_ids=[mine["id"]],
        email="deleting.gm@example.com",
        full_name="Deleting Global Manager",
    )
    headers = auth_headers(gm["access_token"])

    # In scope: allowed.
    in_scope_map = _create_map(client, token, mine["id"], "In Scope Map")
    assert client.delete(f"/api/maps/{in_scope_map['id']}", headers=headers).status_code == 200

    group_id, floor_id = _seed_group_with_floor(client, token, mine["id"])
    assert client.delete(
        f"/api/map-groups/{group_id}/floors/{floor_id}", headers=headers
    ).status_code == 200
    assert client.delete(f"/api/map-groups/{group_id}", headers=headers).status_code == 200

    # Out of scope: refused, so the role gate is never the whole decision.
    out_map = _create_map(client, token, theirs["id"], "Out Of Scope Map")
    assert client.delete(f"/api/maps/{out_map['id']}", headers=headers).status_code == 403

    out_group_id, out_floor_id = _seed_group_with_floor(client, token, theirs["id"])
    assert client.delete(
        f"/api/map-groups/{out_group_id}/floors/{out_floor_id}", headers=headers
    ).status_code == 403
    assert client.delete(
        f"/api/map-groups/{out_group_id}", headers=headers
    ).status_code == 403


def test_regular_user_cannot_delete_any_map_structure(client):
    token, _admin = create_admin_and_get_token(client)
    building = _create_building(client, token, "Protected Building")
    target = _create_map(client, token, building["id"], "Protected Map")
    group_id, floor_id = _seed_group_with_floor(client, token, building["id"])

    registered = client.post(
        "/api/auth/register",
        json={
            "full_name": "Curious Visitor",
            "email": "curious@example.com",
            "password": "password123",
        },
    )
    headers = auth_headers(registered.json()["access_token"])

    assert client.delete(f"/api/maps/{target['id']}", headers=headers).status_code == 403
    assert client.delete(f"/api/map-groups/{group_id}", headers=headers).status_code == 403
    assert client.delete(
        f"/api/map-groups/{group_id}/floors/{floor_id}", headers=headers
    ).status_code == 403
