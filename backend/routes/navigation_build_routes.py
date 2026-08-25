"""
Automatic navigation build — Phase A, PREVIEW ONLY.

  POST /api/maps/{map_id}/navigation-build/preview

There is deliberately NO apply endpoint in this module and no route that
writes anything. Persistence of the generated transit graph, automatic QR
issuance and the end-to-end orchestration are Phase B, gated on an
operator inspecting this preview against a real floor plan first.

Authorization matches the existing semantic-analysis endpoints exactly:
require_any_admin plus a per-map building-scope check.
"""

from __future__ import annotations

from beanie import PydanticObjectId
from fastapi import APIRouter, Body, Depends, HTTPException, status

from core.auth_deps import require_any_admin, user_can_access_map
from core.errors import FORBIDDEN_MAP_SCOPE
from models.map_model import Map
from models.user_model import User
from schemas.navigation_build_schema import (
    NavigationBuildPreviewRequest,
    NavigationBuildPreviewResponse,
)
from services.navigation_build_preview_service import preview_navigation_build


router = APIRouter(tags=["Automatic Navigation Build"])


def _require_map_scope(admin: User, map_item: Map) -> None:
    """Identical rule to routes/semantic_analysis_routes._require_map_scope."""
    if admin.role != "super_admin" and not user_can_access_map(admin, map_item):
        raise HTTPException(**FORBIDDEN_MAP_SCOPE)


@router.post(
    "/api/maps/{map_id}/navigation-build/preview",
    response_model=NavigationBuildPreviewResponse,
)
async def preview_automatic_navigation_build(
    map_id: str,
    request: NavigationBuildPreviewRequest = Body(
        default_factory=NavigationBuildPreviewRequest
    ),
    admin: User = Depends(require_any_admin),
):
    """
    Proposes a hidden transit graph and room arrival points for this map,
    derived from the drawing's own geometry and its approved semantic
    analysis.

    COMPLETELY READ-ONLY. No Room, RoutePoint, RouteEdge, LocationCode,
    semantic review or publication record is created, updated or deleted.
    The response describes what an apply WOULD do, including how many QR
    codes it would issue, and creates none of it.

    A refusal is a normal outcome, returned as HTTP 200 with
    `available: false`, a named `failed_stage` and a human-readable
    `reason` — never as an error status. The `diagnostics` block reports
    every count and every rejection so a run can be judged rather than
    guessed at.
    """

    try:
        object_id = PydanticObjectId(map_id)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Map not found"
        )

    map_item = await Map.get(object_id)

    if not map_item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Map not found"
        )

    _require_map_scope(admin, map_item)

    result = await preview_navigation_build(
        map_id=map_id,
        item_external_ids=request.item_external_ids,
        lang=request.lang,
    )

    return NavigationBuildPreviewResponse(**result)
