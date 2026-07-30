"""
Building identity resolution.

Map upload (and the current-data backfill) both need the same answer to
"is this the same building we already have, or a new one?" — this module
is the single place that decides, so there is exactly one definition of
building identity instead of ad-hoc string comparisons scattered across
routes.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Optional

from models.building_model import Building


def normalize_building_name(raw_name: str) -> str:
    """
    Case/whitespace/diacritic-insensitive identity key for a building name.

    "QuickRoute Mall", "quickroute   mall" and "  QuickRoute Mall  " must
    all resolve to the same building. This intentionally does NOT strip
    non-Latin scripts (Arabic/Hebrew building names) — NFKD + casefold is
    safe for those too, it just normalizes width/compatibility forms and
    combining marks, and casefold() is a no-op for scripts without case.
    """

    if not raw_name:
        return ""

    decomposed = unicodedata.normalize("NFKD", raw_name)
    collapsed_whitespace = re.sub(r"\s+", " ", decomposed).strip()
    return collapsed_whitespace.casefold()


async def find_or_create_building(
    display_name: str,
    *,
    name_local: Optional[str] = None,
    campus: Optional[str] = None,
    category: Optional[str] = None,
) -> Building:
    """
    Look up a Building by its normalized name; create one if none exists.

    Safe to call concurrently/repeatedly with the same name — the unique
    sparse index on Building.normalized_name is the actual source of
    truth for "does this already exist", not just this lookup. If two
    requests race and both miss the initial find(), the loser's insert()
    raises a duplicate-key error, which is caught here and turned into a
    second, now-successful find() instead of a 500 — so callers never see
    a duplicate-building failure from ordinary concurrent map uploads.
    """

    cleaned_name = (display_name or "").strip()

    if not cleaned_name:
        # campus/title were both blank — nothing distinctive to name a
        # building after. Callers are expected to validate this earlier;
        # this is a defensive fallback, not the normal path.
        cleaned_name = "Unnamed Building"

    normalized = normalize_building_name(cleaned_name)

    existing = await Building.find_one(
        Building.normalized_name == normalized
    )

    if existing:
        return existing

    new_building = Building(
        name_en=cleaned_name,
        name_local=name_local,
        campus=campus or cleaned_name,
        category=category,
        normalized_name=normalized,
    )

    try:
        await new_building.insert()
        return new_building
    except Exception as error:
        # Duplicate key on the unique normalized_name index — another
        # concurrent request already created it between our find() and
        # insert(). Re-fetch instead of failing; this is what makes
        # find_or_create_building idempotent under concurrency, not just
        # under sequential re-runs.
        is_duplicate_key = (
            "E11000" in str(error) or "duplicate key" in str(error).lower()
        )

        if not is_duplicate_key:
            raise

        winner = await Building.find_one(
            Building.normalized_name == normalized
        )

        if winner:
            return winner

        raise
