from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class RouteEdgeCreate(BaseModel):
    map_id: str = Field(..., min_length=1)

    from_point_id: str = Field(..., min_length=1)
    to_point_id: str = Field(..., min_length=1)

    distance: float = Field(..., gt=0)

    is_bidirectional: bool = True
    is_accessible: bool = True

    description: Optional[str] = None


class RouteEdgeUpdate(BaseModel):
    map_id: Optional[str] = None

    from_point_id: Optional[str] = None
    to_point_id: Optional[str] = None

    distance: Optional[float] = Field(default=None, gt=0)

    is_bidirectional: Optional[bool] = None
    is_accessible: Optional[bool] = None
    is_active: Optional[bool] = None

    description: Optional[str] = None


class RouteEdgeResponse(BaseModel):
    id: str
    map_id: str

    from_point_id: str
    to_point_id: str

    distance: float

    is_bidirectional: bool
    is_accessible: bool
    is_active: bool

    description: Optional[str] = None

    created_at: datetime
    updated_at: datetime