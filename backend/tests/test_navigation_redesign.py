"""
Backend tests for the "Fix three connected end-user navigation issues"
task:
  1. Room/Store RoutePoints must never be used as an intermediate transit
     node (only as start or destination) — logic/multi_floor_routing.py's
     _suppress_intermediate_destination_nodes + RoomTransitBlockedError.
  2. Turn-by-turn instructions must only ever describe the ACTUAL returned
     route (landmark restriction, turn-angle thresholds, consecutive-leg
     grouping, generic corridor phrasing) — logic/instruction_generator.py.
  3. A single-choice vertical-transport preference
     (any/elevator/stairs) is a per-request graph-edge filter applied
     before the existing Dijkstra call — routes/navigation_routes.py.

Reuses the same admin/map-group/route-point/connector helper functions
already established by tests/test_multi_floor_navigation.py rather than
duplicating them, per this repo's existing cross-file test convention
(see tests/test_destination_placement.py, tests/test_map_floor_edit.py,
etc., which all import shared helpers from tests.test_api_integration the
same way).

Run with: pytest backend/tests/test_navigation_redesign.py -v
"""

import pytest
from beanie import PydanticObjectId

from logic.instruction_generator import (
    classify_turn,
    resolve_display_name,
    resolve_localized_display_name,
)
from logic.multi_floor_routing import calculate_multi_floor_route

from tests.test_multi_floor_navigation import (
    auth_headers,
    create_admin,
    create_map_group,
    create_route_point,
    create_edge,
    create_connector,
    add_stop,
    _floor_by_number,
)


# ---------------------------------------------------------
# SECTION 3 — ROOM/STORE NODES MUST NOT BE INTERMEDIATE TRANSIT
# ---------------------------------------------------------

def test_room_valid_as_destination(client):
    # A Room point used as the route's END point must work exactly like
    # any other destination-capable point.
    token = create_admin(client, "roomdest1@example.com", "ROOMDEST1")
    group = create_map_group(client, token, code="ROOMDESTGRP1")
    floor0 = _floor_by_number(group, 0)

    entrance = create_route_point(client, token, floor0["id"], "Entrance", 10, 10, 0, "entrance")
    room = create_route_point(client, token, floor0["id"], "Women's Shower", 100, 10, 0, "room")
    create_edge(client, token, floor0["id"], entrance["id"], room["id"])

    response = client.post(
        "/api/navigation/multi-floor-route",
        json={"start_point_id": entrance["id"], "end_point_id": room["id"]},
    )
    assert response.status_code == 200, response.text
    assert response.json()["segments"][-1]["point_ids"][-1] == room["id"]


def test_store_valid_as_destination(client):
    token = create_admin(client, "storedest1@example.com", "STOREDEST1")
    group = create_map_group(client, token, code="STOREDESTGRP1")
    floor0 = _floor_by_number(group, 0)

    entrance = create_route_point(client, token, floor0["id"], "Entrance", 10, 10, 0, "entrance")
    store = create_route_point(client, token, floor0["id"], "Super-Pharm", 100, 10, 0, "store")
    create_edge(client, token, floor0["id"], entrance["id"], store["id"])

    response = client.post(
        "/api/navigation/multi-floor-route",
        json={"start_point_id": entrance["id"], "end_point_id": store["id"]},
    )
    assert response.status_code == 200, response.text
    assert response.json()["segments"][-1]["point_ids"][-1] == store["id"]


def test_room_valid_as_start_point(client):
    # Mirrors how QR-code resolution hands the backend a start_point_id
    # that may itself be a Room (e.g. scanning a code placed inside a
    # room) — QR resolution logic itself is untouched, this only confirms
    # the multi-floor route calculation accepts a room/store point as the
    # START without issue.
    token = create_admin(client, "roomstart1@example.com", "ROOMSTART1")
    group = create_map_group(client, token, code="ROOMSTARTGRP1")
    floor0 = _floor_by_number(group, 0)

    room = create_route_point(client, token, floor0["id"], "Women's Shower", 10, 10, 0, "room")
    destination = create_route_point(client, token, floor0["id"], "Exit", 100, 10, 0, "exit")
    create_edge(client, token, floor0["id"], room["id"], destination["id"])

    response = client.post(
        "/api/navigation/multi-floor-route",
        json={"start_point_id": room["id"], "end_point_id": destination["id"]},
    )
    assert response.status_code == 200, response.text
    assert response.json()["segments"][0]["point_ids"][0] == room["id"]


def test_unrelated_room_not_used_as_intermediate_when_an_alternate_path_exists(client):
    # Corridor A -- Women's Shower -- Corridor B (a "shortcut" through the
    # room) PLUS a direct Corridor A -- Corridor B walkway edge (slightly
    # longer, but the only edge type a route is allowed to use). The
    # route from Corridor A to Corridor B must use the direct walkway,
    # never the shortcut through the unrelated Room.
    token = create_admin(client, "roomtransit1@example.com", "ROOMTRANSIT1")
    group = create_map_group(client, token, code="ROOMTRANSITGRP1")
    floor0 = _floor_by_number(group, 0)

    corridor_a = create_route_point(client, token, floor0["id"], "Corridor A", 10, 10, 0, "junction")
    room = create_route_point(client, token, floor0["id"], "Women's Shower", 100, 10, 0, "room")
    corridor_b = create_route_point(client, token, floor0["id"], "Corridor B", 190, 10, 0, "junction")

    create_edge(client, token, floor0["id"], corridor_a["id"], room["id"])
    create_edge(client, token, floor0["id"], room["id"], corridor_b["id"])
    # The legitimate, longer, room-free alternate path.
    create_edge(client, token, floor0["id"], corridor_a["id"], corridor_b["id"])

    response = client.post(
        "/api/navigation/multi-floor-route",
        json={"start_point_id": corridor_a["id"], "end_point_id": corridor_b["id"]},
    )
    assert response.status_code == 200, response.text
    point_ids = response.json()["segments"][0]["point_ids"]
    assert room["id"] not in point_ids

    all_instruction_text = " ".join(i["text"] for i in response.json()["instructions"])
    assert "Women's Shower" not in all_instruction_text


def test_room_transit_blocked_returns_clear_error_when_it_is_the_only_bridge(client):
    # Corridor A -- Women's Shower -- Corridor B is the ONLY path between
    # the two corridor sections (no alternate). Section 3: "If the graph
    # becomes disconnected because a Room point was incorrectly used as
    # the only bridge... return a clear admin/debug indication rather
    # than silently routing through the Room."
    token = create_admin(client, "roomtransit2@example.com", "ROOMTRANSIT2")
    group = create_map_group(client, token, code="ROOMTRANSITGRP2")
    floor0 = _floor_by_number(group, 0)

    corridor_a = create_route_point(client, token, floor0["id"], "Corridor A", 10, 10, 0, "junction")
    room = create_route_point(client, token, floor0["id"], "Women's Shower", 100, 10, 0, "room")
    corridor_b = create_route_point(client, token, floor0["id"], "Corridor B", 190, 10, 0, "junction")

    create_edge(client, token, floor0["id"], corridor_a["id"], room["id"])
    create_edge(client, token, floor0["id"], room["id"], corridor_b["id"])
    # No direct corridor_a <-> corridor_b edge this time.

    response = client.post(
        "/api/navigation/multi-floor-route",
        json={"start_point_id": corridor_a["id"], "end_point_id": corridor_b["id"]},
    )
    # Never silently routes through the room (200 with the room in the
    # path) and never an indistinguishable generic "no route" — a
    # dedicated 409 that names the blocking point.
    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert room["id"] in detail


# ---------------------------------------------------------
# SECTION 5/6 — INSTRUCTION CORRECTNESS
# ---------------------------------------------------------

def test_consecutive_straight_legs_are_grouped_into_one_instruction(client):
    token = create_admin(client, "group1@example.com", "GROUP1")
    group = create_map_group(client, token, code="GROUPGRP1")
    floor0 = _floor_by_number(group, 0)

    # Five collinear points along a straight corridor — four legs, all
    # "straight" turn classification, must collapse into ONE instruction.
    p0 = create_route_point(client, token, floor0["id"], "Entrance", 0, 0, 0, "entrance")
    p1 = create_route_point(client, token, floor0["id"], "P1", 50, 0, 0, "junction")
    p2 = create_route_point(client, token, floor0["id"], "P2", 100, 0, 0, "junction")
    p3 = create_route_point(client, token, floor0["id"], "P3", 150, 0, 0, "junction")
    p4 = create_route_point(client, token, floor0["id"], "Dest", 200, 0, 0, "store")
    for a, b in ((p0, p1), (p1, p2), (p2, p3), (p3, p4)):
        create_edge(client, token, floor0["id"], a["id"], b["id"])

    response = client.post(
        "/api/navigation/multi-floor-route",
        json={"start_point_id": p0["id"], "end_point_id": p4["id"]},
    )
    assert response.status_code == 200, response.text
    body = response.json()

    straight_instructions = [i for i in body["instructions"] if i["type"] == "straight"]
    assert len(straight_instructions) == 1, body["instructions"]
    # The intermediate junction names must never leak into a merged,
    # generic corridor instruction (Section 6).
    assert "P1" not in straight_instructions[0]["text"]
    assert "P2" not in straight_instructions[0]["text"]
    assert "P3" not in straight_instructions[0]["text"]


def test_a_genuine_turn_breaks_the_grouping(client):
    token = create_admin(client, "group2@example.com", "GROUP2")
    group = create_map_group(client, token, code="GROUPGRP2")
    floor0 = _floor_by_number(group, 0)

    # Straight, straight, then a sharp 90-degree right turn, then straight
    # again — must produce: one merged "straight" group, one "right" turn,
    # then a second, SEPARATE "straight" instruction (never merged across
    # the turn).
    p0 = create_route_point(client, token, floor0["id"], "Entrance", 0, 0, 0, "entrance")
    p1 = create_route_point(client, token, floor0["id"], "P1", 50, 0, 0, "junction")
    p2 = create_route_point(client, token, floor0["id"], "Corner", 100, 0, 0, "junction")
    p3 = create_route_point(client, token, floor0["id"], "P3", 100, 50, 0, "junction")
    p4 = create_route_point(client, token, floor0["id"], "Dest", 100, 100, 0, "store")
    for a, b in ((p0, p1), (p1, p2), (p2, p3), (p3, p4)):
        create_edge(client, token, floor0["id"], a["id"], b["id"])

    response = client.post(
        "/api/navigation/multi-floor-route",
        json={"start_point_id": p0["id"], "end_point_id": p4["id"]},
    )
    assert response.status_code == 200, response.text
    body = response.json()

    types = [i["type"] for i in body["instructions"]]
    # start, straight (merged), right, straight, arrive
    assert types == ["start", "straight", "right", "straight", "arrive"], types


def test_generic_straight_instruction_exact_text_english(client):
    token = create_admin(client, "text1@example.com", "TEXT1")
    group = create_map_group(client, token, code="TEXTGRP1")
    floor0 = _floor_by_number(group, 0)

    # generate_floor_instructions' per-vertex leg distance is measured
    # from the TURN VERTEX (p1) to the NEXT point (p2), not from the
    # route's start — so p1->p2 is set to exactly 100 px/m (uncalibrated
    # maps default Map.scale to 1.0, so pixels == meters here) to get a
    # clean, exact expected distance in the instruction text below.
    p0 = create_route_point(client, token, floor0["id"], "Entrance", 0, 0, 0, "entrance")
    p1 = create_route_point(client, token, floor0["id"], "P1", 50, 0, 0, "junction")
    p2 = create_route_point(client, token, floor0["id"], "Dest", 150, 0, 0, "store")
    create_edge(client, token, floor0["id"], p0["id"], p1["id"])
    create_edge(client, token, floor0["id"], p1["id"], p2["id"])

    response = client.post(
        "/api/navigation/multi-floor-route",
        json={"start_point_id": p0["id"], "end_point_id": p2["id"], "lang": "en"},
    )
    body = response.json()
    straight = next(i for i in body["instructions"] if i["type"] == "straight")
    assert straight["text"] == "Continue straight through the corridor for 100 m."


def test_generic_straight_instruction_exact_text_arabic(client):
    token = create_admin(client, "text2@example.com", "TEXT2")
    group = create_map_group(client, token, code="TEXTGRP2")
    floor0 = _floor_by_number(group, 0)

    # generate_floor_instructions' per-vertex leg distance is measured
    # from the TURN VERTEX (p1) to the NEXT point (p2), not from the
    # route's start — so p1->p2 is set to exactly 100 px/m (uncalibrated
    # maps default Map.scale to 1.0, so pixels == meters here) to get a
    # clean, exact expected distance in the instruction text below.
    p0 = create_route_point(client, token, floor0["id"], "Entrance", 0, 0, 0, "entrance")
    p1 = create_route_point(client, token, floor0["id"], "P1", 50, 0, 0, "junction")
    p2 = create_route_point(client, token, floor0["id"], "Dest", 150, 0, 0, "store")
    create_edge(client, token, floor0["id"], p0["id"], p1["id"])
    create_edge(client, token, floor0["id"], p1["id"], p2["id"])

    response = client.post(
        "/api/navigation/multi-floor-route",
        json={"start_point_id": p0["id"], "end_point_id": p2["id"], "lang": "ar"},
    )
    body = response.json()
    straight = next(i for i in body["instructions"] if i["type"] == "straight")
    assert straight["text"] == "تابعي مستقيمًا عبر الممر لمسافة 100 م."


def test_generic_straight_instruction_exact_text_hebrew(client):
    token = create_admin(client, "text3@example.com", "TEXT3")
    group = create_map_group(client, token, code="TEXTGRP3")
    floor0 = _floor_by_number(group, 0)

    # generate_floor_instructions' per-vertex leg distance is measured
    # from the TURN VERTEX (p1) to the NEXT point (p2), not from the
    # route's start — so p1->p2 is set to exactly 100 px/m (uncalibrated
    # maps default Map.scale to 1.0, so pixels == meters here) to get a
    # clean, exact expected distance in the instruction text below.
    p0 = create_route_point(client, token, floor0["id"], "Entrance", 0, 0, 0, "entrance")
    p1 = create_route_point(client, token, floor0["id"], "P1", 50, 0, 0, "junction")
    p2 = create_route_point(client, token, floor0["id"], "Dest", 150, 0, 0, "store")
    create_edge(client, token, floor0["id"], p0["id"], p1["id"])
    create_edge(client, token, floor0["id"], p1["id"], p2["id"])

    response = client.post(
        "/api/navigation/multi-floor-route",
        json={"start_point_id": p0["id"], "end_point_id": p2["id"], "lang": "he"},
    )
    body = response.json()
    straight = next(i for i in body["instructions"] if i["type"] == "straight")
    assert straight["text"] == "המשך ישר במסדרון למרחק 100 מ׳."


def test_turn_angle_thresholds_classify_correctly():
    # Direct unit test of the pure classifier (Section 5's suggested
    # defaults: <25 deg straight; 25-<50 slight; >=50 turn). incoming/
    # outgoing are (dx, dy) vectors; classify_turn returns (type, angle).
    # Straight ahead: no direction change at all.
    assert classify_turn((1, 0), (1, 0))[0] == "straight"
    # ~20 degrees — still within the "straight" tolerance.
    assert classify_turn((1, 0), (1, 0.36))[0] == "straight"
    # 90 degrees — a genuine turn, not slight.
    turn_type, angle = classify_turn((1, 0), (0, 1))
    assert turn_type in ("left", "right")
    assert angle >= 50
    # ~35 degrees — within the slight-turn band.
    slight_type, slight_angle = classify_turn((1, 0), (1, 0.70))
    assert slight_type in ("slight_left", "slight_right")
    assert 25 <= slight_angle < 50


def test_instruction_never_contains_a_raw_technical_point_name(client):
    # A point created with is_auto_generated=True and a technical-looking
    # name must never have that raw name echoed into instruction text —
    # resolve_localized_display_name/resolve_display_name already
    # suppress is_auto_generated names; this exercises that end-to-end
    # through the real route + instruction pipeline (Section 6: "never
    # expose... technical generated names").
    token = create_admin(client, "tech1@example.com", "TECH1")
    group = create_map_group(client, token, code="TECHGRP1")
    floor0 = _floor_by_number(group, 0)

    p0 = create_route_point(client, token, floor0["id"], "Entrance", 0, 0, 0, "entrance")

    # p1 is placed as a REAL turn vertex (not collinear with p0/p2) so
    # that, if the technical name were NOT suppressed, it would actually
    # show up in a "Turn ... at {name}" instruction — a straight-line
    # point would pass this test even with a broken suppression, since
    # straight instructions never interpolate a name at all.
    technical_point = client.post(
        "/api/route-points",
        json={
            "map_id": floor0["id"], "name": "room_point_33", "x": 50, "y": 0,
            "floor": 0, "point_type": "junction", "is_auto_generated": True,
        },
        headers=auth_headers(token),
    )
    assert technical_point.status_code == 201, technical_point.text
    p1 = technical_point.json()

    p2 = create_route_point(client, token, floor0["id"], "Dest", 50, 100, 0, "store")
    create_edge(client, token, floor0["id"], p0["id"], p1["id"])
    create_edge(client, token, floor0["id"], p1["id"], p2["id"])

    response = client.post(
        "/api/navigation/multi-floor-route",
        json={"start_point_id": p0["id"], "end_point_id": p2["id"]},
    )
    assert response.status_code == 200, response.text
    all_text = " ".join(i["text"] for i in response.json()["instructions"])
    assert "room_point_33" not in all_text


# ---------------------------------------------------------
# SECTION 7/8/9 — VERTICAL-TRANSPORT PREFERENCE
# ---------------------------------------------------------

def _build_stairs_only_group(client, token, code):
    group = create_map_group(client, token, code=code)
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
        name="Stairs A", code=f"{code}-STAIRS", connector_type="stairs",
    ).json()
    s0 = add_stop(client, token, stairs_connector["id"], map_id=floor0["id"], x=101, y=10, auto_connect="off")
    s1 = add_stop(client, token, stairs_connector["id"], map_id=floor1["id"], x=101, y=10, auto_connect="off")
    assert s0.status_code == 201 and s1.status_code == 201
    create_edge(client, token, floor0["id"], junction0["id"], s0.json()["stops"][-1]["route_point_id"])
    create_edge(client, token, floor1["id"], s1.json()["stops"][-1]["route_point_id"], junction1["id"])

    return group, floor0, floor1, entrance, destination


def _build_stairs_and_elevator_group(client, token, code):
    group = create_map_group(client, token, code=code)
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
        name="Stairs A", code=f"{code}-STAIRS", connector_type="stairs",
    ).json()
    elevator_connector = create_connector(
        client, token, building_id=floor0["building_id"], map_group_id=group["id"],
        name="Elevator A", code=f"{code}-ELEV", connector_type="elevator",
    ).json()

    for connector, x in ((stairs_connector, 101), (elevator_connector, 150)):
        s0 = add_stop(client, token, connector["id"], map_id=floor0["id"], x=x, y=10, auto_connect="off")
        s1 = add_stop(client, token, connector["id"], map_id=floor1["id"], x=x, y=10, auto_connect="off")
        assert s0.status_code == 201 and s1.status_code == 201
        create_edge(client, token, floor0["id"], junction0["id"], s0.json()["stops"][-1]["route_point_id"])
        create_edge(client, token, floor1["id"], s1.json()["stops"][-1]["route_point_id"], junction1["id"])

    return group, floor0, floor1, entrance, destination


def test_vertical_preference_any_allows_the_only_available_connector_type(client):
    token = create_admin(client, "vert1@example.com", "VERT1")
    _, _, _, entrance, destination = _build_stairs_only_group(client, token, "VERTGRP1")

    response = client.post(
        "/api/navigation/multi-floor-route",
        json={
            "start_point_id": entrance["id"], "end_point_id": destination["id"],
            "vertical_transport_preference": "any",
        },
    )
    assert response.status_code == 200, response.text
    transitions = [s for s in response.json()["segments"] if s["segment_type"] == "transition"]
    assert transitions[0]["transition_type"] == "stairs"


def test_vertical_preference_elevator_excludes_stairs_only_group(client):
    token = create_admin(client, "vert2@example.com", "VERT2")
    _, _, _, entrance, destination = _build_stairs_only_group(client, token, "VERTGRP2")

    response = client.post(
        "/api/navigation/multi-floor-route",
        json={
            "start_point_id": entrance["id"], "end_point_id": destination["id"],
            "vertical_transport_preference": "elevator",
        },
    )
    assert response.status_code == 404, response.text
    assert response.json()["detail"] == "No route using an elevator is available to this destination."


def test_vertical_preference_stairs_excludes_elevator_only_group(client):
    token = create_admin(client, "vert3@example.com", "VERT3")
    group = create_map_group(client, token, code="VERTGRP3")
    floor0 = _floor_by_number(group, 0)
    floor1 = _floor_by_number(group, 1)

    entrance = create_route_point(client, token, floor0["id"], "Entrance", 10, 10, 0, "entrance")
    junction0 = create_route_point(client, token, floor0["id"], "Junction 0", 100, 10, 0, "junction")
    junction1 = create_route_point(client, token, floor1["id"], "Junction 1", 100, 10, 1, "junction")
    destination = create_route_point(client, token, floor1["id"], "Dest", 200, 10, 1, "store")
    create_edge(client, token, floor0["id"], entrance["id"], junction0["id"])
    create_edge(client, token, floor1["id"], junction1["id"], destination["id"])

    elevator_connector = create_connector(
        client, token, building_id=floor0["building_id"], map_group_id=group["id"],
        name="Elevator A", code="VERTGRP3-ELEV", connector_type="elevator",
    ).json()
    s0 = add_stop(client, token, elevator_connector["id"], map_id=floor0["id"], x=101, y=10, auto_connect="off")
    s1 = add_stop(client, token, elevator_connector["id"], map_id=floor1["id"], x=101, y=10, auto_connect="off")
    assert s0.status_code == 201 and s1.status_code == 201
    create_edge(client, token, floor0["id"], junction0["id"], s0.json()["stops"][-1]["route_point_id"])
    create_edge(client, token, floor1["id"], s1.json()["stops"][-1]["route_point_id"], junction1["id"])

    response = client.post(
        "/api/navigation/multi-floor-route",
        json={
            "start_point_id": entrance["id"], "end_point_id": destination["id"],
            "vertical_transport_preference": "stairs",
        },
    )
    assert response.status_code == 404, response.text
    assert response.json()["detail"] == "No route using stairs is available to this destination."


def test_vertical_preference_elevator_selects_elevator_over_stairs(client):
    token = create_admin(client, "vert4@example.com", "VERT4")
    _, _, _, entrance, destination = _build_stairs_and_elevator_group(client, token, "VERTGRP4")

    response = client.post(
        "/api/navigation/multi-floor-route",
        json={
            "start_point_id": entrance["id"], "end_point_id": destination["id"],
            "vertical_transport_preference": "elevator",
        },
    )
    assert response.status_code == 200, response.text
    transitions = [s for s in response.json()["segments"] if s["segment_type"] == "transition"]
    assert len(transitions) == 1
    assert transitions[0]["transition_type"] == "elevator"
    # Section 9 — the instruction must say elevator, never stairs.
    transition_instruction = next(i for i in response.json()["instructions"] if i["type"] == "transition")
    assert "elevator" in transition_instruction["text"].lower()
    assert "stairs" not in transition_instruction["text"].lower()


def test_vertical_preference_stairs_selects_stairs_over_elevator(client):
    token = create_admin(client, "vert5@example.com", "VERT5")
    _, _, _, entrance, destination = _build_stairs_and_elevator_group(client, token, "VERTGRP5")

    response = client.post(
        "/api/navigation/multi-floor-route",
        json={
            "start_point_id": entrance["id"], "end_point_id": destination["id"],
            "vertical_transport_preference": "stairs",
        },
    )
    assert response.status_code == 200, response.text
    transitions = [s for s in response.json()["segments"] if s["segment_type"] == "transition"]
    assert len(transitions) == 1
    assert transitions[0]["transition_type"] == "stairs"
    # Section 9 — the instruction must say stairs, never elevator.
    transition_instruction = next(i for i in response.json()["instructions"] if i["type"] == "transition")
    assert "stairs" in transition_instruction["text"].lower()
    assert "elevator" not in transition_instruction["text"].lower()


def test_vertical_preference_no_route_message_is_localized_arabic(client):
    token = create_admin(client, "vert6@example.com", "VERT6")
    _, _, _, entrance, destination = _build_stairs_only_group(client, token, "VERTGRP6")

    response = client.post(
        "/api/navigation/multi-floor-route",
        json={
            "start_point_id": entrance["id"], "end_point_id": destination["id"],
            "vertical_transport_preference": "elevator", "lang": "ar",
        },
    )
    assert response.status_code == 404, response.text
    assert response.json()["detail"] == "لا يوجد مسار متاح باستخدام المصعد إلى هذه الوجهة."


def test_vertical_preference_no_route_message_is_localized_hebrew(client):
    token = create_admin(client, "vert7@example.com", "VERT7")
    _, _, _, entrance, destination = _build_stairs_only_group(client, token, "VERTGRP7")

    response = client.post(
        "/api/navigation/multi-floor-route",
        json={
            "start_point_id": entrance["id"], "end_point_id": destination["id"],
            "vertical_transport_preference": "elevator", "lang": "he",
        },
    )
    assert response.status_code == 404, response.text
    assert response.json()["detail"] == "אין מסלול זמין באמצעות מעלית ליעד זה."


def test_vertical_preference_defaults_to_any_when_omitted(client):
    # Backward compatibility (Section 10) — a caller that never sends
    # vertical_transport_preference at all (e.g. an older QR-navigation
    # client) must behave exactly as before: the stairs-only route still
    # succeeds.
    token = create_admin(client, "vert8@example.com", "VERT8")
    _, _, _, entrance, destination = _build_stairs_only_group(client, token, "VERTGRP8")

    response = client.post(
        "/api/navigation/multi-floor-route",
        json={"start_point_id": entrance["id"], "end_point_id": destination["id"]},
    )
    assert response.status_code == 200, response.text


def test_vertical_preference_invalid_value_returns_400(client):
    token = create_admin(client, "vert9@example.com", "VERT9")
    _, _, _, entrance, destination = _build_stairs_only_group(client, token, "VERTGRP9")

    response = client.post(
        "/api/navigation/multi-floor-route",
        json={
            "start_point_id": entrance["id"], "end_point_id": destination["id"],
            "vertical_transport_preference": "teleport",
        },
    )
    assert response.status_code == 400, response.text


# ---------------------------------------------------------
# BUG-FIX ROUND — Failure 1: technical point names must never leak into
# user-facing instructions, independent of the is_auto_generated flag
# (which is not even settable via the public RoutePointCreate schema).
# ---------------------------------------------------------

def test_technical_name_room_point_pattern_is_suppressed():
    # is_auto_generated=False here on purpose — the whole point of this
    # bug-fix round is that the flag is NOT a reliable signal.
    assert resolve_display_name("room_point_33", None, False) is None


def test_technical_name_corridor_point_pattern_is_suppressed():
    assert resolve_display_name("corridor_point_12", None, False) is None


def test_technical_name_route_point_and_node_patterns_are_suppressed():
    assert resolve_display_name("route_point_123", None, False) is None
    assert resolve_display_name("node_44", None, False) is None


def test_technical_name_objectid_like_is_suppressed():
    assert resolve_display_name("507f1f77bcf86cd799439011", None, False) is None


def test_technical_name_uuid_like_is_suppressed():
    assert resolve_display_name("550e8400-e29b-41d4-a716-446655440000", None, False) is None


def test_technical_name_real_generated_shape_is_still_suppressed():
    # The system's own real auto-generated shape (services/
    # graph_generation_service.py) — confirms the new pattern-based check
    # still covers the exact case the pre-existing is_auto_generated flag
    # was originally meant for, so this is additive, not a regression.
    assert resolve_display_name("Corridor Point 1784904901734-6", None, False) is None
    assert resolve_localized_display_name(
        "Corridor Point 1784904901734-6", is_auto_generated=False, lang="en"
    ) is None


def test_valid_semantic_name_is_preserved():
    # A real, legitimate name — even one containing a digit — must never
    # be caught by the technical-shape pattern (it deliberately requires
    # the literal word "point"/"node", which a genuine destination name
    # essentially never contains).
    assert resolve_display_name("Meeting Point", None, False) == "Meeting Point"
    assert resolve_display_name("Gate 7", None, False) == "Gate 7"
    # display_name always wins outright, even over a technical-looking
    # raw `name` sitting underneath it.
    assert resolve_display_name("room_point_33", "Pharmacy", False) == "Pharmacy"
    assert (
        resolve_localized_display_name(
            "room_point_33", display_name_en="Pharmacy", lang="en"
        )
        == "Pharmacy"
    )


def test_generic_fallback_is_multilingual(client):
    # End-to-end: when BOTH the start point's and the very next point's
    # names are suppressed (technical shape), the "start" instruction's
    # name fallback chain (points[1].name or points[0].name) bottoms out
    # at "" and falls through to the required generic, translated phrase
    # in each language — never a blank/broken "Proceed toward ."
    #
    # Bug-fix round: a single admin/token is created ONCE, outside the
    # loop, and reused for all three languages — /api/invitation-codes/
    # dev-create (which create_admin's make_invitation_code() calls) only
    # ever succeeds for the FIRST super_admin in the whole (per-test, in-
    # memory) database; calling create_admin again inside the loop tried
    # to bootstrap a second, third super_admin and correctly got refused
    # with 403 ("...only available before the first super_admin account
    # exists" — see routes/invitation_code_routes.py's dev-create gate).
    # This mirrors how every other multi-step test in this file already
    # reuses one token across several requests; only map-group codes (and
    # the route points/edges built from them) need to stay unique per
    # language, which they still do below, so the three languages remain
    # fully isolated from each other and this test's outcome never depends
    # on iteration order.
    token = create_admin(client, "tech2@example.com", "TECH2")

    for lang, phrase in {
        "en": "Proceed toward the destination.",
        "ar": "تابعي باتجاه الوجهة.",
        "he": "המשך לכיוון היעד.",
    }.items():
        group = create_map_group(client, token, code=f"TECHGRP2{lang.upper()}")
        floor0 = _floor_by_number(group, 0)

        p0 = client.post(
            "/api/route-points",
            json={
                "map_id": floor0["id"], "name": "node_1", "x": 0, "y": 0,
                "floor": 0, "point_type": "entrance",
            },
            headers=auth_headers(token),
        ).json()
        p1 = client.post(
            "/api/route-points",
            json={
                "map_id": floor0["id"], "name": "route_point_2", "x": 50, "y": 0,
                "floor": 0, "point_type": "store",
            },
            headers=auth_headers(token),
        ).json()
        create_edge(client, token, floor0["id"], p0["id"], p1["id"])

        response = client.post(
            "/api/navigation/multi-floor-route",
            json={"start_point_id": p0["id"], "end_point_id": p1["id"], "lang": lang},
        )
        assert response.status_code == 200, response.text
        instructions = response.json()["instructions"]

        start_instruction = instructions[0]
        assert start_instruction["type"] == "start"
        assert start_instruction["text"] == phrase
        assert "node_1" not in start_instruction["text"]

        arrive_instruction = instructions[-1]
        assert arrive_instruction["type"] == "arrive"
        assert "route_point_2" not in arrive_instruction["text"]


# ---------------------------------------------------------
# BUG-FIX ROUND — Failure 2: a Room/Store destination or start point must
# never be wrongly treated as an unrelated intermediate bridge, including
# when it physically coincides with another destination-capable point,
# and id comparisons must be canonical (str vs PydanticObjectId).
# ---------------------------------------------------------

def _setup_room_coincident_with_existing_store(client, token, code):
    """
    Exact shape of the real bug: an existing "store" RoutePoint already
    sits at a location, and a Room is placed at that SAME location. Room
    placement's own dedup (point_type="room") does not match the existing
    "store" point (different concrete types), so a second, new "room"
    RoutePoint is created and auto-connected to the nearest neighbor —
    which, at distance 0, is the pre-existing "store" point itself. That
    pre-existing point is destination-capable and is NOT the literal
    start/end id, so without the physical-coincidence exception in
    _suppress_intermediate_destination_nodes, it would be wrongly treated
    as an "unrelated" bridge and blocked.
    """
    group = create_map_group(client, token, code=code)
    floor0 = _floor_by_number(group, 0)
    floor1 = _floor_by_number(group, 1)

    entrance = create_route_point(client, token, floor0["id"], "Entrance", 10, 10, 0, "entrance")
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

    stop0 = add_stop(
        client, token, connector["id"], map_id=floor0["id"], x=101, y=10, auto_connect="off"
    )
    stop1 = add_stop(
        client, token, connector["id"], map_id=floor1["id"], x=101, y=10, auto_connect="off"
    )
    assert stop0.status_code == 201 and stop1.status_code == 201
    create_edge(client, token, floor0["id"], junction0["id"], stop0.json()["stops"][-1]["route_point_id"])
    create_edge(client, token, floor1["id"], stop1.json()["stops"][-1]["route_point_id"], junction1["id"])

    room_response = client.post(
        "/api/rooms",
        json={
            "building_id": floor1["building_id"],
            "name_en": "Super-Pharm",
            "room_type": "store",
            "floor": 1,
            "map_id": floor1["id"],
            "x": destination["x"],
            "y": destination["y"],
        },
        headers=auth_headers(token),
    )
    assert room_response.status_code == 201, room_response.text
    room = room_response.json()

    return entrance, destination, room


def test_cross_floor_room_destination_returns_200(client):
    token = create_admin(client, "idfix1@example.com", "IDFIX1")
    entrance, destination, room = _setup_room_coincident_with_existing_store(
        client, token, "IDFIXGRP1"
    )

    response = client.post(
        "/api/navigation/multi-floor-route",
        json={"start_point_id": entrance["id"], "end_point_id": room["route_point_id"]},
    )
    assert response.status_code == 200, response.text
    assert response.json()["segments"][-1]["floor"] == 1


def test_selected_room_destination_is_not_blocked(client):
    token = create_admin(client, "idfix2@example.com", "IDFIX2")
    entrance, destination, room = _setup_room_coincident_with_existing_store(
        client, token, "IDFIXGRP2"
    )

    response = client.post(
        "/api/navigation/multi-floor-route",
        json={"start_point_id": entrance["id"], "end_point_id": room["route_point_id"]},
    )
    assert response.status_code == 200, response.text
    assert response.json()["segments"][-1]["point_ids"][-1] == room["route_point_id"]


def test_selected_room_start_is_not_blocked_cross_floor(client):
    token = create_admin(client, "idfix3@example.com", "IDFIX3")
    entrance, destination, room = _setup_room_coincident_with_existing_store(
        client, token, "IDFIXGRP3"
    )

    # Reversed: the Room's own point is now the START.
    response = client.post(
        "/api/navigation/multi-floor-route",
        json={"start_point_id": room["route_point_id"], "end_point_id": entrance["id"]},
    )
    assert response.status_code == 200, response.text
    assert response.json()["segments"][0]["point_ids"][0] == room["route_point_id"]


def test_unrelated_room_used_only_as_bridge_still_blocked_after_fix(client):
    # The physical-coincidence exception must NOT reopen the door to
    # routing through a genuinely unrelated Room bridge — reusing the
    # exact "only bridge" setup from Section 3's own tests to prove this
    # fix didn't weaken that requirement.
    token = create_admin(client, "idfix4@example.com", "IDFIX4")
    group = create_map_group(client, token, code="IDFIXGRP4")
    floor0 = _floor_by_number(group, 0)

    corridor_a = create_route_point(client, token, floor0["id"], "Corridor A", 10, 10, 0, "junction")
    room = create_route_point(client, token, floor0["id"], "Women's Shower", 100, 10, 0, "room")
    corridor_b = create_route_point(client, token, floor0["id"], "Corridor B", 190, 10, 0, "junction")

    create_edge(client, token, floor0["id"], corridor_a["id"], room["id"])
    create_edge(client, token, floor0["id"], room["id"], corridor_b["id"])

    response = client.post(
        "/api/navigation/multi-floor-route",
        json={"start_point_id": corridor_a["id"], "end_point_id": corridor_b["id"]},
    )
    assert response.status_code == 409, response.text
    assert room["id"] in response.json()["detail"]


@pytest.mark.asyncio
async def test_endpoint_id_accepted_as_objectid_or_plain_string(client):
    # Section: "normalise ObjectId/string values consistently" — calls
    # calculate_multi_floor_route directly (bypassing the HTTP JSON layer,
    # which always sends plain strings) with a PydanticObjectId end_point_id
    # to prove the internal str() normalization means this is never
    # silently mismatched against the graph's own string-keyed nodes.
    token = create_admin(client, "idfix5@example.com", "IDFIX5")
    group = create_map_group(client, token, code="IDFIXGRP5")
    floor0 = _floor_by_number(group, 0)

    entrance = create_route_point(client, token, floor0["id"], "Entrance", 0, 0, 0, "entrance")
    store = create_route_point(client, token, floor0["id"], "Dest", 50, 0, 0, "store")
    create_edge(client, token, floor0["id"], entrance["id"], store["id"])

    result = await calculate_multi_floor_route(
        map_ids=[floor0["id"]],
        start_point_id=PydanticObjectId(entrance["id"]),
        end_point_id=PydanticObjectId(store["id"]),
    )
    assert result is not None
    assert result.point_ids[-1] == store["id"]
    assert result.point_ids[0] == entrance["id"]
