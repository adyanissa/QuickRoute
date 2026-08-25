from datetime import datetime
from typing import Dict, Optional

from beanie import Document
from pydantic import Field
from pymongo import IndexModel


class Room(Document):
    building_id: str

    name_en: str
    name_local: Optional[str] = None

    # Optional multilingual translations — {"ar":..., "he":..., "en":...},
    # every key optional. Entirely additive: a Room created before this
    # field existed simply has `names=None` and keeps working exactly as
    # before via the name_en/name_local fallback (see
    # schemas/localization_schema.get_localized_text). Populated when a
    # Destination is created from an approved semantic-analysis entity
    # (see routes/room_routes.py's create_room) so every admin-approved
    # translation is preserved; never auto-translated.
    names: Optional[Dict[str, Optional[str]]] = None

    # Set only when this Room was created FROM an approved published
    # semantic entity (see models/semantic_map_publication_model.py) —
    # mirrors the same traceability link RoutePoint already has
    # (semantic_publication_id/semantic_entity_external_id/
    # semantic_entity_type). Never used by routing; purely a display/
    # traceability link, and never set for a manually-typed Room.
    semantic_publication_id: Optional[str] = None
    semantic_entity_external_id: Optional[str] = None
    semantic_entity_type: Optional[str] = None

    room_number: Optional[str] = None
    floor: Optional[int] = None
    room_type: Optional[str] = None

    description: Optional[str] = None
    category: Optional[str] = None

    # Map-based destination placement (optional — the manual-only entry
    # flow never sets these, and a Room without them behaves exactly as
    # before: a category entry with no navigation link).
    #
    # map_id/x/y are the map and original-image coordinates the admin
    # clicked when placing this destination. route_point_id is the
    # RoutePoint that was created-or-reused at that location and is what
    # the end-user navigation flow resolves directly (see
    # room_routes.py/create_room and IndoorNavigationScreen.jsx) — it is
    # never re-derived by searching for "a" point that happens to
    # reference this room, so there is exactly one unambiguous answer to
    # "which RoutePoint is this destination".
    map_id: Optional[str] = None
    x: Optional[float] = None
    y: Optional[float] = None
    route_point_id: Optional[str] = None

    # Nested-room navigation (Approved Semantic Analysis -> Automatic
    # Destinations spec, Section 9). Set only after explicit admin
    # confirmation that this Room is physically reached BY PASSING THROUGH
    # another Room (e.g. Library Storage/Office is accessed through Library
    # Storage) — parent_room_id is that outer Room's id. None for every
    # ordinary, non-nested Room (the overwhelming majority, including every
    # Room that existed before this field). The outer Room referenced here
    # must itself have its own destination RoutePoint's
    # allow_transit_through set True for the nested path to actually route
    # (see services/semantic_destination_service.py, which is the only
    # code path allowed to set both together, and
    # logic/multi_floor_routing.py, which is the only place this
    # relationship is actually consulted for routing). Never inferred from
    # coordinates/proximity alone — always an explicit, approved link.
    parent_room_id: Optional[str] = None

    is_active: bool = True

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "rooms"
        indexes = [
            # GET /api/rooms?building_id=... is the query the public
            # Destination Selection screen makes on every visit, and it was
            # a full collection scan. Not unique: a building has many rooms.
            IndexModel("building_id"),
        ]