from datetime import datetime
from typing import List, Optional

from beanie import PydanticObjectId
from fastapi import APIRouter, Depends, HTTPException, Query, status

from core.auth_deps import require_global_admin
from models.building_model import Building
from models.map_group_model import MapGroup
from models.user_model import User
from models.vertical_connector_model import VerticalConnector, CONNECTOR_TYPES
from schemas.vertical_connector_schema import (
    VerticalConnectorCreate,
    VerticalConnectorUpdate,
    VerticalConnectorResponse,
    ConnectorStopCreate,
    ConnectorStopResponse,
)
from services.vertical_connector_service import (
    resolve_connector_code,
    get_connector_stops,
    is_stop_connected_to_floor_graph,
    add_connector_stop,
    remove_connector_stop,
    delete_connector,
)


router = APIRouter(
    prefix="/api/vertical-connectors",
    tags=["Vertical Connectors"],
)


async def _connector_to_response(
    connector: VerticalConnector,
) -> VerticalConnectorResponse:
    stops = await get_connector_stops(connector)

    stop_responses: List[ConnectorStopResponse] = []
    all_connected = True

    for stop in stops:
        connected = await is_stop_connected_to_floor_graph(stop)
        all_connected = all_connected and connected

        stop_responses.append(
            ConnectorStopResponse(
                route_point_id=str(stop.id),
                map_id=stop.map_id,
                floor=stop.floor,
                x=stop.x,
                y=stop.y,
                name=stop.name,
                connected_to_floor_graph=connected,
            )
        )

    return VerticalConnectorResponse(
        id=str(connector.id),
        building_id=connector.building_id,
        map_group_id=connector.map_group_id,
        connector_code=connector.connector_code,
        name=connector.name,
        connector_type=connector.connector_type,
        is_bidirectional=connector.is_bidirectional,
        is_accessible=connector.is_accessible,
        is_active=connector.is_active,
        wait_time_seconds=connector.wait_time_seconds,
        seconds_per_floor=connector.seconds_per_floor,
        distance_per_floor_meters=connector.distance_per_floor_meters,
        description=connector.description,
        stops=stop_responses,
        is_fully_connected=(len(stops) >= 2 and all_connected),
        created_at=connector.created_at,
        updated_at=connector.updated_at,
    )


async def _load_connector_or_404(connector_id: str) -> VerticalConnector:
    try:
        connector = await VerticalConnector.get(PydanticObjectId(connector_id))
    except Exception:
        connector = None

    if not connector:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Vertical connector not found",
        )

    return connector


@router.post(
    "",
    response_model=VerticalConnectorResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_vertical_connector(
    data: VerticalConnectorCreate,
    _admin: User = Depends(require_global_admin),
):
    building = await Building.get(PydanticObjectId(data.building_id))
    if not building:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Building not found"
        )

    group = await MapGroup.get(PydanticObjectId(data.map_group_id))
    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Map group not found"
        )

    if group.building_id != data.building_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This map group does not belong to the given building.",
        )

    if data.connector_type not in CONNECTOR_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"connector_type must be one of {CONNECTOR_TYPES}",
        )

    code = await resolve_connector_code(data.name, data.connector_code)

    connector = VerticalConnector(
        building_id=data.building_id,
        map_group_id=data.map_group_id,
        connector_code=code,
        name=data.name.strip(),
        connector_type=data.connector_type,
        is_bidirectional=data.is_bidirectional,
        is_accessible=data.is_accessible,
        wait_time_seconds=data.wait_time_seconds,
        seconds_per_floor=data.seconds_per_floor,
        distance_per_floor_meters=data.distance_per_floor_meters,
        description=data.description,
    )
    await connector.insert()

    return await _connector_to_response(connector)


@router.get("", response_model=List[VerticalConnectorResponse])
async def get_all_vertical_connectors(
    map_group_id: Optional[str] = Query(default=None),
    building_id: Optional[str] = Query(default=None),
):
    query = {}
    if map_group_id:
        query["map_group_id"] = map_group_id
    if building_id:
        query["building_id"] = building_id

    connectors = await VerticalConnector.find(query).to_list()
    return [await _connector_to_response(c) for c in connectors]


@router.get("/{connector_id}", response_model=VerticalConnectorResponse)
async def get_vertical_connector(connector_id: str):
    connector = await _load_connector_or_404(connector_id)
    return await _connector_to_response(connector)


@router.put("/{connector_id}", response_model=VerticalConnectorResponse)
async def update_vertical_connector(
    connector_id: str,
    data: VerticalConnectorUpdate,
    _admin: User = Depends(require_global_admin),
):
    connector = await _load_connector_or_404(connector_id)
    update_data = data.model_dump(exclude_unset=True)

    accessibility_changed = (
        "is_accessible" in update_data
        and update_data["is_accessible"] != connector.is_accessible
    )

    for field, value in update_data.items():
        setattr(connector, field, value)

    connector.updated_at = datetime.utcnow()
    await connector.save()

    if accessibility_changed:
        # Keep every existing transition edge's is_accessible flag in sync
        # with the connector's own setting — never let an edge silently
        # disagree with the connector metadata that created it.
        from models.route_edge_model import RouteEdge

        await RouteEdge.find(RouteEdge.connector_id == str(connector.id)).update(
            {"$set": {"is_accessible": connector.is_accessible}}
        )

    return await _connector_to_response(connector)


@router.delete("/{connector_id}", status_code=status.HTTP_200_OK)
async def delete_vertical_connector(
    connector_id: str,
    _admin: User = Depends(require_global_admin),
):
    connector = await _load_connector_or_404(connector_id)
    summary = await delete_connector(connector)

    return {
        "message": "Vertical connector deleted successfully",
        **summary,
    }


@router.post(
    "/{connector_id}/stops",
    response_model=VerticalConnectorResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_vertical_connector_stop(
    connector_id: str,
    data: ConnectorStopCreate,
    _admin: User = Depends(require_global_admin),
):
    connector = await _load_connector_or_404(connector_id)

    await add_connector_stop(
        connector,
        map_id=data.map_id,
        x=data.x,
        y=data.y,
        name=data.name,
        auto_connect=data.auto_connect,
    )

    return await _connector_to_response(connector)


@router.delete(
    "/{connector_id}/stops/{route_point_id}",
    response_model=VerticalConnectorResponse,
)
async def remove_vertical_connector_stop(
    connector_id: str,
    route_point_id: str,
    _admin: User = Depends(require_global_admin),
):
    connector = await _load_connector_or_404(connector_id)
    await remove_connector_stop(connector, route_point_id)

    return await _connector_to_response(connector)
