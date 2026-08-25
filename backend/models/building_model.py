from datetime import datetime
from typing import Optional

from beanie import Document
from pydantic import Field
from pymongo import IndexModel


class Building(Document):
    name_en: str
    name_local: Optional[str] = None
    description: Optional[str] = None
    short_tag: Optional[str] = None
    icon_color: Optional[str] = None
    category: Optional[str] = None
    campus: Optional[str] = None
    is_active: bool = True

    # Case/whitespace/diacritic-insensitive identity key used by
    # find_or_create_building() so "QuickRoute Mall", "quickroute mall" and
    # "  QuickRoute   Mall " all resolve to the same building instead of
    # creating duplicates. Not shown in the API — derived automatically from
    # name_en (or name_local when name_en isn't distinctive) whenever a
    # building is created or renamed. Optional at the schema level only so
    # buildings created before this field existed can still load; a real
    # value is always assigned on insert.
    normalized_name: Optional[str] = None

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "buildings"
        indexes = [
            IndexModel("normalized_name", unique=True, sparse=True),
        ]