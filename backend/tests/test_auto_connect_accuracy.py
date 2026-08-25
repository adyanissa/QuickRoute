"""
Acceptance tests for the Auto Connect accuracy correction.

Two real-map failures motivated this work:

  * Auto Connect reported "no hallway/junction point close enough" for
    rooms with a corridor drawn right beside them. Three separate causes:
    a wall rejection was reported with a distance-flavoured reason; the
    fractional wall tolerance gives SHORT lines essentially no slack, so
    the geometrically most obvious connections were the ones failing; and
    the search only ever looked at corridor NODES, never at the drawn
    corridor EDGES between them.

  * Auto Connect sometimes produced ROOM -> ROOM edges. Not from the Auto
    Connect Destinations preview/apply pair, which has always been
    restricted to hallway/junction — from
    graph_connection_service.auto_connect_point, whose candidate pool had
    no point_type filter at all, reached with a room point by both
    POST /api/rooms and POST /api/route-points?auto_connect=.

Each numbered test below is one of the ten acceptance cases agreed for
this fix.

Run with: pytest backend/tests/test_auto_connect_accuracy.py -v
"""

import cv2
import numpy as np
import pytest

from tests.test_api_integration import auth_headers, create_admin_and_get_token

from models.room_model import Room
from models.route_edge_model import RouteEdge
from models.route_point_model import RoutePoint


PREVIEW_URL = "/api/route-edges/auto-connect-destinations/preview"
APPLY_URL = "/api/route-edges/auto-connect-destinations/apply"


# ---------------------------------------------------------
# Helpers (local copies, matching the established per-file convention —
# see tests/test_auto_connect_corridor_types.py).
# ---------------------------------------------------------

def _create_map(client, token, title="Auto Connect Accuracy Map", floor=None):
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


def _create_edge(client, token, map_id, from_point_id, to_point_id):
    response = client.post(
        "/api/route-edges",
        json={
            "map_id": map_id,
            "from_point_id": from_point_id,
            "to_point_id": to_point_id,
            "edge_type": "walkway",
        },
        headers=auth_headers(token),
    )
    assert response.status_code == 201, response.text
    return response.json()


def _preview(client, token, map_id, **kwargs):
    response = client.post(
        PREVIEW_URL, json={"map_id": map_id, **kwargs}, headers=auth_headers(token)
    )
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


def _find(preview_result, destination_point_id):
    for proposal in preview_result["proposals"]:
        if proposal["destination_point_id"] == destination_point_id:
            return proposal
    return None


def _install_plan(monkeypatch, tmp_path, map_id, image):
    """Publish a synthetic floor plan as this map's source image, for both
    the legacy wall mask and the strict validator."""
    monkeypatch.setattr("services.graph_connection_service.SOURCE_DIR", tmp_path)
    monkeypatch.setattr("services.strict_geometry_service.SOURCE_DIR", tmp_path)
    cv2.imwrite(str(tmp_path / f"{map_id}.png"), image)


def _blank_plan(width=600, height=400):
    return np.full((height, width), 255, dtype=np.uint8)


# =========================================================
# 1. Normal room near a corridor connects to the corridor.
# =========================================================

def test_room_near_corridor_connects_to_corridor(client):
    token, _ = create_admin_and_get_token(client, email="acc1@example.com")
    map_item = _create_map(client, token)

    hall_a = _create_point(client, token, map_item["id"], "Hall A", 100, 100)
    hall_b = _create_point(client, token, map_item["id"], "Hall B", 500, 100)
    _create_edge(client, token, map_item["id"], hall_a["id"], hall_b["id"])

    room = _create_point(
        client, token, map_item["id"], "Room 1", 110, 160, point_type="room"
    )

    proposal = _find(_preview(client, token, map_item["id"]), room["id"])

    assert proposal["status"] == "proposed"
    assert proposal["candidates"]
    assert proposal["candidates"][0]["point_type"] in ("hallway", "junction")
    assert proposal["graph_connected"] is True


# =========================================================
# 2. A room closer to another ROOM than to the corridor must still
#    connect to the corridor, and must never see the other room.
# =========================================================

def test_room_closer_to_another_room_still_connects_to_corridor(client):
    token, _ = create_admin_and_get_token(client, email="acc2@example.com")
    map_item = _create_map(client, token)

    hall_a = _create_point(client, token, map_item["id"], "Hall A", 100, 100)
    hall_b = _create_point(client, token, map_item["id"], "Hall B", 500, 100)
    _create_edge(client, token, map_item["id"], hall_a["id"], hall_b["id"])

    room_a = _create_point(
        client, token, map_item["id"], "Room A", 300, 300, point_type="room"
    )
    # Ten pixels away — far nearer than any corridor point.
    room_b = _create_point(
        client, token, map_item["id"], "Room B", 310, 300, point_type="room"
    )

    result = _preview(client, token, map_item["id"])
    proposal = _find(result, room_a["id"])

    assert proposal["status"] == "proposed"

    candidate_ids = [c["point_id"] for c in proposal["candidates"]]
    assert room_b["id"] not in candidate_ids
    assert all(
        c["point_type"] in ("hallway", "junction") for c in proposal["candidates"]
    )

    # ...and the same in reverse, so this is not an ordering artifact.
    reverse = _find(result, room_b["id"])
    assert room_a["id"] not in [c["point_id"] for c in reverse["candidates"]]


# =========================================================
# 3. A room door beside the MIDDLE of a long corridor edge, far from both
#    endpoint nodes, still finds a valid attachment.
# =========================================================

def test_room_beside_middle_of_long_corridor_edge_finds_attachment(client):
    token, _ = create_admin_and_get_token(client, email="acc3@example.com")
    map_item = _create_map(client, token)

    # One long corridor run. Its endpoints are 300px from the room; the
    # perpendicular foot is 40px away.
    hall_a = _create_point(client, token, map_item["id"], "Hall West", 0, 100)
    hall_b = _create_point(client, token, map_item["id"], "Hall East", 600, 100)
    edge = _create_edge(client, token, map_item["id"], hall_a["id"], hall_b["id"])

    room = _create_point(
        client, token, map_item["id"], "Mid Room", 300, 140, point_type="room"
    )

    proposal = _find(_preview(client, token, map_item["id"]), room["id"])

    assert proposal["status"] == "proposed"

    best = proposal["candidates"][0]
    assert best["target_type"] == "corridor_edge"
    assert best["corridor_edge_id"] == edge["id"]
    assert best["point_id"] is None
    # Perpendicular foot, not an endpoint.
    assert best["attachment_x"] == pytest.approx(300.0, abs=1.0)
    assert best["attachment_y"] == pytest.approx(100.0, abs=1.0)
    assert best["distance_px"] == pytest.approx(40.0, abs=1.0)
    assert proposal["connection_type"] == "corridor_edge_split"


@pytest.mark.asyncio
async def test_edge_attachment_applies_by_splitting_the_corridor(client):
    token, _ = create_admin_and_get_token(client, email="acc3b@example.com")
    map_item = _create_map(client, token)

    hall_a = _create_point(client, token, map_item["id"], "Hall West", 0, 100)
    hall_b = _create_point(client, token, map_item["id"], "Hall East", 600, 100)
    edge = _create_edge(client, token, map_item["id"], hall_a["id"], hall_b["id"])
    room = _create_point(
        client, token, map_item["id"], "Mid Room", 300, 140, point_type="room"
    )

    best = _find(_preview(client, token, map_item["id"]), room["id"])["candidates"][0]

    apply_result = _apply(
        client,
        token,
        map_item["id"],
        [
            {
                "destination_point_id": room["id"],
                "corridor_edge_id": best["corridor_edge_id"],
                "attachment_x": best["attachment_x"],
                "attachment_y": best["attachment_y"],
            }
        ],
    )

    assert apply_result["created"] == 1
    assert apply_result["corridor_junctions_created"] == 1

    junction_id = apply_result["created_point_ids"][0]
    junction = await RoutePoint.get(junction_id)
    assert junction.point_type == "junction"
    assert junction.x == pytest.approx(300.0, abs=1.0)

    # The original edge is deactivated, never deleted...
    original = await RouteEdge.get(edge["id"])
    assert original.is_active is False

    # ...and replaced by two corridor edges through the junction, so the
    # corridor is still walkable end to end.
    active = await RouteEdge.find(
        {"map_id": map_item["id"], "is_active": True}
    ).to_list()
    through_junction = {
        (e.from_point_id, e.to_point_id)
        for e in active
        if junction_id in (e.from_point_id, e.to_point_id)
    }
    assert len(through_junction) == 3  # west, east, and the room
    assert any(hall_a["id"] in pair for pair in through_junction)
    assert any(hall_b["id"] in pair for pair in through_junction)
    assert any(room["id"] in pair for pair in through_junction)


# =========================================================
# 4. The nearest candidate needs a wall crossing — reject it and take the
#    next valid corridor candidate instead.
# =========================================================

def test_wall_blocked_nearest_candidate_falls_through_to_the_next(
    client, tmp_path, monkeypatch
):
    token, _ = create_admin_and_get_token(client, email="acc4@example.com")
    map_item = _create_map(client, token)

    # A thick structural wall at x=200..240, full height. The room sits to
    # its left; the NEAR hallway is on the far side of it, the FAR hallway
    # is on the room's own side.
    image = _blank_plan()
    cv2.rectangle(image, (200, 0), (220, 400), 0, thickness=-1)
    _install_plan(monkeypatch, tmp_path, map_item["id"], image)

    near_behind_wall = _create_point(
        client, token, map_item["id"], "Behind Wall", 300, 200
    )
    far_same_side = _create_point(client, token, map_item["id"], "Same Side", 60, 340)
    _create_edge(
        client, token, map_item["id"], near_behind_wall["id"], far_same_side["id"]
    )

    room = _create_point(
        client, token, map_item["id"], "Walled Room", 100, 200, point_type="room"
    )

    proposal = _find(_preview(client, token, map_item["id"]), room["id"])

    assert proposal["status"] == "proposed"
    chosen_ids = [c["point_id"] for c in proposal["candidates"]]
    assert near_behind_wall["id"] not in chosen_ids
    assert far_same_side["id"] in chosen_ids
    # The wall rejection is reported, not silently swallowed.
    assert proposal["blocked_candidate_count"] >= 1


def test_every_candidate_wall_blocked_reports_a_wall_reason_not_distance(
    client, tmp_path, monkeypatch
):
    # This is the exact misreport from the bug: a corridor drawn close by,
    # a wall in between, and the admin told "no corridor point close
    # enough to connect to".
    token, _ = create_admin_and_get_token(client, email="acc4b@example.com")
    map_item = _create_map(client, token)

    image = _blank_plan()
    cv2.rectangle(image, (200, 0), (220, 400), 0, thickness=-1)
    _install_plan(monkeypatch, tmp_path, map_item["id"], image)

    hall_a = _create_point(client, token, map_item["id"], "Hall A", 400, 150)
    hall_b = _create_point(client, token, map_item["id"], "Hall B", 500, 250)
    _create_edge(client, token, map_item["id"], hall_a["id"], hall_b["id"])

    room = _create_point(
        client, token, map_item["id"], "Sealed Room", 80, 200, point_type="room"
    )

    proposal = _find(_preview(client, token, map_item["id"]), room["id"])

    assert proposal["status"] == "no_candidate"
    assert proposal["reason"] == "blocked_by_wall"
    assert proposal["blocked_candidate_count"] >= 1
    # ...and it still reports how far the corridor actually was, so the
    # admin can tell this apart from a genuine distance problem.
    assert proposal["nearest_distance_px"] is not None


def test_a_marker_behind_its_own_room_wall_reports_the_wall_not_distance(
    client, tmp_path, monkeypatch
):
    # A room marker sits INSIDE its room, so its own boundary is between it
    # and the corridor. has_clear_line remains authoritative — this is
    # deliberately still refused rather than forgiven, because a single
    # wall stroke is geometrically indistinguishable from a rasterised-shut
    # doorway and guessing would silently create routes through walls.
    #
    # What the fix guarantees is that the admin is told the truth: a wall
    # is in the way, and the corridor is N pixels away. Previously this
    # exact case reported "no hallway/junction point close enough", which
    # sent admins off to draw more corridor they did not need.
    token, _ = create_admin_and_get_token(client, email="acc4c@example.com")
    map_item = _create_map(client, token)

    image = _blank_plan()
    cv2.rectangle(image, (100, 150), (260, 300), 0, thickness=10)
    _install_plan(monkeypatch, tmp_path, map_item["id"], image)

    hall_a = _create_point(client, token, map_item["id"], "Hall A", 120, 110)
    hall_b = _create_point(client, token, map_item["id"], "Hall B", 480, 110)
    _create_edge(client, token, map_item["id"], hall_a["id"], hall_b["id"])

    room = _create_point(
        client, token, map_item["id"], "Boxed Room", 180, 220, point_type="room"
    )

    proposal = _find(_preview(client, token, map_item["id"]), room["id"])

    assert proposal["status"] == "no_candidate"
    assert proposal["reason"] == "blocked_by_wall"
    assert proposal["blocked_candidate_count"] >= 1
    # The actionable part: the corridor really is close, and the admin can
    # see exactly how close.
    assert proposal["nearest_distance_px"] is not None
    assert proposal["nearest_distance_px"] < proposal["max_hard_distance_px"]


def test_two_wall_crossings_are_refused_even_when_the_fraction_rule_passes(
    tmp_path, monkeypatch
):
    # "Never use an unrelated room interior as a shortcut", enforced by
    # counting wall CROSSINGS rather than wall pixels.
    #
    # Deliberately a direct unit test of the rule: has_clear_line's
    # tolerance is a fraction of the sampled length, so the interesting
    # case is a line it ACCEPTS — long enough that a few clipped wall
    # pixels stay under 3% — which entering and leaving another enclosed
    # space always produces two separate blocked runs for.
    from services.auto_connect_destinations_service import _attachment_is_clear
    from services.graph_connection_service import has_clear_line

    monkeypatch.setattr("services.graph_connection_service.SOURCE_DIR", tmp_path)

    map_id = "two-wall-crossing-map"
    image = _blank_plan(880, 400)
    # Two thin parallel walls: the two sides of an unrelated room.
    cv2.rectangle(image, (300, 0), (303, 400), 0, thickness=-1)
    cv2.rectangle(image, (500, 0), (503, 400), 0, thickness=-1)
    cv2.imwrite(str(tmp_path / f"{map_id}.png"), image)

    # Long enough that the clipped pixels stay under the fractional
    # tolerance — the authoritative check says this line is fine...
    assert has_clear_line(map_id, 40, 200, 840, 200) is True

    # ...and the crossing-count rule refuses it anyway, because it passes
    # straight through the space between the two walls.
    is_clear, _ = _attachment_is_clear(map_id, 40, 200, 840, 200)
    assert is_clear is False

    # One crossing — a single boundary — is still allowed, so this rule
    # only ever rejects the shortcut case.
    single_wall_clear, grazed = _attachment_is_clear(map_id, 40, 200, 400, 200)
    assert single_wall_clear is True
    assert grazed is True


# =========================================================
# 5. A corridor point exists but is isolated from the walkway graph — no
#    successful attachment, and a reason that says exactly that.
# =========================================================

def test_isolated_corridor_point_is_not_claimed_as_a_connection(client):
    token, _ = create_admin_and_get_token(client, email="acc5@example.com")
    map_item = _create_map(client, token)

    # A real, connected corridor far away...
    hall_a = _create_point(client, token, map_item["id"], "Main A", 1400, 1400)
    hall_b = _create_point(client, token, map_item["id"], "Main B", 1500, 1400)
    _create_edge(client, token, map_item["id"], hall_a["id"], hall_b["id"])

    # ...and one stray hallway dot right next to the room, wired to
    # nothing at all.
    stray = _create_point(client, token, map_item["id"], "Stray Dot", 110, 100)

    room = _create_point(
        client, token, map_item["id"], "Lonely Room", 100, 100, point_type="room"
    )

    proposal = _find(_preview(client, token, map_item["id"]), room["id"])

    candidate_ids = [c["point_id"] for c in proposal["candidates"]]
    assert stray["id"] not in candidate_ids
    assert proposal["isolated_candidate_count"] >= 1

    if proposal["status"] == "no_candidate":
        assert proposal["reason"] == "corridor_candidate_isolated"
    else:
        # If the far corridor was reachable it must be the one chosen, and
        # it must be on the connected graph.
        assert proposal["graph_connected"] is True
        assert stray["id"] not in candidate_ids


def test_a_lone_hallway_point_map_is_not_treated_as_isolated(client):
    # Regression guard for the rule above: with no multi-point component
    # anywhere, there is no "main graph" to be isolated from, and a single
    # hand-placed hallway point stays a perfectly good candidate.
    token, _ = create_admin_and_get_token(client, email="acc5b@example.com")
    map_item = _create_map(client, token)

    hall = _create_point(client, token, map_item["id"], "Only Hall", 120, 100)
    room = _create_point(
        client, token, map_item["id"], "Room", 100, 100, point_type="room"
    )

    proposal = _find(_preview(client, token, map_item["id"]), room["id"])

    assert proposal["status"] == "proposed"
    assert proposal["candidates"][0]["point_id"] == hall["id"]
    assert proposal["isolated_candidate_count"] == 0


# =========================================================
# 6. Inner room inside an outer room, explicit nested relationship, outer
#    room approved for pass-through -> the inner room connects through it.
# =========================================================

@pytest.mark.asyncio
async def test_nested_child_connects_through_an_approved_pass_through_parent(client):
    token, _ = create_admin_and_get_token(client, email="acc6@example.com")
    map_item = _create_map(client, token)

    hall_a = _create_point(client, token, map_item["id"], "Hall A", 100, 100)
    hall_b = _create_point(client, token, map_item["id"], "Hall B", 500, 100)
    _create_edge(client, token, map_item["id"], hall_a["id"], hall_b["id"])

    outer = _create_point(
        client, token, map_item["id"], "Outer Room", 200, 250, point_type="room"
    )
    inner = _create_point(
        client, token, map_item["id"], "Inner Room", 220, 260, point_type="room"
    )

    # Pass-through is an explicit admin approval, never inferred.
    client.put(
        f"/api/route-points/{outer['id']}",
        json={"allow_transit_through": True},
        headers=auth_headers(token),
    )

    outer_room = await Room.find_one({"route_point_id": outer["id"]})
    inner_room = await Room.find_one({"route_point_id": inner["id"]})
    inner_room.parent_room_id = str(outer_room.id)
    await inner_room.save()

    proposal = _find(_preview(client, token, map_item["id"]), inner["id"])

    assert proposal["status"] == "proposed"
    assert proposal["is_nested_access"] is True
    assert proposal["connection_type"] == "nested_room_via_parent"
    assert proposal["parent_pass_through"] is True
    assert proposal["nested_parent_room_id"] == str(outer_room.id)
    assert proposal["proposed_candidate_id"] == outer["id"]

    # ...and the OUTER room still connects to the corridor itself, so the
    # full chain inner -> outer -> corridor exists.
    outer_proposal = _find(_preview(client, token, map_item["id"]), outer["id"])
    assert outer_proposal["status"] == "proposed"
    assert outer_proposal["candidates"][0]["point_type"] in ("hallway", "junction")


# =========================================================
# 7. Same nesting, but the outer room is NOT pass-through -> NEEDS
#    REVIEW, and never a fabricated direct corridor connection.
# =========================================================

@pytest.mark.asyncio
async def test_nested_child_without_pass_through_parent_needs_review(client):
    token, _ = create_admin_and_get_token(client, email="acc7@example.com")
    map_item = _create_map(client, token)

    hall_a = _create_point(client, token, map_item["id"], "Hall A", 100, 100)
    hall_b = _create_point(client, token, map_item["id"], "Hall B", 500, 100)
    _create_edge(client, token, map_item["id"], hall_a["id"], hall_b["id"])

    outer = _create_point(
        client, token, map_item["id"], "Outer Room", 200, 250, point_type="room"
    )
    inner = _create_point(
        client, token, map_item["id"], "Inner Room", 220, 260, point_type="room"
    )

    outer_room = await Room.find_one({"route_point_id": outer["id"]})
    inner_room = await Room.find_one({"route_point_id": inner["id"]})
    inner_room.parent_room_id = str(outer_room.id)
    await inner_room.save()
    # Deliberately NOT approving allow_transit_through on the parent.

    result = _preview(client, token, map_item["id"])
    proposal = _find(result, inner["id"])

    assert proposal["status"] == "needs_review"
    assert proposal["reason"] == "nested_parent_not_pass_through"
    assert proposal["is_nested_access"] is True
    assert proposal["parent_pass_through"] is False
    assert proposal["candidates"] == []
    assert proposal["proposed_candidate_id"] is None
    assert result["summary"]["needs_review"] >= 1


# =========================================================
# 8. Two unrelated nearby rooms are never auto-connected to each other —
#    not in the preview, not on apply, and not by the point-creation path
#    that actually produced the bad edges on the real map.
# =========================================================

def test_unrelated_nearby_rooms_are_never_connected_by_preview(client):
    token, _ = create_admin_and_get_token(client, email="acc8@example.com")
    map_item = _create_map(client, token)

    room_a = _create_point(
        client, token, map_item["id"], "Room A", 300, 300, point_type="room"
    )
    room_b = _create_point(
        client, token, map_item["id"], "Room B", 305, 300, point_type="room"
    )

    result = _preview(client, token, map_item["id"])

    for point_id, other_id in ((room_a["id"], room_b["id"]), (room_b["id"], room_a["id"])):
        proposal = _find(result, point_id)
        assert other_id not in [c["point_id"] for c in proposal["candidates"]]


def test_unrelated_room_pair_is_rejected_by_apply(client):
    token, _ = create_admin_and_get_token(client, email="acc8b@example.com")
    map_item = _create_map(client, token)

    room_a = _create_point(
        client, token, map_item["id"], "Room A", 300, 300, point_type="room"
    )
    room_b = _create_point(
        client, token, map_item["id"], "Room B", 305, 300, point_type="room"
    )

    apply_result = _apply(
        client,
        token,
        map_item["id"],
        [{"destination_point_id": room_a["id"], "corridor_point_id": room_b["id"]}],
    )

    assert apply_result["created"] == 0
    assert apply_result["rejected_invalid"] == 1


@pytest.mark.asyncio
async def test_creating_a_room_point_never_auto_links_it_to_another_room(client):
    # The actual source of the Room -> Room edges seen on the real map:
    # POST /api/route-points?auto_connect=nearest used an unfiltered
    # candidate pool, so a new room point wired itself to whatever
    # happened to be nearest — including another room.
    token, _ = create_admin_and_get_token(client, email="acc8c@example.com")
    map_item = _create_map(client, token)

    existing_room = _create_point(
        client, token, map_item["id"], "Existing Room", 300, 300,
        floor=0, point_type="room",
    )

    response = client.post(
        "/api/route-points?auto_connect=nearest",
        json={
            "map_id": map_item["id"],
            "name": "New Room",
            "x": 320,
            "y": 300,
            "floor": 0,
            "point_type": "room",
        },
        headers=auth_headers(token),
    )
    assert response.status_code == 201, response.text
    new_point = response.json()

    assert new_point["auto_connected_edge_ids"] == []

    edges = await RouteEdge.find({"map_id": map_item["id"]}).to_list()
    assert not any(
        {e.from_point_id, e.to_point_id} == {existing_room["id"], new_point["id"]}
        for e in edges
    )


@pytest.mark.asyncio
async def test_a_room_coincident_with_an_existing_destination_still_links(client):
    # The one deliberate exception to "a destination never links to another
    # destination": two destination points at the SAME coordinates are two
    # records of one physical place, not two rooms. This happens for real
    # when a "store" RoutePoint already exists and an admin then places a
    # Room there — point dedup does not merge them because the concrete
    # point_types differ.
    #
    # logic/multi_floor_routing.py already recognises exactly this pair via
    # its own 6px coincidence rule, which is what stops the router treating
    # it as an unrelated room used as a bridge. Breaking the link here
    # would strand every such room (see
    # tests/test_navigation_redesign.py::test_selected_room_destination_is_not_blocked).
    token, _ = create_admin_and_get_token(client, email="acc8f@example.com")
    map_item = _create_map(client, token)

    existing_store = _create_point(
        client, token, map_item["id"], "Super-Pharm", 300, 300,
        floor=0, point_type="store",
    )

    response = client.post(
        "/api/route-points?auto_connect=nearest",
        json={
            "map_id": map_item["id"],
            "name": "Super-Pharm Room",
            "x": 302,
            "y": 300,
            "floor": 0,
            "point_type": "room",
        },
        headers=auth_headers(token),
    )
    assert response.status_code == 201, response.text
    new_point = response.json()

    assert len(new_point["auto_connected_edge_ids"]) == 1
    edge = await RouteEdge.get(new_point["auto_connected_edge_ids"][0])
    assert {edge.from_point_id, edge.to_point_id} == {
        existing_store["id"],
        new_point["id"],
    }


@pytest.mark.asyncio
async def test_the_coincidence_exception_does_not_stretch_to_a_nearby_room(client):
    # Ten pixels apart is a different room, and stays excluded — the
    # exception above is identity, not proximity.
    token, _ = create_admin_and_get_token(client, email="acc8g@example.com")
    map_item = _create_map(client, token)

    neighbour = _create_point(
        client, token, map_item["id"], "Neighbour Room", 300, 300,
        floor=0, point_type="room",
    )

    response = client.post(
        "/api/route-points?auto_connect=nearest",
        json={
            "map_id": map_item["id"],
            "name": "Another Room",
            "x": 310,
            "y": 300,
            "floor": 0,
            "point_type": "room",
        },
        headers=auth_headers(token),
    )
    assert response.status_code == 201, response.text
    new_point = response.json()

    assert new_point["auto_connected_edge_ids"] == []

    edges = await RouteEdge.find({"map_id": map_item["id"]}).to_list()
    assert not any(
        {e.from_point_id, e.to_point_id} == {neighbour["id"], new_point["id"]}
        for e in edges
    )


@pytest.mark.asyncio
async def test_creating_a_room_point_still_auto_links_to_a_corridor(client):
    # The other half of the same rule: restricting the pool must not stop
    # a room from attaching to a genuine hallway point.
    token, _ = create_admin_and_get_token(client, email="acc8d@example.com")
    map_item = _create_map(client, token)

    hallway = _create_point(
        client, token, map_item["id"], "Hallway", 300, 300, floor=0, point_type="hallway"
    )

    response = client.post(
        "/api/route-points?auto_connect=nearest",
        json={
            "map_id": map_item["id"],
            "name": "Room By Hall",
            "x": 330,
            "y": 300,
            "floor": 0,
            "point_type": "room",
        },
        headers=auth_headers(token),
    )
    assert response.status_code == 201, response.text
    new_point = response.json()

    assert len(new_point["auto_connected_edge_ids"]) == 1

    edge = await RouteEdge.get(new_point["auto_connected_edge_ids"][0])
    assert {edge.from_point_id, edge.to_point_id} == {hallway["id"], new_point["id"]}


@pytest.mark.asyncio
async def test_corridor_points_keep_their_unrestricted_auto_connect(client):
    # Only destination points get the restricted pool. A corridor point
    # being merged into the graph must behave exactly as before, including
    # linking to an untyped legacy point.
    token, _ = create_admin_and_get_token(client, email="acc8e@example.com")
    map_item = _create_map(client, token)

    legacy = _create_point(
        client, token, map_item["id"], "Legacy Point", 300, 300, floor=0, point_type=None
    )

    response = client.post(
        "/api/route-points?auto_connect=nearest",
        json={
            "map_id": map_item["id"],
            "name": "New Hallway",
            "x": 330,
            "y": 300,
            "floor": 0,
            "point_type": "hallway",
        },
        headers=auth_headers(token),
    )
    assert response.status_code == 201, response.text
    new_point = response.json()

    assert len(new_point["auto_connected_edge_ids"]) == 1
    edge = await RouteEdge.get(new_point["auto_connected_edge_ids"][0])
    assert {edge.from_point_id, edge.to_point_id} == {legacy["id"], new_point["id"]}


# =========================================================
# 9. Rooms that are already validly connected stay untouched.
# =========================================================

@pytest.mark.asyncio
async def test_already_connected_rooms_are_left_alone(client):
    token, _ = create_admin_and_get_token(client, email="acc9@example.com")
    map_item = _create_map(client, token)

    hall_a = _create_point(client, token, map_item["id"], "Hall A", 100, 100)
    hall_b = _create_point(client, token, map_item["id"], "Hall B", 500, 100)
    _create_edge(client, token, map_item["id"], hall_a["id"], hall_b["id"])

    room = _create_point(
        client, token, map_item["id"], "Connected Room", 110, 160, point_type="room"
    )
    existing = _create_edge(client, token, map_item["id"], room["id"], hall_a["id"])

    before = await RouteEdge.find({"map_id": map_item["id"]}).to_list()

    result = _preview(client, token, map_item["id"])
    proposal = _find(result, room["id"])

    assert proposal is None
    assert result["summary"]["already_connected"] == 1

    after = await RouteEdge.find({"map_id": map_item["id"]}).to_list()
    assert len(after) == len(before)

    unchanged = await RouteEdge.get(existing["id"])
    assert unchanged.is_active is True
    assert unchanged.from_point_id == room["id"]
    assert unchanged.to_point_id == hall_a["id"]


# =========================================================
# 10. Preview stays read-only until proposals are explicitly accepted.
# =========================================================

@pytest.mark.asyncio
async def test_preview_writes_nothing_including_the_new_edge_search(client):
    token, _ = create_admin_and_get_token(client, email="acc10@example.com")
    map_item = _create_map(client, token)

    hall_a = _create_point(client, token, map_item["id"], "Hall West", 0, 100)
    hall_b = _create_point(client, token, map_item["id"], "Hall East", 600, 100)
    _create_edge(client, token, map_item["id"], hall_a["id"], hall_b["id"])
    _create_point(client, token, map_item["id"], "Mid Room", 300, 140, point_type="room")
    _create_point(client, token, map_item["id"], "Far Room", 300, 380, point_type="room")

    points_before = len(await RoutePoint.find({"map_id": map_item["id"]}).to_list())
    edges_before = len(await RouteEdge.find({"map_id": map_item["id"]}).to_list())

    # Repeatedly — an edge-split proposal must stay a proposal no matter
    # how many times it is previewed.
    for _ in range(3):
        result = _preview(client, token, map_item["id"])
        assert result["proposals"]

    assert len(await RoutePoint.find({"map_id": map_item["id"]}).to_list()) == points_before
    assert len(await RouteEdge.find({"map_id": map_item["id"]}).to_list()) == edges_before


@pytest.mark.asyncio
async def test_only_the_accepted_proposal_is_applied(client):
    token, _ = create_admin_and_get_token(client, email="acc10b@example.com")
    map_item = _create_map(client, token)

    hall_a = _create_point(client, token, map_item["id"], "Hall A", 100, 100)
    hall_b = _create_point(client, token, map_item["id"], "Hall B", 500, 100)
    _create_edge(client, token, map_item["id"], hall_a["id"], hall_b["id"])

    accepted_room = _create_point(
        client, token, map_item["id"], "Accepted", 110, 160, point_type="room"
    )
    ignored_room = _create_point(
        client, token, map_item["id"], "Ignored", 490, 160, point_type="room"
    )

    result = _preview(client, token, map_item["id"])
    chosen = _find(result, accepted_room["id"])["candidates"][0]

    apply_result = _apply(
        client,
        token,
        map_item["id"],
        [
            {
                "destination_point_id": accepted_room["id"],
                "corridor_point_id": chosen["point_id"],
            }
        ],
    )
    assert apply_result["created"] == 1

    edges = await RouteEdge.find(
        {"map_id": map_item["id"], "is_active": True}
    ).to_list()
    assert not any(
        ignored_room["id"] in (e.from_point_id, e.to_point_id) for e in edges
    )


# =========================================================
# Apply-side guards for the new edge attachment.
# =========================================================

def test_apply_rejects_a_pair_with_both_a_point_and_an_edge(client):
    token, _ = create_admin_and_get_token(client, email="accg1@example.com")
    map_item = _create_map(client, token)

    hall_a = _create_point(client, token, map_item["id"], "Hall A", 0, 100)
    hall_b = _create_point(client, token, map_item["id"], "Hall B", 600, 100)
    edge = _create_edge(client, token, map_item["id"], hall_a["id"], hall_b["id"])
    room = _create_point(
        client, token, map_item["id"], "Room", 300, 140, point_type="room"
    )

    apply_result = _apply(
        client,
        token,
        map_item["id"],
        [
            {
                "destination_point_id": room["id"],
                "corridor_point_id": hall_a["id"],
                "corridor_edge_id": edge["id"],
                "attachment_x": 300,
                "attachment_y": 100,
            }
        ],
    )

    assert apply_result["created"] == 0
    assert apply_result["rejected_invalid"] == 1


def test_apply_rejects_an_edge_attachment_with_no_coordinates(client):
    token, _ = create_admin_and_get_token(client, email="accg2@example.com")
    map_item = _create_map(client, token)

    hall_a = _create_point(client, token, map_item["id"], "Hall A", 0, 100)
    hall_b = _create_point(client, token, map_item["id"], "Hall B", 600, 100)
    edge = _create_edge(client, token, map_item["id"], hall_a["id"], hall_b["id"])
    room = _create_point(
        client, token, map_item["id"], "Room", 300, 140, point_type="room"
    )

    apply_result = _apply(
        client,
        token,
        map_item["id"],
        [{"destination_point_id": room["id"], "corridor_edge_id": edge["id"]}],
    )

    assert apply_result["created"] == 0
    assert apply_result["rejected_invalid"] == 1


@pytest.mark.asyncio
async def test_apply_rejects_an_edge_attachment_that_crosses_a_wall(
    client, tmp_path, monkeypatch
):
    # The preview's geometry check is not trusted at apply time — the
    # attachment is revalidated against a fresh read of the wall mask.
    token, _ = create_admin_and_get_token(client, email="accg3@example.com")
    map_item = _create_map(client, token)

    hall_a = _create_point(client, token, map_item["id"], "Hall A", 0, 100)
    hall_b = _create_point(client, token, map_item["id"], "Hall B", 600, 100)
    edge = _create_edge(client, token, map_item["id"], hall_a["id"], hall_b["id"])
    room = _create_point(
        client, token, map_item["id"], "Room", 300, 340, point_type="room"
    )

    image = _blank_plan()
    cv2.rectangle(image, (0, 180), (600, 200), 0, thickness=-1)
    _install_plan(monkeypatch, tmp_path, map_item["id"], image)

    apply_result = _apply(
        client,
        token,
        map_item["id"],
        [
            {
                "destination_point_id": room["id"],
                "corridor_edge_id": edge["id"],
                "attachment_x": 300,
                "attachment_y": 100,
            }
        ],
    )

    assert apply_result["created"] == 0
    assert apply_result["rejected_invalid"] == 1
    assert apply_result["corridor_junctions_created"] == 0

    # Nothing was split.
    original = await RouteEdge.get(edge["id"])
    assert original.is_active is True
