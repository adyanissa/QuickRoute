from datetime import datetime, timezone
from typing import Literal, Optional

from beanie import Document
from pydantic import Field
from pymongo import IndexModel


InvitationRole = Literal[
    "super_admin",
    "global_manager",
    "building_manager",
    "regular_user",
]


class InvitationCode(Document):
    code: str = Field(..., min_length=6, max_length=30)

    role: InvitationRole = "regular_user"
    building_ids: list[str] = Field(default_factory=list)
    all_buildings: bool = False

    # Additive/backward-compatible (RBAC/dashboard cleanup task, Phase 2)
    # — mirrors User.map_group_ids/map_ids so a building_manager invitation
    # can optionally narrow scope below building level. Existing
    # invitation documents without these fields load with the empty-list
    # default, no migration needed.
    map_group_ids: list[str] = Field(default_factory=list)
    map_ids: list[str] = Field(default_factory=list)

    # Optional restriction: only this email may consume the code. Stored
    # trimmed + lowercased so the comparison at signup never depends on
    # the caller's casing/whitespace.
    intended_email: Optional[str] = None

    # Optional expiry. None = never expires.
    expires_at: Optional[datetime] = None

    # `is_active` is the revocation flag (admin-controlled). `is_used` is
    # the single-use consumption flag (system-controlled at signup). Kept
    # as two distinct booleans so status precedence (used > revoked >
    # expired > active) can be computed unambiguously — see
    # logic/invitation_code_logic.py:compute_invitation_code_status.
    is_active: bool = True
    is_used: bool = False

    created_by_user_id: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    used_at: Optional[datetime] = None
    used_by_user_id: Optional[str] = None
    used_by_email: Optional[str] = None

    revoked_at: Optional[datetime] = None
    revoked_by_user_id: Optional[str] = None

    class Settings:
        name = "invitation_codes"
        indexes = [
            IndexModel("code", unique=True),
        ]
