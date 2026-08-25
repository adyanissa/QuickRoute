"""
Acceptance tests for the Auto Connect APPLY / persistence path.

THE REPORTED FAILURE
--------------------
On a deployed Floor 2:

    Scanned 50 · Already connected 47 · Proposed 3 · No corridor point 0

All three proposals High confidence and valid (one of them
connection_type = corridor_edge_split, clear line true, on walkable graph
true, nearest corridor 20.23 px). The admin clicks "Accept all
high-confidence proposals", then "Review complete", then confirms. Closing
and reopening Auto Connect shows *Already connected 47 · Proposed 3* again
— the identical three proposals, forever.

ROOT CAUSE
----------
routes/route_edge_routes.find_duplicate_edge matched ANY stored RouteEdge
document, active or not. Several paths in this system retire an edge by
setting is_active = False rather than deleting it — legacy repair does
exactly that to an invalid Room-to-Room or stale attachment, and
_split_corridor_edge_for_attachment does it to the original corridor edge —
because deactivation is reversible and auditable.

Every READER of the graph correctly ignores those documents, so the room is
genuinely disconnected and is correctly proposed. The WRITE path then found
the dead edge, reported "skipped (already connected)", and wrote nothing.
Silent, permanent, and it defeated the bulk retry and legacy-repair
reconnection in exactly the same way.

Two further preview/apply disagreements are covered here too, because each
one produces the identical silent loop for a different proposal:

  * apply compared floors with a raw `!=` while the preview used the shared
    _floors_are_compatible rule (which knows that when Map.floor is set,
    every RoutePoint on it is on that floor by construction);
  * apply revalidated geometry with the legacy 900 px gate while the
    preview had moved onto the strict full-resolution path.

Nothing about proposal generation is exercised or changed here.

Run with: pytest backend/tests/test_auto_connect_apply_persistence.py -v
"""

import cv2
import numpy as np
import pytest

from tests.test_api_integration import auth_headers, create_admin_and_get_token

from models.route_edge_model import RouteEdge
from models.route_point_model import RoutePoint


PREVIEW_URL = "/api/route-edges/auto-connect-destinations/preview"
APPLY_URL = "/api/route-edges/auto-connect-destinations/apply"

CORRIDOR_Y = 1000
# Rooms sit above the corridor. Well over the 6 px dedup tolerance apart.
ROOM_Y = 940


# ---------------------------------------------------------
# Helpers (local copies, per this suite's established convention).
# ---------------------------------------------------------

def _create_map(client, token, title="Floor 2", floor=None):
    response = client.post(
        "/api/maps", json={"title": title, "floor": floor}, headers=auth_headers(token)
    )
    assert response.status_code == 201, response.text
    return response.json()


def _create_point(client, token, map_id, name, x, y, point_type="hallway", floor=None):
    response = client.post(
        "/api/route-points",
        json={
            "map_id": map_id,
            "name": name,
            "x": x,
            "y": y,
            "point_type": point_type,
            "floor": floor,
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
    """A COMPLETELY FRESH read of persisted state — the preview endpoint is
    documented as 100% read-only and rebuilds its whole view from the
    database on every call, which is exactly what reopening the panel in
    the admin UI does."""
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


def _accepted_pair(proposal):
    """Exactly what the review panel sends for a proposal's default
    candidate — a corridor edge attachment carries the edge id and the
    projected position, everything else carries a point id."""
    candidate = proposal["candidates"][0]

    if candidate["target_type"] == "corridor_edge":
        return {
            "destination_point_id": proposal["destination_point_id"],
            "corridor_edge_id": candidate["corridor_edge_id"],
            "attachment_x": candidate["attachment_x"],
            "attachment_y": candidate["attachment_y"],
        }

    return {
        "destination_point_id": proposal["destination_point_id"],
        "corridor_point_id": candidate["point_id"],
    }


def _install_blank_plan(monkeypatch, tmp_path, map_id):
    """Give the map a readable source image with no walls on it.

    Without one, wall_mask_available is False and every proposal is forced
    to "needs_review" confidence — so the reported state (three HIGH
    confidence proposals) could not be reproduced at all. With a blank plan
    the geometry checks run and pass, which is what the reported map does
    for these three rooms too: clear line true.
    """
    import services.graph_connection_service as graph_connection_service
    from services.strict_geometry_service import clear_strict_mask_cache

    monkeypatch.setattr("services.graph_connection_service.SOURCE_DIR", tmp_path)
    monkeypatch.setattr("services.strict_geometry_service.SOURCE_DIR", tmp_path)
    graph_connection_service._WALL_MASK_CACHE.clear()
    clear_strict_mask_cache()

    cv2.imwrite(
        str(tmp_path / f"{map_id}.png"),
        np.full((1400, 2600), 255, dtype=np.uint8),
    )


async def _build_floor_two(client, token, monkeypatch, tmp_path, connected_rooms=47):
    """The reported starting state: `connected_rooms` destinations already
    wired to the corridor, plus three that are not — one for each of the
    three ways apply used to silently refuse a valid proposal.

    Returns (map_id, {label: destination_point_id}).
    """

    map_item = _create_map(client, token)
    map_id = map_item["id"]
    _install_blank_plan(monkeypatch, tmp_path, map_id)

    # A corridor of hallway nodes, joined end to end. The last span is left
    # deliberately long so a room beside its MIDDLE projects onto the edge
    # rather than onto either endpoint.
    nodes = []
    for index in range(6):
        nodes.append(
            _create_point(
                client, token, map_id, f"Hall {index}", 200 + index * 200, CORRIDOR_Y
            )
        )
    long_span = _create_point(client, token, map_id, "Hall End", 2400, CORRIDOR_Y)
    nodes.append(long_span)

    for a, b in zip(nodes, nodes[1:]):
        _create_edge(client, token, map_id, a["id"], b["id"])

    # The long edge is the last one: 1200 -> 2400.
    long_edge = await RouteEdge.find_one(
        {
            "map_id": map_id,
            "from_point_id": nodes[-2]["id"],
            "to_point_id": nodes[-1]["id"],
        }
    )
    assert long_edge is not None

    destinations = {}

    # ── the already-connected majority ────────────────────────────────
    for index in range(connected_rooms):
        room = _create_point(
            client,
            token,
            map_id,
            f"Office {100 + index}",
            210 + index * 20,
            ROOM_Y,
            point_type="room",
        )
        _create_edge(client, token, map_id, room["id"], nodes[index % 5]["id"])

    # ── 1. the edge-split case ────────────────────────────────────────
    # Beside the middle of the long span, far from both of its endpoints.
    edge_split_room = _create_point(
        client, token, map_id, "Office 245", 1800, CORRIDOR_Y - 20, point_type="room"
    )
    destinations["edge_split"] = edge_split_room["id"]

    # ── 2. the reported root cause ────────────────────────────────────
    # A room whose only edge was RETIRED (is_active = False) exactly the way
    # services/legacy_edge_repair_service.py retires an invalid one.
    retired_room = _create_point(
        client, token, map_id, "Office 246", 260, ROOM_Y - 40, point_type="room"
    )
    destinations["retired_edge"] = retired_room["id"]
    dead_edge = _create_edge(client, token, map_id, retired_room["id"], nodes[0]["id"])
    dead_doc = await RouteEdge.get(dead_edge["id"])
    dead_doc.is_active = False
    await dead_doc.save()

    # ── 3. an ordinary never-connected room ───────────────────────────
    plain_room = _create_point(
        client, token, map_id, "Office 247", 620, ROOM_Y - 40, point_type="room"
    )
    destinations["plain"] = plain_room["id"]

    return map_id, destinations


# =========================================================
# 1. THE REPORTED CASE, end to end.
# =========================================================

@pytest.mark.asyncio
async def test_apply_all_persists_and_the_proposals_do_not_come_back(client, tmp_path, monkeypatch):
    token, _ = create_admin_and_get_token(client, email="persist1@example.com")
    map_id, destinations = await _build_floor_two(client, token, monkeypatch, tmp_path)

    # ── initial state ─────────────────────────────────────────────────
    before = _preview(client, token, map_id)
    assert before["summary"]["scanned"] == 50
    assert before["summary"]["already_connected"] == 47
    assert before["summary"]["proposed"] == 3
    assert before["summary"]["no_candidate"] == 0

    proposals = [_find(before, pid) for pid in destinations.values()]
    assert all(p is not None and p["status"] == "proposed" for p in proposals)
    assert all(p["confidence"] == "high" for p in proposals), [
        p["confidence"] for p in proposals
    ]

    # At least one of them must be the corridor_edge_split case.
    split = _find(before, destinations["edge_split"])
    assert split["connection_type"] == "corridor_edge_split"
    assert split["candidates"][0]["target_type"] == "corridor_edge"
    assert split["candidates"][0]["corridor_edge_id"]
    assert split["graph_connected"] is True
    assert split["clear_line"] is True

    # ── accept all three ──────────────────────────────────────────────
    result = _apply(
        client, token, map_id, [_accepted_pair(p) for p in proposals]
    )

    assert result["requested"] == 3
    assert result["created"] == 3, result
    assert result["skipped_existing"] == 0, result
    assert result["rejected_invalid"] == 0, result
    assert result["failed"] == 0, result
    assert result["corridor_junctions_created"] >= 1, result

    # ── a completely fresh read of persisted state ────────────────────
    after = _preview(client, token, map_id)

    assert after["summary"]["already_connected"] == 50
    assert after["summary"]["proposed"] == 0
    assert after["summary"]["no_candidate"] == 0
    assert after["summary"]["needs_review"] == 0

    for pid in destinations.values():
        assert _find(after, pid) is None, "an accepted proposal came back"


# =========================================================
# 2. The written edges are real, active, and on the right points.
# =========================================================

@pytest.mark.asyncio
async def test_the_written_edges_are_active_and_correctly_attached(client, tmp_path, monkeypatch):
    token, _ = create_admin_and_get_token(client, email="persist2@example.com")
    map_id, destinations = await _build_floor_two(client, token, monkeypatch, tmp_path)

    before = _preview(client, token, map_id)
    split = _find(before, destinations["edge_split"])
    original_edge_id = split["candidates"][0]["corridor_edge_id"]

    result = _apply(
        client,
        token,
        map_id,
        [_accepted_pair(_find(before, pid)) for pid in destinations.values()],
    )
    assert result["created"] == 3, result

    for edge_id in result["created_edge_ids"]:
        edge = await RouteEdge.get(edge_id)
        assert edge is not None
        assert edge.is_active is True
        assert edge.edge_type == "walkway"
        assert edge.map_id == map_id

    # The junction really exists, and the room's own canonical destination
    # point is what is joined to it — the marker is never moved or replaced.
    assert result["created_point_ids"]

    junctions = [await RoutePoint.get(pid) for pid in result["created_point_ids"]]
    for candidate in junctions:
        assert candidate is not None
        assert candidate.is_active is True
        assert candidate.point_type == "junction"

    # The one this room was attached to.
    junction = next(
        j
        for j in junctions
        if round(float(j.x)) == 1800 and round(float(j.y)) == CORRIDOR_Y
    )

    room_point = await RoutePoint.get(destinations["edge_split"])
    assert float(room_point.x) == pytest.approx(1800)
    assert float(room_point.y) == pytest.approx(CORRIDOR_Y - 20)

    join = await RouteEdge.find_one(
        {
            "map_id": map_id,
            "is_active": True,
            "$or": [
                {
                    "from_point_id": destinations["edge_split"],
                    "to_point_id": str(junction.id),
                },
                {
                    "from_point_id": str(junction.id),
                    "to_point_id": destinations["edge_split"],
                },
            ],
        }
    )
    assert join is not None, "the room was not joined to the new junction"

    # The original corridor edge was split: deactivated, never deleted, and
    # replaced by two active corridor edges through the junction.
    original = await RouteEdge.get(original_edge_id)
    assert original is not None, "the original edge must be retired, not deleted"
    assert original.is_active is False

    replacements = await RouteEdge.find(
        {
            "map_id": map_id,
            "is_active": True,
            "$or": [
                {"from_point_id": str(junction.id)},
                {"to_point_id": str(junction.id)},
            ],
        }
    ).to_list()
    # Two corridor replacements plus the room's own join. (A later split of
    # one of those replacements would add more, so this is a floor.)
    assert len(replacements) >= 3


# =========================================================
# 3. A retired edge must never be mistaken for a live one.
#    THE root cause, isolated.
# =========================================================

@pytest.mark.asyncio
async def test_a_deactivated_edge_does_not_block_reconnection(client):
    token, _ = create_admin_and_get_token(client, email="persist3@example.com")

    map_item = _create_map(client, token)
    map_id = map_item["id"]
    hall_a = _create_point(client, token, map_id, "Hall A", 100, 100)
    hall_b = _create_point(client, token, map_id, "Hall B", 500, 100)
    _create_edge(client, token, map_id, hall_a["id"], hall_b["id"])

    room = _create_point(client, token, map_id, "Office 245", 110, 160, point_type="room")

    retired = _create_edge(client, token, map_id, room["id"], hall_a["id"])
    retired_doc = await RouteEdge.get(retired["id"])
    retired_doc.is_active = False
    await retired_doc.save()

    proposal = _find(_preview(client, token, map_id), room["id"])
    assert proposal is not None and proposal["status"] == "proposed"

    result = _apply(client, token, map_id, [_accepted_pair(proposal)])

    # This is the exact assertion that failed before the fix: apply reported
    # skipped_existing 1 / created 0, because find_duplicate_edge matched the
    # retired document.
    assert result["skipped_existing"] == 0, result
    assert result["created"] == 1, result

    assert _find(_preview(client, token, map_id), room["id"]) is None
    # ...and the retired edge is still retired. Nothing was resurrected.
    assert (await RouteEdge.get(retired["id"])).is_active is False


# =========================================================
# 4. Individual Accept.
# =========================================================

@pytest.mark.asyncio
async def test_individual_accept_persists_only_that_one(client, tmp_path, monkeypatch):
    token, _ = create_admin_and_get_token(client, email="persist4@example.com")
    map_id, destinations = await _build_floor_two(client, token, monkeypatch, tmp_path)

    before = _preview(client, token, map_id)
    assert before["summary"]["proposed"] == 3

    one = _find(before, destinations["edge_split"])
    result = _apply(client, token, map_id, [_accepted_pair(one)])
    assert result["created"] == 1, result

    after = _preview(client, token, map_id)
    assert after["summary"]["already_connected"] == 48
    assert after["summary"]["proposed"] == 2
    assert _find(after, destinations["edge_split"]) is None
    # The two the admin did NOT accept are untouched and still offered.
    assert _find(after, destinations["retired_edge"]) is not None
    assert _find(after, destinations["plain"]) is not None

    # Accepting the remaining two afterwards finishes the job.
    remaining = [
        _accepted_pair(_find(after, destinations["retired_edge"])),
        _accepted_pair(_find(after, destinations["plain"])),
    ]
    assert _apply(client, token, map_id, remaining)["created"] == 2

    final = _preview(client, token, map_id)
    assert final["summary"]["already_connected"] == 50
    assert final["summary"]["proposed"] == 0


# =========================================================
# 5. Applying twice is a no-op, not a duplicate.
# =========================================================

@pytest.mark.asyncio
async def test_re_applying_the_same_pair_is_skipped_not_duplicated(client, tmp_path, monkeypatch):
    token, _ = create_admin_and_get_token(client, email="persist5@example.com")
    map_id, destinations = await _build_floor_two(client, token, monkeypatch, tmp_path)

    before = _preview(client, token, map_id)
    pair = _accepted_pair(_find(before, destinations["plain"]))

    assert _apply(client, token, map_id, [pair])["created"] == 1

    # The same pair again: now there IS a live edge, so this must be
    # skipped. The is_active filter must not have broken duplicate
    # detection for real duplicates.
    second = _apply(client, token, map_id, [pair])
    assert second["created"] == 0, second
    assert second["skipped_existing"] == 1, second

    live = await RouteEdge.find(
        {
            "map_id": map_id,
            "is_active": True,
            "$or": [
                {
                    "from_point_id": destinations["plain"],
                    "to_point_id": pair["corridor_point_id"],
                },
                {
                    "from_point_id": pair["corridor_point_id"],
                    "to_point_id": destinations["plain"],
                },
            ],
        }
    ).to_list()
    assert len(live) == 1, "a duplicate edge was written"


# =========================================================
# 6. Apply must never refuse silently.
# =========================================================

@pytest.mark.asyncio
async def test_a_refused_pair_says_why(client, tmp_path, monkeypatch):
    token, _ = create_admin_and_get_token(client, email="persist6@example.com")
    map_id, destinations = await _build_floor_two(client, token, monkeypatch, tmp_path)

    before = _preview(client, token, map_id)
    pair = _accepted_pair(_find(before, destinations["plain"]))

    # A corridor point from a different map — the classic forged/stale pair.
    other_map = _create_map(client, token, title="Another floor")
    foreign = _create_point(client, token, other_map["id"], "Foreign", 50, 50)

    result = _apply(
        client,
        token,
        map_id,
        [
            {
                "destination_point_id": pair["destination_point_id"],
                "corridor_point_id": foreign["id"],
            }
        ],
    )

    assert result["created"] == 0
    assert result["rejected_invalid"] == 1
    # The part that used to be missing entirely.
    assert result["warnings"], "a refusal must never be silent"
    assert result["rejected_reasons"], result
    assert result["rejected_reasons"][0]["reason"] == "wrong_map"


# =========================================================
# 7. Apply agrees with the preview about geometry.
# =========================================================

@pytest.mark.asyncio
async def test_apply_accepts_a_doorway_resolved_proposal_the_preview_made(
    client, tmp_path, monkeypatch
):
    """The preview moved onto the strict full-resolution path; apply used to
    re-check with the legacy 900 px gate. A proposal resolved through a real
    doorway was therefore proposed and then silently refused — the same
    permanent loop, from a different cause."""

    import services.graph_connection_service as graph_connection_service
    from services.strict_geometry_service import clear_strict_mask_cache
    from tests.test_doorway_attachment import (
        CORRIDOR_TOP_Y,
        DOOR_THRESHOLD,
        _plan,
    )

    token, _ = create_admin_and_get_token(client, email="persist7@example.com")
    map_item = _create_map(client, token)
    map_id = map_item["id"]

    monkeypatch.setattr("services.graph_connection_service.SOURCE_DIR", tmp_path)
    monkeypatch.setattr("services.strict_geometry_service.SOURCE_DIR", tmp_path)
    graph_connection_service._WALL_MASK_CACHE.clear()
    clear_strict_mask_cache()
    cv2.imwrite(
        str(tmp_path / f"{map_id}.png"), _plan(doors=[(850, 90, DOOR_THRESHOLD)])
    )

    hall_a = _create_point(client, token, map_id, "Hall W", 300, CORRIDOR_TOP_Y + 120)
    hall_b = _create_point(client, token, map_id, "Hall E", 1600, CORRIDOR_TOP_Y + 120)
    _create_edge(client, token, map_id, hall_a["id"], hall_b["id"])

    room = _create_point(
        client,
        token,
        map_id,
        "Electrical Room",
        850,
        CORRIDOR_TOP_Y - 12,
        point_type="room",
    )

    proposal = _find(_preview(client, token, map_id), room["id"])
    assert proposal is not None and proposal["status"] == "proposed"

    result = _apply(client, token, map_id, [_accepted_pair(proposal)])

    assert result["rejected_invalid"] == 0, result
    assert result["created"] == 1, result

    after = _preview(client, token, map_id)
    assert _find(after, room["id"]) is None
    assert after["summary"]["already_connected"] == 1
    assert after["summary"]["proposed"] == 0
