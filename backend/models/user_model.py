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

    # Finer-grained scope for building_manager (RBAC/dashboard cleanup
    # task, Phase 2): additive, backward-compatible — every existing user
    # document without these fields loads with the empty-list default via
    # Beanie/Pydantic, no migration required. Empty (the default) means
    # "no map/map-group-level restriction beyond building_ids" — see
    # core/auth_deps.py's check_map_access for the exact precedence
    # (map_ids > map_group_ids > building_ids).
    map_group_ids: list[str] = Field(default_factory=list)
    map_ids: list[str] = Field(default_factory=list)

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "users"