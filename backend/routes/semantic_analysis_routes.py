"""
API endpoints for the semantic map-analysis workflow (Section 12).

Every endpoint here is admin-only (require_global_admin — super_admin or
global_manager, matching the same dependency the map-upload endpoints
already use). Normal users never call any of these directly; the only
thing normal users ever see downstream of this feature is a RoutePoint's
already-resolved display_name (see route_point routes/schema), never raw
AI drafts, prompt text, evidence, or validation errors (Section 19).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from beanie import PydanticObjectId
from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from pydantic import BaseModel

from core.auth_deps import (
    require_global_admin,
    require_any_admin,
    user_can_access_map,
    user_can_access_building,
)
from core.errors import FORBIDDEN_MAP_SCOPE, FORBIDDEN_BUILDING_SCOPE, MAP_GROUP_FORBIDDEN_SCOPE
from models.map_model import Map
from models.map_group_model import MapGroup
from models.semantic_map_analysis_model import SemanticMapAnalysis
from models.semantic_map_publication_model import SemanticEntity
from models.user_model import User
from schemas.localization_schema import get_localized_text
from services import semantic_analysis_service as svc
from services.semantic_prompt_loader import get_prompt_info
from services.semantic_publication_service import (
    publish_analysis,
    validate_reviewed_result_for_publish,
    normalize_floor_codes,
    repair_floor_codes_for_map,
)
from schemas.semantic_destination_schema import (
    SemanticDestinationPreviewRequest,
    SemanticDestinationPreviewResponse,
    SemanticDestinationApplyRequest,
    SemanticDestinationApplyResult,
)
from services.semantic_destination_service import (
    preview_semantic_destinations,
    apply_semantic_destinations,
)


router = APIRouter(tags=["Semantic Map Analysis"])


# ---------------------------------------------------------
# Serialization — never includes ai_result/reviewed_result in the "list"
# shape; those are only returned by the explicit .../result endpoint
# (Section 19: keep raw drafts scoped to callers that actually need them).
# ---------------------------------------------------------


def analysis_to_summary(analysis: SemanticMapAnalysis) -> Dict[str, Any]:
    return {
        "analysis_id": analysis.analysis_id,
        "scope_type": analysis.scope_type,
        "map_id": analysis.map_id,
        "map_group_id": analysis.map_group_id,
        "building_id": analysis.building_id,
        "status": analysis.status,
        "progress": analysis.progress,
        "attempt_count": analysis.attempt_count,
        "prompt_version": analysis.prompt_version,
        "prompt_sha256": analysis.prompt_sha256,
        "model": analysis.model,
        "provider": analysis.provider,
        "review_status": analysis.review_status,
        "review_revision": analysis.review_revision,
        "error_code": analysis.error_code,
        "error_message": analysis.error_message,
        "created_at": analysis.created_at,
        "started_at": analysis.started_at,
        "completed_at": analysis.completed_at,
        "updated_at": analysis.updated_at,
        "published_analysis_id": analysis.published_analysis_id,
        "published_at": analysis.published_at,
    }


def analysis_to_detail(analysis: SemanticMapAnalysis) -> Dict[str, Any]:
    summary = analysis_to_summary(analysis)
    summary["local_validation"] = analysis.local_validation
    return summary


async def _load_analysis_or_404(analysis_id: str) -> SemanticMapAnalysis:
    analysis = await SemanticMapAnalysis.find_one(
        SemanticMapAnalysis.analysis_id == analysis_id
    )
    if not analysis:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Semantic analysis not found",
        )
    return analysis


async def _load_map_or_404(map_id: str) -> Map:
    try:
        map_item = await Map.get(PydanticObjectId(map_id))
    except Exception as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Map not found"
        ) from error
    if not map_item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Map not found"
        )
    return map_item


def _require_map_scope(admin: User, map_item: Map) -> None:
    """RBAC/dashboard cleanup task, Phase 2 continuation."""
    if admin.role != "super_admin" and not user_can_access_map(admin, map_item):
        raise HTTPException(**FORBIDDEN_MAP_SCOPE)


async def _require_analysis_scope(admin: User, analysis: SemanticMapAnalysis) -> None:
    """Same map_id/map_group_id-driven scope rule
    core/auth_deps.require_semantic_analysis_access implements, inlined
    here so every route in this file (which already loads the analysis
    itself, not just an id) doesn't need a second redundant DB fetch."""
    if admin.role == "super_admin":
        return

    if analysis.scope_type == "map" and analysis.map_id:
        try:
            map_item = await Map.get(PydanticObjectId(analysis.map_id))
        except Exception:
            map_item = None
        if map_item is not None:
            _require_map_scope(admin, map_item)
            return

    if not user_can_access_building(admin, analysis.building_id):
        raise HTTPException(**FORBIDDEN_BUILDING_SCOPE)
    if admin.role == "building_manager":
        if admin.map_group_ids and analysis.map_group_id not in admin.map_group_ids:
            raise HTTPException(**MAP_GROUP_FORBIDDEN_SCOPE)
        if admin.map_ids and not admin.map_group_ids:
            raise HTTPException(**MAP_GROUP_FORBIDDEN_SCOPE)


# ---------------------------------------------------------
# Start (Section 12) — idempotent by default; force=true creates a new
# revision and supersedes the previous unpublished one.
# ---------------------------------------------------------


class StartAnalysisRequest(BaseModel):
    force: bool = False


@router.post("/api/maps/{map_id}/semantic-analysis/start")
async def start_map_semantic_analysis(
    map_id: str,
    body: StartAnalysisRequest = Body(default=StartAnalysisRequest()),
    admin: User = Depends(require_any_admin),
):
    map_item = await _load_map_or_404(map_id)
    _require_map_scope(admin, map_item)

    # Uses the ONE canonical resolver (see map_image_service.
    # resolve_analysis_source_path_async) — the fix for the "No source
    # file could be located on disk" bug, which was caused by this
    # endpoint, its map-group sibling below, and the background worker
    # each independently re-deriving "where is this map's source file" by
    # filename convention and being able to silently disagree with each
    # other.
    from services.map_image_service import (
        resolve_analysis_source_path_async,
        to_storage_relative_path,
    )

    resolved_source = await resolve_analysis_source_path_async(map_item)

    if resolved_source is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "This map has no processed source file available "
                "locally or in storage. Wait for processing to "
                "complete or upload the map again."
            ),
        )

    source_path = resolved_source.path

    # Self-heal: a map processed before analysis_source_path existed (or
    # whose preserved-original copy failed silently at upload time) now
    # gets the field backfilled the first time resolution succeeds, so
    # every subsequent read goes straight through the reliable persisted
    # pointer instead of re-deriving it by convention again.
    if map_item.analysis_source_path != to_storage_relative_path(source_path):
        map_item.analysis_source_path = to_storage_relative_path(source_path)
        map_item.analysis_source_type = resolved_source.source_type
        await map_item.save()

    analysis = await svc.enqueue_analysis_for_map(
        map_id=map_id,
        building_id=map_item.building_id,
        map_group_id=map_item.map_group_id,
        source_path=source_path,
        source_filename=map_item.source_filename or source_path.name,
        created_by=str(admin.id),
        force=body.force,
    )
    return analysis_to_summary(analysis)


@router.get("/api/maps/{map_id}/semantic-analysis/latest")
async def get_latest_map_semantic_analysis(
    map_id: str,
    admin: User = Depends(require_any_admin),
):
    map_item = await _load_map_or_404(map_id)
    _require_map_scope(admin, map_item)

    analysis = await SemanticMapAnalysis.find_one(
        {"map_id": map_id}, sort=[("created_at", -1)]
    )
    if not analysis:
        return None
    return analysis_to_summary(analysis)


@router.get("/api/maps/{map_id}/semantic-entities")
async def get_published_semantic_entities_for_map(
    map_id: str,
    entity_type: Optional[str] = Query(default=None),
    admin: User = Depends(require_any_admin),
):
    """
    Powers the "Choose name from approved map data" RoutePoint selector
    (Section 16). Only ever returns entities from the currently ACTIVE
    publication for this exact map — never AI drafts, never rejected/
    pending entities.
    """

    map_item = await _load_map_or_404(map_id)
    _require_map_scope(admin, map_item)

    query: Dict[str, Any] = {"map_id": map_id, "active": True}
    if entity_type:
        query["entity_type"] = entity_type

    entities = await SemanticEntity.find(query).to_list()
    return [
        {
            "entity_external_id": entity.entity_external_id,
            "entity_type": entity.entity_type,
            "map_id": entity.map_id,
            "floor_external_id": entity.floor_external_id,
            # Prefer the nested canonical field; fall back to assembling
            # it from the legacy flat fields for any entity indexed
            # before `names` existed — both describe the exact same
            # single document, never a second/third one.
            "names": entity.names
            or {
                "original": entity.names_original,
                "en": entity.names_en,
                "ar": entity.names_ar,
                "he": entity.names_he,
            },
            # Safe single-string legacy fallback (Section 7) — resolved
            # server-side once here so a caller that only wants "the
            # best available name" never has to reimplement the
            # fallback chain itself.
            "name": get_localized_text(
                entity.names
                or {
                    "en": entity.names_en,
                    "ar": entity.names_ar,
                    "he": entity.names_he,
                },
                "en",
                entity.names_original,
            ),
            "category": entity.category,
            "subcategory": entity.subcategory,
            "displayed_number": entity.displayed_number,
            "confidence": entity.confidence,
            "publication_id": entity.publication_id,
        }
        for entity in entities
    ]


# ---------------------------------------------------------
# Get / result
# ---------------------------------------------------------


@router.get("/api/semantic-analyses/{analysis_id}")
async def get_semantic_analysis(
    analysis_id: str,
    admin: User = Depends(require_any_admin),
):
    analysis = await _load_analysis_or_404(analysis_id)
    await _require_analysis_scope(admin, analysis)
    return analysis_to_detail(analysis)


@router.get("/api/semantic-analyses/{analysis_id}/result")
async def get_semantic_analysis_result(
    analysis_id: str,
    admin: User = Depends(require_any_admin),
):
    analysis = await _load_analysis_or_404(analysis_id)
    await _require_analysis_scope(admin, analysis)

    # Authoritative semantic floor code (see semantic_publication_service's
    # module docstring): the AI invents its own "floor_001"-style
    # placeholder text, unrelated to which real floor this Map is — the
    # review screen must always show the code derived from Map.floor
    # instead. This is a VIEW-ONLY transform: ai_result is never rewritten
    # in the database (its own model docstring promises that), and
    # reviewed_result is only persisted-corrected when the admin actually
    # saves (see save_reviewed_result below) or publishes — a GET must
    # never have a side effect.
    floor_number: Optional[int] = None
    if analysis.scope_type == "map" and analysis.map_id and PydanticObjectId.is_valid(analysis.map_id):
        map_item = await Map.get(PydanticObjectId(analysis.map_id))
        if map_item:
            floor_number = map_item.floor

    ai_result_view, _ = normalize_floor_codes(analysis.ai_result, floor_number=floor_number)
    reviewed_result_view, _ = normalize_floor_codes(
        analysis.reviewed_result, floor_number=floor_number
    )

    return {
        "analysis_id": analysis.analysis_id,
        "status": analysis.status,
        "prompt_version": analysis.prompt_version,
        "prompt_sha256": analysis.prompt_sha256,
        "review_revision": analysis.review_revision,
        "ai_result": ai_result_view,
        "reviewed_result": reviewed_result_view,
        "local_validation": analysis.local_validation,
    }


# ---------------------------------------------------------
# Retry / cancel
# ---------------------------------------------------------


@router.post("/api/semantic-analyses/{analysis_id}/retry")
async def retry_semantic_analysis(
    analysis_id: str,
    admin: User = Depends(require_any_admin),
):
    analysis = await _load_analysis_or_404(analysis_id)
    await _require_analysis_scope(admin, analysis)

    if analysis.status not in ("failed", "invalid_output", "configuration_required"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Cannot retry an analysis in status '{analysis.status}'."
            ),
        )

    if not svc.get_anthropic_api_key():
        analysis.status = "configuration_required"
        analysis.error_code = "missing_api_key"
        analysis.error_message = "ANTHROPIC_API_KEY is still not configured."
    else:
        analysis.status = "queued"
        analysis.error_code = None
        analysis.error_message = None
        analysis.worker_claim_id = None
        analysis.processing_started_at = None

    analysis.updated_at = datetime.utcnow()
    await analysis.save()
    return analysis_to_summary(analysis)


@router.post("/api/semantic-analyses/{analysis_id}/cancel")
async def cancel_semantic_analysis(
    analysis_id: str,
    admin: User = Depends(require_any_admin),
):
    analysis = await _load_analysis_or_404(analysis_id)
    await _require_analysis_scope(admin, analysis)

    if analysis.status in ("completed", "cancelled", "superseded"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot cancel an analysis in status '{analysis.status}'.",
        )

    analysis.status = "cancelled"
    analysis.updated_at = datetime.utcnow()
    await analysis.save()
    return analysis_to_summary(analysis)


# ---------------------------------------------------------
# Reviewed result (admin edits) — Section 12/13
# ---------------------------------------------------------


class SaveReviewedResultRequest(BaseModel):
    expected_revision: int
    reviewed_result: Dict[str, Any]


@router.put("/api/semantic-analyses/{analysis_id}/reviewed-result")
async def save_reviewed_result(
    analysis_id: str,
    body: SaveReviewedResultRequest,
    admin: User = Depends(require_any_admin),
):
    analysis = await _load_analysis_or_404(analysis_id)
    await _require_analysis_scope(admin, analysis)

    if analysis.status != "completed" and analysis.reviewed_result is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "This analysis has no completed AI result to review yet."
            ),
        )

    # Optimistic concurrency: reject a save based on a stale revision so
    # two admins editing at once can never silently clobber one another.
    if body.expected_revision != analysis.review_revision:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"This review draft has changed since you loaded it "
                f"(expected revision {body.expected_revision}, current "
                f"revision is {analysis.review_revision}). Reload and "
                "reapply your changes."
            ),
        )

    if not isinstance(body.reviewed_result, dict):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="reviewed_result must be a JSON object.",
        )

    # Authoritative semantic floor code: normalize BEFORE persisting, so
    # every save this analysis ever receives self-heals its own floor
    # code (and every place/facility/etc that references it) from
    # whatever the AI originally invented — the admin never has to fix
    # this by hand, and it never requires re-running the AI.
    floor_number: Optional[int] = None
    if analysis.scope_type == "map" and analysis.map_id and PydanticObjectId.is_valid(analysis.map_id):
        map_item = await Map.get(PydanticObjectId(analysis.map_id))
        if map_item:
            floor_number = map_item.floor
    normalized_reviewed_result, _floor_fix_messages = normalize_floor_codes(
        body.reviewed_result, floor_number=floor_number
    )

    analysis.reviewed_result = normalized_reviewed_result
    analysis.review_revision += 1
    analysis.review_status = "in_progress"
    analysis.updated_at = datetime.utcnow()
    await analysis.save()

    return analysis_to_detail(analysis)


@router.post("/api/semantic-analyses/{analysis_id}/validate")
async def validate_semantic_analysis(
    analysis_id: str,
    admin: User = Depends(require_any_admin),
):
    analysis = await _load_analysis_or_404(analysis_id)
    await _require_analysis_scope(admin, analysis)
    result = validate_reviewed_result_for_publish(analysis.reviewed_result)
    return result


class PublishRequest(BaseModel):
    quickroute_links: Optional[Dict[str, Any]] = None


@router.post("/api/semantic-analyses/{analysis_id}/publish")
async def publish_semantic_analysis(
    analysis_id: str,
    body: PublishRequest = Body(default=PublishRequest()),
    admin: User = Depends(require_any_admin),
):
    analysis = await _load_analysis_or_404(analysis_id)
    await _require_analysis_scope(admin, analysis)

    try:
        publication = await publish_analysis(
            analysis,
            published_by=str(admin.id),
            quickroute_links=body.quickroute_links,
        )
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(error)
        ) from error

    return {
        "publication_id": publication.publication_id,
        "analysis_id": publication.analysis_id,
        "map_id": publication.map_id,
        "publication_revision": publication.publication_revision,
        "published_at": publication.published_at,
    }


@router.post("/api/maps/{map_id}/semantic-analysis/repair-floor-codes")
async def repair_semantic_analysis_floor_codes(
    map_id: str,
    admin: User = Depends(require_any_admin),
):
    """
    Admin-confirmed, explicit repair action for semantic floor codes on
    analysis/publication data that predates the authoritative-floor-code
    fix (see semantic_publication_service.repair_floor_codes_for_map's
    own docstring for exactly what it does and doesn't touch). Scoped to
    exactly this one Map; never runs automatically; never touches
    Rooms/RoutePoints/RouteEdges.
    """

    map_item = await Map.get(PydanticObjectId(map_id)) if PydanticObjectId.is_valid(map_id) else None
    if not map_item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Map not found")

    _require_map_scope(admin, map_item)

    return await repair_floor_codes_for_map(map_id)


# ---------------------------------------------------------
# Optional: Map-Group-scoped analysis (Section 12)
# ---------------------------------------------------------


@router.post("/api/map-groups/{map_group_id}/semantic-analysis/start")
async def start_map_group_semantic_analysis(
    map_group_id: str,
    body: StartAnalysisRequest = Body(default=StartAnalysisRequest()),
    admin: User = Depends(require_any_admin),
):
    try:
        group = await MapGroup.get(PydanticObjectId(map_group_id))
    except Exception as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Map group not found"
        ) from error
    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Map group not found"
        )

    if admin.role != "super_admin":
        if not user_can_access_building(admin, group.building_id):
            raise HTTPException(**FORBIDDEN_BUILDING_SCOPE)
        if admin.role == "building_manager":
            if admin.map_group_ids and str(group.id) not in admin.map_group_ids:
                raise HTTPException(**MAP_GROUP_FORBIDDEN_SCOPE)
            if admin.map_ids and not admin.map_group_ids:
                raise HTTPException(**MAP_GROUP_FORBIDDEN_SCOPE)

    floor_maps = await Map.find(Map.map_group_id == str(group.id)).to_list()
    if not floor_maps:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This map group has no floor maps yet.",
        )

    # Same canonical resolver as the single-map endpoint above — see its
    # comment for why this used to be a third independent, divergence-
    # prone implementation of the same lookup.
    from services.map_image_service import (
        resolve_analysis_source_path_async,
        to_storage_relative_path,
    )

    file_bytes_list: List[bytes] = []
    filenames: List[str] = []
    source_map_ids: List[str] = []

    for floor_map in sorted(floor_maps, key=lambda m: (m.floor is None, m.floor)):
        floor_map_id = str(floor_map.id)
        resolved_source = await resolve_analysis_source_path_async(floor_map)

        if resolved_source is None:
            continue

        path = resolved_source.path

        if floor_map.analysis_source_path != to_storage_relative_path(path):
            floor_map.analysis_source_path = to_storage_relative_path(path)
            floor_map.analysis_source_type = resolved_source.source_type
            await floor_map.save()

        file_bytes_list.append(path.read_bytes())
        filenames.append(floor_map.source_filename or path.name)
        source_map_ids.append(floor_map_id)

    if not file_bytes_list:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="None of this group's floor maps have a processed source file yet.",
        )

    try:
        prompt_info = get_prompt_info()
    except Exception as error:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(error),
        ) from error

    fingerprint = svc.compute_source_fingerprint(file_bytes_list)
    model = svc.get_analysis_model()

    if not body.force:
        existing = await svc.find_reusable_analysis(
            scope_type="map_group",
            map_id=None,
            map_group_id=map_group_id,
            source_fingerprint=fingerprint,
            prompt_sha256=prompt_info["prompt_sha256"],
            model=model,
        )
        if existing:
            return analysis_to_summary(existing)

    has_api_key = bool(svc.get_anthropic_api_key())

    analysis = SemanticMapAnalysis(
        scope_type="map_group",
        map_id=None,
        map_group_id=map_group_id,
        building_id=group.building_id,
        source_map_ids=source_map_ids,
        source_filenames=filenames,
        source_fingerprint=fingerprint,
        prompt_version=prompt_info["prompt_version"],
        prompt_sha256=prompt_info["prompt_sha256"],
        model=model,
        provider=svc.PROVIDER_NAME,
        status="queued" if has_api_key else "configuration_required",
        error_code=None if has_api_key else "missing_api_key",
        error_message=(
            None
            if has_api_key
            else "ANTHROPIC_API_KEY is not configured on the server."
        ),
        created_by=str(admin.id),
    )
    await analysis.insert()
    return analysis_to_summary(analysis)


@router.get("/api/prompts/semantic-map-import/info")
async def get_semantic_prompt_info(_admin: User = Depends(require_global_admin)):
    """
    Safe-to-view version/hash only — never the prompt text itself
    (Section 19). Lets the review UI show "Prompt version: ...,
    hash: ..." without exposing the actual prompt content.
    """

    return get_prompt_info()


# ---------------------------------------------------------
# "Approved Semantic Analysis -> Automatic Destinations" — preview/apply.
# Both admin-protected; preview is entirely read-only, apply independently
# revalidates every accepted item server-side (never trusts the preview
# response as-is). See services/semantic_destination_service.py for the
# actual matching/create/nested-relationship logic — this file only wires
# the two endpoints to it, matching every other route in this file.
# ---------------------------------------------------------


@router.post(
    "/api/maps/{map_id}/semantic-analysis/destinations/preview",
    response_model=SemanticDestinationPreviewResponse,
)
async def preview_semantic_analysis_destinations(
    map_id: str,
    request: SemanticDestinationPreviewRequest = Body(default_factory=SemanticDestinationPreviewRequest),
    admin: User = Depends(require_any_admin),
):
    map_item = await Map.get(PydanticObjectId(map_id))
    if not map_item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Map not found")

    _require_map_scope(admin, map_item)

    result = await preview_semantic_destinations(
        map_id=map_id,
        item_external_ids=request.item_external_ids,
        lang=request.lang,
    )
    return SemanticDestinationPreviewResponse(**result)


@router.post(
    "/api/maps/{map_id}/semantic-analysis/destinations/apply",
    response_model=SemanticDestinationApplyResult,
)
async def apply_semantic_analysis_destinations(
    map_id: str,
    request: SemanticDestinationApplyRequest,
    admin: User = Depends(require_any_admin),
):
    map_item = await Map.get(PydanticObjectId(map_id))
    if not map_item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Map not found")

    _require_map_scope(admin, map_item)

    result = await apply_semantic_destinations(
        map_id=map_id,
        publication_id=request.publication_id,
        accepted_items=[item.model_dump() for item in request.accepted],
        all_or_nothing=request.all_or_nothing,
    )
    return SemanticDestinationApplyResult(**result)