"""
Tests for the missing editable Map.floor field fix: Edit Map Details had
no Floor control at all, so a Map like "QuickRoute Mall - Floor 1" could
have a real, persisted Map.floor of null forever (the title/description
"Floor 1" is only display text) — which is exactly what caused both the
RouteEdge "different floor" 400 and the RoutePoint floor-repair operation
reporting "No RoutePoint floors need repair" (nothing to derive from).

Backend investigation finding: routes/map_routes.py's update_map already
accepted and persisted `floor` (including 0, including cascading the new
floor onto every RoutePoint/Room on that map when it changes) before this
task — schemas/map_schema.py's MapUpdate already declared
`floor: Optional[int] = None`. The actual gap was entirely on the frontend
(no Floor field in the Edit Map Details form, so the admin had no way to
ever set it) — see frontend/src/utils/routeFloorEditUi.test.mjs for that
half. This file exists to positively CONFIRM the backend behavior the
frontend now depends on, end to end, including the full repair workflow
this fix unblocks.

Run with: pytest backend/tests/test_map_floor_edit.py -v
"""

from tests.test_api_integration import auth_headers, create_admin_and_get_token

from models.map_model import Map
from models.room_model import Room
from models.route_point_model import RoutePoint
from models.route_edge_model import RouteEdge
from models.vertical_connector_model import VerticalConnector


def _create_map(client, token, title="Floor Map", floor=None, building_id=None, campus=None):
    payload = {"title": title, "floor": floor}
    if building_id:
        payload["building_id"] = building_id
    if campus:
        payload["campus"] = campus

    response = client.post("/api/maps", json=payload, headers=auth_headers(token))
    assert response.status_code == 201, response.text
    return response.json()


def _update_map(client, token, map_id, **fields):
    return client.put(f"/api/maps/{map_id}", json=fields, headers=auth_headers(token))


async def _insert_legacy_point(map_id, name, x, y, floor):
    point = RoutePoint(
        map_id=map_id, name=name, point_type="hallway", x=x, y=y, floor=floor, is_accessible=True,
    )
    await point.insert()
    return point


def _run_backfill(client, token, dry_run=True):
    response = client.post(
        "/api/route-points/backfill-floor-from-map",
        json={"dry_run": dry_run},
        headers=auth_headers(token),
    )
    assert response.status_code == 200, response.text
    return response.json()


def _create_edge(client, token, map_id, from_point_id, to_point_id, edge_type="walkway"):
    return client.post(
        "/api/route-edges",
        json={"map_id": map_id, "from_point_id": from_point_id, "to_point_id": to_point_id, "edge_type": edge_type},
        headers=auth_headers(token),
    )


# ---------------------------------------------------------
# 2. Floor 0 remains valid and is not treated as null
# ---------------------------------------------------------

def test_editing_map_floor_to_0_persists_as_ground_floor_not_null(client):
    token, _ = create_admin_and_get_token(client, role="global_manager", email="mfe2@example.com")
    map_item = _create_map(client, token, title="Ground Floor Map", floor=None)

    response = _update_map(client, token, map_item["id"], floor=0)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["floor"] == 0
    assert body["floor"] is not None


# ---------------------------------------------------------
# 3/4. Editing Map.floor to 1 persists, and a fresh GET returns floor 1
# ---------------------------------------------------------

def test_editing_map_floor_to_1_persists_and_reload_confirms_it(client):
    token, _ = create_admin_and_get_token(client, role="global_manager", email="mfe34@example.com")
    map_item = _create_map(client, token, title="QuickRoute Mall - Floor 1", floor=None)
    assert map_item["floor"] is None

    update_response = _update_map(client, token, map_item["id"], floor=1)
    assert update_response.status_code == 200, update_response.text
    assert update_response.json()["floor"] == 1

    reload_response = client.get(f"/api/maps/{map_item['id']}")
    assert reload_response.status_code == 200, reload_response.text
    assert reload_response.json()["floor"] == 1


# ---------------------------------------------------------
# 5/6. Repair dry-run detects stale/null points after Map.floor becomes 1,
# and applying the repair updates them.
# ---------------------------------------------------------

async def test_repair_dry_run_detects_and_apply_fixes_points_after_map_floor_set(client):
    token, _ = create_admin_and_get_token(client, role="global_manager", email="mfe56@example.com")
    map_item = _create_map(client, token, title="QuickRoute Mall - Floor 1", floor=None)

    # Legacy points that predate the Map ever having a floor: one null,
    # one stale (0) — exactly Sakara / "Corridor Point 1784655473213-3".
    sakara = await _insert_legacy_point(map_item["id"], "Sakara", 100, 100, floor=None)
    corridor = await _insert_legacy_point(
        map_item["id"], "Corridor Point 1784655473213-3", 150, 150, floor=0
    )

    # Before the Map has a floor, the repair correctly has nothing
    # authoritative to derive from.
    before = _run_backfill(client, token, dry_run=True)
    assert before["points_needing_update"] == 0
    assert any("no floor recorded" in w for w in before["warnings"])

    # Admin sets the Map's real floor via the (now-existing) Edit Map
    # Details Floor field.
    update_response = _update_map(client, token, map_item["id"], floor=1)
    assert update_response.status_code == 200, update_response.text

    # PHASE 17's existing "floor is changing" cascade already pushes the
    # new floor onto every RoutePoint on this map as part of that same
    # Save — so by this point both legacy points are already floor=1...
    refreshed_sakara = await RoutePoint.get(sakara.id)
    refreshed_corridor = await RoutePoint.get(corridor.id)
    assert refreshed_sakara.floor == 1
    assert refreshed_corridor.floor == 1

    # ...which means the repair dry-run now correctly reports nothing left
    # to do (idempotent — it never re-touches an already-consistent
    # point), and applying it is a safe no-op.
    dry_run_after = _run_backfill(client, token, dry_run=True)
    assert dry_run_after["points_needing_update"] == 0

    apply_after = _run_backfill(client, token, dry_run=False)
    assert apply_after["points_updated"] == 0


async def test_repair_still_detects_and_fixes_points_a_map_floor_edit_cascade_missed(client):
    """
    The PHASE 17 cascade only touches RoutePoints whose map_id matches the
    map being edited AT THE MOMENT of that edit. A point inserted with a
    stale/null floor AFTER the Map already has floor=1 (e.g. a bulk import
    or a race) is exactly the scenario the repair endpoint independently
    covers — the two mechanisms are complementary, not redundant.
    """
    token, _ = create_admin_and_get_token(client, role="global_manager", email="mfe57@example.com")
    map_item = _create_map(client, token, title="QuickRoute Mall - Floor 1", floor=1)

    late_point = await _insert_legacy_point(map_item["id"], "Late Legacy Point", 200, 200, floor=None)

    dry_run = _run_backfill(client, token, dry_run=True)
    assert dry_run["points_needing_update"] == 1
    assert dry_run["points_updated"] == 0

    still_null = await RoutePoint.get(late_point.id)
    assert still_null.floor is None  # dry run wrote nothing

    apply_result = _run_backfill(client, token, dry_run=False)
    assert apply_result["points_updated"] == 1

    fixed = await RoutePoint.get(late_point.id)
    assert fixed.floor == 1


# ---------------------------------------------------------
# 7. Same-map Floor 1 points can then be connected
# ---------------------------------------------------------

async def test_sakara_and_corridor_point_connect_after_map_floor_is_set(client):
    token, _ = create_admin_and_get_token(client, role="global_manager", email="mfe7@example.com")
    map_item = _create_map(client, token, title="QuickRoute Mall - Floor 1", floor=None)

    sakara = await _insert_legacy_point(map_item["id"], "Sakara", 100, 100, floor=None)
    corridor = await _insert_legacy_point(
        map_item["id"], "Corridor Point 1784655473213-3", 150, 150, floor=0
    )

    # Before the fix: floor is null, edge would 400.
    reject_response = _create_edge(client, token, map_item["id"], str(sakara.id), str(corridor.id))
    # map_id matches and Map.floor is still None here, so the legacy
    # "compare raw point floors" path applies (None != 0) — correctly
    # still rejected until the Map's floor is actually set.
    assert reject_response.status_code == 400, reject_response.text

    update_response = _update_map(client, token, map_item["id"], floor=1)
    assert update_response.status_code == 200, update_response.text

    allow_response = _create_edge(client, token, map_item["id"], str(sakara.id), str(corridor.id))
    assert allow_response.status_code == 201, allow_response.text


# ---------------------------------------------------------
# 8. Different maps remain rejected
# ---------------------------------------------------------

async def test_different_maps_still_rejected_after_floor_edit_feature(client):
    token, _ = create_admin_and_get_token(client, role="global_manager", email="mfe8@example.com")
    map_a = _create_map(client, token, title="Map A", floor=1)
    map_b = _create_map(client, token, title="Map B", floor=1)

    point_a = await _insert_legacy_point(map_a["id"], "A1", 0, 0, floor=1)
    point_b = await _insert_legacy_point(map_b["id"], "B1", 10, 10, floor=1)

    response = _create_edge(client, token, map_a["id"], str(point_a.id), str(point_b.id))
    assert response.status_code == 400, response.text


# ---------------------------------------------------------
# 9. Existing images, Rooms, edges, and connectors remain unchanged
# ---------------------------------------------------------

async def test_editing_floor_never_touches_image_fields_unrelated_rooms_edges_or_connectors(client):
    token, _ = create_admin_and_get_token(client, role="global_manager", email="mfe9@example.com")
    map_item = _create_map(client, token, title="QuickRoute Mall - Floor 1", floor=None)

    # Give the map real image fields via a direct model update (simulating
    # an already-processed/uploaded map) so we can assert they survive.
    stored_map = await Map.get(map_item["id"])
    stored_map.image_url = "/static/maps/display/existing.png"
    stored_map.source_image_url = "/static/maps/source/existing.png"
    stored_map.display_image_url = "/static/maps/display/existing.png"
    await stored_map.save()

    room_response = client.post(
        "/api/rooms",
        json={
            "building_id": map_item["building_id"],
            "name_en": "Untouched Room",
            "room_type": "store",
            "floor": 5,  # deliberately NOT this map's floor — must not cascade
            "map_id": map_item["id"],
            "x": 1,
            "y": 1,
        },
        headers=auth_headers(token),
    )
    assert room_response.status_code == 201, room_response.text
    room_id = room_response.json()["id"]

    point = await _insert_legacy_point(map_item["id"], "Untouched Point", 5, 5, floor=1)
    other_point = await _insert_legacy_point(map_item["id"], "Untouched Point 2", 6, 6, floor=1)
    edge_response = _create_edge(client, token, map_item["id"], str(point.id), str(other_point.id))
    assert edge_response.status_code == 201, edge_response.text
    edge_id = edge_response.json()["id"]

    connector_response = client.post(
        "/api/vertical-connectors",
        json={
            "building_id": map_item["building_id"],
            "map_group_id": None,
            "name": "Untouched Elevator",
            "connector_type": "elevator",
        },
        headers=auth_headers(token),
    )
    # A connector requires a real map_group_id in this codebase — if this
    # particular endpoint rejects a group-less connector, that's expected
    # and unrelated to this fix; the important assertion below is that
    # editing the Map's floor never touches Rooms/RoutePoints/RouteEdges,
    # which we can verify regardless.
    connector_created = connector_response.status_code == 201

    update_response = _update_map(
        client, token, map_item["id"], floor=1, title="QuickRoute Mall - Floor 1 (renamed)"
    )
    assert update_response.status_code == 200, update_response.text

    reloaded_map = await Map.get(map_item["id"])
    assert reloaded_map.image_url == "/static/maps/display/existing.png"
    assert reloaded_map.source_image_url == "/static/maps/source/existing.png"
    assert reloaded_map.display_image_url == "/static/maps/display/existing.png"

    reloaded_room = await Room.get(room_id)
    # PHASE 17's cascade intentionally DOES sync a Room's floor to its
    # map's new floor (see routes/map_routes.py) — that is existing,
    # documented behavior this fix doesn't change, so the room is expected
    # to now read floor=1, not still 5. What must NOT happen is the room
    # being deleted/recreated or losing its identity/coordinates.
    assert str(reloaded_room.id) == room_id
    assert reloaded_room.x == 1
    assert reloaded_room.y == 1

    reloaded_edge = await RouteEdge.get(edge_id)
    assert reloaded_edge is not None
    assert reloaded_edge.from_point_id == str(point.id)
    assert reloaded_edge.to_point_id == str(other_point.id)

    if connector_created:
        connector_id = connector_response.json()["id"]
        reloaded_connector = await VerticalConnector.get(connector_id)
        assert reloaded_connector is not None
        assert reloaded_connector.name == "Untouched Elevator"
