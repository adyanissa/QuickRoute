from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class MapCreate(BaseModel):
    title: str = Field(..., min_length=2)
    campus: Optional[str] = None
    address: Optional[str] = None
    description: Optional[str] = None
    image_url: Optional[str] = None


class MapUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=2)
    campus: Optional[str] = None
    address: Optional[str] = None
    description: Optional[str] = None
    image_url: Optional[str] = None
    is_current: Optional[bool] = None


class MapResponse(BaseModel):
    id: str
    title: str
    campus: Optional[str] = None
    address: Optional[str] = None
    description: Optional[str] = None
    image_url: Optional[str] = None
    is_current: bool
    created_at: datetime
    updated_at: datetime