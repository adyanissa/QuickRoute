from datetime import datetime
from typing import List, Optional

from beanie import PydanticObjectId
from fastapi import APIRouter, Depends, HTTPException, Query, status

from core.auth_deps import get_current_user, user_can_manage_building
from core.errors import FORBIDDEN_BUILDING_SCOPE, FORBIDDEN_ROLE
from models.room_model import Room
from models.building_model import Building
from models.route_point_model import RoutePoint
from models.user_model import User
from schemas.room_schema import RoomCreate, RoomUpdate, RoomResponse


router = APIRouter(
    prefix="/api/rooms",
    tags=["Rooms & Destinations"]
)


def room_to_response(room: Room) -> RoomResponse:
    return RoomResponse(
        id=str(room.id),
        building_id=room.building_id,
        name_en=room.name_en,
        name_local=room.name_local,
        room_number=room.room_number,
        floor=room.floor,
        room_type=room.room_type,
        description=room.description,
        category=room.category,
        is_active=room.is_active,
        created_at=room.created_at,
        updated_at=room.updated_at,
    )


@router.post(
    "",
    response_model=RoomResponse,
    status_code=status.HTTP_201_CREATED
)
async def create_room(
    room_data: RoomCreate,
    user: User = Depends(get_current_user),
):
    if user.role == "regular_user":
        raise HTTPException(**FORBIDDEN_ROLE)

    if not user_can_manage_building(user, room_data.building_id):
        raise HTTPException(**FORBIDDEN_BUILDING_SCOPE)

    building = await Building.get(PydanticObjectId(room_data.building_id))

    if not building:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Building not found"
        )

    new_room = Room(
        building_id=room_data.building_id,
        name_en=room_data.name_en,
        name_local=room_data.name_local,
        room_number=room_data.room_number,
        floor=room_data.floor,
        room_type=room_data.room_type,
        description=room_data.description,
        category=room_data.category,
    )

    await new_room.insert()
    return room_to_response(new_room)


@router.get(
    "",
    response_model=List[RoomResponse]
)
async def get_all_rooms(
    building_id: Optional[str] = Query(default=None),
    floor: Optional[int] = Query(default=None),
    room_type: Optional[str] = Query(default=None),
):
    query = {}

    if building_id:
        query["building_id"] = building_id

    if floor is not None:
        query["floor"] = floor

    if room_type:
        query["room_type"] = room_type

    rooms = await Room.find(query).to_list()
    return [room_to_response(room) for room in rooms]


@router.get(
    "/{room_id}",
    response_model=RoomResponse
)
async def get_room_by_id(room_id: PydanticObjectId):
    room = await Room.get(room_id)

    if not room:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Room not found"
        )

    return room_to_response(room)


@router.put(
    "/{room_id}",
    response_model=RoomResponse
)
async def update_room(
    room_id: PydanticObjectId,
    room_data: RoomUpdate,
    user: User = Depends(get_current_user),
):
    room = await Room.get(room_id)

    if not room:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Room not found"
        )

    if user.role == "regular_user":
        raise HTTPException(**FORBIDDEN_ROLE)

    if not user_can_manage_building(user, room.building_id):
        raise HTTPException(**FORBIDDEN_BUILDING_SCOPE)

    update_data = room_data.model_dump(exclude_unset=True)

    if "building_id" in update_data:
        if not user_can_manage_building(user, update_data["building_id"]):
            raise HTTPException(**FORBIDDEN_BUILDING_SCOPE)

        building = await Building.get(PydanticObjectId(update_data["building_id"]))

        if not building:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Building not found"
            )

    for field, value in update_data.items():
        setattr(room, field, value)

    room.updated_at = datetime.utcnow()

    await room.save()
    return room_to_response(room)


@router.delete(
    "/{room_id}",
    status_code=status.HTTP_200_OK
)
async def delete_room(
    room_id: PydanticObjectId,
    user: User = Depends(get_current_user),
):
    room = await Room.get(room_id)

    if not room:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Room not found"
        )

    if user.role == "regular_user":
        raise HTTPException(**FORBIDDEN_ROLE)

    if not user_can_manage_building(user, room.building_id):
        raise HTTPException(**FORBIDDEN_BUILDING_SCOPE)

    # A room that is already connected to the navigation graph (has a
    # RoutePoint pointing at it) must not be silently unlinked — the
    # admin needs to disconnect it from the graph first.
    linked_point = await RoutePoint.find_one(
        RoutePoint.room_id == str(room_id)
    )

    if linked_point:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "This room is still connected to the navigation graph. "
                "Remove its route point connection before deleting it."
            ),
        )

    await room.delete()

    return {
        "message": "Room deleted successfully"
    }