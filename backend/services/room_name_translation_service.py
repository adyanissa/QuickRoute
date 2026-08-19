"""
One-off, admin-triggered translation backfill for EXISTING Destinations.

WHY THIS EXISTS
---------------
The multilingual plumbing has been correct for a long time: Room.names is a
{"ar","he","en"} object, every API schema carries it, and both
schemas/localization_schema.get_localized_text() and the frontend's mirror
of it resolve a name for the current UI language. What was missing was the
DATA — the semantic-analysis prompt treated ar/he as optional, so rooms
created from a floor plan were persisted as
{"en": "Electrical Room", "ar": None, "he": None} and every locale
correctly fell back to English.

This module fills ONLY those empty language slots on rooms that already
exist. It is deliberately separate from
routes/maintenance_routes.backfill_room_names, which copies name_en into
names.en and explicitly never invents a translation — that endpoint stays
exactly as it is.

WHAT IT MAY TOUCH
-----------------
names.ar and names.he, and only when they are currently empty.

It never writes any other Room field, and never reads or writes RoutePoint,
RouteEdge, LocationCode, Map or Building at all — the navigation graph,
placement coordinates, QR codes and Auto Connect state are untouched by
construction, not merely by convention. The only Beanie write in this whole
flow is `room.set({...})` limited to `names` (plus `updated_at`) in
routes/maintenance_routes.py.

PROVIDER
--------
Reuses this project's existing Anthropic configuration verbatim —
get_anthropic_api_key() and get_analysis_model() from
services/semantic_analysis_service. No new provider, no new dependency, no
new environment variable. One batched request per run, never one per room.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Sequence

from schemas.localization_schema import (
    SUPPORTED_LANGUAGES,
    localized_text_to_dict,
)
from services.semantic_analysis_service import (
    Anthropic,
    SemanticAnalysisError,
    _strip_outer_markdown_fence,
    get_analysis_model,
    get_anthropic_api_key,
)

# The languages this backfill is able to fill. `en` is deliberately absent:
# it is the source text, never a target.
TRANSLATABLE_LANGUAGES = ("ar", "he")

# One request covers this many distinct names. 164 destinations is a single
# chunk; the cap exists only so an unusually large estate still works.
MAX_NAMES_PER_REQUEST = 200

# Generous but bounded — the reply is a small JSON object, never prose.
MAX_OUTPUT_TOKENS = 8000


TRANSLATION_SYSTEM_PROMPT = """\
You translate indoor-wayfinding DESTINATION NAMES for a building navigation
app. You will receive a JSON array of names in English. Return translations
into Arabic and Hebrew.

Return ONLY a JSON object, no prose and no Markdown fence:

{"translations": [{"source": "<exact input string>", "ar": "<Arabic>", "he": "<Hebrew>"}]}

RULES

1. `source` must be the input string reproduced EXACTLY, character for
   character. It is the key used to match your answer back to a record.

2. Translate GENERIC, FUNCTIONAL space names naturally, the way a sign in a
   real building in that language would read. Examples of the KIND of name
   this applies to (this is not a closed list — translate any functional
   space name you are given): electrical room, control room, storage,
   office, restroom, shower, laboratory, reception, meeting room, stairs,
   elevator, corridor, kitchen, waiting area, server room, workshop.

3. PRESERVE room numbers, codes and identifiers EXACTLY as they appear —
   digits, letters and separators unchanged, in the same order relative to
   the translated words. "Meeting Room B" keeps its "B". "Lab 204" keeps
   "204". Do not convert digits to another numeral system.

4. Do NOT translate a PROPER NAME or a BUSINESS/BRAND name. If the name
   identifies a specific company, shop, person, department brand or
   institution rather than a function, return null for that language. Never
   substitute a different business identity, and never guess what a brand
   "means".

5. If you are UNSURE what a name refers to, or it is an abbreviation you
   cannot confidently expand, return null for that language. A null is
   always safe: the app keeps showing the English name. An invented or
   approximate translation is not safe.

6. Never return an empty string. Use null.

7. Return one entry per input name, and no entries for names you were not
   given.
"""


class RoomNameTranslationError(RuntimeError):
    """Stable, safe-to-surface failure. Mirrors SemanticAnalysisError's
    shape so the route can report it the same way, and never carries an API
    key or a raw stack trace."""

    def __init__(self, error_code: str, message: str):
        super().__init__(message)
        self.error_code = error_code
        self.message = message


def _clean(value: Any) -> Optional[str]:
    """Whitespace-only is never a usable translation — the same rule
    schemas/localization_schema applies."""

    if not isinstance(value, str):
        return None

    stripped = value.strip()
    return stripped or None


def missing_languages(names: Any) -> List[str]:
    """
    Which of ar/he this record still needs, given its CURRENT names object.

    A language that already holds any non-empty string is never listed, so
    a manually corrected translation can never become a candidate for
    overwriting.
    """

    current = localized_text_to_dict(names)
    return [lang for lang in TRANSLATABLE_LANGUAGES if not current.get(lang)]


def room_needs_translation(room) -> bool:
    return bool(missing_languages(getattr(room, "names", None)))


def source_text_for(room) -> Optional[str]:
    """
    The English string to translate FROM.

    names.en first (the structured value), then the legacy flat name_en.
    name_local is deliberately not used: this codebase's name_local
    convention does not record WHICH language it holds, so treating it as
    English would risk translating Hebrew text as though it were English.
    """

    current = localized_text_to_dict(getattr(room, "names", None))
    return current.get("en") or _clean(getattr(room, "name_en", None))


def collect_source_names(rooms: Sequence[Any]) -> List[str]:
    """
    The DISTINCT English strings a batch needs translated.

    Distinct matters: 164 destinations across a campus commonly contain the
    same "Storage" or "Electrical Room" many times, and each repeated name
    costs nothing extra this way.
    """

    seen: Dict[str, None] = {}

    for room in rooms:
        if not room_needs_translation(room):
            continue

        source = source_text_for(room)
        if source:
            seen.setdefault(source, None)

    return list(seen.keys())


def parse_translation_payload(raw_text: str) -> Dict[str, Dict[str, Optional[str]]]:
    """
    Turns the model's reply into {source: {"ar": str|None, "he": str|None}}.

    Hostile to malformed output by design — this is the boundary that
    protects the database from a bad generation:
      * anything that is not a JSON object with a `translations` list is a
        hard failure, never a partial write;
      * an entry without a usable `source` string is skipped;
      * a value that is not a non-empty string becomes None, which the
        caller treats as "no proposal", never as "blank it out";
      * unknown keys are ignored.
    """

    cleaned = _strip_outer_markdown_fence(raw_text or "")

    try:
        payload = json.loads(cleaned)
    except (json.JSONDecodeError, TypeError) as error:
        raise RoomNameTranslationError(
            "invalid_json", f"Translation response was not valid JSON: {error}"
        ) from error

    if not isinstance(payload, dict):
        raise RoomNameTranslationError(
            "invalid_shape", "Translation response was not a JSON object."
        )

    entries = payload.get("translations")

    if not isinstance(entries, list):
        raise RoomNameTranslationError(
            "invalid_shape",
            "Translation response had no `translations` array.",
        )

    result: Dict[str, Dict[str, Optional[str]]] = {}

    for entry in entries:
        if not isinstance(entry, dict):
            continue

        source = _clean(entry.get("source"))
        if not source:
            continue

        result[source] = {
            lang: _clean(entry.get(lang)) for lang in TRANSLATABLE_LANGUAGES
        }

    return result


def call_translation_provider(names: Sequence[str]) -> Dict[str, Dict[str, Optional[str]]]:
    """
    ONE batched Anthropic request for the whole list of distinct names.

    Synchronous by design — the caller runs it via asyncio.to_thread so it
    never blocks the event loop, exactly like
    call_ai_provider_for_analysis. Uses the project's existing key and
    model settings; adds no configuration of its own.
    """

    if not names:
        return {}

    if Anthropic is None:
        raise RoomNameTranslationError(
            "provider_package_missing",
            "The anthropic Python package is not installed on the server.",
        )

    api_key = get_anthropic_api_key()

    if not api_key:
        raise RoomNameTranslationError(
            "missing_api_key", "ANTHROPIC_API_KEY is not configured."
        )

    client = Anthropic(api_key=api_key)

    collected: Dict[str, Dict[str, Optional[str]]] = {}

    for start in range(0, len(names), MAX_NAMES_PER_REQUEST):
        chunk = list(names[start : start + MAX_NAMES_PER_REQUEST])

        try:
            message = client.messages.create(
                model=get_analysis_model(),
                max_tokens=MAX_OUTPUT_TOKENS,
                system=TRANSLATION_SYSTEM_PROMPT,
                messages=[
                    {
                        "role": "user",
                        "content": json.dumps(chunk, ensure_ascii=False),
                    }
                ],
            )
        except SemanticAnalysisError:
            raise
        except Exception as error:  # noqa: BLE001 - never leak the key/stack
            raise RoomNameTranslationError(
                "provider_request_failed",
                f"The translation request failed: {type(error).__name__}",
            ) from error

        raw_text = "".join(
            block.text
            for block in getattr(message, "content", [])
            if getattr(block, "type", None) == "text"
        )

        collected.update(parse_translation_payload(raw_text))

    return collected


def build_proposal(room, translations: Dict[str, Dict[str, Optional[str]]]) -> Optional[Dict[str, Any]]:
    """
    The per-room proposal, computed with NO database access and NO writes.

    Returns None when there is nothing to propose — the room already has
    both languages, has no English source, or the model returned nothing
    usable for it (an unknown, a brand name, or an entry it declined).

    `will_change` lists only languages that are currently empty AND have a
    usable new value, so an entry can never propose overwriting or blanking
    an existing translation.
    """

    needed = missing_languages(getattr(room, "names", None))

    if not needed:
        return None

    source = source_text_for(room)

    if not source:
        return None

    suggested = translations.get(source) or {}
    current = localized_text_to_dict(getattr(room, "names", None))

    proposed = dict(current)
    will_change: List[str] = []

    for lang in needed:
        value = _clean(suggested.get(lang))
        if value:
            proposed[lang] = value
            will_change.append(lang)

    if not will_change:
        return None

    return {
        "room_id": str(room.id),
        "map_id": room.map_id,
        "building_id": room.building_id,
        "source_name": source,
        "current": {lang: current.get(lang) for lang in SUPPORTED_LANGUAGES},
        "proposed": {lang: proposed.get(lang) for lang in SUPPORTED_LANGUAGES},
        "will_change": will_change,
    }


def build_proposals(
    rooms: Sequence[Any], translations: Dict[str, Dict[str, Optional[str]]]
) -> List[Dict[str, Any]]:
    proposals = []

    for room in rooms:
        proposal = build_proposal(room, translations)
        if proposal is not None:
            proposals.append(proposal)

    return proposals


def updates_for_room(room, proposal: Dict[str, Any]) -> Dict[str, Optional[str]]:
    """
    The final `names` value to persist, recomputed against the room as it
    exists RIGHT NOW rather than as it looked when the preview was built.

    This is the stale-preview guard: a language an admin filled in by hand
    between preview and apply is no longer empty, so it is dropped from the
    update and keeps the admin's text. Returns the complete merged names
    object; the caller writes only the `names` field.
    """

    current = localized_text_to_dict(getattr(room, "names", None))
    proposed = proposal.get("proposed") or {}

    merged = dict(current)
    applied: List[str] = []

    for lang in TRANSLATABLE_LANGUAGES:
        if current.get(lang):
            continue  # already has a value — never overwrite

        value = _clean(proposed.get(lang))
        if value:
            merged[lang] = value
            applied.append(lang)

    # `en` is never sourced from the proposal: the English name is the
    # input, not an output, and must survive this operation untouched.
    merged["en"] = current.get("en")

    return {"names": merged, "applied": applied}
