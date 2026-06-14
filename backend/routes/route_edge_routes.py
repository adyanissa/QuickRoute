from datetime import datetime
from typing import List, Optional

from beanie import PydanticObjectId
from fastapi import APIRouter, HTTPException, Query, status

from models.route_edge_model import RouteEdge
from models.route_point_model import RoutePoint
from models.map_model import Map
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
        distance=edge.distance,
        is_bidirectional=edge.is_bidirectional,
        is_accessible=edge.is_accessible,
        is_active=edge.is_active,
        description=edge.description,
        created_at=edge.created_at,
        updated_at=edge.updated_at,
    )


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


@router.post(
    "",
    response_model=RouteEdgeResponse,
    status_code=status.HTTP_201_CREATED
)
async def create_route_edge(edge_data: RouteEdgeCreate):
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

    new_edge = RouteEdge(
        map_id=edge_data.map_id,
        from_point_id=edge_data.from_point_id,
        to_point_id=edge_data.to_point_id,
        distance=edge_data.distance,
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
    is_accessible: Optional[bool] = Query(default=None),
):
    query = {}

    if map_id:
        query["map_id"] = map_id

    if from_point_id:
        query["from_point_id"] = from_point_id

    if to_point_id:
        query["to_point_id"] = to_point_id

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
    edge_data: RouteEdgeUpdate
):
    edge = await RouteEdge.get(edge_id)

    if not edge:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Route edge not found"
        )

    update_data = edge_data.model_dump(exclude_unset=True)

    new_from_point_id = update_data.get("from_point_id", edge.from_point_id)
    new_to_point_id = update_data.get("to_point_id", edge.to_point_id)

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

    for field, value in update_data.items():
        setattr(edge, field, value)

    edge.updated_at = datetime.utcnow()

    await edge.save()
    return route_edge_to_response(edge)


@router.delete(
    "/{edge_id}",
    status_code=status.HTTP_200_OK
)
async def delete_route_edge(edge_id: PydanticObjectId):
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