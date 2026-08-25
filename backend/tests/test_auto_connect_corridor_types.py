"""
Tests for the "Auto Connect Destinations" corridor point_type filtering
fix.

Bug being regression-tested: an admin created RoutePoints with point_type
"hallway"/"junction" (the only corridor-network types the frontend's Add
Route Point selector actually offers) and Auto Connect Destinations still
reported "No corridor point found" for every destination, even though
those hallway/junction points genuinely existed on the map. There is no
"corridor" value anywhere in RoutePoint.point_type's real value set.

This file proves:
  1. A hallway point is accepted as a corridor candidate.
  2. A junction point is accepted as a corridor candidate.
  3. A room point is not accepted as a corridor candidate.
  4. Candidates on another Map are ignored.
  5. Candidates on another Floor are ignored (even within the same Map).
  6. Existing hallway/junction points produce proposals when valid.
  7. Missing RouteEdges among transit points returns a distinct reason
     ("transit_points_not_connected_by_edges"), never the generic/blanket
     "no corridor point found" behavior.
  8. Preview performs no writes.

Also covers the map-level "no hallway/junction points exist at all"
reason ("no_transit_points_on_map"), completing the four required
distinct outcomes: (1) no candidates exist, (2) candidates exist but are
not connected to each other by RouteEdges, (3) candidates exist but are
too far, (4) a valid proposal is found.

Run with: pytest backend/tests/test_auto_connect_corridor_types.py -v
"""

import pytest

from tests.test_api_integration import auth_headers, create_admin_and_get_token

from constants.route_point_types import TRANSIT_CANDIDATE_POINT_TYPES
from models.route_point_model import RoutePoint
from models.route_edge_model import RouteEdge


PREVIEW_URL = "/api/route-edges/auto-connect-destinations/preview"


# ---------------------------------------------------------
# Helpers (local copies, matching the established per-file convention —
# see tests/test_auto_connect_destinations.py).
# ---------------------------------------------------------

def _create_map(client, token, title="Corridor Type Test Map", floor=None):
    response = client.post(
        "/api/maps", json={"title": title, "floor": floor}, headers=auth_headers(token)
    )
    assert response.status_code == 201, response.text
    return response.json()


def _create_point(client, token, map_id, name, x, y, floor=None, point_type="hallway"):
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


def _find_proposal(preview_result, destination_point_id):
    for proposal in preview_result["proposals"]:
        if proposal["destination_point_id"] == destination_point_id:
            return proposal
    return None


# ---------------------------------------------------------
# Sanity check on the constants themselves — this is the exact thing the
# bug report claimed was wrong ("point_type == 'corridor'" or an outdated
# list). Failing this test would mean the underlying constant regressed.
# ---------------------------------------------------------

def test_transit_candidate_types_are_hallway_and_junction_only():
    assert TRANSIT_CANDIDATE_POINT_TYPES == {"hallway", "junction"}
    assert "corridor" not in TRANSIT_CANDIDATE_POINT_TYPES


# ---------------------------------------------------------
# 1. A hallway point is accepted as a corridor candidate.
# ---------------------------------------------------------

def test_hallway_point_accepted_as_corridor_candidate(client):
    token, _ = create_admin_and_get_token(client, role="super_admin", email="corr1@example.com")

    map_item = _create_map(client, token)
    room = _create_point(client, token, map_item["id"], "Room", 100, 100, point_type="room")
    hallway = _create_point(client, token, map_item["id"], "Hallway", 130, 100, point_type="hallway")

    result = _preview(client, token, map_item["id"])
    proposal = _find_proposal(result, room["id"])

    assert proposal is not None
    assert proposal["status"] == "proposed"
    assert proposal["proposed_candidate_id"] == hallway["id"]
    assert proposal["candidates"][0]["point_type"] == "hallway"


# ---------------------------------------------------------
# 2. A junction point is accepted as a corridor candidate.
# ---------------------------------------------------------

def test_junction_point_accepted_as_corridor_candidate(client):
    token, _ = create_admin_and_get_token(client, role="super_admin", email="corr2@example.com")

    map_item = _create_map(client, token)
    store = _create_point(client, token, map_item["id"], "Store", 200, 200, point_type="store")
    junction = _create_point(client, token, map_item["id"], "Junction", 225, 200, point_type="junction")

    result = _preview(client, token, map_item["id"])
    proposal = _find_proposal(result, store["id"])

    assert proposal is not None
    assert proposal["status"] == "proposed"
    assert proposal["proposed_candidate_id"] == junction["id"]
    assert proposal["candidates"][0]["point_type"] == "junction"


# ---------------------------------------------------------
# 3. A room point is not accepted as a corridor candidate.
# ---------------------------------------------------------

def test_room_point_not_accepted_as_corridor_candidate(client):
    token, _ = create_admin_and_get_token(client, role="super_admin", email="corr3@example.com")

    map_item = _create_map(client, token)
    room_a = _create_point(client, token, map_item["id"], "Room A", 300, 300, point_type="room")
    # Only other RoutePoint on the map is itself destination-capable
    # ("room") — never a valid corridor candidate for another room.
    _create_point(client, token, map_item["id"], "Room B", 310, 300, point_type="room")

    result = _preview(client, token, map_item["id"])
    proposal = _find_proposal(result, room_a["id"])

    assert proposal is not None
    assert proposal["status"] == "no_candidate"
    assert proposal["candidates"] == []
    # No hallway/junction exists anywhere on this map at all.
    assert proposal["reason"] == "no_transit_points_on_map"


# ---------------------------------------------------------
# 4. Candidates on another Map are ignored.
# ---------------------------------------------------------

def test_hallway_on_another_map_is_ignored(client):
    token, _ = create_admin_and_get_token(client, role="super_admin", email="corr4@example.com")

    map_a = _create_map(client, token, title="Map A")
    map_b = _create_map(client, token, title="Map B")

    room = _create_point(client, token, map_a["id"], "Room On A", 100, 100, point_type="room")
    # Identical coordinates on a genuinely different Map — must never be
    # treated as a candidate.
    _create_point(client, token, map_b["id"], "Hallway On B", 100, 100, point_type="hallway")

    result = _preview(client, token, map_a["id"])
    proposal = _find_proposal(result, room["id"])

    assert proposal is not None
    assert proposal["status"] == "no_candidate"
    assert proposal["reason"] == "no_transit_points_on_map"


# ---------------------------------------------------------
# 5. Candidates on another Floor are ignored (even within the same Map).
# ---------------------------------------------------------

def test_hallway_on_another_floor_is_ignored(client):
    token, _ = create_admin_and_get_token(client, role="super_admin", email="corr5@example.com")

    map_item = _create_map(client, token)
    room = _create_point(
        client, token, map_item["id"], "Room Floor 0", 100, 100, floor=0, point_type="room"
    )
    # Same map, same pixel neighborhood, but a different `floor` value —
    # must never be proposed as a same-floor walkway candidate.
    _create_point(
        client, token, map_item["id"], "Hallway Floor 1", 105, 100, floor=1, point_type="hallway"
    )

    result = _preview(client, token, map_item["id"])
    proposal = _find_proposal(result, room["id"])

    assert proposal is not None
    assert proposal["status"] == "no_candidate"
    assert proposal["candidates"] == []


# ---------------------------------------------------------
# 6. Existing hallway/junction points produce proposals when valid.
# ---------------------------------------------------------

def test_existing_hallway_and_junction_points_produce_valid_proposals(client):
    token, _ = create_admin_and_get_token(client, role="super_admin", email="corr6@example.com")

    map_item = _create_map(client, token)
    room = _create_point(client, token, map_item["id"], "Room", 400, 400, point_type="room")
    store = _create_point(client, token, map_item["id"], "Store", 500, 500, point_type="store")
    hallway = _create_point(client, token, map_item["id"], "Hallway", 420, 400, point_type="hallway")
    junction = _create_point(client, token, map_item["id"], "Junction", 520, 500, point_type="junction")

    result = _preview(client, token, map_item["id"])

    room_proposal = _find_proposal(result, room["id"])
    store_proposal = _find_proposal(result, store["id"])

    assert room_proposal["status"] == "proposed"
    assert room_proposal["proposed_candidate_id"] == hallway["id"]

    assert store_proposal["status"] == "proposed"
    assert store_proposal["proposed_candidate_id"] == junction["id"]

    assert result["summary"]["scanned"] == 2
    assert result["summary"]["proposed"] == 2
    assert result["summary"]["no_candidate"] == 0


# ---------------------------------------------------------
# 7. Missing RouteEdges among transit points returns the correct reason
#    instead of the generic "No corridor point found" behavior.
# ---------------------------------------------------------

def test_disconnected_transit_network_returns_distinct_reason(client):
    token, _ = create_admin_and_get_token(client, role="super_admin", email="corr7@example.com")

    map_item = _create_map(client, token)
    room = _create_point(client, token, map_item["id"], "Room", 0, 0, point_type="room")
    # Two hallway/junction points exist on this map, but the admin never
    # drew a walkway connection between them — an isolated pair of dots,
    # not an actual connected corridor network.
    _create_point(client, token, map_item["id"], "Hallway One", 5000, 5000, point_type="hallway")
    _create_point(client, token, map_item["id"], "Junction Two", 5050, 5050, point_type="junction")

    result = _preview(client, token, map_item["id"])
    proposal = _find_proposal(result, room["id"])

    assert proposal is not None
    assert proposal["status"] == "no_candidate"
    assert proposal["reason"] == "transit_points_not_connected_by_edges"
    # Never the old undifferentiated behavior.
    assert proposal["reason"] != "no_transit_point_within_range"


def test_connected_transit_network_does_not_trigger_disconnected_reason(client):
    """Sibling of the above: once the admin DOES connect the two transit
    points to each other with a walkway edge, the network is no longer
    reported as disconnected — proving the check is genuinely about edge
    connectivity, not merely "more than one transit point exists"."""

    token, _ = create_admin_and_get_token(client, role="super_admin", email="corr7b@example.com")

    map_item = _create_map(client, token)
    room = _create_point(client, token, map_item["id"], "Room", 400, 400, point_type="room")
    hallway = _create_point(client, token, map_item["id"], "Hallway A", 420, 400, point_type="hallway")
    junction = _create_point(client, token, map_item["id"], "Junction B", 800, 800, point_type="junction")

    _create_edge(client, token, map_item["id"], hallway["id"], junction["id"])

    result = _preview(client, token, map_item["id"])
    proposal = _find_proposal(result, room["id"])

    assert proposal is not None
    assert proposal["status"] == "proposed"
    assert proposal["proposed_candidate_id"] == hallway["id"]


# ---------------------------------------------------------
# 8. Preview performs no writes.
# ---------------------------------------------------------

@pytest.mark.asyncio
async def test_preview_creates_zero_route_points_and_edges(client):
    token, _ = create_admin_and_get_token(client, role="super_admin", email="corr8@example.com")

    map_item = _create_map(client, token)
    room = _create_point(client, token, map_item["id"], "Room", 100, 100, point_type="room")
    _create_point(client, token, map_item["id"], "Hallway", 120, 100, point_type="hallway")

    points_before = await RoutePoint.find({"map_id": map_item["id"]}).to_list()
    edges_before = await RouteEdge.find({"map_id": map_item["id"]}).to_list()

    result = _preview(client, token, map_item["id"])
    assert _find_proposal(result, room["id"])["status"] == "proposed"

    points_after = await RoutePoint.find({"map_id": map_item["id"]}).to_list()
    edges_after = await RouteEdge.find({"map_id": map_item["id"]}).to_list()

    assert len(points_after) == len(points_before) == 2
    assert len(edges_after) == len(edges_before) == 0
