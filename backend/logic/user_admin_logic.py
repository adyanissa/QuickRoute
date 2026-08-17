"""
Users & Access — the single place that decides who may manage whom, what a
role change is allowed to be, and what scope a role is allowed to carry.

Every rule lives here rather than in the route so the same decision cannot
drift between the list endpoint, the update endpoint and the delete
endpoint, and so a frontend that offers the wrong option can never turn
into an actual privilege escalation: the route validates through these
functions before it writes anything.

Two invariants this module exists to protect:

  1. ROLE HIERARCHY. A global_manager may never create, promote to,
     demote, edit or delete a super_admin. Super-admin account management
     is super_admin-only. This mirrors
     logic/invitation_code_logic.CREATABLE_ROLES_BY_CREATOR, which already
     enforces the same hierarchy for invitations — the two tables are kept
     deliberately identical so an account cannot be granted through one
     door what it is refused at the other.

  2. SCOPE NORMALIZATION. A role's scope shape is derived here, never
     accepted from the client. A building_manager always ends up with
     exactly one building_id and empty map_group_ids/map_ids; a promoted
     account never keeps the narrower scope of the role it left behind.
"""

from typing import Optional

from beanie import PydanticObjectId
from fastapi import HTTPException

from core.errors import FORBIDDEN_ROLE, BUILDING_NOT_FOUND, FORBIDDEN_BUILDING_SCOPE
from models.building_model import Building
from models.user_model import User


# Roles this feature administers. regular_user accounts are created by the
# public POST /api/auth/register flow and are deliberately NOT listed or
# managed here — this page is about administrators and their access, and
# listing every end user would both bury the administrators and widen the
# amount of personal data an admin screen exposes for no product reason.
ADMIN_TIER_ROLES = ("super_admin", "global_manager", "building_manager")

# Who may hand out which role. Identical by design to
# invitation_code_logic.CREATABLE_ROLES_BY_CREATOR minus regular_user
# (which is not assignable through this feature at all).
ASSIGNABLE_ROLES_BY_ACTOR: dict[str, set[str]] = {
    "super_admin": {"super_admin", "global_manager", "building_manager"},
    "global_manager": {"building_manager"},
}


def can_manage_users(actor: User) -> bool:
    """super_admin and global_manager only. building_manager administers a
    building, never the installation's accounts; regular_user has no admin
    surface at all."""
    return bool(actor) and actor.role in ("super_admin", "global_manager")


def require_can_manage_users(actor: User) -> None:
    if not can_manage_users(actor):
        raise HTTPException(**FORBIDDEN_ROLE)


def assert_may_act_on_target(actor: User, target: User) -> None:
    """The super-admin protection, applied to every mutation (edit AND
    delete). A global_manager is refused before any field is even looked
    at, so it cannot demote, rename, rescope or remove a super_admin."""
    if target.role == "super_admin" and actor.role != "super_admin":
        raise HTTPException(**FORBIDDEN_ROLE)


def assert_may_assign_role(actor: User, new_role: str) -> None:
    """Blocks promotion beyond the actor's own authority — including the
    self-promotion case, since a global_manager is not in the table for
    'super_admin' regardless of which account it is editing."""
    if new_role not in ASSIGNABLE_ROLES_BY_ACTOR.get(actor.role, set()):
        raise HTTPException(**FORBIDDEN_ROLE)


async def assert_not_last_super_admin(target: User) -> None:
    """A QuickRoute installation must always retain at least one account
    that can administer it. Applied to deletion AND to demotion — losing
    the last super_admin by editing its role would strand the system just
    as completely as deleting it."""
    if target.role != "super_admin":
        return

    remaining = await User.find(User.role == "super_admin").count()
    if remaining <= 1:
        raise HTTPException(
            status_code=409,
            detail="This is the last Super Admin account and cannot be removed or demoted.",
        )


def assert_not_self(actor: User, target: User) -> None:
    """An admin cannot delete the account it is currently signed in as —
    a one-click way to lock yourself out mid-session."""
    if str(actor.id) == str(target.id):
        raise HTTPException(
            status_code=409,
            detail="You cannot delete the account you are currently signed in with.",
        )


async def resolve_scope_for_role(
    actor: User, role: str, building_id: Optional[str]
) -> dict:
    """Derives the persisted scope for `role`. The client's own scope
    fields are never trusted — only the single `building_id` a
    building_manager assignment needs, and even that is validated to exist
    AND to be inside the actor's own authorized scope, so an edited
    request cannot assign a building the actor could not otherwise reach.

    Returns the exact set of User scope fields to write, so a role change
    can never leave the previous role's narrower or wider scope behind
    (the "stale building_ids / map_group_ids / map_ids" problem).
    """

    # Imported here rather than at module import time: core.auth_deps
    # imports models.user_model, and a top-level import would close an
    # import cycle through this module's own model imports.
    from core.auth_deps import user_can_access_building

    if role == "super_admin":
        # System-wide by definition — no per-building selection exists.
        return {
            "building_ids": [],
            "all_buildings": True,
            "map_group_ids": [],
            "map_ids": [],
        }

    if role == "global_manager":
        # Scope shape (c) from core/auth_deps.py: an empty building list on
        # a global_manager means "project-wide by role", which is what this
        # product means by Global Manager. Any building/map-group/map scope
        # from a previous role is cleared.
        return {
            "building_ids": [],
            "all_buildings": False,
            "map_group_ids": [],
            "map_ids": [],
        }

    if role == "building_manager":
        # EXACTLY ONE building — the whole point of the role. Assigning the
        # building (not the maps that happen to exist inside it today) is
        # what makes future uploads automatically visible to the manager.
        if not building_id:
            raise HTTPException(
                status_code=400,
                detail="A Building Manager must be assigned exactly one building.",
            )

        try:
            building = await Building.get(PydanticObjectId(building_id))
        except Exception:
            building = None

        if not building:
            raise HTTPException(**BUILDING_NOT_FOUND)

        if not user_can_access_building(actor, building_id):
            raise HTTPException(**FORBIDDEN_BUILDING_SCOPE)

        return {
            "building_ids": [building_id],
            "all_buildings": False,
            # Legacy map/map-group narrowing is deliberately cleared on an
            # explicit edit: under the final rule a Building Manager owns
            # the whole building, and leaving a stale map_ids list would
            # silently keep hiding newly uploaded floors.
            "map_group_ids": [],
            "map_ids": [],
        }

    raise HTTPException(**FORBIDDEN_ROLE)


def describe_scope(user: User) -> str:
    """A stable machine-readable summary of what an account's persisted
    scope actually is, so the UI can render honest responsibility text —
    including for legacy accounts whose stored shape predates the
    one-building rule. Never guesses: an account narrowed by map_ids is
    reported as such rather than being displayed as a plain building
    manager."""
    if user.role == "super_admin":
        return "system_wide"
    if user.role == "global_manager":
        return "all_buildings" if user.all_buildings else (
            "buildings" if user.building_ids else "project_wide"
        )
    if user.role == "building_manager":
        if user.map_ids:
            return "legacy_maps"
        if user.map_group_ids:
            return "legacy_map_groups"
        if len(user.building_ids or []) > 1:
            return "legacy_multi_building"
        if user.building_ids:
            return "building"
        return "unassigned"
    return "none"
