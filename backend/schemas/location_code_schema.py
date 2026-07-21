from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class LocationCodeCreate(BaseModel):
    code: str = Field(..., min_length=1, max_length=64)

    building_id: str = Field(..., min_length=1)
    map_id: str = Field(..., min_length=1)
    route_point_id: str = Field(..., min_length=1)

    label: Optional[str] = None
    is_active: bool = True


class LocationCodeUpdate(BaseModel):
    code: Optional[str] = Field(default=None, min_length=1, max_length=64)

    building_id: Optional[str] = None
    map_id: Optional[str] = None
    route_point_id: Optional[str] = None

    label: Optional[str] = None
    is_active: Optional[bool] = None


class LocationCodeResponse(BaseModel):
    id: str
    code: str

    building_id: str
    map_id: str
    route_point_id: str

    label: Optional[str] = None
    is_active: bool

    created_at: datetime
    updated_at: datetime


class LocationCodeResolveResponse(BaseModel):
    code: str

    building_id: str
    map_id: str
    route_point_id: str

    label: Optional[str] = None
