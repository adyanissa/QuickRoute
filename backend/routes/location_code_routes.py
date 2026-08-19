from datetime import datetime
from typing import Dict, List, Optional, Tuple

from beanie import PydanticObjectId
from fastapi import APIRouter, Depends, HTTPException, Query, status

from models.location_code_model import LocationCode
from models.map_model import Map
from models.building_model import Building
from models.route_point_model import RoutePoint
from models.user_model import User
from schemas.location_code_schema import (
    LocationCodeCreate,
    LocationCodeGenerate,
    LocationCodeUpdate,
    LocationCodeResponse,
    LocationCodeResolveResponse,
)
from services.room_location_code_service import (
    generate_location_code_candidate,
)
from core.auth_deps import (
    get_accessible_building_ids,
    get_current_user,
    require_any_admin,
    user_can_access_building,
    user_can_manage_building,
)
from core.errors import (
    LOCATION_CODE_NOT_FOUND,
    LOCATION_CODE_ALREADY_EXISTS,
    LOCATION_CODE_INACTIVE,
    BUILDING_NOT_FOUND,
    FORBIDDEN_BUILDING_SCOPE,
    FORBIDDEN_ROLE,
)


router = APIRouter(
    prefix="/api/location-codes",
    tags=["Location Codes"]
)


async def resolve_location_code_group_and_floor(map_id: str, route_point_id: str):
    """
    Resolved fresh from the linked Map/RoutePoint every time — never
    stored on LocationCode itself (see LocationCodeResponse.map_group_id/
    floor docstrings) — so a code always reflects its point's real,
    current floor rather than a value that could silently go stale.

    "Treat map_id as the authoritative floor source" — same rule already
    established for RoutePoint/RouteEdge floor consistency (see
    routes/route_point_routes.py's create_route_point). This was the
    actual bug behind "the code card says Floor 1 but the user's Current
    floor shows —": this function used to read ONLY route_point.floor,
    which can be null/stale for a point that predates floor tracking or
    was never backfilled, while the admin list's own display already
    fell back to the Map's floor (`entry.floor ?? map?.floor` in
    AdminLocationCodesScreen.jsx) — so the two disagreed. Falls back to
    the RoutePoint's own floor only when the Map itself has no floor
    recorded at all (a legacy map that predates floor tracking).
    """

    map_group_id = None
    map_floor = None
    point_floor = None

    try:
        map_item = await Map.get(PydanticObjectId(map_id))
        if map_item:
            map_group_id = map_item.map_group_id
            map_floor = map_item.floor
    except Exception:
        pass

    try:
        route_point = await RoutePoint.get(PydanticObjectId(route_point_id))
        if route_point:
            point_floor = route_point.floor
    except Exception:
        pass

    floor = map_floor if map_floor is not None else point_floor

    return map_group_id, floor


async def location_code_to_response(entry: LocationCode) -> LocationCodeResponse:
    map_group_id, floor = await resolve_location_code_group_and_floor(
        entry.map_id, entry.route_point_id
    )

    return LocationCodeResponse(
        id=str(entry.id),
        code=entry.code,
        building_id=entry.building_id,
        map_id=entry.map_id,
        route_point_id=entry.route_point_id,
        map_group_id=map_group_id,
        floor=floor,
        label=entry.label,
        is_active=entry.is_active,
        created_at=entry.created_at,
        updated_at=entry.updated_at,
    )


# ---------------------------------------------------------------------
# Batched enrichment — used ONLY by GET /api/location-codes.
#
# WHY THIS EXISTS
# ---------------
# location_code_to_response() is correct but asks the database two
# questions per code: Map.get() and RoutePoint.get(). Building a LIST that
# way costs 1 + 2N sequential round trips. Measured against a real
# inventory of ~146 codes that is ~293 round trips and close to a minute of
# pure Atlas latency for a response of a few hundred kilobytes.
#
# The list endpoint therefore asks the same two questions ONCE FOR ALL
# CODES, in at most two additional queries, and answers each code from
# memory. The resolution ladder below is a line-for-line mirror of
# resolve_location_code_group_and_floor(); that function and
# location_code_to_response() are deliberately left untouched and still
# serve every create / generate / get-by-id / update path exactly as
# before. GET /resolve/{code} has its own separate defensive re-check and
# is not affected by any of this.
#
# Query count: at most 3 (location_codes, maps, route_points), CONSTANT in
# the number of codes. A lookup whose input set is empty is skipped.
#
# The response is byte-identical to the old path — the companion test
# tests/test_location_codes_list_batching.py asserts equality against
# location_code_to_response() code by code.
# ---------------------------------------------------------------------


def _to_object_id(value) -> Optional[PydanticObjectId]:
    """
    Mirrors the `try: PydanticObjectId(...) except: treat as missing`
    behaviour resolve_location_code_group_and_floor() relies on, so a
    malformed or null stored id degrades to exactly the same result it
    does today rather than raising.
    """

    if not value:
        return None

    try:
        return PydanticObjectId(value)
    except Exception:  # noqa: BLE001 - a malformed id is a data problem
        return None


class LocationCodeListEnrichment:
    """
    Pre-fetched answers to the two per-code questions, keyed by the
    CANONICAL id string (str(document.id)) — the single-code path resolves
    through PydanticObjectId too, so keying any other way could disagree
    with it for a differently-formatted stored id.

    A missing entry means "not found", which is exactly the state the
    single-code path reaches when Map.get()/RoutePoint.get() returns None.
    """

    __slots__ = ("maps_by_id", "points_by_id")

    def __init__(
        self,
        maps_by_id: Dict[str, Map],
        points_by_id: Dict[str, RoutePoint],
    ) -> None:
        self.maps_by_id = maps_by_id
        self.points_by_id = points_by_id

    def group_and_floor(
        self, map_id: Optional[str], route_point_id: Optional[str]
    ) -> Tuple[Optional[str], Optional[int]]:
        """Same two INDEPENDENT lookups and the same precedence as
        resolve_location_code_group_and_floor() — see its docstring for why
        the Map's floor is authoritative and the RoutePoint's is only a
        fallback for a legacy map with no floor recorded. A failure on one
        side never suppresses the other, exactly as the two separate
        try/except blocks there do not."""

        map_group_id = None
        map_floor = None
        point_floor = None

        map_oid = _to_object_id(map_id)
        map_item = (
            self.maps_by_id.get(str(map_oid)) if map_oid is not None else None
        )

        if map_item:
            map_group_id = map_item.map_group_id
            map_floor = map_item.floor

        point_oid = _to_object_id(route_point_id)
        route_point = (
            self.points_by_id.get(str(point_oid))
            if point_oid is not None
            else None
        )

        if route_point:
            point_floor = route_point.floor

        floor = map_floor if map_floor is not None else point_floor

        return map_group_id, floor


async def build_location_code_list_enrichment(
    entries: List[LocationCode],
) -> LocationCodeListEnrichment:
    map_oids = {
        oid
        for oid in (_to_object_id(entry.map_id) for entry in entries)
        if oid is not None
    }

    maps_by_id: Dict[str, Map] = {}

    if map_oids:
        map_items = await Map.find({"_id": {"$in": list(map_oids)}}).to_list()
        maps_by_id = {str(item.id): item for item in map_items}

    point_oids = {
        oid
        for oid in (_to_object_id(entry.route_point_id) for entry in entries)
        if oid is not None
    }

    points_by_id: Dict[str, RoutePoint] = {}

    if point_oids:
        points = await RoutePoint.find(
            {"_id": {"$in": list(point_oids)}}
        ).to_list()
        points_by_id = {str(point.id): point for point in points}

    return LocationCodeListEnrichment(
        maps_by_id=maps_by_id,
        points_by_id=points_by_id,
    )


def location_code_to_list_response(
    entry: LocationCode, enrichment: LocationCodeListEnrichment
) -> LocationCodeResponse:
    """
    The batched counterpart of location_code_to_response(). Synchronous by
    design — every question it needs answered was already answered in bulk.
    The field mapping below is identical to that function's, field for
    field, in the same order.
    """

    map_group_id, floor = enrichment.group_and_floor(
        entry.map_id, entry.route_point_id
    )

    return LocationCodeResponse(
        id=str(entry.id),
        code=entry.code,
        building_id=entry.building_id,
        map_id=entry.map_id,
        route_point_id=entry.route_point_id,
        map_group_id=map_group_id,
        floor=floor,
        label=entry.label,
        is_active=entry.is_active,
        created_at=entry.created_at,
        updated_at=entry.updated_at,
    )


async def build_location_code_list_responses(
    entries: List[LocationCode],
) -> List[LocationCodeResponse]:
    enrichment = await build_location_code_list_enrichment(entries)
    return [
        location_code_to_list_response(entry, enrichment) for entry in entries
    ]


async def validate_location_code_references(
    building_id: str,
    map_id: str,
    route_point_id: str,
) -> None:
    building = await Building.get(PydanticObjectId(building_id))
    if not building:
        raise HTTPException(**BUILDING_NOT_FOUND)

    map_item = await Map.get(PydanticObjectId(map_id))
    if not map_item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Map not found"
        )

    route_point = await RoutePoint.get(PydanticObjectId(route_point_id))
    if not route_point:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Route point not found"
        )

    # The whole point of a location code is to guarantee it always resolves
    # to a real, currently-valid start point on the map it claims — so the
    # referenced RoutePoint must actually belong to the referenced map.
    if route_point.map_id != map_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="route_point_id does not belong to the given map_id"
        )

    # And the map/point must actually belong to the claimed building —
    # older maps/points created before building_id existed have None here
    # and are intentionally not rejected (they still need to work until
    # backfilled), but an explicit mismatch is always a real error.
    if map_item.building_id and map_item.building_id != building_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="map_id does not belong to the given building_id",
        )

    if route_point.building_id and route_point.building_id != building_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "route_point_id does not belong to the given building_id"
            ),
        )

    if not route_point.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="route_point_id is not an active point",
        )


# ---------------------------------------------------------
# Public resolve endpoint
# Must be declared before /{code_id} so "resolve" isn't parsed as an id.
# ---------------------------------------------------------

@router.get(
    "/resolve/{code}",
    response_model=LocationCodeResolveResponse,
)
async def resolve_location_code(code: str):
    entry = await LocationCode.find_one(LocationCode.code == code)

    if not entry:
        raise HTTPException(**LOCATION_CODE_NOT_FOUND)

    if not entry.is_active:
        raise HTTPException(**LOCATION_CODE_INACTIVE)

    # Defensive re-check: the RoutePoint or Map this code points to may have
    # been deleted after the code was created. A location code must never
    # resolve to a start point that no longer exists.
    route_point = await RoutePoint.get(
        PydanticObjectId(entry.route_point_id)
    )

    if not route_point or route_point.map_id != entry.map_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="This code's route point is no longer available"
        )

    map_item = await Map.get(PydanticObjectId(entry.map_id))

    # Same Map-floor-is-authoritative rule as
    # resolve_location_code_group_and_floor() above — reused here rather
    # than re-fetching, since map_item/route_point are already loaded by
    # this endpoint's own defensive re-check.
    resolved_floor = (
        map_item.floor if map_item and map_item.floor is not None
        else route_point.floor
    )

    return LocationCodeResolveResponse(
        code=entry.code,
        building_id=entry.building_id,
        map_id=entry.map_id,
        route_point_id=entry.route_point_id,
        map_group_id=map_item.map_group_id if map_item else None,
        floor=resolved_floor,
        label=entry.label,
    )


# ---------------------------------------------------------
# Admin CRUD
# ---------------------------------------------------------

@router.post(
    "",
    response_model=LocationCodeResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_location_code(
    data: LocationCodeCreate,
    user: User = Depends(get_current_user),
):
    if user.role == "regular_user":
        raise HTTPException(**FORBIDDEN_ROLE)

    if not user_can_manage_building(user, data.building_id):
        raise HTTPException(**FORBIDDEN_BUILDING_SCOPE)

    existing = await LocationCode.find_one(LocationCode.code == data.code)

    if existing:
        raise HTTPException(**LOCATION_CODE_ALREADY_EXISTS)

    await validate_location_code_references(
        building_id=data.building_id,
        map_id=data.map_id,
        route_point_id=data.route_point_id,
    )

    new_entry = LocationCode(
        code=data.code,
        building_id=data.building_id,
        map_id=data.map_id,
        route_point_id=data.route_point_id,
        label=data.label,
        is_active=data.is_active,
    )

    await new_entry.insert()
    return await location_code_to_response(new_entry)


# The code format lives in services/room_location_code_service so the manual
# "Generate code" button below and the automatic per-room QR issued during
# semantic/auto-connect apply can never drift into two different formats.
# Re-exported under the original private name so nothing else in this module
# has to change.
_generate_code_candidate = generate_location_code_candidate


@router.post(
    "/generate",
    response_model=LocationCodeResponse,
    status_code=status.HTTP_201_CREATED,
)
async def generate_location_code(
    data: LocationCodeGenerate,
    user: User = Depends(get_current_user),
):
    """
    Auto-generates a unique code for an existing RoutePoint (typically an
    entrance) instead of requiring the admin to invent one. building_id
    and map_id are always derived from the RoutePoint itself, so the
    result can never reference a mismatched building/map/point trio.
    """

    if user.role == "regular_user":
        raise HTTPException(**FORBIDDEN_ROLE)

    route_point = await RoutePoint.get(
        PydanticObjectId(data.route_point_id)
    )

    if not route_point:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Route point not found",
        )

    if not route_point.building_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "This route point has no building_id yet — its map must "
                "be associated with a building before a location code can "
                "be generated for it."
            ),
        )

    if not user_can_manage_building(user, route_point.building_id):
        raise HTTPException(**FORBIDDEN_BUILDING_SCOPE)

    for _attempt in range(10):
        candidate = _generate_code_candidate()
        existing = await LocationCode.find_one(
            LocationCode.code == candidate
        )

        if not existing:
            new_entry = LocationCode(
                code=candidate,
                building_id=route_point.building_id,
                map_id=route_point.map_id,
                route_point_id=str(route_point.id),
                label=data.label or route_point.name,
                is_active=data.is_active,
            )

            await new_entry.insert()
            return await location_code_to_response(new_entry)

    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Could not generate a unique location code, try again",
    )


@router.get(
    "",
    response_model=List[LocationCodeResponse],
)
async def get_all_location_codes(
    building_id: Optional[str] = Query(default=None),
    map_id: Optional[str] = Query(default=None),
    is_active: Optional[bool] = Query(default=None),
    admin: User = Depends(require_any_admin),
):
    """
    Admin inventory of QR/location codes.

    This is an ADMIN listing, not part of the public wayfinding contract:
    the anonymous QR flow only ever calls GET /resolve/{code} below, with a
    code the user physically scanned. This endpoint previously had no auth
    dependency at all, which made the entire physical QR label inventory
    (every code string, plus its building/map/route-point ids) publicly
    enumerable by anyone who could reach the API — exactly the class of
    leak GET /api/route-points/public was explicitly hardened against (see
    routes/route_point_routes.py, which refuses to list without a
    map_id/building_id filter for the same reason). Every other admin
    listing in this codebase already requires authentication.

    Results are additionally narrowed to the caller's authorized buildings,
    the same way GET /api/rooms and GET /api/route-edges are.
    """

    query = {}

    if building_id:
        query["building_id"] = building_id

    if map_id:
        query["map_id"] = map_id

    if is_active is not None:
        query["is_active"] = is_active

    accessible_building_ids = get_accessible_building_ids(admin)

    if accessible_building_ids is not None:
        if building_id:
            # An explicit out-of-scope building_id is rejected outright
            # rather than silently re-scoped, so an admin UI bug can never
            # show a restricted admin a list that LOOKS like the building
            # they asked for but quietly is not.
            if not user_can_access_building(admin, building_id):
                raise HTTPException(**FORBIDDEN_BUILDING_SCOPE)
        else:
            query["building_id"] = {"$in": accessible_building_ids}

    entries = await LocationCode.find(query).to_list()

    # Batched enrichment — see build_location_code_list_enrichment above.
    # Produces the identical LocationCodeResponse list the previous
    # `[await location_code_to_response(entry) for entry in entries]`
    # produced, in a constant number of queries instead of 1 + 2N.
    return await build_location_code_list_responses(entries)


@router.get(
    "/{code_id}",
    response_model=LocationCodeResponse,
)
async def get_location_code_by_id(
    code_id: PydanticObjectId,
    admin: User = Depends(require_any_admin),
):
    """Admin detail view — see get_all_location_codes above for why this
    is authenticated and scope-checked rather than public."""

    entry = await LocationCode.get(code_id)

    if not entry:
        raise HTTPException(**LOCATION_CODE_NOT_FOUND)

    if not user_can_access_building(admin, entry.building_id):
        raise HTTPException(**FORBIDDEN_BUILDING_SCOPE)

    return await location_code_to_response(entry)


@router.put(
    "/{code_id}",
    response_model=LocationCodeResponse,
)
async def update_location_code(
    code_id: PydanticObjectId,
    data: LocationCodeUpdate,
    user: User = Depends(get_current_user),
):
    entry = await LocationCode.get(code_id)

    if not entry:
        raise HTTPException(**LOCATION_CODE_NOT_FOUND)

    if user.role == "regular_user":
        raise HTTPException(**FORBIDDEN_ROLE)

    if not user_can_manage_building(user, entry.building_id):
        raise HTTPException(**FORBIDDEN_BUILDING_SCOPE)

    update_data = data.model_dump(exclude_unset=True)

    if "building_id" in update_data and not user_can_manage_building(
        user, update_data["building_id"]
    ):
        raise HTTPException(**FORBIDDEN_BUILDING_SCOPE)

    if "code" in update_data and update_data["code"] != entry.code:
        duplicate = await LocationCode.find_one(
            LocationCode.code == update_data["code"]
        )
        if duplicate:
            raise HTTPException(**LOCATION_CODE_ALREADY_EXISTS)

    new_building_id = update_data.get("building_id", entry.building_id)
    new_map_id = update_data.get("map_id", entry.map_id)
    new_route_point_id = update_data.get(
        "route_point_id", entry.route_point_id
    )

    if (
        "building_id" in update_data
        or "map_id" in update_data
        or "route_point_id" in update_data
    ):
        await validate_location_code_references(
            building_id=new_building_id,
            map_id=new_map_id,
            route_point_id=new_route_point_id,
        )

    for field, value in update_data.items():
        setattr(entry, field, value)

    entry.updated_at = datetime.utcnow()

    await entry.save()
    return await location_code_to_response(entry)


@router.delete(
    "/{code_id}",
    status_code=status.HTTP_200_OK,
)
async def delete_location_code(
    code_id: PydanticObjectId,
    user: User = Depends(get_current_user),
):
    entry = await LocationCode.get(code_id)

    if not entry:
        raise HTTPException(**LOCATION_CODE_NOT_FOUND)

    if user.role == "regular_user":
        raise HTTPException(**FORBIDDEN_ROLE)

    if not user_can_manage_building(user, entry.building_id):
        raise HTTPException(**FORBIDDEN_BUILDING_SCOPE)

    await entry.delete()

    return {
        "message": "Location code deleted successfully"
    }
