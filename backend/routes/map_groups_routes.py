"""
Multi-floor Map Groups.

A MapGroup is the shared parent identity for several per-floor Map
documents (e.g. a mall's ground floor, first floor, and parking level).
Each floor keeps its own independent Map record — its own image, its own
RoutePoints/RouteEdges, its own scale, its own processing state — related
back to the group only via `Map.map_group_id`. This file never creates a
single Map record shared by multiple floors, never merges floor images,
and never fabricates cross-floor navigation edges — see
routes/route_edge_routes.py for the (still fully explicit,
admin-triggered-only) stairs/elevator transition support this feature
prepares the model for.

Endpoints:
  POST   /api/map-groups                       create a group + its
                                                 initial floor(s) — all
                                                 files/floors in one
                                                 all-or-nothing multipart
                                                 request.
  POST   /api/map-groups/{group_id}/floors      add one or more floors to
                                                 an EXISTING group — never
                                                 recreates the group, never
                                                 changes its code, never
                                                 touches other floors.
  GET    /api/map-groups                        list every group with its
                                                 ordered floors.
  GET    /api/map-groups/{group_id}             one group with its ordered
                                                 floors.
  PUT    /api/map-groups/{group_id}             edit group metadata (name/
                                                 campus/address/description)
                                                 — the code is immutable
                                                 once a group exists.
  DELETE /api/map-groups/{group_id}/floors/{id} delete exactly one floor —
                                                 the group and every other
                                                 floor are left untouched.
  DELETE /api/map-groups/{group_id}             delete the group AND every
                                                 one of its floors (explicit
                                                 cascade, never partial).
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from beanie import PydanticObjectId
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
    status,
)
from pydantic import BaseModel, Field, ValidationError

from core.auth_deps import require_global_admin
from models.building_model import Building
from models.map_group_model import MapGroup
from models.map_model import Map
from models.user_model import User
from schemas.map_group_schema import MapGroupFloorInput, MapGroupResponse
from services.building_service import find_or_create_building
from services.map_group_service import resolve_group_code
from services.map_image_service import (
    delete_file_safely,
    preserve_original_source_file,
    save_upload_to_temporary_file,
    to_storage_relative_path,
)
from logic.graph_validation import validate_multi_floor_navigation
from routes.map_routes import (
    cascade_delete_map_graph,
    clean_optional_text,
    map_to_response,
    process_map_in_background,
    remove_map_files,
    resolve_map_building_id,
)


router = APIRouter(
    prefix="/api/map-groups",
    tags=["Map Groups"],
)


# ---------------------------------------------------------
# Shared validation helpers
# ---------------------------------------------------------

def parse_floors_json(floors_json: str) -> List[MapGroupFloorInput]:
    try:
        raw_list = json.loads(floors_json)
    except (TypeError, ValueError) as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"floors_json must be valid JSON: {error}",
        ) from error

    if not isinstance(raw_list, list) or len(raw_list) == 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="floors_json must be a non-empty JSON list of floor entries.",
        )

    try:
        return [MapGroupFloorInput(**entry) for entry in raw_list]
    except ValidationError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid floor entry: {error}",
        ) from error


def validate_no_duplicate_floors(
    new_floors: List[MapGroupFloorInput],
    existing_floor_numbers: set,
) -> None:
    """
    Two floor maps in the same group must never share a floor number —
    checked both within the batch being submitted right now (e.g. two rows
    both left at floor 0) and against every floor the group already has
    (e.g. re-adding floor 1 to a group that already has one).
    """

    seen_in_batch = set()

    for entry in new_floors:
        if entry.floor in seen_in_batch:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Floor {entry.floor} is used by more than one floor "
                    "entry in this upload."
                ),
            )
        seen_in_batch.add(entry.floor)

        if entry.floor in existing_floor_numbers:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Floor {entry.floor} already exists in this map group."
                ),
            )


async def _existing_floor_numbers(group_id: str) -> set:
    existing_maps = await Map.find(Map.map_group_id == group_id).to_list()
    return {m.floor for m in existing_maps if m.floor is not None}


async def _load_group_or_404(group_id: str) -> MapGroup:
    try:
        object_id = PydanticObjectId(group_id)
    except Exception as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Map group not found",
        ) from error

    group = await MapGroup.get(object_id)
    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Map group not found",
        )
    return group


async def group_to_response(group: MapGroup) -> MapGroupResponse:
    floor_maps = await Map.find(Map.map_group_id == str(group.id)).to_list()
    # Sort by numeric floor value (requirement: floor maps are always
    # returned/rendered in ascending floor order); floors without a number
    # (should not normally happen — floor is required on creation) sort last.
    floor_maps.sort(key=lambda m: (m.floor is None, m.floor))

    return MapGroupResponse(
        id=str(group.id),
        code=group.code,
        name=group.name,
        building_id=group.building_id,
        campus=group.campus,
        address=group.address,
        description=group.description,
        floor_count=len(floor_maps),
        floors=[
            map_to_response(m, map_group_code=group.code) for m in floor_maps
        ],
        created_at=group.created_at,
        updated_at=group.updated_at,
    )


class _CreatedFloorFile:
    __slots__ = ("token", "path", "entry", "content_type", "filename")

    def __init__(self, token, path, entry, content_type, filename):
        self.token = token
        self.path = path
        self.entry = entry
        self.content_type = content_type
        self.filename = filename


async def _save_floor_files(
    files: List[UploadFile],
    floor_entries: List[MapGroupFloorInput],
) -> List[_CreatedFloorFile]:
    """
    Saves every floor's uploaded file to temporary storage, one at a time.
    If any single file fails validation (bad extension, too large, empty),
    every file already saved in this same batch is cleaned up immediately
    and the whole request is rejected before a single Map/MapGroup
    document is ever written — the "validate before writing files where
    possible" requirement, applied to the one part of validation that can
    only happen once a file's bytes are actually read.
    """

    saved: List[_CreatedFloorFile] = []

    try:
        for upload_file, entry in zip(files, floor_entries):
            token = uuid.uuid4().hex
            try:
                path = await save_upload_to_temporary_file(
                    upload_file=upload_file,
                    map_id=token,
                )
            except ValueError as error:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Floor {entry.floor} ({entry.title}): {error}",
                ) from error

            saved.append(
                _CreatedFloorFile(
                    token=token,
                    path=path,
                    entry=entry,
                    content_type=upload_file.content_type
                    or "application/octet-stream",
                    filename=upload_file.filename or "uploaded-map",
                )
            )
    except Exception:
        for item in saved:
            delete_file_safely(item.path)
        raise

    return saved


async def _create_floor_maps(
    saved_files: List[_CreatedFloorFile],
    *,
    building_id: str,
    map_group_id: str,
) -> List[Map]:
    """
    Creates one Map document per floor. If any single insert fails, every
    Map already inserted in this call is deleted again and every saved
    file (for every floor in this batch, including ones whose Map insert
    never even ran yet) is removed — an initial multi-floor upload is
    all-or-nothing, exactly as the task requires.

    LOCAL UPLOAD DURABILITY FIX (source-file bug): each floor's exact
    original bytes are also copied into the durable ORIGINALS_DIR and
    recorded on Map.analysis_source_path synchronously here, before this
    request returns and before _schedule_processing() hands the floor to
    the background task. Identical reasoning to the single-map upload
    endpoint (see routes/map_routes.py's upload_map) — without it, a
    multi-floor upload reports success while no durable, analysis-readable
    file exists for any floor yet, and a background task that never
    completes leaves every floor's semantic analysis failing with "No
    source file could be located on disk". A failure here raises and is
    handled by the same all-or-nothing rollback below, so a floor whose
    file cannot be durably saved never leaves a half-created group behind.
    """

    created: List[Map] = []

    try:
        for item in saved_files:
            new_map = Map(
                title=item.entry.title.strip(),
                building_id=building_id,
                map_group_id=map_group_id,
                floor=item.entry.floor,
                floor_label=clean_optional_text(item.entry.floor_label),
                source_filename=item.filename,
                source_content_type=item.content_type,
                processing_status="pending",
                processing_progress=0,
                scale=item.entry.scale,
                is_current=False,
                is_current_for_floor=True,
            )
            await new_map.insert()
            created.append(new_map)

            try:
                preserved_original_path = preserve_original_source_file(
                    str(new_map.id), item.path
                )
            except Exception:
                preserved_original_path = None

            if (
                preserved_original_path is None
                or not preserved_original_path.exists()
                or preserved_original_path.stat().st_size == 0
            ):
                # Raised as a plain error, not an HTTPException, so both
                # callers' existing rollback-and-wrap handlers turn it into
                # one clean 500 instead of nesting an HTTPException inside
                # another one's detail string.
                raise RuntimeError(
                    f"floor {item.entry.floor} ({item.entry.title}) could "
                    "not be durably saved to local storage "
                    "(backend/uploads/maps/originals) — check that the "
                    "backend process has write access to that directory"
                )

            new_map.analysis_source_path = to_storage_relative_path(
                preserved_original_path
            )

            new_map.analysis_source_type = (
                "original_pdf"
                if preserved_original_path.suffix.lower() == ".pdf"
                else "original_image"
            )

            new_map.updated_at = datetime.utcnow()

            await new_map.save()
    except Exception:
        for m in created:
            try:
                await m.delete()
            except Exception:
                pass
        for item in saved_files:
            delete_file_safely(item.path)
        raise

    return created


def _schedule_processing(
    background_tasks: BackgroundTasks,
    saved_files: List[_CreatedFloorFile],
    created_maps: List[Map],
) -> None:
    for item, map_item in zip(saved_files, created_maps):
        background_tasks.add_task(
            process_map_in_background,
            str(map_item.id),
            str(item.path),
            item.entry.use_openai,
            item.entry.auto_generate_graph,
        )


# ---------------------------------------------------------
# Create group + initial floors (all-or-nothing)
# ---------------------------------------------------------

@router.post(
    "",
    response_model=MapGroupResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_map_group(
    background_tasks: BackgroundTasks,
    files: List[UploadFile] = File(...),
    floors_json: str = Form(...),
    name: str = Form(...),
    code: Optional[str] = Form(default=None),
    building_id: Optional[str] = Form(default=None),
    campus: Optional[str] = Form(default=None),
    address: Optional[str] = Form(default=None),
    description: Optional[str] = Form(default=None),
    _admin: User = Depends(require_global_admin),
):
    cleaned_name = name.strip()
    if len(cleaned_name) < 2:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Map group name must contain at least 2 characters.",
        )

    floor_entries = parse_floors_json(floors_json)

    if len(files) != len(floor_entries):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Received {len(files)} file(s) but {len(floor_entries)} "
                "floor entr(y/ies) — each floor needs exactly one file."
            ),
        )

    # Validate everything that doesn't require touching disk/DB first.
    validate_no_duplicate_floors(floor_entries, existing_floor_numbers=set())

    resolved_code = await resolve_group_code(cleaned_name, code)
    resolved_building_id = await resolve_map_building_id(
        building_id, campus, cleaned_name
    )

    saved_files = await _save_floor_files(files, floor_entries)

    new_group = MapGroup(
        building_id=resolved_building_id,
        name=cleaned_name,
        code=resolved_code,
        description=clean_optional_text(description),
        campus=clean_optional_text(campus),
        address=clean_optional_text(address),
    )

    try:
        await new_group.insert()
    except Exception as error:
        for item in saved_files:
            delete_file_safely(item.path)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Could not create the map group: {error}",
        ) from error

    try:
        created_maps = await _create_floor_maps(
            saved_files,
            building_id=resolved_building_id,
            map_group_id=str(new_group.id),
        )
    except Exception as error:
        # Whole-group rollback: this is the INITIAL creation of the group,
        # so a failure here must never leave a half-created, floor-less (or
        # partially-floored) group behind.
        await new_group.delete()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Could not create the floor maps: {error}",
        ) from error

    _schedule_processing(background_tasks, saved_files, created_maps)

    return await group_to_response(new_group)


# ---------------------------------------------------------
# Add floor(s) to an existing group
# ---------------------------------------------------------

@router.post(
    "/{group_id}/floors",
    response_model=MapGroupResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_floors_to_map_group(
    group_id: str,
    background_tasks: BackgroundTasks,
    files: List[UploadFile] = File(...),
    floors_json: str = Form(...),
    _admin: User = Depends(require_global_admin),
):
    group = await _load_group_or_404(group_id)

    floor_entries = parse_floors_json(floors_json)

    if len(files) != len(floor_entries):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Received {len(files)} file(s) but {len(floor_entries)} "
                "floor entr(y/ies) — each floor needs exactly one file."
            ),
        )

    existing_floor_numbers = await _existing_floor_numbers(str(group.id))
    validate_no_duplicate_floors(floor_entries, existing_floor_numbers)

    saved_files = await _save_floor_files(files, floor_entries)

    try:
        created_maps = await _create_floor_maps(
            saved_files,
            building_id=group.building_id,
            map_group_id=str(group.id),
        )
    except Exception as error:
        # Adding floors to an EXISTING group must never touch the group
        # itself or any floor it already had — only the new floor(s) from
        # this call are rolled back (already handled inside
        # _create_floor_maps), the group document is never deleted here.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Could not add the new floor(s): {error}",
        ) from error

    _schedule_processing(background_tasks, saved_files, created_maps)

    group.updated_at = datetime.utcnow()
    await group.save()

    return await group_to_response(group)


# ---------------------------------------------------------
# List / get
# ---------------------------------------------------------

@router.get(
    "",
    response_model=List[MapGroupResponse],
)
async def get_all_map_groups(
    building_id: Optional[str] = None,
):
    query = {}
    if building_id:
        query["building_id"] = building_id

    groups = await MapGroup.find(query).to_list()
    return [await group_to_response(group) for group in groups]


@router.get(
    "/{group_id}",
    response_model=MapGroupResponse,
)
async def get_map_group_by_id(group_id: str):
    group = await _load_group_or_404(group_id)
    return await group_to_response(group)


# ---------------------------------------------------------
# Admin multi-floor graph validation (PHASE 15) — a read-only report an
# admin runs before trusting this group for real navigation. Never
# mutates anything; safe to call as often as needed while configuring
# corridors/connectors.
# ---------------------------------------------------------

@router.get(
    "/{group_id}/validate-navigation",
)
async def validate_map_group_navigation(
    group_id: str,
    _admin: User = Depends(require_global_admin),
):
    group = await _load_group_or_404(group_id)
    result = await validate_multi_floor_navigation(group)
    return result.to_dict()


# ---------------------------------------------------------
# Edit group metadata (code is immutable)
# ---------------------------------------------------------

class MapGroupUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=2)
    campus: Optional[str] = None
    address: Optional[str] = None
    description: Optional[str] = None


@router.put(
    "/{group_id}",
    response_model=MapGroupResponse,
)
async def update_map_group(
    group_id: str,
    update_data: MapGroupUpdate,
    _admin: User = Depends(require_global_admin),
):
    group = await _load_group_or_404(group_id)

    payload = update_data.model_dump(exclude_unset=True)

    if "name" in payload:
        group.name = payload["name"].strip()
    for optional_field in ("campus", "address", "description"):
        if optional_field in payload:
            setattr(group, optional_field, clean_optional_text(payload[optional_field]))

    group.updated_at = datetime.utcnow()
    await group.save()

    return await group_to_response(group)


# ---------------------------------------------------------
# Delete one floor (group and other floors untouched)
# ---------------------------------------------------------

@router.delete(
    "/{group_id}/floors/{map_id}",
    status_code=status.HTTP_200_OK,
)
async def delete_map_group_floor(
    group_id: str,
    map_id: PydanticObjectId,
    _admin: User = Depends(require_global_admin),
):
    group = await _load_group_or_404(group_id)

    map_item = await Map.get(map_id)
    if not map_item or map_item.map_group_id != str(group.id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="This floor does not belong to the given map group.",
        )

    map_id_str = str(map_id)
    cascade_summary = await cascade_delete_map_graph(map_id_str)
    await map_item.delete()
    remove_map_files(map_id_str)

    group.updated_at = datetime.utcnow()
    await group.save()

    return {
        "message": "Floor deleted successfully",
        "map_group_id": str(group.id),
        **cascade_summary,
    }


# ---------------------------------------------------------
# Delete the whole group (explicit cascade to every floor)
# ---------------------------------------------------------

@router.delete(
    "/{group_id}",
    status_code=status.HTTP_200_OK,
)
async def delete_map_group(
    group_id: str,
    _admin: User = Depends(require_global_admin),
):
    group = await _load_group_or_404(group_id)

    floor_maps = await Map.find(Map.map_group_id == str(group.id)).to_list()

    deleted_floor_count = 0
    totals = {"deleted_edges": 0, "deleted_points": 0, "deleted_location_codes": 0}

    for map_item in floor_maps:
        map_id_str = str(map_item.id)
        cascade_summary = await cascade_delete_map_graph(map_id_str)
        for key in totals:
            totals[key] += cascade_summary.get(key, 0)
        await map_item.delete()
        remove_map_files(map_id_str)
        deleted_floor_count += 1

    await group.delete()

    return {
        "message": "Map group and all its floors deleted successfully",
        "deleted_floor_count": deleted_floor_count,
        **totals,
    }
