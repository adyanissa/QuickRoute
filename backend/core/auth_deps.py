"""
FastAPI dependencies for JWT authentication and role/building authorization.

Kept separate from core/security.py (token encode/decode + password hashing)
so route files only need to import the small set of dependency functions
they actually use.
"""

from typing import Optional

from beanie import PydanticObjectId
from fastapi import Depends, HTTPException, Request

from core.errors import (
    NOT_AUTHENTICATED,
    INVALID_OR_EXPIRED_TOKEN,
    FORBIDDEN_ROLE,
    FORBIDDEN_BUILDING_SCOPE,
)
from core.security import TokenError, decode_access_token
from models.user_model import User


def _extract_bearer_token(request: Request) -> Optional[str]:
    header = request.headers.get("Authorization")

    if not header or not header.lower().startswith("bearer "):
        return None

    return header.split(" ", 1)[1].strip() or None


async def get_current_user(request: Request) -> User:
    """
    Resolve the authenticated User document from the request's
    `Authorization: Bearer <token>` header. Raises 401 when the header is
    missing, the token is invalid/expired, or the user no longer exists.
    """

    token = _extract_bearer_token(request)

    if not token:
        raise HTTPException(**NOT_AUTHENTICATED)

    try:
        payload = decode_access_token(token)
    except TokenError as error:
        raise HTTPException(**INVALID_OR_EXPIRED_TOKEN) from error

    user_id = payload.get("sub")

    if not user_id:
        raise HTTPException(**INVALID_OR_EXPIRED_TOKEN)

    try:
        user = await User.get(PydanticObjectId(user_id))
    except Exception as error:
        raise HTTPException(**INVALID_OR_EXPIRED_TOKEN) from error

    if not user:
        raise HTTPException(**INVALID_OR_EXPIRED_TOKEN)

    return user


def require_roles(*allowed_roles: str):
    """
    Dependency factory: 401 if not authenticated, 403 if the authenticated
    user's role is not one of `allowed_roles`.
    """

    async def _dependency(user: User = Depends(get_current_user)) -> User:
        if user.role not in allowed_roles:
            raise HTTPException(**FORBIDDEN_ROLE)
        return user

    return _dependency


# Any admin-tier role — used for actions that are safe for every admin
# level to perform (e.g. reading admin-only data).
require_any_admin = require_roles(
    "super_admin", "global_manager", "building_manager"
)

# Only the two "global" tiers — used for actions that affect shared
# infrastructure not scoped to a single building (map upload/drawing the
# navigation graph, creating buildings, issuing invitation codes).
require_global_admin = require_roles("super_admin", "global_manager")


def user_can_manage_building(user: User, building_id: str) -> bool:
    if user.role in ("super_admin", "global_manager"):
        return True

    if user.role == "building_manager":
        return user.all_buildings or building_id in user.building_ids

    return False


async def require_building_access(
    building_id: str,
    user: User = Depends(get_current_user),
) -> User:
    """
    Dependency for building-scoped mutation endpoints (rooms, location
    codes). super_admin/global_manager always pass; building_manager must
    have the building in their assigned building_ids (or all_buildings);
    regular_user is always rejected.
    """

    if user.role == "regular_user":
        raise HTTPException(**FORBIDDEN_ROLE)

    if not user_can_manage_building(user, building_id):
        raise HTTPException(**FORBIDDEN_BUILDING_SCOPE)

    return user
