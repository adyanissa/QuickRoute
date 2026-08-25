from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class RoutePointFloorBackfillRequest(BaseModel):
    # True by default — an admin must explicitly opt into `dry_run=false`
    # to actually write anything. Mirrors how this endpoint is documented
    # ("support dry_run=true first") and how the admin UI action is
    # required to call it: always dry-run first, only apply after an
    # explicit confirmation.
    dry_run: bool = True


class RoutePointFloorChange(BaseModel):
    point_id: str
    map_id: str
    name: str
    old_floor: Optional[int] = None
    new_floor: int


class RoutePointFloorBackfillResponse(BaseModel):
    dry_run: bool

    points_inspected: int
    points_needing_update: int
    points_updated: int

    # Every change that was (or, in a dry run, would be) applied — capped
    # defensively so a very large legacy dataset can't blow up the
    # response payload; `points_needing_update`/`points_updated` above are
    # always the true, uncapped counts regardless of this list's length.
    changes: List[RoutePointFloorChange] = Field(default_factory=list)

    # Points this operation deliberately left untouched because there was
    # no safe, non-guessed floor to assign (map missing entirely, or the
    # map itself has no floor recorded either) — surfaced so an admin
    # knows exactly what still needs manual attention instead of silently
    # skipping it.
    warnings: List[str] = Field(default_factory=list)


class RoutePointCreate(BaseModel):
    map_id: str = Field(..., min_length=1)

    # Admin-entered custom names (e.g. "Coffee Junction") are the normal
    # case for points created via Draw Walkable Path — max_length matches
    # the frontend's ROUTE_POINT_NAME_MAX_LENGTH (drawPathHelpers.js) so a
    # too-long name is rejected consistently on both sides, not just
    # silently truncated. Unicode (Arabic/Hebrew/etc.) names are accepted
    # natively — `str` has no ASCII restriction, and FastAPI parses the
    # request body as UTF-8.
    name: str = Field(..., min_length=2, max_length=120)
    point_type: Optional[str] = None

    x: float
    y: float

    floor: Optional[int] = None
    building_id: Optional[str] = None
    room_id: Optional[str] = None

    is_accessible: bool = True

    # Optional semantic-name linkage — see models/route_point_model.py's
    # matching fields for the full explanation. All None/omitted by
    # default; only ever set explicitly by the admin UI.
    display_name: Optional[str] = Field(default=None, max_length=160)
    display_name_en: Optional[str] = Field(default=None, max_length=160)
    display_name_ar: Optional[str] = Field(default=None, max_length=160)
    display_name_he: Optional[str] = Field(default=None, max_length=160)
    semantic_publication_id: Optional[str] = None
    semantic_entity_external_id: Optional[str] = None
    semantic_entity_type: Optional[str] = None

    # See models/route_point_model.py. Default False — an ordinary point
    # never allows transit-through just because it was created via this
    # endpoint.
    allow_transit_through: bool = False

    # When true, skip the server-side find-or-create duplicate check and
    # always insert a new document even if a near-identical point already
    # exists. Off by default — normal admin/auto-generation flows should
    # always go through dedup; this exists only as an explicit escape
    # hatch (e.g. two genuinely distinct junctions that happen to be very
    # close together).
    force_create: bool = False


class RoutePointUpdate(BaseModel):
    map_id: Optional[str] = None

    # Explicit-rename path only (see route_point_routes.py's update
    # endpoint) — an existing reused point's name is never changed by the
    # Draw Walkable Path save flow itself, only by a deliberate PUT here.
    name: Optional[str] = Field(default=None, min_length=2, max_length=120)
    point_type: Optional[str] = None

    x: Optional[float] = None
    y: Optional[float] = None

    floor: Optional[int] = None
    building_id: Optional[str] = None
    room_id: Optional[str] = None

    is_accessible: Optional[bool] = None
    is_active: Optional[bool] = None

    # Optional semantic-name linkage — see RoutePointCreate above. Sending
    # an explicit empty string clears a previously-set display name; the
    # field is simply omitted (exclude_unset) to leave it untouched.
    display_name: Optional[str] = Field(default=None, max_length=160)
    display_name_en: Optional[str] = Field(default=None, max_length=160)
    display_name_ar: Optional[str] = Field(default=None, max_length=160)
    display_name_he: Optional[str] = Field(default=None, max_length=160)
    semantic_publication_id: Optional[str] = None
    semantic_entity_external_id: Optional[str] = None
    semantic_entity_type: Optional[str] = None

    # See models/route_point_model.py / RoutePointCreate above. Omitted
    # (exclude_unset) leaves the stored value untouched, same convention
    # as every other optional field here.
    allow_transit_through: Optional[bool] = None


class RoutePointResponse(BaseModel):
    id: str
    map_id: str

    name: str
    point_type: Optional[str] = None

    x: float
    y: float

    floor: Optional[int] = None
    building_id: Optional[str] = None
    room_id: Optional[str] = None

    connector_id: Optional[str] = None
    connector_code: Optional[str] = None

    is_accessible: bool
    is_active: bool

    display_name: Optional[str] = None
    display_name_en: Optional[str] = None
    display_name_ar: Optional[str] = None
    display_name_he: Optional[str] = None
    semantic_publication_id: Optional[str] = None
    semantic_entity_external_id: Optional[str] = None
    semantic_entity_type: Optional[str] = None

    allow_transit_through: bool = False

    is_auto_generated: bool = False
    generation_method: Optional[str] = None
    generation_confidence: Optional[float] = None
    generation_version: Optional[int] = None

    # Derived, authoritative-metadata-first provenance classification
    # (Problem 2.3 of the navigation-data cleanup task): one of
    # "manual" | "generated" | "semantic_destination" |
    # "vertical_connector" | "unknown_legacy". Computed server-side by
    # routes/route_point_routes.py's classify_route_point_source() so the
    # frontend never has to re-derive this logic itself.
    source: str = "manual"

    created_at: datetime
    updated_at: datetime

    # True only on the specific response to a create call that reused an
    # existing point instead of inserting a new document. Always False on
    # every other response (get/list/update) — this is a one-shot signal
    # for the caller that just asked to create a point, not a persisted
    # property of the point itself.
    was_reused: bool = False

    # IDs of any RouteEdge documents the server created automatically as a
    # side effect of this create call (only possible when ?auto_connect=
    # nearest|all_valid was requested and this was a genuinely new point,
    # never on a reused point). Same one-shot-signal rule as was_reused:
    # only meaningful on the create response, always empty otherwise. The
    # caller (Draw Walkable Path's Save Path) needs these ids so a later
    # rollback of a failed save can delete them too — deleting the point
    # alone would otherwise be rejected (409) because these edges still
    # reference it.
    auto_connected_edge_ids: List[str] = Field(default_factory=list)

    # Destination data flow (Section 2/3/8) — one-shot signals reporting
    # what services/room_sync_service.py just did for this point, so the
    # admin UI can show "this point is now a destination" or a warning
    # without needing a second request. Always additive/optional: a client
    # that doesn't know about these fields keeps working exactly as
    # before. `room_id` above already reflects the resulting link — these
    # two only add the "what just happened" narrative.
    # One of: created | updated | reused | deactivated |
    # skipped_non_destination | skipped_no_building | skipped_ambiguous |
    # sync_failed | None (never attempted, e.g. GET/list responses).
    room_sync_action: Optional[str] = None
    room_sync_warning: Optional[str] = None


class RoutePointCountResponse(BaseModel):
    """
    Problem 2.1: a count that always states its own scope, so it can never
    be mistaken for belonging to a narrower context than it actually
    covers. `is_global=True` means literally every RoutePoint in the
    entire system, across every location/building/map — this must always
    be labeled as such (e.g. "All locations: N nodes") wherever it is
    shown, never presented next to per-building stats as if it were
    scoped the same way.
    """

    count: int
    map_id: Optional[str] = None
    building_id: Optional[str] = None
    room_id: Optional[str] = None
    floor: Optional[int] = None
    point_type: Optional[str] = None
    source: Optional[str] = None
    is_global: bool = False


class PublicRoutePointResponse(BaseModel):
    """
    RBAC/dashboard cleanup task, Phase 3 — the minimal shape returned to
    anonymous/end-user callers (QR entry, kiosk navigation). Deliberately
    excludes everything the admin management response exposes that an
    ordinary navigating visitor never needs and shouldn't see: provenance
    (is_auto_generated/generation_method/generation_confidence/
    generation_version/source), semantic linkage ids, room-sync
    action/warning notes, and was_reused/auto_connected_edge_ids (both
    one-shot admin-create signals). Only what turn-by-turn navigation
    itself actually renders.
    """

    id: str
    map_id: str
    name: str
    point_type: Optional[str] = None
    x: float
    y: float
    floor: Optional[int] = None
    building_id: Optional[str] = None
    room_id: Optional[str] = None
    is_accessible: bool = True
    is_active: bool = True
    display_name: Optional[str] = None
    display_name_en: Optional[str] = None
    display_name_ar: Optional[str] = None
    display_name_he: Optional[str] = None
    allow_transit_through: bool = False


class RoutePointBulkDeleteRequest(BaseModel):
    """
    RBAC/dashboard cleanup task, Phase 6 — shared request shape for both
    the preview and apply bulk-delete endpoints, so a caller can send the
    exact same body to preview first and then apply (only the endpoint
    path and the `confirm` flag differ).
    """

    point_ids: List[str] = Field(..., min_length=1, max_length=500)


class RoutePointBulkDeleteIssue(BaseModel):
    point_id: str
    # One of: not_found | out_of_scope | has_connected_edges |
    # has_location_code | invalid_id
    reason: str
    detail: str
    # Only populated for has_connected_edges, so the admin can see exactly
    # how many edges are blocking this point without a separate call.
    connected_edge_count: Optional[int] = None


class RoutePointBulkDeleteWarning(BaseModel):
    """
    Non-blocking side effects the admin should know about ahead of time —
    unlike RoutePointBulkDeleteIssue above, these never prevent deletion.
    """

    point_id: str
    # One of: linked_room_will_be_deactivated
    reason: str
    detail: str


class RoutePointBulkDeletePreviewResponse(BaseModel):
    """
    Preview-only — never deletes anything. Mirrors the same all-or-nothing
    validation the apply endpoint will perform, so what the admin sees in
    the preview dialog is exactly what will happen (or exactly why it
    won't) when they confirm.
    """

    requested_count: int
    deletable_count: int
    blocked_count: int

    # ids that passed every check and would actually be deleted if this
    # exact same request were sent to the apply endpoint right now.
    deletable_point_ids: List[str] = Field(default_factory=list)

    issues: List[RoutePointBulkDeleteIssue] = Field(default_factory=list)
    warnings: List[RoutePointBulkDeleteWarning] = Field(default_factory=list)

    # All-or-nothing: apply will refuse the whole batch unless this is
    # True, i.e. unless `issues` is empty. Surfaced explicitly so the
    # frontend never has to re-derive it from `issues.length == 0`.
    can_apply_all: bool = False


class RoutePointBulkDeleteApplyResponse(BaseModel):
    """
    Result of an actually-applied bulk delete. Because the apply endpoint
    is strictly all-or-nothing (see route handler docstring), a 200
    response here always means every id in `deleted_point_ids` was
    deleted and nothing else was touched — there is never a partial
    "some succeeded, some failed" result to reconcile.
    """

    deleted_count: int
    deleted_point_ids: List[str] = Field(default_factory=list)
    warnings: List[RoutePointBulkDeleteWarning] = Field(default_factory=list)


class RoutePointListResponse(BaseModel):
    """
    RBAC/dashboard cleanup task, Phase 8 — paginated RoutePoint listing.
    Additive: GET /api/route-points (unpaginated, returns a bare list)
    keeps working completely unchanged for every existing caller; this
    backs the NEW GET /api/route-points/list endpoint only, so nothing
    that already depends on the old response shape breaks.
    """

    items: List["RoutePointResponse"] = Field(default_factory=list)

    page: int = 1
    page_size: int = 50

    # Number of items actually returned in `items` on this page — never
    # more than page_size, and less than page_size only on the last page.
    loaded_count: int = 0

    # Total number of RoutePoints matching the filter+scope, across every
    # page — always the true count, never approximated.
    total_count: int = 0
    total_pages: int = 0

    # Scope metadata (Problem 2.1's "never a bare number" rule, extended
    # to pagination): mirrors RoutePointCountResponse's own filters/
    # is_global so the frontend never has to guess what this page's items
    # are scoped to.
    map_id: Optional[str] = None
    building_id: Optional[str] = None
    room_id: Optional[str] = None
    floor: Optional[int] = None
    point_type: Optional[str] = None
    source: Optional[str] = None
    search: Optional[str] = None
    is_global: bool = False