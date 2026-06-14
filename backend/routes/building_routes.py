from datetime import datetime
from typing import List

from beanie import PydanticObjectId
from fastapi import APIRouter, HTTPException, status

from models.building_model import Building
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
async def create_building(building_data: BuildingCreate):
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
async def get_all_buildings():
    buildings = await Building.find_all().to_list()
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
    building_data: BuildingUpdate
):
    building = await Building.get(building_id)

    if not building:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Building not found"
        )

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
async def delete_building(building_id: PydanticObjectId):
    building = await Building.get(building_id)

    if not building:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Building not found"
        )

    await building.delete()

    return {
        "message": "Building deleted successfully"
    }