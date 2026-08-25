import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from beanie import Document
from pydantic import Field
from pymongo import IndexModel


class SemanticMapPublication(Document):
    """
    Admin-Reviewed Semantic Data made permanent — Layer (B)/(C) boundary
    (Section 2 and Section 15). Created ONLY by an explicit
    POST /api/semantic-analyses/{id}/publish call; never automatic.

    Publishing never touches Maps/RoutePoints/RouteEdges/Rooms/connectors
    — it only makes the admin-reviewed JSON (plus the QuickRoute floor/
    building links the admin confirmed) available as read-only reference
    data that RoutePoint-naming UI can search.
    """

    publication_id: str = Field(default_factory=lambda: uuid.uuid4().hex)

    analysis_id: str
    prompt_version: str
    prompt_sha256: str

    # Full reviewed_result document as it stood at publish time — the
    # canonical source of truth for this publication. `semantic_entities`
    # (below) is a derived search index built FROM this, never the other
    # way around.
    reviewed_result: Dict[str, Any]

    # {"building_links": [{"building_external_id", "building_id"}],
    #  "floor_links": [{"floor_external_id", "map_id"}]}
    # — see Section 14. Never injected into reviewed_result itself.
    quickroute_links: Dict[str, Any] = Field(default_factory=dict)

    map_id: Optional[str] = None
    map_group_id: Optional[str] = None
    building_id: Optional[str] = None

    publication_revision: int = 1
    published_by: Optional[str] = None
    published_at: datetime = Field(default_factory=datetime.utcnow)

    # True for the current, active publication for this map/map-group;
    # a later re-publish (new analysis revision) sets the previous
    # publication's is_active to False (superseded) but never deletes it
    # — full audit history is preserved (Section 15).
    is_active: bool = True
    superseded_by_publication_id: Optional[str] = None

    class Settings:
        name = "semantic_map_publications"
        indexes = [
            IndexModel("publication_id", unique=True),
            IndexModel("analysis_id"),
            IndexModel("map_id"),
            IndexModel("map_group_id"),
            IndexModel("is_active"),
            IndexModel("published_at"),
        ]


class SemanticEntity(Document):
    """
    Derived, searchable semantic-entity index (Section 15). Generated ONLY
    from accepted/corrected entities of an active publication's
    reviewed_result — rejected entities and pending-review entities are
    never indexed here. This is what the "Choose name from approved map
    data" RoutePoint selector (Section 16) actually queries; it is never
    itself the canonical source (the publication's reviewed_result is).
    """

    publication_id: str
    analysis_id: str

    entity_external_id: str
    # e.g. "place", "facility", "access_point", "vertical_connection",
    # "public_area", "outdoor_area", "parking_area", "parking_space".
    entity_type: str

    building_id: Optional[str] = None
    map_id: Optional[str] = None
    floor_external_id: Optional[str] = None

    # Legacy flat fields — kept exactly as-is for backward compatibility
    # with every entity indexed before the `names` field below existed;
    # still populated on every new entity too (never removed/replaced).
    names_original: Optional[str] = None
    names_en: Optional[str] = None
    names_ar: Optional[str] = None
    names_he: Optional[str] = None

    # Canonical nested multilingual structure — {"ar":..., "he":...,
    # "en":...} — the same single-document shape used everywhere else
    # (Room.names, RoutePoint's display_name_* triple exposed the same
    # way in API responses). This is the SAME data as the four flat
    # fields above, just also available pre-assembled; nothing here ever
    # creates a second/third document per language (see
    # schemas/localization_schema.py). Optional/None for any entity
    # indexed before this field was added — those keep resolving
    # correctly through the flat fields via names_ar/en/he in that case.
    names: Optional[Dict[str, Optional[str]]] = None

    category: Optional[str] = None
    subcategory: Optional[str] = None
    displayed_number: Optional[str] = None

    confidence: Optional[float] = None
    review_status: Optional[str] = None

    source_document_ids: List[str] = Field(default_factory=list)

    active: bool = True

    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "semantic_entities"
        indexes = [
            IndexModel("publication_id"),
            IndexModel("map_id"),
            IndexModel("building_id"),
            IndexModel("entity_type"),
            IndexModel("active"),
        ]
