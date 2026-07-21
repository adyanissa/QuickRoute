import { apiRequest } from "./api";

// GET /api/location-codes/resolve/{code} — public, no auth required.
// response: { code, building_id, map_id, route_point_id, label }
export function resolveLocationCode(code) {
  return apiRequest(
    `/api/location-codes/resolve/${encodeURIComponent(code)}`,
  );
}

// GET /api/location-codes — supports optional filters:
// building_id, map_id, is_active
export function getLocationCodes(filters = {}) {
  const params = new URLSearchParams();

  if (filters.building_id) params.set("building_id", filters.building_id);
  if (filters.map_id) params.set("map_id", filters.map_id);
  if (filters.is_active !== undefined && filters.is_active !== null) {
    params.set("is_active", filters.is_active);
  }

  const query = params.toString();
  return apiRequest(`/api/location-codes${query ? `?${query}` : ""}`);
}

export function getLocationCodeById(codeId) {
  return apiRequest(`/api/location-codes/${codeId}`);
}

// data: { code, building_id, map_id, route_point_id, label?, is_active? }
export function createLocationCode(data) {
  return apiRequest("/api/location-codes", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export function updateLocationCode(codeId, data) {
  return apiRequest(`/api/location-codes/${codeId}`, {
    method: "PUT",
    body: JSON.stringify(data),
  });
}

export function deleteLocationCode(codeId) {
  return apiRequest(`/api/location-codes/${codeId}`, {
    method: "DELETE",
  });
}
