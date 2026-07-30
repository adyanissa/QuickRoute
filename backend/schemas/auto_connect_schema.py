"""
Request/response schemas for "Auto Connect Destinations to Corridors" —
POST /api/route-edges/auto-connect-destinations/preview (read-only) and
POST /api/route-edges/auto-connect-destinations/apply (creates ordinary
same-floor walkway RouteEdges only, and only for explicitly accepted
pairs). See services/auto_connect_destinations_service.py for the actual
candidate-selection/validation logic these schemas carry.
"""

from typing import List, Literal, Optional

from pydantic import BaseModel, Field


AutoConnectScope = Literal["map", "map_group"]
AutoConnectConfidence = Literal["high", "medium", "low", "needs_review"]
AutoConnectStatus = Literal["proposed", "already_connected", "no_candidate"]


class AutoConnectPreviewRequest(BaseModel):
    map_id: str = Field(..., min_length=1)

    # Defensive extra filter only — a Map already represents a single
    # floor in this project's normal (post-migration) model; see
    # calculate_edge_distance()'s own docstring in route_edge_routes.py for
    # the two floor models this codebase still supports side by side.
    floor: Optional[int] = None

    max_distance_px: Optional[float] = Field(default=None, gt=0)

    scope: AutoConnectScope = "map"

    # Which language to resolve destination_name/candidate names in
    # (resolve_localized_display_name) — purely a display concern, never
    # affects candidate selection/validation.
    lang: str = "en"


class AutoConnectCandidate(BaseModel):
    point_id: str
    name: str
    point_type: str
    distance_px: float
    distance_meters: Optional[float] = None
    blocked_by_wall: bool = False


class AutoConnectProposal(BaseModel):
    map_id: str
    floor: Optional[int] = None

    destination_point_id: str
    destination_name: str
    destination_point_type: str

    status: AutoConnectStatus
    confidence: Optional[AutoConnectConfidence] = None
    reason: Optional[str] = None

    # True when this destination already has at least one OTHER edge
    # (of any type/validity) that is not itself a valid active walkway
    # connection to a transit point — e.g. a stale Room→Room edge. Shown
    # as a warning; those edges are never touched/removed automatically.
    has_existing_invalid_edges: bool = False

    is_calibrated: bool = False

    # The single default/nearest valid candidate's id — matches
    # candidates[0].point_id when candidates is non-empty. None when
    # status is not "proposed".
    proposed_candidate_id: Optional[str] = None

    candidates: List[AutoConnectCandidate] = Field(default_factory=list)

    # Nested-room navigation (Approved Semantic Analysis -> Automatic
    # Destinations spec, Section 12.B). True only when this proposal's
    # sole candidate is the destination's explicitly approved parent Room
    # (Room.parent_room_id) — never set for an ordinary nearby-hallway/
    # junction proposal. Lets the frontend show "approved nested access"
    # styling instead of an ordinary corridor-candidate list.
    is_nested_access: bool = False


class AutoConnectPreviewSummary(BaseModel):
    scanned: int = 0
    already_connected: int = 0
    proposed: int = 0
    needs_review: int = 0
    no_candidate: int = 0


class AutoConnectPreviewResponse(BaseModel):
    summary: AutoConnectPreviewSummary
    proposals: List[AutoConnectProposal] = Field(default_factory=list)


class AutoConnectAcceptedPair(BaseModel):
    destination_point_id: str = Field(..., min_length=1)
    corridor_point_id: str = Field(..., min_length=1)


class AutoConnectApplyRequest(BaseModel):
    map_id: str = Field(..., min_length=1)
    accepted: List[AutoConnectAcceptedPair] = Field(default_factory=list)


class AutoConnectApplyResult(BaseModel):
    requested: int = 0
    created: int = 0
    skipped_existing: int = 0
    rejected_invalid: int = 0
    failed: int = 0
    created_edge_ids: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
