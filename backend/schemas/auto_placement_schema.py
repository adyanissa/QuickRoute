"""
Response schemas for the READ-ONLY geometry preview:
  POST /api/maps/{map_id}/semantic-analysis/destinations/auto-place/preview

WHAT THIS FEATURE IS
--------------------
It answers one question per accepted semantic room: "is there a position
on this map that the drawing itself justifies, and that provably reaches
the existing corridor graph?" When the answer is yes it hands that
position to the EXISTING placement flow, exactly as if an admin had
clicked there. When the answer is anything else it says so and the admin
clicks. There is no third outcome.

WHAT THIS FEATURE IS NOT
------------------------
It is NOT door detection, and nothing in it may be described as such.
QuickRoute has no door, opening, threshold or polygon data of any kind,
and this feature does not create any. It never infers a room's shape, its
boundary, its entrance, or any routing topology. The only geometry it
consumes is:

  * the bounding box of a text label PRINTED on the map, and
  * the wall mask the graph generator already builds from the same image.

The only geometry it produces is a single (x, y) point, and only when a
straight line from that point to an existing corridor RoutePoint passes
the same wall check every manual connection already passes.

THE BOUNDED NUDGE
-----------------
A room's label is usually printed inside the room, which is where the
arrival point belongs — but a label's centre can land on the printed text
itself, on a wall, or in a corner with no line of sight to the corridor.
So the search tries a small, fixed set of positions near the matched
label's box, in a fixed order, and stops at the first one that passes
every check. It never wanders: the budget is derived from the label's own
size and hard-capped, so the search cannot walk across the floor plan
hunting for a position that happens to work.

Every accepted placement records the full evidence for that decision (see
AutoPlacementDiagnostics) so an admin can see exactly why the system chose
that point and reject it if the drawing says otherwise.
"""

from typing import List, Literal, Optional

from pydantic import BaseModel, Field

from schemas.semantic_destination_schema import PlacementSource


# auto_connectable            — a safe position was found; hand it to apply
# needs_arrival_confirmation  — geometry could not be established safely;
#                               the admin places this one by hand. This is
#                               the catch-all: no wall mask, no source
#                               image, nothing to check against.
# ambiguous_label             — two or more labels match this room equally
# no_label_match              — no printed label matches this room
# no_safe_graph_connection    — the label was found, but no position near
#                               it has a clear line to any corridor point
AutoPlacementStatus = Literal[
    "auto_connectable",
    "needs_arrival_confirmation",
    "ambiguous_label",
    "no_label_match",
    "no_safe_graph_connection",
]


class MatchedGraphElement(BaseModel):
    """The existing corridor RoutePoint the suggested position reaches.
    Always an existing point — this feature never proposes a new one."""

    route_point_id: str
    point_type: Optional[str] = None
    name: Optional[str] = None
    x: float
    y: float
    distance_px: float
    confidence_tier: Optional[str] = None  # high | medium | low


class AutoPlacementDiagnostics(BaseModel):
    """
    The complete evidence trail for one decision — recorded for refusals
    as well as placements, because "why did it NOT place this one" is the
    question an admin actually asks.
    """

    # --- what the drawing says -------------------------------------
    matched_label: Optional[str] = None
    label_source: Optional[str] = None       # vector_pdf | ocr
    label_bbox: Optional[List[float]] = None  # [x0, y0, x1, y1]
    label_center: Optional[List[float]] = None  # [x, y]
    label_ocr_confidence: Optional[float] = None

    # --- how the name was matched to it ----------------------------
    matching_rule: Optional[str] = None
    matched_name: Optional[str] = None
    matched_language: Optional[str] = None
    tied_label_texts: List[str] = Field(default_factory=list)

    # --- the nudge -------------------------------------------------
    # Where the search started (always the label box centre), where it
    # ended, and how far and in which direction it moved. A zero nudge
    # distance means the label centre itself passed every check.
    anchor_x: Optional[float] = None
    anchor_y: Optional[float] = None
    nudge_distance_px: Optional[float] = None
    nudge_direction_deg: Optional[float] = None
    nudge_budget_px: Optional[float] = None
    nudge_rule: Optional[str] = None  # which probe position was accepted

    # --- the safety checks -----------------------------------------
    wall_mask_available: bool = False
    candidate_on_wall: Optional[bool] = None
    clear_line_passed: Optional[bool] = None
    candidates_considered: int = 0
    positions_probed: int = 0
    rejections: List[str] = Field(default_factory=list)


class AutoPlacementProposal(BaseModel):
    semantic_item_id: str
    map_id: str
    floor: Optional[int] = None

    room_name: Optional[str] = None
    room_number: Optional[str] = None
    matched_room_id: Optional[str] = None

    status: AutoPlacementStatus
    # "map_label" only when status == "auto_connectable"; otherwise
    # whatever the destination preview already said about this item.
    placement_source: PlacementSource = "needs_manual_placement"

    # Set only when status == "auto_connectable". Both are the SAME point:
    # QuickRoute's destination RoutePoint IS the room's arrival point (see
    # services/semantic_destination_service). They are reported separately
    # because the two names mean different things to an admin, and so that
    # this contract does not have to change if they ever diverge.
    suggested_room_point: Optional[List[float]] = None      # [x, y]
    suggested_arrival_point: Optional[List[float]] = None   # [x, y]

    semantic_match_confidence: float = 0.0
    geometry_confidence: float = 0.0

    matched_graph_element: Optional[MatchedGraphElement] = None
    diagnostics: AutoPlacementDiagnostics = Field(
        default_factory=AutoPlacementDiagnostics
    )
    # Human-readable, admin-facing. Always populated for a non-placed item.
    message: Optional[str] = None


class AutoPlacementSummary(BaseModel):
    scanned: int = 0
    auto_connectable: int = 0
    needs_arrival_confirmation: int = 0
    ambiguous_label: int = 0
    no_label_match: int = 0
    no_safe_graph_connection: int = 0
    # Items already carrying a trustworthy coordinate; this feature has
    # nothing to do for them and never re-places them.
    already_placed: int = 0


class AutoPlacementPreviewRequest(BaseModel):
    item_external_ids: Optional[List[str]] = None
    lang: str = "en"


class AutoPlacementPreviewResponse(BaseModel):
    publication_id: Optional[str] = None
    # vector_pdf | ocr | unavailable — where the labels came from, and why
    # there are none when there are none.
    label_source: str = "unavailable"
    label_source_reason: Optional[str] = None
    label_count: int = 0
    wall_mask_available: bool = False

    summary: AutoPlacementSummary = Field(default_factory=AutoPlacementSummary)
    proposals: List[AutoPlacementProposal] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
