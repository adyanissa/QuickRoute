import heapq


def build_graph(edges):
    graph = {}

    for edge in edges:
        from_node = edge["from"]
        to_node = edge["to"]
        distance = edge["distance"]

        if from_node not in graph:
            graph[from_node] = []

        if to_node not in graph:
            graph[to_node] = []

        graph[from_node].append((to_node, distance))
        graph[to_node].append((from_node, distance))

    return graph


def dijkstra(graph, start, end):
    distances = {node: float("inf") for node in graph}
    previous = {node: None for node in graph}

    distances[start] = 0
    priority_queue = [(0, start)]

    while priority_queue:
        current_distance, current_node = heapq.heappop(priority_queue)

        if current_node == end:
            break

        if current_distance > distances[current_node]:
            continue

        for neighbor, weight in graph[current_node]:
            new_distance = current_distance + weight

            if new_distance < distances[neighbor]:
                distances[neighbor] = new_distance
                previous[neighbor] = current_node
                heapq.heappush(priority_queue, (new_distance, neighbor))

    if end not in distances or distances[end] == float("inf"):
        return None, None

    path = []
    current = end

    while current is not None:
        path.append(current)
        current = previous[current]

    path.reverse()

    return path, distances[end]