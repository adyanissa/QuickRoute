"""
GET /api/rooms performance regression suite.

The list endpoint used to build its response with
`[await room_to_response(room) for room in rooms]`, which asks the database
three questions PER ROOM (RoutePoint.get, RouteEdge.find_one, Map.get) —
1 + 3N sequential round trips. Against a remote Atlas cluster that measured
~35 seconds for one building.

It now uses the batched path in routes/room_routes.py. These tests pin down
the two things that matter:

  * the response is EQUIVALENT to what the per-room path produced, for
    every navigability case and every degenerate room shape, and
  * the query count is CONSTANT — it does not grow with the number of
    rooms, and the per-room helpers are never reached from the list path.

Run with: pytest backend/tests/test_rooms_list_batching.py -v
"""

import asyncio
import contextlib
from collections import Counter

import pytest
from beanie import PydanticObjectId

from models.building_model import Building
from models.map_model import Map
from models.map_group_model import MapGroup
from models.room_model import Room
from models.route_edge_model import RouteEdge
from models.route_point_model import RoutePoint

from routes.room_routes import room_to_response


# ---------------------------------------------------------
# Query counting
#
# Wraps the driver-level collection methods, so it counts REAL round
# trips: Beanie's .find().to_list() is one `find`, and .get()/.find_one()
# is one `find_one`. Nothing is mocked out — the queries still execute.
# ---------------------------------------------------------

COUNTED_MODELS = (Room, RoutePoint, RouteEdge, Map, MapGroup, Building)
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


def total(counts):
    return sum(counts.values())


# ---------------------------------------------------------
# Seeding — written straight through Beanie so degenerate shapes
# (no route point, deleted route point, malformed id) can be built
# exactly as they occur in real data.
# ---------------------------------------------------------

BUILDING_ID = "6a836ffae3e4a269a4589f63"
OTHER_BUILDING_ID = "6a836ffae3e4a269a4589f64"


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


async def _make_point(map_id, *, name, is_active=True):
    point = RoutePoint(
        map_id=map_id,
        building_id=BUILDING_ID,
        name=name,
        x=10.0,
        y=10.0,
        point_type="hallway",
        floor=1,
        is_active=is_active,
    )
    await point.insert()
    return point


async def _make_edge(map_id, from_point_id, to_point_id, *, is_active=True):
    edge = RouteEdge(
        map_id=map_id,
        from_point_id=from_point_id,
        to_point_id=to_point_id,
        distance=10.0,
        is_active=is_active,
    )
    await edge.insert()
    return edge


async def _make_room(**kwargs):
    kwargs.setdefault("building_id", BUILDING_ID)
    kwargs.setdefault("name_en", "Room")
    kwargs.setdefault("room_type", "store")
    room = Room(**kwargs)
    await room.insert()
    return room


async def _seed_full_matrix():
    """
    One room for every branch of the navigability ladder plus both
    map_group_id outcomes. Returns the map so callers can assert on it.
    """

    group = MapGroup(code="BATCH-GRP", name="Batch Group", building_id=BUILDING_ID)
    await group.insert()

    grouped_map = Map(
        title="Grouped Floor",
        building_id=BUILDING_ID,
        map_group_id=str(group.id),
        floor=1,
    )
    await grouped_map.insert()

    lone_map = Map(title="Ungrouped Floor", building_id=BUILDING_ID, floor=2)
    await lone_map.insert()

    map_id = str(grouped_map.id)

    # 1 — connected + active  -> is_navigable True
    corridor = await _make_point(map_id, name="Corridor")
    connected_point = await _make_point(map_id, name="Connected")
    await _make_edge(map_id, str(corridor.id), str(connected_point.id))
    await _make_room(
        name_en="Connected Room",
        map_id=map_id,
        route_point_id=str(connected_point.id),
        floor=1,
    )

    # 2 — placed but no edge -> disconnected_from_graph
    lonely_point = await _make_point(map_id, name="Lonely")
    await _make_room(
        name_en="Disconnected Room",
        map_id=map_id,
        route_point_id=str(lonely_point.id),
        floor=1,
    )

    # 3 — only an INACTIVE edge -> still disconnected_from_graph
    inactive_edge_point = await _make_point(map_id, name="Inactive Edge")
    await _make_edge(
        map_id, str(corridor.id), str(inactive_edge_point.id), is_active=False
    )
    await _make_room(
        name_en="Inactive Edge Room",
        map_id=map_id,
        route_point_id=str(inactive_edge_point.id),
        floor=1,
    )

    # 4 — inactive route point -> inactive_route_point (wins over room state)
    dead_point = await _make_point(map_id, name="Dead", is_active=False)
    await _make_edge(map_id, str(corridor.id), str(dead_point.id))
    await _make_room(
        name_en="Inactive Point Room",
        map_id=map_id,
        route_point_id=str(dead_point.id),
        floor=1,
    )

    # 5 — route point id pointing at nothing -> route_point_not_found
    await _make_room(
        name_en="Orphan Room",
        map_id=map_id,
        route_point_id=str(PydanticObjectId()),
        floor=1,
    )

    # 6 — no route point at all, active room -> missing_route_point
    await _make_room(name_en="Unplaced Room", map_id=map_id, floor=1)

    # 7 — no route point, inactive room -> inactive_destination
    await _make_room(name_en="Retired Room", map_id=map_id, floor=1, is_active=False)

    # 8 — inactive room WITH a live connected point -> inactive_destination
    live_point = await _make_point(map_id, name="Live But Retired")
    await _make_edge(map_id, str(corridor.id), str(live_point.id))
    await _make_room(
        name_en="Retired Placed Room",
        map_id=map_id,
        route_point_id=str(live_point.id),
        floor=1,
        is_active=False,
    )

    # 9 — no map_id at all -> map_group_id must be None
    await _make_room(name_en="Mapless Room")

    # 10 — map with no group -> map_group_id must be None
    await _make_room(name_en="Ungrouped Room", map_id=str(lone_map.id), floor=2)

    # 11 — map_id pointing at a deleted map -> map_group_id None
    await _make_room(
        name_en="Dangling Map Room", map_id=str(PydanticObjectId()), floor=1
    )

    # 12 — malformed ids on both links -> must degrade, never raise
    await _make_room(
        name_en="Malformed Room",
        map_id="not-an-object-id",
        route_point_id="also-not-an-object-id",
    )

    # 13 — a room in ANOTHER building, to prove the filter still applies
    await _make_room(name_en="Other Building Room", building_id=OTHER_BUILDING_ID)

    return {"group_id": str(group.id), "map_id": map_id, "lone_map_id": str(lone_map.id)}


# ---------------------------------------------------------
# 1 — response equivalence with the per-room path
# ---------------------------------------------------------

def test_list_response_is_identical_to_the_per_room_path(client):
    """
    The strongest possible statement of "nothing changed": build the same
    list through the OLD per-room helper and assert field-for-field
    equality with what the endpoint now returns.
    """

    run(_seed_full_matrix())

    response = client.get(f"/api/rooms?building_id={BUILDING_ID}")
    assert response.status_code == 200, response.text
    batched = response.json()

    async def _reference():
        rooms = await Room.find({"building_id": BUILDING_ID}).to_list()
        return [
            (await room_to_response(room)).model_dump(mode="json") for room in rooms
        ]

    reference = run(_reference())

    assert len(batched) == len(reference) > 0

    by_id_batched = {entry["id"]: entry for entry in batched}
    by_id_reference = {entry["id"]: entry for entry in reference}

    assert by_id_batched.keys() == by_id_reference.keys()

    for room_id, expected in by_id_reference.items():
        assert by_id_batched[room_id] == expected, room_id


def test_every_room_field_is_present_and_unchanged(client):
    run(_seed_full_matrix())

    body = client.get(f"/api/rooms?building_id={BUILDING_ID}").json()
    entry = next(r for r in body if r["name_en"] == "Connected Room")

    for field in (
        "id", "building_id", "name_en", "name_local", "names",
        "semantic_publication_id", "semantic_entity_external_id",
        "semantic_entity_type", "room_number", "floor", "room_type",
        "description", "category", "map_id", "x", "y", "route_point_id",
        "parent_room_id", "map_group_id", "is_active", "created_at",
        "updated_at", "route_point_was_reused", "route_point_connected",
        "is_navigable", "navigation_unavailable_reason",
    ):
        assert field in entry, field

    # The one-shot create/update signals stay False on a plain GET, exactly
    # as they always have (schemas/room_schema.py).
    assert entry["route_point_was_reused"] is False
    assert entry["route_point_connected"] is False


# ---------------------------------------------------------
# 2 — is_navigable semantics
# ---------------------------------------------------------

def test_is_navigable_semantics_are_unchanged(client):
    run(_seed_full_matrix())

    body = client.get(f"/api/rooms?building_id={BUILDING_ID}").json()
    by_name = {entry["name_en"]: entry for entry in body}

    expected = {
        "Connected Room":        (True,  None),
        "Disconnected Room":     (False, "disconnected_from_graph"),
        "Inactive Edge Room":    (False, "disconnected_from_graph"),
        "Inactive Point Room":   (False, "inactive_route_point"),
        "Orphan Room":           (False, "route_point_not_found"),
        "Unplaced Room":         (False, "missing_route_point"),
        "Retired Room":          (False, "inactive_destination"),
        "Retired Placed Room":   (False, "inactive_destination"),
        "Mapless Room":          (False, "missing_route_point"),
        "Ungrouped Room":        (False, "missing_route_point"),
        "Dangling Map Room":     (False, "missing_route_point"),
        "Malformed Room":        (False, "route_point_not_found"),
    }

    for name, (is_navigable, reason) in expected.items():
        assert by_name[name]["is_navigable"] is is_navigable, name
        assert by_name[name]["navigation_unavailable_reason"] == reason, name


def test_inactive_route_point_still_outranks_inactive_room(client):
    """
    Precedence guard: a deactivated RoutePoint may also flip the Room to
    inactive. The more specific reason must win — the same ordering
    compute_room_navigability() documents.
    """

    async def _seed():
        map_item = Map(title="Precedence", building_id=BUILDING_ID, floor=1)
        await map_item.insert()
        point = await _make_point(str(map_item.id), name="Dead", is_active=False)
        await _make_room(
            name_en="Both Inactive",
            map_id=str(map_item.id),
            route_point_id=str(point.id),
            is_active=False,
        )

    run(_seed())

    body = client.get(f"/api/rooms?building_id={BUILDING_ID}").json()
    entry = next(r for r in body if r["name_en"] == "Both Inactive")

    assert entry["is_navigable"] is False
    assert entry["navigation_unavailable_reason"] == "inactive_route_point"


def test_an_edge_from_either_end_counts_as_connected(client):
    """Connectivity is direction-agnostic, as it always was."""

    async def _seed():
        map_item = Map(title="Either End", building_id=BUILDING_ID, floor=1)
        await map_item.insert()
        map_id = str(map_item.id)

        corridor = await _make_point(map_id, name="Corridor")
        from_side = await _make_point(map_id, name="From Side")
        to_side = await _make_point(map_id, name="To Side")

        await _make_edge(map_id, str(from_side.id), str(corridor.id))
        await _make_edge(map_id, str(corridor.id), str(to_side.id))

        await _make_room(
            name_en="From Side Room", map_id=map_id, route_point_id=str(from_side.id)
        )
        await _make_room(
            name_en="To Side Room", map_id=map_id, route_point_id=str(to_side.id)
        )

    run(_seed())

    body = client.get(f"/api/rooms?building_id={BUILDING_ID}").json()
    by_name = {entry["name_en"]: entry for entry in body}

    assert by_name["From Side Room"]["is_navigable"] is True
    assert by_name["To Side Room"]["is_navigable"] is True


# ---------------------------------------------------------
# 3 — map_group_id resolution
# ---------------------------------------------------------

def test_map_group_id_resolution_is_unchanged(client):
    seeded = run(_seed_full_matrix())

    body = client.get(f"/api/rooms?building_id={BUILDING_ID}").json()
    by_name = {entry["name_en"]: entry for entry in body}

    # Resolved live from Map(map_id).map_group_id — never stored on Room.
    assert by_name["Connected Room"]["map_group_id"] == seeded["group_id"]

    # A map that belongs to no group, a room with no map, a dangling map id
    # and a malformed map id all resolve to None rather than raising.
    assert by_name["Ungrouped Room"]["map_group_id"] is None
    assert by_name["Mapless Room"]["map_group_id"] is None
    assert by_name["Dangling Map Room"]["map_group_id"] is None
    assert by_name["Malformed Room"]["map_group_id"] is None


def test_rooms_sharing_one_map_all_resolve_the_same_group(client):
    """The map is fetched once and reused — every room on it must still
    report the group, not just the first."""

    seeded = run(_seed_full_matrix())

    body = client.get(f"/api/rooms?building_id={BUILDING_ID}").json()
    on_grouped_map = [r for r in body if r["map_id"] == seeded["map_id"]]

    assert len(on_grouped_map) >= 5
    assert all(r["map_group_id"] == seeded["group_id"] for r in on_grouped_map)


# ---------------------------------------------------------
# 4 — constant query count
# ---------------------------------------------------------

async def _seed_n_connected_rooms(count):
    map_item = Map(title=f"Scale {count}", building_id=BUILDING_ID, floor=1)
    await map_item.insert()
    map_id = str(map_item.id)

    corridor = await _make_point(map_id, name="Corridor")

    for index in range(count):
        point = await _make_point(map_id, name=f"P{index}")
        await _make_edge(map_id, str(corridor.id), str(point.id))
        await _make_room(
            name_en=f"Room {index}",
            map_id=map_id,
            route_point_id=str(point.id),
            floor=1,
        )


def test_query_count_does_not_grow_with_the_number_of_rooms(client):
    run(_seed_n_connected_rooms(3))

    with count_queries() as small_counts:
        small = client.get(f"/api/rooms?building_id={BUILDING_ID}")

    assert small.status_code == 200
    assert len(small.json()) == 3

    run(Room.delete_all())
    run(RoutePoint.delete_all())
    run(RouteEdge.delete_all())
    run(Map.delete_all())

    run(_seed_n_connected_rooms(40))

    with count_queries() as large_counts:
        large = client.get(f"/api/rooms?building_id={BUILDING_ID}")

    assert large.status_code == 200
    assert len(large.json()) == 40

    # 13x the rooms, byte-for-byte the same number of database calls.
    assert total(small_counts) == total(large_counts), (
        f"query count grew with room count: "
        f"3 rooms -> {dict(small_counts)}, 40 rooms -> {dict(large_counts)}"
    )

    # And that constant is small: rooms + route_points + route_edges + maps.
    assert total(large_counts) <= 4, dict(large_counts)


def test_the_four_batched_queries_are_the_expected_ones(client):
    run(_seed_n_connected_rooms(6))

    with count_queries() as counts:
        assert client.get(f"/api/rooms?building_id={BUILDING_ID}").status_code == 200

    assert counts["rooms.find"] == 1
    assert counts["route_points.find"] == 1
    assert counts["route_edges.find"] == 1
    assert counts["maps.find"] == 1


def test_an_empty_building_costs_a_single_query(client):
    """Nothing to enrich means nothing to fetch — the batched path skips
    every lookup whose input set is empty."""

    with count_queries() as counts:
        response = client.get(f"/api/rooms?building_id={BUILDING_ID}")

    assert response.status_code == 200
    assert response.json() == []
    assert total(counts) == 1
    assert counts["rooms.find"] == 1


# ---------------------------------------------------------
# 5 — no per-room fallback
# ---------------------------------------------------------

def test_the_list_endpoint_never_issues_a_per_room_lookup(client):
    """
    The old path's fingerprint was RoutePoint.get / Map.get (both
    `find_one`) and RouteEdge.find_one, once per room. None of them may be
    reached from the list endpoint any more — at ANY room count.
    """

    run(_seed_full_matrix())

    with count_queries() as counts:
        assert client.get(f"/api/rooms?building_id={BUILDING_ID}").status_code == 200

    assert counts["route_points.find_one"] == 0, dict(counts)
    assert counts["route_edges.find_one"] == 0, dict(counts)
    assert counts["maps.find_one"] == 0, dict(counts)

    # No aggregation pipeline snuck in either.
    assert counts["rooms.aggregate"] == 0
    assert counts["route_edges.aggregate"] == 0


def test_the_single_room_endpoints_still_use_the_per_room_path(
    client, monkeypatch
):
    """
    The batching is scoped to the LIST endpoint only. GET /api/rooms/{id}
    must keep going through room_to_response()/compute_room_navigability()
    and must NEVER be served by the batched list enrichment.

    HOW THIS IS ASSERTED, AND WHY IT CHANGED
    ----------------------------------------
    This test used to prove the point by fingerprinting the QUERY SHAPE:
    it required exactly one `route_edges.find_one`, because
    compute_room_navigability() used to answer "is any active edge
    touching this point?" with a single RouteEdge.find_one().

    That fingerprint is now stale, and correctly so. The connectivity rule
    moved into services/graph_connectivity_service, where
    room_connection_state() loads a whole-floor FloorGraphIndex —
    "three reads per map, never per point" — via RoutePoint.find /
    RouteEdge.find / Room.find. The single-room route therefore issues
    `route_edges.find`, not `route_edges.find_one`. That is a deliberate
    change: the index is what makes the newer `only_invalid_edges` verdict
    and transitive nested-parent resolution possible, and a per-point
    existence check cannot express either. Forcing the production code back
    to find_one to satisfy this assertion would undo a real improvement.

    So the assertion now targets the invariant this test actually exists to
    protect — WHICH CODE PATH serves the route — by spying on the functions
    themselves. That is immune to any future change in how either path
    phrases its queries, which is exactly the property the old version
    lacked.
    """

    import routes.room_routes as room_routes

    calls = Counter()

    def spy_async(name, original):
        async def wrapper(*args, **kwargs):
            calls[name] += 1
            return await original(*args, **kwargs)

        return wrapper

    def spy_sync(name, original):
        def wrapper(*args, **kwargs):
            calls[name] += 1
            return original(*args, **kwargs)

        return wrapper

    for name in ("room_to_response", "compute_room_navigability",
                 "resolve_room_map_group_id", "build_room_list_enrichment",
                 "build_room_list_responses"):
        monkeypatch.setattr(
            room_routes, name, spy_async(name, getattr(room_routes, name))
        )

    monkeypatch.setattr(
        room_routes,
        "room_to_list_response",
        spy_sync("room_to_list_response", room_routes.room_to_list_response),
    )

    run(_seed_full_matrix())

    room = run(Room.find_one({"name_en": "Connected Room"}))

    response = client.get(f"/api/rooms/{room.id}")

    # 1. Response behaviour is correct and unchanged.
    assert response.status_code == 200
    assert response.json()["is_navigable"] is True
    assert response.json()["navigation_unavailable_reason"] is None
    assert response.json()["id"] == str(room.id)

    # 2. It went through the per-room path.
    assert calls["room_to_response"] == 1, dict(calls)
    assert calls["compute_room_navigability"] == 1, dict(calls)
    assert calls["resolve_room_map_group_id"] == 1, dict(calls)

    # 3. It was NOT routed through the list batching implementation.
    assert calls["build_room_list_responses"] == 0, dict(calls)
    assert calls["build_room_list_enrichment"] == 0, dict(calls)
    assert calls["room_to_list_response"] == 0, dict(calls)


def test_the_list_endpoint_is_served_by_the_batched_path(client, monkeypatch):
    """
    The mirror image of the test above, and the reason both are worth
    having: the LIST route must be served by the batched enrichment and
    must never fall back to the per-room builder — no matter what query
    shapes either path happens to use.
    """

    import routes.room_routes as room_routes

    calls = Counter()

    def spy_async(name, original):
        async def wrapper(*args, **kwargs):
            calls[name] += 1
            return await original(*args, **kwargs)

        return wrapper

    for name in ("room_to_response", "build_room_list_responses",
                 "build_room_list_enrichment"):
        monkeypatch.setattr(
            room_routes, name, spy_async(name, getattr(room_routes, name))
        )

    run(_seed_full_matrix())

    response = client.get(f"/api/rooms?building_id={BUILDING_ID}")

    assert response.status_code == 200
    assert len(response.json()) > 0

    assert calls["build_room_list_responses"] == 1, dict(calls)
    assert calls["build_room_list_enrichment"] == 1, dict(calls)

    # Once for the whole list, never once per room.
    assert calls["room_to_response"] == 0, dict(calls)


# ---------------------------------------------------------
# 6 — degenerate rooms keep their current behaviour
# ---------------------------------------------------------

def test_rooms_without_a_route_point_or_map_are_returned_normally(client):
    run(_seed_full_matrix())

    body = client.get(f"/api/rooms?building_id={BUILDING_ID}").json()
    by_name = {entry["name_en"]: entry for entry in body}

    mapless = by_name["Mapless Room"]
    assert mapless["map_id"] is None
    assert mapless["route_point_id"] is None
    assert mapless["map_group_id"] is None
    assert mapless["is_navigable"] is False
    assert mapless["navigation_unavailable_reason"] == "missing_route_point"

    unplaced = by_name["Unplaced Room"]
    assert unplaced["route_point_id"] is None
    assert unplaced["map_group_id"] is not None  # its map IS in a group
    assert unplaced["navigation_unavailable_reason"] == "missing_route_point"


def test_a_list_of_only_degenerate_rooms_does_not_error(client):
    """No valid route point and no valid map anywhere: the batched path
    must skip those lookups rather than issue an $in with an empty list."""

    async def _seed():
        await _make_room(name_en="A")
        await _make_room(name_en="B", map_id="not-an-object-id")
        await _make_room(name_en="C", route_point_id="also-bad")

    run(_seed())

    with count_queries() as counts:
        response = client.get(f"/api/rooms?building_id={BUILDING_ID}")

    assert response.status_code == 200
    assert len(response.json()) == 3
    assert all(r["is_navigable"] is False for r in response.json())
    assert all(r["map_group_id"] is None for r in response.json())
    assert total(counts) == 1


# ---------------------------------------------------------
# 7 — filtering and public access are untouched
# ---------------------------------------------------------

def test_the_building_filter_still_scopes_the_result(client):
    run(_seed_full_matrix())

    body = client.get(f"/api/rooms?building_id={BUILDING_ID}").json()
    assert all(r["building_id"] == BUILDING_ID for r in body)
    assert not any(r["name_en"] == "Other Building Room" for r in body)


def test_the_floor_filter_still_works(client):
    seeded = run(_seed_full_matrix())

    body = client.get(
        f"/api/rooms?building_id={BUILDING_ID}&floor=2"
    ).json()

    assert body
    assert all(r["floor"] == 2 for r in body)
    assert all(r["map_id"] == seeded["lone_map_id"] for r in body)


def test_the_endpoint_is_still_reachable_anonymously(client):
    """The public Destination Selection screen calls this with no token —
    optional auth behaviour must be exactly as before."""

    run(_seed_full_matrix())

    response = client.get(f"/api/rooms?building_id={BUILDING_ID}")

    assert response.status_code == 200
    assert len(response.json()) > 0
