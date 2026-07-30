from datetime import datetime
from typing import Dict, List, Optional

from pydantic import BaseModel, Field, field_validator

from constants.destination_types import (
    ALL_ACCEPTED_DESTINATION_TYPES,
    is_accepted_destination_type,
)


class RoomCreate(BaseModel):
    building_id: str = Field(..., min_length=1)

    name_en: str = Field(..., min_length=2)
    name_local: Optional[str] = None

    # Optional {"ar":..., "he":..., "en":...} translations — see
    # models/room_model.py. Sending only some languages is valid; an
    # absent language is simply left unset, never defaulted/invented.
    names: Optional[Dict[str, Optional[str]]] = None

    # Traceability link to the semantic entity this Destination was
    # created from, when applicable (see routes/room_routes.py). All
    # optional/None for the ordinary manual-entry flow.
    semantic_publication_id: Optional[str] = None
    semantic_entity_external_id: Optional[str] = None
    semantic_entity_type: Optional[str] = None

    room_number: Optional[str] = None
    floor: Optional[int] = None
    room_type: Optional[str] = None

    description: Optional[str] = None
    category: Optional[str] = None

    # A brand-new Room has no prior stored room_type to preserve, so a
    # genuinely unsupported value is safely rejected here (see
    # constants/destination_types.py for the full canonical list and the
    # "why not elevator/stairs" architecture decision). RoomUpdate
    # deliberately has NO equivalent validator — an update's room_type is
    # only checked in routes/room_routes.py's update_room(), and only when
    # it's actually being changed to a NEW value, so an already-stored
    # legacy value (e.g. the old "operating") always round-trips safely
    # even if a future admin action resaves a Room without ever touching
    # its Type field.
    @field_validator("room_type")
    @classmethod
    def _validate_room_type(cls, value: Optional[str]) -> Optional[str]:
        if not is_accepted_destination_type(value):
            raise ValueError(
                f"Unsupported room_type '{value}'. Must be one of: "
                f"{sorted(ALL_ACCEPTED_DESTINATION_TYPES)}"
            )
        return value

    # Nested-room navigation (see models/room_model.py). None for every
    # ordinary Room. Only ever meaningfully set via an explicit admin
    # confirmation (services/semantic_destination_service.py or a direct
    # admin edit) — never guessed from name/proximity.
    parent_room_id: Optional[str] = None

    # Map-based destination placement — all optional so the existing
    # manual-only "type everything in" flow keeps working unchanged. When
    # map_id, x and y are ALL provided, create_room() creates-or-reuses a
    # destination RoutePoint at that location and auto-connects it to the
    # nearby walkable graph (see room_routes.py). Providing only some of
    # the three is treated as "no map placement" rather than a partial/
    # broken one.
    map_id: Optional[str] = None
    x: Optional[float] = None
    y: Optional[float] = None


class RoomUpdate(BaseModel):
    building_id: Optional[str] = None

    name_en: Optional[str] = Field(default=None, min_length=2)
    name_local: Optional[str] = None

    # Same merge semantics as everywhere else in this file: a language
    # key genuinely ABSENT from this dict leaves that language untouched;
    # a key present (even as null) overwrites just that one language.
    # See schemas/localization_schema.merge_localized_text(), which
    # room_routes.update_room() uses to apply this correctly.
    names: Optional[Dict[str, Optional[str]]] = None

    semantic_publication_id: Optional[str] = None
    semantic_entity_external_id: Optional[str] = None
    semantic_entity_type: Optional[str] = None

    room_number: Optional[str] = None
    floor: Optional[int] = None
    room_type: Optional[str] = None

    description: Optional[str] = None
    category: Optional[str] = None

    is_active: Optional[bool] = None

    # See RoomCreate above. Sending an explicit null clears a previously
    # set nested relationship (never overwritten by an ordinary Room's
    # own default of None just because the field was omitted, thanks to
    # the usual exclude_unset convention every other field here uses).
    parent_room_id: Optional[str] = None

    # Same map-placement fields as RoomCreate. Sending a new map_id/x/y
    # repositions the destination — see update_room()'s docstring for
    # exactly what that does (and does not) touch on the previously
    # linked RoutePoint.
    map_id: Optional[str] = None
    x: Optional[float] = None
    y: Optional[float] = None


class RoomResponse(BaseModel):
    id: str
    building_id: str

    name_en: str
    name_local: Optional[str] = None

    # Full multilingual object — None for a legacy Room that has never
    # had a translation stored (existing consumers keep using name_en/
    # name_local unchanged; new consumers can read this instead). See
    # Section 7 of the multilingual content spec: user-facing APIs return
    # the full object, never silently pick just one language server-side.
    names: Optional[Dict[str, Optional[str]]] = None

    semantic_publication_id: Optional[str] = None
    semantic_entity_external_id: Optional[str] = None
    semantic_entity_type: Optional[str] = None

    room_number: Optional[str] = None
    floor: Optional[int] = None
    room_type: Optional[str] = None

    description: Optional[str] = None
    category: Optional[str] = None

    map_id: Optional[str] = None
    x: Optional[float] = None
    y: Optional[float] = None
    route_point_id: Optional[str] = None

    parent_room_id: Optional[str] = None

    # Resolved (never stored on Room itself) from Map(map_id).map_group_id
    # at response time — None whenever map_id is None, or when the linked
    # map is an ungrouped single-floor map. See room_to_response() in
    # room_routes.py.
    map_group_id: Optional[str] = None

    is_active: bool

    created_at: datetime
    updated_at: datetime

    # One-shot signals, populated only on the specific response to a
    # create/update call that just performed the map-linking step — same
    # pattern as RoutePointResponse.was_reused. Always False on plain
    # get/list responses; not a persisted property of the Room itself.
    route_point_was_reused: bool = False
    route_point_connected: bool = False

    # The authoritative, LIVE navigability signal — computed fresh on
    # every single response (list/get/create/update alike) by actually
    # querying the current RoutePoint/RouteEdge state, never trusted from
    # a stored/cached value. This is what end-user screens (e.g.
    # DestinationSelectionScreen.jsx) must use to decide whether a
    # destination card is clickable — unlike route_point_connected above,
    # this is never silently False just because the request happened to
    # be a plain GET. See compute_room_navigability() in room_routes.py.
    is_navigable: bool = False
    navigation_unavailable_reason: Optional[str] = None


# ── "Sync Rooms from Route Points" bulk admin action ────────────────────────
# Destination data flow (Section 4): repairs existing destination-capable
# RoutePoints (type "room"/"store") that predate this feature and have no
# linked Room yet, without requiring the admin to open Add Room once per
# point. See services/room_sync_service.py for the actual matching/create/
# update logic this endpoint drives; this only defines its request/response
# shape.
class RoomSyncRequest(BaseModel):
    # Exactly one of these two must be given (enforced in the route) — the
    # scope the bulk action operates over, matching "the currently selected
    # building or Map Group" the admin has open.
    building_id: Optional[str] = None
    map_group_id: Optional[str] = None


class RoomSyncResponse(BaseModel):
    scanned: int
    created: int
    updated: int
    skipped: int
    failed: int

    # Short, safe (never a raw exception) explanations for every skipped/
    # failed point — capped so a very large legacy dataset can't blow up
    # the response payload; the scanned/created/updated/skipped/failed
    # counts above are always the true, uncapped totals regardless of this
    # list's length.
    warnings: List[str] = Field(default_factory=list)