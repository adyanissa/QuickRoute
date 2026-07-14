from datetime import datetime, timezone
from typing import Literal, Optional

from beanie import Document
from pydantic import Field


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

    is_used: bool = False
    used_by_email: Optional[str] = None

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    used_at: Optional[datetime] = None

    class Settings:
        name = "invitation_codes"