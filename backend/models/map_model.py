from datetime import datetime
from typing import Dict, Literal, Optional

from beanie import Document
from pydantic import Field


ProcessingStatus = Literal[
    "not_started",
    "pending",
    "processing",
    "completed",
    "failed",
]

GenerationMethod = Literal[
    "local",
    "openai",
    "hybrid",
]


class Map(Document):
    title: str
    campus: Optional[str] = None
    address: Optional[str] = None
    description: Optional[str] = None

    # The building this map belongs to. Every RoutePoint created for this
    # map inherits this same building_id (see route_point_routes.py), so
    # Rooms, RoutePoints and LocationCodes for one physical location all
    # trace back to one Building. Optional at the schema level so maps
    # created before this field existed still load; new maps always get a
    # real value (either admin-selected or auto-created/reused from
    # campus/title via services/building_service.find_or_create_building).
    building_id: Optional[str] = None

    # The shared multi-floor parent this map belongs to (see
    # models/map_group_model.py). None for every pre-existing single-floor
    # map and for any map an admin still creates through the original
    # single-map upload flow — both keep working completely unchanged.
    # Never used as a coordinate/graph key; only RouteEdge/RoutePoint
    # queries still key strictly off `map_id`, never `map_group_id`, so
    # widening this relationship can never merge two floors' coordinates.
    map_group_id: Optional[str] = None

    # Which physical floor this map represents (e.g. 0 = ground floor,
    # 1 = first floor). A single map image currently represents one floor;
    # multi-floor buildings are modeled as multiple Map documents sharing
    # the same building_id (and, for an explicit multi-floor group, the
    # same map_group_id). Kept separate from RoutePoint.floor (which
    # remains the source of truth Dijkstra/edges actually use) so the admin
    # doesn't have to re-enter it for every point created on this map.
    floor: Optional[int] = None

    # Human-readable floor label, independent of the numeric `floor` value
    # so basements/parking/mezzanines can read naturally (e.g. floor=-1,
    # floor_label="Parking B1"). Optional — falls back to a numeric display
    # derived from `floor` on the frontend when not set.
    floor_label: Optional[str] = None

    # Old/current image field - do not remove
    image_url: Optional[str] = None

    # Original accurate map used by Admin
    source_image_url: Optional[str] = None

    # Clean colorful map displayed to the user
    display_image_url: Optional[str] = None

    # Information about the uploaded original file
    source_filename: Optional[str] = None
    source_content_type: Optional[str] = None

    # Image processing status
    processing_status: ProcessingStatus = "not_started"
    processing_progress: int = Field(default=0, ge=0, le=100)
    processing_error: Optional[str] = None

    # How the display map was created
    generation_method: Optional[GenerationMethod] = None

    # Original image dimensions
    source_width: Optional[int] = Field(default=None, gt=0)
    source_height: Optional[int] = Field(default=None, gt=0)

    # Display image dimensions
    display_width: Optional[int] = Field(default=None, gt=0)
    display_height: Optional[int] = Field(default=None, gt=0)

    # Meters-per-pixel for this floor's image. Defaults to the placeholder
    # value 1.0 for every map created before calibration existed (and any
    # map an admin hasn't calibrated yet) — that default must never be
    # presented to an admin/end-user as an accurate real-world distance;
    # see `is_calibrated` below, which is the actual trust signal.
    scale: float = Field(default=1.0, gt=0)

    # Scale per floor:
    # example: {"0": 0.05, "1": 0.03}
    floor_scales: Dict[str, float] = Field(default_factory=dict)

    # True only after an admin has explicitly run the two-click distance
    # calibration (POST /api/maps/{id}/calibrate-scale) on THIS map, or
    # explicitly copied a calibration from another floor. `scale = 1.0`
    # alone is never treated as "calibrated" — every distance/time shown
    # to an admin or end user must be able to tell an uncalibrated map
    # apart from a genuinely measured one instead of silently presenting
    # scale=1.0 pixel-distances as if they were meters.
    is_calibrated: bool = False
    calibrated_at: Optional[datetime] = None
    # How this map's current scale was set — "measured" (two-click
    # calibration on this map) or "copied" (explicitly copied from another
    # floor's calibration by an admin action, e.g. identical floor plans).
    # None when never calibrated.
    calibration_source: Optional[str] = None

    # Legacy single-map-collection-wide "current map" flag (see
    # set_map_as_current() in map_routes.py) — left completely untouched
    # for ungrouped maps. Grouped floor maps never participate in this
    # global flag (it is meaningless once multiple floors can be "current"
    # simultaneously, one per floor) and always keep this False; see
    # `is_current_for_floor` below for the per-floor equivalent.
    is_current: bool = True

    # Per-(map_group_id, floor) "current" flag — the multi-floor
    # equivalent of `is_current` above, scoped to a single floor instead of
    # the whole maps collection. True for every floor map today (each floor
    # only ever has one Map document per this task's scope), but kept as
    # its own real field now so a future "replace this floor's image"
    # workflow has somewhere safe to record which of possibly several Map
    # documents for the same (map_group_id, floor) is the active one,
    # without disturbing any other floor.
    is_current_for_floor: bool = True

    # Outcome of the most recent automatic walkable-graph generation
    # attempt for this map (see services/graph_generation_service.py).
    # None means generation was never attempted. This is deliberately not
    # a boolean "success" flag — low-confidence results are a normal,
    # expected outcome (the map is preserved and manual drawing still
    # works), not an error.
    graph_generation_status: Optional[str] = None
    graph_generation_confidence: Optional[float] = None
    graph_generation_note: Optional[str] = None
    graph_generated_at: Optional[datetime] = None

    processed_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "maps"