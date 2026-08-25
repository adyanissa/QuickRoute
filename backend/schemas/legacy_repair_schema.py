"""
Request/response schemas for legacy invalid-connection repair and for the
bulk pending-attachment retry.

See services/legacy_edge_repair_service.py for what counts as invalid (and,
just as importantly, what is deliberately preserved), and
services/destination_attachment_service.py for the single attachment
algorithm both of these ultimately call.
"""

from typing import List, Literal, Optional

from pydantic import BaseModel, Field


# What a finding is. Only the first two are ever repaired automatically —
# a transit bridge needs an admin decision because cutting either of its
# corridor edges could sever the corridor itself.
LegacyFindingKind = Literal[
    "room_to_room",
    "stale_attachment",
    "room_used_as_transit_bridge",
    "only_invalid_edges",
]


class LegacyRepairPreviewRequest(BaseModel):
    # Always exactly one map. There is deliberately no building-wide or
    # global variant: a destructive cleanup must never be able to reach a
    # floor the admin is not looking at.
    map_id: str = Field(..., min_length=1)


class LegacyRepairFinding(BaseModel):
    kind: LegacyFindingKind

    # False for findings that are reported for human judgement only.
    repairable: bool = False

    # Set for edge-level findings; None for point-level ones.
    edge_id: Optional[str] = None
    from_point_id: Optional[str] = None
    to_point_id: Optional[str] = None

    # Set for point-level findings.
    point_id: Optional[str] = None

    # Human-facing labels — never a raw id as the primary label.
    from_name: Optional[str] = None
    to_name: Optional[str] = None
    room_name: Optional[str] = None

    # For a transit bridge: the walkable-graph points it currently sits
    # between, so the admin knows which pair needs a direct corridor link.
    graph_neighbour_ids: List[str] = Field(default_factory=list)

    detail: Optional[str] = None


class LegacyRepairPreviewResponse(BaseModel):
    map_id: str
    scanned_edges: int = 0
    scanned_destinations: int = 0
    invalid_edges: int = 0
    repairable_edges: int = 0
    needs_review: int = 0
    findings: List[LegacyRepairFinding] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


class LegacyRepairApplyRequest(BaseModel):
    map_id: str = Field(..., min_length=1)

    # The edges the admin confirmed. Omit to repair every auto-repairable
    # finding this map's own preview reports — still only the repairable
    # kinds, and still only on this map: an id that is not in this map's
    # preview is rejected rather than acted on.
    edge_ids: Optional[List[str]] = None


class LegacyRepairUnconnected(BaseModel):
    point_id: str
    name: Optional[str] = None
    reason: Optional[str] = None


class LegacyRepairApplyResult(BaseModel):
    map_id: str
    requested: int = 0
    repaired: int = 0
    skipped_already_repaired: int = 0
    rejected_invalid: int = 0
    reconnected: int = 0
    still_needs_review: int = 0
    unconnected: List[LegacyRepairUnconnected] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


class PendingAttachmentRetryRequest(BaseModel):
    map_id: str = Field(..., min_length=1)

    # Defensive extra narrowing only — a Map already represents one floor
    # in the normal model.
    floor: Optional[int] = None


class PendingAttachmentEntry(BaseModel):
    point_id: str
    name: Optional[str] = None
    point_type: Optional[str] = None
    reason: Optional[str] = None


class PendingAttachmentRetryResult(BaseModel):
    map_id: str
    scanned: int = 0
    already_connected: int = 0
    attached: int = 0
    junctions_created: int = 0
    still_pending: int = 0
    pending: List[PendingAttachmentEntry] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
