from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field

from schemas.map_schema import MapResponse


class MapGroupFloorInput(BaseModel):
    """
    One floor's metadata, paired positionally with one uploaded file in a
    multi-floor batch request (see routes/map_groups_routes.py — the
    multipart request carries `files: List[UploadFile]` plus a single
    `floors_json` Form field holding a JSON list of these, matched by
    index). Kept as its own schema (rather than N separate indexed Form
    fields like `floor_0`, `floor_1`, ...) so the admin can add or remove
    floor rows freely in the frontend without inventing an unbounded set
    of field names, and so validation of the whole batch happens in one
    place before any file is written to disk.
    """

    title: str = Field(..., min_length=2)
    floor: int
    floor_label: Optional[str] = None
    scale: float = Field(default=1.0, gt=0)
    use_openai: bool = False
    auto_generate_graph: bool = True


class MapGroupCreateFields(BaseModel):
    """
    The non-file, non-per-floor Form fields of POST /api/map-groups (Map
    Group Information). Not used directly as a FastAPI parameter type
    (multipart requests need individual `Form(...)` parameters — see the
    route), but documents the exact shape those Form fields represent.
    """

    building_id: Optional[str] = None
    name: str = Field(..., min_length=2)
    code: Optional[str] = None
    campus: Optional[str] = None
    address: Optional[str] = None
    description: Optional[str] = None


class MapGroupResponse(BaseModel):
    id: str
    code: str
    name: str
    building_id: str

    campus: Optional[str] = None
    address: Optional[str] = None
    description: Optional[str] = None

    # Derived by counting/loading Map documents with this map_group_id at
    # response time — never stored on MapGroup itself, so there is exactly
    # one source of truth for "how many floors"/"which floors" (the Map
    # collection), never two numbers that can drift apart.
    floor_count: int
    floors: List[MapResponse] = Field(default_factory=list)

    created_at: datetime
    updated_at: datetime


class MapGroupSummaryResponse(BaseModel):
    """
    Lightweight group listing entry (GET /api/map-groups) — same shape as
    MapGroupResponse but intentionally reused as-is (floors included) since
    the Map Management screen's grouped list needs each group's floors to
    render its expandable floor list without a second round-trip per
    group. Kept as a distinct name only for readability at the call site.
    """

    id: str
    code: str
    name: str
    building_id: str
    campus: Optional[str] = None
    address: Optional[str] = None
    description: Optional[str] = None
    floor_count: int
    floors: List[MapResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
