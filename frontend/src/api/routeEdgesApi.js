import { apiRequest } from "./api";

// GET /api/route-edges — supports optional filters:
// map_id, from_point_id, to_point_id, edge_type, is_accessible
export function getRouteEdges(filters = {}) {
  const params = new URLSearchParams();

  if (filters.map_id) params.set("map_id", filters.map_id);
  if (filters.from_point_id) params.set("from_point_id", filters.from_point_id);
  if (filters.to_point_id) params.set("to_point_id", filters.to_point_id);
  if (filters.edge_type) params.set("edge_type", filters.edge_type);
  if (filters.is_accessible !== undefined && filters.is_accessible !== null) {
    params.set("is_accessible", filters.is_accessible);
  }

  const query = params.toString();
  return apiRequest(`/api/route-edges${query ? `?${query}` : ""}`);
}

export function getRouteEdgeById(edgeId) {
  return apiRequest(`/api/route-edges/${edgeId}`);
}

// edgeData: { map_id, from_point_id, to_point_id, edge_type, distance_override,
// is_bidirectional, is_accessible, description }
// Note: `distance` is always calculated server-side and must never be sent
// or computed on the frontend.
export function createRouteEdge(edgeData) {
  return apiRequest("/api/route-edges", {
    method: "POST",
    body: JSON.stringify(edgeData),
  });
}

export function deleteRouteEdge(edgeId) {
  return apiRequest(`/api/route-edges/${edgeId}`, {
    method: "DELETE",
  });
}
