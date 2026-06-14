from datetime import datetime
from typing import Optional

from beanie import Document
from pydantic import Field


class Building(Document):
    name_en: str
    name_local: Optional[str] = None
    description: Optional[str] = None
    short_tag: Optional[str] = None
    icon_color: Optional[str] = None
    category: Optional[str] = None
    campus: Optional[str] = None
    is_active: bool = True

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "buildings"