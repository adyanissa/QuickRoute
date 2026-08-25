from datetime import datetime
from typing import List

from beanie import PydanticObjectId
from fastapi import APIRouter, Depends, HTTPException, status

from core.auth_deps import (
    get_current_user,
    get_current_user_optional,
    require_global_admin,
    user_can_manage_building,
    get_accessible_building_ids,
)
from core.errors import FORBIDDEN_BUILDING_SCOPE, FORBIDDEN_ROLE
from models.building_model import Building
from models.room_model import Room
from models.route_point_model import RoutePoint
from models.location_code_model import LocationCode
from models.user_model import User
from schemas.building_schema import BuildingCreate, BuildingUpdate, BuildingResponse


router = APIRouter(
    prefix="/api/locations/buildings",
    tags=["Locations - Buildings"]
)


def building_to_response(building: Building) -> BuildingResponse:
    return BuildingResponse(
        id=str(building.id),
        name_en=building.name_en,
        name_local=building.name_local,
        description=building.description,
        short_tag=building.short_tag,
        icon_color=building.icon_color,
        category=building.category,
        campus=building.campus,
        is_active=building.is_active,
        created_at=building.created_at,
        updated_at=building.updated_at,
    )


@router.post(
    "",
    response_model=BuildingResponse,
    status_code=status.HTTP_201_CREATED
)
async def create_building(
    building_data: BuildingCreate,
    _admin: User = Depends(require_global_admin),
):
    new_building = Building(
        name_en=building_data.name_en,
        name_local=building_data.name_local,
        description=building_data.description,
        short_tag=building_data.short_tag,
        icon_color=building_data.icon_color,
        category=building_data.category,
        campus=building_data.campus,
    )

    await new_building.insert()
    return building_to_response(new_building)


@router.get(
    "",
    response_model=List[BuildingResponse]
)
async def get_all_buildings(
    admin: User = Depends(get_current_user_optional),
):
    """
    RBAC/dashboard cleanup task, Phase 9 — deliberately stays reachable
    with NO login at all (this is also the exact endpoint the public,
    anonymous BuildingSelectionScreen uses to let a visitor pick their
    building before ever navigating), so an anonymous caller — and an
    authenticated `regular_user`, who has no admin scope of their own —
    both still see every active building, completely unchanged from
    before this task.

    The one behavior actually added here: when the caller IS an
    authenticated admin-tier user (global_manager/building_manager without
    all_buildings, specifically — super_admin and all_buildings=True both
    already see everything), the list is narrowed to only the buildings
    they can access. This is what makes the Admin Dashboard's building
    count/list correctly scoped instead of always showing the whole
    system's buildings regardless of who's logged in.
    """

    query = {}

    if admin is not None and admin.role != "regular_user":
        accessible_ids = get_accessible_building_ids(admin)
        if accessible_ids is not None:
            query["_id"] = {"$in": [PydanticObjectId(bid) for bid in accessible_ids if bid]}

    buildings = await Building.find(query).to_list()
    return [building_to_response(building) for building in buildings]


@router.get(
    "/{building_id}",
    response_model=BuildingResponse
)
async def get_building_by_id(building_id: PydanticObjectId):
    building = await Building.get(building_id)

    if not building:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Building not found"
        )

    return building_to_response(building)


@router.put(
    "/{building_id}",
    response_model=BuildingResponse
)
async def update_building(
    building_id: PydanticObjectId,
    building_data: BuildingUpdate,
    user: User = Depends(get_current_user),
):
    building = await Building.get(building_id)

    if not building:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Building not found"
        )

    if user.role == "regular_user":
        raise HTTPException(**FORBIDDEN_ROLE)

    if not user_can_manage_building(user, str(building_id)):
        raise HTTPException(**FORBIDDEN_BUILDING_SCOPE)

    update_data = building_data.model_dump(exclude_unset=True)

    for field, value in update_data.items():
        setattr(building, field, value)

    building.updated_at = datetime.utcnow()

    await building.save()
    return building_to_response(building)


@router.delete(
    "/{building_id}",
    status_code=status.HTTP_200_OK
)
async def delete_building(
    building_id: PydanticObjectId,
    _admin: User = Depends(require_global_admin),
):
    building = await Building.get(building_id)

    if not building:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Building not found"
        )

    building_id_str = str(building_id)

    # Buildings are the root of a lot of navigation data (rooms, entrance
    # points, location codes). Deleting one out from under that data would
    # silently orphan it, so this rejects deletion until the admin has
    # removed the dependent records first — a deliberate, visible action
    # rather than an automatic wide cascade.
    linked_room = await Room.find_one(Room.building_id == building_id_str)

    if linked_room:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "This building still has rooms assigned to it. "
                "Delete or reassign its rooms before deleting the building."
            ),
        )

    linked_point = await RoutePoint.find_one(
        RoutePoint.building_id == building_id_str
    )

    if linked_point:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "This building still has route points assigned to it. "
                "Remove those connections before deleting the building."
            ),
        )

    linked_location_code = await LocationCode.find_one(
        LocationCode.building_id == building_id_str
    )

    if linked_location_code:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "This building still has location codes assigned to it. "
                "Delete those location codes before deleting the building."
            ),
        )

    await building.delete()

    return {
        "message": "Building deleted successfully"
    }