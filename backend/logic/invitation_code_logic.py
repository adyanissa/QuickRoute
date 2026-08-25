"""
Invitation Code business logic: secure code generation, the creator
permission hierarchy (who may issue a code for which role/buildings),
status precedence, and atomic single-use consumption at signup.

Kept separate from routes/invitation_code_routes.py so the atomic
consumption helper can also be imported by logic/auth_logic.py without a
route-layer <-> route-layer import.
"""

import secrets
import string
from datetime import datetime, timezone
from typing import Optional

from beanie import PydanticObjectId
from beanie.operators import Set
from fastapi import HTTPException

from core.errors import (
    BUILDING_NOT_FOUND,
    FORBIDDEN_ROLE,
    FORBIDDEN_BUILDING_SCOPE,
    INVALID_BUILDING_SCOPE_FOR_ROLE,
)
from models.building_model import Building
from models.invitation_code_model import InvitationCode, InvitationRole
from models.user_model import User


# ---------------------------------------------------------
# Secure code generation
# ---------------------------------------------------------

def generate_random_code(length: int = 8) -> str:
    # Cryptographically secure (secrets module), unambiguous uppercase
    # alphanumeric alphabet — matches the pattern already used for
    # Location Codes (routes/location_code_routes.py:_generate_code_candidate).
    characters = string.ascii_uppercase + string.digits
    random_part = "".join(secrets.choice(characters) for _ in range(length))
    return f"QR-{random_part}"


async def generate_unique_code(custom_code: Optional[str] = None) -> str:
    """
    Returns a code guaranteed unique against the current invitation_codes
    collection. If `custom_code` is given (already normalized to upper/
    trimmed by the schema validator), it is used as-is after a uniqueness
    check; otherwise a secure random code is generated and retried on the
    rare collision.
    """

    if custom_code:
        existing = await InvitationCode.find_one(InvitationCode.code == custom_code)
        if existing:
            raise HTTPException(
                status_code=409,
                detail="This invitation code already exists, choose another",
            )
        return custom_code

    for _attempt in range(10):
        candidate = generate_random_code()
        existing = await InvitationCode.find_one(InvitationCode.code == candidate)
        if not existing:
            return candidate

    raise HTTPException(
        status_code=500,
        detail="Could not generate a unique invitation code, try again",
    )


# ---------------------------------------------------------
# Creator permission hierarchy
# ---------------------------------------------------------

# Which roles each creator role is allowed to mint a code for. Anything
# not listed here (building_manager, regular_user as creators) is
# forbidden entirely at the route dependency level (require_global_admin),
# but this table is also enforced directly so it stays correct even if the
# route-level dependency ever changes.
# Final admin user/access model: the ADMIN invitation UI no longer offers
# `regular_user` (see frontend utils/invitationCodeFormHelpers.js) because
# an ordinary QuickRoute visitor is never invited by an administrator —
# they self-register through POST /api/auth/register, which needs no code
# at all. The role deliberately REMAINS creatable here: it is not a
# privileged role, existing regular_user invitations must keep validating,
# and the requirement was explicitly about the admin choices rather than
# destroying the role. Privileged assignment is what this table guards,
# and that hierarchy is unchanged.
CREATABLE_ROLES_BY_CREATOR: dict[str, set[str]] = {
    "super_admin": {"super_admin", "global_manager", "building_manager", "regular_user"},
    "global_manager": {"building_manager", "regular_user"},
}


async def validate_role_and_scope_for_creation(
    creator: User,
    role: InvitationRole,
    all_buildings: bool,
    building_ids: list[str],
    map_group_ids: Optional[list[str]] = None,
    map_ids: Optional[list[str]] = None,
) -> None:
    """
    Enforces the full creator permission + building/map-group/map-scope
    hierarchy from the spec. Raises HTTPException on any violation. Does
    not mutate anything — pure validation, called before an InvitationCode
    is built.

    map_group_ids/map_ids (RBAC/dashboard cleanup task, Phase 2/4) are
    additive: only ever meaningful for building_manager invitations (the
    role Phase 2 defines fine-grained map/map-group scoping for), and are
    validated against core.auth_deps.get_accessible_building_ids/
    check_map_group_access/check_map_access so a creator can never narrow
    an invitation to a map/map-group they themselves cannot reach — the
    exact same "no inviter may grant access beyond their own scope" rule
    already enforced below for building_ids.
    """

    map_group_ids = list(map_group_ids or [])
    map_ids = list(map_ids or [])

    allowed_roles = CREATABLE_ROLES_BY_CREATOR.get(creator.role, set())
    if role not in allowed_roles:
        raise HTTPException(**FORBIDDEN_ROLE)

    if role == "super_admin":
        # System-wide by definition — no individual building/map-group/map
        # selection.
        if not all_buildings or building_ids or map_group_ids or map_ids:
            raise HTTPException(**INVALID_BUILDING_SCOPE_FOR_ROLE)

    elif role == "global_manager" and all_buildings:
        # RBAC/dashboard cleanup task, Phase 3: "no inviter may grant
        # all_buildings=True unless authorized" — only super_admin, or a
        # global_manager who ALREADY has all_buildings=True themselves, may
        # mint an unrestricted global_manager invitation. A global_manager
        # scoped to specific building_ids can still invite another
        # global_manager, just never with all_buildings=True (they'd be
        # granting more than they themselves have).
        if creator.role != "super_admin" and not creator.all_buildings:
            raise HTTPException(**INVALID_BUILDING_SCOPE_FOR_ROLE)

    if role == "global_manager":
        # All-buildings or a specific set is fine; both empty (global
        # scope purely by role, matching how global_manager users already
        # bypass per-building checks via user_can_manage_building) is also
        # fine. map_group_ids/map_ids are not a global_manager concept
        # (Phase 2 only defines them for building_manager) — reject rather
        # than silently ignore, so an admin UI bug can't produce an
        # invitation whose stored scope doesn't match what was intended.
        if map_group_ids or map_ids:
            raise HTTPException(**INVALID_BUILDING_SCOPE_FOR_ROLE)

    elif role == "building_manager":
        if all_buildings:
            raise HTTPException(**INVALID_BUILDING_SCOPE_FOR_ROLE)
        # Final rule: a Building Manager administers EXACTLY ONE building.
        # Assigning the building (rather than the maps inside it) is what
        # makes floors uploaded later automatically visible to them, and
        # exactly one keeps the scope boundary unambiguous.
        if len(building_ids) != 1:
            raise HTTPException(
                status_code=400,
                detail="A Building Manager invitation must assign exactly one building.",
            )

    else:
        # regular_user: no admin scope concept at all.
        if map_group_ids or map_ids:
            raise HTTPException(**INVALID_BUILDING_SCOPE_FOR_ROLE)

    # Every referenced building must exist, and the creator must actually
    # be authorized to manage it. RBAC/dashboard cleanup task, Phase 3:
    # switched from the legacy user_can_manage_building (which treats
    # global_manager as unconditionally authorized for every building) to
    # the stricter, spec-accurate user_can_access_building — a
    # global_manager restricted to specific building_ids can no longer
    # mint an invitation for a building outside that set, satisfying "no
    # inviter may grant access outside their own scope" for real, not just
    # for building_manager.
    from core.auth_deps import user_can_access_building

    for building_id in building_ids:
        try:
            building = await Building.get(PydanticObjectId(building_id))
        except Exception:
            building = None

        if not building:
            raise HTTPException(**BUILDING_NOT_FOUND)

        if not user_can_access_building(creator, building_id):
            raise HTTPException(**FORBIDDEN_BUILDING_SCOPE)

    # map_group_ids/map_ids must each belong to one of the SAME
    # building_ids just validated above (never a stray map/map-group in a
    # building the creator didn't even list, let alone one they can't
    # manage) — this keeps the invitation internally consistent, not just
    # individually-authorized.
    if map_group_ids:
        from models.map_group_model import MapGroup

        for map_group_id in map_group_ids:
            try:
                map_group = await MapGroup.get(PydanticObjectId(map_group_id))
            except Exception:
                map_group = None

            if not map_group:
                raise HTTPException(
                    status_code=404, detail=f"Map group {map_group_id} not found"
                )
            if map_group.building_id not in building_ids:
                raise HTTPException(**FORBIDDEN_BUILDING_SCOPE)

    if map_ids:
        from models.map_model import Map

        for map_id in map_ids:
            try:
                map_item = await Map.get(PydanticObjectId(map_id))
            except Exception:
                map_item = None

            if not map_item:
                raise HTTPException(status_code=404, detail=f"Map {map_id} not found")
            if map_item.building_id not in building_ids:
                raise HTTPException(**FORBIDDEN_BUILDING_SCOPE)


# ---------------------------------------------------------
# Status precedence
# ---------------------------------------------------------

def compute_invitation_code_status(entry: InvitationCode) -> str:
    """
    Single source of truth for status precedence: used > revoked >
    expired > active. Once used/revoked/expired, a code can never report
    back as active.
    """

    if entry.is_used:
        return "used"

    if not entry.is_active:
        return "revoked"

    if entry.expires_at is not None:
        expires_at = entry.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at <= datetime.now(timezone.utc):
            return "expired"

    return "active"


# ---------------------------------------------------------
# Atomic single-use consumption (used by logic/auth_logic.py at signup)
# ---------------------------------------------------------

class InvitationCodeConsumptionError(Exception):
    """Raised when a code cannot be validated/reserved for signup."""

    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


async def find_and_validate_code_for_signup(
    raw_code: str, email: str
) -> InvitationCode:
    """
    Looks up a code by its normalized (trimmed/uppercased) form and runs
    every pre-reservation check (exists, active, not used, not expired,
    not revoked, intended-email match). Does NOT reserve/consume it — call
    reserve_invitation_code_for_signup() next, atomically, right before
    creating the user.
    """

    normalized = (raw_code or "").strip().upper()

    entry = await InvitationCode.find_one(InvitationCode.code == normalized)
    if entry is None:
        raise InvitationCodeConsumptionError(404, "Invalid invitation code")

    status_now = compute_invitation_code_status(entry)

    if status_now == "used":
        raise InvitationCodeConsumptionError(400, "Invitation code already used")
    if status_now == "revoked":
        raise InvitationCodeConsumptionError(400, "This invitation code has been revoked")
    if status_now == "expired":
        raise InvitationCodeConsumptionError(400, "This invitation code has expired")

    if entry.intended_email:
        normalized_email = (email or "").strip().lower()
        if normalized_email != entry.intended_email:
            raise InvitationCodeConsumptionError(
                403,
                "This invitation code is restricted to a different email address",
            )

    return entry


async def reserve_invitation_code_for_signup(
    code_id: PydanticObjectId, user_id: str, email: str
) -> bool:
    """
    Atomically flips is_used False -> True in a single conditional
    update_one at the driver level (Beanie's find_one(...).update(Set(...))
    compiles to one atomic MongoDB update_one call), so two concurrent
    signup requests for the same code can never both succeed: only the
    request whose update actually matches a document with is_used==False
    gets modified_count == 1.
    """

    result = await InvitationCode.find_one(
        InvitationCode.id == code_id,
        InvitationCode.is_used == False,  # noqa: E712
        InvitationCode.is_active == True,  # noqa: E712
    ).update(
        Set(
            {
                InvitationCode.is_used: True,
                InvitationCode.used_at: datetime.now(timezone.utc),
                InvitationCode.used_by_user_id: user_id,
                InvitationCode.used_by_email: (email or "").strip().lower(),
            }
        )
    )

    modified = getattr(result, "modified_count", None)
    if modified is None:
        modified = getattr(result, "matched_count", 0)

    return bool(modified)


async def release_invitation_code_reservation(code_id: PydanticObjectId) -> None:
    """
    Compensating rollback: if user creation fails *after* the code was
    successfully reserved above, this reverts the reservation so the code
    is not incorrectly burned.
    """

    await InvitationCode.find_one(InvitationCode.id == code_id).update(
        Set(
            {
                InvitationCode.is_used: False,
                InvitationCode.used_at: None,
                InvitationCode.used_by_user_id: None,
                InvitationCode.used_by_email: None,
            }
        )
    )
