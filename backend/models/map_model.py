from datetime import datetime
from typing import Dict, Optional

from beanie import Document
from pydantic import Field


class Map(Document):
    title: str
    campus: Optional[str] = None
    address: Optional[str] = None
    description: Optional[str] = None
    image_url: Optional[str] = None

    # Default scale for old/simple maps
    scale: float = 1.0

    # Scale per floor:
    # example: {"0": 0.05, "1": 0.03}
    floor_scales: Dict[str, float] = Field(default_factory=dict)

    is_current: bool = True

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "maps"