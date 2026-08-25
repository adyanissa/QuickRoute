import { apiRequest } from "./api";

// GET /api/rooms — supports optional filters: building_id, floor, room_type
//
// `options` is forwarded verbatim to apiRequest (and therefore to fetch),
// so a caller can pass `{ signal }` to abort a request it has superseded.
// Optional and defaulted, so every existing call site is unaffected.
export function getRooms(filters = {}, options = {}) {
  const params = new URLSearchParams();

  if (filters.building_id) params.set("building_id", filters.building_id);
  if (filters.floor !== undefined && filters.floor !== null) {
    params.set("floor", filters.floor);
  }
  if (filters.room_type) params.set("room_type", filters.room_type);

  const query = params.toString();
  return apiRequest(`/api/rooms${query ? `?${query}` : ""}`, options);
}

export function getRoomById(roomId) {
  return apiRequest(`/api/rooms/${roomId}`);
}

export function createRoom(roomData) {
  return apiRequest("/api/rooms", {
    method: "POST",
    body: JSON.stringify(roomData),
  });
}

export function updateRoom(roomId, roomData) {
  return apiRequest(`/api/rooms/${roomId}`, {
    method: "PUT",
    body: JSON.stringify(roomData),
  });
}

export function deleteRoom(roomId) {
  return apiRequest(`/api/rooms/${roomId}`, {
    method: "DELETE",
  });
}

// Admin-only bulk repair (destination data flow, Section 4): "Sync Rooms
// from Route Points". Scoped by exactly one of building_id/map_group_id —
// creates/updates linked Rooms for existing "room"/"store" RoutePoints
// that predate automatic Room creation, so the admin never has to open
// Add Room once per point. Never touches Dijkstra/routing/graph topology
// — see backend/routes/room_routes.py's sync_rooms_from_route_points.
export function syncRoomsFromRoutePoints({ building_id, map_group_id } = {}) {
  return apiRequest("/api/rooms/sync-from-route-points", {
    method: "POST",
    body: JSON.stringify({
      building_id: building_id || null,
      map_group_id: map_group_id || null,
    }),
  });
}
