import math
from datetime import datetime
from typing import List, Optional

from beanie import PydanticObjectId
from fastapi import APIRouter, Depends, HTTPException, Query, status

from core.auth_deps import require_global_admin
from models.route_edge_model import RouteEdge
from models.route_point_model import RoutePoint
from models.map_model import Map
from models.user_model import User
from schemas.route_edge_schema import (
    RouteEdgeCreate,
    RouteEdgeUpdate,
    RouteEdgeResponse,
)


router = APIRouter(
    prefix="/api/route-edges",
    tags=["Route Edges"]
)


def route_edge_to_response(edge: RouteEdge) -> RouteEdgeResponse:
    return RouteEdgeResponse(
        id=str(edge.id),
        map_id=edge.map_id,
        from_point_id=edge.from_point_id,
        to_point_id=edge.to_point_id,
        edge_type=edge.edge_type,
        distance=edge.distance,
        distance_override=edge.distance_override,
        is_bidirectional=edge.is_bidirectional,
        is_accessible=edge.is_accessible,
        is_active=edge.is_active,
        description=edge.description,
        created_at=edge.created_at,
        updated_at=edge.updated_at,
    )


def get_scale_for_floor(map_item: Map, floor: int) -> float:
    floor_key = str(floor)

    if map_item.floor_scales and floor_key in map_item.floor_scales:
        return map_item.floor_scales[floor_key]

    return map_item.scale


async def validate_edge_ids(
    map_id: Optional[str] = None,
    from_point_id: Optional[str] = None,
    to_point_id: Optional[str] = None,
):
    if map_id:
        map_item = await Map.get(PydanticObjectId(map_id))
        if not map_item:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Map not found"
            )

    if from_point_id:
        from_point = await RoutePoint.get(PydanticObjectId(from_point_id))
        if not from_point:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="From route point not found"
            )

    if to_point_id:
        to_point = await RoutePoint.get(PydanticObjectId(to_point_id))
        if not to_point:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="To route point not found"
            )


async def calculate_edge_distance(
    map_id: str,
    from_point_id: str,
    to_point_id: str,
    edge_type: str = "walkway",
    distance_override: Optional[float] = None
) -> float:
    map_item = await Map.get(PydanticObjectId(map_id))
    from_point = await RoutePoint.get(PydanticObjectId(from_point_id))
    to_point = await RoutePoint.get(PydanticObjectId(to_point_id))

    if not map_item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Map not found"
        )

    if not from_point or not to_point:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Route point not found"
        )

    if from_point.map_id != map_id or to_point.map_id != map_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Both points must belong to the same map"
        )

    same_floor = from_point.floor == to_point.floor

    if edge_type == "walkway":
        if not same_floor:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Walkway edge must connect points on the same floor"
            )

        pixel_distance = math.sqrt(
            (to_point.x - from_point.x) ** 2 +
            (to_point.y - from_point.y) ** 2
        )

        floor_scale = get_scale_for_floor(map_item, from_point.floor)
        distance_meters = pixel_distance * floor_scale

        return round(distance_meters, 2)

    if edge_type in ["stairs", "elevator"]:
        if same_floor:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Stairs or elevator edge should connect points on different floors"
            )

        if distance_override is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="distance_override is required for stairs/elevator edges"
            )

        return round(distance_override, 2)

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Invalid edge_type"
    )


@router.post(
    "",
    response_model=RouteEdgeResponse,
    status_code=status.HTTP_201_CREATED
)
async def create_route_edge(
    edge_data: RouteEdgeCreate,
    _admin: User = Depends(require_global_admin),
):
    if edge_data.from_point_id == edge_data.to_point_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="from_point_id and to_point_id cannot be the same"
        )

    await validate_edge_ids(
        map_id=edge_data.map_id,
        from_point_id=edge_data.from_point_id,
        to_point_id=edge_data.to_point_id,
    )

    calculated_distance = await calculate_edge_distance(
        map_id=edge_data.map_id,
        from_point_id=edge_data.from_point_id,
        to_point_id=edge_data.to_point_id,
        edge_type=edge_data.edge_type,
        distance_override=edge_data.distance_override
    )

    new_edge = RouteEdge(
        map_id=edge_data.map_id,
        from_point_id=edge_data.from_point_id,
        to_point_id=edge_data.to_point_id,
        edge_type=edge_data.edge_type,
        distance=calculated_distance,
        distance_override=edge_data.distance_override,
        is_bidirectional=edge_data.is_bidirectional,
        is_accessible=edge_data.is_accessible,
        description=edge_data.description,
    )

    await new_edge.insert()
    return route_edge_to_response(new_edge)


@router.get(
    "",
    response_model=List[RouteEdgeResponse]
)
async def get_all_route_edges(
    map_id: Optional[str] = Query(default=None),
    from_point_id: Optional[str] = Query(default=None),
    to_point_id: Optional[str] = Query(default=None),
    edge_type: Optional[str] = Query(default=None),
    is_accessible: Optional[bool] = Query(default=None),
):
    query = {}

    if map_id:
        query["map_id"] = map_id

    if from_point_id:
        query["from_point_id"] = from_point_id

    if to_point_id:
        query["to_point_id"] = to_point_id

    if edge_type:
        query["edge_type"] = edge_type

    if is_accessible is not None:
        query["is_accessible"] = is_accessible

    edges = await RouteEdge.find(query).to_list()
    return [route_edge_to_response(edge) for edge in edges]


@router.get(
    "/{edge_id}",
    response_model=RouteEdgeResponse
)
async def get_route_edge_by_id(edge_id: PydanticObjectId):
    edge = await RouteEdge.get(edge_id)

    if not edge:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Route edge not found"
        )

    return route_edge_to_response(edge)


@router.put(
    "/{edge_id}",
    response_model=RouteEdgeResponse
)
async def update_route_edge(
    edge_id: PydanticObjectId,
    edge_data: RouteEdgeUpdate,
    _admin: User = Depends(require_global_admin),
):
    edge = await RouteEdge.get(edge_id)

    if not edge:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Route edge not found"
        )

    update_data = edge_data.model_dump(exclude_unset=True)

    new_map_id = update_data.get("map_id", edge.map_id)
    new_from_point_id = update_data.get("from_point_id", edge.from_point_id)
    new_to_point_id = update_data.get("to_point_id", edge.to_point_id)
    new_edge_type = update_data.get("edge_type", edge.edge_type)
    new_distance_override = update_data.get(
        "distance_override",
        edge.distance_override
    )

    if new_from_point_id == new_to_point_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="from_point_id and to_point_id cannot be the same"
        )

    await validate_edge_ids(
        map_id=update_data.get("map_id"),
        from_point_id=update_data.get("from_point_id"),
        to_point_id=update_data.get("to_point_id"),
    )

    if (
        "map_id" in update_data
        or "from_point_id" in update_data
        or "to_point_id" in update_data
        or "edge_type" in update_data
        or "distance_override" in update_data
    ):
        update_data["distance"] = await calculate_edge_distance(
            map_id=new_map_id,
            from_point_id=new_from_point_id,
            to_point_id=new_to_point_id,
            edge_type=new_edge_type,
            distance_override=new_distance_override
        )

    for field, value in update_data.items():
        setattr(edge, field, value)

    edge.updated_at = datetime.utcnow()

    await edge.save()
    return route_edge_to_response(edge)


@router.delete(
    "/{edge_id}",
    status_code=status.HTTP_200_OK
)
async def delete_route_edge(
    edge_id: PydanticObjectId,
    _admin: User = Depends(require_global_admin),
):
    edge = await RouteEdge.get(edge_id)

    if not edge:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Route edge not found"
        )

    await edge.delete()

    return {
        "message": "Route edge deleted successfully"
    }