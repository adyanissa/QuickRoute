"""
"Every accepted navigable room gets its own QR / LocationCode."

Covers services/room_location_code_service.ensure_room_location_codes and
its two call sites:

  POST /api/maps/{map_id}/semantic-analysis/destinations/apply
  POST /api/route-edges/auto-connect-destinations/apply

The invariant under test, in one sentence: a Room is given exactly ONE
active LocationCode as soon as — and never before — it has an arrival
RoutePoint that is genuinely joined to its own floor's corridor graph, and
running either apply again never mints a second one.

Deliberately reuses tests/test_semantic_destinations.py's fixtures rather
than building a parallel harness, so these tests exercise the same real
endpoints an admin drives.

No test here makes any AI provider call: the semantic publication is
inserted directly as a document, exactly as the existing semantic-
destination tests do, so Claude is never contacted.

Run with: pytest backend/tests/test_room_location_codes.py -v
"""

import pytest
from beanie import PydanticObjectId

from tests.test_api_integration import auth_headers, create_admin_and_get_token
from tests.test_semantic_destinations import (
    _apply,
    _auto_connect_apply,
    _create_edge,
    _create_map,
    _create_point,
    _create_publication,
    _place,
)

from models.location_code_model import LocationCode
from models.room_model import Room
from models.route_edge_model import RouteEdge
from models.route_point_model import RoutePoint
from services import room_location_code_service as qr_service
from services.semantic_publication_service import compute_authoritative_floor_code


# Every map in this file is floor 1, and apply() refuses to run against a
# stale semantic floor code (semantic_destination_service._floor_code_
# mismatch recomputes it from Map.floor), so the publication fixture must
# use the authoritative code rather than the generic "floor-1" default.
FLOOR_1_CODE = compute_authoritative_floor_code(1)

RESOLVE_URL = "/api/location-codes/resolve/{code}"
PUBLIC_POINT_URL = "/api/route-points/public/{point_id}"


# ---------------------------------------------------------
# Helpers
# ---------------------------------------------------------


async def _codes_for_point(route_point_id: str):
    return await LocationCode.find({"route_point_id": route_point_id}).to_list()


async def _active_codes_on_map(map_id: str):
    return await LocationCode.find({"map_id": map_id, "is_active": True}).to_list()


async def _setup_room_with_corridor(client, token, *, place_id="place_401", name="Room 401"):
    """
    The realistic admin path: a corridor point already exists on the map,
    the semantic item is accepted, and the admin places it at x/y during
    preview review. Returns (map, corridor_point, apply_result, room).
    """

    building = client.post(
        "/api/locations/buildings",
        json={"name_en": f"QR Building {place_id}"},
        headers=auth_headers(token),
    )
    assert building.status_code == 201, building.text
    building_id = building.json()["id"]

    map_item = _create_map(
        client, token, title=f"QR Map {place_id}", floor=1, building_id=building_id
    )
    corridor = _create_point(
        client, token, map_item["id"], "Corridor A", 100, 100, floor=1
    )

    await _create_publication(
        map_item["id"],
        places=[_place(place_id, name, floor_external_id=FLOOR_1_CODE)],
        floor_external_id=FLOOR_1_CODE,
    )

    result = _apply(
        client,
        token,
        map_item["id"],
        [{"semantic_item_id": place_id, "entity_kind": "place", "x": 110, "y": 100}],
    )

    room = await Room.find_one({"semantic_entity_external_id": place_id})
    return map_item, corridor, result, room


# ---------------------------------------------------------
# 1-3. Materialization: Room, arrival RoutePoint, and the link
# ---------------------------------------------------------


@pytest.mark.asyncio
async def test_accepted_room_materializes_room_and_arrival_point(client):
    token, _ = create_admin_and_get_token(client, email="qr-materialize@example.com")
    map_item, _corridor, result, room = await _setup_room_with_corridor(client, token)

    assert result["rooms_created"] == 1
    assert room is not None
    assert room.name_en == "Room 401"

    # 3. Room.route_point_id points at the arrival RoutePoint.
    assert room.route_point_id
    point = await RoutePoint.get(PydanticObjectId(room.route_point_id))
    assert point is not None
    assert point.map_id == map_item["id"]
    assert point.point_type == "room"
    # And the link is bidirectional, which is what lets a scanned QR be
    # traced back to its room without any new LocationCode field.
    assert point.room_id == str(room.id)


# ---------------------------------------------------------
# 4. No QR until the arrival point is actually connected
# ---------------------------------------------------------


@pytest.mark.asyncio
async def test_no_qr_while_arrival_point_is_not_connected(client):
    token, _ = create_admin_and_get_token(client, email="qr-unconnected@example.com")
    map_item, _corridor, result, room = await _setup_room_with_corridor(
        client, token, place_id="place_unconn", name="Unconnected Room"
    )

    # Semantic apply deliberately creates no RouteEdge, so the room is not
    # navigable yet and must NOT have been given a code.
    assert result["qr_codes_created"] == 0
    assert result["rooms_unconnected"] >= 1
    assert await _codes_for_point(room.route_point_id) == []

    reasons = {
        entry["reason"]
        for entry in result["rooms_needing_review"]
        if entry["room_id"] == str(room.id)
    }
    assert reasons == {"not_connected_to_graph"}

    # And nothing invented an edge to make it navigable.
    edges = await RouteEdge.find({"map_id": map_item["id"]}).to_list()
    assert edges == []


# ---------------------------------------------------------
# 5. One QR appears once the room becomes navigable
# ---------------------------------------------------------


@pytest.mark.asyncio
async def test_auto_connect_apply_issues_exactly_one_qr(client):
    token, _ = create_admin_and_get_token(client, email="qr-connected@example.com")
    map_item, corridor, _result, room = await _setup_room_with_corridor(
        client, token, place_id="place_conn", name="Connected Room"
    )

    connect_result = _auto_connect_apply(
        client,
        token,
        map_item["id"],
        [
            {
                "destination_point_id": room.route_point_id,
                "corridor_point_id": corridor["id"],
            }
        ],
    )

    assert connect_result["created"] == 1
    assert connect_result["qr_codes_created"] == 1
    assert connect_result["rooms_unconnected"] == 0

    codes = await _codes_for_point(room.route_point_id)
    assert len(codes) == 1
    assert codes[0].is_active is True
    assert codes[0].map_id == map_item["id"]
    assert codes[0].building_id == map_item["building_id"]
    assert codes[0].route_point_id == room.route_point_id
    # Label defaults to the room's approved name so a printed sheet is
    # readable without a second lookup.
    assert codes[0].label == "Connected Room"


# ---------------------------------------------------------
# 6-7. Idempotency — the critical requirement
# ---------------------------------------------------------


@pytest.mark.asyncio
async def test_applying_twice_creates_no_duplicate_qr_room_point_or_edge(client):
    token, _ = create_admin_and_get_token(client, email="qr-idempotent@example.com")
    map_item, corridor, _result, room = await _setup_room_with_corridor(
        client, token, place_id="place_idem", name="Idempotent Room"
    )

    pair = [
        {
            "destination_point_id": room.route_point_id,
            "corridor_point_id": corridor["id"],
        }
    ]

    first = _auto_connect_apply(client, token, map_item["id"], pair)
    assert first["qr_codes_created"] == 1

    # Re-run BOTH applies a second time, in the same order an admin would.
    second_semantic = _apply(
        client,
        token,
        map_item["id"],
        [{"semantic_item_id": "place_idem", "entity_kind": "place", "x": 110, "y": 100}],
    )
    second_connect = _auto_connect_apply(client, token, map_item["id"], pair)

    # The code is recognised and reused, never re-minted.
    assert second_semantic["qr_codes_created"] == 0
    assert second_semantic["qr_codes_reused"] == 1
    assert second_connect["qr_codes_created"] == 0
    assert second_connect["qr_codes_reused"] == 1
    assert second_connect["skipped_existing"] == 1

    # And nothing else duplicated either.
    assert len(await _codes_for_point(room.route_point_id)) == 1
    assert len(await Room.find({"map_id": map_item["id"]}).to_list()) == 1
    assert (
        len(
            await RoutePoint.find(
                {"map_id": map_item["id"], "point_type": "room"}
            ).to_list()
        )
        == 1
    )
    assert len(await RouteEdge.find({"map_id": map_item["id"]}).to_list()) == 1


@pytest.mark.asyncio
async def test_ensure_is_idempotent_when_called_directly_many_times(client):
    token, _ = create_admin_and_get_token(client, email="qr-direct@example.com")
    map_item, corridor, _result, room = await _setup_room_with_corridor(
        client, token, place_id="place_direct", name="Direct Room"
    )
    _create_edge(client, token, map_item["id"], room.route_point_id, corridor["id"])

    first = await qr_service.ensure_room_location_codes(map_item["id"])
    assert first["qr_codes_created"] == 1

    for _ in range(3):
        again = await qr_service.ensure_room_location_codes(map_item["id"])
        assert again["qr_codes_created"] == 0
        assert again["qr_codes_reused"] == 1

    assert len(await _active_codes_on_map(map_item["id"])) == 1


# ---------------------------------------------------------
# 8. A blocking / unaccepted item never becomes a live QR
# ---------------------------------------------------------


@pytest.mark.asyncio
async def test_unaccepted_item_never_gets_a_room_or_qr(client):
    token, _ = create_admin_and_get_token(client, email="qr-blocking@example.com")

    building = client.post(
        "/api/locations/buildings",
        json={"name_en": "QR Blocking Building"},
        headers=auth_headers(token),
    )
    building_id = building.json()["id"]
    map_item = _create_map(
        client, token, title="QR Blocking Map", floor=1, building_id=building_id
    )
    corridor = _create_point(client, token, map_item["id"], "Corridor B", 100, 100, floor=1)

    # Still pending review — exactly the "blocking review item" case.
    await _create_publication(
        map_item["id"],
        places=[
            _place(
                "place_pending",
                "Pending Room",
                status="pending",
                floor_external_id=FLOOR_1_CODE,
            )
        ],
        floor_external_id=FLOOR_1_CODE,
    )

    result = _apply(
        client,
        token,
        map_item["id"],
        [{"semantic_item_id": "place_pending", "entity_kind": "place", "x": 110, "y": 100}],
    )

    assert result["rooms_created"] == 0
    assert await Room.find({"map_id": map_item["id"]}).to_list() == []
    assert await _active_codes_on_map(map_item["id"]) == []

    # Even a later auto-connect run cannot conjure one, because no Room and
    # no destination point were ever created.
    connect = _auto_connect_apply(
        client,
        token,
        map_item["id"],
        [
            {
                "destination_point_id": corridor["id"],
                "corridor_point_id": corridor["id"],
            }
        ],
    )
    assert connect["qr_codes_created"] == 0
    assert await _active_codes_on_map(map_item["id"]) == []


# ---------------------------------------------------------
# 9. A room with no coordinates is reported, never invented
# ---------------------------------------------------------


@pytest.mark.asyncio
async def test_unplaced_room_is_reported_for_review_and_gets_no_qr(client):
    token, _ = create_admin_and_get_token(client, email="qr-unplaced@example.com")

    building = client.post(
        "/api/locations/buildings",
        json={"name_en": "QR Unplaced Building"},
        headers=auth_headers(token),
    )
    building_id = building.json()["id"]
    map_item = _create_map(
        client, token, title="QR Unplaced Map", floor=1, building_id=building_id
    )

    await _create_publication(
        map_item["id"],
        places=[_place("place_noxy", "Unplaced Room", floor_external_id=FLOOR_1_CODE)],
        floor_external_id=FLOOR_1_CODE,
    )

    # Accepted, but the admin gave no x/y — semantic analysis has no
    # coordinates of its own, so no arrival point can exist.
    result = _apply(client, token, map_item["id"], [{"semantic_item_id": "place_noxy", "entity_kind": "place"}])

    room = await Room.find_one({"semantic_entity_external_id": "place_noxy"})
    assert room is not None
    assert room.route_point_id is None

    assert result["qr_codes_created"] == 0
    assert result["rooms_unplaced"] >= 1
    assert {
        entry["reason"]
        for entry in result["rooms_needing_review"]
        if entry["room_id"] == str(room.id)
    } == {"no_arrival_point"}

    assert await _active_codes_on_map(map_item["id"]) == []
    assert await RoutePoint.find({"map_id": map_item["id"]}).to_list() == []


# ---------------------------------------------------------
# 10-11. Public QR resolution and the arrival-comparison contract
# ---------------------------------------------------------


@pytest.mark.asyncio
async def test_public_resolve_returns_the_rooms_arrival_route_point(client):
    token, _ = create_admin_and_get_token(client, email="qr-resolve@example.com")
    map_item, corridor, _result, room = await _setup_room_with_corridor(
        client, token, place_id="place_resolve", name="Resolvable Room"
    )
    _create_edge(client, token, map_item["id"], room.route_point_id, corridor["id"])
    await qr_service.ensure_room_location_codes(map_item["id"])

    code = (await _codes_for_point(room.route_point_id))[0]

    # Public, unauthenticated — the QR-scanner contract.
    resolved = client.get(RESOLVE_URL.format(code=code.code))
    assert resolved.status_code == 200, resolved.text
    body = resolved.json()

    assert body["route_point_id"] == room.route_point_id
    assert body["map_id"] == map_item["id"]
    assert body["building_id"] == map_item["building_id"]
    assert body["floor"] == 1


@pytest.mark.asyncio
async def test_scanned_point_carries_room_id_for_arrival_comparison(client):
    """
    The arrival check compares stable ids, never names, and needs no new
    field on LocationCode: resolve gives a route_point_id, and the PUBLIC
    route-point endpoint already exposes that point's room_id.
    """

    token, _ = create_admin_and_get_token(client, email="qr-arrival@example.com")
    map_item, corridor, _result, room = await _setup_room_with_corridor(
        client, token, place_id="place_arrival", name="Arrival Room"
    )
    _create_edge(client, token, map_item["id"], room.route_point_id, corridor["id"])
    await qr_service.ensure_room_location_codes(map_item["id"])

    code = (await _codes_for_point(room.route_point_id))[0]

    resolved = client.get(RESOLVE_URL.format(code=code.code)).json()
    point = client.get(PUBLIC_POINT_URL.format(point_id=resolved["route_point_id"]))
    assert point.status_code == 200, point.text

    assert point.json()["room_id"] == str(room.id)


@pytest.mark.asyncio
async def test_scanning_a_different_room_resolves_to_that_other_room(client):
    """
    The relocate case: two navigable rooms on one map, each with its own
    code, each resolving to its own arrival point and its own room id — so
    the frontend can tell "this is my destination" from "this is somewhere
    else" purely by id.
    """

    token, _ = create_admin_and_get_token(client, email="qr-relocate@example.com")

    building = client.post(
        "/api/locations/buildings",
        json={"name_en": "QR Relocate Building"},
        headers=auth_headers(token),
    )
    building_id = building.json()["id"]
    map_item = _create_map(
        client, token, title="QR Relocate Map", floor=1, building_id=building_id
    )
    corridor = _create_point(client, token, map_item["id"], "Corridor C", 100, 100, floor=1)

    await _create_publication(
        map_item["id"],
        places=[
            _place("place_415", "Room 415", floor_external_id=FLOOR_1_CODE),
            _place("place_428", "Room 428", floor_external_id=FLOOR_1_CODE),
        ],
        floor_external_id=FLOOR_1_CODE,
    )
    _apply(
        client,
        token,
        map_item["id"],
        [
            {"semantic_item_id": "place_415", "entity_kind": "place", "x": 110, "y": 100},
            {"semantic_item_id": "place_428", "entity_kind": "place", "x": 100, "y": 130},
        ],
    )

    room_415 = await Room.find_one({"semantic_entity_external_id": "place_415"})
    room_428 = await Room.find_one({"semantic_entity_external_id": "place_428"})

    _create_edge(client, token, map_item["id"], room_415.route_point_id, corridor["id"])
    _create_edge(client, token, map_item["id"], room_428.route_point_id, corridor["id"])

    summary = await qr_service.ensure_room_location_codes(map_item["id"])
    assert summary["qr_codes_created"] == 2

    code_415 = (await _codes_for_point(room_415.route_point_id))[0]
    code_428 = (await _codes_for_point(room_428.route_point_id))[0]
    assert code_415.code != code_428.code

    for code, room in ((code_415, room_415), (code_428, room_428)):
        resolved = client.get(RESOLVE_URL.format(code=code.code)).json()
        assert resolved["route_point_id"] == room.route_point_id
        point = client.get(
            PUBLIC_POINT_URL.format(point_id=resolved["route_point_id"])
        ).json()
        assert point["room_id"] == str(room.id)

    # And a route between the two really does exist through the corridor —
    # the graph is traversed via RouteEdges, never via the codes.
    route = client.post(
        "/api/navigation/multi-floor-route",
        json={
            "start_point_id": room_415.route_point_id,
            "end_point_id": room_428.route_point_id,
        },
    )
    assert route.status_code == 200, route.text
    assert route.json()["destination_point_id"] == room_428.route_point_id


# ---------------------------------------------------------
# 12. Existing QR APIs stay backward compatible
# ---------------------------------------------------------


@pytest.mark.asyncio
async def test_manually_generated_code_is_reused_not_duplicated(client):
    """
    An admin who already generated a code by hand for the arrival point
    must not end up with a second, automatic one.
    """

    token, _ = create_admin_and_get_token(client, email="qr-manual@example.com")
    map_item, corridor, _result, room = await _setup_room_with_corridor(
        client, token, place_id="place_manual", name="Manual Room"
    )
    _create_edge(client, token, map_item["id"], room.route_point_id, corridor["id"])

    manual = client.post(
        "/api/location-codes/generate",
        json={"route_point_id": room.route_point_id, "label": "Hand made"},
        headers=auth_headers(token),
    )
    assert manual.status_code == 201, manual.text

    summary = await qr_service.ensure_room_location_codes(map_item["id"])
    assert summary["qr_codes_created"] == 0
    assert summary["qr_codes_reused"] == 1

    codes = await _codes_for_point(room.route_point_id)
    assert len(codes) == 1
    assert codes[0].label == "Hand made"


def test_generated_code_format_is_unchanged(client):
    """The shared generator must keep producing the same 8-character
    ambiguity-free format the printed labels and the manual endpoint use."""

    for _ in range(50):
        code = qr_service.generate_location_code_candidate()
        assert len(code) == 8
        assert set(code) <= set(qr_service.LOCATION_CODE_ALPHABET)
        # No characters that are easy to misread on a printed label.
        assert not (set(code) & set("01OI"))


@pytest.mark.asyncio
async def test_admin_location_code_listing_still_requires_auth(client):
    token, _ = create_admin_and_get_token(client, email="qr-authz@example.com")
    map_item, corridor, _result, room = await _setup_room_with_corridor(
        client, token, place_id="place_authz", name="Authz Room"
    )
    _create_edge(client, token, map_item["id"], room.route_point_id, corridor["id"])
    await qr_service.ensure_room_location_codes(map_item["id"])

    # Automatically issued codes are still admin-only inventory.
    assert client.get("/api/location-codes").status_code == 401
    listed = client.get("/api/location-codes", headers=auth_headers(token))
    assert listed.status_code == 200
    assert len(listed.json()) == 1


# ---------------------------------------------------------
# 13. An inactive / detached arrival point never yields a QR
# ---------------------------------------------------------


@pytest.mark.asyncio
async def test_inactive_arrival_point_is_reported_not_coded(client):
    token, _ = create_admin_and_get_token(client, email="qr-inactive@example.com")
    map_item, corridor, _result, room = await _setup_room_with_corridor(
        client, token, place_id="place_inactive", name="Inactive Room"
    )
    _create_edge(client, token, map_item["id"], room.route_point_id, corridor["id"])

    point = await RoutePoint.get(PydanticObjectId(room.route_point_id))
    point.is_active = False
    await point.save()

    summary = await qr_service.ensure_room_location_codes(map_item["id"])
    assert summary["qr_codes_created"] == 0
    assert summary["rooms_unplaced"] == 1
    assert {
        entry["reason"] for entry in summary["rooms_needing_review"]
    } == {"arrival_point_missing_or_inactive"}
    assert await _active_codes_on_map(map_item["id"]) == []


@pytest.mark.asyncio
async def test_edge_on_another_map_does_not_make_a_room_navigable(client):
    """
    Connectivity is per-floor: an edge recorded on a different map must
    never be mistaken for this room's own corridor connection.
    """

    token, _ = create_admin_and_get_token(client, email="qr-othermap@example.com")
    map_item, _corridor, _result, room = await _setup_room_with_corridor(
        client, token, place_id="place_othermap", name="Other Map Room"
    )

    other_map = _create_map(
        client,
        token,
        title="QR Other Map",
        floor=2,
        building_id=map_item["building_id"],
    )
    other_a = _create_point(client, token, other_map["id"], "Other A", 10, 10, floor=2)
    other_b = _create_point(client, token, other_map["id"], "Other B", 60, 10, floor=2)
    _create_edge(client, token, other_map["id"], other_a["id"], other_b["id"])

    summary = await qr_service.ensure_room_location_codes(map_item["id"])
    assert summary["qr_codes_created"] == 0
    assert summary["rooms_unconnected"] == 1
    assert await _active_codes_on_map(map_item["id"]) == []
