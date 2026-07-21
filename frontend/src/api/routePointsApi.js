import { apiRequest } from "./api";

// GET /api/route-points — supports optional filters:
// map_id, building_id, room_id, floor, point_type
export function getRoutePoints(filters = {}) {
  const params = new URLSearchParams();

  if (filters.map_id) params.set("map_id", filters.map_id);
  if (filters.building_id) params.set("building_id", filters.building_id);
  if (filters.room_id) params.set("room_id", filters.room_id);
  if (filters.floor !== undefined && filters.floor !== null) {
    params.set("floor", filters.floor);
  }
  if (filters.point_type) params.set("point_type", filters.point_type);

  const query = params.toString();
  return apiRequest(`/api/route-points${query ? `?${query}` : ""}`);
}

export function getRoutePointById(pointId) {
  return apiRequest(`/api/route-points/${pointId}`);
}

export function createRoutePoint(pointData) {
  return apiRequest("/api/route-points", {
    method: "POST",
    body: JSON.stringify(pointData),
  });
}

export function updateRoutePoint(pointId, pointData) {
  return apiRequest(`/api/route-points/${pointId}`, {
    method: "PUT",
    body: JSON.stringify(pointData),
  });
}

export function deleteRoutePoint(pointId) {
  return apiRequest(`/api/route-points/${pointId}`, {
    method: "DELETE",
  });
}
