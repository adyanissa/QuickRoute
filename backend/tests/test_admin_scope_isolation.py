"""
Admin dashboard refinement task — backend tests for STRICT resource/tenant
isolation on the two admin listing endpoints that previously had no
authorization at all:

    GET /api/maps          (every Map in the database, to anyone)
    GET /api/map-groups    (every MapGroup + every one of its floors, to anyone)
    GET /api/map-groups/{id}

QuickRoute serves independent institutions (hospitals, colleges, malls,
offices). A manager responsible for one of them must not be able to learn
that the others exist — not their names, not their counts, not by dropping
the Authorization header, and not by pasting an id into a URL. These tests
assert exactly that, plus the two things the fix must NOT break: the
anonymous end-user wayfinding flow, and a super_admin's intentional
system-wide scope.

Uses the same in-memory mongomock TestClient fixtures as the rest of the
suite (see conftest.py) — no real MongoDB is ever touched.

Run with: pytest backend/tests/test_admin_scope_isolation.py -v
"""

from tests.test_api_integration import (
    auth_headers,
    create_admin_and_get_token,
    make_invitation_code,
    signup,
)
from tests.test_rbac_scope_authorization import (
    _create_building,
    _signup_with_invite,
)


def _create_map(client, token, building_id, title, map_group_id=None):
    payload = {"title": title, "building_id": building_id}
    if map_group_id:
        payload["map_group_id"] = map_group_id
    response = client.post("/api/maps", json=payload, headers=auth_headers(token))
    assert response.status_code in (200, 201), response.text
    return response.json()


def _two_institutions(client):
    """A super_admin plus two completely unrelated institutions, each with
    its own building and its own map. Returns everything the tests need."""
    token, _admin = create_admin_and_get_token(client)

    hospital = _create_building(client, token, "Meir Hospital Wing")
    college = _create_building(client, token, "Yezreel Engineering Building")

    hospital_map = _create_map(client, token, hospital["id"], "Hospital Ground Floor")
    college_map = _create_map(client, token, college["id"], "College Ground Floor")

    return token, hospital, college, hospital_map, college_map


# ─────────────────────────────────────────────────────────────────────────
# 1. The endpoints are no longer anonymously enumerable
# ─────────────────────────────────────────────────────────────────────────


def test_map_list_is_not_anonymously_enumerable(client):
    _two_institutions(client)

    # Dropping the Authorization header must NOT be a way around scope.
    assert client.get("/api/maps").status_code == 401
    assert client.get("/api/map-groups").status_code == 401


def test_regular_user_cannot_enumerate_maps_or_map_groups(client):
    token, _admin = create_admin_and_get_token(client)
    _create_building(client, token, "Some Building")

    code = make_invitation_code(
        client, code="QR-PLAINUSER1", role="regular_user", creator_token=token
    )
    user_token = signup(client, code, email="plain.user@example.com").json()["access_token"]

    assert client.get("/api/maps", headers=auth_headers(user_token)).status_code == 403
    assert client.get("/api/map-groups", headers=auth_headers(user_token)).status_code == 403


# ─────────────────────────────────────────────────────────────────────────
# 2. Cross-institution isolation for a building-scoped manager
# ─────────────────────────────────────────────────────────────────────────


def test_building_scoped_manager_never_sees_another_institution(client):
    token, hospital, college, hospital_map, college_map = _two_institutions(client)

    manager_token = _signup_with_invite(
        client,
        token,
        role="building_manager",
        building_ids=[hospital["id"]],
        email="hospital.manager@example.com",
        code="unused",
    )

    maps = client.get("/api/maps", headers=auth_headers(manager_token)).json()
    titles = [m["title"] for m in maps]

    assert titles == ["Hospital Ground Floor"]
    # The other institution's map must not appear in ANY form — not as a
    # name, not as an id, not as a count.
    assert college_map["id"] not in [m["id"] for m in maps]
    assert "College Ground Floor" not in titles
    assert len(maps) == 1

    # ...and neither may it be reached by id (IDOR).
    direct = client.get(
        f"/api/maps/{college_map['id']}", headers=auth_headers(manager_token)
    )
    assert direct.status_code == 403, direct.text


def test_explicit_out_of_scope_building_id_is_rejected_not_silently_rescoped(client):
    token, hospital, college, _hospital_map, _college_map = _two_institutions(client)

    manager_token = _signup_with_invite(
        client,
        token,
        role="building_manager",
        building_ids=[hospital["id"]],
        email="scoped.manager@example.com",
        code="unused",
    )

    response = client.get(
        f"/api/map-groups?building_id={college['id']}",
        headers=auth_headers(manager_token),
    )
    assert response.status_code == 403, response.text


# ─────────────────────────────────────────────────────────────────────────
# 3. The sibling-floor leak (map_ids scope) — the strictest case
# ─────────────────────────────────────────────────────────────────────────


def _group_with_three_floors(client, token, building_id):
    """Creates a MapGroup document plus three Map floors that reference it.

    Written directly against the Beanie models rather than through the
    multipart upload endpoint because these tests are about authorization,
    not image processing — and POST /api/maps deliberately does not accept a
    map_group_id (a floor is only ever attached to a group by the upload
    flow), so the link has to be made here. Same run_until_complete pattern
    tests/test_multilingual_localization.py already uses for seeding.
    """

    import asyncio

    from models.map_group_model import MapGroup
    from models.map_model import Map

    async def _seed():
        group = MapGroup(
            building_id=building_id,
            name="Hospital Tower",
            code="ISO-TEST-01",
        )
        await group.insert()

        floors = []
        for number in range(3):
            floor = Map(
                title=f"Floor {number}",
                building_id=building_id,
                map_group_id=str(group.id),
                floor=number,
            )
            await floor.insert()
            floors.append({"id": str(floor.id), "title": floor.title})

        return str(group.id), floors

    return asyncio.get_event_loop().run_until_complete(_seed())


def test_map_ids_scope_hides_sibling_floors_everywhere(client):
    token, _admin = create_admin_and_get_token(client)
    building = _create_building(client, token, "Tower Building")
    group_id, floors = _group_with_three_floors(client, token, building["id"])
    allowed = floors[1]

    manager_token = _signup_with_invite(
        client,
        token,
        role="building_manager",
        building_ids=[building["id"]],
        map_ids=[allowed["id"]],
        email="floor.manager@example.com",
        code="unused",
    )

    # (a) the flat map list contains ONLY the assigned floor
    maps = client.get("/api/maps", headers=auth_headers(manager_token)).json()
    assert [m["id"] for m in maps] == [allowed["id"]]

    # (b) the group is still reachable as PARENT CONTEXT, but its floors and
    #     its floor_count describe only what this manager may access — a
    #     sibling floor is absent, never present-but-disabled.
    groups = client.get("/api/map-groups", headers=auth_headers(manager_token)).json()
    assert len(groups) == 1
    group = groups[0]
    assert group["id"] == group_id
    assert [f["id"] for f in group["floors"]] == [allowed["id"]]
    assert group["floor_count"] == 1
    assert "Floor 0" not in [f["title"] for f in group["floors"]]
    assert "Floor 2" not in [f["title"] for f in group["floors"]]

    # (c) a sibling floor cannot be fetched directly either
    sibling = floors[0]
    direct = client.get(
        f"/api/maps/{sibling['id']}", headers=auth_headers(manager_token)
    )
    assert direct.status_code == 403, direct.text


def test_super_admin_still_sees_the_whole_group(client):
    token, _admin = create_admin_and_get_token(client)
    building = _create_building(client, token, "Tower Building")
    group_id, floors = _group_with_three_floors(client, token, building["id"])

    groups = client.get("/api/map-groups", headers=auth_headers(token)).json()
    group = next(g for g in groups if g["id"] == group_id)

    assert group["floor_count"] == len(floors)
    assert len(group["floors"]) == len(floors)


def test_out_of_scope_group_cannot_be_fetched_by_id(client):
    token, hospital, college, _hm, _cm = _two_institutions(client)
    college_group_id, _floors = _group_with_three_floors(client, token, college["id"])

    manager_token = _signup_with_invite(
        client,
        token,
        role="building_manager",
        building_ids=[hospital["id"]],
        email="other.manager@example.com",
        code="unused",
    )

    response = client.get(
        f"/api/map-groups/{college_group_id}", headers=auth_headers(manager_token)
    )
    assert response.status_code == 403, response.text

    # And it is absent from the listing entirely — no name, no id, no count.
    listing = client.get("/api/map-groups", headers=auth_headers(manager_token)).json()
    assert college_group_id not in [g["id"] for g in listing]


# ─────────────────────────────────────────────────────────────────────────
# 4. Regression guards — what the fix must NOT break
# ─────────────────────────────────────────────────────────────────────────


def test_public_navigation_can_still_resolve_a_map_by_id_anonymously(client):
    _token, _hospital, _college, hospital_map, _college_map = _two_institutions(client)

    # The kiosk/QR wayfinding flow (NavigationRouteMap.jsx) resolves a single
    # map with no login at all. That contract is unchanged.
    response = client.get(f"/api/maps/{hospital_map['id']}")
    assert response.status_code == 200, response.text
    assert response.json()["id"] == hospital_map["id"]


def test_public_route_point_listing_still_works_anonymously(client):
    _two_institutions(client)

    # The same public flow lists route points with no auth — untouched.
    assert client.get("/api/route-points").status_code == 200
    assert client.get("/api/route-points/count").status_code == 200


def test_anonymous_building_listing_is_unchanged(client):
    _token, hospital, college, _hm, _cm = _two_institutions(client)

    # GET /api/locations/buildings is deliberately public: the anonymous
    # BuildingSelectionScreen uses it to let a visitor pick where they are.
    # This test pins that pre-existing contract so a future change to the
    # admin scoping cannot silently break end-user navigation.
    response = client.get("/api/locations/buildings")
    assert response.status_code == 200
    names = [b["name_en"] for b in response.json()]
    assert hospital["name_en"] in names
    assert college["name_en"] in names
