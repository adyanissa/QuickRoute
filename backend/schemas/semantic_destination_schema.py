"""
Request/response schemas for "Approved Semantic Analysis -> Automatic
Destinations and Nested-Room Navigation":
  POST /api/maps/{map_id}/semantic-analysis/destinations/preview (read-only)
  POST /api/maps/{map_id}/semantic-analysis/destinations/apply (creates/
  updates Rooms + destination RoutePoints for explicitly accepted items
  only, and only after independent server-side revalidation).

IMPORTANT ARCHITECTURAL FACT discovered by inspecting
schemas/semantic_analysis_schema.py before writing this file: the semantic
analysis JSON contract DELIBERATELY contains NO coordinates, bounding
boxes, polygons, centroids, or door/entrance anchors anywhere
(FORBIDDEN_ROUTING_FIELD_NAMES explicitly rejects x/y/coordinates/polygon/
bounding_box/door_node_id/entrance_route_point_id if the AI ever returns
them — this is the deliberate "Routing-Graph Separation" the schema's own
docstring describes). A semantic item therefore can only ever identify
WHAT a place is (names/type/confidence/containment) — never WHERE it is on
the map image. `placement_source` below reflects this honestly: a
genuinely new destination point can only ever be "manual" (the admin
clicks the correct spot on the map during preview review, or an existing
RoutePoint is reused) — never "door"/"boundary"/"centroid", since none of
that geometry exists anywhere in this codebase's semantic data.
"""

from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field


EntityKind = Literal["place", "facility"]
ProposedAction = Literal["create", "update", "reuse", "skip"]
PlacementSource = Literal["existing_route_point", "manual", "needs_manual_placement"]


class SemanticDestinationPreviewRequest(BaseModel):
    # Restrict the scan to specific approved items only (e.g. the admin
    # just approved a handful more since the last preview) — omitted/empty
    # means "every accepted/corrected place+facility in the map's active
    # publication".
    item_external_ids: Optional[List[str]] = None
    lang: str = "en"


class SemanticDestinationCandidate(BaseModel):
    """One possible nested-parent candidate for an inner item, resolved
    from the semantic item's own inside_place_external_id /
    belongs_to_place_external_id — never from proximity/name similarity
    alone (Section 16 of destination_types-adjacent conventions: never
    guess a relationship the data doesn't explicitly declare)."""

    semantic_item_id: str
    name: str
    entity_kind: EntityKind
    matched_room_id: Optional[str] = None


class SemanticDestinationProposal(BaseModel):
    semantic_item_id: str
    entity_kind: EntityKind
    map_id: str
    floor: Optional[int] = None

    name_en: Optional[str] = None
    name_ar: Optional[str] = None
    name_he: Optional[str] = None
    name_original: Optional[str] = None

    detected_category: Optional[str] = None
    detected_subcategory: Optional[str] = None
    # Only set when detected_category/subcategory exactly matches a
    # canonical constants/destination_types.py value — never fabricated.
    proposed_room_type: Optional[str] = None

    confidence: Optional[float] = None
    needs_review: bool = False

    room_action: ProposedAction = "create"
    route_point_action: ProposedAction = "create"

    matched_room_id: Optional[str] = None
    matched_route_point_id: Optional[str] = None
    match_basis: Optional[str] = None  # semantic_id | direct_link | legacy_name | None

    placement_source: PlacementSource = "needs_manual_placement"
    proposed_x: Optional[float] = None
    proposed_y: Optional[float] = None

    # True whenever this proposal has no trustworthy coordinate yet (no
    # existing linked RoutePoint, and nothing admin-reviewed to reuse) —
    # i.e. whenever placement_source is "needs_manual_placement" AND the
    # item is still actually destined to become a Room (not an
    # excluded/ambiguous "skip"). Distinct from `needs_review` above,
    # which reflects AI confidence, not location trustworthiness. The
    # item is never dropped from the proposals list for this reason —
    # see `warnings` for the human-readable explanation.
    needs_location_review: bool = False

    # Nested-room proposal (Section 3.9/16). None when this item has no
    # declared containment field at all.
    nested_parent_candidate: Optional[SemanticDestinationCandidate] = None
    pass_through_proposed: bool = False

    warnings: List[str] = Field(default_factory=list)
    excluded: bool = False
    exclusion_reason: Optional[str] = None


class SemanticDestinationPreviewSummary(BaseModel):
    scanned: int = 0
    new_rooms_proposed: int = 0
    new_route_points_proposed: int = 0
    existing_linked_found: int = 0
    updates_proposed: int = 0
    nested_relationships_proposed: int = 0
    needs_location_review: int = 0
    rejected_or_invalid: int = 0
    ambiguous_matches: int = 0
    duplicates_prevented: int = 0


class SemanticDestinationPreviewResponse(BaseModel):
    publication_id: Optional[str] = None
    summary: SemanticDestinationPreviewSummary
    proposals: List[SemanticDestinationProposal] = Field(default_factory=list)
    # Section 8 (floor-code defense-in-depth): non-fatal, map-level
    # warnings — e.g. this map's semantic floor code is stale and needs
    # the admin repair action run before apply will accept anything.
    # Preview stays read-only either way; apply is what actually rejects.
    warnings: List[str] = Field(default_factory=list)


class AcceptedDestinationItem(BaseModel):
    semantic_item_id: str = Field(..., min_length=1)
    entity_kind: EntityKind

    # Required only when this item has no existing linked RoutePoint —
    # the admin-reviewed map location. Omitted for a pure "reuse" item.
    x: Optional[float] = None
    y: Optional[float] = None

    # Explicit nested-parent confirmation (Section 10: "Do not enable
    # pass-through without explicit admin confirmation" — this whole
    # object IS that confirmation). None means "not nested".
    parent_semantic_item_id: Optional[str] = None

    # Confirms THIS item itself may be passed through by other users on
    # their way to some other approved inner destination. Independent of
    # parent_semantic_item_id above (that's "I am nested under someone
    # else"; this is "someone else may be nested under me"). Default
    # False, exactly matching RoutePoint.allow_transit_through's default.
    allow_transit_through: bool = False


class SemanticDestinationApplyRequest(BaseModel):
    publication_id: Optional[str] = None
    accepted: List[AcceptedDestinationItem] = Field(default_factory=list)


class SemanticDestinationApplyResult(BaseModel):
    requested: int = 0
    rooms_created: int = 0
    rooms_updated: int = 0
    route_points_created: int = 0
    route_points_updated: int = 0
    reused: int = 0
    nested_relationships_created: int = 0
    pass_through_flags_enabled: int = 0
    skipped: int = 0
    ambiguous: int = 0
    failed: int = 0
    warnings: List[str] = Field(default_factory=list)
    created_room_ids: List[str] = Field(default_factory=list)
    created_route_point_ids: List[str] = Field(default_factory=list)
