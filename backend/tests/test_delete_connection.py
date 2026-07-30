"""
Tests for the admin "Delete Connection" feature (AdminMapScreen.jsx): an
admin deletes a single RouteEdge ("Walkable Path" connection) without ever
deleting either endpoint RoutePoint.

No new backend endpoint was added for this feature — it reuses the
existing, already-admin-protected DELETE /api/route-edges/{edge_id}
endpoint (routes/route_edge_routes.py::delete_route_edge), which already
only ever calls `edge.delete()` on the RouteEdge document itself and never
touches RoutePoint, Room, QR/location-code, calibration, or Dijkstra/
routing logic in any way. These tests are therefore regression coverage
proving that existing contract holds, plus the auth/only-one-edge/repeat-
delete behaviors the new admin UI now depends on.

Run with: pytest backend/tests/test_delete_connection.py -v
"""

import pytest

from tests.test_api_integration import auth_headers, create_admin_and_get_token, make_invitation_code, signup

from models.route_point_model import RoutePoint
from models.route_edge_model import RouteEdge


# ---------------------------------------------------------
# Helpers (local copies, matching the established per-file convention used
# by tests/test_route_edge_floor_consistency.py — only auth_headers and
# create_admin_and_get_token are imported/reused from test_api_integration).
# ---------------------------------------------------------

def _create_map(client, token, title="Delete Connection Test Map", floor=None, building_id=None):
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


# ---------------------------------------------------------
# 1. Deleting an ordinary walkway edge succeeds and removes exactly that
#    RouteEdge document.
# ---------------------------------------------------------

def test_delete_connection_removes_the_edge(client):
    token, _ = create_admin_and_get_token(client, role="global_manager", email="delconn1@example.com")

    map_item = _create_map(client, token, title="Delete Connection Map 1")
    point_a = _create_point(client, token, map_item["id"], "Point A", 0, 0)
    point_b = _create_point(client, token, map_item["id"], "Point B", 10, 0)
    edge = _create_edge(client, token, map_item["id"], point_a["id"], point_b["id"])

    delete_response = client.delete(
        f"/api/route-edges/{edge['id']}",
        headers=auth_headers(token),
    )
    assert delete_response.status_code == 200, delete_response.text

    get_response = client.get(f"/api/route-edges/{edge['id']}")
    assert get_response.status_code == 404

    remaining = client.get("/api/route-edges", params={"map_id": map_item["id"]})
    assert remaining.status_code == 200
    assert edge["id"] not in [item["id"] for item in remaining.json()]


# ---------------------------------------------------------
# 2. Both endpoint RoutePoints remain completely unchanged after the
#    connecting edge is deleted — the core safety requirement of this
#    feature.
# ---------------------------------------------------------

def test_delete_connection_never_deletes_either_endpoint_route_point(client):
    token, _ = create_admin_and_get_token(client, role="global_manager", email="delconn2@example.com")

    map_item = _create_map(client, token, title="Delete Connection Map 2")
    point_a = _create_point(client, token, map_item["id"], "Room A", 0, 0, point_type="room")
    point_b = _create_point(client, token, map_item["id"], "Store B", 20, 0, point_type="store")
    edge = _create_edge(client, token, map_item["id"], point_a["id"], point_b["id"])

    delete_response = client.delete(
        f"/api/route-edges/{edge['id']}",
        headers=auth_headers(token),
    )
    assert delete_response.status_code == 200, delete_response.text

    point_a_after = client.get(f"/api/route-points/{point_a['id']}")
    point_b_after = client.get(f"/api/route-points/{point_b['id']}")

    assert point_a_after.status_code == 200, point_a_after.text
    assert point_b_after.status_code == 200, point_b_after.text

    assert point_a_after.json()["name"] == "Room A"
    assert point_a_after.json()["point_type"] == "room"
    assert point_a_after.json()["is_active"] is True

    assert point_b_after.json()["name"] == "Store B"
    assert point_b_after.json()["point_type"] == "store"
    assert point_b_after.json()["is_active"] is True


# ---------------------------------------------------------
# 3. Deleting one edge never deletes any other/sibling edge — "only the
#    exact selected edge may be removed".
# ---------------------------------------------------------

def test_delete_connection_only_removes_the_selected_edge(client):
    token, _ = create_admin_and_get_token(client, role="global_manager", email="delconn3@example.com")

    map_item = _create_map(client, token, title="Delete Connection Map 3")
    point_a = _create_point(client, token, map_item["id"], "Corridor Point A", 0, 0)
    point_b = _create_point(client, token, map_item["id"], "Corridor Point B", 10, 0)
    point_c = _create_point(client, token, map_item["id"], "Corridor Point C", 20, 0)

    edge_ab = _create_edge(client, token, map_item["id"], point_a["id"], point_b["id"])
    edge_bc = _create_edge(client, token, map_item["id"], point_b["id"], point_c["id"])

    delete_response = client.delete(
        f"/api/route-edges/{edge_ab['id']}",
        headers=auth_headers(token),
    )
    assert delete_response.status_code == 200, delete_response.text

    remaining_ids = [
        item["id"]
        for item in client.get("/api/route-edges", params={"map_id": map_item["id"]}).json()
    ]
    assert edge_ab["id"] not in remaining_ids
    assert edge_bc["id"] in remaining_ids


# ---------------------------------------------------------
# 4. The delete endpoint is admin-protected — a regular user cannot delete
#    a connection, and an unauthenticated request is also rejected.
# ---------------------------------------------------------

def test_delete_connection_requires_admin_role(client):
    token, _ = create_admin_and_get_token(client, role="global_manager", email="delconn4admin@example.com")

    map_item = _create_map(client, token, title="Delete Connection Map 4")
    point_a = _create_point(client, token, map_item["id"], "Corridor Point A", 0, 0)
    point_b = _create_point(client, token, map_item["id"], "Corridor Point B", 10, 0)
    edge = _create_edge(client, token, map_item["id"], point_a["id"], point_b["id"])

    # A regular (non-admin) user, invited by this same admin, must not be
    # able to delete a connection.
    regular_code = make_invitation_code(
        client, code="QR-DELCONN4", role="regular_user", creator_token=token
    )
    regular_signup = signup(client, regular_code, email="delconn4user@example.com")
    assert regular_signup.status_code == 200, regular_signup.text
    regular_token = regular_signup.json()["access_token"]

    forbidden_response = client.delete(
        f"/api/route-edges/{edge['id']}",
        headers=auth_headers(regular_token),
    )
    assert forbidden_response.status_code == 403

    # No auth header at all.
    unauthenticated_response = client.delete(f"/api/route-edges/{edge['id']}")
    assert unauthenticated_response.status_code in (401, 403)

    # The edge must still exist — neither rejected attempt deleted anything.
    still_there = client.get(f"/api/route-edges/{edge['id']}")
    assert still_there.status_code == 200


# ---------------------------------------------------------
# 5. Deleting an edge id that doesn't exist returns a safe 404 (this is the
#    "keep the edge visible, show a safe error" backend contract the
#    frontend's failure-handling branch relies on).
# ---------------------------------------------------------

def test_delete_connection_unknown_edge_id_returns_404(client):
    token, _ = create_admin_and_get_token(client, role="global_manager", email="delconn5@example.com")

    response = client.delete(
        "/api/route-edges/000000000000000000000000",
        headers=auth_headers(token),
    )
    assert response.status_code == 404
    assert "detail" in response.json()
    # The error must be a safe, human-readable string, never a raw
    # exception/traceback.
    assert isinstance(response.json()["detail"], str)


# ---------------------------------------------------------
# 6. Deleting the same connection twice: the second call is a safe 404,
#    not a crash or a silent success — matches "do not expose raw database
#    exceptions".
# ---------------------------------------------------------

def test_delete_connection_twice_second_call_is_safe_404(client):
    token, _ = create_admin_and_get_token(client, role="global_manager", email="delconn6@example.com")

    map_item = _create_map(client, token, title="Delete Connection Map 6")
    point_a = _create_point(client, token, map_item["id"], "Corridor Point A", 0, 0)
    point_b = _create_point(client, token, map_item["id"], "Corridor Point B", 10, 0)
    edge = _create_edge(client, token, map_item["id"], point_a["id"], point_b["id"])

    first = client.delete(f"/api/route-edges/{edge['id']}", headers=auth_headers(token))
    assert first.status_code == 200, first.text

    second = client.delete(f"/api/route-edges/{edge['id']}", headers=auth_headers(token))
    assert second.status_code == 404


# ---------------------------------------------------------
# 7. Regression proving edge deletion and point deletion stay correctly
#    linked: deleting the only connecting edge is what should legitimately
#    unblock deleting a RoutePoint afterward (test_api_integration.py's
#    test_route_point_delete_rejected_while_edges_exist already proves a
#    point CANNOT be deleted while an edge references it — this proves the
#    reverse still works once that edge is gone, without Delete Connection
#    needing to touch RoutePoint deletion logic itself at all).
# ---------------------------------------------------------

def test_deleting_connection_unblocks_previously_rejected_point_delete(client):
    token, _ = create_admin_and_get_token(client, role="global_manager", email="delconn7@example.com")

    map_item = _create_map(client, token, title="Delete Connection Map 7")
    point_a = _create_point(client, token, map_item["id"], "Corridor Point A", 0, 0)
    point_b = _create_point(client, token, map_item["id"], "Corridor Point B", 10, 0)
    edge = _create_edge(client, token, map_item["id"], point_a["id"], point_b["id"])

    blocked = client.delete(f"/api/route-points/{point_a['id']}", headers=auth_headers(token))
    assert blocked.status_code == 409

    delete_edge_response = client.delete(
        f"/api/route-edges/{edge['id']}", headers=auth_headers(token)
    )
    assert delete_edge_response.status_code == 200, delete_edge_response.text

    now_allowed = client.delete(f"/api/route-points/{point_a['id']}", headers=auth_headers(token))
    assert now_allowed.status_code == 200, now_allowed.text
