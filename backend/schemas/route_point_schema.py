from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class RoutePointCreate(BaseModel):
    map_id: str = Field(..., min_length=1)

    name: str = Field(..., min_length=2)
    point_type: Optional[str] = None

    x: float
    y: float

    floor: Optional[int] = None
    building_id: Optional[str] = None
    room_id: Optional[str] = None

    is_accessible: bool = True


class RoutePointUpdate(BaseModel):
    map_id: Optional[str] = None

    name: Optional[str] = Field(default=None, min_length=2)
    point_type: Optional[str] = None

    x: Optional[float] = None
    y: Optional[float] = None

    floor: Optional[int] = None
    building_id: Optional[str] = None
    room_id: Optional[str] = None

    is_accessible: Optional[bool] = None
    is_active: Optional[bool] = None


class RoutePointResponse(BaseModel):
    id: str
    map_id: str

    name: str
    point_type: Optional[str] = None

    x: float
    y: float

    floor: Optional[int] = None
    building_id: Optional[str] = None
    room_id: Optional[str] = None

    is_accessible: bool
    is_active: bool

    created_at: datetime
    updated_at: datetime