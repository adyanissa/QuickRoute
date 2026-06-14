from datetime import datetime, timezone

from beanie import Document
from pydantic import EmailStr, Field


class User(Document):
    full_name: str = Field(..., min_length=2, max_length=100)
    email: EmailStr
    password: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "users"