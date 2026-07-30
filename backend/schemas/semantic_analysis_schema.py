"""
Pydantic models for the exact JSON contract produced by the fixed
`quickroute_semantic_map_import_v2` prompt (see
backend/prompts/quickroute_semantic_map_import_v2.txt — this schema is a
direct, field-by-field translation of that prompt's sections 1-20 and must
be kept in sync with it; the prompt file is the source of truth for the
CONTRACT, this file is the source of truth for VALIDATING it).

These models exist for local validation only (see semantic_analysis_service.
py): the AI's raw JSON response is parsed with json.loads() and then handed
to `SemanticMapImportV2.model_validate(...)`. This also doubles as the "one
source of truth" the task requires for the JSON Schema of the AI provider's
JSON-object response mode (via `.model_json_schema()`).

Every model uses `extra="forbid"` so an AI response containing an unexpected
field (a routing coordinate, an ID-only array element, an invented key) is
rejected by Pydantic itself rather than silently accepted — this is exactly
what the prompt's "Critical Full-Object Rule" and "Routing-Graph Separation"
sections require callers to enforce.

IMPORTANT: none of these models accept x/y/pixel coordinates, route point
IDs, route edge IDs, graph nodes/edges/weights, or Dijkstra data anywhere —
that omission is deliberate and is itself part of the validation (an AI
response that includes any of those fields fails Pydantic validation with
an "extra fields not permitted" error before it ever reaches the database).
"""

from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------------
# Shared sub-objects
# ---------------------------------------------------------------------

Status = Literal["confirmed", "probable", "uncertain"]
ReviewStatusValue = Literal["pending", "accepted", "corrected", "rejected"]
DetectedLanguage = Literal["ar", "he", "en", "mixed", "unknown"]


class Names(StrictModel):
    original: Optional[str] = None
    en: Optional[str] = None
    ar: Optional[str] = None
    he: Optional[str] = None


class FloorNames(StrictModel):
    label_original: Optional[str] = None
    full_original: Optional[str] = None
    en: Optional[str] = None
    ar: Optional[str] = None
    he: Optional[str] = None


class EntityReview(StrictModel):
    status: ReviewStatusValue = "pending"
    notes: Optional[str] = None


class EvidenceSource(StrictModel):
    text: Optional[str] = None
    source_file: Optional[str] = None
    source_page: Optional[int] = None
    source_view_type: Optional[str] = None
    source_region_description: Optional[str] = None


# ---------------------------------------------------------------------
# 1. import_draft
# ---------------------------------------------------------------------


class ImportDraft(StrictModel):
    status: str = "ready_for_review"
    source_type: str = "ai_extraction"
    requires_human_review: bool = True
    can_publish_immediately: bool = False


# ---------------------------------------------------------------------
# 2. source_documents[]
# ---------------------------------------------------------------------


class SourceDocument(StrictModel):
    source_document_id: str
    source_file: Optional[str] = None
    file_type: Optional[str] = None
    total_pages_in_file: Optional[int] = None
    source_page: Optional[int] = None
    page_type: Optional[str] = None
    drawing_title: Optional[str] = None
    drawing_number: Optional[str] = None
    project_number: Optional[str] = None
    site_name_detected: Optional[str] = None
    building_detected: Optional[str] = None
    zone_detected: Optional[str] = None
    floor_detected: Optional[str] = None
    is_complete_plan: Optional[bool] = None
    is_partial_plan: Optional[bool] = None
    is_duplicate_or_enlarged_view: Optional[bool] = None
    included_in_extraction: Optional[bool] = None
    exclusion_reason: Optional[str] = None
    notes: Optional[str] = None


# ---------------------------------------------------------------------
# 3. site (single object)
# ---------------------------------------------------------------------


class Site(StrictModel):
    site_external_id: str
    names: Names = Field(default_factory=Names)
    site_type: Optional[str] = None
    site_type_original: Optional[str] = None
    site_type_normalized: Optional[str] = None
    detected_languages: List[DetectedLanguage] = Field(default_factory=list)
    description: Optional[str] = None
    source_document_ids: List[str] = Field(default_factory=list)
    status: Status = "confirmed"
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    review: EntityReview = Field(default_factory=EntityReview)


# ---------------------------------------------------------------------
# 4. buildings[]
# ---------------------------------------------------------------------


class Building(StrictModel):
    building_external_id: str
    site_external_id: Optional[str] = None
    building_number: Optional[str] = None
    names: Names = Field(default_factory=Names)
    building_type: Optional[str] = None
    building_type_original: Optional[str] = None
    building_type_normalized: Optional[str] = None
    alternative_names: List[str] = Field(default_factory=list)
    location_description: Optional[str] = None
    source_document_ids: List[str] = Field(default_factory=list)
    status: Status = "confirmed"
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    review: EntityReview = Field(default_factory=EntityReview)


# ---------------------------------------------------------------------
# 5. zones[]
# ---------------------------------------------------------------------


class Zone(StrictModel):
    zone_external_id: str
    building_external_id: Optional[str] = None
    zone_number: Optional[str] = None
    names: Names = Field(default_factory=Names)
    zone_type: Optional[str] = None
    zone_type_original: Optional[str] = None
    zone_type_normalized: Optional[str] = None
    serves_floor_external_ids: List[str] = Field(default_factory=list)
    source_document_ids: List[str] = Field(default_factory=list)
    evidence_sources: List[EvidenceSource] = Field(default_factory=list)
    status: Status = "confirmed"
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    review: EntityReview = Field(default_factory=EntityReview)


# ---------------------------------------------------------------------
# 6. floors[]
# ---------------------------------------------------------------------


class FloorAdministratorSettings(StrictModel):
    navigable: Optional[bool] = None
    publicly_accessible: Optional[bool] = None
    destination_selection_enabled: Optional[bool] = None
    restricted_access: Optional[bool] = None
    reason: Optional[str] = None


class FloorAiRecommendation(StrictModel):
    suggested_navigable: Optional[bool] = None
    suggested_public_access: Optional[bool] = None
    suggested_destination_selection: Optional[bool] = None
    suggested_restricted_access: Optional[bool] = None
    reason: Optional[str] = None


class FloorSummary(StrictModel):
    total_places: int = 0
    total_facilities: int = 0
    total_access_points: int = 0
    total_public_areas: int = 0
    main_place_types: List[str] = Field(default_factory=list)
    main_services: List[str] = Field(default_factory=list)
    plain_language_summary: Optional[str] = None


class Floor(StrictModel):
    floor_external_id: str
    building_external_id: Optional[str] = None
    floor_code: Optional[str] = None
    floor_number: Optional[float] = None
    names: FloorNames = Field(default_factory=FloorNames)
    elevation_original: Optional[str] = None
    source_document_ids: List[str] = Field(default_factory=list)
    administrator_settings: FloorAdministratorSettings = Field(
        default_factory=FloorAdministratorSettings
    )
    ai_recommendation: FloorAiRecommendation = Field(
        default_factory=FloorAiRecommendation
    )
    floor_summary: FloorSummary = Field(default_factory=FloorSummary)
    status: Status = "confirmed"
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    review: EntityReview = Field(default_factory=EntityReview)


# ---------------------------------------------------------------------
# 7. places[]
# ---------------------------------------------------------------------


class PlaceAdministratorSettings(StrictModel):
    selectable_destination: Optional[bool] = None
    public_access: Optional[bool] = None
    restricted_access: Optional[bool] = None
    accessible: Optional[bool] = None


class PlaceAiRecommendation(StrictModel):
    suggested_selectable_destination: Optional[bool] = None
    suggested_public_access: Optional[bool] = None
    suggested_restricted_access: Optional[bool] = None
    suggested_accessible: Optional[bool] = None
    reason: Optional[str] = None


class Place(StrictModel):
    place_external_id: str
    building_external_id: Optional[str] = None
    floor_external_id: Optional[str] = None
    zone_external_id: Optional[str] = None

    displayed_number: Optional[str] = None
    normalized_number: Optional[str] = None
    number_type: Optional[str] = None

    room_number: Optional[str] = None
    unit_number: Optional[str] = None
    shop_number: Optional[str] = None
    department_number: Optional[str] = None
    clinic_number: Optional[str] = None
    office_number: Optional[str] = None

    names: Names = Field(default_factory=Names)
    detected_language: Optional[DetectedLanguage] = None
    alternative_readings: List[str] = Field(default_factory=list)

    category: Optional[str] = None
    subcategory: Optional[str] = None
    subcategory_original: Optional[str] = None
    subcategory_normalized: Optional[str] = None

    inside_place_external_id: Optional[str] = None
    belongs_to_place_external_id: Optional[str] = None
    related_place_external_ids: List[str] = Field(default_factory=list)

    administrator_settings: PlaceAdministratorSettings = Field(
        default_factory=PlaceAdministratorSettings
    )
    ai_recommendation: PlaceAiRecommendation = Field(
        default_factory=PlaceAiRecommendation
    )

    source_document_ids: List[str] = Field(default_factory=list)
    evidence_sources: List[EvidenceSource] = Field(default_factory=list)

    status: Status = "confirmed"
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    review: EntityReview = Field(default_factory=EntityReview)


# ---------------------------------------------------------------------
# 8. facilities[]
# ---------------------------------------------------------------------


class FacilityAdministratorSettings(StrictModel):
    selectable_destination: Optional[bool] = None
    public_access: Optional[bool] = None
    accessible: Optional[bool] = None


class FacilityAiRecommendation(StrictModel):
    suggested_selectable_destination: Optional[bool] = None
    suggested_public_access: Optional[bool] = None
    suggested_accessible: Optional[bool] = None
    reason: Optional[str] = None


class Facility(StrictModel):
    facility_external_id: str
    building_external_id: Optional[str] = None
    floor_external_id: Optional[str] = None
    zone_external_id: Optional[str] = None

    displayed_number: Optional[str] = None
    normalized_number: Optional[str] = None
    room_number: Optional[str] = None

    names: Names = Field(default_factory=Names)

    facility_type: Optional[str] = None
    facility_type_original: Optional[str] = None
    facility_type_normalized: Optional[str] = None
    enclosed_room: Optional[bool] = None

    administrator_settings: FacilityAdministratorSettings = Field(
        default_factory=FacilityAdministratorSettings
    )
    ai_recommendation: FacilityAiRecommendation = Field(
        default_factory=FacilityAiRecommendation
    )

    source_document_ids: List[str] = Field(default_factory=list)
    evidence_sources: List[EvidenceSource] = Field(default_factory=list)

    status: Status = "confirmed"
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    review: EntityReview = Field(default_factory=EntityReview)


# ---------------------------------------------------------------------
# 9. access_points[]
# ---------------------------------------------------------------------


class RampInfo(StrictModel):
    ramp_detected: bool = False
    slope_percent: Optional[float] = None
    ramp_purpose: Optional[str] = None
    pedestrian_accessible: Optional[bool] = None
    vehicle_accessible: Optional[bool] = None


class AccessPointAdministratorSettings(StrictModel):
    public_access: Optional[bool] = None
    accessible: Optional[bool] = None
    enabled_for_routing: Optional[bool] = None


class AccessPointAiRecommendation(StrictModel):
    suggested_public_access: Optional[bool] = None
    suggested_accessible: Optional[bool] = None
    suggested_enabled_for_routing: Optional[bool] = None
    reason: Optional[str] = None


class AccessPoint(StrictModel):
    access_external_id: str
    building_external_id: Optional[str] = None
    floor_external_id: Optional[str] = None
    zone_external_id: Optional[str] = None

    displayed_number: Optional[str] = None
    names: Names = Field(default_factory=Names)

    access_type: Optional[str] = None
    access_type_original: Optional[str] = None
    access_type_normalized: Optional[str] = None

    serves_building_external_id: Optional[str] = None
    serves_floor_external_id: Optional[str] = None
    serves_place_external_id: Optional[str] = None

    ramp: RampInfo = Field(default_factory=RampInfo)

    administrator_settings: AccessPointAdministratorSettings = Field(
        default_factory=AccessPointAdministratorSettings
    )
    ai_recommendation: AccessPointAiRecommendation = Field(
        default_factory=AccessPointAiRecommendation
    )

    source_document_ids: List[str] = Field(default_factory=list)
    evidence_sources: List[EvidenceSource] = Field(default_factory=list)

    status: Status = "confirmed"
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    review: EntityReview = Field(default_factory=EntityReview)


# ---------------------------------------------------------------------
# 10. public_areas[]
# ---------------------------------------------------------------------


class PublicArea(StrictModel):
    area_external_id: str
    building_external_id: Optional[str] = None
    floor_external_id: Optional[str] = None
    zone_external_id: Optional[str] = None

    displayed_number: Optional[str] = None
    names: Names = Field(default_factory=Names)

    area_type: Optional[str] = None
    area_type_original: Optional[str] = None
    area_type_normalized: Optional[str] = None

    connected_place_external_ids: List[str] = Field(default_factory=list)
    connected_area_external_ids: List[str] = Field(default_factory=list)

    source_document_ids: List[str] = Field(default_factory=list)
    evidence_sources: List[EvidenceSource] = Field(default_factory=list)

    status: Status = "confirmed"
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    review: EntityReview = Field(default_factory=EntityReview)


# ---------------------------------------------------------------------
# 11. vertical_connections[]
# ---------------------------------------------------------------------


class FloorAppearance(StrictModel):
    floor_external_id: str
    source_document_ids: List[str] = Field(default_factory=list)
    evidence_sources: List[EvidenceSource] = Field(default_factory=list)
    status: Status = "confirmed"
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class VerticalConnectionAdministratorSettings(StrictModel):
    accessible: Optional[bool] = None
    enabled_for_routing: Optional[bool] = None


class VerticalConnectionAiRecommendation(StrictModel):
    suggested_accessible: Optional[bool] = None
    suggested_enabled_for_routing: Optional[bool] = None
    reason: Optional[str] = None


class VerticalConnection(StrictModel):
    connection_external_id: str
    building_external_id: Optional[str] = None

    displayed_number: Optional[str] = None
    normalized_number: Optional[str] = None

    names: Names = Field(default_factory=Names)

    connection_type: Optional[str] = None
    connection_type_original: Optional[str] = None
    connection_type_normalized: Optional[str] = None

    serves_floor_external_ids: List[str] = Field(default_factory=list)
    floor_appearances: List[FloorAppearance] = Field(default_factory=list)

    administrator_settings: VerticalConnectionAdministratorSettings = Field(
        default_factory=VerticalConnectionAdministratorSettings
    )
    ai_recommendation: VerticalConnectionAiRecommendation = Field(
        default_factory=VerticalConnectionAiRecommendation
    )

    status: Status = "confirmed"
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    review: EntityReview = Field(default_factory=EntityReview)


# ---------------------------------------------------------------------
# 12. outdoor_areas[]
# ---------------------------------------------------------------------


class OutdoorAreaAdministratorSettings(StrictModel):
    selectable_destination: Optional[bool] = None
    public_access: Optional[bool] = None
    accessible: Optional[bool] = None


class OutdoorAreaAiRecommendation(StrictModel):
    suggested_selectable_destination: Optional[bool] = None
    suggested_public_access: Optional[bool] = None
    suggested_accessible: Optional[bool] = None
    reason: Optional[str] = None


class OutdoorArea(StrictModel):
    outdoor_external_id: str
    building_external_id: Optional[str] = None
    floor_external_id: Optional[str] = None

    belongs_to_place_external_id: Optional[str] = None
    related_place_external_ids: List[str] = Field(default_factory=list)

    displayed_number: Optional[str] = None
    names: Names = Field(default_factory=Names)

    outdoor_type: Optional[str] = None
    outdoor_type_original: Optional[str] = None
    outdoor_type_normalized: Optional[str] = None

    administrator_settings: OutdoorAreaAdministratorSettings = Field(
        default_factory=OutdoorAreaAdministratorSettings
    )
    ai_recommendation: OutdoorAreaAiRecommendation = Field(
        default_factory=OutdoorAreaAiRecommendation
    )

    source_document_ids: List[str] = Field(default_factory=list)
    evidence_sources: List[EvidenceSource] = Field(default_factory=list)

    status: Status = "confirmed"
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    review: EntityReview = Field(default_factory=EntityReview)


# ---------------------------------------------------------------------
# 13. parking_areas[]
# ---------------------------------------------------------------------


class ParkingArea(StrictModel):
    parking_external_id: str
    building_external_id: Optional[str] = None
    floor_external_id: Optional[str] = None
    floor_code: Optional[str] = None

    displayed_number: Optional[str] = None
    names: Names = Field(default_factory=Names)

    parking_type: Optional[str] = None
    parking_type_original: Optional[str] = None
    parking_type_normalized: Optional[str] = None

    entrance_access_external_ids: List[str] = Field(default_factory=list)
    exit_access_external_ids: List[str] = Field(default_factory=list)

    accessible_parking_detected: Optional[bool] = None

    source_document_ids: List[str] = Field(default_factory=list)
    evidence_sources: List[EvidenceSource] = Field(default_factory=list)

    status: Status = "confirmed"
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    review: EntityReview = Field(default_factory=EntityReview)


# ---------------------------------------------------------------------
# 14. parking_spaces[]
# ---------------------------------------------------------------------


class ParkingSpaceAdministratorSettings(StrictModel):
    selectable_destination: Optional[bool] = None
    accessible: Optional[bool] = None


class ParkingSpace(StrictModel):
    parking_space_external_id: str
    parking_external_id: Optional[str] = None
    building_external_id: Optional[str] = None
    floor_external_id: Optional[str] = None

    displayed_number: Optional[str] = None
    parking_space_type: Optional[str] = None

    administrator_settings: ParkingSpaceAdministratorSettings = Field(
        default_factory=ParkingSpaceAdministratorSettings
    )

    source_document_ids: List[str] = Field(default_factory=list)
    evidence_sources: List[EvidenceSource] = Field(default_factory=list)

    status: Status = "confirmed"
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    review: EntityReview = Field(default_factory=EntityReview)


# ---------------------------------------------------------------------
# 15. cross_building_connections[]
# ---------------------------------------------------------------------


class CrossBuildingAdministratorSettings(StrictModel):
    public_access: Optional[bool] = None
    accessible: Optional[bool] = None
    enabled_for_routing: Optional[bool] = None


class CrossBuildingAiRecommendation(StrictModel):
    suggested_public_access: Optional[bool] = None
    suggested_accessible: Optional[bool] = None
    suggested_enabled_for_routing: Optional[bool] = None
    reason: Optional[str] = None


class CrossBuildingConnection(StrictModel):
    connection_external_id: str
    names: Names = Field(default_factory=Names)

    connection_type: Optional[str] = None
    connection_type_original: Optional[str] = None
    connection_type_normalized: Optional[str] = None

    from_building_external_id: Optional[str] = None
    from_floor_external_id: Optional[str] = None
    from_place_external_id: Optional[str] = None

    to_building_external_id: Optional[str] = None
    to_floor_external_id: Optional[str] = None
    to_place_external_id: Optional[str] = None

    administrator_settings: CrossBuildingAdministratorSettings = Field(
        default_factory=CrossBuildingAdministratorSettings
    )
    ai_recommendation: CrossBuildingAiRecommendation = Field(
        default_factory=CrossBuildingAiRecommendation
    )

    source_document_ids: List[str] = Field(default_factory=list)
    evidence_sources: List[EvidenceSource] = Field(default_factory=list)

    status: Status = "confirmed"
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    review: EntityReview = Field(default_factory=EntityReview)


# ---------------------------------------------------------------------
# 16. review_items[]
# ---------------------------------------------------------------------


class ReviewItemReview(StrictModel):
    status: ReviewStatusValue = "pending"
    selected_resolution: Optional[str] = None
    corrected_value: Optional[str] = None
    notes: Optional[str] = None


class ReviewItem(StrictModel):
    review_item_external_id: str
    item_type: Optional[str] = None
    related_entity_external_ids: List[str] = Field(default_factory=list)

    visible_text: Optional[str] = None
    displayed_number: Optional[str] = None

    possible_readings: List[str] = Field(default_factory=list)
    possible_count: List[int] = Field(default_factory=list)

    reason: Optional[str] = None
    evidence_sources: List[EvidenceSource] = Field(default_factory=list)

    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    blocks_publication: bool = True

    review: ReviewItemReview = Field(default_factory=ReviewItemReview)


# ---------------------------------------------------------------------
# 17. unreadable_areas[]
# ---------------------------------------------------------------------


class UnreadableArea(StrictModel):
    source_file: Optional[str] = None
    source_page: Optional[int] = None
    source_region_description: Optional[str] = None
    description: Optional[str] = None
    reason: Optional[str] = None


# ---------------------------------------------------------------------
# 18. summary
# ---------------------------------------------------------------------


class Summary(StrictModel):
    total_source_files: int = 0
    total_pdf_pages: int = 0
    total_native_images: int = 0

    total_buildings: int = 0
    total_zones: int = 0
    total_floors: int = 0

    total_places: int = 0
    total_facilities: int = 0
    total_access_points: int = 0
    total_public_areas: int = 0

    total_physical_elevators: int = 0
    total_elevator_floor_appearances: int = 0

    total_physical_stairs: int = 0
    total_stair_floor_appearances: int = 0

    total_physical_escalators: int = 0
    total_escalator_floor_appearances: int = 0

    total_physical_ramps: int = 0
    total_ramp_floor_appearances: int = 0

    total_outdoor_areas: int = 0
    total_parking_areas: int = 0
    total_parking_spaces: int = 0
    total_accessible_parking_spaces: int = 0

    main_buildings: List[str] = Field(default_factory=list)
    main_place_types: List[str] = Field(default_factory=list)
    main_services: List[str] = Field(default_factory=list)

    plain_language_summary: Optional[str] = None


# ---------------------------------------------------------------------
# 19. validation
# ---------------------------------------------------------------------


class Validation(StrictModel):
    all_files_analyzed: bool = False
    all_pdf_pages_analyzed: bool = False
    visual_inspection_completed: bool = False
    page_classification_completed: bool = False

    building_assignments_checked: bool = False
    building_assignments_verified: bool = False

    floor_assignments_checked: bool = False
    floor_assignments_verified: bool = False

    name_number_pairings_checked: bool = False
    name_number_pairings_verified: bool = False

    all_visible_labels_checked: bool = False
    all_visible_labels_successfully_verified: bool = False

    all_visible_room_numbers_checked: bool = False
    all_visible_room_numbers_successfully_verified: bool = False

    all_visible_unit_numbers_checked: bool = False
    all_visible_unit_numbers_successfully_verified: bool = False

    all_visible_shop_numbers_checked: bool = False
    all_visible_shop_numbers_successfully_verified: bool = False

    drawing_references_excluded: bool = False
    dimensions_excluded: bool = False
    construction_codes_excluded: bool = False

    duplicate_floors_checked: bool = False
    duplicate_places_checked: bool = False
    duplicate_external_ids_checked: bool = False

    vertical_connections_reviewed_for_duplicates: bool = False

    complete_object_arrays_verified: bool = False
    confirmed_entities_have_visible_evidence: bool = False
    unreadable_text_was_not_guessed: bool = False

    all_external_id_references_valid: bool = False
    administrator_policy_fields_left_unconfirmed: bool = False

    summary_totals_recalculated: bool = False
    summary_totals_verified: bool = False

    # NOTE: these two are themselves required VALIDATION FLAGS the model
    # must report (i.e. "did the response avoid returning routing data" —
    # true/false describing an absence), not a request for actual routing
    # data. Rejecting a response merely for setting these to their correct
    # (false-meaning-clean) values would be rejecting the exact field the
    # prompt requires — see semantic_analysis_service.py's local validation
    # pass, which checks these are BOOLEANS and that no *other* field in
    # the whole document contains real coordinates/graph data, but never
    # rejects the document just because these flags are present.
    contains_routing_coordinates: bool = False
    contains_routing_graph_data: bool = False

    ready_for_admin_review: bool = False
    ready_for_publish: bool = False

    errors: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


# ---------------------------------------------------------------------
# Top-level contract
# ---------------------------------------------------------------------


class SemanticMapImportV2(StrictModel):
    schema_version: Literal["quickroute_semantic_map_import_v2"]
    import_draft: ImportDraft
    source_documents: List[SourceDocument] = Field(default_factory=list)
    site: Site
    buildings: List[Building] = Field(default_factory=list)
    zones: List[Zone] = Field(default_factory=list)
    floors: List[Floor] = Field(default_factory=list)
    places: List[Place] = Field(default_factory=list)
    facilities: List[Facility] = Field(default_factory=list)
    access_points: List[AccessPoint] = Field(default_factory=list)
    public_areas: List[PublicArea] = Field(default_factory=list)
    vertical_connections: List[VerticalConnection] = Field(
        default_factory=list
    )
    outdoor_areas: List[OutdoorArea] = Field(default_factory=list)
    parking_areas: List[ParkingArea] = Field(default_factory=list)
    parking_spaces: List[ParkingSpace] = Field(default_factory=list)
    cross_building_connections: List[CrossBuildingConnection] = Field(
        default_factory=list
    )
    review_items: List[ReviewItem] = Field(default_factory=list)
    unreadable_areas: List[UnreadableArea] = Field(default_factory=list)
    summary: Summary
    validation: Validation


# Fields that, if ever present anywhere in a raw AI response dict (checked
# before Pydantic parsing, on every dict/list node, not just top-level),
# indicate the model returned forbidden routing-graph data. Pydantic's
# extra="forbid" already rejects genuinely unexpected keys, but this list
# is used by semantic_analysis_service.py for a fast, explicit,
# human-readable pre-check so a rejection can say exactly which forbidden
# field was found rather than a generic "extra fields not permitted".
FORBIDDEN_ROUTING_FIELD_NAMES = {
    "x",
    "y",
    "pixel_x",
    "pixel_y",
    "coordinates",
    "coordinate",
    "polygon",
    "bounding_box",
    "route_point_id",
    "route_edge_id",
    "route_points",
    "route_edges",
    "route_nodes",
    "route_weight",
    "graph_nodes",
    "graph_edges",
    "graph_weight",
    "navigation_graph_draft",
    "dijkstra",
    "entrance_route_point_id",
    "door_node_id",
    "transition_node_id",
    "calculated_distance",
    "distance_meters",
    "svg_viewbox",
}
