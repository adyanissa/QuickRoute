from datetime import datetime
from typing import Optional

from beanie import Document
from pydantic import Field
from pymongo import IndexModel


class MapGroup(Document):
    """
    The shared parent identity for a multi-floor indoor map (e.g. a mall
    with a ground floor, first floor, and a parking basement). Each floor
    remains its own independent `Map` document — its own image, its own
    RoutePoints/RouteEdges, its own processing/scale — linked back here
    only via `Map.map_group_id`. A MapGroup never stores per-floor data
    itself (no image, no points) so there is exactly one source of truth
    for "how many floors" and "what floor is this": query `Map` by
    `map_group_id`, never duplicate that count/list onto this document.

    A single-floor building never needs a MapGroup — `Map.map_group_id`
    stays None for those, preserving the pre-existing single-map workflow
    exactly as it was (see routes/map_routes.py's plain /upload and
    /api/maps endpoints, both left untouched by this feature).
    """

    building_id: str

    name: str
    # Stable, unique, admin-facing identifier for the whole floor set
    # (e.g. "QRMALL-001"). Normalized (trimmed/uppercased/validated) by
    # services/map_group_service.py before this is ever written — never
    # regenerated once a group exists, even as floors are added later.
    code: str

    description: Optional[str] = None
    campus: Optional[str] = None
    address: Optional[str] = None

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "map_groups"
        indexes = [
            IndexModel("code", unique=True),
        ]
