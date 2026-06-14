from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class RoomCreate(BaseModel):
    building_id: str = Field(..., min_length=1)

    name_en: str = Field(..., min_length=2)
    name_local: Optional[str] = None

    room_number: Optional[str] = None
    floor: Optional[int] = None
    room_type: Optional[str] = None

    description: Optional[str] = None
    category: Optional[str] = None


class RoomUpdate(BaseModel):
    building_id: Optional[str] = None

    name_en: Optional[str] = Field(default=None, min_length=2)
    name_local: Optional[str] = None

    room_number: Optional[str] = None
    floor: Optional[int] = None
    room_type: Optional[str] = None

    description: Optional[str] = None
    category: Optional[str] = None

    is_active: Optional[bool] = None


class RoomResponse(BaseModel):
    id: str
    building_id: str

    name_en: str
    name_local: Optional[str] = None

    room_number: Optional[str] = None
    floor: Optional[int] = None
    room_type: Optional[str] = None

    description: Optional[str] = None
    category: Optional[str] = None

    is_active: bool

    created_at: datetime
    updated_at: datetime