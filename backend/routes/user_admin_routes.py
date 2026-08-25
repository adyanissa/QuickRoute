"""
Users & Access — administrative management of QuickRoute's administrator
accounts.

Authorization model (enforced here AND re-asserted inside
logic/user_admin_logic.py, so a route-level mistake cannot silently widen
anything):

  super_admin      full management of every administrator account
  global_manager   may list every administrator, but may only edit/delete
                   building_manager accounts, and may only ever assign the
                   building_manager role — it can neither create, promote
                   to, demote, rename nor delete a super_admin, including
                   itself
  building_manager no access at all (403) — it administers a building,
                   not the installation's accounts
  regular_user     no access at all (403)

Scope: `building_manager` accounts are administered by BUILDING, never by
map. Assigning the building (rather than the maps that exist inside it at
assignment time) is what makes maps uploaded later automatically visible
to that manager.

regular_user accounts are intentionally out of scope for this feature —
they are created by the public POST /api/auth/register flow, carry no
administrative access, and listing them here would bury the actual
administrators.
"""

from typing import List, Optional

from beanie import PydanticObjectId
from fastapi import APIRouter, Depends, HTTPException, Query, status

from core.auth_deps import get_current_user
from core.errors import FORBIDDEN_ROLE
from logic.user_admin_logic import (
    ADMIN_TIER_ROLES,
    assert_may_act_on_target,
    assert_may_assign_role,
    assert_not_last_super_admin,
    assert_not_self,
    describe_scope,
    require_can_manage_users,
    resolve_scope_for_role,
)
from models.building_model import Building
from models.user_model import User
from schemas.user_admin_schema import (
    AdminUserResponse,
    AdminUserUpdate,
    AssignedBuildingSummary,
)


router = APIRouter(prefix="/api/admin/users", tags=["Admin - Users & Access"])


async def require_users_admin(user: User = Depends(get_current_user)) -> User:
    """Route gate. Same role set as require_global_admin, but declared
    through the feature's own predicate so the two can diverge later
    without one silently inheriting the other's meaning."""
    require_can_manage_users(user)
    return user


def _may_mutate(actor: User, target: User) -> bool:
    try:
        assert_may_act_on_target(actor, target)
    except HTTPException:
        return False
    return True


async def _resolve_building_summaries(users: List[User]) -> dict:
    """One lookup for every building referenced by the listed accounts, so
    responsibility can be rendered as a real name instead of an ObjectId.
    A building that no longer exists simply resolves to nothing rather
    than breaking the list."""
    ids = set()
    for user in users:
        for building_id in user.building_ids or []:
            ids.add(building_id)

    if not ids:
        return {}

    object_ids = []
    for building_id in ids:
        try:
            object_ids.append(PydanticObjectId(building_id))
        except Exception:
            continue

    if not object_ids:
        return {}

    buildings = await Building.find({"_id": {"$in": object_ids}}).to_list()
    return {
        str(building.id): AssignedBuildingSummary(
            id=str(building.id),
            name=building.name_en,
            site=(building.campus or None),
        )
        for building in buildings
    }


def _to_response(
    user: User, actor: User, buildings_by_id: dict
) -> AdminUserResponse:
    assigned = None
    if user.role == "building_manager" and user.building_ids:
        assigned = buildings_by_id.get(user.building_ids[0])

    mutable = _may_mutate(actor, user)

    return AdminUserResponse(
        id=str(user.id),
        full_name=user.full_name,
        email=user.email,
        role=user.role,
        building_ids=list(user.building_ids or []),
        all_buildings=bool(user.all_buildings),
        map_group_ids=list(user.map_group_ids or []),
        map_ids=list(user.map_ids or []),
        assigned_building=assigned,
        scope_kind=describe_scope(user),
        created_at=user.created_at,
        can_edit=mutable,
        # Never offer to delete the account you are signed in with, and
        # never the last super_admin — both are re-checked server-side.
        can_delete=mutable and str(actor.id) != str(user.id),
    )


@router.get("", response_model=List[AdminUserResponse])
async def list_admin_users(
    search: Optional[str] = Query(default=None),
    role: Optional[str] = Query(default=None),
    actor: User = Depends(require_users_admin),
):
    query: dict = {"role": {"$in": list(ADMIN_TIER_ROLES)}}

    if role:
        if role not in ADMIN_TIER_ROLES:
            raise HTTPException(**FORBIDDEN_ROLE)
        query["role"] = role

    users = await User.find(query).to_list()

    if search:
        needle = search.strip().lower()
        if needle:
            users = [
                user
                for user in users
                if needle in (user.full_name or "").lower()
                or needle in (user.email or "").lower()
            ]

    users.sort(key=lambda u: ((u.full_name or "").lower(), u.email or ""))
    buildings_by_id = await _resolve_building_summaries(users)
    return [_to_response(user, actor, buildings_by_id) for user in users]


async def _load_admin_user_or_404(user_id: str) -> User:
    try:
        target = await User.get(PydanticObjectId(user_id))
    except Exception:
        target = None

    if not target or target.role not in ADMIN_TIER_ROLES:
        # A regular_user id is reported exactly like a nonexistent one:
        # this feature administers administrators, and confirming that
        # some other id exists would leak account existence for free.
        raise HTTPException(status_code=404, detail="User not found")

    return target


@router.get("/{user_id}", response_model=AdminUserResponse)
async def get_admin_user(user_id: str, actor: User = Depends(require_users_admin)):
    target = await _load_admin_user_or_404(user_id)
    buildings_by_id = await _resolve_building_summaries([target])
    return _to_response(target, actor, buildings_by_id)


@router.put("/{user_id}", response_model=AdminUserResponse)
async def update_admin_user(
    user_id: str,
    payload: AdminUserUpdate,
    actor: User = Depends(require_users_admin),
):
    target = await _load_admin_user_or_404(user_id)

    # Refused before any field is inspected: a global_manager may not
    # touch a super_admin at all.
    assert_may_act_on_target(actor, target)

    if payload.full_name is not None:
        target.full_name = payload.full_name.strip()

    new_role = payload.role or target.role

    if payload.role is not None and payload.role != target.role:
        assert_may_assign_role(actor, payload.role)
        # Demoting the last super_admin strands the installation exactly
        # as thoroughly as deleting it.
        if target.role == "super_admin":
            await assert_not_last_super_admin(target)

    # Scope is DERIVED from the (possibly new) role — never taken from the
    # client — so a role change can never leave the previous role's scope
    # behind, and a building_manager always ends up with exactly one
    # building and no map/map-group narrowing.
    building_id = payload.building_id
    if new_role == "building_manager" and building_id is None:
        # Unchanged role and no new building supplied: keep the current
        # assignment rather than forcing the caller to resend it.
        building_id = (target.building_ids or [None])[0]

    scope = await resolve_scope_for_role(actor, new_role, building_id)

    target.role = new_role
    target.building_ids = scope["building_ids"]
    target.all_buildings = scope["all_buildings"]
    target.map_group_ids = scope["map_group_ids"]
    target.map_ids = scope["map_ids"]

    await target.save()

    buildings_by_id = await _resolve_building_summaries([target])
    return _to_response(target, actor, buildings_by_id)


@router.delete("/{user_id}", status_code=status.HTTP_200_OK)
async def delete_admin_user(user_id: str, actor: User = Depends(require_users_admin)):
    target = await _load_admin_user_or_404(user_id)

    assert_may_act_on_target(actor, target)
    assert_not_self(actor, target)
    await assert_not_last_super_admin(target)

    await target.delete()

    # Invitation codes reference this account only through optional
    # display lookups (created_by_user_id -> name, resolved leniently),
    # and every code created since this feature also carries a
    # denormalized created_by_name, so the audit trail survives the
    # account being removed.
    return {"message": "User deleted successfully"}
