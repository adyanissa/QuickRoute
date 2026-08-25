"""
Shared, provider-neutral multilingual-text structure used across every
dynamic (database-sourced) piece of content in QuickRoute — semantic map
entities, Destinations/Rooms, and RoutePoint display names.

QuickRoute supports exactly three UI languages: Arabic (ar), Hebrew (he),
and English (en) — matching the frontend's `useLang()` context values
one-for-one. This module is the single source of truth for the canonical
"LocalizedText" shape and its safe resolution logic, so no screen/route
implements its own competing fallback chain (see also
frontend/src/utils/localization.js, which mirrors this exact fallback
order for the client side).

Design constraints (do not relax without re-reading the multilingual
content spec this module implements):
  - Every field is optional. A record with only one language (or none)
    is completely valid — legacy single-language data must never be
    rejected or forced through a translation step.
  - This module NEVER invents/auto-translates text. It only ever
    resolves which already-stored string to show.
  - An empty/whitespace-only string is never treated as a valid
    translation — it is skipped exactly like a missing field.
  - `language` is always validated against the fixed {ar, he, en}
    allowlist before being used to look anything up. It is only ever
    used as a plain Python dict/attribute key here — never concatenated
    into a MongoDB field path or query — but the allowlist check is kept
    regardless, so a bad/unexpected value can never reach a dict lookup
    with attacker-controlled data.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict

# The exact, fixed set of supported UI languages. Keep in sync with
# frontend/src/context/LangContext.jsx's supported values.
SUPPORTED_LANGUAGES = ("ar", "he", "en")

# Resolution order used whenever the exact requested language has no
# usable (non-empty) value. English is preferred as the broadest-reach
# fallback, then Arabic, then Hebrew — matches the order specified for
# get_localized_text() in the multilingual content spec.
FALLBACK_LANGUAGE_ORDER = ("en", "ar", "he")


class LocalizedText(BaseModel):
    """
    {"ar": str | None, "he": str | None, "en": str | None}

    Every field is optional so a record can legitimately carry only one
    or two languages (e.g. an admin corrected only the Arabic name so
    far) without being forced to fabricate the others.
    """

    model_config = ConfigDict(extra="forbid")

    ar: Optional[str] = None
    he: Optional[str] = None
    en: Optional[str] = None


def is_supported_language(language: Optional[str]) -> bool:
    return language in SUPPORTED_LANGUAGES


def _clean(value: Optional[str]) -> Optional[str]:
    """An empty or whitespace-only string is never a valid translation."""
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _as_dict(
    names: Optional["LocalizedText | Dict[str, Any]"],
) -> Dict[str, Any]:
    if names is None:
        return {}
    if isinstance(names, LocalizedText):
        return names.model_dump()
    if isinstance(names, dict):
        return names
    return {}


def get_localized_text(
    names: Optional["LocalizedText | Dict[str, Any]"],
    language: Optional[str],
    legacy_name: Optional[str] = None,
) -> str:
    """
    Resolves the single best string to display for `language`, given a
    (possibly partial, possibly None) set of translations plus an
    optional legacy single-language fallback (e.g. Room.name_en or
    SemanticEntity.names_original).

    Fallback order (never skipped, always applied in this exact order):
      1. the requested language, if it is a real supported value and has
         a non-empty translation;
      2. English;
      3. Arabic;
      4. Hebrew;
      5. the legacy `name` string;
      6. "" (empty string) — the safe placeholder callers can detect and
         render their own "Unnamed"/"—" UI for, never a crash.

    `language` is validated against the fixed {ar, he, en} allowlist
    before being used for a lookup — an unrecognized value (or None) is
    simply treated as "no exact match", never raises, and never reaches
    a raw dict/attribute access with untrusted content.
    """

    data = _as_dict(names)

    if is_supported_language(language):
        requested = _clean(data.get(language))
        if requested:
            return requested

    for fallback_lang in FALLBACK_LANGUAGE_ORDER:
        value = _clean(data.get(fallback_lang))
        if value:
            return value

    legacy = _clean(legacy_name)
    if legacy:
        return legacy

    return ""


def localized_text_to_dict(
    names: Optional["LocalizedText | Dict[str, Any]"],
) -> Dict[str, Optional[str]]:
    """
    Normalizes any of {None, a LocalizedText, a plain dict} into a plain
    {"ar":..., "he":..., "en":...} dict with every key always present
    (None for a language that has no stored value) — the exact shape
    user-facing API responses return under the `names` key.
    """

    data = _as_dict(names)
    return {
        "ar": _clean(data.get("ar")),
        "he": _clean(data.get("he")),
        "en": _clean(data.get("en")),
    }


def merge_localized_text(
    existing: Optional["LocalizedText | Dict[str, Any]"],
    updates: Optional["LocalizedText | Dict[str, Any]"],
) -> Dict[str, Optional[str]]:
    """
    Merges `updates` on top of `existing` ONE LANGUAGE AT A TIME — a key
    that is absent (not present at all) in `updates` keeps its existing
    value; a key that IS present in `updates` (even if explicitly None)
    overwrites just that one language. This is what lets an admin correct
    only the Arabic name without silently touching/blanking the Hebrew or
    English ones (see AdminMapAnalysisScreen.jsx's per-language Correct
    fields), since the caller only ever includes the language(s) that
    were actually edited in `updates`.
    """

    base = localized_text_to_dict(existing)
    changes = _as_dict(updates)
    for lang in SUPPORTED_LANGUAGES:
        if lang in changes:
            base[lang] = _clean(changes.get(lang))
    return base
