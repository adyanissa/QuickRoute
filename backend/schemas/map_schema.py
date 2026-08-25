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


class GeneratedGraphNodePreview(BaseModel):
    x: float
    y: float
    kind: str  # "endpoint" | "junction"


class GeneratedGraphEdgePreview(BaseModel):
    from_index: int
    to_index: int
    pixel_length: float


class GraphGenerationPreviewResponse(BaseModel):
    """
    "Generate Route Graph" preview (navigation-data cleanup task, Section
    1.3): read-only — this endpoint NEVER writes a RoutePoint or RouteEdge.
    It re-runs the exact same extraction the apply step will use, so what
    the admin reviews here is exactly what would be created, with nothing
    silently different between preview and apply.
    """

    map_id: str
    nodes: list[GeneratedGraphNodePreview] = Field(default_factory=list)
    edges: list[GeneratedGraphEdgePreview] = Field(default_factory=list)
    confidence: float = 0.0
    walkable_fraction: float = 0.0
    component_count: int = 0
    note: str = ""
    # False whenever confidence is below the service's own
    # MIN_CONFIDENCE_TO_APPLY threshold — the frontend must clearly warn
    # the admin and should discourage confirming a low-confidence
    # proposal, never silently allow it through as if it were normal.
    meets_confidence_threshold: bool = False


class GraphGenerationApplyRequest(BaseModel):
    # Explicit admin confirmation (Section 1.3, step 7): apply must never
    # write anything unless the admin has reviewed the preview and
    # affirmatively confirmed it. Defaults to False on purpose so an
    # accidental/legacy call with no body never silently writes.
    confirm: bool = False


class GraphGenerationApplyResponse(MapResponse):
    graph_applied: bool = False
    graph_points_created: int = 0
    graph_edges_created: int = 0
    graph_points_cleared: int = 0
    graph_edges_cleared: int = 0


class GeneratedGraphCleanupPreviewResponse(BaseModel):
    """
    "Preview Generated Graph Cleanup" (Section 1.6): scoped to one map,
    read-only, identifies only records that carry proof of being
    auto-generated (RoutePoint.is_auto_generated / RouteEdge.
    is_auto_generated). Never includes manual, semantic-destination, or
    vertical-connector points. Records that look legacy-generated (e.g. an
    "Auto Point N" name) but carry no provenance flag are reported
    separately as unknown_legacy_point_count and are NEVER eligible for
    deletion by this workflow.
    """

    map_id: str
    map_name: Optional[str] = None
    floor: Optional[int] = None
    generated_point_count: int = 0
    generated_edge_count: int = 0
    # RouteEdges that reference a generated point but are not themselves
    # flagged is_auto_generated (e.g. a manual edge an admin drew to a
    # generated point) — these would be deleted as a side-effect of
    # deleting their generated endpoint, so they must be disclosed before
    # confirmation, not silently dropped.
    dependent_manual_edge_count: int = 0
    # Navigation-data-problem task (Part 3A): the preview must show the
    # FULL picture, not just what would be deleted — manual/edge counts so
    # the admin can see exactly what will be LEFT UNTOUCHED, never just
    # what will be removed.
    manual_point_count: int = 0
    manual_edge_count: int = 0
    semantic_destination_point_count: int = 0
    vertical_connector_point_count: int = 0
    rooms_linked_to_generated_points: int = 0
    vertical_connectors_linked_to_generated_points: int = 0
    unknown_legacy_point_count: int = 0
    unknown_legacy_note: Optional[str] = None
    generated_point_ids: list[str] = Field(default_factory=list)
    generated_edge_ids: list[str] = Field(default_factory=list)


class GeneratedGraphCleanupApplyRequest(BaseModel):
    confirm: bool = False


class GeneratedGraphCleanupApplyResponse(BaseModel):
    map_id: str
    applied: bool = False
    points_deleted: int = 0
    edges_deleted: int = 0


# ---------------------------------------------------------
# Navigation-data-problem task, Part 3B — Full Navigation Reset for ONE
# explicitly selected Map. Deliberately separate request/response shapes
# from the generated-only cleanup pair above — this is a stronger,
# distinct destructive action (deletes EVERY RoutePoint/RouteEdge on the
# map, not just proven-generated ones) and must never be reachable by
# accidentally reusing the generated-only cleanup's "confirm: true" body.
# ---------------------------------------------------------

class PointSourceBreakdown(BaseModel):
    manual: int = 0
    generated: int = 0
    semantic_destination: int = 0
    vertical_connector: int = 0
    unknown_legacy: int = 0


class FullMapResetPreviewResponse(BaseModel):
    found: bool = True
    map_id: str
    map_name: Optional[str] = None
    floor: Optional[int] = None
    total_point_count: int = 0
    total_edge_count: int = 0
    point_source_breakdown: PointSourceBreakdown = Field(default_factory=PointSourceBreakdown)
    rooms_linked_count: int = 0
    room_ids_linked: list[str] = Field(default_factory=list)
    vertical_connectors_linked_count: int = 0
    vertical_connector_codes_linked: list[str] = Field(default_factory=list)
    location_code_count: int = 0
    location_codes_linked: list[str] = Field(default_factory=list)
    point_ids: list[str] = Field(default_factory=list)
    edge_ids: list[str] = Field(default_factory=list)
    warning: Optional[str] = None


class FullMapResetApplyRequest(BaseModel):
    # Both the exact map_id (already in the URL path) AND this body must
    # agree — a defense-in-depth check against a stale/mismatched client
    # request ever hitting the wrong map (Part 3B: "Require exact selected
    # Map ID").
    map_id: str
    confirm: bool = False
    # Must equal either the Map's own exact title, or the fixed phrase
    # "RESET NAVIGATION DATA" — checked in the route, not here, since it
    # needs the live Map document to compare against.
    confirmation_text: str = ""


class FullMapResetApplyResponse(BaseModel):
    found: bool = True
    map_id: str
    map_name: Optional[str] = None
    applied: bool = False
    points_deleted: int = 0
    edges_deleted: int = 0
    point_ids_deleted: list[str] = Field(default_factory=list)
    edge_ids_deleted: list[str] = Field(default_factory=list)
    point_source_breakdown_deleted: PointSourceBreakdown = Field(default_factory=PointSourceBreakdown)
    rooms_unlinked_count: int = 0
    room_ids_unlinked: list[str] = Field(default_factory=list)
    location_codes_deactivated_count: int = 0
    location_codes_deactivated: list[str] = Field(default_factory=list)
    vertical_connectors_affected_count: int = 0
    vertical_connector_codes_affected: list[str] = Field(default_factory=list)


# ---------------------------------------------------------
# Part 4 — multi-Map overview + multi-Map cleanup (Super Admin only).
# ---------------------------------------------------------

class MapNavigationOverviewItem(BaseModel):
    map_id: str
    map_name: Optional[str] = None
    building_id: Optional[str] = None
    building_name: Optional[str] = None
    map_group_id: Optional[str] = None
    floor: Optional[int] = None
    total_point_count: int = 0
    generated_point_count: int = 0
    manual_point_count: int = 0
    semantic_destination_point_count: int = 0
    vertical_connector_point_count: int = 0
    unknown_legacy_point_count: int = 0
    total_edge_count: int = 0


class MapsNavigationOverviewResponse(BaseModel):
    maps: list[MapNavigationOverviewItem] = Field(default_factory=list)


class MultiMapCleanupRequest(BaseModel):
    map_ids: list[str] = Field(default_factory=list)


class MultiMapGeneratedCleanupPreviewResponse(BaseModel):
    requested_map_ids: list[str] = Field(default_factory=list)
    valid_map_ids: list[str] = Field(default_factory=list)
    skipped_map_ids: list[str] = Field(default_factory=list)
    per_map: list[GeneratedGraphCleanupPreviewResponse] = Field(default_factory=list)
    total_generated_point_count: int = 0
    total_generated_edge_count: int = 0


class MultiMapGeneratedCleanupApplyResponse(BaseModel):
    requested_map_ids: list[str] = Field(default_factory=list)
    applied_map_ids: list[str] = Field(default_factory=list)
    skipped_map_ids: list[str] = Field(default_factory=list)
    per_map: list[GeneratedGraphCleanupApplyResponse] = Field(default_factory=list)
    total_points_deleted: int = 0
    total_edges_deleted: int = 0


class MultiMapFullResetPreviewResponse(BaseModel):
    requested_map_ids: list[str] = Field(default_factory=list)
    valid_map_ids: list[str] = Field(default_factory=list)
    skipped_map_ids: list[str] = Field(default_factory=list)
    per_map: list[FullMapResetPreviewResponse] = Field(default_factory=list)
    total_point_count: int = 0
    total_edge_count: int = 0


class MultiMapFullResetApplyRequest(BaseModel):
    map_ids: list[str] = Field(default_factory=list)
    confirm: bool = False
    # Must exactly equal "RESET SELECTED NAVIGATION DATA" (Part 4's
    # required strong confirmation phrase for a multi-Map full reset).
    confirmation_phrase: str = ""


class MultiMapFullResetApplyResponse(BaseModel):
    requested_map_ids: list[str] = Field(default_factory=list)
    applied_map_ids: list[str] = Field(default_factory=list)
    skipped_map_ids: list[str] = Field(default_factory=list)
    per_map: list[FullMapResetApplyResponse] = Field(default_factory=list)
    total_points_deleted: int = 0
    total_edges_deleted: int = 0