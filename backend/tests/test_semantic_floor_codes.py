"""
Tests for "Fix semantic floor identifiers so they match the QuickRoute
Map's real physical floor":

  The AI's own "TEMPORARY EXTERNAL IDS" convention (prompt Section Z)
  tells it to invent placeholder ids like "floor_001" purely for internal
  cross-referencing within one analysis response — that text has no
  relationship to which REAL physical floor a Map represents, so every
  single-floor analysis run against, say, Floor 2 or Floor 3 tended to
  come back with the exact same "floor_001". The one authoritative source
  of "which physical floor is this" is (and always was) Map.floor (see
  models/map_model.py's own docstring). This file proves:

    services/semantic_publication_service.py:
      - compute_authoritative_floor_code(floor_number) -> "floor_{NNN}"
        (Ground Floor/0 -> floor_000, 1 -> floor_001, ... 10 -> floor_010)
      - normalize_floor_codes(reviewed, floor_number=...) renames the
        floor entity AND every place/facility/etc that references it,
        purely/idempotently, never mutating its input
      - GET /api/semantic-analyses/{id}/result returns a VIEW-ONLY
        normalized copy (ai_result itself, "never rewritten", stays
        untouched in the database)
      - PUT .../reviewed-result persists the corrected code on every save
      - POST .../publish normalizes before deriving floor_links, and
        rejects (409) a frontend-supplied floor_links override that
        contradicts the map's own physical floor (Section 8: "the
        backend must calculate the expected code itself and must not
        trust a frontend-supplied value")
      - POST /api/maps/{map_id}/semantic-analysis/repair-floor-codes is
        an explicit, admin-confirmed, scoped-to-one-map repair action for
        analyses/publications that predate this fix — never automatic,
        never touches Rooms/RoutePoints/RouteEdges, and preserves every
        approved name/translation/review status/confidence/geometry.

    services/semantic_destination_service.py:
      - preview/apply already correctly used Map.floor for
        Room.floor/RoutePoint.floor (Section 6 required no change there —
        confirmed unchanged by a dedicated regression test below)
      - apply now REJECTS (never silently mis-tags) any attempt to create
        destinations under a stale/pre-fix floor code; preview WARNS
        (stays read-only) instead of blocking

This file never mutates .env, performs no Git operations, and never
publishes/applies real project data — every Map/analysis/publication used
here is created fresh, in-memory (mongomock), by each test itself.

Run with: pytest backend/tests/test_semantic_floor_codes.py -v
"""

from tests.test_api_integration import auth_headers, create_admin_and_get_token

from models.room_model import Room
from models.route_point_model import RoutePoint
from models.semantic_map_analysis_model import SemanticMapAnalysis
from models.semantic_map_publication_model import SemanticMapPublication, SemanticEntity
from services.semantic_publication_service import (
    compute_authoritative_floor_code,
    normalize_floor_codes,
)


DEST_PREVIEW_URL = "/api/maps/{map_id}/semantic-analysis/destinations/preview"
DEST_APPLY_URL = "/api/maps/{map_id}/semantic-analysis/destinations/apply"
REPAIR_URL = "/api/maps/{map_id}/semantic-analysis/repair-floor-codes"
RESULT_URL = "/api/semantic-analyses/{analysis_id}/result"
PUBLISH_URL = "/api/semantic-analyses/{analysis_id}/publish"


# ---------------------------------------------------------
# Helpers (local copies, matching the established per-file convention —
# see tests/test_semantic_destinations.py / tests/test_semantic_map_
# analysis.py).
# ---------------------------------------------------------


def _create_map(client, token, title="Floor Code Test Map", floor=None, building_id=None):
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


def _semantic_result(
    floor_external_id="floor_001",
    place_ids=("place_001",),
    facility_ids=(),
    review_status="pending",
):
    """Mirrors tests/test_semantic_map_analysis.py's own `_valid_ai_result`
    shape exactly (same required top-level keys), parametrized so each
    test can control the AI's own (unreliable) floor_external_id, which
    entities exist, and their review status."""

    return {
        "schema_version": "quickroute_semantic_map_import_v2",
        "import_draft": {
            "status": "ready_for_review",
            "source_type": "ai_extraction",
            "requires_human_review": True,
            "can_publish_immediately": False,
        },
        "source_documents": [],
        "site": {"site_external_id": "site_001"},
        "buildings": [],
        "zones": [],
        "floors": [{"floor_external_id": floor_external_id}],
        "places": [
            {
                "place_external_id": pid,
                "floor_external_id": floor_external_id,
                "names": {"original": pid, "en": f"Place {pid}"},
                "category": "store",
                "review": {"status": review_status},
            }
            for pid in place_ids
        ],
        "facilities": [
            {
                "facility_external_id": fid,
                "floor_external_id": floor_external_id,
                "names": {"original": fid, "en": f"Facility {fid}"},
                "facility_type": "restroom",
                "review": {"status": review_status},
            }
            for fid in facility_ids
        ],
        "access_points": [],
        "public_areas": [],
        "vertical_connections": [],
        "outdoor_areas": [],
        "parking_areas": [],
        "parking_spaces": [],
        "cross_building_connections": [],
        "review_items": [],
        "unreadable_areas": [],
        "summary": {"total_places": len(place_ids), "total_floors": 1},
        "validation": {},
    }


async def _create_publication(map_id, floor, place_ids=(), facility_ids=(), floor_external_id=None):
    """Builds an ACTIVE SemanticMapPublication whose floor code is already
    authoritative (the normal, post-fix case) unless `floor_external_id`
    is explicitly overridden to simulate legacy/pre-fix data."""

    code = floor_external_id or compute_authoritative_floor_code(floor)
    publication = SemanticMapPublication(
        analysis_id=f"test-analysis-{map_id}",
        prompt_version="test-v1",
        prompt_sha256="0" * 64,
        reviewed_result=_semantic_result(
            floor_external_id=code, place_ids=place_ids, facility_ids=facility_ids, review_status="accepted"
        ),
        quickroute_links={"floor_links": [{"floor_external_id": code, "map_id": map_id}]},
        map_id=map_id,
        is_active=True,
    )
    await publication.insert()
    return publication


def _preview(client, token, map_id, **kwargs):
    response = client.post(
        DEST_PREVIEW_URL.format(map_id=map_id), json=kwargs, headers=auth_headers(token)
    )
    assert response.status_code == 200, response.text
    return response.json()


def _apply(client, token, map_id, accepted, publication_id=None):
    response = client.post(
        DEST_APPLY_URL.format(map_id=map_id),
        json={"publication_id": publication_id, "accepted": accepted},
        headers=auth_headers(token),
    )
    assert response.status_code == 200, response.text
    return response.json()


def _find_proposal(preview_result, semantic_item_id):
    for proposal in preview_result["proposals"]:
        if proposal["semantic_item_id"] == semantic_item_id:
            return proposal
    return None


async def _make_completed_analysis(map_id, ai_result, reviewed_result=None, review_revision=0):
    analysis = SemanticMapAnalysis(
        map_id=map_id,
        scope_type="map",
        source_fingerprint=f"fp-{map_id}",
        prompt_version="v",
        prompt_sha256="h",
        model="claude-sonnet-4-20250514",
        status="completed",
        ai_result=ai_result,
        reviewed_result=reviewed_result,
        review_revision=review_revision,
    )
    await analysis.insert()
    return analysis


# ===========================================================
# PART A — compute_authoritative_floor_code / normalize_floor_codes
# (pure, no DB) — spec items 1-5 (the exact required mapping table) and
# items 6-7 (independence across analyses / every reference updated).
# ===========================================================


# 1. Ground Floor / floor number 0 -> floor_000.
def test_ground_floor_generates_floor_000():
    assert compute_authoritative_floor_code(0) == "floor_000"


# 2. Floor 1 -> floor_001.
def test_floor_1_generates_floor_001():
    assert compute_authoritative_floor_code(1) == "floor_001"


# 3. Floor 2 -> floor_002.
def test_floor_2_generates_floor_002():
    assert compute_authoritative_floor_code(2) == "floor_002"


# 4. Floor 3 -> floor_003.
def test_floor_3_generates_floor_003():
    assert compute_authoritative_floor_code(3) == "floor_003"


# 5. Floor 10 -> floor_010 (padded to 3 digits, not truncated/renumbered).
def test_floor_10_generates_floor_010():
    assert compute_authoritative_floor_code(10) == "floor_010"


# 6. Separate analyses do not all restart at floor_001 — two different
#    analyses that both received the AI's identical "floor_001" placeholder
#    resolve to DIFFERENT, map-derived codes once normalized against their
#    own map's physical floor.
def test_separate_analyses_do_not_all_restart_at_floor_001():
    reviewed_floor_2 = _semantic_result(floor_external_id="floor_001", place_ids=("p_a",))
    reviewed_floor_3 = _semantic_result(floor_external_id="floor_001", place_ids=("p_b",))

    normalized_2, msgs_2 = normalize_floor_codes(reviewed_floor_2, floor_number=2)
    normalized_3, msgs_3 = normalize_floor_codes(reviewed_floor_3, floor_number=3)

    assert normalized_2["floors"][0]["floor_external_id"] == "floor_002"
    assert normalized_3["floors"][0]["floor_external_id"] == "floor_003"
    assert normalized_2["floors"][0]["floor_external_id"] != normalized_3["floors"][0]["floor_external_id"]
    assert msgs_2 and msgs_3

    # Ground Floor (0) sharing the same AI placeholder as Floor 1 must also
    # resolve to two distinct, correct codes rather than both becoming
    # floor_001.
    reviewed_ground = _semantic_result(floor_external_id="floor_001", place_ids=("p_c",))
    normalized_ground, _ = normalize_floor_codes(reviewed_ground, floor_number=0)
    assert normalized_ground["floors"][0]["floor_external_id"] == "floor_000"


# 7. Every place (and facility, and any other entity type that can carry a
#    floor_external_id) references the correct floor code after
#    normalization — never left pointing at the stale code.
def test_every_place_and_facility_references_the_correct_floor_code():
    reviewed = _semantic_result(
        floor_external_id="floor_001", place_ids=("p1", "p2"), facility_ids=("f1",)
    )

    normalized, messages = normalize_floor_codes(reviewed, floor_number=2)

    assert normalized["floors"][0]["floor_external_id"] == "floor_002"
    assert all(p["floor_external_id"] == "floor_002" for p in normalized["places"])
    assert all(f["floor_external_id"] == "floor_002" for f in normalized["facilities"])
    assert len(messages) == 1

    # Pure/idempotent: the ORIGINAL dict passed in must be untouched.
    assert reviewed["floors"][0]["floor_external_id"] == "floor_001"
    assert reviewed["places"][0]["floor_external_id"] == "floor_001"

    # Idempotent: normalizing an already-correct document is a true no-op.
    normalized_again, messages_again = normalize_floor_codes(normalized, floor_number=2)
    assert normalized_again["floors"][0]["floor_external_id"] == "floor_002"
    assert messages_again == []


# ===========================================================
# PART B — end-to-end HTTP/DB integration — spec items 8-11.
# ===========================================================


# 8. The review UI's own data source (GET .../result) shows the
#    authoritative floor_002 for a Floor 2 map — never the AI's
#    independently-invented "floor_001" (AdminMapAnalysisScreen.jsx's
#    review table renders item.floor_external_id directly from this
#    response, confirmed by inspection).
async def test_review_result_endpoint_shows_floor_002_for_a_floor_2_map(client):
    token, _ = create_admin_and_get_token(client, role="global_manager", email="fc8@example.com")
    map_item = _create_map(client, token, floor=2)

    ai_result = _semantic_result(floor_external_id="floor_001", place_ids=("p8",))
    analysis = await _make_completed_analysis(map_item["id"], ai_result)

    response = client.get(RESULT_URL.format(analysis_id=analysis.analysis_id), headers=auth_headers(token))
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["ai_result"]["floors"][0]["floor_external_id"] == "floor_002"
    assert body["ai_result"]["places"][0]["floor_external_id"] == "floor_002"

    # View-only: the persisted ai_result itself must remain untouched
    # ("never rewritten once status becomes completed" per the model's
    # own docstring).
    refreshed = await SemanticMapAnalysis.find_one(SemanticMapAnalysis.analysis_id == analysis.analysis_id)
    assert refreshed.ai_result["floors"][0]["floor_external_id"] == "floor_001"


# 8b. Saving a reviewed_result (PUT) PERSISTS the corrected code — unlike
#     the GET view above, this one is expected to actually change what's
#     stored in the database.
async def test_save_reviewed_result_persists_the_authoritative_floor_code(client):
    token, _ = create_admin_and_get_token(client, role="global_manager", email="fc8b@example.com")
    map_item = _create_map(client, token, floor=2)

    ai_result = _semantic_result(floor_external_id="floor_001", place_ids=("p8b",))
    analysis = await _make_completed_analysis(map_item["id"], ai_result)

    edited = _semantic_result(floor_external_id="floor_001", place_ids=("p8b",), review_status="accepted")
    response = client.put(
        f"/api/semantic-analyses/{analysis.analysis_id}/reviewed-result",
        json={"expected_revision": 0, "reviewed_result": edited},
        headers=auth_headers(token),
    )
    assert response.status_code == 200, response.text

    refreshed = await SemanticMapAnalysis.find_one(SemanticMapAnalysis.analysis_id == analysis.analysis_id)
    assert refreshed.reviewed_result["floors"][0]["floor_external_id"] == "floor_002"
    assert refreshed.reviewed_result["places"][0]["floor_external_id"] == "floor_002"


# 9. The semantic destination preview for a Floor 3 map uses the physical
#    floor 3 (Section 6 — Room/RoutePoint.floor were already correct
#    before this fix; this is a regression guard proving that stays true).
async def test_destination_preview_for_floor_3_uses_physical_floor_3(client):
    token, _ = create_admin_and_get_token(client, role="global_manager", email="fc9@example.com")
    map_item = _create_map(client, token, floor=3)
    await _create_publication(map_item["id"], floor=3, place_ids=("p9",))

    result = _preview(client, token, map_item["id"])
    proposal = _find_proposal(result, "p9")

    assert proposal is not None
    assert proposal["floor"] == 3
    assert proposal["excluded"] is False


# 10. Apply creates Rooms and RoutePoints on the selected Map's REAL
#     floor (Floor 3 Map -> Room.floor == 3, RoutePoint.floor == 3), and
#     the semantic floor code stays a formatted string, never saved into
#     the numeric floor field.
async def test_apply_creates_room_and_route_point_on_the_maps_real_floor(client):
    token, _ = create_admin_and_get_token(client, role="global_manager", email="fc10@example.com")
    map_item = _create_map(client, token, floor=3)
    await _create_publication(map_item["id"], floor=3, place_ids=("p10",))

    result = _apply(
        client, token, map_item["id"],
        accepted=[{"semantic_item_id": "p10", "entity_kind": "place", "x": 5, "y": 5}],
    )
    assert result["rooms_created"] == 1
    assert result["route_points_created"] == 1

    rooms = await Room.find({"map_id": map_item["id"]}).to_list()
    points = await RoutePoint.find({"map_id": map_item["id"]}).to_list()
    assert rooms[0].floor == 3
    assert points[0].floor == 3
    # Numeric floor fields must never hold the formatted string identifier.
    assert rooms[0].floor != "floor_003"
    assert points[0].floor != "floor_003"


# 11. Correcting the floor code (the admin-confirmed repair action) never
#     loses approved names, translations, review decisions, confidence
#     values — only the floor_external_id references change.
async def test_repair_floor_codes_preserves_approved_names_and_review_status(client):
    token, _ = create_admin_and_get_token(client, role="global_manager", email="fc11@example.com")
    map_item = _create_map(client, token, floor=2)

    ai_result = _semantic_result(floor_external_id="floor_001", place_ids=("p11",))
    reviewed = _semantic_result(floor_external_id="floor_001", place_ids=("p11",), review_status="accepted")
    reviewed["places"][0]["names"]["en"] = "Admin Corrected Name"
    reviewed["places"][0]["confidence"] = 0.42

    analysis = await _make_completed_analysis(
        map_item["id"], ai_result, reviewed_result=reviewed, review_revision=3
    )

    response = client.post(REPAIR_URL.format(map_id=map_item["id"]), headers=auth_headers(token))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["changed"] is True
    assert analysis.analysis_id in body["changed_analysis_ids"]

    refreshed = await SemanticMapAnalysis.find_one(SemanticMapAnalysis.analysis_id == analysis.analysis_id)
    assert refreshed.reviewed_result["floors"][0]["floor_external_id"] == "floor_002"
    assert refreshed.reviewed_result["places"][0]["floor_external_id"] == "floor_002"
    # Everything else about the admin's own review work must be untouched.
    assert refreshed.reviewed_result["places"][0]["names"]["en"] == "Admin Corrected Name"
    assert refreshed.reviewed_result["places"][0]["review"]["status"] == "accepted"
    assert refreshed.reviewed_result["places"][0]["confidence"] == 0.42
    # ai_result (Layer A, "never rewritten") must remain completely
    # untouched by a repair action too.
    assert refreshed.ai_result["floors"][0]["floor_external_id"] == "floor_001"
    # The repair also normalizes the ACTIVE publication + its floor_links,
    # not just the analysis draft, when one exists for this map.
    assert refreshed.review_revision == 3


# 11b. repair_floor_codes also corrects an already-published, ACTIVE
#      publication's floor_links and rebuilds its SemanticEntity index,
#      without touching a superseded (inactive) one.
async def test_repair_floor_codes_corrects_active_publication_and_its_index(client):
    token, _ = create_admin_and_get_token(client, role="global_manager", email="fc11b@example.com")
    map_item = _create_map(client, token, floor=2)

    # Simulate a publication made before this fix landed.
    await _create_publication(map_item["id"], floor=2, place_ids=("p11b",), floor_external_id="floor_001")

    response = client.post(REPAIR_URL.format(map_id=map_item["id"]), headers=auth_headers(token))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["changed"] is True
    assert body["changed_publication_id"] is not None

    publication = await SemanticMapPublication.find_one({"map_id": map_item["id"], "is_active": True})
    assert publication.reviewed_result["floors"][0]["floor_external_id"] == "floor_002"
    assert publication.quickroute_links["floor_links"][0]["floor_external_id"] == "floor_002"

    entities = await SemanticEntity.find({"publication_id": publication.publication_id}).to_list()
    assert len(entities) == 1
    assert entities[0].floor_external_id == "floor_002"


# 12. Existing Dijkstra/navigation behaviour is unaffected by any of the
#     above — ordinary single-map route calculation between two connected
#     RoutePoints still works exactly as before.
async def test_existing_navigation_route_calculation_is_unaffected(client):
    token, _ = create_admin_and_get_token(client, role="global_manager", email="fc12@example.com")
    map_item = _create_map(client, token, floor=2)
    point_a = _create_point(client, token, map_item["id"], "Point A", 0, 0, floor=2)
    point_b = _create_point(client, token, map_item["id"], "Point B", 10, 0, floor=2)
    _create_edge(client, token, map_item["id"], point_a["id"], point_b["id"])

    response = client.post(
        "/api/navigation/route",
        json={"map_id": map_item["id"], "start_point_id": point_a["id"], "end_point_id": point_b["id"]},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["path_point_ids"] == [point_a["id"], point_b["id"]]
    assert body["total_distance"] > 0


# ===========================================================
# PART C — Section 8 validation: reject stale/overridden floor codes at
# publish and at destination-apply time; preview warns without blocking.
# ===========================================================


async def test_publish_rejects_floor_link_override_that_contradicts_map_floor(client):
    token, _ = create_admin_and_get_token(client, role="global_manager", email="fc13@example.com")
    map_item = _create_map(client, token, floor=2)

    reviewed = _semantic_result(floor_external_id="floor_002", place_ids=("p13",), review_status="accepted")
    analysis = await _make_completed_analysis(map_item["id"], reviewed, reviewed_result=reviewed)

    response = client.post(
        PUBLISH_URL.format(analysis_id=analysis.analysis_id),
        json={"quickroute_links": {"floor_links": [{"floor_external_id": "floor_099", "map_id": map_item["id"]}]}},
        headers=auth_headers(token),
    )
    assert response.status_code == 409
    assert "floor_099" in response.text
    assert "floor_002" in response.text


async def test_publish_succeeds_and_self_heals_a_stale_ai_floor_code(client):
    token, _ = create_admin_and_get_token(client, role="global_manager", email="fc13b@example.com")
    map_item = _create_map(client, token, floor=2)

    reviewed = _semantic_result(floor_external_id="floor_001", place_ids=("p13b",), review_status="accepted")
    analysis = await _make_completed_analysis(map_item["id"], reviewed, reviewed_result=reviewed)

    response = client.post(PUBLISH_URL.format(analysis_id=analysis.analysis_id), headers=auth_headers(token))
    assert response.status_code == 200, response.text
    body = response.json()

    publication = await SemanticMapPublication.find_one({"publication_id": body["publication_id"]})
    assert publication.reviewed_result["floors"][0]["floor_external_id"] == "floor_002"
    assert publication.quickroute_links["floor_links"][0]["floor_external_id"] == "floor_002"


async def test_apply_rejects_destinations_when_floor_code_is_stale(client):
    token, _ = create_admin_and_get_token(client, role="global_manager", email="fc14@example.com")
    map_item = _create_map(client, token, floor=2)
    await _create_publication(map_item["id"], floor=2, place_ids=("p14",), floor_external_id="floor_001")

    result = _apply(
        client, token, map_item["id"],
        accepted=[{"semantic_item_id": "p14", "entity_kind": "place", "x": 1, "y": 1}],
    )
    assert result["failed"] == 1
    assert result["rooms_created"] == 0
    assert any("out of date" in w.lower() or "stale" in w.lower() for w in result["warnings"])

    rooms = await Room.find({"map_id": map_item["id"]}).to_list()
    assert rooms == []


async def test_preview_warns_but_does_not_block_on_stale_floor_code(client):
    token, _ = create_admin_and_get_token(client, role="global_manager", email="fc15@example.com")
    map_item = _create_map(client, token, floor=2)
    await _create_publication(map_item["id"], floor=2, place_ids=("p15",), floor_external_id="floor_001")

    result = _preview(client, token, map_item["id"])
    assert result["summary"]["scanned"] == 1
    assert any("out of date" in w.lower() or "stale" in w.lower() for w in result["warnings"])


async def test_apply_succeeds_after_repair_floor_codes_fixes_stale_publication(client):
    token, _ = create_admin_and_get_token(client, role="global_manager", email="fc16@example.com")
    map_item = _create_map(client, token, floor=2)
    await _create_publication(map_item["id"], floor=2, place_ids=("p16",), floor_external_id="floor_001")

    blocked = _apply(
        client, token, map_item["id"],
        accepted=[{"semantic_item_id": "p16", "entity_kind": "place", "x": 1, "y": 1}],
    )
    assert blocked["rooms_created"] == 0

    repair_response = client.post(REPAIR_URL.format(map_id=map_item["id"]), headers=auth_headers(token))
    assert repair_response.status_code == 200, repair_response.text
    assert repair_response.json()["changed"] is True

    allowed = _apply(
        client, token, map_item["id"],
        accepted=[{"semantic_item_id": "p16", "entity_kind": "place", "x": 1, "y": 1}],
    )
    assert allowed["rooms_created"] == 1


async def test_ground_floor_map_never_becomes_floor_001(client):
    """Section 3: Ground Floor (Map.floor == 0) must produce floor_000,
    never floor_001 merely because the AI happened to invent "floor_001"
    as its own placeholder text for the one/only floor entity — publishing
    a raw AI "floor_001" result against a Ground Floor map must correct it
    to floor_000, exactly like any other floor number would be corrected."""

    token, _ = create_admin_and_get_token(client, role="global_manager", email="fc17@example.com")
    map_item = _create_map(client, token, floor=0)

    reviewed = _semantic_result(floor_external_id="floor_001", place_ids=("p17",), review_status="accepted")
    analysis = await _make_completed_analysis(map_item["id"], reviewed, reviewed_result=reviewed)

    response = client.post(PUBLISH_URL.format(analysis_id=analysis.analysis_id), headers=auth_headers(token))
    assert response.status_code == 200, response.text
    body = response.json()

    publication = await SemanticMapPublication.find_one({"publication_id": body["publication_id"]})
    assert publication.quickroute_links["floor_links"][0]["floor_external_id"] == "floor_000"
    assert publication.reviewed_result["floors"][0]["floor_external_id"] == "floor_000"
    assert publication.reviewed_result["places"][0]["floor_external_id"] == "floor_000"

    result = _preview(client, token, map_item["id"])
    proposal = _find_proposal(result, "p17")
    assert proposal is not None
    assert proposal["floor"] == 0
