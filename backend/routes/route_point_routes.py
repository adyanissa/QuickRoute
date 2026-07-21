from datetime import datetime
from typing import List, Optional

from beanie import PydanticObjectId
from fastapi import APIRouter, Depends, HTTPException, Query, status

from core.auth_deps import require_global_admin
from models.route_point_model import RoutePoint
from models.route_edge_model import RouteEdge
from models.location_code_model import LocationCode
from models.map_model import Map
from models.building_model import Building
from models.room_model import Room
from models.user_model import User
from schemas.route_point_schema import (
    RoutePointCreate,
    RoutePointUpdate,
    RoutePointResponse,
)


router = APIRouter(
    prefix="/api/route-points",
    tags=["Route Points"]
)


def route_point_to_response(point: RoutePoint) -> RoutePointResponse:
    return RoutePointResponse(
        id=str(point.id),
        map_id=point.map_id,
        name=point.name,
        point_type=point.point_type,
        x=point.x,
        y=point.y,
        floor=point.floor,
        building_id=point.building_id,
        room_id=point.room_id,
        is_accessible=point.is_accessible,
        is_active=point.is_active,
        created_at=point.created_at,
        updated_at=point.updated_at,
    )


async def validate_related_ids(
    map_id: Optional[str] = None,
    building_id: Optional[str] = None,
    room_id: Optional[str] = None,
):
    if map_id:
        map_item = await Map.get(PydanticObjectId(map_id))
        if not map_item:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Map not found"
            )

    if building_id:
        building = await Building.get(PydanticObjectId(building_id))
        if not building:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Building not found"
            )

    if room_id:
        room = await Room.get(PydanticObjectId(room_id))
        if not room:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Room not found"
            )


@router.post(
    "",
    response_model=RoutePointResponse,
    status_code=status.HTTP_201_CREATED
)
async def create_route_point(
    point_data: RoutePointCreate,
    _admin: User = Depends(require_global_admin),
):
    await validate_related_ids(
        map_id=point_data.map_id,
        building_id=point_data.building_id,
        room_id=point_data.room_id,
    )

    new_point = RoutePoint(
        map_id=point_data.map_id,
        name=point_data.name,
        point_type=point_data.point_type,
        x=point_data.x,
        y=point_data.y,
        floor=point_data.floor,
        building_id=point_data.building_id,
        room_id=point_data.room_id,
        is_accessible=point_data.is_accessible,
    )

    await new_point.insert()
    return route_point_to_response(new_point)


@router.get(
    "",
    response_model=List[RoutePointResponse]
)
async def get_all_route_points(
    map_id: Optional[str] = Query(default=None),
    building_id: Optional[str] = Query(default=None),
    room_id: Optional[str] = Query(default=None),
    floor: Optional[int] = Query(default=None),
    point_type: Optional[str] = Query(default=None),
):
    query = {}

    if map_id:
        query["map_id"] = map_id

    if building_id:
        query["building_id"] = building_id

    if room_id:
        query["room_id"] = room_id

    if floor is not None:
        query["floor"] = floor

    if point_type:
        query["point_type"] = point_type

    points = await RoutePoint.find(query).to_list()
    return [route_point_to_response(point) for point in points]


@router.get(
    "/{point_id}",
    response_model=RoutePointResponse
)
async def get_route_point_by_id(point_id: PydanticObjectId):
    point = await RoutePoint.get(point_id)

    if not point:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Route point not found"
        )

    return route_point_to_response(point)


@router.put(
    "/{point_id}",
    response_model=RoutePointResponse
)
async def update_route_point(
    point_id: PydanticObjectId,
    point_data: RoutePointUpdate,
    _admin: User = Depends(require_global_admin),
):
    point = await RoutePoint.get(point_id)

    if not point:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Route point not found"
        )

    update_data = point_data.model_dump(exclude_unset=True)

    await validate_related_ids(
        map_id=update_data.get("map_id"),
        building_id=update_data.get("building_id"),
        room_id=update_data.get("room_id"),
    )

    for field, value in update_data.items():
        setattr(point, field, value)

    point.updated_at = datetime.utcnow()

    await point.save()
    return route_point_to_response(point)


@router.delete(
    "/{point_id}",
    status_code=status.HTTP_200_OK
)
async def delete_route_point(
    point_id: PydanticObjectId,
    _admin: User = Depends(require_global_admin),
):
    point = await RoutePoint.get(point_id)

    if not point:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Route point not found"
        )

    point_id_str = str(point_id)

    # A point that still has edges attached is load-bearing for the
    # navigation graph — deleting it would silently break every route that
    # passes through it. Reject instead of a wide implicit cascade; the
    # admin deletes the edges first (e.g. by re-drawing that corridor).
    linked_edge = await RouteEdge.find_one(
        {
            "$or": [
                {"from_point_id": point_id_str},
                {"to_point_id": point_id_str},
            ]
        }
    )

    if linked_edge:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "This route point still has connected edges. "
                "Delete the connecting edges before deleting the point."
            ),
        )

    linked_location_code = await LocationCode.find_one(
        LocationCode.route_point_id == point_id_str
    )

    if linked_location_code:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "This route point is used as a location code's start "
                "point. Delete or reassign that location code first."
            ),
        )

    await point.delete()

    return {
        "message": "Route point deleted successfully"
    }