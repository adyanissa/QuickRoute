from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class BuildingCreate(BaseModel):
    name_en: str = Field(..., min_length=2)
    name_local: Optional[str] = None
    description: Optional[str] = None
    short_tag: Optional[str] = None
    icon_color: Optional[str] = None
    category: Optional[str] = None
    campus: Optional[str] = None


class BuildingUpdate(BaseModel):
    name_en: Optional[str] = Field(default=None, min_length=2)
    name_local: Optional[str] = None
    description: Optional[str] = None
    short_tag: Optional[str] = None
    icon_color: Optional[str] = None
    category: Optional[str] = None
    campus: Optional[str] = None
    is_active: Optional[bool] = None


class BuildingResponse(BaseModel):
    id: str
    name_en: str
    name_local: Optional[str] = None
    description: Optional[str] = None
    short_tag: Optional[str] = None
    icon_color: Optional[str] = None
    category: Optional[str] = None
    campus: Optional[str] = None
    is_active: bool
    created_at: datetime
    updated_at: datetime