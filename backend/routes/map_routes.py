from __future__ import annotations

import asyncio
import math
import shutil
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

from core.auth_deps import (
    get_current_user,
    get_current_user_optional,
    require_global_admin,
    require_any_admin,
    user_can_manage_building,
    user_can_access_building,
    user_can_access_map,
)
from core.errors import FORBIDDEN_ROLE, FORBIDDEN_BUILDING_SCOPE, FORBIDDEN_MAP_SCOPE
from models.building_model import Building
from models.map_model import Map
from models.user_model import User
from schemas.map_schema import (
    MapCreate,
    MapProcessingResponse,
    MapResponse,
    MapUpdate,
    MapCalibrateRequest,
    MapCalibrationResponse,
    CopyCalibrationRequest,
    OcrSuggestRequest,
    OcrSuggestResponse,
    GraphGenerationPreviewResponse,
    GraphGenerationApplyRequest,
    GraphGenerationApplyResponse,
    GeneratedGraphCleanupPreviewResponse,
    GeneratedGraphCleanupApplyRequest,
    GeneratedGraphCleanupApplyResponse,
)
from routes.route_edge_routes import recalculate_walkway_edges_for_map
from services.building_service import find_or_create_building
from services.graph_generation_service import (
    generate_and_apply_walkable_graph,
    extract_walkable_graph,
    preview_generated_graph_cleanup,
    apply_generated_graph_cleanup,
    MIN_CONFIDENCE_TO_APPLY,
    _clear_previous_auto_generated_graph,
)
from services.ocr_service import suggest_destination_name
from services.map_image_service import (
    DISPLAY_DIR,
    SOURCE_DIR,
    TEMP_DIR,
    delete_file_safely,
    preserve_original_source_file,
    process_uploaded_map,
    save_upload_to_temporary_file,
    to_storage_relative_path,
)
from services.semantic_analysis_service import (
    enqueue_analysis_for_map,
    get_auto_analyze_enabled,
)
from services.storage_backend import (
    delete_generated_file,
    ensure_generated_file_local,
    resolve_generated_file_url,
    sync_generated_file,
)
from models.route_edge_model import RouteEdge
from models.route_point_model import RoutePoint
from models.location_code_model import LocationCode
from models.map_group_model import MapGroup
from models.room_model import Room


router = APIRouter(
    prefix="/api/maps",
    tags=["Map Management"],
)


# ---------------------------------------------------------
# Helpers
# ---------------------------------------------------------

def _require_map_scope(admin: User, map_item: Map) -> None:
    """RBAC/dashboard cleanup task, Phase 2: shared scope check for every
    single-map admin endpoint below (preview/generate-graph, cleanup
    preview/apply, clear-generated-graph, update/delete/calibrate/copy-
    calibration/retry-processing). super_admin/global_manager-with-scope
    pass via user_can_access_map(); a building_manager (or a global_manager
    now correctly restricted to specific building_ids — see auth_deps.py's
    module docstring) outside this map's building/map-group/map scope gets
    403, never a silent pass-through."""
    if not user_can_access_map(admin, map_item):
        raise HTTPException(**FORBIDDEN_MAP_SCOPE)


def clean_optional_text(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None

    cleaned_value = value.strip()
    return cleaned_value if cleaned_value else None


async def resolve_map_building_id(
    explicit_building_id: Optional[str],
    campus: Optional[str],
    title: str,
) -> str:
    """
    Priority 1 building resolution for a map being created:
    1. An admin-selected building_id — validated to actually exist.
    2. Otherwise, find-or-create a building from campus (preferred, since
       it is meant to describe the physical site) or the map title.
    """

    if explicit_building_id:
        building = await Building.get(PydanticObjectId(explicit_building_id))

        if not building:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Building not found",
            )

        return str(building.id)

    building_name = clean_optional_text(campus) or title
    building = await find_or_create_building(
        building_name,
        campus=clean_optional_text(campus),
    )

    return str(building.id)


async def resolve_map_group_code(map_group_id: Optional[str]) -> Optional[str]:
    """
    Looks up a single MapGroup's code by id — used when a caller needs
    exactly one map's response (get_map_by_id, upload, create). Listing
    routes that return many maps use `build_group_code_cache` below
    instead, to avoid one query per map.
    """

    if not map_group_id:
        return None

    try:
        group = await MapGroup.get(PydanticObjectId(map_group_id))
    except Exception:
        return None

    return group.code if group else None


async def build_group_code_cache(map_items: list[Map]) -> dict:
    """
    One query for every distinct map_group_id present in `map_items`,
    instead of one query per map — used by get_all_maps() and any other
    route returning a list of maps that may span several (or no) groups.
    """

    group_ids = {
        map_item.map_group_id
        for map_item in map_items
        if map_item.map_group_id
    }

    if not group_ids:
        return {}

    try:
        object_ids = [PydanticObjectId(gid) for gid in group_ids]
    except Exception:
        object_ids = []

    if not object_ids:
        return {}

    groups = await MapGroup.find({"_id": {"$in": object_ids}}).to_list()
    return {str(group.id): group.code for group in groups}


def map_to_response(
    map_item: Map,
    *,
    map_group_code: Optional[str] = None,
) -> MapResponse:
    return _build_map_response(MapResponse, map_item, map_group_code=map_group_code)


def _build_map_response(
    response_cls,
    map_item: Map,
    *,
    map_group_code: Optional[str] = None,
    **extra_fields,
):
    source_image_url = resolve_generated_file_url(
        map_item.source_image_url
    )

    display_image_url = resolve_generated_file_url(
        map_item.display_image_url
    )

    if map_item.image_url == map_item.display_image_url:
        image_url = display_image_url
    elif map_item.image_url == map_item.source_image_url:
        image_url = source_image_url
    else:
        image_url = resolve_generated_file_url(
            map_item.image_url
        )

    return response_cls(
        id=str(map_item.id),
        title=map_item.title,
        campus=map_item.campus,
        address=map_item.address,
        description=map_item.description,
        building_id=map_item.building_id,
        floor=map_item.floor,
        floor_label=map_item.floor_label,
        map_group_id=map_item.map_group_id,
        map_group_code=map_group_code,

        image_url=image_url,
        source_image_url=source_image_url,
        display_image_url=display_image_url,

        source_filename=map_item.source_filename,
        source_content_type=map_item.source_content_type,

        processing_status=map_item.processing_status,
        processing_progress=map_item.processing_progress,
        processing_error=map_item.processing_error,
        generation_method=map_item.generation_method,

        source_width=map_item.source_width,
        source_height=map_item.source_height,
        display_width=map_item.display_width,
        display_height=map_item.display_height,

        scale=map_item.scale,
        floor_scales=map_item.floor_scales,
        is_calibrated=map_item.is_calibrated,
        calibrated_at=map_item.calibrated_at,
        calibration_source=map_item.calibration_source,

        is_current=map_item.is_current,
        is_current_for_floor=map_item.is_current_for_floor,

        graph_generation_status=map_item.graph_generation_status,
        graph_generation_confidence=map_item.graph_generation_confidence,
        graph_generation_note=map_item.graph_generation_note,
        graph_generated_at=map_item.graph_generated_at,

        processed_at=map_item.processed_at,
        created_at=map_item.created_at,
        updated_at=map_item.updated_at,
        **extra_fields,
    )


def map_to_calibration_response(
    map_item: Map,
    *,
    edges_recalculated: int,
    edges_recalculation_skipped: int,
) -> MapCalibrationResponse:
    """
    Used only by the two calibration endpoints below — an additive-only
    sibling of map_to_response() that also reports the walkway-edge
    recalculation summary (requirement 6). Every other Map endpoint keeps
    calling plain map_to_response()/MapResponse, completely unaffected.
    """

    return _build_map_response(
        MapCalibrationResponse,
        map_item,
        edges_recalculated=edges_recalculated,
        edges_recalculation_skipped=edges_recalculation_skipped,
    )


def map_to_processing_response(
    map_item: Map,
) -> MapProcessingResponse:
    return MapProcessingResponse(
        id=str(map_item.id),
        processing_status=map_item.processing_status,
        processing_progress=map_item.processing_progress,
        processing_error=map_item.processing_error,
        generation_method=map_item.generation_method,
        source_image_url=resolve_generated_file_url(
            map_item.source_image_url
        ),
        display_image_url=resolve_generated_file_url(
            map_item.display_image_url
        ),
        processed_at=map_item.processed_at,
    )


async def set_map_as_current(map_item: Map) -> None:
    """
    Make this map current and deactivate all other current maps.
    """

    await Map.find(
        Map.is_current == True
    ).update(
        {
            "$set": {
                "is_current": False,
            }
        }
    )

    map_item.is_current = True
    map_item.updated_at = datetime.utcnow()

    await map_item.save()


def remove_map_files(map_id: str) -> None:
    """
    Delete generated source, display and temporary files (local disk and,
    if configured, their S3 copies).
    """

    delete_file_safely(
        SOURCE_DIR / f"{map_id}.png"
    )

    delete_file_safely(
        DISPLAY_DIR / f"{map_id}.png"
    )

    delete_generated_file(f"/uploads/maps/source/{map_id}.png")
    delete_generated_file(f"/uploads/maps/display/{map_id}.png")

    for temporary_file in TEMP_DIR.glob(
        f"{map_id}_*"
    ):
        delete_file_safely(temporary_file)


async def cascade_delete_map_graph(map_id: str) -> dict:
    """
    Remove every RouteEdge, RoutePoint and LocationCode that belongs to a
    map being deleted, so deleting a map never leaves orphaned navigation
    graph documents behind. Edges are removed before points because edges
    reference point IDs.

    A cross-floor VerticalConnector transition edge is stored with
    map_id = the FROM point's map and to_map_id = the TO point's (other
    floor's) map (see models/route_edge_model.py). Deleting only edges
    whose `map_id` equals this map would leave a transition edge intact
    whenever THIS map is the destination side of that edge — an orphaned
    edge referencing a to_point_id on a map that no longer exists. Both
    queries together ensure a transition edge is removed no matter which
    of its two floors is deleted, without ever touching an edge that
    belongs entirely to a different, unrelated map.
    """

    deleted_edges = await RouteEdge.find(
        {"$or": [{"map_id": map_id}, {"to_map_id": map_id}]}
    ).delete()

    deleted_location_codes = await LocationCode.find(
        LocationCode.map_id == map_id
    ).delete()

    deleted_points = await RoutePoint.find(
        RoutePoint.map_id == map_id
    ).delete()

    return {
        "deleted_edges": (
            deleted_edges.deleted_count if deleted_edges else 0
        ),
        "deleted_points": (
            deleted_points.deleted_count if deleted_points else 0
        ),
        "deleted_location_codes": (
            deleted_location_codes.deleted_count
            if deleted_location_codes
            else 0
        ),
    }


# ---------------------------------------------------------
# Background map processing
# ---------------------------------------------------------

async def process_map_in_background(
    map_id: str,
    uploaded_path_string: str,
    use_openai: bool,
    auto_generate_graph: bool = False,
) -> None:
    """
    Process the uploaded map after the upload endpoint responds.

    The CPU-heavy image processing runs in another thread so it
    does not block the FastAPI event loop.
    """

    uploaded_path = Path(uploaded_path_string)

    try:
        map_item = await Map.get(
            PydanticObjectId(map_id)
        )

        if not map_item:
            delete_file_safely(uploaded_path)
            return

        map_item.processing_status = "processing"
        map_item.processing_progress = 15
        map_item.processing_error = None
        map_item.updated_at = datetime.utcnow()

        await map_item.save()

        # Best-effort, purely additive: preserve the exact original
        # uploaded bytes (before any PDF-first-page flattening) so a
        # later semantic-analysis job can inspect a PDF's real, un-
        # flattened pages instead of only the single normalized PNG this
        # pipeline has always produced. Never affects map processing
        # itself — a failure here is silently ignored and handled below
        # by persisting the normalized-PNG fallback instead.
        preserved_original_path = None
        try:
            preserved_original_path = preserve_original_source_file(
                map_id, uploaded_path
            )
        except Exception:
            preserved_original_path = None

        result = await asyncio.to_thread(
            process_uploaded_map,
            uploaded_path,
            map_id,
            use_openai,
        )

        # Read the map again in case it was deleted while processing.
        map_item = await Map.get(
            PydanticObjectId(map_id)
        )

        if not map_item:
            remove_map_files(map_id)
            return

        # Local disk always has the authoritative copy already; this only
        # additionally uploads to S3 and swaps in the S3 URL when
        # MAP_STORAGE_BACKEND=s3 is configured. No-op (returns the same
        # local URL) otherwise, so default local-disk behavior is unchanged.
        map_item.source_image_url = sync_generated_file(
            result.source_path, result.source_url
        )
        map_item.display_image_url = sync_generated_file(
            result.display_path, result.display_url
        )

        # Keep the old image field working with old frontend code.
        map_item.image_url = map_item.display_image_url

        map_item.source_width = result.source_width
        map_item.source_height = result.source_height

        map_item.display_width = result.display_width
        map_item.display_height = result.display_height

        map_item.generation_method = (
            result.generation_method
        )

        map_item.processing_status = "completed"
        map_item.processing_progress = 100
        map_item.processing_error = None

        map_item.processed_at = datetime.utcnow()
        map_item.updated_at = datetime.utcnow()

        # Source-file path bug fix: persist an explicit, reliable pointer
        # to the physical file semantic analysis must read for THIS map,
        # instead of leaving every future reader to re-derive it by
        # filename convention. Prefer the true preserved original (any
        # page count, full quality); fall back to the normalized
        # full-resolution SOURCE_DIR PNG (never a thumbnail — this is the
        # same accurate file the admin sees) only when preservation
        # failed. Setting this field is unconditional here — every map
        # that finishes processing successfully gets a resolvable
        # analysis source, never left blank.
        if preserved_original_path and preserved_original_path.exists():
            map_item.analysis_source_path = to_storage_relative_path(
                preserved_original_path
            )
            map_item.analysis_source_type = (
                "original_pdf"
                if preserved_original_path.suffix.lower() == ".pdf"
                else "original_image"
            )
        else:
            map_item.analysis_source_path = to_storage_relative_path(
                result.source_path
            )
            map_item.analysis_source_type = "rendered_source_png"

        await map_item.save()

        # Automatic semantic-map-analysis enqueue (Section 9). Fires only
        # after map processing has genuinely succeeded, gated by
        # AUTO_ANALYZE_MAPS, and NEVER waits for the AI provider — this
        # only ever creates a "queued" (or "configuration_required")
        # database record; the actual Anthropic/Claude call happens later,
        # out-of-band, in services/semantic_analysis_worker.py (the two
        # older references to OpenAI here were left over from before the
        # Anthropic migration and never described this branch's runtime;
        # OpenAI is used only by the unrelated cosmetic display-map recolor
        # in services/map_image_service.py). A failure here is caught and
        # ignored so it can never turn an otherwise-successful map
        # upload into a failure.
        if get_auto_analyze_enabled():
            try:
                from services.map_image_service import (
                    resolve_analysis_source_path as _resolve_analysis_source,
                )

                # Uses the exact same canonical resolver the manual
                # "Start Analysis" endpoint and the background worker both
                # use (see map_image_service.resolve_analysis_source_path)
                # — the fix for the original bug, where three independent,
                # convention-based lookups could silently disagree.
                resolved_source = _resolve_analysis_source(map_item)
                analysis_source_path = (
                    resolved_source.path if resolved_source else result.source_path
                )

                await enqueue_analysis_for_map(
                    map_id=map_id,
                    building_id=map_item.building_id,
                    map_group_id=map_item.map_group_id,
                    source_path=analysis_source_path,
                    source_filename=(
                        map_item.source_filename or f"{map_id}.png"
                    ),
                    created_by=None,
                )
            except Exception as analysis_error:
                print(
                    "Could not enqueue semantic analysis for map "
                    f"{map_id}:",
                    str(analysis_error),
                )

        # SAFETY FIX (navigation-data cleanup task): walkable-graph
        # generation must NEVER be applied automatically — it used to run
        # here unconditionally whenever the upload form's "auto-generate"
        # checkbox was left checked (its default), silently writing
        # dozens/hundreds of "Auto Point N" RoutePoints and RouteEdges
        # (including points outside the building, in title-block/metadata
        # regions, and inaccurate long edges) with no admin review at all.
        # Graph generation is now an explicit, separate admin workflow:
        # POST /{map_id}/generate-graph/preview (read-only, no writes) must
        # be reviewed first, then POST /{map_id}/generate-graph (now
        # requires confirm=true in the request body) actually writes.
        # `auto_generate_graph` is still accepted here (and still recorded
        # on the request) for backward API compatibility with existing
        # callers/tests, but it no longer triggers ANY automatic write —
        # this parameter is intentionally inert now. Manual Draw Walkable
        # Path, and the new explicit preview/confirm workflow, remain the
        # only ways a walkable graph is ever created for a map.
        if auto_generate_graph:
            map_item.graph_generation_status = "pending_manual_preview"
            map_item.graph_generation_note = (
                "Automatic graph generation is no longer applied on "
                "upload. Open Generate Route Graph to preview and "
                "explicitly confirm a proposed graph for this map."
            )
            map_item.graph_generated_at = datetime.utcnow()
            await map_item.save()

    except Exception as error:
        try:
            failed_map = await Map.get(
                PydanticObjectId(map_id)
            )

            if failed_map:
                failed_map.processing_status = "failed"
                failed_map.processing_progress = 0
                failed_map.processing_error = str(error)
                failed_map.updated_at = datetime.utcnow()

                await failed_map.save()

        except Exception as database_error:
            print(
                "Could not save map processing failure:",
                str(database_error),
            )

        print(
            f"Map processing failed for map {map_id}:",
            str(error),
        )

    finally:
        delete_file_safely(uploaded_path)


# ---------------------------------------------------------
# Normal JSON map creation
# ---------------------------------------------------------

@router.post(
    "",
    response_model=MapResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_map(
    map_data: MapCreate,
    admin: User = Depends(require_any_admin),
):
    # RBAC/dashboard cleanup task, Phase 2: building_manager may now reach
    # this endpoint (previously require_global_admin blocked them
    # entirely), but only when an explicit building_id they're authorized
    # for is supplied — a building_manager can never rely on the auto-
    # create-a-building-from-title/campus fallback below, since that could
    # silently create a brand-new Building outside any scope at all.
    if admin.role == "building_manager":
        if not map_data.building_id:
            raise HTTPException(
                status_code=400,
                detail="building_id is required for this role",
            )
        if not user_can_access_building(admin, map_data.building_id):
            raise HTTPException(**FORBIDDEN_BUILDING_SCOPE)

    legacy_image_url = (
        map_data.image_url
        or map_data.display_image_url
        or map_data.source_image_url
    )

    already_has_display_image = bool(
        map_data.display_image_url
    )

    cleaned_title = map_data.title.strip()

    resolved_building_id = await resolve_map_building_id(
        map_data.building_id,
        map_data.campus,
        cleaned_title,
    )

    new_map = Map(
        title=cleaned_title,
        campus=clean_optional_text(
            map_data.campus
        ),
        address=clean_optional_text(
            map_data.address
        ),
        description=clean_optional_text(
            map_data.description
        ),
        building_id=resolved_building_id,
        floor=map_data.floor,

        image_url=legacy_image_url,
        source_image_url=map_data.source_image_url,
        display_image_url=map_data.display_image_url,

        processing_status=(
            "completed"
            if already_has_display_image
            else "not_started"
        ),
        processing_progress=(
            100
            if already_has_display_image
            else 0
        ),
        processed_at=(
            datetime.utcnow()
            if already_has_display_image
            else None
        ),

        scale=map_data.scale,
        floor_scales=map_data.floor_scales,

        is_current=False,
    )

    await new_map.insert()
    await set_map_as_current(new_map)

    return map_to_response(new_map)


# ---------------------------------------------------------
# Upload PDF/image and automatically process it
# Important: this route must be before /{map_id}
# ---------------------------------------------------------

@router.post(
    "/upload",
    response_model=MapResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_map(
    background_tasks: BackgroundTasks,

    file: UploadFile = File(...),

    title: str = Form(...),
    campus: Optional[str] = Form(default=None),
    address: Optional[str] = Form(default=None),
    description: Optional[str] = Form(default=None),

    # Admin-selected building, or leave unset to auto-create/reuse one
    # from campus/title (see resolve_map_building_id above).
    building_id: Optional[str] = Form(default=None),
    floor: Optional[int] = Form(default=None),

    scale: float = Form(default=1.0, gt=0),

    # True means:
    # try OpenAI when an API key exists.
    # Otherwise local processing is used automatically.
    use_openai: bool = Form(default=True),

    # DEPRECATED (navigation-data cleanup task): this flag no longer
    # triggers ANY automatic RoutePoint/RouteEdge write — see
    # process_map_in_background above. Still accepted for backward
    # compatibility with existing callers/tests; default changed to False
    # since it is now inert either way. Use the explicit
    # POST /{map_id}/generate-graph/preview then
    # POST /{map_id}/generate-graph (confirm=true) workflow instead.
    auto_generate_graph: bool = Form(default=False),

    admin: User = Depends(require_any_admin),
):
    # Same building_manager restriction as create_map() above — an
    # explicit, authorized building_id is required; the auto-create/reuse
    # fallback (resolve_map_building_id via campus/title) stays available
    # only to super_admin/global_manager.
    if admin.role == "building_manager":
        if not building_id:
            raise HTTPException(
                status_code=400,
                detail="building_id is required for this role",
            )
        if not user_can_access_building(admin, building_id):
            raise HTTPException(**FORBIDDEN_BUILDING_SCOPE)

    cleaned_title = title.strip()

    if len(cleaned_title) < 2:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Map title must contain at least "
                "2 characters."
            ),
        )

    source_filename = (
        file.filename or "uploaded-map"
    )

    source_content_type = (
        file.content_type
        or "application/octet-stream"
    )

    # Temporary token is used before MongoDB creates the map ID.
    upload_token = uuid.uuid4().hex

    try:
        uploaded_path = (
            await save_upload_to_temporary_file(
                upload_file=file,
                map_id=upload_token,
            )
        )

    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(error),
        ) from error

    except Exception as error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=(
                f"Could not save the uploaded map: {error}"
            ),
        ) from error

    try:
        resolved_building_id = await resolve_map_building_id(
            building_id,
            campus,
            cleaned_title,
        )

        new_map = Map(
            title=cleaned_title,
            campus=clean_optional_text(campus),
            address=clean_optional_text(address),
            description=clean_optional_text(
                description
            ),
            building_id=resolved_building_id,
            floor=floor,

            image_url=None,
            source_image_url=None,
            display_image_url=None,

            source_filename=source_filename,
            source_content_type=source_content_type,

            processing_status="pending",
            processing_progress=0,
            processing_error=None,
            generation_method=None,

            source_width=None,
            source_height=None,
            display_width=None,
            display_height=None,

            scale=scale,
            floor_scales={},

            is_current=False,
        )

        await new_map.insert()
        await set_map_as_current(new_map)

    except HTTPException:
        delete_file_safely(uploaded_path)
        raise

    except Exception as error:
        delete_file_safely(uploaded_path)

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=(
                f"Could not create the map record: {error}"
            ),
        ) from error

    # LOCAL UPLOAD DURABILITY FIX (source-file bug).
    #
    # Until now, the ONLY place that produced a durable, analysis-readable
    # file for this map was process_map_in_background() below — a Starlette
    # BackgroundTasks callback that runs AFTER this response has already
    # been sent. That meant this endpoint answered "Map uploaded
    # successfully" (HTTP 201) at a moment when zero durable files existed
    # on disk and Map.analysis_source_path was still None. If that
    # background callback never ran to completion — the dev server
    # reloading mid-write, the process being restarted or killed, or any
    # unrelated processing error raised before its own persistence step —
    # the Map record survived pointing at nothing, and semantic analysis
    # (auto-enqueued or started manually) later failed with "No source file
    # could be located on disk for this analysis (the Map's uploaded file
    # may have been removed)" even though the API had already reported
    # success.
    #
    # The fix: copy the uploaded file's exact original bytes into the
    # existing durable ORIGINALS_DIR (backend/uploads/maps/originals — an
    # absolute Path(__file__)-derived location, never CWD-relative)
    # synchronously, inside this request, BEFORE returning. This is a plain
    # local file copy: no PDF rendering, no OpenCV, no OpenAI call, so it
    # costs one file copy (bounded by MAP_MAX_UPLOAD_SIZE_MB) while all the
    # heavy image work legitimately stays in the background task below.
    # Success is only ever reported once the durable file is proven to
    # exist on disk with real content.
    #
    # process_map_in_background() still runs unchanged afterwards and still
    # writes analysis_source_path itself; for a successfully preserved
    # original it simply re-persists the identical value, so nothing about
    # the happy path changes. This only removes the window in which no
    # durable source existed at all.
    try:
        preserved_original_path = preserve_original_source_file(
            str(new_map.id), uploaded_path
        )
    except Exception:
        preserved_original_path = None

    if (
        preserved_original_path is None
        or not preserved_original_path.exists()
        or preserved_original_path.stat().st_size == 0
    ):
        # Persistence genuinely failed — never leave behind a Map record
        # that points at a nonexistent local file, and never report
        # success.
        delete_file_safely(uploaded_path)

        try:
            await new_map.delete()
        except Exception:
            pass

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=(
                "The uploaded file could not be durably saved to local "
                "storage (backend/uploads/maps/originals). Upload aborted "
                "— no Map record was left behind. Check that the backend "
                "process has write access to that directory and try again."
            ),
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

    background_tasks.add_task(
        process_map_in_background,
        str(new_map.id),
        str(uploaded_path),
        use_openai,
        auto_generate_graph,
    )

    return map_to_response(new_map)


# ---------------------------------------------------------
# Get all/current maps
# ---------------------------------------------------------

@router.get(
    "",
    response_model=List[MapResponse],
)
async def get_all_maps(admin: User = Depends(require_any_admin)):
    """
    Admin-only listing, narrowed to the caller's authorized scope.

    Before the admin dashboard scope-isolation task this endpoint had NO
    dependency at all and returned every Map in the database — including
    every other institution's floor plans, processing state and source
    paths — to any caller. Consumers were traced before adding the
    dependency: only admin screens list maps (AdminContext, AdminMapScreen,
    AdminRoomsScreen). The public/anonymous wayfinding flow resolves a
    single Map through GET /api/maps/{id}, which keeps its existing
    optional-auth contract, so end-user navigation is unaffected.

    Authentication is required rather than optional so a scoped manager
    cannot bypass their own scope by dropping the Authorization header.
    """

    maps = await Map.find_all().to_list()
    # Filtered in Python rather than in the query because map-level scope
    # is a precedence rule (map_ids > map_group_ids > building_ids) that
    # already has exactly one implementation in core/auth_deps.py — this
    # endpoint reuses it instead of re-expressing it as a Mongo filter.
    maps = [m for m in maps if user_can_access_map(admin, m)]
    group_codes = await build_group_code_cache(maps)

    return [
        map_to_response(
            map_item,
            map_group_code=group_codes.get(map_item.map_group_id),
        )
        for map_item in maps
    ]


@router.get(
    "/current",
    response_model=MapResponse,
)
async def get_current_map(
    user: Optional[User] = Depends(get_current_user_optional),
):
    current_map = await Map.find_one(
        Map.is_current == True
    )

    if not current_map:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No current map found",
        )

    # Scope isolation: an admin-tier caller must not be handed a map
    # outside their scope just because it happens to carry the legacy
    # collection-wide `is_current` flag. Anonymous callers and
    # regular_user keep the pre-existing public behavior exactly (this
    # endpoint predates admin scoping and is part of the kiosk-style
    # flow's contract), and the "no map for you" answer is the same 404
    # an empty collection produces, so no out-of-scope map's existence is
    # revealed.
    if (
        user is not None
        and user.role != "regular_user"
        and not user_can_access_map(user, current_map)
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No current map found",
        )

    return map_to_response(current_map)


# ---------------------------------------------------------
# Processing status
# Must also be before /{map_id}
# ---------------------------------------------------------

@router.get(
    "/{map_id}/processing-status",
    response_model=MapProcessingResponse,
)
async def get_map_processing_status(
    map_id: PydanticObjectId,
):
    map_item = await Map.get(map_id)

    if not map_item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Map not found",
        )

    return map_to_processing_response(map_item)


# ---------------------------------------------------------
# Retry processing
# ---------------------------------------------------------

@router.post(
    "/{map_id}/retry-processing",
    response_model=MapProcessingResponse,
)
async def retry_map_processing(
    map_id: PydanticObjectId,
    background_tasks: BackgroundTasks,
    use_openai: bool = True,
    auto_generate_graph: bool = False,
    admin: User = Depends(require_any_admin),
):
    map_item = await Map.get(map_id)

    if not map_item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Map not found",
        )

    _require_map_scope(admin, map_item)

    if map_item.processing_status in {
        "pending",
        "processing",
    }:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "This map is already being processed."
            ),
        )

    source_path = SOURCE_DIR / f"{map_id}.png"

    stored_source_url = (
        map_item.source_image_url
        or map_item.image_url
    )

    source_available = await asyncio.to_thread(
        ensure_generated_file_local,
        stored_source_url,
        source_path,
    )

    if not source_available:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "The original processed source image could not "
                "be restored from storage. Upload the map again."
            ),
        )

    retry_input_path = (
        TEMP_DIR / f"{map_id}_retry_input.png"
    )

    try:
        shutil.copyfile(
            source_path,
            retry_input_path,
        )

    except Exception as error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=(
                f"Could not prepare the map for retry: "
                f"{error}"
            ),
        ) from error

    map_item.processing_status = "pending"
    map_item.processing_progress = 0
    map_item.processing_error = None
    map_item.generation_method = None
    map_item.processed_at = None
    map_item.updated_at = datetime.utcnow()

    await map_item.save()

    background_tasks.add_task(
        process_map_in_background,
        str(map_item.id),
        str(retry_input_path),
        use_openai,
        auto_generate_graph,
    )

    return map_to_processing_response(map_item)


# ---------------------------------------------------------
# Explicit walkable-graph generation — preview (no writes) + confirm-gated
# apply (navigation-data cleanup task, Section 1.3). This is now the ONLY
# way a walkable graph is ever created for a map; process_map_in_
# background above no longer applies anything automatically.
# ---------------------------------------------------------

async def _resolve_map_source_path(map_item: Map) -> Path:
    if map_item.processing_status != "completed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "This map has not finished processing yet. Wait for "
                "processing to complete before generating a graph."
            ),
        )

    source_path = SOURCE_DIR / f"{map_item.id}.png"

    stored_source_url = map_item.source_image_url or map_item.image_url

    source_available = await asyncio.to_thread(
        ensure_generated_file_local,
        stored_source_url,
        source_path,
    )

    if not source_available:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "The processed source image could not be restored "
                "from storage."
            ),
        )

    return source_path


@router.post(
    "/{map_id}/generate-graph/preview",
    response_model=GraphGenerationPreviewResponse,
)
async def preview_map_graph(
    map_id: PydanticObjectId,
    admin: User = Depends(require_any_admin),
):
    """
    Step 2-4 of "Generate Route Graph" (Section 1.3): runs the exact same
    extraction the apply step uses, on this map's already-processed source
    image, and returns proposed nodes/edges for admin review. NEVER writes
    a RoutePoint, RouteEdge, or anything else to MongoDB — the only
    mutation on this map document itself is none at all.
    """

    map_item = await Map.get(map_id)

    if not map_item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Map not found",
        )

    _require_map_scope(admin, map_item)

    source_path = await _resolve_map_source_path(map_item)

    extraction = await asyncio.to_thread(extract_walkable_graph, source_path)

    return GraphGenerationPreviewResponse(
        map_id=str(map_id),
        nodes=[
            {"x": node.x, "y": node.y, "kind": node.kind}
            for node in extraction.nodes
        ],
        edges=[
            {
                "from_index": edge.from_index,
                "to_index": edge.to_index,
                "pixel_length": edge.pixel_length,
            }
            for edge in extraction.edges
        ],
        confidence=extraction.confidence,
        walkable_fraction=extraction.walkable_fraction,
        component_count=extraction.component_count,
        note=extraction.note,
        meets_confidence_threshold=extraction.confidence >= MIN_CONFIDENCE_TO_APPLY,
    )


@router.post(
    "/{map_id}/generate-graph",
    response_model=GraphGenerationApplyResponse,
)
async def generate_map_graph(
    map_id: PydanticObjectId,
    apply_request: GraphGenerationApplyRequest = GraphGenerationApplyRequest(),
    admin: User = Depends(require_any_admin),
):
    """
    Step 7-8 of "Generate Route Graph" (Section 1.3): writes RoutePoints/
    RouteEdges ONLY when `confirm: true` is explicitly sent in the request
    body — the admin must have already reviewed
    POST /{map_id}/generate-graph/preview. A request with confirm omitted
    or false performs no writes and returns 400, so an accidental or
    legacy call can never silently apply a graph. Safe to call repeatedly:
    each run clears only this map's previously auto-generated points/edges
    (never manual ones) before creating the new graph. A low-confidence
    result creates nothing and leaves any existing graph untouched.
    """

    if not apply_request.confirm:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Explicit confirmation is required. Call "
                "POST /{map_id}/generate-graph/preview first, review the "
                "proposed graph, then resend this request with "
                '{"confirm": true}.'
            ),
        )

    map_item = await Map.get(map_id)

    if not map_item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Map not found",
        )

    _require_map_scope(admin, map_item)

    source_path = await _resolve_map_source_path(map_item)

    outcome = await generate_and_apply_walkable_graph(map_item, source_path)

    refreshed = await Map.get(map_id)
    response_data = map_to_response(refreshed).model_dump()

    return GraphGenerationApplyResponse(
        **response_data,
        graph_applied=outcome.applied,
        graph_points_created=outcome.points_created,
        graph_edges_created=outcome.edges_created,
        graph_points_cleared=outcome.points_cleared,
        graph_edges_cleared=outcome.edges_cleared,
    )


@router.get(
    "/{map_id}/generate-graph/cleanup/preview",
    response_model=GeneratedGraphCleanupPreviewResponse,
)
async def preview_map_generated_graph_cleanup(
    map_id: PydanticObjectId,
    admin: User = Depends(require_any_admin),
):
    """
    "Preview Generated Graph Cleanup" (Section 1.6): read-only, scoped to
    this one map. Identifies only RoutePoints/RouteEdges that carry proof
    of being auto-generated (is_auto_generated=True). Never includes
    manual, semantic-destination, or vertical-connector records. Records
    that merely look legacy-generated by name but carry no provenance
    flag are reported separately (unknown_legacy_point_count) and are
    never proposed for deletion.
    """

    map_item = await Map.get(map_id)

    if not map_item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Map not found",
        )

    _require_map_scope(admin, map_item)

    preview = await preview_generated_graph_cleanup(str(map_id))
    return GeneratedGraphCleanupPreviewResponse(**preview)


@router.post(
    "/{map_id}/generate-graph/cleanup/apply",
    response_model=GeneratedGraphCleanupApplyResponse,
)
async def apply_map_generated_graph_cleanup(
    map_id: PydanticObjectId,
    cleanup_request: GeneratedGraphCleanupApplyRequest = GeneratedGraphCleanupApplyRequest(),
    admin: User = Depends(require_any_admin),
):
    """
    Deletes ONLY records proven auto-generated (is_auto_generated=True) on
    this one map — requires `confirm: true` in the request body, exactly
    mirroring the graph-generation apply endpoint's confirmation gate.
    Idempotent: calling this a second time finds nothing left to delete
    and returns zero counts, never an error.
    """

    if not cleanup_request.confirm:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Explicit confirmation is required. Call "
                "GET /{map_id}/generate-graph/cleanup/preview first, "
                "review the counts, then resend this request with "
                '{"confirm": true}.'
            ),
        )

    map_item = await Map.get(map_id)

    if not map_item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Map not found",
        )

    _require_map_scope(admin, map_item)

    result = await apply_generated_graph_cleanup(str(map_id))
    return GeneratedGraphCleanupApplyResponse(**result)


@router.delete(
    "/{map_id}/generated-graph",
    status_code=status.HTTP_200_OK,
)
async def clear_generated_map_graph(
    map_id: PydanticObjectId,
    admin: User = Depends(require_any_admin),
):
    """
    Removes only this map's auto-generated RoutePoints/RouteEdges —
    manually drawn/added points and edges (including manual edges that
    happen to touch a generated point) are never deleted by this.
    """

    map_item = await Map.get(map_id)

    if not map_item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Map not found",
        )

    _require_map_scope(admin, map_item)

    points_cleared, edges_cleared = await _clear_previous_auto_generated_graph(
        str(map_id), map_item.floor
    )

    map_item.graph_generation_status = "cleared"
    map_item.graph_generation_confidence = None
    map_item.graph_generation_note = (
        "Auto-generated graph cleared by an admin."
    )
    map_item.graph_generated_at = datetime.utcnow()

    await map_item.save()

    return {
        "message": "Auto-generated graph cleared",
        "points_cleared": points_cleared,
        "edges_cleared": edges_cleared,
    }


@router.post(
    "/{map_id}/ocr-suggest",
    response_model=OcrSuggestResponse,
)
async def ocr_suggest_destination_name(
    map_id: PydanticObjectId,
    request: OcrSuggestRequest,
    user: User = Depends(get_current_user),
):
    """
    Best-effort OCR name suggestion for the map-based destination
    placement flow (AdminRoomsScreen.jsx "Suggest Name from Map"). Crops a
    bounded region of this map's processed source image around
    (request.x, request.y) and runs local OCR on it.

    This NEVER creates, updates, or deletes anything — it only reads the
    map's source image file and returns a suggestion. The caller (admin)
    must confirm or edit the result before any Room/RoutePoint is saved.
    Gated the same way Room creation is (any admin-tier role that can
    manage this map's building) rather than global-admin-only, so a
    building_manager placing destinations in their own building can use
    it too.
    """

    if user.role == "regular_user":
        raise HTTPException(**FORBIDDEN_ROLE)

    map_item = await Map.get(map_id)

    if not map_item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Map not found",
        )

    if map_item.building_id and not user_can_manage_building(
        user, map_item.building_id
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to manage this building",
        )

    source_path = SOURCE_DIR / f"{map_id}.png"

    stored_source_url = (
        map_item.source_image_url
        or map_item.image_url
    )

    source_available = await asyncio.to_thread(
        ensure_generated_file_local,
        stored_source_url,
        source_path,
    )

    if not source_available:
        return OcrSuggestResponse(
            available=False,
            text="",
            confidence=0.0,
            low_confidence=True,
            reason=(
                "This map's processed source image could not "
                "be restored from storage."
            ),
        )

    kwargs = {}
    if request.width is not None:
        kwargs["crop_width"] = request.width
    if request.height is not None:
        kwargs["crop_height"] = request.height

    result = suggest_destination_name(
        str(map_id), request.x, request.y, **kwargs
    )

    return OcrSuggestResponse(
        available=result.available,
        text=result.text,
        confidence=result.confidence,
        low_confidence=result.low_confidence,
        reason=result.reason,
    )


# ---------------------------------------------------------
# Get map by ID
# ---------------------------------------------------------

@router.get(
    "/{map_id}",
    response_model=MapResponse,
)
async def get_map_by_id(
    map_id: PydanticObjectId,
    user: Optional[User] = Depends(get_current_user_optional),
):
    map_item = await Map.get(map_id)

    if not map_item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Map not found",
        )

    # RBAC/dashboard cleanup task, Phase 2: same optional-auth pattern as
    # route_point_routes.py's GET endpoints — this route is also called
    # unauthenticated by the public navigation flow
    # (NavigationRouteMap.jsx), so it must stay reachable with no login.
    # Only an authenticated, non-super_admin admin-tier caller is IDOR-
    # checked against their own scope.
    if user is not None and user.role not in ("regular_user", "super_admin"):
        if not user_can_access_map(user, map_item):
            raise HTTPException(**FORBIDDEN_MAP_SCOPE)

    group_code = await resolve_map_group_code(map_item.map_group_id)
    return map_to_response(map_item, map_group_code=group_code)


# ---------------------------------------------------------
# Update map
# ---------------------------------------------------------

@router.put(
    "/{map_id}",
    response_model=MapResponse,
)
async def update_map(
    map_id: PydanticObjectId,
    map_data: MapUpdate,
    admin: User = Depends(require_any_admin),
):
    map_item = await Map.get(map_id)

    if not map_item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Map not found",
        )

    _require_map_scope(admin, map_item)

    update_data = map_data.model_dump(
        exclude_unset=True
    )

    if "title" in update_data:
        update_data["title"] = (
            update_data["title"].strip()
        )

    for optional_field in [
        "campus",
        "address",
        "description",
    ]:
        if optional_field in update_data:
            update_data[optional_field] = (
                clean_optional_text(
                    update_data[optional_field]
                )
            )

    should_be_current = (
        update_data.pop(
            "is_current",
            None,
        )
    )

    # PHASE 17 — "changing a floor number" safety: reject a floor number
    # that would collide with a sibling floor already in this Map Group,
    # and cascade the new floor value onto every RoutePoint/Room that
    # denormalizes this map's floor — otherwise those records would
    # silently disagree with the map's own floor forever (PHASE 16:
    # "Room route_point_id matches Room map_id/floor").
    new_floor = update_data.get("floor")
    floor_is_changing = "floor" in update_data and new_floor != map_item.floor

    if floor_is_changing and map_item.map_group_id:
        sibling = await Map.find_one(
            {
                "map_group_id": map_item.map_group_id,
                "floor": new_floor,
                "_id": {"$ne": map_item.id},
            }
        )
        if sibling:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Floor {new_floor} is already used by another floor "
                    "in this map group."
                ),
            )

    for field, value in update_data.items():
        setattr(map_item, field, value)

    if floor_is_changing:
        map_id_str = str(map_item.id)
        await RoutePoint.find(RoutePoint.map_id == map_id_str).update(
            {"$set": {"floor": new_floor}}
        )
        await Room.find(Room.map_id == map_id_str).update(
            {"$set": {"floor": new_floor}}
        )

    # Keep compatibility with old frontend code.
    if (
        "display_image_url" in update_data
        and map_item.display_image_url
    ):
        map_item.image_url = (
            map_item.display_image_url
        )

    map_item.updated_at = datetime.utcnow()

    if should_be_current is True:
        await set_map_as_current(map_item)

    else:
        if should_be_current is False:
            map_item.is_current = False

        await map_item.save()

    return map_to_response(map_item)


# ---------------------------------------------------------
# Scale calibration (PHASE 8)
# ---------------------------------------------------------

@router.post(
    "/{map_id}/calibrate-scale",
    response_model=MapCalibrationResponse,
)
async def calibrate_map_scale(
    map_id: PydanticObjectId,
    data: MapCalibrateRequest,
    admin: User = Depends(require_any_admin),
):
    """
    Two-click calibration: the admin has clicked two points on this map's
    own image whose real-world distance they know. meters_per_pixel is
    always computed server-side from the actual pixel distance between
    those two points — a client-supplied scale is never trusted directly.
    `scale = 1.0` is the pre-calibration placeholder and must never be
    silently treated as measured; only this endpoint (or explicitly
    copying another floor's calibration below) may set is_calibrated=True.
    """

    map_item = await Map.get(map_id)

    if not map_item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Map not found",
        )

    _require_map_scope(admin, map_item)

    pixel_distance = math.sqrt(
        (data.point_b_x - data.point_a_x) ** 2
        + (data.point_b_y - data.point_a_y) ** 2
    )

    if pixel_distance <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "The two calibration points must not be identical — "
                "pick two points with a real, measurable pixel distance."
            ),
        )

    meters_per_pixel = data.real_distance_meters / pixel_distance

    map_item.scale = meters_per_pixel
    map_item.is_calibrated = True
    map_item.calibrated_at = datetime.utcnow()
    map_item.calibration_source = "measured"
    map_item.updated_at = datetime.utcnow()

    await map_item.save()

    # Calibration has already succeeded and saved above — recalculating
    # existing walkway edges for the new scale is a best-effort follow-up
    # that must never fail or roll back that save (requirement 5). Only
    # this map's own walkway edges are touched; stairs/elevator/escalator/
    # ramp edges (distance_override) are never selected (requirement 8).
    edges_recalculated, edges_skipped = await recalculate_walkway_edges_for_map(
        str(map_item.id)
    )

    return map_to_calibration_response(
        map_item,
        edges_recalculated=edges_recalculated,
        edges_recalculation_skipped=edges_skipped,
    )


@router.post(
    "/{map_id}/copy-calibration",
    response_model=MapCalibrationResponse,
)
async def copy_map_calibration(
    map_id: PydanticObjectId,
    data: CopyCalibrationRequest,
    admin: User = Depends(require_any_admin),
):
    """
    Explicit admin action only (PHASE 8: "allow copying calibration to
    another floor only as an explicit admin action") — copies a SOURCE
    map's already-measured scale onto this map. The source map must
    itself be genuinely calibrated (never chains an uncalibrated
    placeholder scale from one floor to another).
    """

    map_item = await Map.get(map_id)
    if not map_item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Map not found",
        )

    _require_map_scope(admin, map_item)

    source_map = await Map.get(PydanticObjectId(data.source_map_id))
    if not source_map:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Source map not found",
        )

    # The source map being copied FROM must also be in the caller's scope
    # — otherwise a building_manager could read another building's
    # calibration value indirectly by copying it onto a map they do own.
    _require_map_scope(admin, source_map)

    if not source_map.is_calibrated:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The source map has not been calibrated yet.",
        )

    map_item.scale = source_map.scale
    map_item.is_calibrated = True
    map_item.calibrated_at = datetime.utcnow()
    map_item.calibration_source = "copied"
    map_item.updated_at = datetime.utcnow()

    await map_item.save()

    # Same safe, best-effort recalculation as calibrate_map_scale() above
    # (requirement 7) — this map's own copied scale changed, so its
    # existing walkway edges are recalculated the same way.
    edges_recalculated, edges_skipped = await recalculate_walkway_edges_for_map(
        str(map_item.id)
    )

    return map_to_calibration_response(
        map_item,
        edges_recalculated=edges_recalculated,
        edges_recalculation_skipped=edges_skipped,
    )


# ---------------------------------------------------------
# Delete map
# ---------------------------------------------------------

@router.delete(
    "/{map_id}",
    status_code=status.HTTP_200_OK,
)
async def delete_map(
    map_id: PydanticObjectId,
    # PERMANENT STRUCTURAL DELETION is reserved for the global tier
    # (super_admin / global_manager). A building_manager is a full
    # OPERATIONAL administrator of its assigned building — it uploads
    # maps, creates map groups, adds floors, edits metadata and manages
    # every room/route-point/location-code inside that building — but it
    # may not permanently destroy a map, because this delete cascades
    # (Rooms, RoutePoints, RouteEdges and LocationCodes all go with it)
    # and is unrecoverable.
    #
    # The role gate is only the FIRST half: a scoped global_manager must
    # still be inside the map's own building, which the explicit
    # user_can_access_map() check below enforces. Role alone never
    # authorizes a delete here.
    admin: User = Depends(require_global_admin),
):
    map_item = await Map.get(map_id)

    # Final Building Manager rule: deleting a map is administration of the
    # map's OWN building, resolved from the stored Map document rather
    # than from anything the client sent. A building_manager may delete a
    # map inside its assigned building and is refused on every other one.
    if map_item is not None and not user_can_access_map(admin, map_item):
        raise HTTPException(**FORBIDDEN_MAP_SCOPE)

    if not map_item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Map not found",
        )

    _require_map_scope(admin, map_item)

    was_current = map_item.is_current
    map_id_str = str(map_id)

    # Cascade first (edges -> location codes -> points) so nothing in the
    # navigation graph ever ends up pointing at a map that no longer
    # exists.
    cascade_summary = await cascade_delete_map_graph(map_id_str)

    await map_item.delete()

    remove_map_files(map_id_str)

    # When the current map is deleted, select another map.
    if was_current:
        replacement_map = await Map.find_one()

        if replacement_map:
            await set_map_as_current(
                replacement_map
            )

    return {
        "message": "Map deleted successfully",
        **cascade_summary,
    }