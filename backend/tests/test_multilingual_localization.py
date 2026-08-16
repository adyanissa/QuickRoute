"""
Tests for "Safe end-to-end multilingual dynamic content" (the
LocalizedText {ar, he, en} structure, its shared get_localized_text /
merge_localized_text helpers, and every real place that now uses them:
Room create/update, semantic entity publication, the published-entities
API, localized turn-by-turn instruction text, and the optional
backfill-room-names maintenance endpoint).

16 scenarios, matching the multilingual content spec's backend test list:

  1.  get_localized_text: exact requested language returned when present.
  2.  get_localized_text: falls through en -> ar -> he -> legacy -> "" in
      that exact order when the requested language is missing.
  3.  get_localized_text: whitespace-only values are treated as empty,
      never returned as a "valid" translation.
  4.  get_localized_text: an unsupported/unexpected `language` value never
      raises and never reaches a raw dict lookup with attacker-controlled
      content — it just falls through the normal chain.
  5.  localized_text_to_dict: normalizes None / a LocalizedText / a plain
      dict uniformly, always returning all three keys.
  6.  merge_localized_text: a language key ABSENT from `updates` preserves
      the existing value; a key PRESENT (even as null) overwrites just
      that one language — the exact mechanism that lets an admin correct
      only Arabic without touching English/Hebrew.
  7.  LocalizedText (extra="forbid") rejects an unexpected field instead
      of silently accepting arbitrary attacker-controlled keys.
  8.  Room create with a full `names` object stores + returns it, and
      keeps legacy name_en/name_local completely intact.
  9.  Room create with NO `names` at all (legacy request) leaves `names`
      None in the response — full backward compatibility.
  10. Room update: correcting ONLY names.ar via the real HTTP API never
      touches an already-stored English/Hebrew translation.
  11. Room update: explicitly sending a null value for one language
      clears just that language, leaving the others untouched.
  12. Publishing a semantic analysis populates SemanticEntity.names
      identically to the legacy flat names_en/ar/he/original fields —
      never a second, independently-drifting copy.
  13. GET /api/maps/{map_id}/semantic-entities returns both the full
      `names` object and a server-resolved legacy `name` fallback string.
  14. generate_floor_instructions produces real Arabic/Hebrew text (not
      just English with a language tag) for the exact same route input,
      and falls back to English for an unrecognized language code.
  15. generate_transition_instruction + resolve_localized_display_name:
      per-language connector/display names and floor labels resolve
      correctly, with a safe fallback chain when a language is missing.
  16. POST /api/maintenance/backfill-room-names is safe, optional,
      idempotent: dry_run=True never writes, dry_run=False only ever
      backfills name_en into names.en (never guesses name_local's
      language), and a second run changes nothing further.

Run with: pytest backend/tests/test_multilingual_localization.py -v
"""

import pytest

from tests.test_api_integration import auth_headers, create_admin_and_get_token

from schemas.localization_schema import (
    LocalizedText,
    get_localized_text,
    localized_text_to_dict,
    merge_localized_text,
)
from models.map_model import Map
from models.room_model import Room
from models.semantic_map_analysis_model import SemanticMapAnalysis
from models.semantic_map_publication_model import SemanticEntity
from services.semantic_publication_service import publish_analysis
from logic.instruction_generator import (
    generate_floor_instructions,
    generate_transition_instruction,
    resolve_localized_display_name,
)

try:
    from pydantic import ValidationError
except ImportError:  # pragma: no cover
    ValidationError = Exception


# ---------------------------------------------------------------------
# 1 — exact requested language wins when present
# ---------------------------------------------------------------------

def test_get_localized_text_returns_exact_requested_language():
    names = {"ar": "صيدلية الشفاء", "he": "בית מרקחת אלשפאא", "en": "Al Shifaa Pharmacy"}
    assert get_localized_text(names, "ar") == "صيدلية الشفاء"
    assert get_localized_text(names, "he") == "בית מרקחת אלשפאא"
    assert get_localized_text(names, "en") == "Al Shifaa Pharmacy"


# ---------------------------------------------------------------------
# 2 — exact fallback order: requested -> en -> ar -> he -> legacy -> ""
# ---------------------------------------------------------------------

def test_get_localized_text_fallback_order_is_exact():
    # Requested language missing -> falls to en.
    assert get_localized_text({"en": "English Name"}, "ar") == "English Name"

    # en also missing -> falls to ar.
    assert get_localized_text({"ar": "Arabic Only"}, "he") == "Arabic Only"

    # en and ar both missing -> falls to he.
    assert get_localized_text({"he": "Hebrew Only"}, "ar") == "Hebrew Only"

    # Nothing in `names` at all -> falls to the legacy name.
    assert get_localized_text({}, "ar", "Legacy Name") == "Legacy Name"
    assert get_localized_text(None, "en", "Legacy Name") == "Legacy Name"

    # Nothing anywhere -> safe empty string, never raises.
    assert get_localized_text(None, "en", None) == ""
    assert get_localized_text({}, "ar") == ""


# ---------------------------------------------------------------------
# 3 — whitespace-only values are never a "valid" translation
# ---------------------------------------------------------------------

def test_get_localized_text_treats_whitespace_only_as_empty():
    names = {"ar": "   ", "en": "Real English Name"}
    assert get_localized_text(names, "ar") == "Real English Name"
    assert get_localized_text({"en": "   "}, "en", "Legacy") == "Legacy"


# ---------------------------------------------------------------------
# 4 — an unsupported/attacker-controlled `language` value never raises
#     and never reaches a raw dict lookup with untrusted content
# ---------------------------------------------------------------------

def test_get_localized_text_handles_unsupported_language_safely():
    names = {"en": "English Name"}
    # A completely bogus language code just falls through to the normal
    # chain instead of raising or doing a raw dict[language] lookup.
    assert get_localized_text(names, "fr") == "English Name"
    assert get_localized_text(names, "") == "English Name"
    assert get_localized_text(names, None) == "English Name"
    # Something that LOOKS like an injection attempt is still just
    # treated as "no exact match" — never propagated into a Mongo query
    # or attribute access.
    assert get_localized_text(names, "$where") == "English Name"
    assert get_localized_text(names, "__proto__") == "English Name"


# ---------------------------------------------------------------------
# 5 — localized_text_to_dict normalizes every input shape uniformly
# ---------------------------------------------------------------------

def test_localized_text_to_dict_normalizes_every_shape():
    assert localized_text_to_dict(None) == {"ar": None, "he": None, "en": None}
    assert localized_text_to_dict({"en": "Only English"}) == {
        "ar": None,
        "he": None,
        "en": "Only English",
    }
    assert localized_text_to_dict(LocalizedText(en="From Model")) == {
        "ar": None,
        "he": None,
        "en": "From Model",
    }
    # Whitespace-only stored values are cleaned to None, not returned as-is.
    assert localized_text_to_dict({"ar": "   "}) == {"ar": None, "he": None, "en": None}


# ---------------------------------------------------------------------
# 6 — merge_localized_text: absent key preserves, present key overwrites
#     (the core "correct one language without touching the others" fix)
# ---------------------------------------------------------------------

def test_merge_localized_text_absent_key_preserves_existing():
    existing = {"ar": "Old Arabic", "he": "Old Hebrew", "en": "Old English"}
    # `updates` only mentions "ar" — he/en must survive completely
    # unchanged, never silently blanked by the partial update.
    merged = merge_localized_text(existing, {"ar": "New Arabic"})
    assert merged == {"ar": "New Arabic", "he": "Old Hebrew", "en": "Old English"}


def test_merge_localized_text_present_null_explicitly_clears_that_language():
    existing = {"ar": "Old Arabic", "he": "Old Hebrew", "en": "Old English"}
    merged = merge_localized_text(existing, {"he": None})
    assert merged == {"ar": "Old Arabic", "he": None, "en": "Old English"}


def test_merge_localized_text_with_no_prior_existing_value():
    merged = merge_localized_text(None, {"en": "Brand New"})
    assert merged == {"ar": None, "he": None, "en": "Brand New"}


# ---------------------------------------------------------------------
# 7 — LocalizedText rejects an unexpected field (extra="forbid")
# ---------------------------------------------------------------------

def test_localized_text_model_rejects_unexpected_field():
    with pytest.raises(ValidationError):
        LocalizedText(ar="ok", he="ok", en="ok", malicious_field="$where")


# ---------------------------------------------------------------------
# 8 — Room create with a full `names` object
# ---------------------------------------------------------------------

def test_create_room_with_full_names_object(client):
    token, _ = create_admin_and_get_token(client, email="ml8@example.com")
    building = client.post(
        "/api/locations/buildings",
        json={"name_en": "ML Building 8"},
        headers=auth_headers(token),
    ).json()

    created = client.post(
        "/api/rooms",
        json={
            "building_id": building["id"],
            "name_en": "Al Shifaa Pharmacy",
            "room_type": "pharmacy",
            "names": {
                "ar": "صيدلية الشفاء",
                "he": "בית מרקחת אלשפאא",
                "en": "Al Shifaa Pharmacy",
            },
        },
        headers=auth_headers(token),
    )
    assert created.status_code == 201, created.text
    room = created.json()

    # Legacy fields fully intact.
    assert room["name_en"] == "Al Shifaa Pharmacy"
    # New nested structure present with all three languages.
    assert room["names"] == {
        "ar": "صيدلية الشفاء",
        "he": "בית מרקחת אלשפאא",
        "en": "Al Shifaa Pharmacy",
    }

    fetched = client.get(f"/api/rooms/{room['id']}").json()
    assert fetched["names"]["ar"] == "صيدلية الشفاء"


# ---------------------------------------------------------------------
# 9 — Room create with NO `names` at all (full backward compatibility)
# ---------------------------------------------------------------------

def test_create_room_without_names_stays_fully_backward_compatible(client):
    token, _ = create_admin_and_get_token(client, email="ml9@example.com")
    building = client.post(
        "/api/locations/buildings",
        json={"name_en": "ML Building 9"},
        headers=auth_headers(token),
    ).json()

    created = client.post(
        "/api/rooms",
        json={
            "building_id": building["id"],
            "name_en": "Legacy Only Room",
            "room_type": "room",
        },
        headers=auth_headers(token),
    )
    assert created.status_code == 201, created.text
    room = created.json()

    assert room["name_en"] == "Legacy Only Room"
    assert room["names"] is None


# ---------------------------------------------------------------------
# 10 — correcting ONLY names.ar via the real API never touches en/he
# ---------------------------------------------------------------------

def test_update_room_names_ar_only_never_touches_en_or_he(client):
    token, _ = create_admin_and_get_token(client, email="ml10@example.com")
    building = client.post(
        "/api/locations/buildings",
        json={"name_en": "ML Building 10"},
        headers=auth_headers(token),
    ).json()

    created = client.post(
        "/api/rooms",
        json={
            "building_id": building["id"],
            "name_en": "Original Store",
            "room_type": "store",
            "names": {"ar": "Old Arabic", "he": "Old Hebrew", "en": "Old English"},
        },
        headers=auth_headers(token),
    ).json()

    updated = client.put(
        f"/api/rooms/{created['id']}",
        json={"names": {"ar": "Corrected Arabic"}},
        headers=auth_headers(token),
    )
    assert updated.status_code == 200, updated.text
    body = updated.json()

    assert body["names"]["ar"] == "Corrected Arabic"
    # Never silently blanked or overwritten — the exact bug this fixes.
    assert body["names"]["he"] == "Old Hebrew"
    assert body["names"]["en"] == "Old English"

    # Re-fetch independently to be sure this isn't just an echoed request.
    refetched = client.get(f"/api/rooms/{created['id']}").json()
    assert refetched["names"] == {
        "ar": "Corrected Arabic",
        "he": "Old Hebrew",
        "en": "Old English",
    }


# ---------------------------------------------------------------------
# 11 — explicit null for one language clears just that language
# ---------------------------------------------------------------------

def test_update_room_names_explicit_null_clears_only_that_language(client):
    token, _ = create_admin_and_get_token(client, email="ml11@example.com")
    building = client.post(
        "/api/locations/buildings",
        json={"name_en": "ML Building 11"},
        headers=auth_headers(token),
    ).json()

    created = client.post(
        "/api/rooms",
        json={
            "building_id": building["id"],
            "name_en": "Store Eleven",
            "room_type": "store",
            "names": {"ar": "Arabic Eleven", "he": "Hebrew Eleven", "en": "English Eleven"},
        },
        headers=auth_headers(token),
    ).json()

    updated = client.put(
        f"/api/rooms/{created['id']}",
        json={"names": {"he": None}},
        headers=auth_headers(token),
    ).json()

    assert updated["names"]["he"] is None
    assert updated["names"]["ar"] == "Arabic Eleven"
    assert updated["names"]["en"] == "English Eleven"


# ---------------------------------------------------------------------
# 12/13 — publication builds a real SemanticEntity with matching nested
#         + legacy names, and the published-entities API exposes both
# ---------------------------------------------------------------------

def _multilingual_ai_result():
    return {
        "schema_version": "quickroute_semantic_map_import_v2",
        "import_draft": {
            "status": "ready_for_review",
            "source_type": "ai_extraction",
            "requires_human_review": True,
            "can_publish_immediately": False,
        },
        "source_documents": [],
        "site": {"site_external_id": "site_ml"},
        "buildings": [],
        "zones": [],
        "floors": [{"floor_external_id": "floor_ml"}],
        "places": [
            {
                "place_external_id": "place_ml_001",
                "floor_external_id": "floor_ml",
                "names": {
                    "original": "Pharmacy",
                    "en": "Al Shifaa Pharmacy",
                    "ar": "صيدلية الشفاء",
                    "he": "בית מרקחת אלשפאא",
                },
                "category": "pharmacy",
                "review": {"status": "accepted"},
            }
        ],
        "facilities": [],
        "access_points": [],
        "public_areas": [],
        "vertical_connections": [],
        "outdoor_areas": [],
        "parking_areas": [],
        "parking_spaces": [],
        "cross_building_connections": [],
        "review_items": [],
        "unreadable_areas": [],
        "summary": {"total_places": 1, "total_floors": 1},
        "validation": {},
    }


@pytest.mark.asyncio
async def test_publish_populates_nested_names_matching_legacy_flat_fields(client):
    analysis = SemanticMapAnalysis(
        map_id="map-ml-12",
        source_fingerprint="fp-ml-12",
        prompt_version="v",
        prompt_sha256="h",
        model="claude-sonnet-4-20250514",
        status="completed",
        ai_result=_multilingual_ai_result(),
        reviewed_result=_multilingual_ai_result(),
    )
    await analysis.insert()

    publication = await publish_analysis(analysis, published_by="tester")

    entities = await SemanticEntity.find(
        {"publication_id": publication.publication_id}
    ).to_list()
    assert len(entities) == 1
    entity = entities[0]

    # Legacy flat fields (unchanged behavior).
    assert entity.names_en == "Al Shifaa Pharmacy"
    assert entity.names_ar == "صيدلية الشفاء"
    assert entity.names_he == "בית מרקחת אלשפאא"
    assert entity.names_original == "Pharmacy"

    # New nested structure — the exact same admin-approved data, never a
    # second independently-drifting copy.
    assert entity.names == {
        "ar": "صيدلية الشفاء",
        "he": "בית מרקחת אלשפאא",
        "en": "Al Shifaa Pharmacy",
    }


def test_published_semantic_entities_endpoint_returns_names_and_legacy_name(client):
    token, _ = create_admin_and_get_token(client, email="ml13@example.com")

    # This endpoint loads and scope-checks the Map document before
    # returning anything, so the analysis must reference a REAL Map id.
    seeded_map_id = {}

    async def _seed():
        map_item = Map(title="ML 13 Map", processing_status="completed", scale=1.0)
        await map_item.insert()
        seeded_map_id["id"] = str(map_item.id)

        analysis = SemanticMapAnalysis(
            map_id=seeded_map_id["id"],
            source_fingerprint="fp-ml-13",
            prompt_version="v",
            prompt_sha256="h",
            model="claude-sonnet-4-20250514",
            status="completed",
            ai_result=_multilingual_ai_result(),
            reviewed_result=_multilingual_ai_result(),
        )
        await analysis.insert()
        await publish_analysis(analysis, published_by="tester")

    import asyncio
    asyncio.get_event_loop().run_until_complete(_seed())

    response = client.get(
        f"/api/maps/{seeded_map_id['id']}/semantic-entities",
        headers=auth_headers(token),
    )
    assert response.status_code == 200, response.text
    entities = response.json()
    assert len(entities) == 1
    entity = entities[0]

    assert entity["names"]["ar"] == "صيدلية الشفاء"
    assert entity["names"]["he"] == "בית מרקחת אלשפאא"
    assert entity["names"]["en"] == "Al Shifaa Pharmacy"
    # Server-resolved legacy fallback string, always present.
    assert entity["name"] == "Al Shifaa Pharmacy"


# ---------------------------------------------------------------------
# 14 — real Arabic/Hebrew instruction text, not just English
# ---------------------------------------------------------------------

def test_generate_floor_instructions_produces_real_arabic_and_hebrew_text():
    points = [
        {"id": "p1", "x": 0, "y": 0, "name": "Start"},
        {"id": "p2", "x": 100, "y": 0, "name": "Pharmacy Corner"},
        {"id": "p3", "x": 100, "y": 100, "name": "Destination"},
    ]

    en_instructions = generate_floor_instructions(points, lang="en")
    ar_instructions = generate_floor_instructions(points, lang="ar")
    he_instructions = generate_floor_instructions(points, lang="he")

    assert "Proceed toward" in en_instructions[0]["text"]
    assert "توجه نحو" in ar_instructions[0]["text"]
    assert "המשך לכיוון" in he_instructions[0]["text"]

    # Arrival text also genuinely localized, not just an English string
    # with a language code attached.
    assert "arrived" in en_instructions[-1]["text"].lower()
    assert "وصلت" in ar_instructions[-1]["text"]
    assert "הגעת" in he_instructions[-1]["text"]


def test_generate_floor_instructions_falls_back_to_english_for_unknown_lang():
    points = [
        {"id": "p1", "x": 0, "y": 0, "name": "Start"},
        {"id": "p2", "x": 100, "y": 0, "name": "End"},
    ]
    fallback = generate_floor_instructions(points, lang="fr")
    english = generate_floor_instructions(points, lang="en")
    assert fallback[0]["text"] == english[0]["text"]


# ---------------------------------------------------------------------
# 15 — transition instructions + resolve_localized_display_name
# ---------------------------------------------------------------------

def test_generate_transition_instruction_localizes_floor_label():
    en_step = generate_transition_instruction(
        connector_type="elevator",
        connector_name="Elevator A",
        to_floor=2,
        to_floor_label=None,
        lang="en",
    )
    ar_step = generate_transition_instruction(
        connector_type="elevator",
        connector_name="Elevator A",
        to_floor=2,
        to_floor_label=None,
        lang="ar",
    )
    he_step = generate_transition_instruction(
        connector_type="elevator",
        connector_name="Elevator A",
        to_floor=2,
        to_floor_label=None,
        lang="he",
    )

    assert "Floor 2" in en_step["text"]
    assert "الطابق 2" in ar_step["text"]
    assert "קומה 2" in he_step["text"]


def test_resolve_localized_display_name_fallback_chain():
    # Requested language present -> used directly.
    assert (
        resolve_localized_display_name(
            "Technical Name",
            display_name_en="English Display",
            display_name_ar="Arabic Display",
            lang="ar",
        )
        == "Arabic Display"
    )

    # Requested language missing -> falls through en -> ar -> he.
    assert (
        resolve_localized_display_name(
            "Technical Name",
            display_name_en="English Display",
            lang="he",
        )
        == "English Display"
    )

    # No per-language values at all, legacy display_name still used.
    assert (
        resolve_localized_display_name(
            "Technical Name",
            display_name="Legacy Display",
            lang="ar",
        )
        == "Legacy Display"
    )

    # Nothing at all and auto-generated -> never leaks the raw technical
    # name to a normal user.
    assert (
        resolve_localized_display_name(
            "Corridor Point 1784904901734-6",
            is_auto_generated=True,
            lang="en",
        )
        is None
    )


# ---------------------------------------------------------------------
# 16 — backfill-room-names: safe, optional, idempotent
# ---------------------------------------------------------------------

def test_backfill_room_names_dry_run_never_writes(client):
    token, _ = create_admin_and_get_token(client, email="ml16a@example.com")
    building = client.post(
        "/api/locations/buildings",
        json={"name_en": "ML Building 16A"},
        headers=auth_headers(token),
    ).json()

    room = client.post(
        "/api/rooms",
        json={
            "building_id": building["id"],
            "name_en": "Legacy Room Sixteen A",
            "room_type": "room",
        },
        headers=auth_headers(token),
    ).json()
    assert room["names"] is None

    dry = client.post(
        "/api/maintenance/backfill-room-names",
        headers=auth_headers(token),
    )
    assert dry.status_code == 200, dry.text
    body = dry.json()
    assert body["dry_run"] is True
    assert room["id"] in body["room_ids"]

    # Never actually wrote anything.
    unchanged = client.get(f"/api/rooms/{room['id']}").json()
    assert unchanged["names"] is None


def test_backfill_room_names_writes_only_name_en_and_is_idempotent(client):
    token, _ = create_admin_and_get_token(client, email="ml16b@example.com")
    building = client.post(
        "/api/locations/buildings",
        json={"name_en": "ML Building 16B"},
        headers=auth_headers(token),
    ).json()

    room = client.post(
        "/api/rooms",
        json={
            "building_id": building["id"],
            "name_en": "Legacy Room Sixteen B",
            "room_type": "room",
        },
        headers=auth_headers(token),
    ).json()

    real_run = client.post(
        "/api/maintenance/backfill-room-names?dry_run=false",
        headers=auth_headers(token),
    )
    assert real_run.status_code == 200, real_run.text
    assert real_run.json()["rooms_updated"] == 1

    updated = client.get(f"/api/rooms/{room['id']}").json()
    # Only the known-English legacy value was backfilled — ar/he are
    # never guessed/invented.
    assert updated["names"] == {"ar": None, "he": None, "en": "Legacy Room Sixteen B"}

    # Running it again changes nothing further (idempotent) — the room
    # already has `names` set, so it's excluded from the next pass.
    second_run = client.post(
        "/api/maintenance/backfill-room-names?dry_run=false",
        headers=auth_headers(token),
    )
    assert second_run.status_code == 200, second_run.text
    assert room["id"] not in second_run.json()["room_ids"]

    still_same = client.get(f"/api/rooms/{room['id']}").json()
    assert still_same["names"] == {"ar": None, "he": None, "en": "Legacy Room Sixteen B"}
