from datetime import datetime
from typing import Optional

from beanie import Document
from pydantic import Field


class RoutePoint(Document):
    map_id: str

    name: str
    point_type: Optional[str] = None

    x: float
    y: float

    floor: Optional[int] = None
    building_id: Optional[str] = None
    room_id: Optional[str] = None

    is_accessible: bool = True
    is_active: bool = True

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "route_points"