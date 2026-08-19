"""
GET /api/location-codes performance regression suite.

The list endpoint used to build its response with
`[await location_code_to_response(entry) for entry in entries]`, which asks
the database two questions PER CODE (Map.get, RoutePoint.get) — 1 + 2N
sequential round trips. Measured in a real browser against ~146 codes:
~20 s stalled + ~42 s waiting, about a minute end to end.

It now uses the batched path in routes/location_code_routes.py. These tests
pin down the two things that matter:

  * the response is EQUIVALENT to what the per-code path produced, for
    every degenerate relationship shape, and
  * the query count is CONSTANT — it does not grow with the number of
    codes, and the per-code helpers are never reached from the list path.

Mirrors tests/test_rooms_list_batching.py, which did the same job for
GET /api/rooms.

Run with: pytest backend/tests/test_location_codes_list_batching.py -v
"""

import asyncio
import contextlib
from collections import Counter

import pytest
from beanie import PydanticObjectId

from models.building_model import Building
from models.location_code_model import LocationCode
from models.map_group_model import MapGroup
from models.map_model import Map
from models.route_point_model import RoutePoint
from models.user_model import User

from routes.location_code_routes import location_code_to_response

from tests.test_api_integration import auth_headers, create_admin_and_get_token


# ---------------------------------------------------------
# Query counting — wraps the driver-level collection methods, so it counts
# REAL round trips. Nothing is mocked out; the queries still execute.
# ---------------------------------------------------------

COUNTED_MODELS = (LocationCode, Map, RoutePoint, Building, MapGroup, User)
COUNTED_OPS = ("find", "find_one", "aggregate", "distinct", "count_documents")


@contextlib.contextmanager
def count_queries():
    counts = Counter()
    restore = []

    for model in COUNTED_MODELS:
        collection = model.get_pymongo_collection()
        collection_name = model.get_collection_name()

        for op in COUNTED_OPS:
            original = getattr(collection, op, None)

            if original is None:
                continue

            def make_wrapper(op=op, name=collection_name, original=original):
                def wrapper(*args, **kwargs):
                    counts[f"{name}.{op}"] += 1
                    return original(*args, **kwargs)

                return wrapper

            setattr(collection, op, make_wrapper())
            restore.append((collection, op, original))

    try:
        yield counts
    finally:
        for collection, op, original in restore:
            setattr(collection, op, original)


def enrichment_queries(counts):
    """Round trips the ENRICHMENT costs — the auth lookup that every
    authenticated request makes is not part of what this pass changed."""

    return (
        counts["location_codes.find"]
        + counts["maps.find"]
        + counts["route_points.find"]
        + counts["location_codes.find_one"]
        + counts["maps.find_one"]
        + counts["route_points.find_one"]
    )


# ---------------------------------------------------------
# Seeding — written through Beanie so degenerate shapes (dangling map,
# deleted route point, malformed id) can be built exactly as they occur.
# ---------------------------------------------------------

BUILDING_ID = "7c946ffae3e4a269a4589f71"
OTHER_BUILDING_ID = "7c946ffae3e4a269a4589f72"


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


async def _make_point(map_id, *, name, floor=None, building_id=BUILDING_ID):
    point = RoutePoint(
        map_id=map_id,
        building_id=building_id,
        name=name,
        x=10.0,
        y=10.0,
        point_type="entrance",
        floor=floor,
        is_active=True,
    )
    await point.insert()
    return point


async def _make_code(**kwargs):
    kwargs.setdefault("building_id", BUILDING_ID)
    kwargs.setdefault("map_id", "")
    kwargs.setdefault("route_point_id", "")
    entry = LocationCode(**kwargs)
    await entry.insert()
    return entry


async def _seed_full_matrix():
    """One code for every branch of the group/floor resolution ladder."""

    group = MapGroup(code="LC-BATCH", name="Batch Group", building_id=BUILDING_ID)
    await group.insert()

    grouped_map = Map(
        title="Grouped Floor",
        building_id=BUILDING_ID,
        map_group_id=str(group.id),
        floor=3,
    )
    await grouped_map.insert()

    # A map with NO floor recorded — the legacy case where the RoutePoint's
    # own floor is the fallback.
    floorless_map = Map(title="Legacy Floor", building_id=BUILDING_ID)
    await floorless_map.insert()

    ungrouped_map = Map(title="Ungrouped Floor", building_id=BUILDING_ID, floor=1)
    await ungrouped_map.insert()

    grouped_id = str(grouped_map.id)

    # 1 — normal: grouped map with a floor, live point
    p1 = await _make_point(grouped_id, name="Main Entrance", floor=9)
    await _make_code(
        code="AAAA1111", map_id=grouped_id, route_point_id=str(p1.id),
        label="Main Entrance",
    )

    # 2 — map floor wins over a DIFFERENT point floor
    p2 = await _make_point(grouped_id, name="Side Door", floor=7)
    await _make_code(code="AAAA2222", map_id=grouped_id, route_point_id=str(p2.id))

    # 3 — map has no floor -> the point's floor is the fallback
    p3 = await _make_point(str(floorless_map.id), name="Legacy Point", floor=5)
    await _make_code(
        code="AAAA3333", map_id=str(floorless_map.id), route_point_id=str(p3.id),
    )

    # 4 — map has no floor AND the point has no floor -> None
    p4 = await _make_point(str(floorless_map.id), name="No Floor Anywhere")
    await _make_code(
        code="AAAA4444", map_id=str(floorless_map.id), route_point_id=str(p4.id),
    )

    # 5 — ungrouped map -> map_group_id None, floor still from the map
    p5 = await _make_point(str(ungrouped_map.id), name="Ungrouped Point", floor=2)
    await _make_code(
        code="AAAA5555", map_id=str(ungrouped_map.id), route_point_id=str(p5.id),
    )

    # 6 — INACTIVE code, otherwise normal
    p6 = await _make_point(grouped_id, name="Retired Door", floor=4)
    await _make_code(
        code="AAAA6666", map_id=grouped_id, route_point_id=str(p6.id),
        is_active=False, label="Retired",
    )

    # 7 — dangling map id (map deleted after the code was created)
    p7 = await _make_point(grouped_id, name="Orphan Map Point", floor=6)
    await _make_code(
        code="AAAA7777", map_id=str(PydanticObjectId()), route_point_id=str(p7.id),
    )

    # 8 — dangling route point id (point deleted)
    await _make_code(
        code="AAAA8888", map_id=grouped_id, route_point_id=str(PydanticObjectId()),
    )

    # 9 — BOTH dangling
    await _make_code(
        code="AAAA9999",
        map_id=str(PydanticObjectId()),
        route_point_id=str(PydanticObjectId()),
    )

    # 10 — malformed ids on both links
    await _make_code(
        code="BBBB1111", map_id="not-an-object-id", route_point_id="also-bad",
    )

    # 11 — empty ids
    await _make_code(code="BBBB2222", map_id="", route_point_id="")

    # 12 — two codes sharing ONE map and ONE point (dedup must not drop one)
    await _make_code(code="BBBB3333", map_id=grouped_id, route_point_id=str(p1.id))

    # 13 — a code in ANOTHER building, to prove scoping still applies
    await _make_code(
        code="BBBB4444", building_id=OTHER_BUILDING_ID,
        map_id=grouped_id, route_point_id=str(p1.id),
    )

    return {
        "group_id": str(group.id),
        "grouped_map_id": grouped_id,
        "floorless_map_id": str(floorless_map.id),
        "ungrouped_map_id": str(ungrouped_map.id),
    }


async def _seed_n_codes(count):
    map_item = Map(title=f"Scale {count}", building_id=BUILDING_ID, floor=1)
    await map_item.insert()
    map_id = str(map_item.id)

    for index in range(count):
        point = await _make_point(map_id, name=f"P{index}", floor=1)
        await _make_code(
            code=f"SCALE{index:04d}", map_id=map_id, route_point_id=str(point.id),
        )


# ---------------------------------------------------------
# 1 — response equivalence with the per-code path
# ---------------------------------------------------------

def test_list_response_is_identical_to_the_per_code_path(client):
    """The strongest statement of "nothing changed": build the same list
    through the OLD per-code helper and assert field-for-field equality."""

    run(_seed_full_matrix())
    token, _ = create_admin_and_get_token(client, email="lcbatch1@example.com")

    response = client.get("/api/location-codes", headers=auth_headers(token))
    assert response.status_code == 200, response.text
    batched = response.json()

    async def _reference():
        entries = await LocationCode.find({}).to_list()
        return [
            (await location_code_to_response(entry)).model_dump(mode="json")
            for entry in entries
        ]

    reference = run(_reference())

    assert len(batched) == len(reference) > 0

    by_id_batched = {e["id"]: e for e in batched}
    by_id_reference = {e["id"]: e for e in reference}

    assert by_id_batched.keys() == by_id_reference.keys()

    for code_id, expected in by_id_reference.items():
        assert by_id_batched[code_id] == expected, code_id


def test_every_response_field_is_present_and_unchanged(client):
    run(_seed_full_matrix())
    token, _ = create_admin_and_get_token(client, email="lcbatch2@example.com")

    body = client.get(
        "/api/location-codes", headers=auth_headers(token)
    ).json()
    entry = next(e for e in body if e["code"] == "AAAA1111")

    for field in (
        "id", "code", "building_id", "map_id", "route_point_id",
        "map_group_id", "floor", "label", "is_active",
        "created_at", "updated_at",
    ):
        assert field in entry, field

    assert entry["code"] == "AAAA1111"
    assert entry["label"] == "Main Entrance"
    assert entry["is_active"] is True


def test_map_group_and_floor_resolution_is_unchanged(client):
    seeded = run(_seed_full_matrix())
    token, _ = create_admin_and_get_token(client, email="lcbatch3@example.com")

    body = client.get(
        "/api/location-codes", headers=auth_headers(token)
    ).json()
    by_code = {e["code"]: e for e in body}

    # (map_group_id, floor) for each seeded relationship shape.
    expected = {
        "AAAA1111": (seeded["group_id"], 3),    # map floor wins
        "AAAA2222": (seeded["group_id"], 3),    # ...over the point's own floor
        "AAAA3333": (None, 5),                  # no map floor -> point floor
        "AAAA4444": (None, None),               # neither has a floor
        "AAAA5555": (None, 1),                  # ungrouped map, map floor
        "AAAA6666": (seeded["group_id"], 3),    # inactive code, same resolution
        "AAAA7777": (None, 6),                  # dangling map -> point floor
        "AAAA8888": (seeded["group_id"], 3),    # dangling point -> map floor
        "AAAA9999": (None, None),               # both dangling
        "BBBB1111": (None, None),               # both malformed
        "BBBB2222": (None, None),               # both empty
        "BBBB3333": (seeded["group_id"], 3),    # shares map+point with AAAA1111
    }

    for code, (group_id, floor) in expected.items():
        assert by_code[code]["map_group_id"] == group_id, code
        assert by_code[code]["floor"] == floor, code


def test_a_failure_on_one_side_does_not_suppress_the_other(client):
    """The two lookups are independent: a dangling map must still let the
    point's floor through, and a dangling point must still let the map's
    group through. This is the precedence the single-code path's two
    separate try/except blocks produce."""

    seeded = run(_seed_full_matrix())
    token, _ = create_admin_and_get_token(client, email="lcbatch4@example.com")

    body = client.get(
        "/api/location-codes", headers=auth_headers(token)
    ).json()
    by_code = {e["code"]: e for e in body}

    assert by_code["AAAA7777"]["map_group_id"] is None
    assert by_code["AAAA7777"]["floor"] == 6

    assert by_code["AAAA8888"]["map_group_id"] == seeded["group_id"]
    assert by_code["AAAA8888"]["floor"] == 3


# ---------------------------------------------------------
# 2 — inactive codes
# ---------------------------------------------------------

def test_inactive_codes_keep_their_exact_current_behaviour(client):
    seeded = run(_seed_full_matrix())
    token, _ = create_admin_and_get_token(client, email="lcbatch5@example.com")

    body = client.get(
        "/api/location-codes", headers=auth_headers(token)
    ).json()
    inactive = next(e for e in body if e["code"] == "AAAA6666")

    # Still listed, still fully enriched, just flagged inactive.
    assert inactive["is_active"] is False
    assert inactive["map_group_id"] == seeded["group_id"]
    assert inactive["floor"] == 3
    assert inactive["label"] == "Retired"


def test_the_is_active_filter_still_works(client):
    run(_seed_full_matrix())
    token, _ = create_admin_and_get_token(client, email="lcbatch6@example.com")

    active = client.get(
        "/api/location-codes?is_active=true", headers=auth_headers(token)
    ).json()
    inactive = client.get(
        "/api/location-codes?is_active=false", headers=auth_headers(token)
    ).json()

    assert all(e["is_active"] is True for e in active)
    assert [e["code"] for e in inactive] == ["AAAA6666"]


# ---------------------------------------------------------
# 3 — constant query count
# ---------------------------------------------------------

def test_query_count_does_not_grow_with_the_number_of_codes(client):
    token, _ = create_admin_and_get_token(client, email="lcbatch7@example.com")

    run(_seed_n_codes(3))

    with count_queries() as small:
        small_response = client.get(
            "/api/location-codes", headers=auth_headers(token)
        )

    assert small_response.status_code == 200
    assert len(small_response.json()) == 3

    run(LocationCode.delete_all())
    run(RoutePoint.delete_all())
    run(Map.delete_all())

    run(_seed_n_codes(60))

    with count_queries() as large:
        large_response = client.get(
            "/api/location-codes", headers=auth_headers(token)
        )

    assert large_response.status_code == 200
    assert len(large_response.json()) == 60

    # 20x the codes, the same number of enrichment round trips.
    assert enrichment_queries(small) == enrichment_queries(large), (
        f"query count grew with code count: "
        f"3 codes -> {dict(small)}, 60 codes -> {dict(large)}"
    )

    # And that constant is small: location_codes + maps + route_points.
    assert enrichment_queries(large) <= 3, dict(large)


def test_the_three_batched_queries_are_the_expected_ones(client):
    token, _ = create_admin_and_get_token(client, email="lcbatch8@example.com")
    run(_seed_n_codes(8))

    with count_queries() as counts:
        assert client.get(
            "/api/location-codes", headers=auth_headers(token)
        ).status_code == 200

    assert counts["location_codes.find"] == 1
    assert counts["maps.find"] == 1
    assert counts["route_points.find"] == 1


def test_an_empty_inventory_costs_a_single_query(client):
    token, _ = create_admin_and_get_token(client, email="lcbatch9@example.com")

    with count_queries() as counts:
        response = client.get(
            "/api/location-codes", headers=auth_headers(token)
        )

    assert response.status_code == 200
    assert response.json() == []
    assert enrichment_queries(counts) == 1
    assert counts["location_codes.find"] == 1


def test_codes_with_no_resolvable_relations_skip_both_lookups(client):
    """Empty/malformed ids produce no $in set, so those queries are not
    issued at all rather than being sent with an empty list."""

    token, _ = create_admin_and_get_token(client, email="lcbatch10@example.com")

    async def _seed():
        await _make_code(code="CCCC1111", map_id="", route_point_id="")
        await _make_code(code="CCCC2222", map_id="bad", route_point_id="bad")

    run(_seed())

    with count_queries() as counts:
        response = client.get(
            "/api/location-codes", headers=auth_headers(token)
        )

    assert response.status_code == 200
    assert len(response.json()) == 2
    assert all(e["map_group_id"] is None for e in response.json())
    assert all(e["floor"] is None for e in response.json())
    assert enrichment_queries(counts) == 1


# ---------------------------------------------------------
# 4 — no per-code fallback
# ---------------------------------------------------------

def test_the_list_endpoint_never_issues_a_per_code_lookup(client):
    """The old path's fingerprint was Map.get / RoutePoint.get (both
    `find_one`), once per code. Neither may be reached from the list
    endpoint any more — at ANY code count."""

    run(_seed_full_matrix())
    token, _ = create_admin_and_get_token(client, email="lcbatch11@example.com")

    with count_queries() as counts:
        assert client.get(
            "/api/location-codes", headers=auth_headers(token)
        ).status_code == 200

    assert counts["maps.find_one"] == 0, dict(counts)
    assert counts["route_points.find_one"] == 0, dict(counts)
    assert counts["location_codes.aggregate"] == 0


def test_the_single_code_endpoints_still_use_the_per_code_path(client):
    """The batching is scoped to the LIST endpoint only. GET
    /api/location-codes/{id} must keep using location_code_to_response()
    unchanged — proved by the per-code `find_one` fingerprint still being
    present on that route."""

    run(_seed_full_matrix())
    token, _ = create_admin_and_get_token(client, email="lcbatch12@example.com")

    entry = run(LocationCode.find_one({"code": "AAAA1111"}))

    with count_queries() as counts:
        response = client.get(
            f"/api/location-codes/{entry.id}", headers=auth_headers(token)
        )

    assert response.status_code == 200
    assert response.json()["code"] == "AAAA1111"

    assert counts["maps.find_one"] == 1, dict(counts)
    assert counts["route_points.find_one"] == 1, dict(counts)


def test_the_public_resolve_endpoint_is_untouched(client):
    """GET /resolve/{code} is the anonymous QR path. It has its own
    defensive re-check and must be completely unaffected by this pass."""

    seeded = run(_seed_full_matrix())

    response = client.get("/api/location-codes/resolve/AAAA1111")

    assert response.status_code == 200
    body = response.json()
    assert body["code"] == "AAAA1111"
    assert body["map_group_id"] == seeded["group_id"]
    assert body["floor"] == 3
    assert body["label"] == "Main Entrance"

    # An inactive code is still refused, anonymously, exactly as before.
    assert client.get("/api/location-codes/resolve/AAAA6666").status_code == 400


# ---------------------------------------------------------
# 5 — permissions and filtering unchanged
# ---------------------------------------------------------

def test_the_endpoint_still_requires_an_authenticated_admin(client):
    run(_seed_full_matrix())

    assert client.get("/api/location-codes").status_code == 401


def test_the_building_filter_still_scopes_the_result(client):
    run(_seed_full_matrix())
    token, _ = create_admin_and_get_token(client, email="lcbatch13@example.com")

    body = client.get(
        f"/api/location-codes?building_id={BUILDING_ID}",
        headers=auth_headers(token),
    ).json()

    assert body
    assert all(e["building_id"] == BUILDING_ID for e in body)
    assert not any(e["code"] == "BBBB4444" for e in body)


def test_the_map_filter_still_works(client):
    seeded = run(_seed_full_matrix())
    token, _ = create_admin_and_get_token(client, email="lcbatch14@example.com")

    body = client.get(
        f"/api/location-codes?map_id={seeded['floorless_map_id']}",
        headers=auth_headers(token),
    ).json()

    assert {e["code"] for e in body} == {"AAAA3333", "AAAA4444"}


def test_a_scoped_admin_still_sees_only_its_own_buildings(client):
    """The scope narrowing runs on the QUERY, before enrichment — the
    batched path must not widen what a restricted admin can see."""

    run(_seed_full_matrix())

    token, user = create_admin_and_get_token(
        client, email="lcbatch15@example.com"
    )

    async def _narrow():
        target = await User.get(user["id"])
        target.role = "building_manager"
        target.all_buildings = False
        target.building_ids = [OTHER_BUILDING_ID]
        await target.save()

    run(_narrow())

    body = client.get(
        "/api/location-codes", headers=auth_headers(token)
    ).json()

    assert {e["code"] for e in body} == {"BBBB4444"}
    assert all(e["building_id"] == OTHER_BUILDING_ID for e in body)


def test_a_scoped_admin_is_still_refused_an_out_of_scope_building(client):
    run(_seed_full_matrix())

    token, user = create_admin_and_get_token(
        client, email="lcbatch16@example.com"
    )

    async def _narrow():
        target = await User.get(user["id"])
        target.role = "building_manager"
        target.all_buildings = False
        target.building_ids = [OTHER_BUILDING_ID]
        await target.save()

    run(_narrow())

    response = client.get(
        f"/api/location-codes?building_id={BUILDING_ID}",
        headers=auth_headers(token),
    )

    assert response.status_code == 403
