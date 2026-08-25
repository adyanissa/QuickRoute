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


class LocationCodeGenerate(BaseModel):
    """
    Auto-generates a unique `code` instead of requiring the admin to type
    one — building_id/map_id are derived from route_point_id, never
    supplied by the caller, so a generated code can never disagree with
    the point it points at.
    """

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

    # Resolved at response time from Map(map_id).map_group_id /
    # RoutePoint(route_point_id).floor — never stored on LocationCode
    # itself, so a code always reflects its point's real, current floor
    # rather than a snapshot that could drift. Both None for a code
    # pointing at an ungrouped single-floor map.
    map_group_id: Optional[str] = None
    floor: Optional[int] = None

    label: Optional[str] = None
    is_active: bool

    created_at: datetime
    updated_at: datetime


class LocationCodeResolveResponse(BaseModel):
    code: str

    building_id: str
    map_id: str
    route_point_id: str

    map_group_id: Optional[str] = None
    floor: Optional[int] = None

    label: Optional[str] = None
