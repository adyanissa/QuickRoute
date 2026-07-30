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

    # Explicit building selection. Leave unset to auto-create/reuse a
    # building from campus/title (see services/building_service.py).
    building_id: Optional[str] = None
    floor: Optional[int] = None
    floor_label: Optional[str] = None

    # Optional shared multi-floor parent — never set through this plain
    # single-map endpoint's normal usage (routes/map_groups_routes.py sets
    # it directly on the Map document instead), kept here only so
    # MapUpdate/MapCreate stay symmetric with MapResponse.
    map_group_id: Optional[str] = None

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

    building_id: Optional[str] = None
    floor: Optional[int] = None
    floor_label: Optional[str] = None
    map_group_id: Optional[str] = None

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
    is_current_for_floor: Optional[bool] = None


class MapResponse(BaseModel):
    id: str
    title: str
    campus: Optional[str] = None
    address: Optional[str] = None
    description: Optional[str] = None

    building_id: Optional[str] = None
    floor: Optional[int] = None
    floor_label: Optional[str] = None

    # The shared multi-floor parent, and its stable admin-facing code —
    # None/None for every ungrouped single-floor map. `map_group_code` is
    # never stored on the Map document itself (see models/map_model.py);
    # it is resolved from the linked MapGroup at response time by
    # map_to_response()/map_to_response_with_group() in map_routes.py, so
    # there is exactly one place a group's code can live.
    map_group_id: Optional[str] = None
    map_group_code: Optional[str] = None

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
    is_calibrated: bool = False
    calibrated_at: Optional[datetime] = None
    calibration_source: Optional[str] = None

    is_current: bool
    is_current_for_floor: bool = True

    graph_generation_status: Optional[str] = None
    graph_generation_confidence: Optional[float] = None
    graph_generation_note: Optional[str] = None
    graph_generated_at: Optional[datetime] = None

    processed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class MapCalibrateRequest(BaseModel):
    """
    Two-click distance calibration (PHASE 8): the admin clicks two points
    on this map's own image whose real-world distance they know, and
    enters that real distance. meters_per_pixel is computed server-side
    from the actual pixel distance between the two points — never trust a
    client-computed scale directly.
    """

    point_a_x: float
    point_a_y: float
    point_b_x: float
    point_b_y: float
    real_distance_meters: float = Field(..., gt=0)


class CopyCalibrationRequest(BaseModel):
    # The floor map whose scale/is_calibrated should be copied onto this
    # one — an explicit admin action only, never automatic, and only
    # meaningful between two floors that are known to share one
    # architectural scale (e.g. identical floor plans stacked vertically).
    source_map_id: str = Field(..., min_length=1)


class MapCalibrationResponse(MapResponse):
    """
    Additive-only extension of MapResponse used solely by the two
    calibration endpoints (calibrate-scale / copy-calibration). Adds a
    summary of the automatic walkway-edge distance recalculation that runs
    right after a successful calibration save, without changing
    MapResponse itself — every other Map endpoint keeps returning the
    exact same shape it always has.
    """

    # Number of existing walkway RouteEdges (belonging to this Map) whose
    # `distance` was successfully recalculated using the new scale.
    edges_recalculated: int = 0

    # Number of walkway edges that were skipped (e.g. an orphaned/invalid
    # edge referencing a missing or cross-map RoutePoint) — never fails or
    # rolls back the calibration itself.
    edges_recalculation_skipped: int = 0


class OcrSuggestRequest(BaseModel):
    # Original-image pixel coordinates — the same coordinate system
    # RoutePoint.x/y and this map's source image already use.
    x: float
    y: float

    # Optional override of the default crop size around (x, y), in the
    # same original-image pixels. Left unset to use the service's default.
    width: Optional[float] = Field(default=None, gt=0)
    height: Optional[float] = Field(default=None, gt=0)


class OcrSuggestResponse(BaseModel):
    # False when OCR could not run at all (engine missing, no source
    # image, unreadable file) — the caller must fall back to a manually
    # typed name and must not treat `text` as meaningful in that case.
    available: bool

    # Suggested text — always empty when nothing legible was found, even
    # when available is True. Never written anywhere automatically; the
    # admin must confirm or edit it before a Room is saved.
    text: str = ""

    # 0..1 — average per-word OCR confidence, normalized from tesseract's
    # native 0-100 scale.
    confidence: float = 0.0

    # True whenever confidence is below the service's low-confidence
    # threshold (or OCR is unavailable/found nothing) — the frontend must
    # keep the name field editable and must not silently trust the
    # suggestion when this is True.
    low_confidence: bool = True

    # Human-readable explanation when available is False or text is
    # empty (e.g. "OCR engine not installed", "No legible text found").
    reason: Optional[str] = None


class MapProcessingResponse(BaseModel):
    id: str
    processing_status: ProcessingStatus
    processing_progress: int
    processing_error: Optional[str] = None
    generation_method: Optional[GenerationMethod] = None
    source_image_url: Optional[str] = None
    display_image_url: Optional[str] = None
    processed_at: Optional[datetime] = None