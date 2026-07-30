"""
Tests for the "Walkway edge must connect points on the same floor" 400
regression (Sakara / "Corridor Point 1784655473213-3" on QuickRoute Mall -
Floor 1): both points were visibly loaded on the same active map, but the
backend rejected the edge because their stored RoutePoint.floor values
disagreed (one legacy point had floor=0 or null while the Map itself is
Floor 1).

Root cause: routes/route_edge_routes.py's calculate_edge_distance()
compared the two points' own `floor` fields directly for a walkway edge,
even though both points had already been confirmed to belong to the exact
same Map document (same map_id) a few lines above. A Map represents one
floor — two points sharing its map_id cannot genuinely be on different
floors, so RoutePoint.floor is not the authoritative floor source, Map.floor
is. The fix removes that raw per-point comparison entirely for the
same-map case and instead treats `map_id` as authoritative, matching
routes/route_point_routes.py's create_route_point (which now derives a new
point's floor from its Map rather than trusting the caller) and the new
POST /api/route-points/backfill-floor-from-map repair endpoint (which
corrects already-stored legacy points' floor to match their Map).

Run with: pytest backend/tests/test_route_edge_floor_consistency.py -v
"""

import pytest

from tests.test_api_integration import auth_headers, create_admin_and_get_token

from models.map_model import Map
from models.route_point_model import RoutePoint
from models.route_edge_model import RouteEdge


# ---------------------------------------------------------
# Helpers
# ---------------------------------------------------------

def _create_map(client, token, title="Floor Map", floor=None, building_id=None, campus=None):
    payload = {"title": title, "floor": floor}
    if building_id:
        payload["building_id"] = building_id
    if campus:
        payload["campus"] = campus

    response = client.post("/api/maps", json=payload, headers=auth_headers(token))
    assert response.status_code == 201, response.text
    return response.json()


def _create_point_via_api(client, token, map_id, name, x, y, floor=None, point_type="hallway"):
    """
    Goes through the real POST /api/route-points endpoint — exercises the
    actual "derive floor from Map" fix, so a `floor` passed here is only
    ever a (now-ignored-when-the-Map-has-one) caller hint, never trusted
    verbatim.
    """
    response = client.post(
        "/api/route-points",
        json={"map_id": map_id, "name": name, "x": x, "y": y, "floor": floor, "point_type": point_type},
        headers=auth_headers(token),
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _insert_legacy_point(map_id, name, x, y, floor):
    """
    Inserts a RoutePoint DIRECTLY (bypassing the API's floor-derivation
    fix) to simulate a genuinely legacy stored point whose floor predates
    — or has drifted from — its Map's own floor. This is exactly the
    real-world "Sakara" / "Corridor Point 1784655473213-3" scenario: data
    that already exists with a stale/null floor, not something a
    currently-running, already-fixed API would create today.
    """
    point = RoutePoint(
        map_id=map_id,
        name=name,
        point_type="hallway",
        x=x,
        y=y,
        floor=floor,
        is_accessible=True,
    )
    await point.insert()
    return point


def _create_edge(client, token, map_id, from_point_id, to_point_id, edge_type="walkway"):
    return client.post(
        "/api/route-edges",
        json={
            "map_id": map_id,
            "from_point_id": from_point_id,
            "to_point_id": to_point_id,
            "edge_type": edge_type,
        },
        headers=auth_headers(token),
    )


def _run_backfill(client, token, dry_run=True):
    response = client.post(
        "/api/route-points/backfill-floor-from-map",
        json={"dry_run": dry_run},
        headers=auth_headers(token),
    )
    assert response.status_code == 200, response.text
    return response.json()


# ---------------------------------------------------------
# 1. Same map + both floor 1 → edge allowed
# ---------------------------------------------------------

def test_same_map_both_points_floor_1_edge_allowed(client):
    token, _ = create_admin_and_get_token(client, role="global_manager", email="f1@example.com")

    map_1 = _create_map(client, token, title="QuickRoute Mall - Floor 1", floor=1)
    point_a = _create_point_via_api(client, token, map_1["id"], "Sakara", 100, 100, floor=1)
    point_b = _create_point_via_api(client, token, map_1["id"], "Corridor A", 150, 150, floor=1)

    response = _create_edge(client, token, map_1["id"], point_a["id"], point_b["id"])
    assert response.status_code == 201, response.text
    assert response.json()["distance"] > 0


# ---------------------------------------------------------
# 2. Same map + one point floor null → derive from map and allow
# ---------------------------------------------------------

@pytest.mark.asyncio
async def test_same_map_one_point_floor_null_derives_from_map_and_allows_edge(client):
    token, _ = create_admin_and_get_token(client, role="global_manager", email="f2@example.com")

    map_1 = _create_map(client, token, title="QuickRoute Mall - Floor 1", floor=1)

    # Sakara: a normal, correctly-floored point.
    sakara = _create_point_via_api(client, token, map_1["id"], "Sakara", 100, 100, floor=1)

    # The legacy corridor point: floor is null in storage (exactly the
    # reported "likely floor 0 or null" scenario), inserted directly to
    # bypass the API's own floor-derivation fix and simulate pre-existing
    # legacy data.
    legacy_point = await _insert_legacy_point(
        map_1["id"], "Corridor Point 1784655473213-3", 150, 150, floor=None
    )

    response = _create_edge(client, token, map_1["id"], sakara["id"], str(legacy_point.id))
    assert response.status_code == 201, response.text


# ---------------------------------------------------------
# 3. Same map + stale floor 0 while Map.floor=1 → repair and allow
# ---------------------------------------------------------

@pytest.mark.asyncio
async def test_same_map_stale_floor_0_allows_edge_and_backfill_repairs_it(client):
    token, _ = create_admin_and_get_token(client, role="global_manager", email="f3@example.com")

    map_1 = _create_map(client, token, title="QuickRoute Mall - Floor 1", floor=1)
    sakara = _create_point_via_api(client, token, map_1["id"], "Sakara", 100, 100, floor=1)

    stale_point = await _insert_legacy_point(
        map_1["id"], "Corridor Point 1784655473213-3", 150, 150, floor=0
    )

    # The edge must already be creatable — map_id, not the stale
    # per-point floor, is what makes it valid.
    response = _create_edge(client, token, map_1["id"], sakara["id"], str(stale_point.id))
    assert response.status_code == 201, response.text

    # And the repair endpoint independently corrects the stale value.
    apply_result = _run_backfill(client, token, dry_run=False)
    assert apply_result["points_updated"] >= 1

    refreshed = await RoutePoint.get(stale_point.id)
    assert refreshed.floor == 1


# ---------------------------------------------------------
# 4. Different map_ids → reject
# ---------------------------------------------------------

def test_different_map_ids_rejects_edge(client):
    token, _ = create_admin_and_get_token(client, role="global_manager", email="f4@example.com")

    map_a = _create_map(client, token, title="Map A", floor=1)
    map_b = _create_map(client, token, title="Map B", floor=1)

    point_a = _create_point_via_api(client, token, map_a["id"], "A1", 0, 0, floor=1)
    point_b = _create_point_via_api(client, token, map_b["id"], "B1", 10, 10, floor=1)

    response = _create_edge(client, token, map_a["id"], point_a["id"], point_b["id"])
    assert response.status_code == 400, response.text
    assert "same map" in response.json()["detail"].lower()


# ---------------------------------------------------------
# 5. Different actual floors/maps → reject
# ---------------------------------------------------------

def test_different_floors_and_maps_rejects_edge(client):
    token, _ = create_admin_and_get_token(client, role="global_manager", email="f5@example.com")

    ground = _create_map(client, token, title="QuickRoute Mall - Ground Floor", floor=0)
    floor1 = _create_map(client, token, title="QuickRoute Mall - Floor 1", floor=1)

    ground_point = _create_point_via_api(client, token, ground["id"], "Ground Corridor", 0, 0, floor=0)
    floor1_point = _create_point_via_api(client, token, floor1["id"], "Floor 1 Corridor", 10, 10, floor=1)

    response = _create_edge(client, token, ground["id"], ground_point["id"], floor1_point["id"])
    assert response.status_code == 400, response.text


# ---------------------------------------------------------
# 6. Backfill dry-run changes nothing
# ---------------------------------------------------------

@pytest.mark.asyncio
async def test_backfill_dry_run_changes_nothing(client):
    token, _ = create_admin_and_get_token(client, role="global_manager", email="f6@example.com")

    map_1 = _create_map(client, token, title="QuickRoute Mall - Floor 1", floor=1)
    stale_point = await _insert_legacy_point(map_1["id"], "Stale Point", 5, 5, floor=0)

    result = _run_backfill(client, token, dry_run=True)
    assert result["dry_run"] is True
    assert result["points_needing_update"] >= 1
    assert result["points_updated"] == 0

    unchanged = await RoutePoint.get(stale_point.id)
    assert unchanged.floor == 0  # still stale — dry run wrote nothing


# ---------------------------------------------------------
# 7. Applied backfill is idempotent
# ---------------------------------------------------------

@pytest.mark.asyncio
async def test_backfill_apply_is_idempotent(client):
    token, _ = create_admin_and_get_token(client, role="global_manager", email="f7@example.com")

    map_1 = _create_map(client, token, title="QuickRoute Mall - Floor 1", floor=1)
    stale_point = await _insert_legacy_point(map_1["id"], "Stale Point", 5, 5, floor=0)
    null_point = await _insert_legacy_point(map_1["id"], "Null Floor Point", 6, 6, floor=None)

    first_run = _run_backfill(client, token, dry_run=False)
    assert first_run["points_updated"] == 2

    refreshed_stale = await RoutePoint.get(stale_point.id)
    refreshed_null = await RoutePoint.get(null_point.id)
    assert refreshed_stale.floor == 1
    assert refreshed_null.floor == 1

    # Second run: every point already matches its Map, so nothing changes.
    second_run = _run_backfill(client, token, dry_run=False)
    assert second_run["points_needing_update"] == 0
    assert second_run["points_updated"] == 0

    still_stale = await RoutePoint.get(stale_point.id)
    still_null = await RoutePoint.get(null_point.id)
    assert still_stale.floor == 1
    assert still_null.floor == 1


# ---------------------------------------------------------
# 8. No duplicate points or edges are created
# ---------------------------------------------------------

@pytest.mark.asyncio
async def test_repair_and_edge_creation_never_duplicate_points_or_edges(client):
    token, _ = create_admin_and_get_token(client, role="global_manager", email="f8@example.com")

    map_1 = _create_map(client, token, title="QuickRoute Mall - Floor 1", floor=1)
    sakara = _create_point_via_api(client, token, map_1["id"], "Sakara", 100, 100, floor=1)
    stale_point = await _insert_legacy_point(
        map_1["id"], "Corridor Point 1784655473213-3", 150, 150, floor=0
    )

    points_before = len(await RoutePoint.find({"map_id": map_1["id"]}).to_list())

    # Backfill only ever corrects `floor` in place — never inserts/removes
    # a RoutePoint document.
    _run_backfill(client, token, dry_run=False)
    points_after_backfill = len(await RoutePoint.find({"map_id": map_1["id"]}).to_list())
    assert points_after_backfill == points_before

    # Creating the edge (now allowed) must create exactly one RouteEdge —
    # no duplicate-point workaround, no duplicate edge.
    response = _create_edge(client, token, map_1["id"], sakara["id"], str(stale_point.id))
    assert response.status_code == 201, response.text

    edges = await RouteEdge.find(
        {
            "$or": [
                {"from_point_id": sakara["id"], "to_point_id": str(stale_point.id)},
                {"from_point_id": str(stale_point.id), "to_point_id": sakara["id"]},
            ]
        }
    ).to_list()
    assert len(edges) == 1

    points_after_edge = len(await RoutePoint.find({"map_id": map_1["id"]}).to_list())
    assert points_after_edge == points_before

    # Re-attempting the identical edge must be rejected as a duplicate,
    # never silently create a second one.
    duplicate_response = _create_edge(client, token, map_1["id"], sakara["id"], str(stale_point.id))
    assert duplicate_response.status_code == 409, duplicate_response.text

    edges_after_retry = await RouteEdge.find(
        {
            "$or": [
                {"from_point_id": sakara["id"], "to_point_id": str(stale_point.id)},
                {"from_point_id": str(stale_point.id), "to_point_id": sakara["id"]},
            ]
        }
    ).to_list()
    assert len(edges_after_retry) == 1


# ---------------------------------------------------------
# Bonus: RoutePoint creation derives floor from Map, ignoring a stale
# caller-supplied floor (Section 3 of the fix).
# ---------------------------------------------------------

def test_route_point_creation_derives_floor_from_map_not_caller(client):
    token, _ = create_admin_and_get_token(client, role="global_manager", email="f9@example.com")

    map_1 = _create_map(client, token, title="QuickRoute Mall - Floor 1", floor=1)

    # Caller (simulating stale frontend state) claims floor=0, but the
    # Map is Floor 1 — the Map must win.
    point = _create_point_via_api(client, token, map_1["id"], "Trusts Map Not Caller", 1, 1, floor=0)
    assert point["floor"] == 1


def test_route_point_creation_falls_back_to_caller_floor_when_map_has_none(client):
    token, _ = create_admin_and_get_token(client, role="global_manager", email="f10@example.com")

    # A legacy/ungrouped map that itself has no floor recorded — nothing
    # authoritative to derive from, so the caller's value is used as a
    # last resort rather than fabricating one.
    legacy_map = _create_map(client, token, title="Legacy Standalone Map", floor=None)

    point = _create_point_via_api(client, token, legacy_map["id"], "Legacy Point", 1, 1, floor=3)
    assert point["floor"] == 3
