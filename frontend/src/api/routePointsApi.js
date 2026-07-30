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

// autoConnect: "off" (default) | "nearest" | "all_valid" — matches the
// backend's ?auto_connect= query param used by the "Merge with safe nearby
// graph points" Draw Walkable Path option. Left unset/"off" preserves the
// exact previous behavior (no surprise edges).
export function createRoutePoint(pointData, { autoConnect } = {}) {
  const query =
    autoConnect && autoConnect !== "off"
      ? `?auto_connect=${encodeURIComponent(autoConnect)}`
      : "";

  return apiRequest(`/api/route-points${query}`, {
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

// Legacy data-consistency repair: corrects RoutePoint.floor to match its
// Map's floor wherever it's missing/stale. Always call with dryRun=true
// first (the backend also defaults to true) to preview the exact count
// of points that would change before ever writing anything — see
// backend/routes/route_point_routes.py's backfill_floor_from_map for the
// full contract (idempotent, never touches coordinates/names/ids/edges).
export function backfillRoutePointFloorFromMap(dryRun = true) {
  return apiRequest("/api/route-points/backfill-floor-from-map", {
    method: "POST",
    body: JSON.stringify({ dry_run: dryRun }),
  });
}
