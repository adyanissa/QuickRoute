"""
FastAPI dependencies for JWT authentication and role/building/map
authorization.

Kept separate from core/security.py (token encode/decode + password hashing)
so route files only need to import the small set of dependency functions
they actually use.

RBAC/dashboard cleanup task, Phase 1 (centralized authorization): this file
now has two layers of scope check, both real and both used by current code:

  1. Building-level (pre-existing): user_can_manage_building() /
     require_building_access() — global_manager is treated as unrestricted
     here, matching the original, already-shipped behavior of every call
     site that predates this task (room_routes.py's Sync Rooms action,
     map_routes.py's OCR-suggest endpoint). Left untouched on purpose so
     those existing call sites never change behavior out from under them.

  2. Building/map-group/map-level (new, stricter, spec-accurate):
     user_can_access_building() and everything built on it below —
     a global_manager that has been given an explicit building list is
     scoped to it (unless all_buildings=True), exactly as the RBAC spec
     requires, and building_manager is further narrowed by
     map_group_ids/map_ids when those are non-empty (map_ids is the most
     restrictive: when set, it alone decides map-level access). Every NEW
     authorization call site added by this task uses this stricter set of
     helpers, never the legacy one.

  THE THREE global_manager SCOPE SHAPES (resolved; this section previously
  recorded case (c) below as a "KNOWN OPERATIONAL RISK"). An invitation
  code can legitimately produce any of these three, so all three need a
  defined meaning:

    a) all_buildings=True, building_ids=[]  ->  unrestricted, every
       building. Mintable only by a super_admin, or by a global_manager
       who already has all_buildings=True (see
       logic/invitation_code_logic.validate_role_and_scope_for_creation).

    b) all_buildings=False, building_ids=[X, Y]  ->  restricted to exactly
       those buildings, the same way a building_manager is. A
       global_manager does NOT get a blanket pass from its role name once
       it has been given an explicit building list.

    c) all_buildings=False, building_ids=[]  ->  PROJECT-WIDE BY ROLE.
       This is the default shape an ordinary global_manager invitation
       produces, and logic/invitation_code_logic.py explicitly allows it
       and documents its meaning: "both empty (global scope purely by
       role, matching how global_manager users already bypass per-building
       checks via user_can_manage_building) is also fine."

  Case (c) used to fall through to "no scope at all", which directly
  contradicted the invitation layer that creates it, and produced a real
  self-lockout rather than a mere tightening: a global_manager would sign
  up with a perfectly ordinary invitation code, create a map (POST
  /api/maps and /api/maps/upload find-or-create a Building from
  campus/title whenever no building_id is supplied), and then be 403'd out
  of the very map they had just created — the freshly auto-created
  building could not possibly already be in their empty building_ids list.
  Every scoped read and mutation for such an account failed the same way.

  Case (c) is now resolved in favour of the meaning the invitation layer
  already documents: an empty building list on a global_manager means "not
  narrowed", never "narrowed to nothing". Narrowing a global_manager is
  done by giving it an explicit building_ids list (case b), which stays
  fully enforced. building_manager is unchanged in all three cases — it
  can never reach case (c) at all, because
  validate_role_and_scope_for_creation rejects a building_manager
  invitation that lists no buildings, and an empty list there would still
  mean "no access", never "all access". regular_user is unchanged.
"""

from typing import List, Optional

from beanie import PydanticObjectId
from fastapi import Depends, HTTPException, Request

from core.errors import (
    NOT_AUTHENTICATED,
    INVALID_OR_EXPIRED_TOKEN,
    FORBIDDEN_ROLE,
    FORBIDDEN_BUILDING_SCOPE,
    BUILDING_NOT_FOUND,
    MAP_GROUP_NOT_FOUND,
    MAP_GROUP_FORBIDDEN_SCOPE,
    MAP_NOT_FOUND,
    FORBIDDEN_MAP_SCOPE,
    ROOM_NOT_FOUND,
    ROUTE_POINT_NOT_FOUND,
    ROUTE_EDGE_NOT_FOUND,
    VERTICAL_CONNECTOR_NOT_FOUND,
    SEMANTIC_ANALYSIS_NOT_FOUND,
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


async def get_current_user_optional(request: Request) -> Optional[User]:
    """
    Same resolution as get_current_user(), but returns None instead of
    raising when there is no bearer token at all — for endpoints that must
    stay reachable by anonymous end users (e.g. the public kiosk-style
    wayfinding flow that resolves RoutePoints/Rooms directly by id/filter,
    with no login) while STILL applying admin scope restrictions when the
    caller happens to be an authenticated admin-tier user (see
    routes/route_point_routes.py's GET endpoints for the actual use).

    A present-but-invalid/expired token still raises 401 (never silently
    downgrades to "anonymous") — only a genuinely absent Authorization
    header is treated as anonymous.
    """

    token = _extract_bearer_token(request)

    if not token:
        return None

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


# ===========================================================
# RBAC/dashboard cleanup task, Phase 1 — centralized, spec-accurate
# resource-scope authorization. Every helper below is deliberately never
# used by any pre-existing call site above this line; they are new,
# stricter, and additive. See the module docstring for exactly how this
# differs from user_can_manage_building()/require_building_access() above.
# ===========================================================


def require_super_admin_role(user: User) -> None:
    """Raises 403 unless `user` is a super_admin. Plain function (not a
    FastAPI dependency) so it can also be called from inside a route body
    that needs to gate only ONE branch of a shared endpoint on super_admin,
    without needing a second Depends()-only route."""
    if user.role != "super_admin":
        raise HTTPException(**FORBIDDEN_ROLE)


async def require_super_admin(user: User = Depends(get_current_user)) -> User:
    """Dependency for genuinely super_admin-only actions (creating/deleting
    Buildings, managing other admins' roles, anything the spec calls
    'Super Admin-only'). global_manager/building_manager/regular_user are
    all rejected — this is intentionally narrower than require_global_admin
    (super_admin OR global_manager), which remains available for the many
    existing endpoints that are correctly meant to allow both."""
    require_super_admin_role(user)
    return user


def get_accessible_building_ids(user: User) -> Optional[List[str]]:
    """Returns the list of building_ids `user` may access, or None to mean
    "every building" (super_admin always; global_manager/building_manager
    only when all_buildings=True — building_manager invitations can never
    actually set all_buildings=True per
    logic/invitation_code_logic.validate_role_and_scope_for_creation, so in
    practice this is only ever reached for super_admin/global_manager, but
    the check is written generically rather than hard-coding that
    assumption). regular_user always gets an empty list — never None,
    never "all" — since a regular_user has no admin scope at all."""
    if user.role == "super_admin":
        return None
    if user.role in ("global_manager", "building_manager") and user.all_buildings:
        return None
    # global_manager scope shape (c) — see the module docstring: an empty
    # building list means "not narrowed", not "narrowed to nothing", so it
    # must return None ("every building") here rather than [] ("no
    # buildings"). Returning [] made every scoped LIST endpoint silently
    # come back empty for an ordinary global_manager.
    if user.role == "global_manager" and not (user.building_ids or []):
        return None
    if user.role in ("global_manager", "building_manager"):
        return list(user.building_ids or [])
    return []


def user_can_access_building(user: User, building_id: Optional[str]) -> bool:
    """Spec-accurate building-level check (see the module docstring for how
    this differs from the legacy user_can_manage_building above, and for
    the three global_manager scope shapes).

    A global_manager that has been given an explicit building_ids list is
    scoped to it exactly like a building_manager — it gets no blanket pass
    from its role name alone. A global_manager with NO building list at all
    (scope shape (c), the default an ordinary invitation produces) is
    project-wide, which is the meaning
    logic/invitation_code_logic.validate_role_and_scope_for_creation
    already documents when it deliberately accepts that shape."""
    if user.role == "super_admin":
        return True

    # Scope shape (c): project-wide by role. Checked before the
    # `not building_id` guard below so that a resource with no building_id
    # at all (legacy Maps predate Map.building_id) stays reachable for a
    # project-wide global_manager, exactly as it is for a super_admin.
    if user.role == "global_manager" and not (user.building_ids or []):
        return True

    # Beyond this point the caller must name a building for anyone other
    # than the two project-wide tiers above.
    if not building_id:
        return False

    if user.role in ("global_manager", "building_manager"):
        return bool(user.all_buildings) or building_id in (user.building_ids or [])
    return False


def _building_and_group_allowed(
    user: User, building_id: Optional[str], map_group_id: Optional[str]
) -> bool:
    """Shared building + optional map-group scope check, used by both
    user_can_access_map_group() and the vertical-connector/semantic-
    analysis map-group-scoped checks below (both of those resources carry
    building_id + map_group_id directly, without needing a MapGroup
    document fetch)."""
    if not user_can_access_building(user, building_id):
        return False
    if user.role != "building_manager":
        return True
    # building_manager: map_group_ids (when non-empty) narrows further.
    # map_ids is checked separately by callers that have an actual map_id
    # of their own to compare (a map-group-scoped resource has no single
    # map_id) — a building_manager restricted only via map_ids (no
    # map_group_ids at all) is deliberately denied group/connector/
    # analysis-level access here, since "only these specific maps" cannot
    # safely be interpreted as "and therefore also every map group those
    # maps happen to belong to".
    if user.map_group_ids:
        return bool(map_group_id) and map_group_id in user.map_group_ids
    if user.map_ids:
        return False
    return True


def user_can_access_map_group(user: User, map_group) -> bool:
    """`map_group` is a models.map_group_model.MapGroup document (or
    anything with .building_id/.id attributes)."""
    if user.role == "super_admin":
        return True
    return _building_and_group_allowed(
        user, getattr(map_group, "building_id", None), str(getattr(map_group, "id", "") or "")
    )


def user_can_access_map(user: User, map_item) -> bool:
    """`map_item` is a models.map_model.Map document (or anything with
    .building_id/.map_group_id/.id attributes). map_ids is the MOST
    restrictive scope for a building_manager: when non-empty, it alone
    decides map-level access (map_group_ids is ignored once map_ids is
    set), matching the spec's explicit "map_ids is the most restrictive
    scope" requirement."""
    if user.role == "super_admin":
        return True
    building_id = getattr(map_item, "building_id", None)
    if not user_can_access_building(user, building_id):
        return False
    if user.role != "building_manager":
        return True
    map_id_str = str(getattr(map_item, "id", "") or "")
    if user.map_ids:
        return map_id_str in user.map_ids
    if user.map_group_ids:
        map_group_id = getattr(map_item, "map_group_id", None)
        return bool(map_group_id) and map_group_id in user.map_group_ids
    return True


async def require_building_scope_access(
    building_id: str,
    user: User = Depends(get_current_user),
) -> User:
    """Stricter, spec-accurate sibling of require_building_access() above —
    uses user_can_access_building() (global_manager IS scope-checked here)
    instead of the legacy user_can_manage_building(). Fetches nothing
    itself; callers that need to confirm the Building actually exists
    should do so separately (most routes already 404 on a missing Building
    before this would even run)."""
    if user.role == "regular_user":
        raise HTTPException(**FORBIDDEN_ROLE)
    if not user_can_access_building(user, building_id):
        raise HTTPException(**FORBIDDEN_BUILDING_SCOPE)
    return user


async def require_map_group_access(map_group_id: str, user: User = Depends(get_current_user)):
    """Fetches the MapGroup and enforces user_can_access_map_group(). 404
    before 403 (a genuinely-existing, out-of-scope group returns 403; a
    nonexistent id always returns 404 regardless of the caller's scope)."""
    from models.map_group_model import MapGroup

    if user.role == "regular_user":
        raise HTTPException(**FORBIDDEN_ROLE)

    try:
        group = await MapGroup.get(PydanticObjectId(map_group_id))
    except Exception:
        group = None
    if not group:
        raise HTTPException(**MAP_GROUP_NOT_FOUND)
    if not user_can_access_map_group(user, group):
        raise HTTPException(**MAP_GROUP_FORBIDDEN_SCOPE)
    return group


async def require_map_access(map_id: str, user: User = Depends(get_current_user)):
    """Fetches the Map and enforces user_can_access_map(). Plain async
    function — call it directly as
    `map_item = await require_map_access(map_id, user)` from inside a route
    body (most Map/RoutePoint/RouteEdge routes already do their own
    Map.get() 404 handling inline), or use Depends(require_map_access) in
    any route whose path parameter is literally named `map_id`."""
    from models.map_model import Map

    if user.role == "regular_user":
        raise HTTPException(**FORBIDDEN_ROLE)

    try:
        map_item = await Map.get(PydanticObjectId(map_id))
    except Exception:
        map_item = None
    if not map_item:
        raise HTTPException(**MAP_NOT_FOUND)
    if not user_can_access_map(user, map_item):
        raise HTTPException(**FORBIDDEN_MAP_SCOPE)
    return map_item


async def require_room_access(room_id: str, user: User = Depends(get_current_user)):
    """Fetches the Room and validates ownership through its Map when the
    Room has one (map-based destination placement), falling back to a
    plain building-level check for a legacy/manual-entry Room that has no
    map_id at all (Room.map_id is optional — see models/room_model.py)."""
    from models.room_model import Room
    from models.map_model import Map

    if user.role == "regular_user":
        raise HTTPException(**FORBIDDEN_ROLE)

    try:
        room = await Room.get(PydanticObjectId(room_id))
    except Exception:
        room = None
    if not room:
        raise HTTPException(**ROOM_NOT_FOUND)

    if user.role == "super_admin":
        return room

    if room.map_id:
        try:
            map_item = await Map.get(PydanticObjectId(room.map_id))
        except Exception:
            map_item = None
        # An orphaned map_id (Map deleted but Room wasn't) falls back to
        # the building check below rather than hard-failing.
        if map_item is not None:
            if not user_can_access_map(user, map_item):
                raise HTTPException(**FORBIDDEN_BUILDING_SCOPE)
            return room

    if not user_can_access_building(user, room.building_id):
        raise HTTPException(**FORBIDDEN_BUILDING_SCOPE)
    return room


async def require_route_point_access(point_id: str, user: User = Depends(get_current_user)):
    """Fetches the RoutePoint and validates ownership through its Map
    (RoutePoint.map_id is always set, unlike Room's). Falls back to the
    point's own denormalized building_id only if its Map has been deleted
    out from under it."""
    from models.route_point_model import RoutePoint
    from models.map_model import Map

    if user.role == "regular_user":
        raise HTTPException(**FORBIDDEN_ROLE)

    try:
        point = await RoutePoint.get(PydanticObjectId(point_id))
    except Exception:
        point = None
    if not point:
        raise HTTPException(**ROUTE_POINT_NOT_FOUND)

    if user.role == "super_admin":
        return point

    map_item = None
    try:
        map_item = await Map.get(PydanticObjectId(point.map_id))
    except Exception:
        map_item = None

    if map_item is not None:
        if not user_can_access_map(user, map_item):
            raise HTTPException(**FORBIDDEN_MAP_SCOPE)
        return point

    # Orphaned point (its Map no longer exists) — fall back to whatever
    # building_id was denormalized onto the point itself; deny outright if
    # even that is missing, rather than guessing.
    if not point.building_id or not user_can_access_building(user, point.building_id):
        raise HTTPException(**FORBIDDEN_BUILDING_SCOPE)
    return point


async def require_route_edge_access(edge_id: str, user: User = Depends(get_current_user)):
    """Fetches the RouteEdge and validates ownership through BOTH its
    map_id and (for a cross-floor transition edge) to_map_id, so a
    building_manager restricted via map_ids can't reach a transition edge
    by way of only one of its two floors being in scope."""
    from models.route_edge_model import RouteEdge
    from models.map_model import Map

    if user.role == "regular_user":
        raise HTTPException(**FORBIDDEN_ROLE)

    try:
        edge = await RouteEdge.get(PydanticObjectId(edge_id))
    except Exception:
        edge = None
    if not edge:
        raise HTTPException(**ROUTE_EDGE_NOT_FOUND)

    if user.role == "super_admin":
        return edge

    map_ids_to_check = [edge.map_id] + ([edge.to_map_id] if edge.to_map_id else [])
    any_map_found = False
    for map_id in map_ids_to_check:
        try:
            map_item = await Map.get(PydanticObjectId(map_id))
        except Exception:
            map_item = None
        if map_item is None:
            continue
        any_map_found = True
        if not user_can_access_map(user, map_item):
            raise HTTPException(**FORBIDDEN_MAP_SCOPE)

    if not any_map_found:
        raise HTTPException(**FORBIDDEN_MAP_SCOPE)

    return edge


async def require_vertical_connector_access(
    connector_id: str, user: User = Depends(get_current_user)
):
    """Fetches the VerticalConnector (which carries building_id +
    map_group_id directly, never a single map_id — it spans floors) and
    enforces the same building/map-group scope rule used for MapGroups."""
    from models.vertical_connector_model import VerticalConnector

    if user.role == "regular_user":
        raise HTTPException(**FORBIDDEN_ROLE)

    try:
        connector = await VerticalConnector.get(PydanticObjectId(connector_id))
    except Exception:
        connector = None
    if not connector:
        raise HTTPException(**VERTICAL_CONNECTOR_NOT_FOUND)

    if user.role == "super_admin":
        return connector

    if not _building_and_group_allowed(user, connector.building_id, connector.map_group_id):
        raise HTTPException(**FORBIDDEN_BUILDING_SCOPE)
    return connector


async def require_semantic_analysis_access(
    analysis_id: str, user: User = Depends(get_current_user)
):
    """Fetches the SemanticMapAnalysis and enforces scope through whichever
    of map_id/map_group_id it actually has (scope_type == "map" vs.
    "map_group" — see models/semantic_map_analysis_model.py). A
    building_manager restricted only via map_ids (no map_group_ids) is
    denied access to a map_group-scoped analysis, mirroring
    _building_and_group_allowed()'s same rule for connectors."""
    from models.semantic_map_analysis_model import SemanticMapAnalysis
    from models.map_model import Map

    if user.role == "regular_user":
        raise HTTPException(**FORBIDDEN_ROLE)

    analysis = await SemanticMapAnalysis.find_one(
        SemanticMapAnalysis.analysis_id == analysis_id
    )
    if not analysis:
        raise HTTPException(**SEMANTIC_ANALYSIS_NOT_FOUND)

    if user.role == "super_admin":
        return analysis

    if analysis.scope_type == "map" and analysis.map_id:
        try:
            map_item = await Map.get(PydanticObjectId(analysis.map_id))
        except Exception:
            map_item = None
        if map_item is not None:
            if not user_can_access_map(user, map_item):
                raise HTTPException(**FORBIDDEN_MAP_SCOPE)
            return analysis

    if not _building_and_group_allowed(user, analysis.building_id, analysis.map_group_id):
        raise HTTPException(**FORBIDDEN_BUILDING_SCOPE)
    return analysis
