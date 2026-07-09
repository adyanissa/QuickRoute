from datetime import datetime
from typing import Optional, Literal

from pydantic import BaseModel, Field


EdgeType = Literal["walkway", "stairs", "elevator"]


class RouteEdgeCreate(BaseModel):
    map_id: str = Field(..., min_length=1)

    from_point_id: str = Field(..., min_length=1)
    to_point_id: str = Field(..., min_length=1)

    # walkway / stairs / elevator
    edge_type: EdgeType = "walkway"

    # Used only when a real transition distance is known,
    # especially for stairs or elevator connections
    distance_override: Optional[float] = Field(
        default=None,
        gt=0
    )

    is_bidirectional: bool = True
    is_accessible: bool = True

    description: Optional[str] = None


class RouteEdgeUpdate(BaseModel):
    map_id: Optional[str] = None

    from_point_id: Optional[str] = None
    to_point_id: Optional[str] = None

    edge_type: Optional[EdgeType] = None

    # Final calculated distance can still be updated if needed
    distance: Optional[float] = Field(
        default=None,
        gt=0
    )

    distance_override: Optional[float] = Field(
        default=None,
        gt=0
    )

    is_bidirectional: Optional[bool] = None
    is_accessible: Optional[bool] = None
    is_active: Optional[bool] = None

    description: Optional[str] = None


class RouteEdgeResponse(BaseModel):
    id: str
    map_id: str

    from_point_id: str
    to_point_id: str

    edge_type: EdgeType

    # Final distance used by routing algorithm
    distance: float

    distance_override: Optional[float] = None

    is_bidirectional: bool
    is_accessible: bool
    is_active: bool

    description: Optional[str] = None

    created_at: datetime
    updated_at: datetime