"""
Tests for "Auto Connect Destinations to Corridors":
  POST /api/route-edges/auto-connect-destinations/preview (read-only)
  POST /api/route-edges/auto-connect-destinations/apply (creates ordinary
  same-floor walkway RouteEdges only, and only for explicitly accepted
  pairs).

Confirmed project point types used throughout (constants/route_point_types.py):
  - destination-capable: "room", "store"
  - transit/corridor-capable: "hallway", "junction"
  (there is no separate "corridor" value anywhere in this codebase)

Run with: pytest backend/tests/test_auto_connect_destinations.py -v
"""

import time

import pytest

from tests.test_api_integration import auth_headers, create_admin_and_get_token

from models.route_point_model import RoutePoint
from models.route_edge_model import RouteEdge


PREVIEW_URL = "/api/route-edges/auto-connect-destinations/preview"
APPLY_URL = "/api/route-edges/auto-connect-destinations/apply"


# ---------------------------------------------------------
# Helpers (local copies, matching the established per-file convention —
# see tests/test_route_edge_floor_consistency.py and
# tests/test_delete_connection.py).
# ---------------------------------------------------------

def _create_map(client, token, title="Auto Connect Test Map", floor=None, building_id=None):
    payload = {"title": title, "floor": floor}
    if building_id:
        payload["building_id"] = building_id

    response = client.post("/api/maps", json=payload, headers=auth_headers(token))
    assert response.status_code == 201, response.text
    return response.json()


def _create_point(client, token, map_id, name, x, y, floor=None, point_type="hallway"):
    response = client.post(
        "/api/route-points",
        json={"map_id": map_id, "name": name, "x": x, "y": y, "floor": floor, "point_type": point_type},
        headers=auth_headers(token),
    )
    assert response.status_code == 201, response.text
    return response.json()


def _create_edge(client, token, map_id, from_point_id, to_point_id, edge_type="walkway"):
    response = client.post(
        "/api/route-edges",
        json={
            "map_id": map_id,
            "from_point_id": from_point_id,
            "to_point_id": to_point_id,
            "edge_type": edge_type,
        },
        headers=auth_headers(token),
    )
    assert response.status_code == 201, response.text
    return response.json()


def _preview(client, token, map_id, **kwargs):
    payload = {"map_id": map_id, **kwargs}
    response = client.post(PREVIEW_URL, json=payload, headers=auth_headers(token))
    assert response.status_code == 200, response.text
    return response.json()


def _apply(client, token, map_id, accepted):
    response = client.post(
        APPLY_URL,
        json={"map_id": map_id, "accepted": accepted},
        headers=auth_headers(token),
    )
    assert response.status_code == 200, response.text
    return response.json()


def _find_proposal(preview_result, destination_point_id):
    for proposal in preview_result["proposals"]:
        if proposal["destination_point_id"] == destination_point_id:
            return proposal
    return None


# ---------------------------------------------------------
# 1. Preview performs no database writes.
# ---------------------------------------------------------

def test_preview_performs_no_database_writes(client):
    token, _ = create_admin_and_get_token(client, role="global_manager", email="ac1@example.com")

    map_item = _create_map(client, token)
    hallway = _create_point(client, token, map_item["id"], "Main Hallway", 100, 100, point_type="hallway")
    room = _create_point(client, token, map_item["id"], "Conference Room", 130, 100, point_type="room")

    edges_before = client.get("/api/route-edges", params={"map_id": map_item["id"]}).json()
    points_before = client.get("/api/route-points", params={"map_id": map_item["id"]}).json()

    result = _preview(client, token, map_item["id"])
    assert len(result["proposals"]) >= 1

    edges_after = client.get("/api/route-edges", params={"map_id": map_item["id"]}).json()
    points_after = client.get("/api/route-points", params={"map_id": map_item["id"]}).json()

    assert edges_before == edges_after == []
    assert len(points_after) == len(points_before) == 2


# ---------------------------------------------------------
# 2. Unconnected Room gets valid corridor candidates.
# ---------------------------------------------------------

def test_unconnected_room_gets_valid_corridor_candidates(client):
    token, _ = create_admin_and_get_token(client, role="global_manager", email="ac2@example.com")

    map_item = _create_map(client, token)
    hallway = _create_point(client, token, map_item["id"], "Corridor Point A", 100, 100, point_type="hallway")
    room = _create_point(client, token, map_item["id"], "Sales Room", 130, 100, point_type="room")

    result = _preview(client, token, map_item["id"])
    proposal = _find_proposal(result, room["id"])

    assert proposal is not None
    assert proposal["status"] == "proposed"
    assert len(proposal["candidates"]) >= 1
    assert proposal["proposed_candidate_id"] == hallway["id"]
    assert proposal["candidates"][0]["point_id"] == hallway["id"]
    # No source image was uploaded for this test map, so wall geometry is
    # genuinely unavailable — this must be "needs_review", never a
    # falsely-claimed high/medium/low confidence (Section 7).
    assert proposal["confidence"] == "needs_review"


# ---------------------------------------------------------
# 3. Unconnected Store gets candidates.
# ---------------------------------------------------------

def test_unconnected_store_gets_candidates(client):
    token, _ = create_admin_and_get_token(client, role="global_manager", email="ac3@example.com")

    map_item = _create_map(client, token)
    hallway = _create_point(client, token, map_item["id"], "Corridor Point B", 200, 200, point_type="hallway")
    store = _create_point(client, token, map_item["id"], "Gift Shop", 230, 200, point_type="store")

    result = _preview(client, token, map_item["id"])
    proposal = _find_proposal(result, store["id"])

    assert proposal is not None
    assert proposal["status"] == "proposed"
    assert proposal["proposed_candidate_id"] == hallway["id"]


# ---------------------------------------------------------
# 4. Already-connected destination is skipped.
# ---------------------------------------------------------

def test_already_connected_destination_is_skipped(client):
    token, _ = create_admin_and_get_token(client, role="global_manager", email="ac4@example.com")

    map_item = _create_map(client, token)
    hallway = _create_point(client, token, map_item["id"], "Corridor Point C", 300, 300, point_type="hallway")
    room = _create_point(client, token, map_item["id"], "Already Linked Room", 330, 300, point_type="room")
    _create_edge(client, token, map_item["id"], room["id"], hallway["id"])

    result = _preview(client, token, map_item["id"])
    proposal = _find_proposal(result, room["id"])

    assert proposal is None
    assert result["summary"]["already_connected"] >= 1


# ---------------------------------------------------------
# 5. A Room is never proposed to another Room.
# ---------------------------------------------------------

def test_room_never_proposed_to_another_room(client):
    token, _ = create_admin_and_get_token(client, role="global_manager", email="ac5@example.com")

    map_item = _create_map(client, token)
    room_a = _create_point(client, token, map_item["id"], "Room A Nearby", 400, 400, point_type="room")
    # Deliberately much closer than the real hallway, so a naive nearest-
    # neighbor implementation without type filtering would wrongly pick it.
    room_b = _create_point(client, token, map_item["id"], "Room B Very Close", 405, 400, point_type="room")
    hallway = _create_point(client, token, map_item["id"], "Corridor Point D", 460, 400, point_type="hallway")

    result = _preview(client, token, map_item["id"])
    proposal = _find_proposal(result, room_a["id"])

    assert proposal is not None
    assert proposal["status"] == "proposed"
    candidate_ids = [c["point_id"] for c in proposal["candidates"]]
    assert room_b["id"] not in candidate_ids
    assert proposal["proposed_candidate_id"] == hallway["id"]


# ---------------------------------------------------------
# 6. A Store is never proposed to another Store.
# ---------------------------------------------------------

def test_store_never_proposed_to_another_store(client):
    token, _ = create_admin_and_get_token(client, role="global_manager", email="ac6@example.com")

    map_item = _create_map(client, token)
    store_a = _create_point(client, token, map_item["id"], "Store A Nearby", 500, 500, point_type="store")
    store_b = _create_point(client, token, map_item["id"], "Store B Very Close", 505, 500, point_type="store")
    hallway = _create_point(client, token, map_item["id"], "Corridor Point E", 560, 500, point_type="hallway")

    result = _preview(client, token, map_item["id"])
    proposal = _find_proposal(result, store_a["id"])

    assert proposal is not None
    candidate_ids = [c["point_id"] for c in proposal["candidates"]]
    assert store_b["id"] not in candidate_ids
    assert proposal["proposed_candidate_id"] == hallway["id"]


# ---------------------------------------------------------
# 7. Stairs/elevator stops are never candidates.
# ---------------------------------------------------------

def test_stairs_and_elevator_are_never_candidates(client):
    token, _ = create_admin_and_get_token(client, role="global_manager", email="ac7@example.com")

    map_item = _create_map(client, token)
    room = _create_point(client, token, map_item["id"], "Isolated Room", 600, 600, point_type="room")
    stairs = _create_point(client, token, map_item["id"], "Stairwell Point", 610, 600, point_type="stairs")
    elevator = _create_point(client, token, map_item["id"], "Elevator Point", 620, 600, point_type="elevator")

    result = _preview(client, token, map_item["id"])
    proposal = _find_proposal(result, room["id"])

    assert proposal is not None
    assert proposal["status"] == "no_candidate"
    assert proposal["candidates"] == []


# ---------------------------------------------------------
# 8. Candidates must be on the same map and floor.
# ---------------------------------------------------------

def test_candidates_must_be_same_map_and_floor(client):
    token, _ = create_admin_and_get_token(client, role="global_manager", email="ac8@example.com")

    map_a = _create_map(client, token, title="Map A")
    map_b = _create_map(client, token, title="Map B")

    room = _create_point(client, token, map_a["id"], "Room On Map A", 100, 100, point_type="room")
    # Same coordinates, but a genuinely different Map document — must never
    # be treated as a candidate even though x/y "look close".
    _create_point(client, token, map_b["id"], "Hallway On Map B", 100, 100, point_type="hallway")

    result = _preview(client, token, map_a["id"])
    proposal = _find_proposal(result, room["id"])

    assert proposal is not None
    assert proposal["status"] == "no_candidate"


# ---------------------------------------------------------
# 9. No candidate outside the configured threshold.
# ---------------------------------------------------------

def test_no_candidate_outside_configured_threshold(client):
    token, _ = create_admin_and_get_token(client, role="global_manager", email="ac9@example.com")

    map_item = _create_map(client, token)
    room = _create_point(client, token, map_item["id"], "Far Room", 0, 0, point_type="room")
    # Far beyond the default max distance (600px).
    _create_point(client, token, map_item["id"], "Distant Hallway", 5000, 5000, point_type="hallway")

    result = _preview(client, token, map_item["id"])
    proposal = _find_proposal(result, room["id"])

    assert proposal is not None
    assert proposal["status"] == "no_candidate"
    assert proposal["reason"] == "no_transit_point_within_range"


# ---------------------------------------------------------
# 10. Apply creates only explicitly accepted pairs.
# ---------------------------------------------------------

def test_apply_creates_only_explicitly_accepted_pairs(client):
    token, _ = create_admin_and_get_token(client, role="global_manager", email="ac10@example.com")

    map_item = _create_map(client, token)
    hallway = _create_point(client, token, map_item["id"], "Corridor Point F", 700, 700, point_type="hallway")
    room_1 = _create_point(client, token, map_item["id"], "Room One", 720, 700, point_type="room")
    room_2 = _create_point(client, token, map_item["id"], "Room Two", 680, 700, point_type="room")

    result = _apply(
        client,
        token,
        map_item["id"],
        accepted=[{"destination_point_id": room_1["id"], "corridor_point_id": hallway["id"]}],
    )

    assert result["requested"] == 1
    assert result["created"] == 1
    assert len(result["created_edge_ids"]) == 1

    edges = client.get("/api/route-edges", params={"map_id": map_item["id"]}).json()
    assert len(edges) == 1
    assert {edges[0]["from_point_id"], edges[0]["to_point_id"]} == {room_1["id"], hallway["id"]}

    # room_2 was never accepted — no edge for it.
    for edge in edges:
        assert room_2["id"] not in (edge["from_point_id"], edge["to_point_id"])


# ---------------------------------------------------------
# 11. Duplicate edge is not created.
# ---------------------------------------------------------

def test_duplicate_edge_is_not_created(client):
    token, _ = create_admin_and_get_token(client, role="global_manager", email="ac11@example.com")

    map_item = _create_map(client, token)
    hallway = _create_point(client, token, map_item["id"], "Corridor Point G", 800, 800, point_type="hallway")
    room = _create_point(client, token, map_item["id"], "Room Three", 820, 800, point_type="room")
    _create_edge(client, token, map_item["id"], room["id"], hallway["id"])

    result = _apply(
        client,
        token,
        map_item["id"],
        accepted=[{"destination_point_id": room["id"], "corridor_point_id": hallway["id"]}],
    )

    assert result["created"] == 0
    assert result["skipped_existing"] == 1

    edges = client.get("/api/route-edges", params={"map_id": map_item["id"]}).json()
    assert len(edges) == 1


# ---------------------------------------------------------
# 12. Reverse-direction duplicate is detected.
# ---------------------------------------------------------

def test_reverse_direction_duplicate_is_detected(client):
    token, _ = create_admin_and_get_token(client, role="global_manager", email="ac12@example.com")

    map_item = _create_map(client, token)
    hallway = _create_point(client, token, map_item["id"], "Corridor Point H", 900, 900, point_type="hallway")
    room = _create_point(client, token, map_item["id"], "Room Four", 920, 900, point_type="room")
    # Existing edge stored in the OPPOSITE direction from what apply will
    # be asked to create.
    _create_edge(client, token, map_item["id"], hallway["id"], room["id"])

    result = _apply(
        client,
        token,
        map_item["id"],
        accepted=[{"destination_point_id": room["id"], "corridor_point_id": hallway["id"]}],
    )

    assert result["created"] == 0
    assert result["skipped_existing"] == 1

    edges = client.get("/api/route-edges", params={"map_id": map_item["id"]}).json()
    assert len(edges) == 1


# ---------------------------------------------------------
# 13. Invalid or stale preview pair is rejected during apply.
# ---------------------------------------------------------

def test_invalid_or_stale_pair_is_rejected_during_apply(client):
    token, _ = create_admin_and_get_token(client, role="global_manager", email="ac13@example.com")

    map_item = _create_map(client, token)
    room_a = _create_point(client, token, map_item["id"], "Room Five", 100, 200, point_type="room")
    room_b = _create_point(client, token, map_item["id"], "Room Six", 120, 200, point_type="room")

    # (a) A stale/nonexistent point id (e.g. the frontend held a preview
    # open after the point was deleted elsewhere).
    delete_response = client.delete(f"/api/route-points/{room_b['id']}", headers=auth_headers(token))
    assert delete_response.status_code == 200, delete_response.text

    # (b) A Room→Room pair — never a valid corridor connection regardless
    # of what any preview claimed.
    result = _apply(
        client,
        token,
        map_item["id"],
        accepted=[
            {"destination_point_id": room_a["id"], "corridor_point_id": room_b["id"]},
        ],
    )

    assert result["created"] == 0
    assert result["rejected_invalid"] == 1

    edges = client.get("/api/route-edges", params={"map_id": map_item["id"]}).json()
    assert edges == []


def test_room_to_room_pair_is_rejected_during_apply(client):
    token, _ = create_admin_and_get_token(client, role="global_manager", email="ac13b@example.com")

    map_item = _create_map(client, token)
    room_a = _create_point(client, token, map_item["id"], "Room Seven", 300, 400, point_type="room")
    room_b = _create_point(client, token, map_item["id"], "Room Eight", 320, 400, point_type="room")

    result = _apply(
        client,
        token,
        map_item["id"],
        accepted=[{"destination_point_id": room_a["id"], "corridor_point_id": room_b["id"]}],
    )

    assert result["created"] == 0
    assert result["rejected_invalid"] == 1

    edges = client.get("/api/route-edges", params={"map_id": map_item["id"]}).json()
    assert edges == []


# ---------------------------------------------------------
# 14. Both RoutePoints remain unchanged after apply.
# ---------------------------------------------------------

def test_both_route_points_remain_unchanged_after_apply(client):
    token, _ = create_admin_and_get_token(client, role="global_manager", email="ac14@example.com")

    map_item = _create_map(client, token)
    hallway = _create_point(client, token, map_item["id"], "Corridor Point I", 150, 150, point_type="hallway")
    room = _create_point(client, token, map_item["id"], "Room Nine", 170, 150, point_type="room")

    _apply(
        client,
        token,
        map_item["id"],
        accepted=[{"destination_point_id": room["id"], "corridor_point_id": hallway["id"]}],
    )

    room_after = client.get(f"/api/route-points/{room['id']}").json()
    hallway_after = client.get(f"/api/route-points/{hallway['id']}").json()

    assert room_after["name"] == "Room Nine"
    assert room_after["point_type"] == "room"
    assert room_after["x"] == 170
    assert room_after["y"] == 150
    assert room_after["is_active"] is True

    assert hallway_after["name"] == "Corridor Point I"
    assert hallway_after["point_type"] == "hallway"
    assert hallway_after["is_active"] is True


# ---------------------------------------------------------
# 15. Dijkstra still routes to the newly connected destination.
# ---------------------------------------------------------

def test_dijkstra_routes_to_newly_connected_destination(client):
    token, _ = create_admin_and_get_token(client, role="global_manager", email="ac15@example.com")

    map_item = _create_map(client, token)
    entrance = _create_point(client, token, map_item["id"], "Front Entrance", 0, 0, point_type="entrance")
    hallway = _create_point(client, token, map_item["id"], "Corridor Point J", 50, 0, point_type="hallway")
    room = _create_point(client, token, map_item["id"], "Room Ten", 90, 0, point_type="room")

    # Entrance <-> hallway is a normal, pre-existing connection; only the
    # room's own corridor connection is missing.
    _create_edge(client, token, map_item["id"], entrance["id"], hallway["id"])

    before_route = client.post(
        "/api/navigation/route",
        json={"map_id": map_item["id"], "start_point_id": entrance["id"], "end_point_id": room["id"]},
    )
    assert before_route.status_code == 404

    apply_result = _apply(
        client,
        token,
        map_item["id"],
        accepted=[{"destination_point_id": room["id"], "corridor_point_id": hallway["id"]}],
    )
    assert apply_result["created"] == 1

    after_route = client.post(
        "/api/navigation/route",
        json={"map_id": map_item["id"], "start_point_id": entrance["id"], "end_point_id": room["id"]},
    )
    assert after_route.status_code == 200, after_route.text
    path_ids = after_route.json()["path_point_ids"]
    assert path_ids[0] == entrance["id"]
    assert path_ids[-1] == room["id"]
    assert hallway["id"] in path_ids


# ---------------------------------------------------------
# 16. Repeated apply is idempotent.
# ---------------------------------------------------------

def test_repeated_apply_is_idempotent(client):
    token, _ = create_admin_and_get_token(client, role="global_manager", email="ac16@example.com")

    map_item = _create_map(client, token)
    hallway = _create_point(client, token, map_item["id"], "Corridor Point K", 250, 250, point_type="hallway")
    room = _create_point(client, token, map_item["id"], "Room Eleven", 270, 250, point_type="room")

    accepted = [{"destination_point_id": room["id"], "corridor_point_id": hallway["id"]}]

    first = _apply(client, token, map_item["id"], accepted=accepted)
    assert first["created"] == 1

    second = _apply(client, token, map_item["id"], accepted=accepted)
    assert second["created"] == 0
    assert second["skipped_existing"] == 1

    edges = client.get("/api/route-edges", params={"map_id": map_item["id"]}).json()
    assert len(edges) == 1


# ---------------------------------------------------------
# 17. Preview handles at least 1,000 destination points without
#     pathological behaviour.
# ---------------------------------------------------------

@pytest.mark.asyncio
async def test_preview_handles_1000_destination_points(client):
    token, _ = create_admin_and_get_token(client, role="global_manager", email="ac17@example.com")

    map_item = _create_map(client, token)
    map_id = map_item["id"]

    # A small grid of hallway points spread across the map so every room
    # has at least one real nearby candidate, inserted directly via the
    # model (bypassing HTTP) purely for bulk-insert speed — the preview
    # endpoint itself is still exercised through the real HTTP route below.
    for hx in range(0, 2000, 200):
        for hy in range(0, 2000, 200):
            await RoutePoint(
                map_id=map_id,
                name=f"Corridor Point {hx}-{hy}",
                point_type="hallway",
                x=float(hx),
                y=float(hy),
                is_active=True,
            ).insert()

    for i in range(1000):
        await RoutePoint(
            map_id=map_id,
            name=f"Bulk Room {i}",
            point_type="room",
            x=float((i % 20) * 100 + 20),
            y=float((i // 20) * 100 + 20),
            is_active=True,
        ).insert()

    started = time.monotonic()
    result = _preview(client, token, map_id)
    elapsed = time.monotonic() - started

    assert len(result["proposals"]) >= 900
    assert result["summary"]["scanned"] == 1000
    # Generous ceiling for an in-memory mongomock test database — this is
    # a "not pathologically slow" guard, not a strict perf benchmark.
    assert elapsed < 30.0, f"preview took {elapsed:.2f}s for 1000 destinations"
