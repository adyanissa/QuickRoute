from flask import Blueprint, jsonify, request
import json
import os

from services.route_service import build_graph, dijkstra

navigation_bp = Blueprint("navigation", __name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_json_file(filename):
    file_path = os.path.join(BASE_DIR, "data", filename)

    with open(file_path, "r", encoding="utf-8") as file:
        return json.load(file)


@navigation_bp.route("/buildings")
def get_buildings():
    buildings = load_json_file("buildings.json")
    return jsonify(buildings)


@navigation_bp.route("/buildings/<building_id>/rooms")
def get_rooms_by_building(building_id):
    rooms = load_json_file("rooms.json")

    if building_id not in rooms:
        return jsonify({
            "error": "Building not found"
        }), 404

    return jsonify(rooms[building_id])


@navigation_bp.route("/rooms/<room_id>")
def get_room_by_id(room_id):
    rooms = load_json_file("rooms.json")

    for building_rooms in rooms.values():
        for room in building_rooms:
            if room["id"] == room_id:
                return jsonify(room)

    return jsonify({
        "error": "Room not found"
    }), 404


@navigation_bp.route("/graph")
def get_graph():
    graph = load_json_file("map_graph.json")
    return jsonify(graph)


@navigation_bp.route("/route")
def get_smart_route():
    start = request.args.get("from")
    end = request.args.get("to")

    if not start or not end:
        return jsonify({
            "error": "Missing from or to parameter"
        }), 400

    graph_data = load_json_file("map_graph.json")

    nodes = graph_data["nodes"]
    edges = graph_data["edges"]

    node_ids = [node["id"] for node in nodes]

    if start not in node_ids:
        return jsonify({
            "error": "Start node not found",
            "start": start
        }), 404

    if end not in node_ids:
        return jsonify({
            "error": "End node not found",
            "end": end
        }), 404

    graph = build_graph(edges)
    path, total_distance = dijkstra(graph, start, end)

    if path is None:
        return jsonify({
            "error": "No route found"
        }), 404

    path_details = []

    for node_id in path:
        node = next((n for n in nodes if n["id"] == node_id), None)
        if node:
            path_details.append(node)

    return jsonify({
        "from": start,
        "to": end,
        "path": path,
        "pathDetails": path_details,
        "totalDistance": total_distance
    })