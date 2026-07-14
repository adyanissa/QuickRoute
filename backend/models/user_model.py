from datetime import datetime, timezone
from typing import Literal

from beanie import Document
from pydantic import EmailStr, Field


UserRole = Literal[
    "super_admin",
    "global_manager",
    "building_manager",
    "regular_user",
]


class User(Document):
    full_name: str = Field(..., min_length=2, max_length=100)
    email: EmailStr
    password: str

    role: UserRole = "regular_user"
    building_ids: list[str] = Field(default_factory=list)
    all_buildings: bool = False

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "users"