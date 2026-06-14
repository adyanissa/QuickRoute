from datetime import datetime
from typing import List

from beanie import PydanticObjectId
from fastapi import APIRouter, HTTPException, status

from models.map_model import Map
from schemas.map_schema import MapCreate, MapUpdate, MapResponse


router = APIRouter(
    prefix="/api/maps",
    tags=["Map Management"]
)


def map_to_response(map_item: Map) -> MapResponse:
    return MapResponse(
        id=str(map_item.id),
        title=map_item.title,
        campus=map_item.campus,
        address=map_item.address,
        description=map_item.description,
        image_url=map_item.image_url,
        is_current=map_item.is_current,
        created_at=map_item.created_at,
        updated_at=map_item.updated_at,
    )


@router.post(
    "",
    response_model=MapResponse,
    status_code=status.HTTP_201_CREATED
)
async def create_map(map_data: MapCreate):
    # If this map is current, make all old maps not current
    await Map.find(Map.is_current == True).update(
        {"$set": {"is_current": False}}
    )

    new_map = Map(
        title=map_data.title,
        campus=map_data.campus,
        address=map_data.address,
        description=map_data.description,
        image_url=map_data.image_url,
        is_current=True,
    )

    await new_map.insert()
    return map_to_response(new_map)


@router.get(
    "",
    response_model=List[MapResponse]
)
async def get_all_maps():
    maps = await Map.find_all().to_list()
    return [map_to_response(map_item) for map_item in maps]


@router.get(
    "/current",
    response_model=MapResponse
)
async def get_current_map():
    current_map = await Map.find_one(Map.is_current == True)

    if not current_map:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No current map found"
        )

    return map_to_response(current_map)


@router.get(
    "/{map_id}",
    response_model=MapResponse
)
async def get_map_by_id(map_id: PydanticObjectId):
    map_item = await Map.get(map_id)

    if not map_item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Map not found"
        )

    return map_to_response(map_item)


@router.put(
    "/{map_id}",
    response_model=MapResponse
)
async def update_map(
    map_id: PydanticObjectId,
    map_data: MapUpdate
):
    map_item = await Map.get(map_id)

    if not map_item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Map not found"
        )

    update_data = map_data.model_dump(exclude_unset=True)

    if update_data.get("is_current") is True:
        await Map.find(Map.is_current == True).update(
            {"$set": {"is_current": False}}
        )

    for field, value in update_data.items():
        setattr(map_item, field, value)

    map_item.updated_at = datetime.utcnow()

    await map_item.save()
    return map_to_response(map_item)


@router.delete(
    "/{map_id}",
    status_code=status.HTTP_200_OK
)
async def delete_map(map_id: PydanticObjectId):
    map_item = await Map.get(map_id)

    if not map_item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Map not found"
        )

    await map_item.delete()

    return {
        "message": "Map deleted successfully"
    }