"""
Request/response schemas for "Auto Connect Destinations to Corridors" —
POST /api/route-edges/auto-connect-destinations/preview (read-only) and
POST /api/route-edges/auto-connect-destinations/apply (creates ordinary
same-floor walkway RouteEdges only, and only for explicitly accepted
pairs). See services/auto_connect_destinations_service.py for the actual
candidate-selection/validation logic these schemas carry.
"""

from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field


AutoConnectScope = Literal["map", "map_group"]
AutoConnectConfidence = Literal["high", "medium", "low", "needs_review"]

# "needs_review" is a distinct STATUS, not just a confidence tier: it means
# the data is nearly right and one admin action fixes it (today: a nested
# child whose approved parent is not usable yet), as opposed to
# "no_candidate", which means the geometry/graph genuinely offered nothing.
AutoConnectStatus = Literal[
    "proposed", "already_connected", "no_candidate", "needs_review"
]

# What a proposal would actually attach to.
#   corridor_node    an existing hallway/junction RoutePoint
#   corridor_edge    a position partway along an existing walkway edge;
#                    applying it splits that edge with a new junction
#   nested_parent    an approved pass-through parent Room's own point
AutoConnectTargetType = Literal["corridor_node", "corridor_edge", "nested_parent"]


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
    # Stable identity for selection in the review UI. Equals point_id for
    # a corridor node or nested parent, and "edge:<edge_id>" for an
    # attachment partway along a corridor edge, which has no point yet.
    candidate_key: str = ""

    # None for a corridor_edge candidate: the junction that will carry the
    # connection does not exist until the admin applies the proposal.
    point_id: Optional[str] = None

    name: str
    point_type: str

    target_type: AutoConnectTargetType = "corridor_node"

    # Set only for target_type "corridor_edge" — the existing walkway edge
    # that would be split.
    corridor_edge_id: Optional[str] = None

    # Candidate's own map coordinates — for a corridor_edge candidate these
    # are the projected attachment point on the edge, not an endpoint.
    x: Optional[float] = None
    y: Optional[float] = None

    # The exact coordinates the connection would attach at. Same as x/y;
    # named separately because apply() consumes these specifically and must
    # not depend on a display field's meaning staying fixed.
    attachment_x: Optional[float] = None
    attachment_y: Optional[float] = None

    distance_px: float
    distance_meters: Optional[float] = None

    blocked_by_wall: bool = False

    # Geometry/graph diagnostics for this specific candidate.
    clear_line: bool = True
    # True when the clear line leaves the destination through its own
    # doorway — a single wall stroke on the destination's side of the line.
    # See _attachment_is_clear in the service for the exact rule.
    doorway_crossing: bool = False
    graph_connected: bool = True

    # ── Door-aware validation ───────────────────────────────────────────
    # True when the legacy 900 px validator rejected this line and the
    # strict full-resolution stage proved the only thing it crosses is a
    # rasterised doorway artefact at the destination's own door.
    doorway_resolved: bool = False

    # The temporary waypoint that proof was carried out through. NOT a new
    # position: the destination's stored x/y are unchanged, and that is
    # where the edge is written from. Set only when doorway_resolved.
    doorway_exit_x: Optional[float] = None
    doorway_exit_y: Optional[float] = None
    doorway_snap_px: Optional[float] = None

    # The measurements behind the decision, so it is auditable from the UI:
    # the caliper of what was crossed, and this drawing's wall stroke.
    doorway_crossing_thickness_px: Optional[float] = None
    wall_stroke_thickness_px: Optional[float] = None

    # From the exit point to the corridor there must be NOTHING at strict
    # resolution — forgiveness stops at the doorway.
    clear_line_after_doorway: Optional[bool] = None
    wall_crossings_after_doorway: Optional[int] = None


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
    # status is not "proposed", and also None when the default candidate is
    # a corridor EDGE attachment, which has no point id yet; use
    # proposed_candidate_key for selection in every case.
    proposed_candidate_id: Optional[str] = None
    proposed_candidate_key: Optional[str] = None

    candidates: List[AutoConnectCandidate] = Field(default_factory=list)

    # Nested-room navigation (Approved Semantic Analysis -> Automatic
    # Destinations spec, Section 12.B). True only when this proposal's
    # sole candidate is the destination's explicitly approved parent Room
    # (Room.parent_room_id) — never set for an ordinary nearby-hallway/
    # junction proposal. Lets the frontend show "approved nested access"
    # styling instead of an ordinary corridor-candidate list.
    is_nested_access: bool = False

    # Scale-aware distance diagnostics (item 8). Always populated when the
    # destination's own coordinates and this scan's hard safety ceiling are
    # known — which is every proposal this service produces.
    destination_x: Optional[float] = None
    destination_y: Optional[float] = None

    # The nearest transit candidate distance found for this destination,
    # even when status is "no_candidate" because it exceeded
    # max_hard_distance_px or was wall-blocked (diagnostics for item 2) —
    # None only when the scan found no same-floor transit point nearby at
    # all to measure against.
    nearest_distance_px: Optional[float] = None

    # This scan's hard safety ceiling for this map (item 7 — scale-aware,
    # derived from the map's canonical image dimensions when known).
    # Candidates beyond this distance are never proposed.
    max_hard_distance_px: Optional[float] = None

    # ── Per-room diagnostics ────────────────────────────────────────────
    # Everything below exists so a failure is diagnosable from the review
    # UI without reading server logs. All optional/defaulted, so any
    # existing consumer that ignores them keeps working.

    target_type: Optional[AutoConnectTargetType] = None

    # What the accepted connection would be:
    #   corridor_node | corridor_edge_split | nested_room_via_parent
    connection_type: Optional[str] = None

    graph_connected: Optional[bool] = None
    clear_line: Optional[bool] = None
    doorway_crossing: Optional[bool] = None

    # How many candidates were found and then discarded, and why. A
    # non-zero blocked count alongside reason "blocked_by_wall" is the
    # difference between "there is no corridor near this room" and "there
    # is one, but a wall is in the way".
    blocked_candidate_count: int = 0
    isolated_candidate_count: int = 0

    # ── Door-aware diagnostics ──────────────────────────────────────────
    # `reason` above keeps the exact vocabulary it has always emitted, so
    # nothing matching on it breaks. `final_reason` is the canonical name
    # for the same outcome and is the ONLY place the two new door-aware
    # outcomes appear:
    #
    #   blocked_by_wall               a wall, and it is not at a doorway
    #   doorway_not_resolved          the obstruction is not provably a door
    #   blocked_after_doorway         past the door, something real is in the way
    #   corridor_component_isolated   the nearby corridor is its own island
    #   no_corridor_candidate         nothing within reach on this floor
    #   nested_parent_required        an approved parent exists but has no point
    #   nested_parent_not_pass_through
    final_reason: Optional[str] = None

    # The destination's own stored coordinates as the search saw them.
    # Echoed back so a diagnosis never depends on the UI's copy.
    origin_x: Optional[float] = None
    origin_y: Optional[float] = None

    nearest_corridor_distance_px: Optional[float] = None
    rejected_by_wall_count: int = 0
    rejected_off_graph_count: int = 0

    # How often the door-aware stage ran, and what it concluded.
    doorway_attempted_count: int = 0
    doorway_resolved_count: int = 0
    # Candidates the legacy 900 px mask rejected purely as a resolution
    # artefact — the strict mask found the line simply clear, no doorway
    # forgiveness involved.
    strict_resolution_rescue_count: int = 0
    # Candidates the legacy 3%-of-samples rule would have ACCEPTED and the
    # strict run-based rule refused — i.e. connections that would have been
    # created straight through a wall. Non-zero means this map was affected
    # by the long-line bypass.
    legacy_bypass_rejected_count: int = 0
    strict_mask_available: Optional[bool] = None

    doorway_resolved: bool = False
    doorway_exit_x: Optional[float] = None
    doorway_exit_y: Optional[float] = None
    doorway_snap_px: Optional[float] = None
    doorway_crossing_thickness_px: Optional[float] = None
    wall_stroke_thickness_px: Optional[float] = None
    clear_line_after_doorway: Optional[bool] = None
    wall_crossings_after_doorway: Optional[int] = None

    # ── Corridor graph shape ────────────────────────────────────────────
    # "corridor_component_isolated" on its own is not actionable. These say
    # whether the stray candidate is one orphan dot or a whole second wing,
    # and how far it sits from the main network — which is the difference
    # between deleting a point and joining two corridors.
    corridor_component_count: Optional[int] = None
    corridor_main_component_size: Optional[int] = None
    corridor_isolated_component_sizes: List[int] = Field(default_factory=list)
    # How many pairs of corridor endpoints were treated as one because they
    # sit on the same physical spot. Reported, never silent.
    corridor_coincident_merges: int = 0
    isolated_candidate_component_size: Optional[int] = None
    isolated_candidate_gap_to_main_px: Optional[float] = None

    # Nested-room diagnostics — populated whenever is_nested_access is
    # True, for the proposed case and both review cases.
    nested_parent_room_id: Optional[str] = None
    nested_parent_room_name: Optional[str] = None
    parent_pass_through: Optional[bool] = None


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

    # Exactly one of corridor_point_id / corridor_edge_id must be set —
    # enforced in apply_auto_connect_destinations, which revalidates every
    # pair from fresh database reads and rejects a pair carrying both or
    # neither. Kept as plain optional fields rather than a discriminated
    # union so an older client that only ever sends corridor_point_id is
    # unaffected.
    corridor_point_id: Optional[str] = Field(default=None, min_length=1)

    # Attach partway along this existing walkway edge. Applying it inserts
    # a junction RoutePoint at (attachment_x, attachment_y), replaces the
    # edge with two corridor edges through that junction, and connects the
    # destination to it.
    corridor_edge_id: Optional[str] = Field(default=None, min_length=1)
    attachment_x: Optional[float] = None
    attachment_y: Optional[float] = None


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

    # Corridor edge-split attachments performed by this apply call: one
    # junction RoutePoint each, plus two replacement corridor edges (the
    # original edge is deactivated, never deleted).
    corridor_junctions_created: int = 0
    created_point_ids: List[str] = Field(default_factory=list)

    # "Every accepted navigable room gets its own QR" — filled in by
    # services/room_location_code_service.ensure_room_location_codes, which
    # apply_auto_connect_destinations calls once the edges above are
    # written. This is the step that actually issues most room QRs, because
    # connecting the arrival point is exactly what makes a room navigable.
    # All default to 0/[] so every existing caller and test that never looks
    # at them keeps working unchanged.
    qr_codes_created: int = 0
    qr_codes_reused: int = 0
    rooms_unplaced: int = 0
    rooms_unconnected: int = 0
    rooms_needing_review: List[Dict[str, str]] = Field(default_factory=list)

    # One entry per refused pair: {destination_point_id, reason}.
    # `rejected_invalid` used to be a bare count with no explanation, so an
    # admin who accepted three proposals and saw "Created 0 · Rejected
    # invalid 3" had nothing to act on. Every refusal now names the check
    # it failed, using the same vocabulary the preview reports.
    rejected_reasons: List[Dict[str, Optional[str]]] = Field(default_factory=list)
