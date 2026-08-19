"""
Prompt section N.1 — display-name population for FUTURE semantic analyses.

WHY THIS FILE IS ALL STATIC
---------------------------
Section N.1 is prompt text sent to Claude. No test can assert what the
model will answer, and deliberately nothing here tries: running a real
analysis would mean sending a real floor plan to a real provider and
writing a real analysis record. Every test below reads the prompt file
and the schema module. Nothing here calls an AI provider, analyzes a map,
enqueues a job, publishes a result, or writes to MongoDB.

What IS worth asserting, and is asserted here:

  1. The policy is present in the ACTIVE prompt — the one file
     services/semantic_prompt_loader loads and hashes into every analysis
     record — so a later edit cannot silently drop it.

  2. It reuses the EXISTING names.original/en/ar/he structure and adds no
     competing one, in the prompt or in the response schema.

  3. It is a rule, not a lookup table: no room-name dictionary, no
     abbreviation dictionary, and no example taken from any real building.

The prompt is hard-wrapped, so assertions run against a whitespace-
normalised copy — matching the exact wrapping would be asserting the line
breaks rather than the rule.

Run with: pytest backend/tests/test_semantic_multilingual_display_names.py -v
"""

import re

import pytest

from schemas.semantic_analysis_schema import SemanticMapImportV2
from services import semantic_prompt_loader


NAME_FIELDS = ("original", "en", "ar", "he")


@pytest.fixture(scope="module")
def prompt_raw():
    semantic_prompt_loader.clear_prompt_cache()
    return semantic_prompt_loader.get_prompt_text()


@pytest.fixture(scope="module")
def prompt_text(prompt_raw):
    return re.sub(r"\s+", " ", prompt_raw)


# ===========================================================
# 1. The four existing fields, and only those
# ===========================================================

def test_the_addendum_is_present_in_the_active_prompt(prompt_text):
    assert "N.1 DISPLAY-NAME POPULATION (ADDENDUM TO SECTION N)" in prompt_text


def test_it_lives_inside_the_existing_multilingual_section(prompt_raw):
    """
    Placed at the end of Section N, before Section O — so it reads as a
    refinement of the multilingual rules that already exist rather than a
    second, competing policy somewhere else in the file.
    """

    multilingual = prompt_raw.index("N. MULTILINGUAL RULES")
    addendum = prompt_raw.index("N.1 DISPLAY-NAME POPULATION")
    taxonomy = prompt_raw.index("O. UNIVERSAL OPEN TAXONOMY")

    assert multilingual < addendum < taxonomy


def test_it_names_the_four_existing_fields(prompt_text):
    for field in NAME_FIELDS:
        assert f"names.{field}" in prompt_text, field


def test_no_second_multilingual_structure_is_introduced(prompt_text):
    for forbidden in (
        "translated_names",
        "localized_names",
        "labels_ar",
        "labels_he",
        "names_ar",
        "names_he",
        "display_names",
        "i18n",
    ):
        assert forbidden not in prompt_text, forbidden


def test_the_addendum_says_so_itself(prompt_text):
    assert "introduces no new field" in prompt_text
    assert "no second naming structure" in prompt_text


def test_the_response_schema_still_has_exactly_the_existing_name_object():
    """
    The schema is untouched by this change. If the addendum had implied a
    new field, this is where it would show up.
    """

    schema = SemanticMapImportV2.model_json_schema()
    definitions = schema.get("$defs", {})

    name_models = {
        name: model
        for name, model in definitions.items()
        if set(model.get("properties", {})) >= {"en", "ar", "he"}
    }

    assert name_models, "no multilingual name model found in the schema"

    for name, model in name_models.items():
        extra = set(model["properties"]) - set(NAME_FIELDS) - {
            "label_original",
            "full_original",
        }
        assert not extra, f"{name} gained unexpected name fields: {sorted(extra)}"


# ===========================================================
# 2. names.original stays verbatim
# ===========================================================

def test_names_original_must_be_the_exact_visible_label(prompt_text):
    assert "names.original is always the exact label as it is visible" in prompt_text


def test_names_original_may_not_be_translated_or_normalized(prompt_text):
    for rule in (
        "Never translate it.",
        "Never normalize, tidy, reorder or re-case it.",
        "Never replace it with a preferred English name.",
        "Never alter its wording, punctuation, spacing, number or code.",
    ):
        assert rule in prompt_text, rule


def test_display_values_never_feed_back_into_the_original(prompt_text):
    assert "They never feed back into it." in prompt_text


# ===========================================================
# 3. Clear descriptive destinations populate EN/AR/HE
# ===========================================================

def test_clear_descriptive_labels_are_translated_into_all_three(prompt_text):
    assert "When the visible label states what the space IS in ordinary words" in prompt_text
    assert "give a natural display value in each of the three languages" in prompt_text


def test_routine_nulls_are_explicitly_discouraged(prompt_text):
    assert (
        "Do not leave names.en, names.ar or names.he null merely because "
        "filling them requires translating" in prompt_text
    )


def test_the_null_placeholders_in_the_json_templates_are_disclaimed(prompt_text):
    """
    The schema templates further down the prompt show every name field as
    null. Without this note the model can read those as the recommended
    answer — which is exactly what produced empty ar/he in practice.
    """

    assert "empty placeholders illustrating the SHAPE" in prompt_text
    assert "not a recommendation to leave translations empty" in prompt_text


# ===========================================================
# 4. Numbers and identifiers survive
# ===========================================================

def test_identifiers_are_carried_through_unchanged(prompt_text):
    assert "carried through every display language unchanged" in prompt_text
    assert "same order relative to the translated words" in prompt_text


def test_identifiers_may_not_be_transformed_in_any_way(prompt_text):
    assert (
        "Never translate, transliterate, renumber, reformat, reorder, drop "
        "or invent an identifier." in prompt_text
    )
    assert "Never convert digits to another numeral system." in prompt_text


# ===========================================================
# 5. Descriptive wording + code stays translatable
# ===========================================================

def test_a_code_does_not_by_itself_make_a_label_untranslatable(prompt_text):
    assert "A code in the label does not make the label uninterpretable" in prompt_text
    assert "translate the words and carry the code through unchanged" in prompt_text


# ===========================================================
# 6. Code-only labels are preserved, never guessed
# ===========================================================

def test_code_only_labels_are_preserved_in_all_four_fields(prompt_text):
    assert "N.1.6 Code-only labels: preserve, never guess" in prompt_text
    assert "put the exact source label in all four fields" in prompt_text


def test_a_plausible_guess_is_explicitly_not_enough(prompt_text):
    assert "That guess is not sufficient" in prompt_text
    assert (
        "If the meaning is not written out in the label itself, and the "
        "drawing gives no reliable indication of it, do not expand it."
        in prompt_text
    )


def test_an_abbreviation_does_not_carry_meaning_between_buildings(prompt_text):
    assert (
        "An abbreviation seen in one building never carries its meaning "
        "to another." in prompt_text
    )


def test_the_reason_preserving_is_safer_is_stated(prompt_text):
    assert "A confident-looking wrong expansion is not" in prompt_text
    assert "nothing downstream can detect it" in prompt_text


# ===========================================================
# 7. Proper names and brands are protected
# ===========================================================

def test_identity_is_preserved_for_proper_and_business_names(prompt_text):
    assert "Do not invent a translation that changes identity" in prompt_text
    assert "preserve identity rather than producing a translated variant" in prompt_text


def test_semantic_safety_outranks_filling_every_language(prompt_text):
    assert (
        "Filling all three languages is never a reason to invent a meaning"
        in prompt_text
    )
    assert "semantic safety wins" in prompt_text


def test_the_existing_do_not_translate_unclear_text_rule_is_still_there(prompt_raw):
    """
    Section N's own rule, which the addendum defers to rather than
    replaces. It must survive this edit intact.
    """

    assert "Do not translate unclear text." in prompt_raw
    assert "Do not replace original text with translated text." in prompt_raw


# ===========================================================
# 8. Source language is never assumed
# ===========================================================

def test_the_source_language_is_not_assumed_to_be_english(prompt_text):
    assert "The source language is never assumed" in prompt_text
    assert (
        "A drawing may be labelled in Arabic, in Hebrew, in English, in a "
        "mix, or in another script" in prompt_text
    )


def test_a_label_is_never_rewritten_for_the_selected_language(prompt_text):
    assert (
        "A label is never rewritten merely because a different display "
        "language exists." in prompt_text
    )


# ===========================================================
# 9. Building/map agnostic — a rule, not a dictionary
# ===========================================================

def test_the_addendum_forbids_matching_against_a_fixed_list(prompt_text):
    assert "do not match it against a fixed list" in prompt_text
    assert "Judge each label on what it actually says" in prompt_text


def test_the_examples_are_labelled_synthetic(prompt_raw):
    section = prompt_raw[
        prompt_raw.index("N.1 DISPLAY-NAME POPULATION") :
        prompt_raw.index("O. UNIVERSAL OPEN TAXONOMY")
    ]

    # Every worked example in the addendum is flagged as illustrative, so
    # it cannot be mistaken for a real label to memorise.
    assert section.count("Synthetic example") == 3
    assert section.count("illustrative only") == 3


def test_no_real_building_identifier_appears_in_the_addendum(prompt_raw):
    """
    The addendum must not encode anything about the building this project
    happens to be deployed against — no real room names, numbers,
    abbreviations, floor identifiers or department names. Its examples are
    invented for the purpose.
    """

    section = prompt_raw[
        prompt_raw.index("N.1 DISPLAY-NAME POPULATION") :
        prompt_raw.index("O. UNIVERSAL OPEN TAXONOMY")
    ]

    for abbreviation in ("RRW", "RRM", "TEL", "ELEC", "MDF", "AHU"):
        assert not re.search(rf"\b{abbreviation}\b", section), abbreviation


def test_the_addendum_maps_no_abbreviation_to_a_meaning(prompt_raw):
    section = prompt_raw[
        prompt_raw.index("N.1 DISPLAY-NAME POPULATION") :
        prompt_raw.index("O. UNIVERSAL OPEN TAXONOMY")
    ]

    # An expansion of an abbreviation would make this a lookup table for
    # that one abbreviation and leave every other building's unhandled.
    for expansion in ("telephone", "telecom", "telemetry", "main distribution"):
        assert expansion not in section.lower(), expansion


def test_the_addendum_shows_worked_examples_with_populated_translations(prompt_raw):
    """
    The failure this whole addendum exists to fix is that every worked
    example in the prompt showed names.ar and names.he as null, so the
    model read null as the expected answer. Describing the rule in prose
    is not enough to unlearn that — at least two examples have to SHOW
    the three display languages actually filled in.

    These are the only translated strings in the addendum, and they exist
    to demonstrate the shape of a populated result, not to be reused: the
    labels are invented (see the building-agnostic tests above), so there
    is nothing here for the model to match a real drawing against.
    """

    section = prompt_raw[
        prompt_raw.index("N.1 DISPLAY-NAME POPULATION") :
        prompt_raw.index("O. UNIVERSAL OPEN TAXONOMY")
    ]

    arabic = [ch for ch in section if "؀" <= ch <= "ۿ"]
    hebrew = [ch for ch in section if "֐" <= ch <= "׿"]

    assert arabic, "no worked example shows a populated names.ar"
    assert hebrew, "no worked example shows a populated names.he"

    # Two synthetic labels, each shown as a complete four-field object.
    populated = re.findall(
        r'"names":\s*\{\s*'
        r'"original":\s*"(?P<original>[^"]+)",\s*'
        r'"en":\s*"(?P<en>[^"]+)",\s*'
        r'"ar":\s*"(?P<ar>[^"]+)",\s*'
        r'"he":\s*"(?P<he>[^"]+)"\s*\}',
        section,
    )

    assert len(populated) >= 2, populated

    for original, en, ar, he in populated:
        # Every field carries a real value — this is the anti-null proof.
        assert original and en and ar and he

        # ar/he are genuinely translated, not the English echoed back.
        assert any("֐" <= ch <= "ۿ" for ch in ar + he), (original, ar, he)

        # names.original is the source label, reproduced verbatim.
        assert original == en, (original, en)

    # At least one example carries an invented identifier, and it survives
    # byte-identically into all four values.
    identifier_examples = [
        row for row in populated if re.search(r"[A-Z]-?\d", row[0])
    ]

    assert identifier_examples, populated

    for original, en, ar, he in identifier_examples:
        identifier = re.search(r"[A-Z]+-?\d+", original).group(0)
        for value in (original, en, ar, he):
            assert identifier in value, (identifier, value)


def test_the_code_only_example_stays_unpopulated_and_preserved(prompt_raw):
    """
    The counterweight: the ambiguous-code example must NOT have been
    swept along into the populated style. It still shows the source label
    repeated verbatim across all four fields rather than a translation.
    """

    section = prompt_raw[
        prompt_raw.index("N.1.6 Code-only labels") :
        prompt_raw.index("N.1.7 Proper names")
    ]

    for line in (
        "names.original:  ZX-204",
        "names.en:        ZX-204",
        "names.ar:        ZX-204",
        "names.he:        ZX-204",
    ):
        assert line in section, line

    # Nothing was translated here.
    assert not any("֐" <= ch <= "ۿ" for ch in section)


# ===========================================================
# 10. Scope — this changes nothing but three display fields
# ===========================================================

def test_the_addendum_declares_its_own_scope(prompt_text):
    assert "authoritative FOR THESE FOUR FIELDS ONLY" in prompt_text
    assert "It changes nothing else." in prompt_text


def test_every_other_semantic_rule_is_declared_unaffected(prompt_text):
    for untouched in (
        "Entity detection",
        "categories",
        "nesting",
        "parent and pass-through relationships",
        "geometry",
        "evidence",
        "confidence",
        "review requirements",
        "detected_language",
        "alternative_readings",
        "the output structure",
    ):
        assert untouched in prompt_text, untouched


# ===========================================================
# 11. Nothing about this edit can trigger work by itself
# ===========================================================

def test_editing_the_prompt_cannot_enqueue_or_reanalyze_anything():
    """
    The decisive safety property, asserted from the source rather than by
    running anything: the worker's only queue is `status == "queued"`, and
    no code anywhere compares the current prompt hash against a stored one
    to decide that an analysis should be redone. So changing this file
    cannot, by itself, cause any existing analysis to be re-run.
    """

    from pathlib import Path

    backend = Path(semantic_prompt_loader.__file__).resolve().parent.parent

    worker = (backend / "services" / "semantic_analysis_worker.py").read_text(
        encoding="utf-8"
    )

    # The queue is a status field, not a prompt comparison.
    assert 'find_one({"status": "queued"})' in worker
    assert "prompt_sha256" not in worker
    assert "get_prompt_text" not in worker

    # No production module decides to re-run anything by comparing hashes.
    for folder in ("routes", "services"):
        for path in (backend / folder).glob("*.py"):
            source = path.read_text(encoding="utf-8")
            for trigger in (
                "prompt_sha256 !=",
                "prompt_sha256 ==",
                "!= get_prompt_sha256",
                "== get_prompt_sha256",
            ):
                assert trigger not in source, f"{path.name}: {trigger}"


def test_the_prompt_is_read_only_when_an_analysis_actually_runs():
    """
    get_prompt_text() has exactly one production call site — inside the
    provider call for a job that is already being processed. It is not
    read at import time, at startup, or on any read endpoint.
    """

    from pathlib import Path

    backend = Path(semantic_prompt_loader.__file__).resolve().parent.parent

    call_sites = []

    for folder in ("routes", "services"):
        for path in (backend / folder).glob("*.py"):
            if path.name == "semantic_prompt_loader.py":
                continue
            source = path.read_text(encoding="utf-8")
            call_sites.extend(
                [path.name] * source.count("get_prompt_text()")
            )

    assert call_sites == ["semantic_analysis_service.py"], call_sites

    startup = (backend / "app.py").read_text(encoding="utf-8")
    assert "get_prompt_text" not in startup
