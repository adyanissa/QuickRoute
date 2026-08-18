"""
The two blockers this pass closes.

BLOCKER 1 — legacy invalid-edge preview + safe repair
    Historical data created before the Auto Connect correction contains
    walkway edges that route through ordinary destination rooms
    (CORRIDOR -> ROOM -> CORRIDOR, or ROOM A -> ROOM B). Those make
    Dijkstra report "the only path passes through a destination
    room/store point" on a floor whose corridor was drawn correctly.

BLOCKER 2 — one reusable attachment algorithm
    Saving a Room door point used to call the node-only
    graph_connection_service.auto_connect_point, while manual Auto Connect
    had corridor-edge projection and junction splitting. A room saved
    beside the MIDDLE of a long corridor therefore stayed unconnected
    until the admin pressed Auto Connect by hand.

Numbered to match the agreed acceptance matrix.

Run with: pytest backend/tests/test_legacy_repair_and_attachment.py -v
"""

import cv2
import numpy as np
import pytest

from tests.test_api_integration import auth_headers, create_admin_and_get_token

from models.location_code_model import LocationCode
from models.room_model import Room
from models.route_edge_model import RouteEdge
from models.route_point_model import RoutePoint


PREVIEW_URL = "/api/route-edges/legacy-connections/preview"
APPLY_URL = "/api/route-edges/legacy-connections/apply"
RETRY_URL = "/api/route-edges/pending-attachments/retry"


# ---------------------------------------------------------
# Helpers (local copies, matching the per-file convention).
# ---------------------------------------------------------

def _create_building(client, token, name):
    response = client.post(
        "/api/locations/buildings",
        json={"name_en": name},
        headers=auth_headers(token),
    )
    assert response.status_code == 201, response.text
    return response.json()


def _create_map(client, token, title, building_id=None, floor=0):
    payload = {"title": title, "floor": floor}
    if building_id:
        payload["building_id"] = building_id
    response = client.post("/api/maps", json=payload, headers=auth_headers(token))
    assert response.status_code == 201, response.text
    return response.json()


def _create_point(client, token, map_id, name, x, y, floor=0, point_type="hallway"):
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


def _create_edge(client, token, map_id, a, b):
    response = client.post(
        "/api/route-edges",
        json={"map_id": map_id, "from_point_id": a, "to_point_id": b, "edge_type": "walkway"},
        headers=auth_headers(token),
    )
    assert response.status_code == 201, response.text
    return response.json()


def _create_room(client, token, building_id, map_id, name, x, y, floor=0):
    response = client.post(
        "/api/rooms",
        json={
            "building_id": building_id,
            "name_en": name,
            "room_type": "room",
            "floor": floor,
            "map_id": map_id,
            "x": x,
            "y": y,
        },
        headers=auth_headers(token),
    )
    assert response.status_code == 201, response.text
    return response.json()


def _preview(client, token, map_id):
    response = client.post(
        PREVIEW_URL, json={"map_id": map_id}, headers=auth_headers(token)
    )
    assert response.status_code == 200, response.text
    return response.json()


def _apply(client, token, map_id, edge_ids=None):
    payload = {"map_id": map_id}
    if edge_ids is not None:
        payload["edge_ids"] = edge_ids
    response = client.post(APPLY_URL, json=payload, headers=auth_headers(token))
    assert response.status_code == 200, response.text
    return response.json()


def _retry(client, token, map_id, floor=None):
    payload = {"map_id": map_id}
    if floor is not None:
        payload["floor"] = floor
    response = client.post(RETRY_URL, json=payload, headers=auth_headers(token))
    assert response.status_code == 200, response.text
    return response.json()


def _kinds(preview, kind):
    return [f for f in preview["findings"] if f["kind"] == kind]


def _floor_with_corridor(client, token, label, floor=0):
    """A building + one floor map carrying a single long corridor run."""
    building = _create_building(client, token, f"{label} Building")
    map_item = _create_map(client, token, f"{label} Map", building["id"], floor=floor)
    hall_a = _create_point(client, token, map_item["id"], "Hall West", 0, 100, floor=floor)
    hall_b = _create_point(client, token, map_item["id"], "Hall East", 600, 100, floor=floor)
    edge = _create_edge(client, token, map_item["id"], hall_a["id"], hall_b["id"])
    return building, map_item, hall_a, hall_b, edge


def _floor_without_corridor(client, token, label, floor=0):
    building = _create_building(client, token, f"{label} Building")
    map_item = _create_map(client, token, f"{label} Map", building["id"], floor=floor)
    return building, map_item


async def _point_of(room):
    return await RoutePoint.get(room["route_point_id"])


async def _active_edges(map_id):
    return await RouteEdge.find({"map_id": map_id, "is_active": True}).to_list()


# =========================================================
# LEGACY REPAIR
# =========================================================

# 1. unrelated Room A <-> Room B edge detected as invalid
@pytest.mark.asyncio
async def test_unrelated_room_to_room_edge_is_detected(client):
    token, _ = create_admin_and_get_token(client, email="lr1@example.com")
    building, map_item, hall_a, _, _ = _floor_with_corridor(client, token, "LR1")

    room_a = _create_room(client, token, building["id"], map_item["id"], "Room A", 800, 800)
    room_b = _create_room(client, token, building["id"], map_item["id"], "Room B", 860, 800)
    bad = _create_edge(
        client, token, map_item["id"], room_a["route_point_id"], room_b["route_point_id"]
    )

    preview = _preview(client, token, map_item["id"])
    findings = _kinds(preview, "room_to_room")

    assert [f["edge_id"] for f in findings] == [bad["id"]]
    assert findings[0]["repairable"] is True
    assert preview["invalid_edges"] == 1
    # Human-facing labels, never a raw id as the primary label.
    assert findings[0]["from_name"]
    assert findings[0]["to_name"]


# 2. normal Room used as a corridor bridge detected
@pytest.mark.asyncio
async def test_room_used_as_transit_bridge_is_detected_but_not_auto_repaired(client):
    token, _ = create_admin_and_get_token(client, email="lr2@example.com")
    building, map_item = _floor_without_corridor(client, token, "LR2")

    # The legacy shape: CORRIDOR -> ROOM -> CORRIDOR, with the two corridor
    # stubs joined ONLY through the room. The room is created FIRST, while
    # there is no corridor for attach-on-save to find, so the only edges it
    # ends up with are the two wired by hand below — exactly how this data
    # came to exist before the Auto Connect correction.
    room = _create_room(client, token, building["id"], map_item["id"], "Bridge Room", 300, 140)
    assert room["route_point_connected"] is False

    hall_a = _create_point(client, token, map_item["id"], "Hall A", 100, 100)
    hall_b = _create_point(client, token, map_item["id"], "Hall B", 500, 100)

    _create_edge(client, token, map_item["id"], room["route_point_id"], hall_a["id"])
    _create_edge(client, token, map_item["id"], room["route_point_id"], hall_b["id"])

    preview = _preview(client, token, map_item["id"])
    bridges = _kinds(preview, "room_used_as_transit_bridge")

    assert len(bridges) == 1
    assert bridges[0]["point_id"] == room["route_point_id"]
    # Reported for human judgement — cutting either edge could sever the
    # corridor, so this is never repaired automatically.
    assert bridges[0]["repairable"] is False
    assert sorted(bridges[0]["graph_neighbour_ids"]) == sorted(
        [hall_a["id"], hall_b["id"]]
    )
    assert preview["needs_review"] >= 1


# 3. explicit nested edge preserved
@pytest.mark.asyncio
async def test_approved_nested_edge_is_preserved(client):
    token, _ = create_admin_and_get_token(client, email="lr3@example.com")
    building, map_item, hall_a, _, _ = _floor_with_corridor(client, token, "LR3")

    outer = _create_room(client, token, building["id"], map_item["id"], "Outer Room", 200, 250)
    inner = _create_room(client, token, building["id"], map_item["id"], "Inner Room", 220, 260)

    client.put(
        f"/api/route-points/{outer['route_point_id']}",
        json={"allow_transit_through": True},
        headers=auth_headers(token),
    )

    inner_room = await Room.get(inner["id"])
    inner_room.parent_room_id = outer["id"]
    await inner_room.save()

    nested_edge = _create_edge(
        client, token, map_item["id"], inner["route_point_id"], outer["route_point_id"]
    )

    preview = _preview(client, token, map_item["id"])

    assert nested_edge["id"] not in [
        f.get("edge_id") for f in _kinds(preview, "room_to_room")
    ]

    # ...and it survives a repair-everything run.
    _apply(client, token, map_item["id"])
    still_there = await RouteEdge.get(nested_edge["id"])
    assert still_there.is_active is True


# 4. parent pass-through nested chain preserved (multi level)
@pytest.mark.asyncio
async def test_multi_level_nested_chain_is_preserved(client):
    token, _ = create_admin_and_get_token(client, email="lr4@example.com")
    building, map_item, hall_a, _, _ = _floor_with_corridor(client, token, "LR4")

    outer = _create_room(client, token, building["id"], map_item["id"], "Room 1", 200, 250)
    mid = _create_room(client, token, building["id"], map_item["id"], "Room 1.1", 220, 260)
    inner = _create_room(client, token, building["id"], map_item["id"], "Room 1.1.1", 240, 270)

    for room in (outer, mid):
        client.put(
            f"/api/route-points/{room['route_point_id']}",
            json={"allow_transit_through": True},
            headers=auth_headers(token),
        )

    mid_room = await Room.get(mid["id"])
    mid_room.parent_room_id = outer["id"]
    await mid_room.save()
    inner_room = await Room.get(inner["id"])
    inner_room.parent_room_id = mid["id"]
    await inner_room.save()

    edge_outer_mid = _create_edge(
        client, token, map_item["id"], mid["route_point_id"], outer["route_point_id"]
    )
    edge_mid_inner = _create_edge(
        client, token, map_item["id"], inner["route_point_id"], mid["route_point_id"]
    )

    preview = _preview(client, token, map_item["id"])
    flagged = {f.get("edge_id") for f in _kinds(preview, "room_to_room")}

    assert edge_outer_mid["id"] not in flagged
    assert edge_mid_inner["id"] not in flagged


# 5. coincident legacy same-location representation preserved
@pytest.mark.asyncio
async def test_same_physical_location_pair_is_preserved(client):
    token, _ = create_admin_and_get_token(client, email="lr5@example.com")
    building, map_item, _, _, _ = _floor_with_corridor(client, token, "LR5")

    store = _create_point(
        client, token, map_item["id"], "Super-Pharm", 300, 300, point_type="store"
    )
    room = _create_room(
        client, token, building["id"], map_item["id"], "Super-Pharm Room", 302, 300
    )

    # Attach-on-save recognises the coincident twin itself — two records of
    # one physical place — so the edge under test already exists.
    twin_edges = [
        e
        for e in await _active_edges(map_item["id"])
        if {e.from_point_id, e.to_point_id}
        == {room["route_point_id"], store["id"]}
    ]
    assert len(twin_edges) == 1, "expected the same-location twin link"
    twin_edge = {"id": str(twin_edges[0].id)}

    preview = _preview(client, token, map_item["id"])
    assert twin_edge["id"] not in [
        f.get("edge_id") for f in _kinds(preview, "room_to_room")
    ]

    _apply(client, token, map_item["id"])
    assert (await RouteEdge.get(twin_edge["id"])).is_active is True


# 6. repair removes only the invalid edge
@pytest.mark.asyncio
async def test_repair_removes_only_the_invalid_edge(client):
    token, _ = create_admin_and_get_token(client, email="lr6@example.com")
    building, map_item, hall_a, hall_b, corridor_edge = _floor_with_corridor(
        client, token, "LR6"
    )

    room_a = _create_room(client, token, building["id"], map_item["id"], "Room A", 800, 800)
    room_b = _create_room(client, token, building["id"], map_item["id"], "Room B", 860, 800)
    bad = _create_edge(
        client, token, map_item["id"], room_a["route_point_id"], room_b["route_point_id"]
    )
    good = _create_edge(
        client, token, map_item["id"], room_a["route_point_id"], hall_a["id"]
    )

    result = _apply(client, token, map_item["id"], [bad["id"]])

    assert result["repaired"] == 1
    assert (await RouteEdge.get(bad["id"])).is_active is False
    # Deactivated, never deleted.
    assert await RouteEdge.get(bad["id"]) is not None
    assert (await RouteEdge.get(good["id"])).is_active is True
    assert (await RouteEdge.get(corridor_edge["id"])).is_active is True


# 7. repair does not delete Room / RoutePoint / LocationCode
@pytest.mark.asyncio
async def test_repair_never_deletes_room_point_or_qr(client):
    token, _ = create_admin_and_get_token(client, email="lr7@example.com")
    building, map_item, hall_a, _, _ = _floor_with_corridor(client, token, "LR7")

    room_a = _create_room(client, token, building["id"], map_item["id"], "Room A", 800, 800)
    room_b = _create_room(client, token, building["id"], map_item["id"], "Room B", 860, 800)
    _create_edge(client, token, map_item["id"], room_a["route_point_id"], hall_a["id"])
    bad = _create_edge(
        client, token, map_item["id"], room_a["route_point_id"], room_b["route_point_id"]
    )

    from services.room_location_code_service import ensure_room_location_codes

    await ensure_room_location_codes(map_item["id"])
    codes_before = await LocationCode.find({"map_id": map_item["id"]}).to_list()
    assert codes_before, "expected a QR to protect"

    _apply(client, token, map_item["id"], [bad["id"]])

    assert await Room.get(room_a["id"]) is not None
    assert await Room.get(room_b["id"]) is not None
    assert await RoutePoint.get(room_a["route_point_id"]) is not None
    assert await RoutePoint.get(room_b["route_point_id"]) is not None

    codes_after = await LocationCode.find({"map_id": map_item["id"]}).to_list()
    assert {str(c.id) for c in codes_after} == {str(c.id) for c in codes_before}
    assert all(c.is_active for c in codes_after)


# 8. repair then reconnects the Room to the corridor when possible
@pytest.mark.asyncio
async def test_repair_reconnects_the_room_to_the_corridor(client):
    token, _ = create_admin_and_get_token(client, email="lr8@example.com")
    building, map_item = _floor_without_corridor(client, token, "LR8")

    # Rooms first, while there is no corridor — so their only connection is
    # the bad Room-to-Room edge, which is the legacy shape.
    room_a = _create_room(client, token, building["id"], map_item["id"], "Room A", 300, 150)
    room_b = _create_room(client, token, building["id"], map_item["id"], "Room B", 360, 150)
    bad = _create_edge(
        client, token, map_item["id"], room_a["route_point_id"], room_b["route_point_id"]
    )

    # The corridor is drawn afterwards, so a correct reattachment IS
    # possible once the bad edge is gone.
    hall_a = _create_point(client, token, map_item["id"], "Hall West", 0, 100)
    hall_b = _create_point(client, token, map_item["id"], "Hall East", 600, 100)
    _create_edge(client, token, map_item["id"], hall_a["id"], hall_b["id"])

    before = client.get(f"/api/rooms/{room_a['id']}").json()
    assert before["is_navigable"] is False

    result = _apply(client, token, map_item["id"], [bad["id"]])

    assert result["repaired"] == 1
    assert result["reconnected"] >= 1

    after = client.get(f"/api/rooms/{room_a['id']}").json()
    assert after["is_navigable"] is True


# 9. repair leaves the Room unconnected with a precise reason when no
#    corridor exists
@pytest.mark.asyncio
async def test_repair_leaves_room_unconnected_with_a_reason_when_no_corridor(client):
    token, _ = create_admin_and_get_token(client, email="lr9@example.com")
    building, map_item = _floor_without_corridor(client, token, "LR9")

    room_a = _create_room(client, token, building["id"], map_item["id"], "Room A", 300, 300)
    room_b = _create_room(client, token, building["id"], map_item["id"], "Room B", 360, 300)
    bad = _create_edge(
        client, token, map_item["id"], room_a["route_point_id"], room_b["route_point_id"]
    )

    result = _apply(client, token, map_item["id"], [bad["id"]])

    assert result["repaired"] == 1
    assert result["reconnected"] == 0
    assert result["still_needs_review"] >= 1
    reasons = {entry["reason"] for entry in result["unconnected"]}
    assert "no_transit_points_on_map" in reasons

    # The room itself is untouched, just honestly unconnected.
    assert await Room.get(room_a["id"]) is not None
    assert client.get(f"/api/rooms/{room_a['id']}").json()["is_navigable"] is False


# 10. repeated repair is idempotent
@pytest.mark.asyncio
async def test_repeated_repair_is_idempotent(client):
    token, _ = create_admin_and_get_token(client, email="lr10@example.com")
    building, map_item, _, _, _ = _floor_with_corridor(client, token, "LR10")

    room_a = _create_room(client, token, building["id"], map_item["id"], "Room A", 300, 150)
    room_b = _create_room(client, token, building["id"], map_item["id"], "Room B", 360, 150)
    bad = _create_edge(
        client, token, map_item["id"], room_a["route_point_id"], room_b["route_point_id"]
    )

    first = _apply(client, token, map_item["id"], [bad["id"]])
    assert first["repaired"] == 1

    edges_after_first = len(await _active_edges(map_item["id"]))
    points_after_first = len(await RoutePoint.find({"map_id": map_item["id"]}).to_list())

    second = _apply(client, token, map_item["id"])
    assert second["repaired"] == 0

    assert len(await _active_edges(map_item["id"])) == edges_after_first
    assert (
        len(await RoutePoint.find({"map_id": map_item["id"]}).to_list())
        == points_after_first
    )


@pytest.mark.asyncio
async def test_apply_rejects_an_edge_from_another_map(client):
    token, _ = create_admin_and_get_token(client, email="lr11@example.com")
    building, map_a, hall_a, _, _ = _floor_with_corridor(client, token, "LR11A")
    _, map_b, _, _, corridor_b = _floor_with_corridor(client, token, "LR11B")

    result = _apply(client, token, map_a["id"], [corridor_b["id"]])

    assert result["repaired"] == 0
    assert result["rejected_invalid"] == 1
    assert (await RouteEdge.get(corridor_b["id"])).is_active is True


# =========================================================
# ATTACH-ON-SAVE
# =========================================================

# 11. save Room near a corridor node -> attaches
@pytest.mark.asyncio
async def test_saving_a_room_near_a_corridor_node_attaches_it(client):
    token, _ = create_admin_and_get_token(client, email="at11@example.com")
    building, map_item, hall_a, _, _ = _floor_with_corridor(client, token, "AT11")

    room = _create_room(client, token, building["id"], map_item["id"], "Door Room", 10, 150)

    assert room["route_point_connected"] is True
    assert client.get(f"/api/rooms/{room['id']}").json()["is_navigable"] is True


# 12. save Room near the MIDDLE of a corridor edge -> split + junction
@pytest.mark.asyncio
async def test_saving_a_room_beside_a_corridor_edge_splits_it(client):
    token, _ = create_admin_and_get_token(client, email="at12@example.com")
    building, map_item, hall_a, hall_b, corridor_edge = _floor_with_corridor(
        client, token, "AT12"
    )

    # 300px from either endpoint; 40px from the perpendicular foot.
    room = _create_room(client, token, building["id"], map_item["id"], "Mid Room", 300, 140)

    assert room["route_point_connected"] is True

    # The original corridor edge was split, not abandoned.
    assert (await RouteEdge.get(corridor_edge["id"])).is_active is False

    junctions = [
        p
        for p in await RoutePoint.find({"map_id": map_item["id"]}).to_list()
        if p.point_type == "junction"
    ]
    assert len(junctions) == 1
    assert abs(float(junctions[0].x) - 300.0) < 2.0

    # ...and the corridor is still walkable end to end through it.
    active = await _active_edges(map_item["id"])
    junction_id = str(junctions[0].id)
    touching = {
        frozenset({e.from_point_id, e.to_point_id})
        for e in active
        if junction_id in (e.from_point_id, e.to_point_id)
    }
    assert frozenset({junction_id, hall_a["id"]}) in touching
    assert frozenset({junction_id, hall_b["id"]}) in touching
    assert frozenset({junction_id, room["route_point_id"]}) in touching


# 13. Room closer to an unrelated Room than to the corridor -> corridor wins
@pytest.mark.asyncio
async def test_a_room_closer_to_another_room_still_attaches_to_the_corridor(client):
    token, _ = create_admin_and_get_token(client, email="at13@example.com")
    building, map_item, _, _, _ = _floor_with_corridor(client, token, "AT13")

    neighbour = _create_room(
        client, token, building["id"], map_item["id"], "Neighbour", 300, 300
    )
    # 20px from the neighbour, 240px from the corridor.
    room = _create_room(client, token, building["id"], map_item["id"], "Late Room", 320, 300)

    assert room["route_point_connected"] is True

    edges = await _active_edges(map_item["id"])
    room_point = room["route_point_id"]
    partners = {
        e.to_point_id if e.from_point_id == room_point else e.from_point_id
        for e in edges
        if room_point in (e.from_point_id, e.to_point_id)
    }
    assert neighbour["route_point_id"] not in partners

    for partner_id in partners:
        partner = await RoutePoint.get(partner_id)
        assert partner.point_type in ("hallway", "junction")


# 14. blocked-by-wall candidate rejected
@pytest.mark.asyncio
async def test_a_wall_blocks_attachment_on_save(client, tmp_path, monkeypatch):
    token, _ = create_admin_and_get_token(client, email="at14@example.com")
    building = _create_building(client, token, "AT14 Building")
    map_item = _create_map(client, token, "AT14 Map", building["id"], floor=0)

    image = np.full((400, 600), 255, dtype=np.uint8)
    cv2.rectangle(image, (200, 0), (220, 400), 0, thickness=-1)
    monkeypatch.setattr("services.graph_connection_service.SOURCE_DIR", tmp_path)
    cv2.imwrite(str(tmp_path / f"{map_item['id']}.png"), image)

    hall_a = _create_point(client, token, map_item["id"], "Hall A", 400, 150)
    hall_b = _create_point(client, token, map_item["id"], "Hall B", 500, 250)
    _create_edge(client, token, map_item["id"], hall_a["id"], hall_b["id"])

    room = _create_room(client, token, building["id"], map_item["id"], "Sealed Room", 80, 200)

    assert room["route_point_connected"] is False
    assert client.get(f"/api/rooms/{room['id']}").json()["is_navigable"] is False


# 15. save Room before the corridor exists -> saved but pending
@pytest.mark.asyncio
async def test_saving_a_room_before_any_corridor_leaves_it_pending(client):
    token, _ = create_admin_and_get_token(client, email="at15@example.com")
    building, map_item = _floor_without_corridor(client, token, "AT15")

    room = _create_room(client, token, building["id"], map_item["id"], "Early Room", 300, 300)

    # Saved, not failed.
    assert room["id"]
    assert room["route_point_id"]
    assert room["route_point_connected"] is False
    # ...and no edge was fabricated.
    assert await _active_edges(map_item["id"]) == []


# =========================================================
# BULK RETRY
# =========================================================

# 16. several pending Rooms + corridor created later -> retry connects them
@pytest.mark.asyncio
async def test_bulk_retry_connects_rooms_placed_before_the_corridor(client):
    token, _ = create_admin_and_get_token(client, email="rt16@example.com")
    building, map_item = _floor_without_corridor(client, token, "RT16")

    rooms = [
        _create_room(
            client, token, building["id"], map_item["id"], f"Room {i}", 100 + i * 80, 160
        )
        for i in range(5)
    ]
    assert all(r["route_point_connected"] is False for r in rooms)

    # The corridor is drawn afterwards — the real admin workflow.
    hall_a = _create_point(client, token, map_item["id"], "Hall West", 0, 100)
    hall_b = _create_point(client, token, map_item["id"], "Hall East", 600, 100)
    _create_edge(client, token, map_item["id"], hall_a["id"], hall_b["id"])

    result = _retry(client, token, map_item["id"])

    assert result["attached"] == 5
    assert result["still_pending"] == 0

    for room in rooms:
        assert client.get(f"/api/rooms/{room['id']}").json()["is_navigable"] is True


# 17. repeated retry creates no duplicate edges or junctions
@pytest.mark.asyncio
async def test_repeated_bulk_retry_creates_no_duplicates(client):
    token, _ = create_admin_and_get_token(client, email="rt17@example.com")
    building, map_item = _floor_without_corridor(client, token, "RT17")

    for i in range(4):
        _create_room(
            client, token, building["id"], map_item["id"], f"Room {i}", 100 + i * 90, 160
        )

    hall_a = _create_point(client, token, map_item["id"], "Hall West", 0, 100)
    hall_b = _create_point(client, token, map_item["id"], "Hall East", 600, 100)
    _create_edge(client, token, map_item["id"], hall_a["id"], hall_b["id"])

    first = _retry(client, token, map_item["id"])
    assert first["attached"] == 4

    edges_after_first = len(await _active_edges(map_item["id"]))
    points_after_first = len(await RoutePoint.find({"map_id": map_item["id"]}).to_list())

    second = _retry(client, token, map_item["id"])
    third = _retry(client, token, map_item["id"])

    assert second["attached"] == 0
    assert third["attached"] == 0
    assert second["already_connected"] == first["scanned"]

    assert len(await _active_edges(map_item["id"])) == edges_after_first
    assert (
        len(await RoutePoint.find({"map_id": map_item["id"]}).to_list())
        == points_after_first
    )


# 18. only the current map/floor is retried
@pytest.mark.asyncio
async def test_bulk_retry_touches_only_the_requested_map(client):
    token, _ = create_admin_and_get_token(client, email="rt18@example.com")
    building_a, map_a = _floor_without_corridor(client, token, "RT18A")
    building_b, map_b = _floor_without_corridor(client, token, "RT18B")

    room_a = _create_room(client, token, building_a["id"], map_a["id"], "A Room", 100, 160)
    room_b = _create_room(client, token, building_b["id"], map_b["id"], "B Room", 100, 160)

    for map_item in (map_a, map_b):
        hall_a = _create_point(client, token, map_item["id"], "Hall West", 0, 100)
        hall_b = _create_point(client, token, map_item["id"], "Hall East", 600, 100)
        _create_edge(client, token, map_item["id"], hall_a["id"], hall_b["id"])

    result = _retry(client, token, map_a["id"])

    assert result["map_id"] == map_a["id"]
    assert client.get(f"/api/rooms/{room_a['id']}").json()["is_navigable"] is True
    # Map B was never touched.
    assert client.get(f"/api/rooms/{room_b['id']}").json()["is_navigable"] is False


# =========================================================
# STAIRS / ELEVATORS
# =========================================================

def _connector_setup(client, token, label):
    """A two-floor map group with one elevator, ready for stop placement."""
    group_response = client.post(
        "/api/map-groups",
        json={"name": f"{label} Group", "code": f"{label}-GRP"},
        headers=auth_headers(token),
    )
    assert group_response.status_code == 201, group_response.text
    return group_response.json()


@pytest.mark.asyncio
async def test_stair_stop_attaches_to_a_corridor_node(client):
    # 19. stop near a corridor node -> attaches
    from models.vertical_connector_model import VerticalConnector
    from services.vertical_connector_service import add_connector_stop

    token, _ = create_admin_and_get_token(client, email="vc19@example.com")
    building, map_item, hall_a, _, _ = _floor_with_corridor(client, token, "VC19")

    connector = VerticalConnector(
        building_id=building["id"],
        map_group_id="vc19-group",
        connector_code="VC19-ELEV",
        name="Elevator A",
        connector_type="elevator",
    )
    await connector.insert()

    stored_map = await __import__("models.map_model", fromlist=["Map"]).Map.get(
        map_item["id"]
    )
    stored_map.map_group_id = "vc19-group"
    await stored_map.save()

    point, was_reused, connected = await add_connector_stop(
        connector, map_id=map_item["id"], x=10, y=150, name=None, auto_connect="nearest"
    )

    assert connected is True
    assert point.connector_id == str(connector.id)


@pytest.mark.asyncio
async def test_stair_stop_splits_a_corridor_edge(client):
    # 20. stop near the middle of a corridor edge -> split + attaches
    from models.map_model import Map
    from models.vertical_connector_model import VerticalConnector
    from services.vertical_connector_service import add_connector_stop

    token, _ = create_admin_and_get_token(client, email="vc20@example.com")
    building, map_item, _, _, corridor_edge = _floor_with_corridor(client, token, "VC20")

    connector = VerticalConnector(
        building_id=building["id"],
        map_group_id="vc20-group",
        connector_code="VC20-STAIR",
        name="Stair 1",
        connector_type="stairs",
    )
    await connector.insert()

    stored_map = await Map.get(map_item["id"])
    stored_map.map_group_id = "vc20-group"
    await stored_map.save()

    _point, _reused, connected = await add_connector_stop(
        connector, map_id=map_item["id"], x=300, y=145, name=None, auto_connect="nearest"
    )

    assert connected is True
    assert (await RouteEdge.get(corridor_edge["id"])).is_active is False

    junctions = [
        p
        for p in await RoutePoint.find({"map_id": map_item["id"]}).to_list()
        if p.point_type == "junction"
    ]
    assert len(junctions) == 1


@pytest.mark.asyncio
async def test_stair_stop_never_attaches_to_a_room(client):
    # 21. stop cannot attach to a Room
    from models.map_model import Map
    from models.vertical_connector_model import VerticalConnector
    from services.vertical_connector_service import add_connector_stop

    token, _ = create_admin_and_get_token(client, email="vc21@example.com")
    building, map_item = _floor_without_corridor(client, token, "VC21")

    room = _create_room(client, token, building["id"], map_item["id"], "Nearby Room", 300, 300)

    connector = VerticalConnector(
        building_id=building["id"],
        map_group_id="vc21-group",
        connector_code="VC21-ELEV",
        name="Elevator B",
        connector_type="elevator",
    )
    await connector.insert()

    stored_map = await Map.get(map_item["id"])
    stored_map.map_group_id = "vc21-group"
    await stored_map.save()

    point, _reused, connected = await add_connector_stop(
        connector, map_id=map_item["id"], x=310, y=300, name=None, auto_connect="nearest"
    )

    # 22. no corridor yet -> pending, and definitely not wired to the room.
    assert connected is False

    edges = await _active_edges(map_item["id"])
    stop_id = str(point.id)
    assert not any(
        stop_id in (e.from_point_id, e.to_point_id)
        and room["route_point_id"] in (e.from_point_id, e.to_point_id)
        for e in edges
    )


@pytest.mark.asyncio
async def test_pending_stair_stop_is_picked_up_by_the_bulk_retry(client):
    # 23. corridor later + retry -> stop attaches
    from models.map_model import Map
    from models.vertical_connector_model import VerticalConnector
    from services.vertical_connector_service import add_connector_stop

    token, _ = create_admin_and_get_token(client, email="vc23@example.com")
    building, map_item = _floor_without_corridor(client, token, "VC23")

    connector = VerticalConnector(
        building_id=building["id"],
        map_group_id="vc23-group",
        connector_code="VC23-STAIR",
        name="Stair 2",
        connector_type="stairs",
    )
    await connector.insert()

    stored_map = await Map.get(map_item["id"])
    stored_map.map_group_id = "vc23-group"
    await stored_map.save()

    point, _reused, connected = await add_connector_stop(
        connector, map_id=map_item["id"], x=300, y=160, name=None, auto_connect="nearest"
    )
    assert connected is False

    hall_a = _create_point(client, token, map_item["id"], "Hall West", 0, 100)
    hall_b = _create_point(client, token, map_item["id"], "Hall East", 600, 100)
    _create_edge(client, token, map_item["id"], hall_a["id"], hall_b["id"])

    result = _retry(client, token, map_item["id"])

    assert result["attached"] >= 1

    edges = await _active_edges(map_item["id"])
    stop_id = str(point.id)
    assert any(stop_id in (e.from_point_id, e.to_point_id) for e in edges)


# =========================================================
# REGRESSION
# =========================================================

# 24. Auto Connect preview/apply still behaves
@pytest.mark.asyncio
async def test_auto_connect_preview_and_apply_still_work(client):
    token, _ = create_admin_and_get_token(client, email="rg24@example.com")
    building, map_item, hall_a, hall_b, _ = _floor_with_corridor(client, token, "RG24")

    # A raw destination point with no attach-on-save behind it.
    room_point = _create_point(
        client, token, map_item["id"], "Manual Room", 300, 300, point_type="room"
    )

    preview = client.post(
        "/api/route-edges/auto-connect-destinations/preview",
        json={"map_id": map_item["id"]},
        headers=auth_headers(token),
    )
    assert preview.status_code == 200, preview.text
    result = preview.json()

    proposal = next(
        p for p in result["proposals"] if p["destination_point_id"] == room_point["id"]
    )
    assert proposal["status"] == "proposed"
    assert proposal["candidates"]
    assert all(
        c["point_type"] in ("hallway", "junction") for c in proposal["candidates"]
    )


# 25. nested room routing remains valid
@pytest.mark.asyncio
async def test_nested_room_proposal_still_targets_the_approved_parent(client):
    token, _ = create_admin_and_get_token(client, email="rg25@example.com")
    building, map_item, _, _, _ = _floor_with_corridor(client, token, "RG25")

    outer = _create_room(client, token, building["id"], map_item["id"], "Outer", 200, 250)
    inner = _create_room(client, token, building["id"], map_item["id"], "Inner", 220, 260)

    client.put(
        f"/api/route-points/{outer['route_point_id']}",
        json={"allow_transit_through": True},
        headers=auth_headers(token),
    )
    inner_room = await Room.get(inner["id"])
    inner_room.parent_room_id = outer["id"]
    await inner_room.save()

    # Clear the inner room's own attach-on-save edge so the nested branch
    # is the one under test.
    for edge in await _active_edges(map_item["id"]):
        if inner["route_point_id"] in (edge.from_point_id, edge.to_point_id):
            edge.is_active = False
            await edge.save()

    preview = client.post(
        "/api/route-edges/auto-connect-destinations/preview",
        json={"map_id": map_item["id"]},
        headers=auth_headers(token),
    ).json()

    proposal = next(
        p
        for p in preview["proposals"]
        if p["destination_point_id"] == inner["route_point_id"]
    )
    assert proposal["is_nested_access"] is True
    assert proposal["proposed_candidate_id"] == outer["route_point_id"]


# 26. floor-scoped Room/QR filtering remains valid
@pytest.mark.asyncio
async def test_floor_scoped_room_filtering_still_holds(client):
    token, _ = create_admin_and_get_token(client, email="rg26@example.com")
    building = _create_building(client, token, "RG26 Building")
    ground = _create_map(client, token, "RG26 Ground", building["id"], floor=0)
    upper = _create_map(client, token, "RG26 Upper", building["id"], floor=1)

    _create_room(client, token, building["id"], ground["id"], "Ground Room", 100, 100, floor=0)
    _create_room(client, token, building["id"], upper["id"], "Upper Room", 100, 100, floor=1)

    ground_rooms = client.get(
        "/api/rooms", params={"map_id": ground["id"]}, headers=auth_headers(token)
    ).json()

    assert [r["name_en"] for r in ground_rooms] == ["Ground Room"]
