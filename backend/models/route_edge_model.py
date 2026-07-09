from datetime import datetime
from typing import Optional

from beanie import Document
from pydantic import Field


class RouteEdge(Document):
    map_id: str

    from_point_id: str
    to_point_id: str

    # walkway / stairs / elevator
    edge_type: str = "walkway"

    # final calculated distance in meters
    distance: float

    # optional manual distance for stairs/elevator
    distance_override: Optional[float] = None

    is_bidirectional: bool = True
    is_accessible: bool = True
    is_active: bool = True

    description: Optional[str] = None

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "route_edges"