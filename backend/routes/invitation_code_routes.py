import os
from datetime import datetime, timezone
from typing import List, Optional

from beanie import PydanticObjectId
from beanie.operators import In, Set
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from core.auth_deps import require_global_admin
from core.errors import (
    DEV_ENDPOINT_DISABLED,
    FORBIDDEN_ROLE,
    INVITATION_CODE_ALREADY_EXISTS,
    INVITATION_CODE_CANNOT_REVOKE,
    INVITATION_CODE_NOT_FOUND,
)
from logic.invitation_code_logic import (
    compute_invitation_code_status,
    generate_unique_code,
    validate_role_and_scope_for_creation,
)
from models.building_model import Building
from models.invitation_code_model import InvitationCode, InvitationRole
from models.user_model import User
from schemas.invitation_code_schema import (
    InvitationCodeCreate,
    InvitationCodeResponse,
    InvitationCodeStatus,
    ValidateInvitationCodeRequest,
    ValidateInvitationCodeResponse,
)

router = APIRouter(
    prefix="/api/invitation-codes",
    tags=["Invitation Codes"]
)


# ---------------------------------------------------------
# Development-only bootstrap endpoint gating
# ---------------------------------------------------------
# The normal, production path for creating invitation codes is the
# authenticated CRUD below (POST /api/invitation-codes, gated by
# require_global_admin). /dev-create exists ONLY to mint the very first
# super_admin account on a brand-new database, where no admin exists yet
# to authenticate as. It is:
#   - disabled by default (must be explicitly opted into via env var)
#   - hidden from the OpenAPI schema when disabled
#   - refuses to run at all once any super_admin already exists, so it can
#     never be used for privilege escalation once a real admin hierarchy
#     is established
#   - never able to bypass the role hierarchy for anything beyond that
#     one-time bootstrap
ALLOW_DEV_INVITATION_ENDPOINTS = (
    os.getenv("ALLOW_DEV_INVITATION_ENDPOINTS", "false").strip().lower() == "true"
)


class DevCreateInvitationCodeRequest(BaseModel):
    code: str = Field(..., min_length=6, max_length=30)
    role: InvitationRole = "super_admin"
    building_ids: list[str] = Field(default_factory=list)
    all_buildings: bool = True


def invitation_code_to_response(
    entry: InvitationCode, created_by_name: Optional[str] = None
) -> InvitationCodeResponse:
    return InvitationCodeResponse(
        id=str(entry.id),
        code=entry.code,
        role=entry.role,
        all_buildings=entry.all_buildings,
        building_ids=list(entry.building_ids),
        map_group_ids=list(getattr(entry, "map_group_ids", []) or []),
        map_ids=list(getattr(entry, "map_ids", []) or []),
        intended_email=entry.intended_email,
        expires_at=entry.expires_at,
        status=compute_invitation_code_status(entry),
        is_active=entry.is_active,
        is_used=entry.is_used,
        created_by_user_id=entry.created_by_user_id,
        created_by_name=created_by_name,
        created_at=entry.created_at,
        used_at=entry.used_at,
        used_by_user_id=entry.used_by_user_id,
        used_by_email=entry.used_by_email,
        revoked_at=entry.revoked_at,
        revoked_by_user_id=entry.revoked_by_user_id,
    )


async def _lookup_creator_names(entries: list[InvitationCode]) -> dict[str, str]:
    creator_ids = []
    for entry in entries:
        if entry.created_by_user_id and entry.created_by_user_id not in creator_ids:
            creator_ids.append(entry.created_by_user_id)

    valid_object_ids = []
    for raw_id in creator_ids:
        try:
            valid_object_ids.append(PydanticObjectId(raw_id))
        except Exception:
            continue

    if not valid_object_ids:
        return {}

    found = await User.find(In(User.id, valid_object_ids)).to_list()
    return {str(u.id): u.full_name for u in found}


# ---------------------------------------------------------
# Public: validate a code before/during Sign Up (no auth — the visitor
# isn't a user yet). Returns only safe, non-sensitive information: no
# creator identity, no usage history, no internal ids beyond what's
# needed to show the invited role/buildings/email restriction.
# ---------------------------------------------------------

@router.post("/validate", response_model=ValidateInvitationCodeResponse)
async def validate_code(request: ValidateInvitationCodeRequest):
    normalized = (request.code or "").strip().upper()
    entry = await InvitationCode.find_one(InvitationCode.code == normalized)

    if entry is None:
        return ValidateInvitationCodeResponse(
            valid=False, message="Invalid invitation code"
        )

    status_now = compute_invitation_code_status(entry)

    if status_now != "active":
        messages = {
            "used": "This invitation code has already been used",
            "revoked": "This invitation code has been revoked",
            "expired": "This invitation code has expired",
        }
        return ValidateInvitationCodeResponse(
            valid=False,
            message=messages.get(status_now, "This invitation code is not active"),
        )

    buildings = []
    if entry.building_ids:
        valid_object_ids = [
            PydanticObjectId(b) for b in entry.building_ids if PydanticObjectId.is_valid(b)
        ]
        if valid_object_ids:
            found = await Building.find(In(Building.id, valid_object_ids)).to_list()
            buildings = [{"id": str(b.id), "name": b.name_en} for b in found]

    return ValidateInvitationCodeResponse(
        valid=True,
        message="Invitation code is valid",
        role=entry.role,
        all_buildings=entry.all_buildings,
        building_ids=list(entry.building_ids),
        buildings=buildings,
        map_group_ids=list(getattr(entry, "map_group_ids", []) or []),
        map_ids=list(getattr(entry, "map_ids", []) or []),
        intended_email=entry.intended_email,
        expires_at=entry.expires_at,
    )


# ---------------------------------------------------------
# Authenticated admin CRUD
# ---------------------------------------------------------
# Every route below requires require_global_admin (super_admin or
# global_manager). building_manager and regular_user are rejected with
# 403 by the dependency itself — this is also how "building_manager does
# not access the Invitation Code management screen by default" is
# enforced on the backend, not just by hiding the button in the UI.

@router.get("", response_model=List[InvitationCodeResponse])
async def list_invitation_codes(
    status_filter: Optional[InvitationCodeStatus] = Query(default=None, alias="status"),
    role: Optional[InvitationRole] = Query(default=None),
    building_id: Optional[str] = Query(default=None),
    user: User = Depends(require_global_admin),
):
    query: dict = {}
    if role:
        query["role"] = role

    entries = await InvitationCode.find(query).sort("-created_at").to_list()

    if building_id:
        entries = [
            e for e in entries if e.all_buildings or building_id in e.building_ids
        ]

    if status_filter:
        entries = [
            e for e in entries if compute_invitation_code_status(e) == status_filter
        ]

    creator_names = await _lookup_creator_names(entries)

    return [
        invitation_code_to_response(e, creator_names.get(e.created_by_user_id))
        for e in entries
    ]


@router.post("", response_model=InvitationCodeResponse, status_code=status.HTTP_201_CREATED)
async def create_invitation_code(
    data: InvitationCodeCreate,
    user: User = Depends(require_global_admin),
):
    # Enforces: creator -> allowed role hierarchy, role -> valid building/
    # map-group/map scope shape, and every referenced building/map-group/
    # map both exists and is within the creator's own manageable scope.
    await validate_role_and_scope_for_creation(
        user,
        data.role,
        data.all_buildings,
        data.building_ids,
        data.map_group_ids,
        data.map_ids,
    )

    if data.expires_at is not None:
        expires_at = data.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at <= datetime.now(timezone.utc):
            raise HTTPException(
                status_code=400, detail="expires_at must be in the future"
            )

    # super_admin codes are system-wide by definition — force the
    # canonical shape server-side regardless of what was validated above.
    final_all_buildings = data.all_buildings
    final_building_ids = list(data.building_ids)
    final_map_group_ids = list(data.map_group_ids)
    final_map_ids = list(data.map_ids)
    if data.role == "super_admin":
        final_all_buildings = True
        final_building_ids = []
        final_map_group_ids = []
        final_map_ids = []
    elif data.role != "building_manager":
        # map_group_ids/map_ids are only ever a building_manager concept
        # (Phase 2) — already rejected by validate_role_and_scope_for_
        # creation for every other role, this is a defensive belt-and-
        # suspenders so the stored document can never disagree.
        final_map_group_ids = []
        final_map_ids = []

    try:
        code = await generate_unique_code(data.code)
    except HTTPException as error:
        if error.status_code == 409:
            raise HTTPException(**INVITATION_CODE_ALREADY_EXISTS)
        raise

    new_entry = InvitationCode(
        code=code,
        role=data.role,
        all_buildings=final_all_buildings,
        building_ids=final_building_ids,
        map_group_ids=final_map_group_ids,
        map_ids=final_map_ids,
        intended_email=data.intended_email,
        expires_at=data.expires_at,
        created_by_user_id=str(user.id),
    )

    await new_entry.insert()
    return invitation_code_to_response(new_entry, user.full_name)


@router.get("/{code_id}", response_model=InvitationCodeResponse)
async def get_invitation_code(
    code_id: PydanticObjectId,
    user: User = Depends(require_global_admin),
):
    entry = await InvitationCode.get(code_id)

    if not entry:
        raise HTTPException(**INVITATION_CODE_NOT_FOUND)

    creator_name = None
    if entry.created_by_user_id:
        try:
            creator = await User.get(PydanticObjectId(entry.created_by_user_id))
            creator_name = creator.full_name if creator else None
        except Exception:
            creator_name = None

    return invitation_code_to_response(entry, creator_name)


@router.post("/{code_id}/revoke", response_model=InvitationCodeResponse)
async def revoke_invitation_code(
    code_id: PydanticObjectId,
    user: User = Depends(require_global_admin),
):
    # Atomic, guarded update — mirrors the same conditional-update pattern
    # used for single-use signup consumption, so a revoke racing against a
    # signup (or two admins revoking at once) can't leave inconsistent
    # state either.
    result = await InvitationCode.find_one(
        InvitationCode.id == code_id,
        InvitationCode.is_used == False,  # noqa: E712
        InvitationCode.is_active == True,  # noqa: E712
    ).update(
        Set(
            {
                InvitationCode.is_active: False,
                InvitationCode.revoked_at: datetime.now(timezone.utc),
                InvitationCode.revoked_by_user_id: str(user.id),
            }
        )
    )

    modified = getattr(result, "modified_count", None) or 0

    if not modified:
        entry = await InvitationCode.get(code_id)
        if not entry:
            raise HTTPException(**INVITATION_CODE_NOT_FOUND)
        raise HTTPException(**INVITATION_CODE_CANNOT_REVOKE)

    entry = await InvitationCode.get(code_id)
    creator_name = None
    if entry.created_by_user_id:
        try:
            creator = await User.get(PydanticObjectId(entry.created_by_user_id))
            creator_name = creator.full_name if creator else None
        except Exception:
            creator_name = None

    return invitation_code_to_response(entry, creator_name)


# ---------------------------------------------------------
# Development-only bootstrap endpoint — see gating notes above. Hidden
# from the OpenAPI schema entirely unless ALLOW_DEV_INVITATION_ENDPOINTS
# is explicitly set, and refuses to run once any super_admin exists even
# when enabled.
# ---------------------------------------------------------

@router.post("/dev-create", include_in_schema=ALLOW_DEV_INVITATION_ENDPOINTS)
async def dev_create_invitation_code(request: DevCreateInvitationCodeRequest):
    if not ALLOW_DEV_INVITATION_ENDPOINTS:
        raise HTTPException(**DEV_ENDPOINT_DISABLED)

    existing_super_admin = await User.find_one(User.role == "super_admin")
    if existing_super_admin is not None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Development invitation endpoint is only available before "
                "the first super_admin account exists"
            ),
        )

    normalized_code = request.code.strip().upper()
    existing_code = await InvitationCode.find_one(
        InvitationCode.code == normalized_code
    )
    if existing_code is not None:
        raise HTTPException(**INVITATION_CODE_ALREADY_EXISTS)

    new_code = InvitationCode(
        code=normalized_code,
        role=request.role,
        building_ids=request.building_ids,
        all_buildings=request.all_buildings,
        created_by_user_id=None,
    )
    await new_code.insert()

    return {
        "success": True,
        "message": "Invitation code created (development bootstrap mode)",
        "invitation_code": invitation_code_to_response(new_code),
    }
