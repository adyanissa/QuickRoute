from datetime import datetime, timezone
from typing import Optional

from beanie import Document
from pydantic import Field


class InvitationCode(Document):
    code: str = Field(..., min_length=6, max_length=30)
    is_used: bool = False
    used_by_email: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    used_at: Optional[datetime] = None

    class Settings:
        name = "invitation_codes"