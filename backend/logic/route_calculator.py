import heapq
from typing import Dict, List, Optional, Tuple

from models.route_edge_model import RouteEdge


def build_graph(edges: List[RouteEdge]) -> Dict[str, List[Tuple[str, float]]]:
    graph: Dict[str, List[Tuple[str, float]]] = {}

    for edge in edges:
        if not edge.is_active or not edge.is_accessible:
            continue

        if edge.from_point_id not in graph:
            graph[edge.from_point_id] = []

        graph[edge.from_point_id].append(
            (edge.to_point_id, edge.distance)
        )

        if edge.is_bidirectional:
            if edge.to_point_id not in graph:
                graph[edge.to_point_id] = []

            graph[edge.to_point_id].append(
                (edge.from_point_id, edge.distance)
            )

    return graph


def calculate_shortest_path(
    edges: List[RouteEdge],
    start_point_id: str,
    end_point_id: str
) -> Optional[dict]:
    graph = build_graph(edges)

    distances: Dict[str, float] = {
        start_point_id: 0
    }

    previous: Dict[str, Optional[str]] = {
        start_point_id: None
    }

    priority_queue: List[Tuple[float, str]] = [
        (0, start_point_id)
    ]

    visited = set()

    while priority_queue:
        current_distance, current_point = heapq.heappop(priority_queue)

        if current_point in visited:
            continue

        visited.add(current_point)

        if current_point == end_point_id:
            break

        for neighbor, edge_distance in graph.get(current_point, []):
            new_distance = current_distance + edge_distance

            if neighbor not in distances or new_distance < distances[neighbor]:
                distances[neighbor] = new_distance
                previous[neighbor] = current_point
                heapq.heappush(priority_queue, (new_distance, neighbor))

    if end_point_id not in distances:
        return None

    path = []
    current = end_point_id

    while current is not None:
        path.append(current)
        current = previous.get(current)

    path.reverse()

    return {
        "path_point_ids": path,
        "total_distance": distances[end_point_id]
    }