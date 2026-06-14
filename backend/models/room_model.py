from datetime import datetime
from typing import Optional

from beanie import Document
from pydantic import Field


class Room(Document):
    building_id: str

    name_en: str
    name_local: Optional[str] = None

    room_number: Optional[str] = None
    floor: Optional[int] = None
    room_type: Optional[str] = None

    description: Optional[str] = None
    category: Optional[str] = None

    is_active: bool = True

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "rooms"