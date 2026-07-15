from datetime import datetime
from typing import Dict, Literal, Optional

from pydantic import BaseModel, Field


ProcessingStatus = Literal[
    "not_started",
    "pending",
    "processing",
    "completed",
    "failed",
]

GenerationMethod = Literal[
    "local",
    "openai",
    "hybrid",
]


class MapCreate(BaseModel):
    title: str = Field(..., min_length=2)
    campus: Optional[str] = None
    address: Optional[str] = None
    description: Optional[str] = None

    # Old/current image field - do not remove
    image_url: Optional[str] = None

    # Accurate original map
    source_image_url: Optional[str] = None

    # Clean colorful map for the user
    display_image_url: Optional[str] = None

    scale: float = Field(default=1.0, gt=0)

    # example: {"0": 0.05, "1": 0.03}
    floor_scales: Dict[str, float] = Field(default_factory=dict)


class MapUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=2)
    campus: Optional[str] = None
    address: Optional[str] = None
    description: Optional[str] = None

    # Old/current image field - do not remove
    image_url: Optional[str] = None

    # Accurate original map
    source_image_url: Optional[str] = None

    # Clean colorful map for the user
    display_image_url: Optional[str] = None

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

    # Old/current image field
    image_url: Optional[str] = None

    # Original accurate map
    source_image_url: Optional[str] = None

    # Clean colorful display map
    display_image_url: Optional[str] = None

    # Uploaded file information
    source_filename: Optional[str] = None
    source_content_type: Optional[str] = None

    # Processing information
    processing_status: ProcessingStatus = "not_started"
    processing_progress: int = 0
    processing_error: Optional[str] = None
    generation_method: Optional[GenerationMethod] = None

    # Image dimensions
    source_width: Optional[int] = None
    source_height: Optional[int] = None
    display_width: Optional[int] = None
    display_height: Optional[int] = None

    scale: float
    floor_scales: Dict[str, float]

    is_current: bool

    processed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class MapProcessingResponse(BaseModel):
    id: str
    processing_status: ProcessingStatus
    processing_progress: int
    processing_error: Optional[str] = None
    generation_method: Optional[GenerationMethod] = None
    source_image_url: Optional[str] = None
    display_image_url: Optional[str] = None
    processed_at: Optional[datetime] = None