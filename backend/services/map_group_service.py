"""
Shared map-group code normalization/generation.

A map group's `code` is its stable, unique, admin-facing identity for the
whole multi-floor set (e.g. "QRMALL-001"). This module is the single place
that decides whether a candidate code is valid and how an automatic one is
generated, so both the create-group route and any future admin-facing
"rename code" action apply exactly the same rules.
"""

import re
from typing import Optional

from fastapi import HTTPException, status

from models.map_group_model import MapGroup


# Letters, digits, and hyphens only; must start with a letter/digit; 2-40
# characters after normalization. Deliberately conservative — this code is
# meant to be typed/read by a human (e.g. printed on a location-code
# label), so spaces, punctuation, and non-ASCII characters are rejected
# rather than silently stripped (silently stripping could make two
# admin-entered codes collide unexpectedly).
_CODE_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9\-]{1,39}$")

_DEFAULT_CODE_BASE = "MAPGROUP"


def normalize_group_code(raw_code: str) -> str:
    """
    Trim/uppercase an admin-provided code and reject anything unsafe.
    Raises HTTPException(422) on invalid input — never silently mutates a
    code into something the admin didn't type (beyond trim + uppercase).
    """

    cleaned = (raw_code or "").strip().upper()

    if not cleaned:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Map group code cannot be empty.",
        )

    if not _CODE_PATTERN.match(cleaned):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Map group code may only contain letters, numbers, and "
                "hyphens, and must be 2-40 characters long."
            ),
        )

    return cleaned


def _slugify_base(name: str) -> str:
    base = re.sub(r"[^A-Z0-9]+", "", (name or "").upper())
    return base[:12] or _DEFAULT_CODE_BASE


async def generate_unique_group_code(name: str) -> str:
    """
    Auto-generates a stable, unique code derived from the group name
    (e.g. "QuickRoute Mall Indoor Map" -> "QUICKROUTEMA-001") when the
    admin does not supply a custom one. Never called again for a group
    once it has a code — group creation is the only place this runs, so a
    later "add another floor" call always reuses the existing code
    untouched (see routes/map_groups_routes.py).
    """

    base = _slugify_base(name)

    for suffix in range(1, 1000):
        candidate = f"{base}-{suffix:03d}"
        existing = await MapGroup.find_one(MapGroup.code == candidate)
        if not existing:
            return candidate

    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Could not generate a unique map group code, try again.",
    )


async def resolve_group_code(
    name: str,
    explicit_code: Optional[str],
) -> str:
    """
    The full code-resolution flow for creating a new group:
      - an admin-supplied code is normalized and rejected if it collides
        with an existing group's code (case-insensitive, since it is
        always uppercased first);
      - otherwise a fresh unique code is generated from the group name.
    """

    if explicit_code and explicit_code.strip():
        normalized = normalize_group_code(explicit_code)

        existing = await MapGroup.find_one(MapGroup.code == normalized)
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Map group code '{normalized}' is already in use.",
            )

        return normalized

    return await generate_unique_group_code(name)
