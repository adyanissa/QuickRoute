"""
Tests for the Auto Connect Destinations scale-aware distance threshold fix.

Root cause being fixed: every unconnected room/store destination was only
ever proposed a hallway/junction candidate if it happened to be within one
fixed, very small raw-pixel cutoff (MAX_DISTANCE_PX_DEFAULT = 600px),
regardless of the map's actual image resolution. On a large, high-
resolution floor-plan image, 600px can be a tiny fraction of the real
floor, so manually-drawn-looking, perfectly reasonable same-floor
connections were silently reported as "No hallway/junction point close
enough" and Proposed stayed 0.

Fix: services/auto_connect_destinations_service.py now derives its
distance thresholds from the map's own canonical image dimensions
(source_width/source_height, falling back to display_width/display_height,
falling back to the old fixed pixel defaults only for maps with neither) —
see _effective_bounds()/_canonical_diagonal_px() there. Every threshold is
clamped to never be smaller than the old fixed defaults, so this only ever
widens what used to propose nothing, never narrows existing behavior.

Covers the 8 required scenarios:
  1. Nearest hallway proposal beyond the old fixed 600px cutoff.
  2. Low-confidence ("farther candidate") proposal, plus direct unit tests
     of the confidence-tier/threshold-scaling logic itself.
  3. Same-map/same-floor enforcement still holds after widening the cutoff.
  4. No room-to-room proposal, even with the widened cutoff.
  5. Apply creates the accepted edge for a pair beyond the old cutoff.
  6. Preview performs no database writes.
  7. Existing manually-drawn edges remain unchanged after Apply.
  8. No duplicate edges are created.

Run with: pytest backend/tests/test_auto_connect_scale_aware_threshold.py -v
"""

import pytest

from beanie import PydanticObjectId

from tests.test_api_integration import auth_headers, create_admin_and_get_token

from models.map_model import Map
from services.auto_connect_destinations_service import (
    _confidence_tier,
    _effective_bounds,
    HIGH_CONFIDENCE_MAX_PX,
    MEDIUM_CONFIDENCE_MAX_PX,
    MAX_DISTANCE_PX_DEFAULT,
)


PREVIEW_URL = "/api/route-edges/auto-connect-destinations/preview"
APPLY_URL = "/api/route-edges/auto-connect-destinations/apply"

# diagonal = hypot(4000, 3000) = 5000. Chosen so every threshold lands on
# a clean, easy-to-assert-against number:
#   high_max   = max(5000 * 0.05, 150) = 250
#   medium_max = max(5000 * 0.18, 390) = 900
#   hard_safety = max(5000 * 0.60, 600) = 3000
BIG_MAP_WIDTH = 4000
BIG_MAP_HEIGHT = 3000


# ---------------------------------------------------------
# Helpers (local copies, matching the established per-file convention —
# see tests/test_auto_connect_destinations.py).
# ---------------------------------------------------------

def _create_map(client, token, title="Scale Aware Test Map", floor=None, building_id=None):
    payload = {"title": title, "floor": floor}
    if building_id:
        payload["building_id"] = building_id
    response = client.post("/api/maps", json=payload, headers=auth_headers(token))
    assert response.status_code == 201, response.text
    return response.json()


async def _set_canonical_dimensions(map_id, width, height):
    # Direct model manipulation — there is no public API for setting
    # source_width/height outside real image upload processing, matching
    # the established pattern in tests/test_batch_destination_placement.py.
    map_doc = await Map.get(PydanticObjectId(map_id))
    map_doc.source_width = width
    map_doc.source_height = height
    await map_doc.save()


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


def _list_edges(client, token, map_id):
    response = client.get(
        "/api/route-edges",
        params={"map_id": map_id},
        headers=auth_headers(token),
    )
    assert response.status_code == 200, response.text
    return response.json()


def _find_proposal(preview_result, destination_point_id):
    for proposal in preview_result["proposals"]:
        if proposal["destination_point_id"] == destination_point_id:
            return proposal
    return None


# ===========================================================
# Pure unit tests of the threshold-scaling logic itself
# (no DB / HTTP round trip needed — these pin down the exact numbers).
# ===========================================================

def test_confidence_tier_bands_are_high_medium_low():
    assert _confidence_tier(50.0, HIGH_CONFIDENCE_MAX_PX, MEDIUM_CONFIDENCE_MAX_PX) == "high"
    assert _confidence_tier(200.0, HIGH_CONFIDENCE_MAX_PX, MEDIUM_CONFIDENCE_MAX_PX) == "medium"
    assert _confidence_tier(1000.0, HIGH_CONFIDENCE_MAX_PX, MEDIUM_CONFIDENCE_MAX_PX) == "low"


def test_effective_bounds_scale_with_canonical_image_diagonal():
    big_map = Map(title="Big Map", source_width=BIG_MAP_WIDTH, source_height=BIG_MAP_HEIGHT)
    high_max_px, medium_max_px, hard_safety_max_px = _effective_bounds(big_map, None)

    assert hard_safety_max_px == pytest.approx(3000.0)
    assert high_max_px == pytest.approx(250.0)
    assert medium_max_px == pytest.approx(900.0)


def test_effective_bounds_falls_back_without_canonical_dimensions():
    legacy_map = Map(title="Legacy Map")  # no source_width/source_height
    high_max_px, medium_max_px, hard_safety_max_px = _effective_bounds(legacy_map, None)

    assert hard_safety_max_px == MAX_DISTANCE_PX_DEFAULT
    assert high_max_px == HIGH_CONFIDENCE_MAX_PX
    assert medium_max_px == MEDIUM_CONFIDENCE_MAX_PX


def test_effective_bounds_never_shrinks_below_old_fixed_defaults():
    # A tiny canonical image (smaller than the old fixed defaults) must
    # still clamp UP to the old defaults — this fix only ever widens the
    # old cutoff, it must never narrow it for any map.
    tiny_map = Map(title="Tiny Map", source_width=100, source_height=100)
    high_max_px, medium_max_px, hard_safety_max_px = _effective_bounds(tiny_map, None)

    assert hard_safety_max_px == MAX_DISTANCE_PX_DEFAULT
    assert high_max_px == HIGH_CONFIDENCE_MAX_PX
    assert medium_max_px == MEDIUM_CONFIDENCE_MAX_PX


# ===========================================================
# 1. Nearest hallway proposal beyond the old fixed 600px cutoff.
# ===========================================================

async def test_nearest_hallway_proposed_beyond_old_fixed_cutoff(client):
    token, _ = create_admin_and_get_token(client, role="super_admin", email="sat1@example.com")
    map_item = _create_map(client, token)
    await _set_canonical_dimensions(map_item["id"], BIG_MAP_WIDTH, BIG_MAP_HEIGHT)

    room = _create_point(client, token, map_item["id"], "Distant Room", 100, 100, point_type="room")
    # 850px away — beyond the OLD fixed 600px cutoff (would have been
    # "no_candidate" before this fix), well within the new hard safety
    # ceiling of 3000px for this map's canonical dimensions.
    hallway = _create_point(client, token, map_item["id"], "Distant Hallway", 100, 950, point_type="hallway")

    result = _preview(client, token, map_item["id"])
    proposal = _find_proposal(result, room["id"])

    assert proposal is not None
    assert proposal["status"] == "proposed"
    assert proposal["proposed_candidate_id"] == hallway["id"]
    assert proposal["candidates"][0]["distance_px"] == pytest.approx(850.0, abs=0.5)
    assert proposal["candidates"][0]["distance_px"] > 600.0
    assert result["summary"]["proposed"] >= 1
    assert result["summary"]["no_candidate"] == 0


# ===========================================================
# 2. Low-confidence ("farther candidate") proposal is still returned,
#    with correct nearest-distance/hard-safety diagnostics (item 8).
# ===========================================================

async def test_farther_candidate_still_proposed_with_diagnostics(client):
    token, _ = create_admin_and_get_token(client, role="super_admin", email="sat2@example.com")
    map_item = _create_map(client, token)
    await _set_canonical_dimensions(map_item["id"], BIG_MAP_WIDTH, BIG_MAP_HEIGHT)

    room = _create_point(client, token, map_item["id"], "Far Room", 0, 0, point_type="room")
    # 2000px away — beyond the medium-confidence tier (900px for this
    # map), but comfortably within the 3000px hard safety ceiling. Must
    # still be proposed, never silently dropped.
    hallway = _create_point(client, token, map_item["id"], "Far Hallway", 2000, 0, point_type="hallway")

    result = _preview(client, token, map_item["id"])
    proposal = _find_proposal(result, room["id"])

    assert proposal is not None
    assert proposal["status"] == "proposed"
    assert proposal["proposed_candidate_id"] == hallway["id"]
    # No source image was uploaded for this test map, so wall geometry is
    # genuinely unavailable — confidence is "needs_review" here, never a
    # falsely-precise "high" (Section 7's existing rule, unchanged by this
    # fix). Distance-tier-wise this candidate is "low" (see the direct
    # _confidence_tier unit tests above for that logic in isolation).
    assert proposal["confidence"] in ("low", "needs_review")
    assert proposal["confidence"] != "high"
    # Item 3/8: actual nearest distance and the hard safety ceiling used
    # for this scan are both always reported.
    assert proposal["nearest_distance_px"] == pytest.approx(2000.0, abs=0.5)
    assert proposal["max_hard_distance_px"] == pytest.approx(3000.0, abs=0.5)
    assert proposal["destination_x"] == pytest.approx(0.0)
    assert proposal["destination_y"] == pytest.approx(0.0)
    assert proposal["candidates"][0]["x"] == pytest.approx(2000.0)
    assert proposal["candidates"][0]["y"] == pytest.approx(0.0)


# ===========================================================
# 3. Same-map/same-floor enforcement still holds after widening the
#    threshold — a widened hard safety ceiling must never let a
#    different-floor or different-Map point slip through.
# ===========================================================

async def test_same_map_same_floor_still_enforced_with_widened_threshold(client):
    token, _ = create_admin_and_get_token(client, role="super_admin", email="sat3@example.com")
    map_a = _create_map(client, token, title="Scale Map A")
    map_b = _create_map(client, token, title="Scale Map B")
    await _set_canonical_dimensions(map_a["id"], BIG_MAP_WIDTH, BIG_MAP_HEIGHT)
    await _set_canonical_dimensions(map_b["id"], BIG_MAP_WIDTH, BIG_MAP_HEIGHT)

    room = _create_point(client, token, map_a["id"], "Room On Map A", 100, 100, floor=0, point_type="room")
    # Same pixel coordinates, well within the new widened hard safety
    # radius — but a genuinely different Map document, so must still
    # never be treated as a candidate.
    _create_point(client, token, map_b["id"], "Hallway On Map B", 100, 100, floor=0, point_type="hallway")
    # Same map, same coordinates, but a different floor — must also still
    # never be treated as a candidate.
    _create_point(client, token, map_a["id"], "Hallway On Different Floor", 105, 105, floor=1, point_type="hallway")

    result = _preview(client, token, map_a["id"])
    proposal = _find_proposal(result, room["id"])

    assert proposal is not None
    assert proposal["status"] == "no_candidate"
    assert proposal["candidates"] == []


# ===========================================================
# 4. No room-to-room proposal, even with the widened threshold.
# ===========================================================

async def test_no_room_to_room_proposal_with_widened_threshold(client):
    token, _ = create_admin_and_get_token(client, role="super_admin", email="sat4@example.com")
    map_item = _create_map(client, token)
    await _set_canonical_dimensions(map_item["id"], BIG_MAP_WIDTH, BIG_MAP_HEIGHT)

    room_a = _create_point(client, token, map_item["id"], "Room A", 500, 500, point_type="room")
    # Deliberately much closer than the real hallway, so a naive
    # nearest-neighbor implementation without type filtering would wrongly
    # pick it — this must never happen regardless of the widened cutoff.
    room_b = _create_point(client, token, map_item["id"], "Room B Very Close", 505, 500, point_type="room")
    hallway = _create_point(client, token, map_item["id"], "Real Hallway", 1300, 500, point_type="hallway")

    result = _preview(client, token, map_item["id"])
    proposal = _find_proposal(result, room_a["id"])

    assert proposal is not None
    assert proposal["status"] == "proposed"
    candidate_ids = [c["point_id"] for c in proposal["candidates"]]
    assert room_b["id"] not in candidate_ids
    assert proposal["proposed_candidate_id"] == hallway["id"]


# ===========================================================
# 5. Apply creates the accepted edge for a pair beyond the old cutoff.
# ===========================================================

async def test_apply_creates_accepted_edge_beyond_old_cutoff(client):
    token, _ = create_admin_and_get_token(client, role="super_admin", email="sat5@example.com")
    map_item = _create_map(client, token)
    await _set_canonical_dimensions(map_item["id"], BIG_MAP_WIDTH, BIG_MAP_HEIGHT)

    room = _create_point(client, token, map_item["id"], "Room To Connect", 0, 0, point_type="room")
    hallway = _create_point(client, token, map_item["id"], "Hallway To Connect", 900, 0, point_type="hallway")

    preview_result = _preview(client, token, map_item["id"])
    proposal = _find_proposal(preview_result, room["id"])
    assert proposal is not None
    assert proposal["status"] == "proposed"

    apply_result = _apply(
        client,
        token,
        map_item["id"],
        accepted=[{"destination_point_id": room["id"], "corridor_point_id": hallway["id"]}],
    )

    assert apply_result["requested"] == 1
    assert apply_result["created"] == 1
    assert len(apply_result["created_edge_ids"]) == 1

    edges = _list_edges(client, token, map_item["id"])
    assert len(edges) == 1
    assert {edges[0]["from_point_id"], edges[0]["to_point_id"]} == {room["id"], hallway["id"]}


# ===========================================================
# 6. Preview performs no database writes.
# ===========================================================

async def test_preview_performs_no_writes_with_widened_threshold(client):
    token, _ = create_admin_and_get_token(client, role="super_admin", email="sat6@example.com")
    map_item = _create_map(client, token)
    await _set_canonical_dimensions(map_item["id"], BIG_MAP_WIDTH, BIG_MAP_HEIGHT)

    room = _create_point(client, token, map_item["id"], "No Write Room", 0, 0, point_type="room")
    _create_point(client, token, map_item["id"], "No Write Hallway", 1800, 0, point_type="hallway")

    edges_before = _list_edges(client, token, map_item["id"])
    points_before = client.get("/api/route-points", params={"map_id": map_item["id"]}).json()

    result = _preview(client, token, map_item["id"])
    proposal = _find_proposal(result, room["id"])
    assert proposal is not None
    assert proposal["status"] == "proposed"

    edges_after = _list_edges(client, token, map_item["id"])
    points_after = client.get("/api/route-points", params={"map_id": map_item["id"]}).json()

    assert edges_before == edges_after == []
    assert len(points_after) == len(points_before) == 2


# ===========================================================
# 7. Existing manually-drawn edges remain unchanged after Apply.
# ===========================================================

async def test_existing_manual_edge_unchanged_after_apply(client):
    token, _ = create_admin_and_get_token(client, role="super_admin", email="sat7@example.com")
    map_item = _create_map(client, token)
    await _set_canonical_dimensions(map_item["id"], BIG_MAP_WIDTH, BIG_MAP_HEIGHT)

    # An unrelated, already-connected pair — a manually drawn edge that
    # Auto Connect must never touch, modify, or remove.
    manual_room = _create_point(client, token, map_item["id"], "Manually Connected Room", 3500, 2500, point_type="room")
    manual_hallway = _create_point(client, token, map_item["id"], "Manually Connected Hallway", 3520, 2500, point_type="hallway")
    manual_edge = _create_edge(client, token, map_item["id"], manual_room["id"], manual_hallway["id"])

    # The actual destination/candidate this test's Apply call targets.
    room = _create_point(client, token, map_item["id"], "New Room", 0, 0, point_type="room")
    hallway = _create_point(client, token, map_item["id"], "New Hallway", 1000, 0, point_type="hallway")

    _apply(
        client,
        token,
        map_item["id"],
        accepted=[{"destination_point_id": room["id"], "corridor_point_id": hallway["id"]}],
    )

    edges = _list_edges(client, token, map_item["id"])
    assert len(edges) == 2

    still_present = next((e for e in edges if e["id"] == manual_edge["id"]), None)
    assert still_present is not None
    assert still_present["from_point_id"] == manual_edge["from_point_id"]
    assert still_present["to_point_id"] == manual_edge["to_point_id"]
    assert still_present["edge_type"] == manual_edge["edge_type"]


# ===========================================================
# 8. No duplicate edges are created.
# ===========================================================

async def test_no_duplicate_edge_created_with_widened_threshold(client):
    token, _ = create_admin_and_get_token(client, role="super_admin", email="sat8@example.com")
    map_item = _create_map(client, token)
    await _set_canonical_dimensions(map_item["id"], BIG_MAP_WIDTH, BIG_MAP_HEIGHT)

    room = _create_point(client, token, map_item["id"], "Dup Check Room", 0, 0, point_type="room")
    hallway = _create_point(client, token, map_item["id"], "Dup Check Hallway", 1200, 0, point_type="hallway")
    _create_edge(client, token, map_item["id"], room["id"], hallway["id"])

    apply_result = _apply(
        client,
        token,
        map_item["id"],
        accepted=[{"destination_point_id": room["id"], "corridor_point_id": hallway["id"]}],
    )

    assert apply_result["created"] == 0
    assert apply_result["skipped_existing"] == 1

    edges = _list_edges(client, token, map_item["id"])
    assert len(edges) == 1
