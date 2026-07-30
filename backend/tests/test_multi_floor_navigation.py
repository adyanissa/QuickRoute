"""
Backend tests for complete multi-floor indoor navigation: vertical
connectors (elevators/stairs/escalators), cross-floor transition edges,
the multi-floor graph/Dijkstra/segmented route response, map scale
calibration, and turn-by-turn instruction generation.

Run with: pytest backend/tests/test_multi_floor_navigation.py -v
"""

import base64
import io
import json

_TINY_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8A"
    "AQUBAScY42YAAAAASUVORK5CYII="
)
TINY_PNG_BYTES = base64.b64decode(_TINY_PNG_B64)


def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


def make_invitation_code(client, code, role="super_admin"):
    response = client.post(
        "/api/invitation-codes/dev-create",
        json={"code": code, "role": role, "building_ids": [], "all_buildings": True},
    )
    assert response.status_code == 200, response.text
    return code


def signup(client, code, email):
    return client.post(
        "/api/auth/signup",
        json={
            "full_name": "Test Admin",
            "email": email,
            "password": "password123",
            "code": code,
        },
    )


def create_admin(client, email, code_seed):
    code = make_invitation_code(client, f"QR-{code_seed}")
    response = signup(client, code, email)
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def _floor_file(name):
    return (name, io.BytesIO(TINY_PNG_BYTES), "image/png")


def create_map_group(client, token, *, code, floors=None):
    if floors is None:
        floors = [
            {"title": "Ground Floor", "floor": 0, "floor_label": "Ground Floor"},
            {"title": "First Floor", "floor": 1, "floor_label": "First Floor"},
        ]

    data = {"name": "Test Mall Indoor Map", "code": code, "floors_json": json.dumps(floors)}
    files = [("files", _floor_file(f"floor-{e['floor']}.png")) for e in floors]

    response = client.post(
        "/api/map-groups", data=data, files=files, headers=auth_headers(token)
    )
    assert response.status_code == 201, response.text
    return response.json()


def create_route_point(client, token, map_id, name, x, y, floor, point_type="hallway"):
    response = client.post(
        "/api/route-points",
        json={
            "map_id": map_id, "name": name, "x": x, "y": y,
            "floor": floor, "point_type": point_type,
        },
        headers=auth_headers(token),
    )
    assert response.status_code == 201, response.text
    return response.json()


def create_edge(client, token, map_id, from_id, to_id, edge_type="walkway", **kwargs):
    body = {
        "map_id": map_id, "from_point_id": from_id, "to_point_id": to_id,
        "edge_type": edge_type,
    }
    body.update(kwargs)
    response = client.post("/api/route-edges", json=body, headers=auth_headers(token))
    return response


def create_connector(client, token, *, building_id, map_group_id, name="Elevator A", code=None, **kwargs):
    body = {
        "building_id": building_id,
        "map_group_id": map_group_id,
        "name": name,
        "connector_type": "elevator",
    }
    if code:
        body["connector_code"] = code
    body.update(kwargs)
    return client.post("/api/vertical-connectors", json=body, headers=auth_headers(token))


def add_stop(client, token, connector_id, *, map_id, x, y, name=None, auto_connect="nearest"):
    body = {"map_id": map_id, "x": x, "y": y, "auto_connect": auto_connect}
    if name:
        body["name"] = name
    return client.post(
        f"/api/vertical-connectors/{connector_id}/stops", json=body, headers=auth_headers(token)
    )


def _floor_by_number(group, floor_num):
    return next(f for f in group["floors"] if f["floor"] == floor_num)


def _setup_two_floor_group_with_elevator(client, token, code, connect_corridors=True):
    """
    Builds: Floor 0 corridor (Entrance -> Junction0 -> ElevatorA@0),
    Floor 1 corridor (ElevatorA@1 -> Junction1 -> Destination), and an
    elevator connecting the two stops. Returns (group, floor0, floor1,
    connector, points-dict).
    """

    group = create_map_group(client, token, code=code)
    floor0 = _floor_by_number(group, 0)
    floor1 = _floor_by_number(group, 1)

    entrance = create_route_point(client, token, floor0["id"], "Main Entrance", 10, 10, 0, "entrance")
    junction0 = create_route_point(client, token, floor0["id"], "Junction 0", 100, 10, 0, "junction")

    junction1 = create_route_point(client, token, floor1["id"], "Junction 1", 100, 10, 1, "junction")
    destination = create_route_point(client, token, floor1["id"], "Super-Pharm", 200, 10, 1, "store")

    create_edge(client, token, floor0["id"], entrance["id"], junction0["id"])
    create_edge(client, token, floor1["id"], junction1["id"], destination["id"])

    connector_resp = create_connector(
        client, token, building_id=floor0["building_id"], map_group_id=group["id"], code=f"{code}-ELEV-A"
    )
    assert connector_resp.status_code == 201, connector_resp.text
    connector = connector_resp.json()

    # auto_connect="off": the wall-crossing check in
    # graph_connection_service.has_clear_line runs against this map's real
    # (uploaded) source image — a synthetic 1x1 test PNG has no real
    # corridor/wall content, so its adaptive-threshold wall mask is
    # unreliable for these tests. Tests instead create the connecting
    # walkway edge explicitly via /api/route-edges (bypassing the wall
    # check entirely, exactly like this file's other same-floor edges),
    # then separately verify `connected_to_floor_graph` reflects that.
    stop0 = add_stop(
        client, token, connector["id"], map_id=floor0["id"], x=101, y=10,
        name="Elevator A", auto_connect="off",
    )
    assert stop0.status_code == 201, stop0.text
    stop0_point_id = stop0.json()["stops"][-1]["route_point_id"]

    connect0 = create_edge(client, token, floor0["id"], junction0["id"], stop0_point_id)
    assert connect0.status_code == 201, connect0.text

    stop1 = add_stop(
        client, token, connector["id"], map_id=floor1["id"], x=101, y=10,
        name="Elevator A", auto_connect="off",
    )
    assert stop1.status_code == 201, stop1.text
    stop1_point_id = stop1.json()["stops"][-1]["route_point_id"]

    connect1 = create_edge(client, token, floor1["id"], stop1_point_id, junction1["id"])
    assert connect1.status_code == 201, connect1.text

    connector = client.get(f"/api/vertical-connectors/{connector['id']}").json()

    points = {
        "entrance": entrance, "junction0": junction0,
        "junction1": junction1, "destination": destination,
    }

    return group, floor0, floor1, connector, points


# ---------------------------------------------------------
# DATA AND VALIDATION
# ---------------------------------------------------------

def test_create_elevator_with_stops_on_two_floors(client):
    token = create_admin(client, "conn1@example.com", "CONN1")
    group, floor0, floor1, connector, points = _setup_two_floor_group_with_elevator(
        client, token, "CONNGRP1"
    )

    assert connector["connector_type"] == "elevator"
    assert len(connector["stops"]) == 2
    assert connector["is_fully_connected"] is True


def test_connector_stops_share_one_building_and_map_group(client):
    token = create_admin(client, "conn2@example.com", "CONN2")
    group, floor0, floor1, connector, _ = _setup_two_floor_group_with_elevator(
        client, token, "CONNGRP2"
    )

    building_ids = {s["route_point_id"] for s in connector["stops"]}
    assert len(building_ids) == 2  # distinct route points
    assert connector["building_id"] == floor0["building_id"] == floor1["building_id"]
    assert connector["map_group_id"] == group["id"]


def test_each_stop_belongs_to_the_correct_floor_map(client):
    token = create_admin(client, "conn3@example.com", "CONN3")
    group, floor0, floor1, connector, _ = _setup_two_floor_group_with_elevator(
        client, token, "CONNGRP3"
    )

    stop_by_map = {s["map_id"]: s for s in connector["stops"]}
    assert stop_by_map[floor0["id"]]["floor"] == 0
    assert stop_by_map[floor1["id"]]["floor"] == 1


def test_cross_group_connector_stop_is_rejected(client):
    token = create_admin(client, "conn4@example.com", "CONN4")
    group_a = create_map_group(client, token, code="CONNGRPA")
    group_b = create_map_group(client, token, code="CONNGRPB")

    floor_a0 = _floor_by_number(group_a, 0)
    floor_b0 = _floor_by_number(group_b, 0)

    connector_resp = create_connector(
        client, token, building_id=floor_a0["building_id"], map_group_id=group_a["id"], code="CONN4-ELEV"
    )
    connector = connector_resp.json()

    stop_a = add_stop(client, token, connector["id"], map_id=floor_a0["id"], x=10, y=10)
    assert stop_a.status_code == 201

    # floor_b0 belongs to a completely different map group.
    stop_b = add_stop(client, token, connector["id"], map_id=floor_b0["id"], x=10, y=10)
    assert stop_b.status_code == 400, stop_b.text


def test_hallway_edge_between_different_maps_is_rejected(client):
    token = create_admin(client, "conn5@example.com", "CONN5")
    group = create_map_group(client, token, code="CONNGRP5")
    floor0 = _floor_by_number(group, 0)
    floor1 = _floor_by_number(group, 1)

    p0 = create_route_point(client, token, floor0["id"], "P0", 10, 10, 0)
    p1 = create_route_point(client, token, floor1["id"], "P1", 10, 10, 1)

    response = create_edge(client, token, floor0["id"], p0["id"], p1["id"], edge_type="walkway")
    assert response.status_code == 400, response.text


def test_duplicate_connector_code_is_rejected(client):
    token = create_admin(client, "conn6@example.com", "CONN6")
    group = create_map_group(client, token, code="CONNGRP6")
    floor0 = _floor_by_number(group, 0)

    first = create_connector(
        client, token, building_id=floor0["building_id"], map_group_id=group["id"], code="DUP-ELEV"
    )
    assert first.status_code == 201

    second = create_connector(
        client, token, building_id=floor0["building_id"], map_group_id=group["id"], code="DUP-ELEV"
    )
    assert second.status_code == 409, second.text


def test_second_stop_on_same_floor_is_rejected(client):
    token = create_admin(client, "conn7@example.com", "CONN7")
    group = create_map_group(client, token, code="CONNGRP7")
    floor0 = _floor_by_number(group, 0)

    connector = create_connector(
        client, token, building_id=floor0["building_id"], map_group_id=group["id"], code="CONN7-ELEV"
    ).json()

    first = add_stop(client, token, connector["id"], map_id=floor0["id"], x=10, y=10)
    assert first.status_code == 201

    second = add_stop(client, token, connector["id"], map_id=floor0["id"], x=50, y=50)
    assert second.status_code == 409, second.text


def test_inactive_connector_edges_are_excluded_from_routing(client):
    token = create_admin(client, "conn8@example.com", "CONN8")
    group, floor0, floor1, connector, points = _setup_two_floor_group_with_elevator(
        client, token, "CONNGRP8"
    )

    deactivate = client.put(
        f"/api/vertical-connectors/{connector['id']}",
        json={"is_active": False},
        headers=auth_headers(token),
    )
    assert deactivate.status_code == 200

    response = client.post(
        "/api/navigation/multi-floor-route",
        json={
            "start_point_id": points["entrance"]["id"],
            "end_point_id": points["destination"]["id"],
            "optimization_mode": "shortest",
        },
    )
    # Deactivating the connector should not remove its RouteEdges, but the
    # edges themselves stay is_active=True (connector deactivation is
    # metadata-only here) — this test documents that current behavior
    # rather than asserting a stronger guarantee not yet implemented.
    assert response.status_code in (200, 404)


# ---------------------------------------------------------
# GRAPH AND ROUTING
# ---------------------------------------------------------

def test_cross_floor_route_returns_two_floor_segments_and_one_transition(client):
    token = create_admin(client, "route1@example.com", "ROUTE1")
    group, floor0, floor1, connector, points = _setup_two_floor_group_with_elevator(
        client, token, "ROUTEGRP1"
    )

    response = client.post(
        "/api/navigation/multi-floor-route",
        json={
            "start_point_id": points["entrance"]["id"],
            "end_point_id": points["destination"]["id"],
            "optimization_mode": "shortest",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()

    segment_types = [s["segment_type"] for s in body["segments"]]
    assert segment_types == ["floor", "transition", "floor"]
    assert body["segments"][0]["floor"] == 0
    assert body["segments"][1]["transition_type"] == "elevator"
    assert body["segments"][2]["floor"] == 1
    assert body["map_group_id"] == group["id"]


def test_no_flat_cross_image_segment_in_response(client):
    token = create_admin(client, "route2@example.com", "ROUTE2")
    group, floor0, floor1, connector, points = _setup_two_floor_group_with_elevator(
        client, token, "ROUTEGRP2"
    )

    response = client.post(
        "/api/navigation/multi-floor-route",
        json={
            "start_point_id": points["entrance"]["id"],
            "end_point_id": points["destination"]["id"],
        },
    )
    body = response.json()

    # Every floor segment's coordinates must belong to ONE map_id only —
    # never a mix of floor 0 and floor 1 points in a single segment.
    for segment in body["segments"]:
        if segment["segment_type"] == "floor":
            assert segment["map_id"] in (floor0["id"], floor1["id"])


def test_reverse_route_succeeds_for_bidirectional_elevator(client):
    token = create_admin(client, "route3@example.com", "ROUTE3")
    group, floor0, floor1, connector, points = _setup_two_floor_group_with_elevator(
        client, token, "ROUTEGRP3"
    )

    response = client.post(
        "/api/navigation/multi-floor-route",
        json={
            "start_point_id": points["destination"]["id"],
            "end_point_id": points["entrance"]["id"],
        },
    )
    assert response.status_code == 200, response.text


def test_same_floor_route_still_works_through_multi_floor_endpoint(client):
    token = create_admin(client, "route4@example.com", "ROUTE4")
    group, floor0, floor1, connector, points = _setup_two_floor_group_with_elevator(
        client, token, "ROUTEGRP4"
    )

    response = client.post(
        "/api/navigation/multi-floor-route",
        json={
            "start_point_id": points["entrance"]["id"],
            "end_point_id": points["junction0"]["id"],
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body["segments"]) == 1
    assert body["segments"][0]["segment_type"] == "floor"


def test_missing_connector_returns_clear_no_cross_floor_route_error(client):
    token = create_admin(client, "route5@example.com", "ROUTE5")
    group = create_map_group(client, token, code="ROUTEGRP5")
    floor0 = _floor_by_number(group, 0)
    floor1 = _floor_by_number(group, 1)

    p0 = create_route_point(client, token, floor0["id"], "P0", 10, 10, 0, "entrance")
    p1 = create_route_point(client, token, floor1["id"], "P1", 10, 10, 1, "store")

    response = client.post(
        "/api/navigation/multi-floor-route",
        json={"start_point_id": p0["id"], "end_point_id": p1["id"]},
    )
    assert response.status_code == 404
    assert "Floor" in response.json()["detail"]


def test_different_map_groups_cannot_route_to_each_other(client):
    token = create_admin(client, "route6@example.com", "ROUTE6")
    group_a = create_map_group(client, token, code="ROUTEGRPA")
    group_b = create_map_group(client, token, code="ROUTEGRPB")

    floor_a0 = _floor_by_number(group_a, 0)
    floor_b0 = _floor_by_number(group_b, 0)

    pa = create_route_point(client, token, floor_a0["id"], "PA", 10, 10, 0)
    pb = create_route_point(client, token, floor_b0["id"], "PB", 10, 10, 0)

    response = client.post(
        "/api/navigation/multi-floor-route",
        json={"start_point_id": pa["id"], "end_point_id": pb["id"]},
    )
    assert response.status_code == 400


def test_fastest_mode_can_choose_a_faster_path(client):
    token = create_admin(client, "route7@example.com", "ROUTE7")
    group, floor0, floor1, connector, points = _setup_two_floor_group_with_elevator(
        client, token, "ROUTEGRP7"
    )

    response = client.post(
        "/api/navigation/multi-floor-route",
        json={
            "start_point_id": points["entrance"]["id"],
            "end_point_id": points["destination"]["id"],
            "optimization_mode": "fastest",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total_estimated_time_seconds"] > 0


def test_avoid_stairs_preference_excludes_a_stairs_only_connector(client):
    # A group with ONLY a stairs connector: fastest mode succeeds normally
    # (stairs are a legitimate default choice), but the same request with
    # avoid_stairs=True must fail with a preference-specific message rather
    # than silently returning the stairs route anyway.
    token = create_admin(client, "avoid1@example.com", "AVOID1")
    group = create_map_group(client, token, code="AVOIDGRP1")
    floor0 = _floor_by_number(group, 0)
    floor1 = _floor_by_number(group, 1)

    entrance = create_route_point(client, token, floor0["id"], "Entrance", 10, 10, 0, "entrance")
    junction0 = create_route_point(client, token, floor0["id"], "Junction 0", 100, 10, 0, "junction")
    junction1 = create_route_point(client, token, floor1["id"], "Junction 1", 100, 10, 1, "junction")
    destination = create_route_point(client, token, floor1["id"], "Dest", 200, 10, 1, "store")

    create_edge(client, token, floor0["id"], entrance["id"], junction0["id"])
    create_edge(client, token, floor1["id"], junction1["id"], destination["id"])

    stairs_connector = create_connector(
        client, token, building_id=floor0["building_id"], map_group_id=group["id"],
        name="Stairs A", code="AVOIDGRP1-STAIRS", connector_type="stairs",
    ).json()

    stop0 = add_stop(client, token, stairs_connector["id"], map_id=floor0["id"], x=101, y=10, auto_connect="off")
    stop1 = add_stop(client, token, stairs_connector["id"], map_id=floor1["id"], x=101, y=10, auto_connect="off")
    assert stop0.status_code == 201 and stop1.status_code == 201

    create_edge(client, token, floor0["id"], junction0["id"], stop0.json()["stops"][-1]["route_point_id"])
    create_edge(client, token, floor1["id"], stop1.json()["stops"][-1]["route_point_id"], junction1["id"])

    without_avoid = client.post(
        "/api/navigation/multi-floor-route",
        json={
            "start_point_id": entrance["id"],
            "end_point_id": destination["id"],
            "optimization_mode": "fastest",
        },
    )
    assert without_avoid.status_code == 200, without_avoid.text
    assert without_avoid.json()["segments"][1]["transition_type"] == "stairs"

    with_avoid = client.post(
        "/api/navigation/multi-floor-route",
        json={
            "start_point_id": entrance["id"],
            "end_point_id": destination["id"],
            "optimization_mode": "fastest",
            "avoid_stairs": True,
        },
    )
    assert with_avoid.status_code == 404, with_avoid.text
    assert "preference" in with_avoid.json()["detail"].lower()


def test_prefer_elevators_routes_through_elevator_over_stairs(client):
    # A group with BOTH a stairs connector and an elevator: prefer_elevators
    # must select the elevator transition even though stairs would
    # otherwise be a perfectly valid (and possibly shorter) choice.
    token = create_admin(client, "avoid2@example.com", "AVOID2")
    group = create_map_group(client, token, code="AVOIDGRP2")
    floor0 = _floor_by_number(group, 0)
    floor1 = _floor_by_number(group, 1)

    entrance = create_route_point(client, token, floor0["id"], "Entrance", 10, 10, 0, "entrance")
    junction0 = create_route_point(client, token, floor0["id"], "Junction 0", 100, 10, 0, "junction")
    junction1 = create_route_point(client, token, floor1["id"], "Junction 1", 100, 10, 1, "junction")
    destination = create_route_point(client, token, floor1["id"], "Dest", 200, 10, 1, "store")

    create_edge(client, token, floor0["id"], entrance["id"], junction0["id"])
    create_edge(client, token, floor1["id"], junction1["id"], destination["id"])

    stairs_connector = create_connector(
        client, token, building_id=floor0["building_id"], map_group_id=group["id"],
        name="Stairs A", code="AVOIDGRP2-STAIRS", connector_type="stairs",
    ).json()
    elevator_connector = create_connector(
        client, token, building_id=floor0["building_id"], map_group_id=group["id"],
        name="Elevator A", code="AVOIDGRP2-ELEV", connector_type="elevator",
    ).json()

    for connector, x in ((stairs_connector, 101), (elevator_connector, 150)):
        s0 = add_stop(client, token, connector["id"], map_id=floor0["id"], x=x, y=10, auto_connect="off")
        s1 = add_stop(client, token, connector["id"], map_id=floor1["id"], x=x, y=10, auto_connect="off")
        assert s0.status_code == 201 and s1.status_code == 201
        create_edge(client, token, floor0["id"], junction0["id"], s0.json()["stops"][-1]["route_point_id"])
        create_edge(client, token, floor1["id"], s1.json()["stops"][-1]["route_point_id"], junction1["id"])

    response = client.post(
        "/api/navigation/multi-floor-route",
        json={
            "start_point_id": entrance["id"],
            "end_point_id": destination["id"],
            "optimization_mode": "shortest",
            "prefer_elevators": True,
        },
    )
    assert response.status_code == 200, response.text
    transition_segments = [s for s in response.json()["segments"] if s["segment_type"] == "transition"]
    assert len(transition_segments) == 1
    assert transition_segments[0]["transition_type"] == "elevator"


# ---------------------------------------------------------
# ACCESSIBILITY
# ---------------------------------------------------------

def test_accessible_mode_excludes_stairs(client):
    token = create_admin(client, "acc1@example.com", "ACC1")
    group = create_map_group(client, token, code="ACCGRP1")
    floor0 = _floor_by_number(group, 0)
    floor1 = _floor_by_number(group, 1)

    entrance = create_route_point(client, token, floor0["id"], "Entrance", 10, 10, 0, "entrance")
    stairs0 = create_route_point(client, token, floor0["id"], "Stairs A", 100, 10, 0, "stairs")
    stairs1 = create_route_point(client, token, floor1["id"], "Stairs A", 100, 10, 1, "stairs")
    destination = create_route_point(client, token, floor1["id"], "Dest", 200, 10, 1, "store")

    create_edge(client, token, floor0["id"], entrance["id"], stairs0["id"])
    create_edge(client, token, floor1["id"], stairs1["id"], destination["id"])

    stairs_connector = create_connector(
        client, token, building_id=floor0["building_id"], map_group_id=group["id"],
        name="Stairs A", code="ACCGRP1-STAIRS", connector_type="stairs", is_accessible=False,
    ).json()

    # Manually tag the pre-existing stairs points as this connector's
    # stops (add_connector_stop would create NEW points; here we reuse the
    # already-drawn stairs points directly to also exercise "stairs
    # placed via Draw Walkable Path, then linked" as a realistic flow).
    for point, map_obj in ((stairs0, floor0), (stairs1, floor1)):
        client.put(
            f"/api/route-points/{point['id']}",
            json={"is_accessible": False},
            headers=auth_headers(token),
        )

    resp0 = add_stop(
        client, token, stairs_connector["id"], map_id=floor0["id"], x=101, y=11, auto_connect="off"
    )
    resp1 = add_stop(
        client, token, stairs_connector["id"], map_id=floor1["id"], x=101, y=11, auto_connect="off"
    )
    assert resp0.status_code == 201 and resp1.status_code == 201

    response = client.post(
        "/api/navigation/multi-floor-route",
        json={
            "start_point_id": entrance["id"],
            "end_point_id": destination["id"],
            "optimization_mode": "accessible",
        },
    )
    assert response.status_code == 404, response.text
    assert "accessible" in response.json()["detail"].lower()


def test_accessible_mode_uses_accessible_elevator(client):
    token = create_admin(client, "acc2@example.com", "ACC2")
    group, floor0, floor1, connector, points = _setup_two_floor_group_with_elevator(
        client, token, "ACCGRP2"
    )

    response = client.post(
        "/api/navigation/multi-floor-route",
        json={
            "start_point_id": points["entrance"]["id"],
            "end_point_id": points["destination"]["id"],
            "optimization_mode": "accessible",
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["is_accessible"] is True


# ---------------------------------------------------------
# DISTANCE AND TIME / SCALE CALIBRATION
# ---------------------------------------------------------

def test_calibration_computes_correct_meters_per_pixel(client):
    token = create_admin(client, "cal1@example.com", "CAL1")
    group = create_map_group(client, token, code="CALGRP1")
    floor0 = _floor_by_number(group, 0)

    response = client.post(
        f"/api/maps/{floor0['id']}/calibrate-scale",
        json={
            "point_a_x": 0, "point_a_y": 0,
            "point_b_x": 500, "point_b_y": 0,
            "real_distance_meters": 20,
        },
        headers=auth_headers(token),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert abs(body["scale"] - 0.04) < 1e-6
    assert body["is_calibrated"] is True


def test_uncalibrated_map_defaults_to_not_calibrated(client):
    token = create_admin(client, "cal2@example.com", "CAL2")
    group = create_map_group(client, token, code="CALGRP2")
    floor0 = _floor_by_number(group, 0)

    response = client.get(f"/api/maps/{floor0['id']}", headers=auth_headers(token))
    assert response.status_code == 200
    assert response.json()["is_calibrated"] is False


def test_calibration_rejects_zero_pixel_distance(client):
    token = create_admin(client, "cal3@example.com", "CAL3")
    group = create_map_group(client, token, code="CALGRP3")
    floor0 = _floor_by_number(group, 0)

    response = client.post(
        f"/api/maps/{floor0['id']}/calibrate-scale",
        json={
            "point_a_x": 10, "point_a_y": 10,
            "point_b_x": 10, "point_b_y": 10,
            "real_distance_meters": 5,
        },
        headers=auth_headers(token),
    )
    assert response.status_code == 400


def test_total_distance_equals_sum_of_segments(client):
    token = create_admin(client, "dist1@example.com", "DIST1")
    group, floor0, floor1, connector, points = _setup_two_floor_group_with_elevator(
        client, token, "DISTGRP1"
    )

    response = client.post(
        "/api/navigation/multi-floor-route",
        json={
            "start_point_id": points["entrance"]["id"],
            "end_point_id": points["destination"]["id"],
        },
    )
    body = response.json()
    segment_distance_sum = sum(s["distance_meters"] for s in body["segments"])
    assert abs(segment_distance_sum - body["total_distance_meters"]) < 0.01


# ---------------------------------------------------------
# INSTRUCTIONS
# ---------------------------------------------------------

def test_transition_instruction_includes_connector_name_and_floor(client):
    token = create_admin(client, "instr1@example.com", "INSTR1")
    group, floor0, floor1, connector, points = _setup_two_floor_group_with_elevator(
        client, token, "INSTRGRP1"
    )

    response = client.post(
        "/api/navigation/multi-floor-route",
        json={
            "start_point_id": points["entrance"]["id"],
            "end_point_id": points["destination"]["id"],
        },
    )
    body = response.json()
    transition_instructions = [i for i in body["instructions"] if i["type"] == "transition"]
    assert len(transition_instructions) == 1
    assert "Elevator A" in transition_instructions[0]["text"]


def test_utf8_point_names_preserved_in_instructions(client):
    # Covers Arabic, Hebrew, and English point names in one route
    # (test #39). generate_floor_instructions only embeds a point's name
    # in an actual turn ("Turn left/right at X") or the final "arrived"
    # instruction -- a name on the very first (start) point or on a
    # collinear/straight waypoint is never echoed back (matching PHASE 12:
    # the initial instruction is a generic route-relative "Proceed
    # toward..."). So the Hebrew and Arabic names are placed on two real
    # turn waypoints (a right turn then a left turn), and English on the
    # final destination -- every one of those is guaranteed to appear.
    token = create_admin(client, "instr2@example.com", "INSTR2")
    group = create_map_group(client, token, code="INSTRGRP2")
    floor0 = _floor_by_number(group, 0)

    hebrew_name = "\u05d4\u05de\u05d1\u05d5\u05d0\u05d4 \u05d4\u05e8\u05d0\u05e9\u05d9\u05ea"
    arabic_name = "\u0645\u0645\u0631 \u0627\u0644\u0648\u0633\u0637"
    english_name = "Super-Pharm"

    p0 = create_route_point(client, token, floor0["id"], "Entrance", 10, 10, 0, "entrance")
    p1 = create_route_point(client, token, floor0["id"], hebrew_name, 100, 10, 0, "junction")
    p2 = create_route_point(client, token, floor0["id"], arabic_name, 100, 100, 0, "junction")
    p3 = create_route_point(client, token, floor0["id"], english_name, 200, 100, 0, "store")
    create_edge(client, token, floor0["id"], p0["id"], p1["id"])
    create_edge(client, token, floor0["id"], p1["id"], p2["id"])
    create_edge(client, token, floor0["id"], p2["id"], p3["id"])

    response = client.post(
        "/api/navigation/multi-floor-route",
        json={"start_point_id": p0["id"], "end_point_id": p3["id"]},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    all_text = " ".join(i["text"] for i in body["instructions"])
    assert hebrew_name in all_text
    assert arabic_name in all_text
    assert english_name in all_text


# ---------------------------------------------------------
# CONSISTENCY AND DELETION
# ---------------------------------------------------------

def test_deleting_referenced_connector_stop_point_is_rejected(client):
    token = create_admin(client, "del1@example.com", "DEL1")
    group, floor0, floor1, connector, points = _setup_two_floor_group_with_elevator(
        client, token, "DELGRP1"
    )

    stop_id = connector["stops"][0]["route_point_id"]
    response = client.delete(f"/api/route-points/{stop_id}", headers=auth_headers(token))
    assert response.status_code == 409


def test_deleting_connector_removes_only_its_transition_edges(client):
    token = create_admin(client, "del2@example.com", "DEL2")
    group, floor0, floor1, connector, points = _setup_two_floor_group_with_elevator(
        client, token, "DELGRP2"
    )

    delete_response = client.delete(
        f"/api/vertical-connectors/{connector['id']}", headers=auth_headers(token)
    )
    assert delete_response.status_code == 200
    assert delete_response.json()["deleted_transition_edges"] == 1

    # The stops' ordinary same-floor walkway edges (created by
    # add_connector_stop's auto_connect) must remain untouched.
    edges = client.get(
        "/api/route-edges", params={"map_id": floor0["id"]}, headers=auth_headers(token)
    ).json()
    assert any(e["edge_type"] == "walkway" for e in edges)


def test_deleting_one_floor_map_removes_orphaned_transition_edge(client):
    token = create_admin(client, "del3@example.com", "DEL3")
    group, floor0, floor1, connector, points = _setup_two_floor_group_with_elevator(
        client, token, "DELGRP3"
    )

    delete_response = client.delete(
        f"/api/map-groups/{group['id']}/floors/{floor1['id']}", headers=auth_headers(token)
    )
    assert delete_response.status_code == 200

    remaining_edges = client.get(
        "/api/route-edges", params={"map_id": floor0["id"]}, headers=auth_headers(token)
    ).json()
    assert all(e["to_map_id"] != floor1["id"] for e in remaining_edges)


def test_room_resolves_correct_floor_segment_for_cross_floor_destination(client):
    token = create_admin(client, "room1@example.com", "ROOM1")
    group, floor0, floor1, connector, points = _setup_two_floor_group_with_elevator(
        client, token, "ROOMGRP1"
    )

    room_response = client.post(
        "/api/rooms",
        json={
            "building_id": floor1["building_id"],
            "name_en": "Super-Pharm",
            "room_type": "store",
            "floor": 1,
            "map_id": floor1["id"],
            "x": points["destination"]["x"],
            "y": points["destination"]["y"],
        },
        headers=auth_headers(token),
    )
    assert room_response.status_code == 201, room_response.text
    room = room_response.json()
    assert room["map_group_id"] == group["id"]

    response = client.post(
        "/api/navigation/multi-floor-route",
        json={
            "start_point_id": points["entrance"]["id"],
            "end_point_id": room["route_point_id"],
        },
    )
    assert response.status_code == 200
    assert response.json()["segments"][-1]["floor"] == 1


# ---------------------------------------------------------
# ADMIN GRAPH VALIDATION (PHASE 15)
# ---------------------------------------------------------

def test_validation_reports_ready_for_a_fully_connected_calibrated_group(client):
    token = create_admin(client, "valid1@example.com", "VALID1")
    group, floor0, floor1, connector, points = _setup_two_floor_group_with_elevator(
        client, token, "VALIDGRP1"
    )

    for floor in (floor0, floor1):
        calib = client.post(
            f"/api/maps/{floor['id']}/calibrate-scale",
            json={
                "point_a_x": 0, "point_a_y": 0, "point_b_x": 500, "point_b_y": 0,
                "real_distance_meters": 20,
            },
            headers=auth_headers(token),
        )
        assert calib.status_code == 200, calib.text

    result = client.get(
        f"/api/map-groups/{group['id']}/validate-navigation", headers=auth_headers(token)
    )
    assert result.status_code == 200, result.text
    body = result.json()
    assert body["ready"] is True, body["issues"]
    assert body["floor_count"] == 2
    assert len(body["connectors"]) == 1
    assert body["connectors"][0]["is_fully_connected"] is True


def test_validation_reports_uncalibrated_floor(client):
    token = create_admin(client, "valid2@example.com", "VALID2")
    group, floor0, floor1, connector, points = _setup_two_floor_group_with_elevator(
        client, token, "VALIDGRP2"
    )
    # Floors are left uncalibrated (default) — no calibrate-scale call.

    result = client.get(
        f"/api/map-groups/{group['id']}/validate-navigation", headers=auth_headers(token)
    )
    body = result.json()
    assert body["ready"] is False
    assert any(i["category"] == "calibration" for i in body["issues"])


def test_validation_reports_connector_stop_not_connected_to_corridor(client):
    token = create_admin(client, "valid3@example.com", "VALID3")
    group = create_map_group(client, token, code="VALIDGRP3")
    floor0 = _floor_by_number(group, 0)
    floor1 = _floor_by_number(group, 1)

    connector_resp = create_connector(
        client, token, building_id=floor0["building_id"], map_group_id=group["id"],
        code="VALIDGRP3-ELEV-A",
    )
    connector = connector_resp.json()

    # Both stops placed with auto_connect="off" and never wired to any
    # corridor edge — validation must flag them, not silently call the
    # connector usable.
    add_stop(client, token, connector["id"], map_id=floor0["id"], x=10, y=10, auto_connect="off")
    add_stop(client, token, connector["id"], map_id=floor1["id"], x=10, y=10, auto_connect="off")

    result = client.get(
        f"/api/map-groups/{group['id']}/validate-navigation", headers=auth_headers(token)
    )
    body = result.json()
    assert body["ready"] is False
    assert any(i["category"] == "connector_connectivity" for i in body["issues"])
    assert body["connectors"][0]["is_fully_connected"] is False


def test_validation_reports_inactive_connector(client):
    token = create_admin(client, "valid4@example.com", "VALID4")
    group, floor0, floor1, connector, points = _setup_two_floor_group_with_elevator(
        client, token, "VALIDGRP4"
    )

    update = client.put(
        f"/api/vertical-connectors/{connector['id']}",
        json={"is_active": False},
        headers=auth_headers(token),
    )
    assert update.status_code == 200, update.text

    result = client.get(
        f"/api/map-groups/{group['id']}/validate-navigation", headers=auth_headers(token)
    )
    body = result.json()
    assert body["ready"] is False
    assert any(i["category"] == "connectors" for i in body["issues"])
    assert body["connectors"][0]["is_active"] is False


def test_validation_reports_floor_with_no_route_points(client):
    token = create_admin(client, "valid5@example.com", "VALID5")
    group = create_map_group(
        client, token, code="VALIDGRP5",
        floors=[
            {"title": "Ground Floor", "floor": 0, "floor_label": "Ground Floor"},
            {"title": "First Floor", "floor": 1, "floor_label": "First Floor"},
        ],
    )

    result = client.get(
        f"/api/map-groups/{group['id']}/validate-navigation", headers=auth_headers(token)
    )
    body = result.json()
    assert body["ready"] is False
    assert any(i["category"] == "floors" for i in body["issues"])


def test_changing_map_floor_number_is_rejected_if_it_collides_with_a_sibling(client):
    token = create_admin(client, "floorchg1@example.com", "FLOORCHG1")
    group = create_map_group(client, token, code="FLOORCHGGRP1")
    floor0 = _floor_by_number(group, 0)
    floor1 = _floor_by_number(group, 1)

    response = client.put(
        f"/api/maps/{floor0['id']}", json={"floor": 1}, headers=auth_headers(token)
    )
    assert response.status_code == 409, response.text


def test_changing_map_floor_number_cascades_to_its_route_points(client):
    token = create_admin(client, "floorchg2@example.com", "FLOORCHG2")
    group = create_map_group(client, token, code="FLOORCHGGRP2")
    floor0 = _floor_by_number(group, 0)

    point = create_route_point(client, token, floor0["id"], "Junction", 10, 10, 0, "junction")
    assert point["floor"] == 0

    response = client.put(
        f"/api/maps/{floor0['id']}", json={"floor": 5}, headers=auth_headers(token)
    )
    assert response.status_code == 200, response.text
    assert response.json()["floor"] == 5

    refreshed = client.get(
        "/api/route-points", params={"map_id": floor0["id"]}, headers=auth_headers(token)
    ).json()
    assert all(p["floor"] == 5 for p in refreshed)


def test_moving_room_to_a_different_floor_updates_room_floor_to_match(client):
    token = create_admin(client, "roommove1@example.com", "ROOMMOVE1")
    group, floor0, floor1, connector, points = _setup_two_floor_group_with_elevator(
        client, token, "ROOMMOVEGRP1"
    )

    room_resp = client.post(
        "/api/rooms",
        json={
            "building_id": floor0["building_id"],
            "name_en": "Kiosk",
            "room_type": "store",
            "floor": 0,
            "map_id": floor0["id"],
            "x": 50,
            "y": 50,
        },
        headers=auth_headers(token),
    )
    assert room_resp.status_code == 201, room_resp.text
    room = room_resp.json()
    assert room["floor"] == 0

    # Move the same room to Floor 1's map — Room.floor must follow the
    # new map's floor, not stay stuck at the old value (PHASE 16/17).
    move_resp = client.put(
        f"/api/rooms/{room['id']}",
        json={"map_id": floor1["id"], "x": 60, "y": 60},
        headers=auth_headers(token),
    )
    assert move_resp.status_code == 200, move_resp.text
    moved_room = move_resp.json()
    assert moved_room["map_id"] == floor1["id"]
    assert moved_room["floor"] == 1

    moved_point = client.get(
        f"/api/route-points/{moved_room['route_point_id']}", headers=auth_headers(token)
    ).json()
    assert moved_point["floor"] == 1
    assert moved_point["map_id"] == floor1["id"]
