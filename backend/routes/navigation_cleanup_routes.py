"""
Navigation-data-problem task — Full Navigation Reset (Part 3B) and
multi-Map cleanup (Part 4) endpoints.

Kept in a dedicated router (rather than growing map_routes.py further)
since these are a genuinely separate, Super-Admin-only, explicitly
destructive workflow from everything else map_routes.py exposes. All
write endpoints here require require_super_admin — "the strictest
existing authorized role" per this task's explicit requirement, since a
Full Reset (unlike generated-only cleanup) can delete manually-added
RoutePoints too and must never be reachable by a building_manager or
global_manager, even one otherwise fully authorized for that map.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from core.auth_deps import require_super_admin
from models.user_model import User
from schemas.map_schema import (
    FullMapResetPreviewResponse,
    FullMapResetApplyRequest,
    FullMapResetApplyResponse,
    MapsNavigationOverviewResponse,
    MultiMapCleanupRequest,
    MultiMapGeneratedCleanupPreviewResponse,
    MultiMapGeneratedCleanupApplyResponse,
    MultiMapFullResetPreviewResponse,
    MultiMapFullResetApplyRequest,
    MultiMapFullResetApplyResponse,
)
from services.navigation_reset_service import (
    preview_full_map_reset,
    apply_full_map_reset,
    list_maps_navigation_overview,
    preview_multi_map_generated_cleanup,
    apply_multi_map_generated_cleanup,
    preview_multi_map_full_reset,
    apply_multi_map_full_reset,
)


router = APIRouter(prefix="/api/navigation-cleanup", tags=["Navigation Cleanup"])


# The fixed phrase accepted in addition to the Map's own exact title for a
# single-Map Full Reset (Part 3B: "Require typing the Map name OR a
# confirmation phrase").
SINGLE_MAP_RESET_PHRASE = "RESET NAVIGATION DATA"

# The fixed phrase required for a multi-Map Full Reset (Part 4's exact
# wording).
MULTI_MAP_RESET_PHRASE = "RESET SELECTED NAVIGATION DATA"


# ---------------------------------------------------------
# Part 3B — Full Navigation Reset for ONE explicitly selected Map.
# ---------------------------------------------------------

@router.get(
    "/maps/{map_id}/full-reset/preview",
    response_model=FullMapResetPreviewResponse,
)
async def preview_map_full_reset(
    map_id: str,
    _admin: User = Depends(require_super_admin),
):
    """Read-only. Never deletes anything. Reports EVERY RoutePoint/
    RouteEdge on this map, not just proven-generated ones."""

    result = await preview_full_map_reset(map_id)
    if not result.get("found"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Map not found"
        )
    return FullMapResetPreviewResponse(**result)


@router.post(
    "/maps/{map_id}/full-reset/apply",
    response_model=FullMapResetApplyResponse,
)
async def apply_map_full_reset(
    map_id: str,
    apply_request: FullMapResetApplyRequest,
    admin: User = Depends(require_super_admin),
):
    """
    Deletes EVERY RoutePoint/RouteEdge on this one map, including
    manually-added ones — intentionally different and stronger than
    generated-only cleanup. Requires ALL of:
      - the map_id in the URL and in the request body to match exactly;
      - confirm: true;
      - confirmation_text equal to either this Map's exact title, or the
        fixed phrase "RESET NAVIGATION DATA".
    Never deletes the Map, Building, MapGroup, Room, LocationCode,
    VerticalConnector, semantic-analysis data, or calibration — see
    services/navigation_reset_service.py's module docstring for exactly
    how linked Rooms/LocationCodes/connectors are safely handled instead.
    """

    if apply_request.map_id != map_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="map_id in the request body must match the URL.",
        )

    if not apply_request.confirm:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Explicit confirmation is required. Call "
                "GET /full-reset/preview first, review every route point "
                "and connection that will be deleted, then resend this "
                "request with confirm: true and the required "
                "confirmation_text."
            ),
        )

    preview = await preview_full_map_reset(map_id)
    if not preview.get("found"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Map not found"
        )

    map_name = preview.get("map_name") or ""
    submitted = (apply_request.confirmation_text or "").strip()

    if submitted != map_name and submitted != SINGLE_MAP_RESET_PHRASE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f'confirmation_text must exactly match this map\'s name '
                f'("{map_name}") or the phrase '
                f'"{SINGLE_MAP_RESET_PHRASE}".'
            ),
        )

    result = await apply_full_map_reset(map_id)
    return FullMapResetApplyResponse(**result)


# ---------------------------------------------------------
# Part 4 — multi-Map overview + multi-Map cleanup (Super Admin only).
# ---------------------------------------------------------

@router.get(
    "/maps-overview",
    response_model=MapsNavigationOverviewResponse,
)
async def get_maps_navigation_overview(
    _admin: User = Depends(require_super_admin),
):
    """Read-only listing of every Map's navigation-data footprint, for
    the multi-Map cleanup screen's map picker/table."""

    maps = await list_maps_navigation_overview()
    return MapsNavigationOverviewResponse(maps=maps)


@router.post(
    "/multi/generated-cleanup/preview",
    response_model=MultiMapGeneratedCleanupPreviewResponse,
)
async def preview_multi_map_generated_cleanup_route(
    cleanup_request: MultiMapCleanupRequest,
    _admin: User = Depends(require_super_admin),
):
    """Read-only. Never deletes anything. Scoped strictly to the
    explicitly selected map_ids — an empty/omitted list previews nothing,
    never "every Map"."""

    if not cleanup_request.map_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one map_id must be selected.",
        )

    result = await preview_multi_map_generated_cleanup(cleanup_request.map_ids)
    return MultiMapGeneratedCleanupPreviewResponse(**result)


@router.post(
    "/multi/generated-cleanup/apply",
    response_model=MultiMapGeneratedCleanupApplyResponse,
)
async def apply_multi_map_generated_cleanup_route(
    cleanup_request: MultiMapCleanupRequest,
    _admin: User = Depends(require_super_admin),
):
    """Deletes only proven-generated records (is_auto_generated=True) on
    each explicitly selected map — every map_id is revalidated fresh
    against the live database, never trusting a client-cached preview."""

    if not cleanup_request.map_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one map_id must be selected.",
        )

    result = await apply_multi_map_generated_cleanup(cleanup_request.map_ids)
    return MultiMapGeneratedCleanupApplyResponse(**result)


@router.post(
    "/multi/full-reset/preview",
    response_model=MultiMapFullResetPreviewResponse,
)
async def preview_multi_map_full_reset_route(
    cleanup_request: MultiMapCleanupRequest,
    _admin: User = Depends(require_super_admin),
):
    """Read-only. Never deletes anything."""

    if not cleanup_request.map_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one map_id must be selected.",
        )

    result = await preview_multi_map_full_reset(cleanup_request.map_ids)
    return MultiMapFullResetPreviewResponse(**result)


@router.post(
    "/multi/full-reset/apply",
    response_model=MultiMapFullResetApplyResponse,
)
async def apply_multi_map_full_reset_route(
    apply_request: MultiMapFullResetApplyRequest,
    admin: User = Depends(require_super_admin),
):
    """
    Deletes EVERY RoutePoint/RouteEdge on EVERY explicitly selected map.
    Requires confirm: true AND confirmation_phrase exactly equal to
    "RESET SELECTED NAVIGATION DATA". Every map_id is revalidated fresh
    against the live database at apply time — a map_id that no longer
    exists (deleted between preview and apply) is skipped and reported in
    skipped_map_ids, never silently treated as "affects every Map".
    require_super_admin is re-checked by FastAPI's own dependency
    resolution on every single call, so a role downgrade between preview
    and apply is naturally rejected before this body ever runs.
    """

    if not apply_request.map_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one map_id must be selected.",
        )

    if not apply_request.confirm:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Explicit confirmation is required. Call "
                "/multi/full-reset/preview first, review every selected "
                "map's totals, then resend this request with "
                "confirm: true and the required confirmation_phrase."
            ),
        )

    submitted = (apply_request.confirmation_phrase or "").strip()
    if submitted != MULTI_MAP_RESET_PHRASE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f'confirmation_phrase must exactly equal "{MULTI_MAP_RESET_PHRASE}".',
        )

    result = await apply_multi_map_full_reset(apply_request.map_ids)
    return MultiMapFullResetApplyResponse(**result)
