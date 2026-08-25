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

// GET /api/route-points/count — same filters as getRoutePoints(), plus
// `source`. Always returns a scope-labeled RoutePointCountResponse
// (count/map_id/building_id/room_id/floor/point_type/source/is_global) —
// never a bare number — so a caller can never present it without also
// knowing (and being able to show) exactly what it's scoped to. Use this
// instead of `getRoutePoints(...).length` for any dashboard/summary
// metric: it shares the exact same query builder + authorized-scope
// narrowing as the list/paginated-list endpoints server-side, so it can
// never disagree with what a matching filtered list actually shows.
export function getRoutePointCount(filters = {}) {
  const params = new URLSearchParams();
  if (filters.map_id) params.set("map_id", filters.map_id);
  if (filters.building_id) params.set("building_id", filters.building_id);
  if (filters.room_id) params.set("room_id", filters.room_id);
  if (filters.floor !== undefined && filters.floor !== null) {
    params.set("floor", filters.floor);
  }
  if (filters.point_type) params.set("point_type", filters.point_type);
  if (filters.source) params.set("source", filters.source);

  const query = params.toString();
  return apiRequest(`/api/route-points/count${query ? `?${query}` : ""}`);
}

// GET /api/route-points/list — the paginated, filtered, scope-authorized
// admin management endpoint (RBAC/dashboard cleanup task, Phase 8/11).
// Server-side filtering + pagination: this never downloads the full
// RoutePoint set and paginates in React. `page`/`pageSize` are 1-based /
// count-of-items respectively, matching the backend's own `page`/
// `page_size` query params exactly.
export function getRoutePointsList({
  mapId,
  buildingId,
  mapGroupId,
  roomId,
  floor,
  pointType,
  source,
  search,
  page = 1,
  pageSize = 50,
} = {}) {
  const params = new URLSearchParams();
  if (mapId) params.set("map_id", mapId);
  if (buildingId) params.set("building_id", buildingId);
  if (mapGroupId) params.set("map_group_id", mapGroupId);
  if (roomId) params.set("room_id", roomId);
  if (floor !== undefined && floor !== null && floor !== "") {
    params.set("floor", floor);
  }
  if (pointType) params.set("point_type", pointType);
  if (source) params.set("source", source);
  if (search) params.set("search", search);
  params.set("page", String(page));
  params.set("page_size", String(pageSize));

  return apiRequest(`/api/route-points/list?${params.toString()}`);
}

// RBAC/dashboard cleanup task, Phase 3 — the public, unauthenticated
// counterparts of getRoutePoints/getRoutePointById above, scoped to the
// minimal fields navigation actually needs and (for the list form) always
// requiring an explicit map_id, never a global unscoped dump. Use these
// two from any screen reachable by an anonymous/QR/kiosk visitor
// (IndoorNavigationScreen.jsx); keep using the admin versions above only
// from authenticated admin screens.
export function getPublicRoutePoints({ mapId, buildingId, pointType } = {}) {
  const params = new URLSearchParams();
  if (mapId) params.set("map_id", mapId);
  if (buildingId) params.set("building_id", buildingId);
  if (pointType) params.set("point_type", pointType);

  return apiRequest(`/api/route-points/public?${params.toString()}`);
}

export function getPublicRoutePointById(pointId) {
  return apiRequest(`/api/route-points/public/${pointId}`);
}

// RBAC/dashboard cleanup task, Phase 6 — preview never deletes anything;
// it reports exactly what apply would do if sent the same pointIds list
// right now (deletable ids, blocking issues, non-blocking warnings).
export function previewBulkDeleteRoutePoints(pointIds) {
  return apiRequest("/api/route-points/bulk-delete/preview", {
    method: "POST",
    body: JSON.stringify({ point_ids: pointIds }),
  });
}

// Strictly all-or-nothing on the backend: if ANY id has a blocking issue,
// the whole request is rejected (409) and nothing is deleted. Always run
// previewBulkDeleteRoutePoints first and only call this once the admin
// has confirmed against a preview with can_apply_all === true.
export function applyBulkDeleteRoutePoints(pointIds) {
  return apiRequest("/api/route-points/bulk-delete/apply", {
    method: "POST",
    body: JSON.stringify({ point_ids: pointIds }),
  });
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
