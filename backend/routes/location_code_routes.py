from datetime import datetime
from typing import List, Optional

from beanie import PydanticObjectId
from fastapi import APIRouter, Depends, HTTPException, Query, status

from models.location_code_model import LocationCode
from models.map_model import Map
from models.building_model import Building
from models.route_point_model import RoutePoint
from models.user_model import User
from schemas.location_code_schema import (
    LocationCodeCreate,
    LocationCodeUpdate,
    LocationCodeResponse,
    LocationCodeResolveResponse,
)
from core.auth_deps import get_current_user, user_can_manage_building
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


def location_code_to_response(entry: LocationCode) -> LocationCodeResponse:
    return LocationCodeResponse(
        id=str(entry.id),
        code=entry.code,
        building_id=entry.building_id,
        map_id=entry.map_id,
        route_point_id=entry.route_point_id,
        label=entry.label,
        is_active=entry.is_active,
        created_at=entry.created_at,
        updated_at=entry.updated_at,
    )


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

    return LocationCodeResolveResponse(
        code=entry.code,
        building_id=entry.building_id,
        map_id=entry.map_id,
        route_point_id=entry.route_point_id,
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
    return location_code_to_response(new_entry)


@router.get(
    "",
    response_model=List[LocationCodeResponse],
)
async def get_all_location_codes(
    building_id: Optional[str] = Query(default=None),
    map_id: Optional[str] = Query(default=None),
    is_active: Optional[bool] = Query(default=None),
):
    query = {}

    if building_id:
        query["building_id"] = building_id

    if map_id:
        query["map_id"] = map_id

    if is_active is not None:
        query["is_active"] = is_active

    entries = await LocationCode.find(query).to_list()
    return [location_code_to_response(entry) for entry in entries]


@router.get(
    "/{code_id}",
    response_model=LocationCodeResponse,
)
async def get_location_code_by_id(code_id: PydanticObjectId):
    entry = await LocationCode.get(code_id)

    if not entry:
        raise HTTPException(**LOCATION_CODE_NOT_FOUND)

    return location_code_to_response(entry)


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
    return location_code_to_response(entry)


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
