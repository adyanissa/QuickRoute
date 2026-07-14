from datetime import datetime
from typing import Dict, Optional

from pydantic import BaseModel, Field


class MapCreate(BaseModel):
    title: str = Field(..., min_length=2)
    campus: Optional[str] = None
    address: Optional[str] = None
    description: Optional[str] = None
    image_url: Optional[str] = None

    scale: float = Field(default=1.0, gt=0)

    # example: {"0": 0.05, "1": 0.03}
    floor_scales: Dict[str, float] = Field(default_factory=dict)


class MapUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=2)
    campus: Optional[str] = None
    address: Optional[str] = None
    description: Optional[str] = None
    image_url: Optional[str] = None

    scale: Optional[float] = Field(default=None, gt=0)

    # example: {"0": 0.05, "1": 0.03}
    floor_scales: Optional[Dict[str, float]] = None

    is_current: Optional[bool] = None


class MapResponse(BaseModel):
    id: str
    title: str
    campus: Optional[str] = None
    address: Optional[str] = None
    description: Optional[str] = None
    image_url: Optional[str] = None

    scale: float
    floor_scales: Dict[str, float]

    is_current: bool
    created_at: datetime
    updated_at: datetime