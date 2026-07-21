import { apiRequest } from "./api";

// GET /api/rooms — supports optional filters: building_id, floor, room_type
export function getRooms(filters = {}) {
  const params = new URLSearchParams();

  if (filters.building_id) params.set("building_id", filters.building_id);
  if (filters.floor !== undefined && filters.floor !== null) {
    params.set("floor", filters.floor);
  }
  if (filters.room_type) params.set("room_type", filters.room_type);

  const query = params.toString();
  return apiRequest(`/api/rooms${query ? `?${query}` : ""}`);
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
