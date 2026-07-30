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

// "Auto Connect Destinations to Corridors" — preview/apply pair.
// previewOptions: { map_id, floor, max_distance_px, scope, lang }
// 100% read-only server-side — never creates a RouteEdge.
export function previewAutoConnectDestinations(previewOptions) {
  return apiRequest("/api/route-edges/auto-connect-destinations/preview", {
    method: "POST",
    body: JSON.stringify(previewOptions),
  });
}

// applyOptions: { map_id, accepted: [{ destination_point_id, corridor_point_id }] }
// Creates exactly the accepted pairs — every pair is revalidated server-side.
export function applyAutoConnectDestinations(applyOptions) {
  return apiRequest("/api/route-edges/auto-connect-destinations/apply", {
    method: "POST",
    body: JSON.stringify(applyOptions),
  });
}
