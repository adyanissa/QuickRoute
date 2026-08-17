"""
Room versus circulation versus non-space — regression coverage for the
semantic-analysis refinement (prompt sections AA, AB, AC).

WHAT CAN AND CANNOT BE TESTED HERE
----------------------------------
The refinement is prompt text sent to Claude, so no test can assert what
the model will answer. Two things CAN be asserted, and both are worth
more than a mocked model response:

  1. The rules are present in the ACTIVE prompt. The prompt is one file
     loaded by services/semantic_prompt_loader and hashed into every
     analysis record, so a content assertion is a real guard against a
     rule being silently dropped in a later edit.

  2. The CONTRACT the rules target holds in code. The product-critical
     invariant is that circulation never becomes a navigable destination
     with a QR code, and that functional rooms — including service rooms
     and rooms with wide open interiors — do. That is enforced by
     DESTINATION_ENTITY_ARRAYS and by preview_semantic_destinations, and
     it is exercised end to end below with real publications.

Nothing here changes the schema. `public_areas` already exists with an
`area_type` taxonomy that includes main_corridor / secondary_corridor /
service_corridor / internal_corridor / lobby / vestibule, and it is
already excluded from destinations. These tests pin that behaviour.

Run with: pytest backend/tests/test_semantic_space_classification.py -v
"""

import re

import pytest

from tests.test_api_integration import auth_headers, create_admin_and_get_token
from tests.test_semantic_destinations import _facility, _place

from models.semantic_map_publication_model import SemanticMapPublication
from schemas.semantic_analysis_schema import Place, PublicArea
from services import semantic_prompt_loader
from services.semantic_destination_service import DESTINATION_ENTITY_ARRAYS


DEST_PREVIEW_URL = "/api/maps/{map_id}/semantic-analysis/destinations/preview"


# ---------------------------------------------------------
# Helpers
# ---------------------------------------------------------


def _public_area(external_id, name_en, area_type="main_corridor", status="accepted"):
    """A circulation space. Deliberately shaped like the real thing so the
    test proves the pipeline ignores it by CONTRACT, not by accident."""

    return {
        "area_external_id": external_id,
        "floor_external_id": "floor-1",
        "names": {"en": name_en, "ar": None, "he": None, "original": None},
        "area_type": area_type,
        "confidence": 0.95,
        "review": {"status": status},
    }


async def _create_publication_with_areas(
    map_id, places=None, facilities=None, public_areas=None
):
    publication = SemanticMapPublication(
        analysis_id="space-classification-analysis",
        prompt_version="test-v1",
        prompt_sha256="0" * 64,
        reviewed_result={
            "places": places or [],
            "facilities": facilities or [],
            "public_areas": public_areas or [],
        },
        quickroute_links={
            "floor_links": [{"floor_external_id": "floor-1", "map_id": map_id}]
        },
        map_id=map_id,
        is_active=True,
    )
    await publication.insert()
    return publication


def _create_map(client, token, title="Space Classification Map"):
    response = client.post(
        "/api/maps", json={"title": title, "floor": None}, headers=auth_headers(token)
    )
    assert response.status_code == 201, response.text
    return response.json()


def _preview(client, token, map_id):
    response = client.post(
        DEST_PREVIEW_URL.format(map_id=map_id), json={}, headers=auth_headers(token)
    )
    assert response.status_code == 200, response.text
    return response.json()


def _proposed_ids(preview_result):
    return {
        proposal["semantic_item_id"]
        for proposal in preview_result["proposals"]
        if not proposal.get("excluded")
    }


@pytest.fixture(scope="module")
def prompt_text():
    """
    The active prompt with all runs of whitespace collapsed to one space.

    The file is hard-wrapped, so a rule sentence is routinely split across
    a line break and an exact substring match on the raw text would be
    asserting the wrapping rather than the rule. Normalising means these
    tests survive a future re-wrap and still fail if a rule is removed,
    which is the only thing they are here to catch.
    """

    semantic_prompt_loader.clear_prompt_cache()
    return re.sub(r"\s+", " ", semantic_prompt_loader.get_prompt_text())


# ===========================================================
# PART A — the rules are in the ACTIVE prompt
# ===========================================================

# 1.
def test_the_room_definition_and_its_anti_promotion_rule_are_present(prompt_text):
    assert "AA. SPACE CLASSIFICATION: ROOM VERSUS CIRCULATION" in prompt_text
    assert "A ROOM DOES NOT BECOME A CORRIDOR" in prompt_text

    # The specific false-promotion triggers must each be named, because
    # "large and empty" is exactly what a meeting room looks like.
    for trigger in (
        "it is empty",
        "it is large",
        "it contains chairs, tables, or desks",
        "it has more than one door",
        "it has a wide area of open floor",
        "it opens onto a corridor",
    ):
        assert trigger in prompt_text, trigger


# 2.
def test_the_corridor_definition_is_functional_not_visual(prompt_text):
    assert "whose main purpose is movement between other spaces" in prompt_text
    assert "it collects the doors of many rooms" in prompt_text
    assert (
        "must never be classified as corridor merely because it is white,"
        in prompt_text
    )


# 3.
def test_the_not_a_corridor_list_covers_the_real_failure_modes(prompt_text):
    for excluded in (
        "the interior of any room",
        "open floor inside a meeting room, classroom, or open-plan office",
        "storage areas",
        "mechanical, electrical, telecom, or service rooms",
        "restroom interiors and stall areas",
        "small alcoves and niches",
        "page margins and sheet whitespace",
        "title blocks, legends, notes, schedules, and drawing metadata",
        "exterior whitespace around the building footprint",
    ):
        assert excluded in prompt_text, excluded


# 4.
def test_the_decision_procedure_and_four_wall_rule_are_present(prompt_text):
    assert "DECISION PROCEDURE" in prompt_text
    assert "Is this space mainly a destination or functional space?" in prompt_text
    assert "FOUR-WALL UNDERSTANDING" in prompt_text
    assert (
        "A space enclosed by four walls, or nearly enclosed by walls with a doorway"
        in prompt_text
    )
    assert "DOORS AND THRESHOLDS" in prompt_text
    assert "The room is not the corridor. The corridor is not the room." in prompt_text


# 5. The conservative bias, stated as a rule rather than a hope.
def test_the_conservative_bias_is_explicit(prompt_text):
    assert "A false corridor is worse than a missing corridor." in prompt_text
    assert "set status to probable or uncertain instead of confirmed" in prompt_text
    # ...but it must not become an excuse to drop real rooms.
    assert (
        "Do not omit a clearly visible room in order to be cautious." in prompt_text
    )


# 6.
def test_the_cropped_map_rules_are_present(prompt_text):
    assert "AB. CROPPED AND PARTIAL FLOOR PLANS" in prompt_text
    assert "Never infer a corridor from whitespace alone." in prompt_text
    assert (
        "Treat the cluster of labelled rooms as the strongest available evidence"
        in prompt_text
    )
    assert "Do not extrapolate beyond the crop." in prompt_text


# 7.
def test_the_whitespace_rules_are_present(prompt_text):
    assert "AC. WHITESPACE AND NON-SPACE REGIONS" in prompt_text
    assert "Blank or open regions are not automatically spaces." in prompt_text
    assert "unreadable_areas[]" in prompt_text


# 8. The refinement must not have disturbed the existing contract sections.
def test_the_refinement_is_additive_and_preserves_the_original_contract(prompt_text):
    for section in (
        "A. NON-NEGOTIABLE OUTPUT CONTRACT",
        "D. ROUTING-GRAPH SEPARATION",
        "E. ABSOLUTE ACCURACY RULE",
        "Q. PLACE CATEGORIES",
        "R. FACILITIES AND EQUIPMENT",
        "U. PUBLIC AND COMMON AREAS",
        "Z. TEMPORARY EXTERNAL IDS",
        "1. EXACT TOP-LEVEL STRUCTURE",
    ):
        assert section in prompt_text, section

    assert prompt_text.strip().startswith("You are an expert")


# 9. THE ONE THAT MUST NEVER REGRESS: the new sections must not have
#    reintroduced any request for geometry. The whole architecture rests
#    on the AI never supplying coordinates.
def test_the_new_sections_never_ask_for_coordinates(prompt_text):
    start = prompt_text.index("AA. SPACE CLASSIFICATION")
    end = prompt_text.index("1. EXACT TOP-LEVEL STRUCTURE")
    added = prompt_text[start:end].lower()

    for forbidden in (
        "coordinate",
        "pixel",
        "bounding_box",
        "bounding box",
        "polygon",
        "centroid",
        "route_point",
        "route point",
        "x/y",
    ):
        assert forbidden not in added, forbidden

    assert (
        "You must not generate routing coordinates" in prompt_text
    ), "the routing-separation rule itself must survive"


# ===========================================================
# PART B — the taxonomy already supports the distinction
# ===========================================================

# 10. No schema change was needed: corridors already have a home.
def test_the_schema_already_models_corridors_as_public_areas():
    corridor = PublicArea(
        area_external_id="area_001",
        floor_external_id="floor_001",
        area_type="main_corridor",
    )
    assert corridor.area_type == "main_corridor"

    for area_type in (
        "secondary_corridor",
        "service_corridor",
        "internal_corridor",
        "lobby",
        "vestibule",
        "open_to_below",
    ):
        assert PublicArea(
            area_external_id="area_x", area_type=area_type
        ).area_type == area_type


# 11.
def test_the_schema_already_models_rooms_and_service_rooms_as_places():
    for category in (
        "meeting_room",
        "classroom",
        "office",
        "storage",
        "telecom_room",
        "electrical_room",
        "mechanical_room",
    ):
        place = Place(place_external_id="place_x", category=category)
        assert place.category == category


# 12. THE CONTRACT GUARD. Circulation is structurally incapable of
#     becoming a destination, so no corridor can ever receive a QR code.
def test_public_areas_are_not_a_destination_entity_kind():
    assert set(DESTINATION_ENTITY_ARRAYS) == {"place", "facility"}

    arrays = {array for array, _id_field in DESTINATION_ENTITY_ARRAYS.values()}
    assert "public_areas" not in arrays
    assert "outdoor_areas" not in arrays
    assert "access_points" not in arrays


# ===========================================================
# PART C — end-to-end behaviour on a cropped-plan shape
# ===========================================================

# 13. A meeting room with a wide open interior is still a destination.
async def test_an_open_interior_meeting_room_is_still_a_destination(client):
    token, _ = create_admin_and_get_token(
        client, role="global_manager", email="sc1@example.com"
    )
    map_item = _create_map(client, token)
    map_id = map_item["id"]

    await _create_publication_with_areas(
        map_id,
        places=[_place("p-meeting", "Meeting Room 1", category="meeting_room")],
    )

    assert "p-meeting" in _proposed_ids(_preview(client, token, map_id))


# 14. A central hallway is circulation and never becomes a destination.
async def test_a_central_hallway_never_becomes_a_destination(client):
    token, _ = create_admin_and_get_token(
        client, role="global_manager", email="sc2@example.com"
    )
    map_item = _create_map(client, token)
    map_id = map_item["id"]

    await _create_publication_with_areas(
        map_id,
        places=[_place("p-101", "Office 101")],
        public_areas=[_public_area("area-main", "Main Corridor", "main_corridor")],
    )

    result = _preview(client, token, map_id)
    proposed = _proposed_ids(result)

    assert "p-101" in proposed
    assert "area-main" not in proposed
    assert all(
        proposal["semantic_item_id"] != "area-main"
        for proposal in result["proposals"]
    )


# 15. A vestibule is circulation too — it is not promoted just because it
#     is small and adjacent to rooms.
async def test_a_vestibule_is_not_promoted_to_a_destination(client):
    token, _ = create_admin_and_get_token(
        client, role="global_manager", email="sc3@example.com"
    )
    map_item = _create_map(client, token)
    map_id = map_item["id"]

    await _create_publication_with_areas(
        map_id,
        places=[_place("p-201", "Office 201")],
        public_areas=[
            _public_area("area-vest", "Vestibule", "vestibule"),
            _public_area("area-lobby", "Lobby", "lobby"),
        ],
    )

    proposed = _proposed_ids(_preview(client, token, map_id))

    assert proposed == {"p-201"}


# 16. Service rooms ARE destinations — they are rooms, not circulation.
async def test_service_rooms_are_destinations(client):
    token, _ = create_admin_and_get_token(
        client, role="global_manager", email="sc4@example.com"
    )
    map_item = _create_map(client, token)
    map_id = map_item["id"]

    await _create_publication_with_areas(
        map_id,
        places=[
            _place("p-store", "Storage 1", category="storage"),
            _place("p-mech", "Mechanical Room", category="mechanical_room"),
            _place("p-telecom", "Telecom Room", category="telecom_room"),
            _place("p-elec", "Electrical Room", category="electrical_room"),
        ],
        facilities=[_facility("f-wc", "Restroom", facility_type="toilet")],
    )

    proposed = _proposed_ids(_preview(client, token, map_id))

    assert {"p-store", "p-mech", "p-telecom", "p-elec", "f-wc"} <= proposed


# 17. A cropped plan: one main corridor, five surrounding rooms.
async def test_a_cropped_plan_yields_rooms_only_never_the_corridor(client):
    token, _ = create_admin_and_get_token(
        client, role="global_manager", email="sc5@example.com"
    )
    map_item = _create_map(client, token)
    map_id = map_item["id"]

    rooms = [
        _place("p-101", "Office 101"),
        _place("p-102", "Office 102", category="meeting_room"),
        _place("p-103", "Classroom 103", category="classroom"),
        _place("p-104", "Storage 104", category="storage"),
        _place("p-105", "Telecom 105", category="telecom_room"),
    ]

    await _create_publication_with_areas(
        map_id,
        places=rooms,
        public_areas=[
            _public_area("area-main", "Main Corridor", "main_corridor"),
            _public_area("area-side", "Side Corridor", "secondary_corridor"),
        ],
    )

    result = _preview(client, token, map_id)
    proposed = _proposed_ids(result)

    assert proposed == {"p-101", "p-102", "p-103", "p-104", "p-105"}
    assert result["summary"]["scanned"] == 5


# 18. Ambiguity stays out rather than being silently created. An item the
#     admin has not accepted is never proposed as a destination.
async def test_an_unaccepted_ambiguous_item_is_not_proposed(client):
    token, _ = create_admin_and_get_token(
        client, role="global_manager", email="sc6@example.com"
    )
    map_item = _create_map(client, token)
    map_id = map_item["id"]

    await _create_publication_with_areas(
        map_id,
        places=[
            _place("p-clear", "Office 301"),
            _place("p-unsure", "Unclear Space", status="pending", confidence=0.2),
            _place("p-rejected", "Not A Room", status="rejected"),
        ],
    )

    proposed = _proposed_ids(_preview(client, token, map_id))

    assert proposed == {"p-clear"}


# 19. An admin-excluded room is reported, not silently dropped — the
#     conservative path still has to be visible.
async def test_an_excluded_room_is_reported_rather_than_hidden(client):
    token, _ = create_admin_and_get_token(
        client, role="global_manager", email="sc7@example.com"
    )
    map_item = _create_map(client, token)
    map_id = map_item["id"]

    await _create_publication_with_areas(
        map_id,
        places=[
            _place("p-keep", "Office 401"),
            _place("p-skip", "Office 402", selectable=False),
        ],
    )

    result = _preview(client, token, map_id)

    by_id = {
        proposal["semantic_item_id"]: proposal for proposal in result["proposals"]
    }

    assert by_id["p-skip"]["excluded"] is True
    assert by_id["p-skip"]["exclusion_reason"]
    assert by_id["p-keep"]["excluded"] is False
