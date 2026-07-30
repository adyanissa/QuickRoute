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
CREATABLE_ROLES_BY_CREATOR: dict[str, set[str]] = {
    "super_admin": {"super_admin", "global_manager", "building_manager", "regular_user"},
    "global_manager": {"building_manager", "regular_user"},
}


async def validate_role_and_scope_for_creation(
    creator: User,
    role: InvitationRole,
    all_buildings: bool,
    building_ids: list[str],
) -> None:
    """
    Enforces the full creator permission + building-scope hierarchy from
    the spec. Raises HTTPException on any violation. Does not mutate
    anything — pure validation, called before an InvitationCode is built.
    """

    allowed_roles = CREATABLE_ROLES_BY_CREATOR.get(creator.role, set())
    if role not in allowed_roles:
        raise HTTPException(**FORBIDDEN_ROLE)

    if role == "super_admin":
        # System-wide by definition — no individual building selection.
        if not all_buildings or building_ids:
            raise HTTPException(**INVALID_BUILDING_SCOPE_FOR_ROLE)

    elif role == "global_manager":
        # All-buildings or a specific set is fine; both empty (global
        # scope purely by role, matching how global_manager users already
        # bypass per-building checks via user_can_manage_building) is also
        # fine.
        pass

    elif role == "building_manager":
        if all_buildings:
            raise HTTPException(**INVALID_BUILDING_SCOPE_FOR_ROLE)
        if not building_ids:
            raise HTTPException(
                status_code=400,
                detail="Building manager invitation codes require at least one building",
            )

    # regular_user: no constraints — may optionally carry building_ids.

    # Every referenced building must exist, and the creator must actually
    # be authorized to manage it (defensive — with the current hierarchy
    # only super_admin/global_manager reach this function and both are
    # authorized for every building, but this generalizes correctly if
    # that ever changes, and directly satisfies the "creator cannot assign
    # a building outside their scope" requirement).
    from core.auth_deps import user_can_manage_building

    for building_id in building_ids:
        try:
            building = await Building.get(PydanticObjectId(building_id))
        except Exception:
            building = None

        if not building:
            raise HTTPException(**BUILDING_NOT_FOUND)

        if not user_can_manage_building(creator, building_id):
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
