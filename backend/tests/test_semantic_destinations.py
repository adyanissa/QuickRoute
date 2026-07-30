"""
Tests for "Approved Semantic Analysis -> Automatic Destinations and
Nested-Room Navigation":

  Stage 1 (destination creation from approved semantic items):
    POST /api/maps/{map_id}/semantic-analysis/destinations/preview
      (read-only)
    POST /api/maps/{map_id}/semantic-analysis/destinations/apply
      (creates/updates Rooms + destination RoutePoints for explicitly
      accepted items only, and records approved nested-parent /
      allow_transit_through relationships)

  Stage 2 (the actual access connection for a nested pair — reuses/extends
  the existing "Auto Connect Destinations to Corridors" feature):
    POST /api/route-edges/auto-connect-destinations/preview
    POST /api/route-edges/auto-connect-destinations/apply

  Nested-room routing itself is exercised through the existing
  POST /api/navigation/multi-floor-route endpoint (confirmed via
  inspection to be the ONLY endpoint whose graph-building code path goes
  through logic/multi_floor_routing.py's _suppress_intermediate_
  destination_nodes / RoutePoint.allow_transit_through check — the
  single-map POST /api/navigation/route endpoint uses a separate, simpler
  Dijkstra in logic/route_calculator.py that has no destination-only
  suppression logic at all, confirmed by inspection). The multi-floor
  endpoint works for a same-map, ungrouped request too ("PHASE 18
  backward compatibility" — see navigation_routes.py), so plain,
  non-map-group test maps are used throughout.

ARCHITECTURAL FACT (see schemas/semantic_destination_schema.py's own
docstring): the semantic-analysis JSON contract deliberately has NO
coordinates/geometry anywhere. A genuinely new destination's map position
can only ever come from an admin-supplied x/y during apply (or an existing
linked RoutePoint being reused) — never a fabricated door/boundary/
centroid. Tests reflect this: "placement" tests assert
placement_source == "existing_route_point" / "needs_manual_placement",
never any door/boundary/centroid value (none exists in this codebase).

Run with: pytest backend/tests/test_semantic_destinations.py -v
"""

import time

from beanie import PydanticObjectId

from tests.test_api_integration import auth_headers, create_admin_and_get_token

from models.room_model import Room
from models.route_point_model import RoutePoint
from models.semantic_map_publication_model import SemanticMapPublication


DEST_PREVIEW_URL = "/api/maps/{map_id}/semantic-analysis/destinations/preview"
DEST_APPLY_URL = "/api/maps/{map_id}/semantic-analysis/destinations/apply"
AUTO_CONNECT_PREVIEW_URL = "/api/route-edges/auto-connect-destinations/preview"
AUTO_CONNECT_APPLY_URL = "/api/route-edges/auto-connect-destinations/apply"
MULTI_FLOOR_ROUTE_URL = "/api/navigation/multi-floor-route"


# ---------------------------------------------------------
# Helpers (local copies, matching the established per-file convention —
# see tests/test_auto_connect_destinations.py and
# tests/test_route_edge_floor_consistency.py).
# ---------------------------------------------------------

def _create_map(client, token, title="Semantic Dest Test Map", floor=None, building_id=None):
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


def _place(
    external_id,
    name_en,
    category="store",
    confidence=0.95,
    status="accepted",
    floor_external_id="floor-1",
    inside_place_external_id=None,
    belongs_to_place_external_id=None,
    selectable=None,
    name_ar=None,
    name_he=None,
    name_original=None,
):
    item = {
        "place_external_id": external_id,
        "floor_external_id": floor_external_id,
        "names": {"en": name_en, "ar": name_ar, "he": name_he, "original": name_original},
        "category": category,
        "confidence": confidence,
        "review": {"status": status},
    }
    if inside_place_external_id:
        item["inside_place_external_id"] = inside_place_external_id
    if belongs_to_place_external_id:
        item["belongs_to_place_external_id"] = belongs_to_place_external_id
    if selectable is not None:
        item["administrator_settings"] = {"selectable_destination": selectable}
    return item


def _facility(
    external_id,
    name_en,
    facility_type="restroom",
    confidence=0.95,
    status="accepted",
    floor_external_id="floor-1",
    selectable=None,
    name_ar=None,
    name_he=None,
    name_original=None,
):
    item = {
        "facility_external_id": external_id,
        "floor_external_id": floor_external_id,
        "names": {"en": name_en, "ar": name_ar, "he": name_he, "original": name_original},
        "facility_type": facility_type,
        "confidence": confidence,
        "review": {"status": status},
    }
    if selectable is not None:
        item["administrator_settings"] = {"selectable_destination": selectable}
    return item


async def _create_publication(map_id, places=None, facilities=None, floor_external_id="floor-1"):
    publication = SemanticMapPublication(
        analysis_id="test-analysis",
        prompt_version="test-v1",
        prompt_sha256="0" * 64,
        reviewed_result={"places": places or [], "facilities": facilities or []},
        quickroute_links={"floor_links": [{"floor_external_id": floor_external_id, "map_id": map_id}]},
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


def _auto_connect_preview(client, token, map_id):
    response = client.post(
        AUTO_CONNECT_PREVIEW_URL, json={"map_id": map_id}, headers=auth_headers(token)
    )
    assert response.status_code == 200, response.text
    return response.json()


def _auto_connect_apply(client, token, map_id, accepted):
    response = client.post(
        AUTO_CONNECT_APPLY_URL,
        json={"map_id": map_id, "accepted": accepted},
        headers=auth_headers(token),
    )
    assert response.status_code == 200, response.text
    return response.json()


# ===========================================================
# PART A — Semantic-destination-creation (15 scenarios).
# ===========================================================

# 1. Preview performs no database writes.
async def test_preview_writes_nothing(client):
    token, _ = create_admin_and_get_token(client, role="global_manager", email="sd1@example.com")
    map_item = _create_map(client, token)
    await _create_publication(map_item["id"], places=[_place("p1", "Library Storage")])

    rooms_before = await Room.find({"map_id": map_item["id"]}).to_list()
    points_before = await RoutePoint.find({"map_id": map_item["id"]}).to_list()

    result = _preview(client, token, map_item["id"])
    assert result["summary"]["scanned"] == 1

    rooms_after = await Room.find({"map_id": map_item["id"]}).to_list()
    points_after = await RoutePoint.find({"map_id": map_item["id"]}).to_list()
    assert rooms_before == rooms_after == []
    assert points_before == points_after == []


# 2. Approved place creates a Room + RoutePoint.
async def test_approved_place_creates_room_and_route_point(client):
    token, _ = create_admin_and_get_token(client, role="global_manager", email="sd2@example.com")
    map_item = _create_map(client, token)
    await _create_publication(map_item["id"], places=[_place("p2", "Library Storage", category="store")])

    result = _apply(
        client, token, map_item["id"],
        accepted=[{"semantic_item_id": "p2", "entity_kind": "place", "x": 100, "y": 100}],
    )
    assert result["rooms_created"] == 1
    assert result["route_points_created"] == 1

    rooms = await Room.find({"map_id": map_item["id"]}).to_list()
    assert len(rooms) == 1
    assert rooms[0].name_en == "Library Storage"
    assert rooms[0].room_type == "store"


# 3. Approved facility creates a Room + RoutePoint too.
async def test_approved_facility_creates_room_and_route_point(client):
    token, _ = create_admin_and_get_token(client, role="global_manager", email="sd3@example.com")
    map_item = _create_map(client, token)
    await _create_publication(
        map_item["id"], facilities=[_facility("f3", "Public Restroom", facility_type="restroom")]
    )

    result = _apply(
        client, token, map_item["id"],
        accepted=[{"semantic_item_id": "f3", "entity_kind": "facility", "x": 10, "y": 20}],
    )
    assert result["rooms_created"] == 1
    rooms = await Room.find({"map_id": map_item["id"]}).to_list()
    assert rooms[0].name_en == "Public Restroom"
    assert rooms[0].room_type == "restroom"
    assert rooms[0].semantic_entity_type == "facility"


# 4. Rejected/unapproved item creates nothing, at both preview and apply.
async def test_rejected_item_creates_nothing(client):
    token, _ = create_admin_and_get_token(client, role="global_manager", email="sd4@example.com")
    map_item = _create_map(client, token)
    await _create_publication(
        map_item["id"], places=[_place("p4", "Unapproved Room", status="rejected")]
    )

    preview = _preview(client, token, map_item["id"])
    assert _find_proposal(preview, "p4") is None

    result = _apply(
        client, token, map_item["id"],
        accepted=[{"semantic_item_id": "p4", "entity_kind": "place", "x": 1, "y": 1}],
    )
    assert result["rooms_created"] == 0
    assert result["skipped"] == 1
    rooms = await Room.find({"map_id": map_item["id"]}).to_list()
    assert rooms == []


# 5. Applying the same accepted item twice is idempotent.
async def test_apply_twice_is_idempotent(client):
    token, _ = create_admin_and_get_token(client, role="global_manager", email="sd5@example.com")
    map_item = _create_map(client, token)
    await _create_publication(map_item["id"], places=[_place("p5", "Library Storage")])

    accepted = [{"semantic_item_id": "p5", "entity_kind": "place", "x": 30, "y": 30}]
    first = _apply(client, token, map_item["id"], accepted=accepted)
    assert first["rooms_created"] == 1

    second = _apply(client, token, map_item["id"], accepted=accepted)
    assert second["rooms_created"] == 0
    assert second["reused"] == 1

    rooms = await Room.find({"map_id": map_item["id"]}).to_list()
    assert len(rooms) == 1


# 6. Stable semantic id prevents duplicates even across separate apply
#    calls that mix an already-applied item with a genuinely new one.
async def test_stable_semantic_id_prevents_duplicate_rooms(client):
    token, _ = create_admin_and_get_token(client, role="global_manager", email="sd6@example.com")
    map_item = _create_map(client, token)
    await _create_publication(
        map_item["id"],
        places=[_place("p6a", "Library Storage"), _place("p6b", "Second Room")],
    )

    _apply(client, token, map_item["id"], accepted=[
        {"semantic_item_id": "p6a", "entity_kind": "place", "x": 40, "y": 40},
    ])
    second = _apply(client, token, map_item["id"], accepted=[
        {"semantic_item_id": "p6a", "entity_kind": "place", "x": 40, "y": 40},
        {"semantic_item_id": "p6b", "entity_kind": "place", "x": 50, "y": 50},
    ])
    assert second["rooms_created"] == 1
    assert second["reused"] == 1

    rooms_a = await Room.find({"semantic_entity_external_id": "p6a"}).to_list()
    assert len(rooms_a) == 1


# 7. Ambiguous legacy match (multiple unlinked Rooms with the same name)
#    is skipped rather than guessed.
async def test_ambiguous_legacy_match_is_skipped(client):
    token, _ = create_admin_and_get_token(client, role="global_manager", email="sd7@example.com")
    map_item = _create_map(client, token)
    await Room(building_id="b1", name_en="Info Desk", map_id=map_item["id"]).insert()
    await Room(building_id="b1", name_en="Info Desk", map_id=map_item["id"]).insert()
    await _create_publication(map_item["id"], places=[_place("p7", "Info Desk")])

    result = _preview(client, token, map_item["id"])
    proposal = _find_proposal(result, "p7")
    assert proposal["room_action"] == "skip"
    assert result["summary"]["ambiguous_matches"] == 1


# 8. Multilingual names are preserved on both the Room and the RoutePoint
#    (Section 14 depends on the RoutePoint side specifically).
async def test_multilingual_names_preserved(client):
    token, _ = create_admin_and_get_token(client, role="global_manager", email="sd8@example.com")
    map_item = _create_map(client, token)
    await _create_publication(map_item["id"], places=[
        _place("p8", "Library Storage", name_ar="مخزن المكتبة", name_he="מחסן הספרייה"),
    ])

    apply_result = _apply(
        client, token, map_item["id"],
        accepted=[{"semantic_item_id": "p8", "entity_kind": "place", "x": 50, "y": 50}],
    )
    room = await Room.get(PydanticObjectId(apply_result["created_room_ids"][0]))
    assert room.names["ar"] == "مخزن المكتبة"
    assert room.names["he"] == "מחסן הספרייה"

    point = await RoutePoint.get(PydanticObjectId(room.route_point_id))
    assert point.display_name_ar == "مخزن المكتبة"
    assert point.display_name_he == "מחסן הספרייה"


# 9. A manual Room rename is never overwritten by a subsequent apply whose
#    AI-provided name is empty (Section 8).
async def test_manual_name_not_overwritten_by_empty_ai_value(client):
    token, _ = create_admin_and_get_token(client, role="global_manager", email="sd9@example.com")
    map_item = _create_map(client, token)
    await _create_publication(map_item["id"], places=[_place("p9", "Library Storage")])

    apply1 = _apply(
        client, token, map_item["id"],
        accepted=[{"semantic_item_id": "p9", "entity_kind": "place", "x": 60, "y": 60}],
    )
    room_id = apply1["created_room_ids"][0]

    rename = client.put(
        f"/api/rooms/{room_id}", json={"name_en": "Admin Renamed Storage"}, headers=auth_headers(token)
    )
    assert rename.status_code == 200, rename.text

    publication2 = await _create_publication(map_item["id"], places=[_place("p9", None)])
    _apply(
        client, token, map_item["id"],
        accepted=[{"semantic_item_id": "p9", "entity_kind": "place"}],
        publication_id=publication2.publication_id,
    )

    room_after = client.get(f"/api/rooms/{room_id}", headers=auth_headers(token)).json()
    assert room_after["name_en"] == "Admin Renamed Storage"


# 10. An already-placed point's manual coordinates are preserved on a
#     reapply that omits x/y (Section 8: "manual point movement never
#     auto-reset").
async def test_manual_coordinates_preserved_on_reapply_without_new_coords(client):
    token, _ = create_admin_and_get_token(client, role="global_manager", email="sd10@example.com")
    map_item = _create_map(client, token)
    await _create_publication(map_item["id"], places=[_place("p10", "Library Storage")])

    apply1 = _apply(
        client, token, map_item["id"],
        accepted=[{"semantic_item_id": "p10", "entity_kind": "place", "x": 111, "y": 222}],
    )
    room_id = apply1["created_room_ids"][0]

    apply2 = _apply(
        client, token, map_item["id"],
        accepted=[{"semantic_item_id": "p10", "entity_kind": "place"}],
    )
    assert apply2["reused"] == 1

    room = await Room.get(PydanticObjectId(room_id))
    point = await RoutePoint.get(PydanticObjectId(room.route_point_id))
    assert point.x == 111
    assert point.y == 222


# 11. Missing coordinates for a genuinely new destination is handled as
#     "needs manual placement", never an invented centroid (Section 5).
#     Also the regression test for a real production bug found while
#     investigating a reported IndexError here: a brand-new Room created
#     for a coordinate-less item never had `map_id` set (it was only ever
#     set later, inside the "a RoutePoint was actually created" branch of
#     _apply_one_item), so it was invisible to every subsequent
#     map-scoped Room.find({"map_id": ...}) query — including preview's
#     own re-scan, which would have silently treated it as never-created
#     and risked duplicating it on a later apply. Fixed in
#     services/semantic_destination_service.py by always setting map_id
#     on Room creation, regardless of whether a RoutePoint could be
#     placed yet.
async def test_missing_coordinates_needs_manual_placement_not_invented(client):
    token, _ = create_admin_and_get_token(client, role="global_manager", email="sd11@example.com")
    map_item = _create_map(client, token)
    await _create_publication(map_item["id"], places=[_place("p11", "Unplaced Room")])

    preview = _preview(client, token, map_item["id"])
    proposal = _find_proposal(preview, "p11")
    assert proposal is not None, (
        f"p11 must remain visible in the preview even with no coordinates; "
        f"got proposals: {preview['proposals']}"
    )
    # Never silently dropped, never in some other list, and the test reads
    # the field the schema actually defines for this.
    assert proposal["placement_source"] == "needs_manual_placement"
    assert proposal["needs_location_review"] is True
    assert proposal["proposed_x"] is None
    assert proposal["proposed_y"] is None
    assert proposal["room_action"] == "create"
    assert proposal["route_point_action"] == "create"
    assert len(proposal["warnings"]) >= 1

    # Preview is still entirely read-only for this item.
    rooms_after_preview = await Room.find({"map_id": map_item["id"]}).to_list()
    assert rooms_after_preview == []

    # Apply without reviewed x/y: the Room may be created (so the approved
    # name/type isn't lost), but the RoutePoint must NOT be — no
    # coordinate is ever invented, and the destination stays unnavigable
    # until an admin supplies one.
    result = _apply(
        client, token, map_item["id"],
        accepted=[{"semantic_item_id": "p11", "entity_kind": "place"}],
    )
    assert result["rooms_created"] == 1
    assert result["route_points_created"] == 0
    assert result["created_route_point_ids"] == []

    rooms_after_apply = await Room.find({"map_id": map_item["id"]}).to_list()
    assert len(rooms_after_apply) == 1, (
        f"expected exactly one Room findable by map_id after apply, got "
        f"{len(rooms_after_apply)} — a map_id regression would show up here "
        f"as an empty list"
    )
    room = rooms_after_apply[0]
    assert room.route_point_id is None
    assert room.map_id == map_item["id"]

    # Reviewed x/y supplied afterward (the admin's later action) DOES
    # place it — coordinates are accepted when explicitly given, never
    # invented, never permanently blocked.
    second_apply = _apply(
        client, token, map_item["id"],
        accepted=[{"semantic_item_id": "p11", "entity_kind": "place", "x": 77, "y": 88}],
    )
    assert second_apply["route_points_created"] == 1
    room_after_placement = await Room.get(PydanticObjectId(str(room.id)))
    assert room_after_placement.route_point_id is not None
    placed_point = await RoutePoint.get(PydanticObjectId(room_after_placement.route_point_id))
    assert placed_point.x == 77
    assert placed_point.y == 88


# 12. An existing linked RoutePoint is the preferred placement source —
#     never re-asked of the admin (Section 5's placement priority, adapted
#     to this codebase's real "existing_route_point / manual /
#     needs_manual_placement" set).
async def test_existing_route_point_preferred_placement_source(client):
    token, _ = create_admin_and_get_token(client, role="global_manager", email="sd12@example.com")
    map_item = _create_map(client, token)

    point = RoutePoint(map_id=map_item["id"], name="Library Storage", point_type="room", x=42.0, y=84.0)
    await point.insert()
    room = Room(
        building_id="b1", name_en="Library Storage", map_id=map_item["id"],
        route_point_id=str(point.id), x=42.0, y=84.0,
        semantic_entity_external_id="p12", semantic_entity_type="place",
    )
    await room.insert()

    await _create_publication(map_item["id"], places=[_place("p12", "Library Storage")])

    result = _preview(client, token, map_item["id"])
    proposal = _find_proposal(result, "p12")
    assert proposal["placement_source"] == "existing_route_point"
    assert proposal["proposed_x"] == 42.0
    assert proposal["proposed_y"] == 84.0


# 13. A semantic item that belongs to a different map (per the
#     publication's own floor_links) is rejected during apply, never
#     silently placed on the wrong map (Section 5's "wrong floor" rule,
#     adapted).
async def test_item_belonging_to_different_map_is_rejected(client):
    token, _ = create_admin_and_get_token(client, role="global_manager", email="sd13@example.com")
    map_a = _create_map(client, token, title="Map A13")
    map_b = _create_map(client, token, title="Map B13")

    publication = SemanticMapPublication(
        analysis_id="t13", prompt_version="t", prompt_sha256="t" * 8,
        reviewed_result={
            "places": [_place("p13", "Other Floor Room", floor_external_id="floor-b")],
            "facilities": [],
        },
        quickroute_links={"floor_links": [
            {"floor_external_id": "floor-a", "map_id": map_a["id"]},
            {"floor_external_id": "floor-b", "map_id": map_b["id"]},
        ]},
        map_id=map_a["id"], is_active=True,
    )
    await publication.insert()

    result = _apply(
        client, token, map_a["id"],
        accepted=[{"semantic_item_id": "p13", "entity_kind": "place", "x": 1, "y": 1}],
        publication_id=publication.publication_id,
    )
    assert result["failed"] == 1
    rooms = await Room.find({"map_id": map_a["id"]}).to_list()
    assert rooms == []


# 14. Room and RoutePoint are bidirectionally linked after apply.
async def test_room_and_route_point_are_bidirectionally_linked(client):
    token, _ = create_admin_and_get_token(client, role="global_manager", email="sd14@example.com")
    map_item = _create_map(client, token)
    await _create_publication(map_item["id"], places=[_place("p14", "Library Storage")])

    result = _apply(
        client, token, map_item["id"],
        accepted=[{"semantic_item_id": "p14", "entity_kind": "place", "x": 5, "y": 5}],
    )
    room = await Room.get(PydanticObjectId(result["created_room_ids"][0]))
    point = await RoutePoint.get(PydanticObjectId(result["created_route_point_ids"][0]))
    assert room.route_point_id == str(point.id)
    assert point.room_id == str(room.id)


# 15. An item explicitly excluded from destination creation
#     (administrator_settings.selectable_destination = False) is never
#     scanned/created, even if an admin's accepted list still includes it
#     (Section 4's "keep approved but exclude from destination creation").
async def test_excluded_by_admin_setting_is_not_scanned_for_creation(client):
    token, _ = create_admin_and_get_token(client, role="global_manager", email="sd15@example.com")
    map_item = _create_map(client, token)
    await _create_publication(
        map_item["id"], places=[_place("p15", "Back Office", selectable=False)]
    )

    preview = _preview(client, token, map_item["id"])
    proposal = _find_proposal(preview, "p15")
    assert proposal["excluded"] is True
    assert proposal["room_action"] == "skip"

    result = _apply(
        client, token, map_item["id"],
        accepted=[{"semantic_item_id": "p15", "entity_kind": "place", "x": 1, "y": 1}],
    )
    assert result["skipped"] == 1
    rooms = await Room.find({"map_id": map_item["id"]}).to_list()
    assert rooms == []


# ===========================================================
# PART B — Nested-room navigation (15 scenarios).
# ===========================================================

# 16. Default allow_transit_through is False for a genuinely new point.
async def test_default_allow_transit_through_is_false(client):
    token, _ = create_admin_and_get_token(client, role="global_manager", email="sd16@example.com")
    map_item = _create_map(client, token)
    await _create_publication(map_item["id"], places=[_place("p16", "Library Storage")])

    result = _apply(
        client, token, map_item["id"],
        accepted=[{"semantic_item_id": "p16", "entity_kind": "place", "x": 1, "y": 1}],
    )
    point = await RoutePoint.get(PydanticObjectId(result["created_route_point_ids"][0]))
    assert point.allow_transit_through is False


# 17. An explicit allow_transit_through=True in the accepted payload
#     persists onto the RoutePoint.
async def test_explicit_pass_through_approval_persists_true(client):
    token, _ = create_admin_and_get_token(client, role="global_manager", email="sd17@example.com")
    map_item = _create_map(client, token)
    await _create_publication(map_item["id"], places=[_place("p17", "Library Storage")])

    result = _apply(
        client, token, map_item["id"],
        accepted=[{
            "semantic_item_id": "p17", "entity_kind": "place",
            "x": 1, "y": 1, "allow_transit_through": True,
        }],
    )
    point = await RoutePoint.get(PydanticObjectId(result["created_route_point_ids"][0]))
    assert point.allow_transit_through is True


# 18. An ordinary Room (allow_transit_through=False) is blocked as the
#     only intermediate node on a route.
async def test_ordinary_room_blocked_as_intermediate_in_multi_floor_routing(client):
    token, _ = create_admin_and_get_token(client, role="global_manager", email="sd18@example.com")
    map_item = _create_map(client, token)
    entrance = _create_point(client, token, map_item["id"], "Entrance 18", 0, 0, point_type="entrance")
    room_a = _create_point(client, token, map_item["id"], "Room A 18", 50, 0, point_type="room")
    room_b = _create_point(client, token, map_item["id"], "Room B 18", 100, 0, point_type="room")
    _create_edge(client, token, map_item["id"], entrance["id"], room_a["id"])
    _create_edge(client, token, map_item["id"], room_a["id"], room_b["id"])

    response = client.post(
        MULTI_FLOOR_ROUTE_URL,
        json={"start_point_id": entrance["id"], "end_point_id": room_b["id"]},
    )
    assert response.status_code in (404, 409)


# 19. A Room explicitly approved with allow_transit_through=True IS
#     allowed as an intermediate node.
async def test_pass_through_room_allowed_as_intermediate_in_multi_floor_routing(client):
    token, _ = create_admin_and_get_token(client, role="global_manager", email="sd19@example.com")
    map_item = _create_map(client, token)
    entrance = _create_point(client, token, map_item["id"], "Entrance 19", 0, 0, point_type="entrance")
    room_a = _create_point(client, token, map_item["id"], "Room A 19", 50, 0, point_type="room")
    room_b = _create_point(client, token, map_item["id"], "Room B 19", 100, 0, point_type="room")
    _create_edge(client, token, map_item["id"], entrance["id"], room_a["id"])
    _create_edge(client, token, map_item["id"], room_a["id"], room_b["id"])

    update = client.put(
        f"/api/route-points/{room_a['id']}", json={"allow_transit_through": True}, headers=auth_headers(token)
    )
    assert update.status_code == 200, update.text

    response = client.post(
        MULTI_FLOOR_ROUTE_URL,
        json={"start_point_id": entrance["id"], "end_point_id": room_b["id"]},
    )
    assert response.status_code == 200, response.text


# 20. Corridor -> approved Outer Room -> Inner Room route succeeds — the
#     canonical PROBLEM B scenario from the spec.
async def test_corridor_outer_inner_route_succeeds(client):
    token, _ = create_admin_and_get_token(client, role="global_manager", email="sd20@example.com")
    map_item = _create_map(client, token)
    corridor = _create_point(client, token, map_item["id"], "Main Corridor 20", 0, 0, point_type="hallway")
    outer = _create_point(client, token, map_item["id"], "Library Storage 20", 50, 0, point_type="room")
    inner = _create_point(client, token, map_item["id"], "Library Storage Office 20", 100, 0, point_type="room")
    _create_edge(client, token, map_item["id"], corridor["id"], outer["id"])
    _create_edge(client, token, map_item["id"], outer["id"], inner["id"])

    client.put(
        f"/api/route-points/{outer['id']}", json={"allow_transit_through": True}, headers=auth_headers(token)
    )

    response = client.post(
        MULTI_FLOOR_ROUTE_URL,
        json={"start_point_id": corridor["id"], "end_point_id": inner["id"]},
    )
    assert response.status_code == 200, response.text


# 21. Both the inner AND outer rooms remain independently selectable
#     start/destination points even with allow_transit_through=True.
async def test_inner_and_outer_both_remain_selectable_destinations(client):
    token, _ = create_admin_and_get_token(client, role="global_manager", email="sd21@example.com")
    map_item = _create_map(client, token)
    corridor = _create_point(client, token, map_item["id"], "Main Corridor 21", 0, 0, point_type="hallway")
    outer = _create_point(client, token, map_item["id"], "Library Storage 21", 50, 0, point_type="room")
    inner = _create_point(client, token, map_item["id"], "Library Storage Office 21", 100, 0, point_type="room")
    _create_edge(client, token, map_item["id"], corridor["id"], outer["id"])
    _create_edge(client, token, map_item["id"], outer["id"], inner["id"])
    client.put(
        f"/api/route-points/{outer['id']}", json={"allow_transit_through": True}, headers=auth_headers(token)
    )

    to_outer = client.post(
        MULTI_FLOOR_ROUTE_URL, json={"start_point_id": corridor["id"], "end_point_id": outer["id"]}
    )
    assert to_outer.status_code == 200, to_outer.text

    to_inner = client.post(
        MULTI_FLOOR_ROUTE_URL, json={"start_point_id": corridor["id"], "end_point_id": inner["id"]}
    )
    assert to_inner.status_code == 200, to_inner.text


# 22. allow_transit_through alone never unlocks an unrelated Room as an
#     auto-connect "corridor" candidate for a genuinely unrelated Room —
#     an explicit Room.parent_room_id relationship is also required
#     (Section 12/13).
async def test_unrelated_room_to_room_blocked(client):
    token, _ = create_admin_and_get_token(client, role="global_manager", email="sd22@example.com")
    map_item = _create_map(client, token)
    room_a = _create_point(client, token, map_item["id"], "Unrelated Room A 22", 0, 0, point_type="room")
    room_b = _create_point(client, token, map_item["id"], "Unrelated Room B 22", 10, 0, point_type="room")
    client.put(
        f"/api/route-points/{room_a['id']}", json={"allow_transit_through": True}, headers=auth_headers(token)
    )

    result = _auto_connect_preview(client, token, map_item["id"])
    proposal = next((p for p in result["proposals"] if p["destination_point_id"] == room_b["id"]), None)
    if proposal is not None:
        candidate_ids = [c["point_id"] for c in proposal["candidates"]]
        assert room_a["id"] not in candidate_ids


# 23. A nested relationship is only ever saved after the parent's
#     allow_transit_through has been explicitly approved — never silently
#     inferred from the containment field alone.
async def test_nested_relation_saved_only_after_explicit_approval(client):
    token, _ = create_admin_and_get_token(client, role="global_manager", email="sd23@example.com")
    map_item = _create_map(client, token)
    await _create_publication(map_item["id"], places=[
        _place("outer23", "Library Storage 23"),
        _place("inner23", "Library Storage Office 23", inside_place_external_id="outer23"),
    ])

    result = _apply(client, token, map_item["id"], accepted=[
        {"semantic_item_id": "outer23", "entity_kind": "place", "x": 0, "y": 0},
        {"semantic_item_id": "inner23", "entity_kind": "place", "x": 10, "y": 0, "parent_semantic_item_id": "outer23"},
    ])
    assert result["nested_relationships_created"] == 0
    assert result["failed"] >= 1

    inner_room = (await Room.find({"semantic_entity_external_id": "inner23"}).to_list())[0]
    assert inner_room.parent_room_id is None


# 24. A self-parent relationship is rejected.
async def test_self_parent_rejected(client):
    token, _ = create_admin_and_get_token(client, role="global_manager", email="sd24@example.com")
    map_item = _create_map(client, token)
    await _create_publication(map_item["id"], places=[_place("self24", "Self Room 24")])

    result = _apply(client, token, map_item["id"], accepted=[
        {
            "semantic_item_id": "self24", "entity_kind": "place", "x": 0, "y": 0,
            "parent_semantic_item_id": "self24", "allow_transit_through": True,
        },
    ])
    assert result["nested_relationships_created"] == 0
    assert result["failed"] >= 1

    room = (await Room.find({"semantic_entity_external_id": "self24"}).to_list())[0]
    assert room.parent_room_id is None


# 25. Circular nesting (A -> B already nested, then B -> A attempted) is
#     rejected.
async def test_circular_nesting_rejected(client):
    token, _ = create_admin_and_get_token(client, role="global_manager", email="sd25@example.com")
    map_item = _create_map(client, token)
    await _create_publication(map_item["id"], places=[
        _place("a25", "Room A 25"), _place("b25", "Room B 25"),
    ])

    _apply(client, token, map_item["id"], accepted=[
        {"semantic_item_id": "a25", "entity_kind": "place", "x": 0, "y": 0, "allow_transit_through": True},
        {"semantic_item_id": "b25", "entity_kind": "place", "x": 10, "y": 0, "parent_semantic_item_id": "a25"},
    ])

    result2 = _apply(client, token, map_item["id"], accepted=[
        {"semantic_item_id": "b25", "entity_kind": "place", "x": 10, "y": 0, "allow_transit_through": True},
        {"semantic_item_id": "a25", "entity_kind": "place", "x": 0, "y": 0, "parent_semantic_item_id": "b25"},
    ])
    assert result2["nested_relationships_created"] == 0
    assert result2["failed"] >= 1

    room_a = (await Room.find({"semantic_entity_external_id": "a25"}).to_list())[0]
    assert room_a.parent_room_id is None


# 26. Cross-map nesting is rejected (the parent and child must be resolved
#     from the SAME map's existing Rooms — a parent from a different map
#     is never in scope to link to).
async def test_cross_map_nesting_rejected(client):
    token, _ = create_admin_and_get_token(client, role="global_manager", email="sd26@example.com")
    map_a = _create_map(client, token, title="Map A26")
    map_b = _create_map(client, token, title="Map B26")

    publication = SemanticMapPublication(
        analysis_id="t26", prompt_version="t", prompt_sha256="t" * 8,
        reviewed_result={
            "places": [
                _place("outer26", "Outer Room 26", floor_external_id="floor-a"),
                _place("inner26", "Inner Room 26", floor_external_id="floor-b", inside_place_external_id="outer26"),
            ],
            "facilities": [],
        },
        quickroute_links={"floor_links": [
            {"floor_external_id": "floor-a", "map_id": map_a["id"]},
            {"floor_external_id": "floor-b", "map_id": map_b["id"]},
        ]},
        map_id=map_a["id"], is_active=True,
    )
    await publication.insert()

    apply_a = _apply(
        client, token, map_a["id"],
        accepted=[{"semantic_item_id": "outer26", "entity_kind": "place", "x": 0, "y": 0, "allow_transit_through": True}],
        publication_id=publication.publication_id,
    )
    assert apply_a["rooms_created"] == 1

    # Note: this is rejected because outer26's Room lives on map_a and is
    # therefore never even loaded into scope by the map_b apply call's own
    # map-scoped Room query — a second, independent safeguard beyond the
    # explicit same-map check in Pass 2 of apply_semantic_destinations.
    apply_b = _apply(
        client, token, map_b["id"],
        accepted=[{"semantic_item_id": "inner26", "entity_kind": "place", "x": 0, "y": 0, "parent_semantic_item_id": "outer26"}],
        publication_id=publication.publication_id,
    )
    assert apply_b["nested_relationships_created"] == 0
    assert apply_b["failed"] >= 1


# 27. Repeating the Stage-2 auto-connect apply for the same nested pair
#     creates no duplicate RouteEdge, and the edge is marked
#     access_relation="nested".
async def test_repeated_nested_apply_creates_no_duplicate_edge(client):
    token, _ = create_admin_and_get_token(client, role="global_manager", email="sd27@example.com")
    map_item = _create_map(client, token)
    corridor = _create_point(client, token, map_item["id"], "Corridor 27", 0, 0, point_type="hallway")
    await _create_publication(map_item["id"], places=[
        _place("outer27", "Outer Room 27"),
        _place("inner27", "Inner Room 27", inside_place_external_id="outer27"),
    ])

    apply1 = _apply(client, token, map_item["id"], accepted=[
        {"semantic_item_id": "outer27", "entity_kind": "place", "x": 50, "y": 0, "allow_transit_through": True},
        {"semantic_item_id": "inner27", "entity_kind": "place", "x": 100, "y": 0, "parent_semantic_item_id": "outer27"},
    ])
    assert apply1["nested_relationships_created"] == 1

    outer_room = (await Room.find({"semantic_entity_external_id": "outer27"}).to_list())[0]
    inner_room = (await Room.find({"semantic_entity_external_id": "inner27"}).to_list())[0]
    outer_point_id = outer_room.route_point_id
    inner_point_id = inner_room.route_point_id

    _create_edge(client, token, map_item["id"], corridor["id"], outer_point_id)

    preview = _auto_connect_preview(client, token, map_item["id"])
    proposal = next(p for p in preview["proposals"] if p["destination_point_id"] == inner_point_id)
    assert proposal["is_nested_access"] is True
    assert proposal["proposed_candidate_id"] == outer_point_id

    apply_edge_1 = _auto_connect_apply(
        client, token, map_item["id"],
        accepted=[{"destination_point_id": inner_point_id, "corridor_point_id": outer_point_id}],
    )
    assert apply_edge_1["created"] == 1

    apply_edge_2 = _auto_connect_apply(
        client, token, map_item["id"],
        accepted=[{"destination_point_id": inner_point_id, "corridor_point_id": outer_point_id}],
    )
    assert apply_edge_2["created"] == 0
    assert apply_edge_2["skipped_existing"] == 1

    edges = client.get("/api/route-edges", params={"map_id": map_item["id"]}, headers=auth_headers(token)).json()
    nested_edges = [
        e for e in edges
        if {e["from_point_id"], e["to_point_id"]} == {inner_point_id, outer_point_id}
    ]
    assert len(nested_edges) == 1
    assert nested_edges[0]["access_relation"] == "nested"


# 28. The pass-through instruction uses the real, multilingual outer-room
#     RoutePoint name — never a technical id, never English-only when a
#     real Arabic name is available (Section 14).
async def test_pass_through_instruction_uses_real_multilingual_outer_room_name(client):
    token, _ = create_admin_and_get_token(client, role="global_manager", email="sd28@example.com")
    map_item = _create_map(client, token)
    corridor = _create_point(client, token, map_item["id"], "Corridor 28", 0, 0, point_type="hallway")
    outer = _create_point(client, token, map_item["id"], "Library Storage 28", 50, 0, point_type="room")
    inner = _create_point(client, token, map_item["id"], "Library Storage Office 28", 100, 0, point_type="room")
    _create_edge(client, token, map_item["id"], corridor["id"], outer["id"])
    _create_edge(client, token, map_item["id"], outer["id"], inner["id"])

    update = client.put(
        f"/api/route-points/{outer['id']}",
        json={"allow_transit_through": True, "display_name_ar": "مخزن المكتبة", "display_name_en": "Library Storage"},
        headers=auth_headers(token),
    )
    assert update.status_code == 200, update.text

    response = client.post(
        MULTI_FLOOR_ROUTE_URL,
        json={"start_point_id": corridor["id"], "end_point_id": inner["id"], "lang": "ar"},
    )
    assert response.status_code == 200, response.text
    instructions = response.json()["instructions"]
    pass_through = [i for i in instructions if i.get("type") == "pass_through"]
    assert len(pass_through) >= 1
    assert "مخزن المكتبة" in pass_through[0]["text"]


# 29. Regression sanity: the plain single-map Dijkstra endpoint (untouched
#     by this whole feature) still routes correctly.
async def test_dijkstra_core_unchanged(client):
    token, _ = create_admin_and_get_token(client, role="global_manager", email="sd29@example.com")
    map_item = _create_map(client, token)
    a = _create_point(client, token, map_item["id"], "A29", 0, 0, point_type="hallway")
    b = _create_point(client, token, map_item["id"], "B29", 10, 0, point_type="hallway")
    _create_edge(client, token, map_item["id"], a["id"], b["id"])

    response = client.post(
        "/api/navigation/route",
        json={"map_id": map_item["id"], "start_point_id": a["id"], "end_point_id": b["id"]},
    )
    assert response.status_code == 200, response.text
    assert response.json()["path_point_ids"] == [a["id"], b["id"]]


# 30. Auto-connect proposes ONLY a nested child's approved parent — never
#     a nearer, unrelated allow_transit_through room (Section 12).
async def test_auto_connect_proposes_only_approved_parent_for_nested_child(client):
    token, _ = create_admin_and_get_token(client, role="global_manager", email="sd30@example.com")
    map_item = _create_map(client, token)
    await _create_publication(map_item["id"], places=[
        _place("outer30", "Real Parent Room 30"),
        _place("inner30", "Nested Child Room 30", inside_place_external_id="outer30"),
    ])

    apply_result = _apply(client, token, map_item["id"], accepted=[
        {"semantic_item_id": "outer30", "entity_kind": "place", "x": 200, "y": 0, "allow_transit_through": True},
        {"semantic_item_id": "inner30", "entity_kind": "place", "x": 210, "y": 0, "parent_semantic_item_id": "outer30"},
    ])
    assert apply_result["nested_relationships_created"] == 1

    decoy = _create_point(client, token, map_item["id"], "Decoy Nearby Room 30", 211, 0, point_type="room")
    client.put(
        f"/api/route-points/{decoy['id']}", json={"allow_transit_through": True}, headers=auth_headers(token)
    )

    outer_room = (await Room.find({"semantic_entity_external_id": "outer30"}).to_list())[0]
    inner_room = (await Room.find({"semantic_entity_external_id": "inner30"}).to_list())[0]

    result = _auto_connect_preview(client, token, map_item["id"])
    proposal = next(p for p in result["proposals"] if p["destination_point_id"] == inner_room.route_point_id)
    assert proposal["is_nested_access"] is True
    assert proposal["proposed_candidate_id"] == outer_room.route_point_id

    candidate_ids = [c["point_id"] for c in proposal["candidates"]]
    assert decoy["id"] not in candidate_ids


# ===========================================================
# PART C — Performance (1 scenario).
# ===========================================================

# 31. Preview handles at least 1,000 approved semantic destinations
#     without pathological behaviour (single batched Room/RoutePoint read
#     — see services/semantic_destination_service.py's own docstring for
#     the "no per-item DB query" design).
async def test_preview_handles_1000_semantic_destinations(client):
    token, _ = create_admin_and_get_token(client, role="global_manager", email="sd31@example.com")
    map_item = _create_map(client, token)
    places = [_place(f"bulk{i}", f"Bulk Place {i}") for i in range(1000)]
    await _create_publication(map_item["id"], places=places)

    started = time.monotonic()
    result = _preview(client, token, map_item["id"])
    elapsed = time.monotonic() - started

    assert result["summary"]["scanned"] == 1000
    assert len(result["proposals"]) == 1000
    # Generous ceiling for an in-memory mongomock test database — this is
    # a "not pathologically slow" guard, not a strict perf benchmark
    # (matching the exact same convention as
    # test_auto_connect_destinations.py's own performance test).
    assert elapsed < 30.0, f"preview took {elapsed:.2f}s for 1000 semantic items"
