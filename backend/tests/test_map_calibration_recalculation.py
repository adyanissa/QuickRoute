"""
Tests for the minimal, low-risk map-calibration improvement: after a
successful `calibrate_map_scale()` / `copy_map_calibration()` save, this
Map's own existing WALKWAY RouteEdges have their `distance` safely
recalculated for the new scale — never Dijkstra, never RoutePoints,
never stairs/elevator/escalator/ramp edges (those use
`distance_override`), never an edge belonging to a different Map, and a
single invalid/orphaned edge is skipped rather than failing the whole
(already-saved) calibration.

Run with: pytest backend/tests/test_map_calibration_recalculation.py -v
"""

from datetime import datetime

import pytest

from tests.test_api_integration import auth_headers, create_admin_and_get_token, _create_map, _create_point

from models.route_edge_model import RouteEdge
from models.route_point_model import RoutePoint


def _parse_dt(value):
    # RouteEdgeResponse JSON-encodes naive UTC datetimes without a "Z"/
    # offset suffix; normalize a trailing "Z" just in case so this works
    # regardless of exactly how a given response serialized it.
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _assert_same_datetime(a, b):
    """
    Asserts two ISO datetime strings represent the SAME moment — used to
    prove an edge's `updated_at` was never touched by walkway
    recalculation (edges from another map, and stairs/elevator edges).

    Exact string/object equality is too strict here for a reason that has
    nothing to do with whether the edge was actually modified: MongoDB
    stores datetimes at millisecond resolution, while a freshly-created
    Python `datetime.utcnow()` object (as returned by the create response,
    before ever round-tripping through Mongo) carries microsecond
    precision. Comparing a pre-round-trip value against a post-round-trip
    GET can therefore differ by a fraction of a millisecond even when
    nothing changed. A small tolerance absorbs exactly that artifact
    without weakening the real protection: any genuine recalculation
    moves `updated_at` forward by the time a full test takes to run,
    many orders of magnitude larger than this tolerance.
    """

    delta = abs((_parse_dt(a) - _parse_dt(b)).total_seconds())
    assert delta < 0.01, f"expected matching timestamps (within 10ms), got {a!r} vs {b!r}"


def _create_walkway_edge(client, token, *, map_id, from_id, to_id):
    response = client.post(
        "/api/route-edges",
        json={
            "map_id": map_id,
            "from_point_id": from_id,
            "to_point_id": to_id,
            "edge_type": "walkway",
        },
        headers=auth_headers(token),
    )
    assert response.status_code == 201, response.text
    return response.json()


def _create_stairs_edge(client, token, *, map_id, from_id, to_id, distance_override):
    response = client.post(
        "/api/route-edges",
        json={
            "map_id": map_id,
            "from_point_id": from_id,
            "to_point_id": to_id,
            "edge_type": "stairs",
            "distance_override": distance_override,
        },
        headers=auth_headers(token),
    )
    assert response.status_code == 201, response.text
    return response.json()


def _calibrate(client, token, map_id, *, real_distance_meters, point_b_x=200):
    return client.post(
        f"/api/maps/{map_id}/calibrate-scale",
        json={
            "point_a_x": 0, "point_a_y": 0,
            "point_b_x": point_b_x, "point_b_y": 0,
            "real_distance_meters": real_distance_meters,
        },
        headers=auth_headers(token),
    )


def _get_edge(client, edge_id):
    response = client.get(f"/api/route-edges/{edge_id}")
    assert response.status_code == 200, response.text
    return response.json()


# ---------------------------------------------------------
# 1 — calibration recalculates existing walkway edges
# ---------------------------------------------------------

def test_calibration_recalculates_existing_walkway_edges(client):
    token, _ = create_admin_and_get_token(client, email="calc1@example.com")
    map_item = _create_map(client, token, title="Calc Map 1", campus="Calc Campus 1")

    # RoutePointCreate.name requires min_length=2 — "A"/"B" would be
    # rejected by the real API validation, so these use real 2+ character
    # names instead (matching the other tests in this file, which all
    # already use multi-character point names).
    point_a = _create_point(client, token, map_item["id"], "Map A", 0, 0, floor=0)
    point_b = _create_point(client, token, map_item["id"], "Map B", 100, 0, floor=0)

    edge = _create_walkway_edge(
        client, token, map_id=map_item["id"], from_id=point_a["id"], to_id=point_b["id"]
    )
    # Pre-calibration placeholder scale is 1.0 -> 100 px * 1.0 = 100 m.
    assert edge["distance"] == 100.0

    # point_a=(0,0), point_b=(200,0) -> pixel_distance=200; real=100m ->
    # meters_per_pixel = 0.5.
    calib = _calibrate(client, token, map_item["id"], real_distance_meters=100, point_b_x=200)
    assert calib.status_code == 200, calib.text
    body = calib.json()
    assert abs(body["scale"] - 0.5) < 1e-9

    # Requirement 6 — additive summary on the calibration response.
    assert body["edges_recalculated"] == 1
    assert body["edges_recalculation_skipped"] == 0

    refetched = _get_edge(client, edge["id"])
    # 100 px (unchanged RoutePoint coordinates) * 0.5 m/px = 50.0 m.
    assert refetched["distance"] == 50.0
    # updated_at must have moved forward.
    assert refetched["updated_at"] != edge["updated_at"]


# ---------------------------------------------------------
# 2 — only edges from the calibrated Map are changed
# ---------------------------------------------------------

def test_only_edges_from_the_calibrated_map_are_changed(client):
    token, _ = create_admin_and_get_token(client, email="calc2@example.com")
    map_a = _create_map(client, token, title="Calc Map 2A", campus="Calc Campus 2A")
    map_b = _create_map(client, token, title="Calc Map 2B", campus="Calc Campus 2B")

    a1 = _create_point(client, token, map_a["id"], "A1", 0, 0, floor=0)
    a2 = _create_point(client, token, map_a["id"], "A2", 100, 0, floor=0)
    edge_a = _create_walkway_edge(client, token, map_id=map_a["id"], from_id=a1["id"], to_id=a2["id"])

    b1 = _create_point(client, token, map_b["id"], "B1", 0, 0, floor=0)
    b2 = _create_point(client, token, map_b["id"], "B2", 100, 0, floor=0)
    edge_b = _create_walkway_edge(client, token, map_id=map_b["id"], from_id=b1["id"], to_id=b2["id"])
    # Refetch from MongoDB (not the raw POST-creation response) so the
    # "before" baseline has gone through the exact same round-trip as the
    # "after" GET below — see _assert_same_datetime's docstring.
    edge_b_before = _get_edge(client, edge_b["id"])

    assert edge_a["distance"] == 100.0
    assert edge_b["distance"] == 100.0

    calib = _calibrate(client, token, map_a["id"], real_distance_meters=100, point_b_x=200)
    assert calib.status_code == 200, calib.text
    assert calib.json()["edges_recalculated"] == 1

    # Map A's edge changed...
    assert _get_edge(client, edge_a["id"])["distance"] == 50.0
    # ...but Map B's edge (a different Map entirely) is completely untouched.
    unchanged = _get_edge(client, edge_b["id"])
    assert unchanged["distance"] == 100.0
    _assert_same_datetime(unchanged["updated_at"], edge_b_before["updated_at"])


# ---------------------------------------------------------
# 3 — stairs/elevator edges (distance_override) are unchanged
# ---------------------------------------------------------

def test_stairs_edges_are_never_recalculated(client):
    token, _ = create_admin_and_get_token(client, email="calc3@example.com")
    map_item = _create_map(client, token, title="Calc Map 3", campus="Calc Campus 3")

    walkway_a = _create_point(client, token, map_item["id"], "WA", 0, 0, floor=0)
    walkway_b = _create_point(client, token, map_item["id"], "WB", 100, 0, floor=0)
    walkway_edge = _create_walkway_edge(
        client, token, map_id=map_item["id"], from_id=walkway_a["id"], to_id=walkway_b["id"]
    )

    # Two points on different floors of the same map so a "stairs" edge
    # between them is valid (legacy one-Map-many-floors-via-RoutePoint.floor
    # model — see calculate_edge_distance's own docstring).
    stairs_a = _create_point(client, token, map_item["id"], "SA", 10, 10, floor=0)
    stairs_b = _create_point(client, token, map_item["id"], "SB", 10, 10, floor=1)
    stairs_edge = _create_stairs_edge(
        client, token,
        map_id=map_item["id"], from_id=stairs_a["id"], to_id=stairs_b["id"],
        distance_override=7.5,
    )
    assert stairs_edge["distance"] == 7.5
    assert stairs_edge["distance_override"] == 7.5
    # Refetch from MongoDB (not the raw POST-creation response) — see
    # _assert_same_datetime's docstring for why this matters.
    stairs_edge_before = _get_edge(client, stairs_edge["id"])

    calib = _calibrate(client, token, map_item["id"], real_distance_meters=100, point_b_x=200)
    assert calib.status_code == 200, calib.text
    # Only the one walkway edge was touched — the stairs edge is
    # deliberately excluded from the query entirely (edge_type == "walkway").
    assert calib.json()["edges_recalculated"] == 1

    assert _get_edge(client, walkway_edge["id"])["distance"] == 50.0

    unchanged_stairs = _get_edge(client, stairs_edge["id"])
    assert unchanged_stairs["distance"] == 7.5
    assert unchanged_stairs["distance_override"] == 7.5
    _assert_same_datetime(unchanged_stairs["updated_at"], stairs_edge_before["updated_at"])


# ---------------------------------------------------------
# 4 — an invalid/orphaned edge is skipped safely, never fails calibration
# ---------------------------------------------------------

@pytest.mark.asyncio
async def test_invalid_orphaned_edge_is_skipped_without_failing_calibration(client):
    token, _ = create_admin_and_get_token(client, email="calc4@example.com")
    map_item = _create_map(client, token, title="Calc Map 4", campus="Calc Campus 4")

    good_a = _create_point(client, token, map_item["id"], "GA", 0, 0, floor=0)
    good_b = _create_point(client, token, map_item["id"], "GB", 100, 0, floor=0)
    good_edge = _create_walkway_edge(
        client, token, map_id=map_item["id"], from_id=good_a["id"], to_id=good_b["id"]
    )

    orphan_a = _create_point(client, token, map_item["id"], "OA", 20, 20, floor=0)
    orphan_b = _create_point(client, token, map_item["id"], "OB", 40, 40, floor=0)
    orphan_edge = _create_walkway_edge(
        client, token, map_id=map_item["id"], from_id=orphan_a["id"], to_id=orphan_b["id"]
    )
    orphan_edge_before = _get_edge(client, orphan_edge["id"])

    # Simulate a genuinely orphaned edge (e.g. a point deleted out-of-band)
    # — bypasses the normal API, which never allows this directly.
    orphan_point = await RoutePoint.get(orphan_a["id"])
    await orphan_point.delete()

    calib = _calibrate(client, token, map_item["id"], real_distance_meters=100, point_b_x=200)
    # The calibration itself must succeed regardless of the one bad edge.
    assert calib.status_code == 200, calib.text
    body = calib.json()
    assert body["is_calibrated"] is True
    assert body["edges_recalculated"] == 1
    assert body["edges_recalculation_skipped"] == 1

    # The good edge was recalculated normally...
    assert _get_edge(client, good_edge["id"])["distance"] == 50.0
    # ...the orphaned edge was left completely untouched, never deleted,
    # never recreated.
    still_there = await RouteEdge.get(orphan_edge["id"])
    assert still_there is not None
    still_there_response = _get_edge(client, orphan_edge["id"])
    assert still_there_response["distance"] == orphan_edge_before["distance"]
    _assert_same_datetime(still_there_response["updated_at"], orphan_edge_before["updated_at"])


# ---------------------------------------------------------
# 5 — copy-calibration also recalculates walkway edges
# ---------------------------------------------------------

def test_copy_calibration_also_recalculates_walkway_edges(client):
    token, _ = create_admin_and_get_token(client, email="calc5@example.com")
    source_map = _create_map(client, token, title="Calc Source Map 5", campus="Calc Campus 5S")
    target_map = _create_map(client, token, title="Calc Target Map 5", campus="Calc Campus 5T")

    # Calibrate the source map to a known scale (0.5 m/px, as in test 1).
    source_calib = _calibrate(client, token, source_map["id"], real_distance_meters=100, point_b_x=200)
    assert source_calib.status_code == 200, source_calib.text
    assert abs(source_calib.json()["scale"] - 0.5) < 1e-9

    t_a = _create_point(client, token, target_map["id"], "TA", 0, 0, floor=0)
    t_b = _create_point(client, token, target_map["id"], "TB", 100, 0, floor=0)
    target_edge = _create_walkway_edge(
        client, token, map_id=target_map["id"], from_id=t_a["id"], to_id=t_b["id"]
    )
    # Target map is still at the uncalibrated placeholder scale (1.0).
    assert target_edge["distance"] == 100.0

    copy_response = client.post(
        f"/api/maps/{target_map['id']}/copy-calibration",
        json={"source_map_id": source_map["id"]},
        headers=auth_headers(token),
    )
    assert copy_response.status_code == 200, copy_response.text
    copy_body = copy_response.json()
    assert abs(copy_body["scale"] - 0.5) < 1e-9
    assert copy_body["edges_recalculated"] == 1
    assert copy_body["edges_recalculation_skipped"] == 0

    refetched = _get_edge(client, target_edge["id"])
    assert refetched["distance"] == 50.0


# ---------------------------------------------------------
# 6 — the additive response fields never break a plain map GET
# ---------------------------------------------------------

def test_plain_map_get_response_is_unaffected_by_the_new_fields(client):
    token, _ = create_admin_and_get_token(client, email="calc6@example.com")
    map_item = _create_map(client, token, title="Calc Map 6", campus="Calc Campus 6")

    calib = _calibrate(client, token, map_item["id"], real_distance_meters=100, point_b_x=200)
    assert calib.status_code == 200, calib.text

    # An ordinary GET (which returns the base MapResponse, not
    # MapCalibrationResponse) is completely unaffected — the new fields
    # are additive only on the two calibration endpoints.
    fetched = client.get(f"/api/maps/{map_item['id']}")
    assert fetched.status_code == 200, fetched.text
    fetched_body = fetched.json()
    assert "edges_recalculated" not in fetched_body
    assert "edges_recalculation_skipped" not in fetched_body
    assert abs(fetched_body["scale"] - 0.5) < 1e-9
