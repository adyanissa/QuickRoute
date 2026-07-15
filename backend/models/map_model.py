from datetime import datetime
from typing import Dict, Literal, Optional

from beanie import Document
from pydantic import Field


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


class Map(Document):
    title: str
    campus: Optional[str] = None
    address: Optional[str] = None
    description: Optional[str] = None

    # Old/current image field - do not remove
    image_url: Optional[str] = None

    # Original accurate map used by Admin
    source_image_url: Optional[str] = None

    # Clean colorful map displayed to the user
    display_image_url: Optional[str] = None

    # Information about the uploaded original file
    source_filename: Optional[str] = None
    source_content_type: Optional[str] = None

    # Image processing status
    processing_status: ProcessingStatus = "not_started"
    processing_progress: int = Field(default=0, ge=0, le=100)
    processing_error: Optional[str] = None

    # How the display map was created
    generation_method: Optional[GenerationMethod] = None

    # Original image dimensions
    source_width: Optional[int] = Field(default=None, gt=0)
    source_height: Optional[int] = Field(default=None, gt=0)

    # Display image dimensions
    display_width: Optional[int] = Field(default=None, gt=0)
    display_height: Optional[int] = Field(default=None, gt=0)

    # Default scale for old/simple maps
    scale: float = Field(default=1.0, gt=0)

    # Scale per floor:
    # example: {"0": 0.05, "1": 0.03}
    floor_scales: Dict[str, float] = Field(default_factory=dict)

    is_current: bool = True

    processed_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "maps"