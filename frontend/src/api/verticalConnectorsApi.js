import { apiRequest } from "./api.js";

// Same normalize-with-camelCase-overrides convention as mapsApi.js /
// mapGroupsApi.js — keeps every backend field plus convenience aliases.
export const normalizeConnectorStop = (stop) => {
  if (!stop) return null;
  return {
    ...stop,
    routePointId: stop.route_point_id,
    mapId: stop.map_id,
    connectedToFloorGraph: Boolean(stop.connected_to_floor_graph),
  };
};

export const normalizeConnector = (connector) => {
  if (!connector) return null;
  return {
    ...connector,
    id: connector.id ?? connector._id,
    buildingId: connector.building_id,
    mapGroupId: connector.map_group_id,
    connectorCode: connector.connector_code,
    connectorType: connector.connector_type,
    isBidirectional: Boolean(connector.is_bidirectional),
    isAccessible: Boolean(connector.is_accessible),
    isActive: connector.is_active !== false,
    waitTimeSeconds: Number(connector.wait_time_seconds ?? 0),
    secondsPerFloor: Number(connector.seconds_per_floor ?? 0),
    distancePerFloorMeters: Number(connector.distance_per_floor_meters ?? 0),
    isFullyConnected: Boolean(connector.is_fully_connected),
    stops: Array.isArray(connector.stops)
      ? connector.stops.map(normalizeConnectorStop)
      : [],
  };
};

// ── Read endpoints ──────────────────────────────────────────────────────────

export async function getVerticalConnectors({ mapGroupId, buildingId } = {}) {
  const params = new URLSearchParams();
  if (mapGroupId) params.set("map_group_id", mapGroupId);
  if (buildingId) params.set("building_id", buildingId);
  const query = params.toString();

  const data = await apiRequest(
    `/api/vertical-connectors${query ? `?${query}` : ""}`,
  );
  return Array.isArray(data) ? data.map(normalizeConnector) : [];
}

export async function getVerticalConnectorById(connectorId) {
  const data = await apiRequest(`/api/vertical-connectors/${connectorId}`);
  return normalizeConnector(data);
}

// ── Write endpoints ─────────────────────────────────────────────────────────

// fields: { buildingId, mapGroupId, connectorCode?, name, connectorType,
//   isBidirectional?, isAccessible?, waitTimeSeconds?, secondsPerFloor?,
//   distancePerFloorMeters?, description? }
export async function createVerticalConnector(fields) {
  const body = {
    building_id: fields.buildingId,
    map_group_id: fields.mapGroupId,
    name: fields.name,
    connector_type: fields.connectorType,
  };
  if (fields.connectorCode) body.connector_code = fields.connectorCode;
  if (fields.isBidirectional !== undefined) body.is_bidirectional = fields.isBidirectional;
  if (fields.isAccessible !== undefined) body.is_accessible = fields.isAccessible;
  if (fields.waitTimeSeconds !== undefined) body.wait_time_seconds = Number(fields.waitTimeSeconds);
  if (fields.secondsPerFloor !== undefined) body.seconds_per_floor = Number(fields.secondsPerFloor);
  if (fields.distancePerFloorMeters !== undefined) {
    body.distance_per_floor_meters = Number(fields.distancePerFloorMeters);
  }
  if (fields.description) body.description = fields.description;

  const data = await apiRequest("/api/vertical-connectors", {
    method: "POST",
    body: JSON.stringify(body),
  });
  return normalizeConnector(data);
}

export async function updateVerticalConnector(connectorId, fields) {
  const body = {};
  if (fields.name !== undefined) body.name = fields.name;
  if (fields.isBidirectional !== undefined) body.is_bidirectional = fields.isBidirectional;
  if (fields.isAccessible !== undefined) body.is_accessible = fields.isAccessible;
  if (fields.isActive !== undefined) body.is_active = fields.isActive;
  if (fields.waitTimeSeconds !== undefined) body.wait_time_seconds = Number(fields.waitTimeSeconds);
  if (fields.secondsPerFloor !== undefined) body.seconds_per_floor = Number(fields.secondsPerFloor);
  if (fields.distancePerFloorMeters !== undefined) {
    body.distance_per_floor_meters = Number(fields.distancePerFloorMeters);
  }
  if (fields.description !== undefined) body.description = fields.description;

  const data = await apiRequest(`/api/vertical-connectors/${connectorId}`, {
    method: "PUT",
    body: JSON.stringify(body),
  });
  return normalizeConnector(data);
}

export async function deleteVerticalConnector(connectorId) {
  return apiRequest(`/api/vertical-connectors/${connectorId}`, {
    method: "DELETE",
  });
}

// Places (or reuses) this connector's stop on one floor's map — mapId/x/y
// must come from a real click on THAT floor's own image, never copied from
// another floor's coordinates.
export async function addConnectorStop(connectorId, { mapId, x, y, name, autoConnect }) {
  const data = await apiRequest(`/api/vertical-connectors/${connectorId}/stops`, {
    method: "POST",
    body: JSON.stringify({
      map_id: mapId,
      x,
      y,
      name: name || undefined,
      auto_connect: autoConnect || "nearest",
    }),
  });
  return normalizeConnector(data);
}

export async function removeConnectorStop(connectorId, routePointId) {
  const data = await apiRequest(
    `/api/vertical-connectors/${connectorId}/stops/${routePointId}`,
    { method: "DELETE" },
  );
  return normalizeConnector(data);
}

// PHASE 15 — Admin "Validate Multi-Floor Navigation" report for one group.
export async function validateMapGroupNavigation(groupId) {
  return apiRequest(`/api/map-groups/${groupId}/validate-navigation`);
}
