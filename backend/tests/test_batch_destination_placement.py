"""
Tests for "Fast batch destination placement" ("Place All Destinations" /
"Save All Destinations"): the existing

  POST /api/maps/{map_id}/semantic-analysis/destinations/apply

endpoint, extended with an optional `all_or_nothing` flag (see
services/semantic_destination_service.py's `_validate_accepted_item_for_
batch` + the pre-write validation pass added to
`apply_semantic_destinations`). NO NEW ENDPOINT WAS ADDED — Section 7 of
the batch-placement spec explicitly says to inspect the existing preview/
apply endpoint first and reuse it if it already safely supports a
complete batch; after inspection it did, once given this one additional
flag plus a bounds/existence pre-validation pass that runs before any
writes.

Default behavior (all_or_nothing omitted or False) is completely
unchanged — see test_semantic_destinations.py, which is re-run alongside
this file and must still pass unmodified.

Run with: pytest backend/tests/test_batch_destination_placement.py -v
"""

from beanie import PydanticObjectId

from tests.test_api_integration import auth_headers, create_admin_and_get_token

from models.map_model import Map
from models.room_model import Room
from models.route_point_model import RoutePoint
from models.route_edge_model import RouteEdge
from models.semantic_map_publication_model import SemanticMapPublication
from services.semantic_publication_service import compute_authoritative_floor_code


DEST_APPLY_URL = "/api/maps/{map_id}/semantic-analysis/destinations/apply"
DEST_PREVIEW_URL = "/api/maps/{map_id}/semantic-analysis/destinations/preview"


# ---------------------------------------------------------
# Helpers (local copies, matching the established per-file convention —
# see tests/test_semantic_destinations.py).
# ---------------------------------------------------------


def _create_map(client, token, title="Batch Placement Test Map", floor=None, building_id=None):
    payload = {"title": title, "floor": floor}
    if building_id:
        payload["building_id"] = building_id
    response = client.post("/api/maps", json=payload, headers=auth_headers(token))
    assert response.status_code == 201, response.text
    return response.json()


def _place(
    external_id,
    name_en,
    category="store",
    confidence=0.95,
    status="accepted",
    floor_external_id="floor-1",
    inside_place_external_id=None,
    selectable=None,
):
    item = {
        "place_external_id": external_id,
        "floor_external_id": floor_external_id,
        "names": {"en": name_en, "ar": None, "he": None, "original": name_en},
        "category": category,
        "confidence": confidence,
        "review": {"status": status},
    }
    if inside_place_external_id:
        item["inside_place_external_id"] = inside_place_external_id
    if selectable is not None:
        item["administrator_settings"] = {"selectable_destination": selectable}
    return item


async def _create_publication(map_id, places=None, facilities=None, floor_external_id="floor-1"):
    publication = SemanticMapPublication(
        analysis_id="batch-test-analysis",
        prompt_version="test-v1",
        prompt_sha256="0" * 64,
        reviewed_result={"places": places or [], "facilities": facilities or []},
        quickroute_links={"floor_links": [{"floor_external_id": floor_external_id, "map_id": map_id}]},
        map_id=map_id,
        is_active=True,
    )
    await publication.insert()
    return publication


def _apply(client, token, map_id, accepted, publication_id=None, all_or_nothing=False):
    response = client.post(
        DEST_APPLY_URL.format(map_id=map_id),
        json={
            "publication_id": publication_id,
            "accepted": accepted,
            "all_or_nothing": all_or_nothing,
        },
        headers=auth_headers(token),
    )
    assert response.status_code == 200, response.text
    return response.json()


# ===========================================================
# 1. A complete batch creates all approved Rooms and linked RoutePoints.
# ===========================================================
async def test_complete_batch_creates_all_rooms_and_route_points(client):
    token, _ = create_admin_and_get_token(client, role="global_manager", email="bp1@example.com")
    map_item = _create_map(client, token)
    await _create_publication(map_item["id"], places=[
        _place("bp1_p1", "Office 261"),
        _place("bp1_p2", "Office 262"),
        _place("bp1_p3", "Office 263"),
    ])

    result = _apply(
        client, token, map_item["id"],
        accepted=[
            {"semantic_item_id": "bp1_p1", "entity_kind": "place", "x": 10, "y": 10},
            {"semantic_item_id": "bp1_p2", "entity_kind": "place", "x": 20, "y": 20},
            {"semantic_item_id": "bp1_p3", "entity_kind": "place", "x": 30, "y": 30},
        ],
        all_or_nothing=True,
    )

    assert result["rooms_created"] == 3
    assert result["route_points_created"] == 3
    assert result["failed"] == 0
    assert result["item_errors"] == {}

    rooms = await Room.find({"map_id": map_item["id"]}).to_list()
    assert len(rooms) == 3
    points = await RoutePoint.find({"map_id": map_item["id"]}).to_list()
    assert len(points) == 3
    for room in rooms:
        assert room.route_point_id is not None


# ===========================================================
# 2. The Map's authoritative floor is used.
# ===========================================================
async def test_batch_uses_maps_authoritative_floor(client):
    token, _ = create_admin_and_get_token(client, role="global_manager", email="bp2@example.com")
    map_item = _create_map(client, token, floor=4)
    # This map has a real, non-None physical floor, so the floor-code
    # defense-in-depth check (_floor_code_mismatch) is active and requires
    # the publication's floor_external_id to be the authoritative
    # "floor_XXX" code derived from that floor — anything else (e.g. the
    # arbitrary "floor-1" placeholder the other fixtures use) would cause
    # apply() to reject the whole batch before ever reaching the
    # all_or_nothing validation this test is actually about.
    floor_code = compute_authoritative_floor_code(4)
    await _create_publication(
        map_item["id"],
        places=[_place("bp2_p1", "Office 401", floor_external_id=floor_code)],
        floor_external_id=floor_code,
    )

    result = _apply(
        client, token, map_item["id"],
        accepted=[{"semantic_item_id": "bp2_p1", "entity_kind": "place", "x": 5, "y": 5}],
        all_or_nothing=True,
    )
    assert result["rooms_created"] == 1

    room = await Room.get(PydanticObjectId(result["created_room_ids"][0]))
    point = await RoutePoint.get(PydanticObjectId(room.route_point_id))
    assert room.floor == 4
    assert point.floor == 4


# ===========================================================
# 3. The operation does not trust conflicting frontend map/floor values.
# ===========================================================
async def test_batch_ignores_conflicting_frontend_floor(client):
    token, _ = create_admin_and_get_token(client, role="global_manager", email="bp3@example.com")
    map_item = _create_map(client, token, floor=2)
    # Same reason as test_batch_uses_maps_authoritative_floor above: a
    # non-None map floor activates _floor_code_mismatch, so the
    # publication/item floor_external_id must be the real authoritative
    # code for floor 2, not the "floor-1" placeholder.
    floor_code = compute_authoritative_floor_code(2)
    await _create_publication(
        map_item["id"],
        places=[_place("bp3_p1", "Office 201", floor_external_id=floor_code)],
        floor_external_id=floor_code,
    )

    # The accepted-item payload schema (AcceptedDestinationItem) has no
    # floor field at all — there is nothing for the frontend to even
    # attempt to override with. The floor is ALWAYS derived server-side
    # from the re-fetched Map document, proven here by asserting the
    # created Room/RoutePoint floor matches the Map's floor regardless of
    # anything the request could have said.
    result = _apply(
        client, token, map_item["id"],
        accepted=[{
            "semantic_item_id": "bp3_p1",
            "entity_kind": "place",
            "x": 5,
            "y": 5,
            # Extra/unexpected fields a malicious or buggy frontend might
            # send are simply ignored by the Pydantic schema.
            "floor": 99,
            "map_id": "some-other-map-id",
        }],
        all_or_nothing=True,
    )
    assert result["rooms_created"] == 1
    room = await Room.get(PydanticObjectId(result["created_room_ids"][0]))
    assert room.floor == 2
    assert room.map_id == map_item["id"]


# ===========================================================
# 4. Invalid coordinates reject the batch before writes.
# ===========================================================
async def test_invalid_coordinates_reject_the_whole_batch_before_writes(client):
    token, _ = create_admin_and_get_token(client, role="global_manager", email="bp4@example.com")
    map_item = _create_map(client, token)

    # Give this map real, known bounds so an out-of-range coordinate can
    # be unambiguously detected (direct model manipulation — there is no
    # public API for setting source_width/height outside image upload,
    # matching how the rest of this test suite sets up map fixtures the
    # HTTP API itself doesn't expose a setter for).
    map_doc = await Map.get(PydanticObjectId(map_item["id"]))
    map_doc.source_width = 1000
    map_doc.source_height = 1000
    await map_doc.save()

    await _create_publication(map_item["id"], places=[
        _place("bp4_p1", "Office 261"),
        _place("bp4_p2", "Office 262"),
    ])

    result = _apply(
        client, token, map_item["id"],
        accepted=[
            {"semantic_item_id": "bp4_p1", "entity_kind": "place", "x": 10, "y": 10},
            # Wildly out of bounds for a 1000x1000 map.
            {"semantic_item_id": "bp4_p2", "entity_kind": "place", "x": 50000, "y": 50000},
        ],
        all_or_nothing=True,
    )

    assert result["rooms_created"] == 0
    assert result["failed"] == 1
    assert "bp4_p2" in result["item_errors"]
    assert "outside" in result["item_errors"]["bp4_p2"].lower()

    # Nothing was written — not even the VALID first item.
    rooms = await Room.find({"map_id": map_item["id"]}).to_list()
    assert rooms == []


async def test_missing_coordinates_reject_the_whole_batch_before_writes(client):
    token, _ = create_admin_and_get_token(client, role="global_manager", email="bp4b@example.com")
    map_item = _create_map(client, token)
    await _create_publication(map_item["id"], places=[_place("bp4b_p1", "Office 261")])

    result = _apply(
        client, token, map_item["id"],
        accepted=[{"semantic_item_id": "bp4b_p1", "entity_kind": "place"}],  # no x/y
        all_or_nothing=True,
    )

    assert result["rooms_created"] == 0
    assert result["failed"] == 1
    assert "bp4b_p1" in result["item_errors"]
    rooms = await Room.find({"map_id": map_item["id"]}).to_list()
    assert rooms == []


# ===========================================================
# 5. Duplicate submission is idempotent.
# ===========================================================
async def test_duplicate_batch_submission_is_idempotent(client):
    token, _ = create_admin_and_get_token(client, role="global_manager", email="bp5@example.com")
    map_item = _create_map(client, token)
    await _create_publication(map_item["id"], places=[
        _place("bp5_p1", "Office 261"),
        _place("bp5_p2", "Office 262"),
    ])

    accepted = [
        {"semantic_item_id": "bp5_p1", "entity_kind": "place", "x": 10, "y": 10},
        {"semantic_item_id": "bp5_p2", "entity_kind": "place", "x": 20, "y": 20},
    ]

    first = _apply(client, token, map_item["id"], accepted=accepted, all_or_nothing=True)
    assert first["rooms_created"] == 2

    second = _apply(client, token, map_item["id"], accepted=accepted, all_or_nothing=True)
    assert second["rooms_created"] == 0
    assert second["reused"] == 2
    assert second["failed"] == 0

    rooms = await Room.find({"map_id": map_item["id"]}).to_list()
    assert len(rooms) == 2  # never duplicated
    points = await RoutePoint.find({"map_id": map_item["id"]}).to_list()
    assert len(points) == 2


# ===========================================================
# 6. Existing Rooms/RoutePoints are reused safely.
# ===========================================================
async def test_existing_linked_point_is_reused_without_a_new_location(client):
    token, _ = create_admin_and_get_token(client, role="global_manager", email="bp6@example.com")
    map_item = _create_map(client, token)
    await _create_publication(map_item["id"], places=[_place("bp6_p1", "Office 261")])

    # First apply creates the Room + RoutePoint.
    first = _apply(
        client, token, map_item["id"],
        accepted=[{"semantic_item_id": "bp6_p1", "entity_kind": "place", "x": 15, "y": 15}],
        all_or_nothing=True,
    )
    assert first["rooms_created"] == 1
    original_room_id = first["created_room_ids"][0]
    original_point_id = first["created_route_point_ids"][0]

    # A batch save that includes this item again WITHOUT x/y (as the
    # frontend does for an existing-linked-point proposal — Section 8:
    # "do not require a new location unless the admin explicitly chooses
    # to replace it") must succeed by reusing it, not fail validation.
    second = _apply(
        client, token, map_item["id"],
        accepted=[{"semantic_item_id": "bp6_p1", "entity_kind": "place"}],
        all_or_nothing=True,
    )
    assert second["failed"] == 0
    assert second["reused"] == 1

    room = await Room.get(PydanticObjectId(original_room_id))
    assert room.route_point_id == original_point_id
    point = await RoutePoint.get(PydanticObjectId(original_point_id))
    assert point.x == 15
    assert point.y == 15  # never silently moved


# ===========================================================
# 7. Rejected destinations are not created.
# ===========================================================
async def test_rejected_destinations_are_never_sent_or_created(client):
    token, _ = create_admin_and_get_token(client, role="global_manager", email="bp7@example.com")
    map_item = _create_map(client, token)
    await _create_publication(map_item["id"], places=[
        _place("bp7_p1", "Office 261"),
        _place("bp7_p2", "Office 262"),
    ])

    # The frontend's buildBatchAcceptedPayload never includes a rejected
    # proposal in the request at all — simulated here by simply omitting
    # bp7_p2 from `accepted`.
    result = _apply(
        client, token, map_item["id"],
        accepted=[{"semantic_item_id": "bp7_p1", "entity_kind": "place", "x": 10, "y": 10}],
        all_or_nothing=True,
    )
    assert result["rooms_created"] == 1

    rooms = await Room.find({"map_id": map_item["id"]}).to_list()
    assert len(rooms) == 1
    assert rooms[0].semantic_entity_external_id == "bp7_p1"


# ===========================================================
# 8. No partial data remains after a failed batch.
# ===========================================================
async def test_failed_batch_leaves_no_partial_data(client):
    token, _ = create_admin_and_get_token(client, role="global_manager", email="bp8@example.com")
    map_item = _create_map(client, token)
    await _create_publication(map_item["id"], places=[
        _place("bp8_p1", "Office 261"),
        _place("bp8_p2", "Office 262"),
        _place("bp8_p3", "Office 263"),
    ])

    result = _apply(
        client, token, map_item["id"],
        accepted=[
            {"semantic_item_id": "bp8_p1", "entity_kind": "place", "x": 10, "y": 10},
            {"semantic_item_id": "bp8_p2", "entity_kind": "place", "x": 20, "y": 20},
            # This one is invalid (unknown semantic_item_id).
            {"semantic_item_id": "bp8_does_not_exist", "entity_kind": "place", "x": 30, "y": 30},
        ],
        all_or_nothing=True,
    )

    assert result["failed"] == 1
    assert "bp8_does_not_exist" in result["item_errors"]
    assert result["rooms_created"] == 0
    assert result["route_points_created"] == 0

    rooms = await Room.find({"map_id": map_item["id"]}).to_list()
    assert rooms == []
    points = await RoutePoint.find({"map_id": map_item["id"]}).to_list()
    assert points == []


# ===========================================================
# 9. Nested relationships remain explicit and validated.
# ===========================================================
async def test_nested_relationship_created_when_both_sides_are_in_the_same_batch(client):
    token, _ = create_admin_and_get_token(client, role="global_manager", email="bp9@example.com")
    map_item = _create_map(client, token)
    await _create_publication(map_item["id"], places=[
        _place("bp9_outer", "Food Court"),
        _place("bp9_inner", "Coffee Kiosk", inside_place_external_id="bp9_outer"),
    ])

    result = _apply(
        client, token, map_item["id"],
        accepted=[
            {
                "semantic_item_id": "bp9_outer",
                "entity_kind": "place",
                "x": 10,
                "y": 10,
                "allow_transit_through": True,
            },
            {
                "semantic_item_id": "bp9_inner",
                "entity_kind": "place",
                "x": 12,
                "y": 12,
                "parent_semantic_item_id": "bp9_outer",
            },
        ],
        all_or_nothing=True,
    )

    assert result["rooms_created"] == 2
    assert result["nested_relationships_created"] == 1

    inner_room = await Room.find_one({"semantic_entity_external_id": "bp9_inner"})
    outer_room = await Room.find_one({"semantic_entity_external_id": "bp9_outer"})
    assert inner_room.parent_room_id == str(outer_room.id)


async def test_nested_relationship_to_a_nonexistent_parent_rejects_the_whole_batch(client):
    token, _ = create_admin_and_get_token(client, role="global_manager", email="bp9b@example.com")
    map_item = _create_map(client, token)
    await _create_publication(map_item["id"], places=[
        _place("bp9b_inner", "Coffee Kiosk", inside_place_external_id="bp9b_ghost"),
    ])

    result = _apply(
        client, token, map_item["id"],
        accepted=[{
            "semantic_item_id": "bp9b_inner",
            "entity_kind": "place",
            "x": 12,
            "y": 12,
            "parent_semantic_item_id": "bp9b_ghost",
        }],
        all_or_nothing=True,
    )

    assert result["failed"] == 1
    assert "bp9b_inner" in result["item_errors"]
    rooms = await Room.find({"map_id": map_item["id"]}).to_list()
    assert rooms == []


# ===========================================================
# 10. No random room-to-room navigation edges are created.
# ===========================================================
async def test_batch_apply_never_creates_route_edges(client):
    token, _ = create_admin_and_get_token(client, role="global_manager", email="bp10@example.com")
    map_item = _create_map(client, token)
    await _create_publication(map_item["id"], places=[
        _place("bp10_p1", "Office 261"),
        _place("bp10_p2", "Office 262"),
    ])

    edges_before = await RouteEdge.find({"map_id": map_item["id"]}).to_list()
    assert edges_before == []

    _apply(
        client, token, map_item["id"],
        accepted=[
            {"semantic_item_id": "bp10_p1", "entity_kind": "place", "x": 10, "y": 10},
            {"semantic_item_id": "bp10_p2", "entity_kind": "place", "x": 20, "y": 20},
        ],
        all_or_nothing=True,
    )

    edges_after = await RouteEdge.find({"map_id": map_item["id"]}).to_list()
    assert edges_after == []  # apply never creates edges, batch or not


# ===========================================================
# 11. Existing navigation/Dijkstra behaviour is unaffected — a plain
#     single-map route between two ordinary RoutePoints still works
#     exactly as before, untouched by anything in this file.
# ===========================================================
async def test_existing_navigation_route_calculation_is_unaffected_by_batch_changes(client):
    token, _ = create_admin_and_get_token(client, role="global_manager", email="bp11@example.com")
    map_item = _create_map(client, token)

    point_a = client.post(
        "/api/route-points",
        json={"map_id": map_item["id"], "name": "Point A", "x": 0, "y": 0, "floor": 1, "point_type": "hallway"},
        headers=auth_headers(token),
    ).json()
    point_b = client.post(
        "/api/route-points",
        json={"map_id": map_item["id"], "name": "Point B", "x": 10, "y": 0, "floor": 1, "point_type": "hallway"},
        headers=auth_headers(token),
    ).json()
    client.post(
        "/api/route-edges",
        json={
            "map_id": map_item["id"],
            "from_point_id": point_a["id"],
            "to_point_id": point_b["id"],
            "edge_type": "walkway",
        },
        headers=auth_headers(token),
    )

    response = client.post(
        "/api/navigation/route",
        json={"map_id": map_item["id"], "start_point_id": point_a["id"], "end_point_id": point_b["id"]},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["path_point_ids"] == [point_a["id"], point_b["id"]]


# ===========================================================
# Backward compatibility: all_or_nothing defaults to False and preserves
# the exact pre-existing partial-tolerant behavior.
# ===========================================================
async def test_all_or_nothing_defaults_to_false_and_preserves_partial_tolerant_behavior(client):
    token, _ = create_admin_and_get_token(client, role="global_manager", email="bp12@example.com")
    map_item = _create_map(client, token)
    await _create_publication(map_item["id"], places=[_place("bp12_p1", "Office 261")])

    # Omitting all_or_nothing entirely (as every pre-existing caller of
    # this endpoint does) must behave exactly as before this feature.
    response = client.post(
        DEST_APPLY_URL.format(map_id=map_item["id"]),
        json={
            "publication_id": None,
            "accepted": [
                {"semantic_item_id": "bp12_p1", "entity_kind": "place", "x": 10, "y": 10},
                {"semantic_item_id": "bp12_does_not_exist", "entity_kind": "place", "x": 1, "y": 1},
            ],
        },
        headers=auth_headers(token),
    )
    assert response.status_code == 200, response.text
    result = response.json()

    # The valid item is still created even though the other one failed —
    # partial-tolerant, exactly like every existing test in
    # test_semantic_destinations.py expects.
    assert result["rooms_created"] == 1
    assert result["item_errors"] == {}
    rooms = await Room.find({"map_id": map_item["id"]}).to_list()
    assert len(rooms) == 1
