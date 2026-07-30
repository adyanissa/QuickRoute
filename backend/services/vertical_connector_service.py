"""
VerticalConnector code normalization/generation (mirrors
services/map_group_service.py's approach exactly, so an admin who already
knows the map-group code rules gets the same rules here) plus the actual
stop-placement / transition-edge-generation logic used by
routes/vertical_connectors_routes.py.
"""

from __future__ import annotations

import re
from typing import List, Optional, Tuple

from beanie import PydanticObjectId
from fastapi import HTTPException, status

from models.map_model import Map
from models.route_edge_model import RouteEdge
from models.route_point_model import RoutePoint
from models.vertical_connector_model import VerticalConnector
from services.graph_connection_service import auto_connect_point
from services.point_dedup_service import find_or_create_route_point


_CODE_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9\-]{1,39}$")
_DEFAULT_CODE_BASE = "CONNECTOR"


def normalize_connector_code(raw_code: str) -> str:
    cleaned = (raw_code or "").strip().upper()

    if not cleaned:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Connector code cannot be empty.",
        )

    if not _CODE_PATTERN.match(cleaned):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Connector code may only contain letters, numbers, and "
                "hyphens, and must be 2-40 characters long."
            ),
        )

    return cleaned


def _slugify_base(name: str) -> str:
    base = re.sub(r"[^A-Z0-9]+", "", (name or "").upper())
    return base[:16] or _DEFAULT_CODE_BASE


async def generate_unique_connector_code(name: str) -> str:
    base = _slugify_base(name)

    for suffix in range(1, 1000):
        candidate = f"{base}-{suffix:03d}"
        existing = await VerticalConnector.find_one(
            VerticalConnector.connector_code == candidate
        )
        if not existing:
            return candidate

    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Could not generate a unique connector code, try again.",
    )


async def resolve_connector_code(
    name: str, explicit_code: Optional[str]
) -> str:
    if explicit_code and explicit_code.strip():
        normalized = normalize_connector_code(explicit_code)

        existing = await VerticalConnector.find_one(
            VerticalConnector.connector_code == normalized
        )
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Connector code '{normalized}' is already in use.",
            )

        return normalized

    return await generate_unique_connector_code(name)


async def get_connector_stops(connector: VerticalConnector) -> List[RoutePoint]:
    """
    Every RoutePoint tagged with this connector's id, ordered by floor
    (None floors last) — never a separate/duplicated list, always a live
    query, so a stop's true current floor/coordinates are always reflected.
    """

    stops = await RoutePoint.find(
        {"connector_id": str(connector.id), "is_active": True}
    ).to_list()

    stops.sort(key=lambda p: (p.floor is None, p.floor if p.floor is not None else 0))
    return stops


async def is_stop_connected_to_floor_graph(stop: RoutePoint) -> bool:
    """
    True once this stop has at least one ordinary same-floor `walkway`
    edge to the local corridor graph (PHASE 5) — a transition edge to
    another floor does not count, since that alone would never let a user
    actually walk from the corridor to this connector on this floor.
    """

    edge = await RouteEdge.find_one(
        {
            "map_id": stop.map_id,
            "edge_type": "walkway",
            "$or": [
                {"from_point_id": str(stop.id)},
                {"to_point_id": str(stop.id)},
            ],
        }
    )
    return edge is not None


def _default_transition_distance_and_time(
    connector: VerticalConnector, from_point: RoutePoint, to_point: RoutePoint
) -> Tuple[float, float]:
    floor_a = from_point.floor if from_point.floor is not None else 0
    floor_b = to_point.floor if to_point.floor is not None else 0
    floor_diff = max(1, abs(floor_a - floor_b))

    distance_meters = round(
        connector.distance_per_floor_meters * floor_diff, 2
    )
    time_seconds = round(
        connector.wait_time_seconds
        + connector.seconds_per_floor * floor_diff,
        2,
    )
    return distance_meters, time_seconds


async def _existing_transition_edge(
    connector_id: str, point_a_id: str, point_b_id: str
) -> Optional[RouteEdge]:
    return await RouteEdge.find_one(
        {
            "connector_id": connector_id,
            "$or": [
                {"from_point_id": point_a_id, "to_point_id": point_b_id},
                {"from_point_id": point_b_id, "to_point_id": point_a_id},
            ],
        }
    )


async def regenerate_transition_edges(connector: VerticalConnector) -> List[RouteEdge]:
    """
    Rebuilds this connector's cross-floor transition edges from scratch
    against its CURRENT stop list — safe to call after every stop
    add/remove. Elevators/ramps/stairs (bidirectional by default) get one
    edge between every pair of stops (a full mesh — an elevator serving
    floors 0/1/2 can go directly 0->2 without stopping, which is correct
    real-world behavior). A non-bidirectional connector (e.g. a one-way
    escalator) only gets edges directly between floor-adjacent stops, in
    ascending floor order, one-way — modeling a real one-way escalator
    chain rather than fabricating a direct multi-floor "jump" no real
    one-way escalator can perform.
    """

    stops = await get_connector_stops(connector)

    # Never touch anything else's edges — only ones this exact connector
    # previously created.
    await RouteEdge.find(RouteEdge.connector_id == str(connector.id)).delete()

    if len(stops) < 2:
        return []

    created: List[RouteEdge] = []

    def _pairs():
        if connector.is_bidirectional:
            for i in range(len(stops)):
                for j in range(i + 1, len(stops)):
                    yield stops[i], stops[j], True
        else:
            ordered = sorted(
                stops,
                key=lambda p: (p.floor is None, p.floor if p.floor is not None else 0),
            )
            for i in range(len(ordered) - 1):
                yield ordered[i], ordered[i + 1], False

    for from_point, to_point, bidirectional in _pairs():
        if from_point.map_id == to_point.map_id:
            # Two stops of the same connector should never share a map —
            # each floor stop must live on its OWN floor's map. Skip
            # rather than create a same-map "transition" edge, which would
            # be structurally meaningless and could collide with a normal
            # walkway edge.
            continue

        distance_meters, time_seconds = _default_transition_distance_and_time(
            connector, from_point, to_point
        )

        new_edge = RouteEdge(
            map_id=from_point.map_id,
            to_map_id=to_point.map_id,
            from_point_id=str(from_point.id),
            to_point_id=str(to_point.id),
            edge_type=connector.connector_type,
            distance=distance_meters,
            connector_id=str(connector.id),
            estimated_time_seconds=time_seconds,
            is_bidirectional=bidirectional,
            is_accessible=connector.is_accessible,
        )
        await new_edge.insert()
        created.append(new_edge)

    return created


async def add_connector_stop(
    connector: VerticalConnector,
    *,
    map_id: str,
    x: float,
    y: float,
    name: Optional[str],
    auto_connect: str,
) -> Tuple[RoutePoint, bool, bool]:
    """
    Places (or reuses) this connector's stop on ONE floor map. Returns
    (point, was_reused, connected_to_floor_graph).
    """

    resolved_map = await Map.get(PydanticObjectId(map_id))
    if not resolved_map:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Map not found"
        )

    if resolved_map.building_id and resolved_map.building_id != connector.building_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This map does not belong to the connector's building.",
        )

    if resolved_map.map_group_id != connector.map_group_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "This map does not belong to the connector's map group — "
                "a connector may only have stops on floors of its own "
                "map group."
            ),
        )

    existing_stop_on_this_map = await RoutePoint.find_one(
        {
            "connector_id": str(connector.id),
            "map_id": map_id,
            "is_active": True,
        }
    )
    if existing_stop_on_this_map:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This connector already has a stop on this floor.",
        )

    point, was_reused = await find_or_create_route_point(
        map_id=map_id,
        name=name or connector.name,
        point_type=connector.connector_type,
        x=x,
        y=y,
        floor=resolved_map.floor,
        building_id=connector.building_id,
        room_id=None,
        is_accessible=connector.is_accessible,
    )

    if point.connector_id and point.connector_id != str(connector.id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "This map location is already a stop of a different "
                "vertical connector."
            ),
        )

    point.connector_id = str(connector.id)
    point.connector_code = connector.connector_code
    point.point_type = connector.connector_type
    await point.save()

    if was_reused:
        connected = await is_stop_connected_to_floor_graph(point)
    else:
        summary = await auto_connect_point(point, mode=auto_connect)
        connected = len(summary["edges_created"]) > 0

    await regenerate_transition_edges(connector)

    return point, was_reused, connected


async def remove_connector_stop(
    connector: VerticalConnector, route_point_id: str
) -> None:
    point = await RoutePoint.get(PydanticObjectId(route_point_id))

    if not point or point.connector_id != str(connector.id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="This stop does not belong to this connector.",
        )

    # Remove only THIS connector's transition edges touching this point —
    # never its ordinary same-floor walkway edge(s), which stay intact so
    # the corridor graph around it is never silently broken.
    await RouteEdge.find(
        {
            "connector_id": str(connector.id),
            "$or": [
                {"from_point_id": route_point_id},
                {"to_point_id": route_point_id},
            ],
        }
    ).delete()

    point.connector_id = None
    point.connector_code = None
    await point.save()

    await regenerate_transition_edges(connector)


async def delete_connector(connector: VerticalConnector) -> dict:
    """
    Safe connector deletion: removes only the transition edges this
    connector owns and un-tags its stop RoutePoints (clearing
    connector_id/connector_code) — the stop points themselves, and their
    ordinary same-floor walkway edges, are left completely intact (they
    simply become normal corridor points again). Never deletes a
    RoutePoint here; RoutePoint deletion already has its own independent
    "no attached edges" safety check (route_point_routes.delete_route_point).
    """

    stops = await get_connector_stops(connector)

    deleted_edges = await RouteEdge.find(
        RouteEdge.connector_id == str(connector.id)
    ).delete()

    for stop in stops:
        stop.connector_id = None
        stop.connector_code = None
        await stop.save()

    await connector.delete()

    return {
        "deleted_transition_edges": (
            deleted_edges.deleted_count if deleted_edges else 0
        ),
        "unlinked_stops": len(stops),
    }
