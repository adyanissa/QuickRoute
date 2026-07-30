from datetime import datetime
from typing import Optional

from beanie import Document
from pydantic import Field


class RoutePoint(Document):
    map_id: str

    name: str
    point_type: Optional[str] = None

    x: float
    y: float

    floor: Optional[int] = None
    building_id: Optional[str] = None
    room_id: Optional[str] = None

    # Set only when this point is a serviced-floor "stop" of a
    # VerticalConnector (elevator/stairs/escalator/ramp) — see
    # models/vertical_connector_model.py. connector_code is denormalized
    # from the connector at stop-creation time purely so admin list/debug
    # views never need an extra lookup; connector_id is always the single
    # source of truth (e.g. for "which stops belong to this connector").
    # None for every ordinary corridor/room/entrance point, which is the
    # overwhelming majority of points both before and after this feature.
    connector_id: Optional[str] = None
    connector_code: Optional[str] = None

    is_accessible: bool = True
    is_active: bool = True

    # Nested-room navigation (Approved Semantic Analysis -> Automatic
    # Destinations spec, Section 9). True only for a destination-capable
    # (room/store) point an admin has EXPLICITLY approved as an "outer"
    # room that a user may walk through to reach an inner destination —
    # e.g. Library Storage on the way to Library Storage/Office. Default
    # False for every point (existing and new): an ordinary Room/Store
    # stays terminal-only (valid start/destination, never an intermediate
    # transit node) exactly as before. Never set automatically — only via
    # an explicit admin confirmation in the nested-room review UI or the
    # semantic-destination apply endpoint. See
    # logic/multi_floor_routing.py's _suppress_intermediate_destination_nodes
    # for the one place this is actually consulted; Dijkstra itself is
    # unmodified.
    allow_transit_through: bool = False

    # Optional semantic-name linkage (Section 16 of the semantic-map-
    # analysis spec). Entirely additive/backward-compatible — every
    # existing point keeps working unchanged with all of these left None.
    # display_name (when set) is what normal-user navigation instructions
    # should prefer showing instead of the raw, often machine-generated
    # `name` above (e.g. "Corridor Point 1784904901734-6"). Never set
    # automatically from AI data — only when an admin explicitly picks a
    # name via "Choose name from approved map data" or types one in.
    display_name: Optional[str] = None
    display_name_en: Optional[str] = None
    display_name_ar: Optional[str] = None
    display_name_he: Optional[str] = None

    # Set only when display_name was chosen FROM a published semantic
    # entity (see models/semantic_map_publication_model.py) rather than
    # typed freely — lets the admin UI show "linked to: <entity>" and
    # lets a later re-publish detect which RoutePoints reference it. Never
    # used by routing/Dijkstra; purely a display/traceability link.
    semantic_publication_id: Optional[str] = None
    semantic_entity_external_id: Optional[str] = None
    semantic_entity_type: Optional[str] = None

    # Generation provenance — lets regeneration clear only what it created
    # and never touch admin-drawn/manually-added points, and lets the admin
    # UI visually distinguish auto-generated points from manual ones.
    is_auto_generated: bool = False
    generation_method: Optional[str] = None
    generation_confidence: Optional[float] = None
    generation_version: Optional[int] = None

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "route_points"