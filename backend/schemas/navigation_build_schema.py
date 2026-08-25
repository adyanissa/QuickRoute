"""
Response contract for the READ-ONLY automatic navigation-build preview:

  POST /api/maps/{map_id}/navigation-build/preview

PHASE A. There is deliberately no apply endpoint and no apply schema. This
preview creates and modifies nothing — no Room, RoutePoint, RouteEdge,
LocationCode, semantic review or publication record.

Everything geometric in here is in FULL-RESOLUTION source-image pixels,
the same space RoutePoint.x/y and Room.x/y use, so the admin map can draw
it straight over the floor plan with no conversion.

The diagnostics block is deliberately verbose. An automatic geometry
pipeline that reports only its successes is impossible to trust or debug:
the interesting question on a real drawing is always "what did it throw
away, and why".
"""

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


# vector_pdf — selectable text read from the preserved original PDF
# ocr        — tesseract read the raster source image
# unavailable— neither worked; label_source_reason says which and why
LabelSource = Literal["vector_pdf", "ocr", "unavailable"]

RoomBuildStatus = Literal[
    "auto_connectable",             # positioned AND attached to the graph
    "needs_arrival_confirmation",   # geometry could not be established
    "ambiguous_label",              # two or more labels match equally
    "no_label_match",               # nothing on the drawing matches
    "no_safe_graph_connection",     # positioned, but no proven path out
    "already_placed",               # has a real location already
]


class BuildPoint(BaseModel):
    x: float
    y: float


class GraphNodeOut(BaseModel):
    """A PROPOSED hidden transit node. Nothing is persisted in Phase A."""

    index: int
    x: float
    y: float
    kind: str = "junction"


class GraphEdgeOut(BaseModel):
    from_index: int
    to_index: int
    # Straight-line distance between the two endpoints above — never a
    # traced path length. See corridor_graph_service for why that
    # distinction is load-bearing.
    length_px: float
    subdivided: bool = False


class RejectedEdgeOut(BaseModel):
    from_point: List[float] = Field(default_factory=list)
    to_point: List[float] = Field(default_factory=list)
    reason: str


class RegionPolygon(BaseModel):
    """Simplified outline, [[x, y], ...] in source pixels."""

    points: List[List[float]] = Field(default_factory=list)
    decision: str = "interior"        # interior | rejected
    reason: Optional[str] = None


class RegionComponentOut(BaseModel):
    index: int
    area: int
    bbox: List[int] = Field(default_factory=list)
    area_fraction: float = 0.0
    signals: Dict[str, Any] = Field(default_factory=dict)
    decision: str = "rejected"
    reason: Optional[str] = None
    promoted_by: Optional[str] = None


class RoomAttachment(BaseModel):
    """A proposed room-arrival -> transit-graph connection."""

    node_index: Optional[int] = None
    node_x: Optional[float] = None
    node_y: Optional[float] = None
    distance_px: Optional[float] = None
    confidence_tier: Optional[str] = None
    strict_clear_line: bool = False


class RoomBuildProposal(BaseModel):
    semantic_item_id: str
    room_name: Optional[str] = None
    room_number: Optional[str] = None
    matched_room_id: Optional[str] = None

    status: RoomBuildStatus
    message: Optional[str] = None

    matched_label: Optional[str] = None
    label_bbox: Optional[List[float]] = None

    arrival_point: Optional[BuildPoint] = None
    attachment: Optional[RoomAttachment] = None

    semantic_match_confidence: float = 0.0
    geometry_confidence: float = 0.0

    would_create_location_code: bool = False
    diagnostics: Dict[str, Any] = Field(default_factory=dict)


class BuildDiagnostics(BaseModel):
    """Every number the operator needs to judge a run. Nothing hidden."""

    # --- resolutions ---------------------------------------------
    strict_geometry_resolution: Dict[str, int] = Field(default_factory=dict)
    topology_working_resolution: Dict[str, int] = Field(default_factory=dict)
    source_resolution: Dict[str, int] = Field(default_factory=dict)

    # --- measured geometry ---------------------------------------
    wall_stroke_thickness_px: float = 0.0
    topology_closing_kernel_px: int = 0
    gap_seal_backoffs: int = 0

    # --- labels ---------------------------------------------------
    label_source: LabelSource = "unavailable"
    label_source_reason: Optional[str] = None
    label_count: int = 0
    ocr_available: bool = False

    # --- regions --------------------------------------------------
    region_component_count: int = 0
    interior_component_count: int = 0
    rejected_component_count: int = 0
    region_components: List[RegionComponentOut] = Field(default_factory=list)
    page_furniture: List[Dict[str, Any]] = Field(default_factory=list)

    # --- circulation separation -----------------------------------
    # Which enclosed cells were judged shared circulation and which were
    # excluded as room interiors, with the door-degree evidence for each.
    circulation: Dict[str, Any] = Field(default_factory=dict)
    # How much reviewed semantic circulation evidence was actually usable.
    # public_areas carry no coordinates by design, so they can only be
    # located by matching their names to printed labels — which means this
    # is empty on a map with no readable labels, and the geometry falls
    # back to door-adjacency alone.
    semantic_circulation_evidence: Dict[str, Any] = Field(default_factory=dict)

    # --- graph ----------------------------------------------------
    skeleton_node_count_before_simplification: int = 0
    proposed_node_count: int = 0
    proposed_edge_count: int = 0
    subdivided_edge_count: int = 0
    rejected_edge_count: int = 0
    pruned_component_count: int = 0
    pruned_node_count: int = 0

    # --- semantic / rooms -----------------------------------------
    accepted_semantic_room_count: int = 0
    provisional_arrival_count: int = 0
    final_auto_positioned_room_count: int = 0
    final_auto_connected_room_count: int = 0
    rooms_requiring_review: List[Dict[str, Any]] = Field(default_factory=list)

    # --- the provisional pass, reported for auditability ----------
    # The provisional graph exists ONLY to break the chicken-and-egg
    # between "arrival points need a graph" and "the region wants arrival
    # points". It is discarded before the final graph is built; no
    # provisional node id, edge, attachment or connectivity decision
    # reaches the response. These counts are here so the two passes can be
    # compared, never as evidence for anything.
    provisional_node_count: int = 0
    provisional_edge_count: int = 0
    provisional_interior_component_count: int = 0
    region_changed_after_refinement: bool = False
    provisional_graph_discarded: bool = True

    # --- timings (ms) ---------------------------------------------
    timings_ms: Dict[str, int] = Field(default_factory=dict)

    # --- per-stage refusals ---------------------------------------
    stage_refusals: List[Dict[str, str]] = Field(default_factory=list)


class NavigationBuildPreviewRequest(BaseModel):
    item_external_ids: Optional[List[str]] = None
    lang: str = "en"


class NavigationBuildPreviewResponse(BaseModel):
    map_id: str
    publication_id: Optional[str] = None

    # False plus a named reason whenever the pipeline refused. A refusal is
    # a normal, expected outcome, never an error response.
    available: bool = False
    reason: Optional[str] = None
    failed_stage: Optional[str] = None

    region_polygons: List[RegionPolygon] = Field(default_factory=list)
    graph_nodes: List[GraphNodeOut] = Field(default_factory=list)
    graph_edges: List[GraphEdgeOut] = Field(default_factory=list)
    rejected_edges: List[RejectedEdgeOut] = Field(default_factory=list)

    rooms: List[RoomBuildProposal] = Field(default_factory=list)

    # How many LocationCodes an apply WOULD create. Phase A creates none.
    location_codes_would_be_created: int = 0

    diagnostics: BuildDiagnostics = Field(default_factory=BuildDiagnostics)
    warnings: List[str] = Field(default_factory=list)
