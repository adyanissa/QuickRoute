from datetime import datetime
from typing import Optional

from beanie import Document
from pydantic import Field


class RouteEdge(Document):
    map_id: str

    from_point_id: str
    to_point_id: str

    distance: float

    is_bidirectional: bool = True
    is_accessible: bool = True
    is_active: bool = True

    description: Optional[str] = None

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "route_edges"