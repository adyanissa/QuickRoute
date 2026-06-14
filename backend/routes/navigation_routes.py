from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel
from beanie import PydanticObjectId

import json
import os

from logic.route_logic import build_graph, dijkstra
from logic.route_calculator import calculate_shortest_path

from models.route_edge_model import RouteEdge
from models.route_point_model import RoutePoint

from core.errors import (
    BUILDING_NOT_FOUND,
    ROOM_NOT_FOUND,
    START_NODE_NOT_FOUND,
    END_NODE_NOT_FOUND,
    NO_ROUTE_FOUND
)


router = APIRouter(tags=["Navigation"])

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class NavigationRouteRequest(BaseModel):
    map_id: str
    start_point_id: str
    end_point_id: str


class NavigationRouteResponse(BaseModel):
    map_id: str
    start_point_id: str
    end_point_id: str
    path_point_ids: list[str]
    path_details: list[dict]
    total_distance: float


def load_json_file(filename):
    file_path = os.path.join(BASE_DIR, "data", filename)

    with open(file_path, "r", encoding="utf-8") as file:
        return json.load(file)


# -----------------------------
# Old temporary JSON APIs
# -----------------------------

@router.get("/buildings")
def get_buildings():
    buildings = load_json_file("buildings.json")
    return buildings


@router.get("/buildings/{building_id}/rooms")
def get_rooms_by_building(building_id: str):
    rooms = load_json_file("rooms.json")

    if building_id not in rooms:
        raise HTTPException(**BUILDING_NOT_FOUND)

    return rooms[building_id]


@router.get("/rooms/{room_id}")
def get_room_by_id(room_id: str):
    rooms = load_json_file("rooms.json")

    for building_rooms in rooms.values():
        for room in building_rooms:
            if room["id"] == room_id:
                return room

    raise HTTPException(**ROOM_NOT_FOUND)


@router.get("/graph")
def get_graph():
    graph = load_json_file("map_graph.json")
    return graph


@router.get("/route")
def get_smart_route(
    start: str = Query(..., alias="from"),
    end: str = Query(..., alias="to")
):
    graph_data = load_json_file("map_graph.json")

    nodes = graph_data["nodes"]
    edges = graph_data["edges"]

    node_ids = [node["id"] for node in nodes]

    if start not in node_ids:
        raise HTTPException(**START_NODE_NOT_FOUND)

    if end not in node_ids:
        raise HTTPException(**END_NODE_NOT_FOUND)

    graph = build_graph(edges)
    path, total_distance = dijkstra(graph, start, end)

    if path is None:
        raise HTTPException(**NO_ROUTE_FOUND)

    path_details = []

    for node_id in path:
        node = next((n for n in nodes if n["id"] == node_id), None)
        if node:
            path_details.append(node)

    return {
        "from": start,
        "to": end,
        "path": path,
        "pathDetails": path_details,
        "totalDistance": total_distance
    }


# -----------------------------
# New real MongoDB route API
# -----------------------------

@router.post("/api/navigation/route", response_model=NavigationRouteResponse)
async def calculate_route_from_mongodb(route_data: NavigationRouteRequest):
    start_point = await RoutePoint.get(
        PydanticObjectId(route_data.start_point_id)
    )

    if not start_point:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Start route point not found"
        )

    end_point = await RoutePoint.get(
        PydanticObjectId(route_data.end_point_id)
    )

    if not end_point:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="End route point not found"
        )

    if start_point.map_id != route_data.map_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Start point does not belong to this map"
        )

    if end_point.map_id != route_data.map_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="End point does not belong to this map"
        )

    edges = await RouteEdge.find(
        RouteEdge.map_id == route_data.map_id
    ).to_list()

    result = calculate_shortest_path(
        edges=edges,
        start_point_id=route_data.start_point_id,
        end_point_id=route_data.end_point_id
    )

    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No route found between the selected points"
        )

    path_details = []

    for point_id in result["path_point_ids"]:
        point = await RoutePoint.get(PydanticObjectId(point_id))

        if point:
            path_details.append({
                "id": str(point.id),
                "name": point.name,
                "point_type": point.point_type,
                "x": point.x,
                "y": point.y,
                "floor": point.floor,
                "building_id": point.building_id,
                "room_id": point.room_id,
                "is_accessible": point.is_accessible,
            })

    return {
        "map_id": route_data.map_id,
        "start_point_id": route_data.start_point_id,
        "end_point_id": route_data.end_point_id,
        "path_point_ids": result["path_point_ids"],
        "path_details": path_details,
        "total_distance": result["total_distance"]
    }