from datetime import datetime
from typing import Optional

from beanie import Document
from pydantic import Field


class Map(Document):
    title: str
    campus: Optional[str] = None
    address: Optional[str] = None
    description: Optional[str] = None
    image_url: Optional[str] = None
    is_current: bool = True

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "maps"