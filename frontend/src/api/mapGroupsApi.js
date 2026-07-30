import { apiRequest, getStoredToken, clearStoredAuth } from "./api";
import API_BASE_URL from "./api";
import { normalizeMap } from "./mapsApi";

// ── Helpers ─────────────────────────────────────────────────────────────────

// Same shape convention as mapsApi.js's normalizeMap: keeps every backend
// field plus camelCase overrides, so callers can use either naming without
// a second round of mapping.
export const normalizeMapGroup = (group) => {
  if (!group) return null;

  return {
    ...group,
    id: group.id ?? group._id,
    buildingId: group.building_id ?? group.buildingId ?? null,
    floorCount: Number(group.floor_count ?? group.floorCount ?? 0),
    floors: Array.isArray(group.floors)
      ? group.floors.map(normalizeMap)
      : [],
  };
};

// ── Read endpoints ──────────────────────────────────────────────────────────

export async function getMapGroups(buildingId) {
  const query = buildingId ? `?building_id=${encodeURIComponent(buildingId)}` : "";
  const data = await apiRequest(`/api/map-groups${query}`);
  return Array.isArray(data) ? data.map(normalizeMapGroup) : [];
}

export async function getMapGroupById(groupId) {
  const data = await apiRequest(`/api/map-groups/${groupId}`);
  return normalizeMapGroup(data);
}

// ── Write endpoints ─────────────────────────────────────────────────────────

export async function updateMapGroup(groupId, data) {
  const result = await apiRequest(`/api/map-groups/${groupId}`, {
    method: "PUT",
    body: JSON.stringify(data),
  });
  return normalizeMapGroup(result);
}

export async function deleteMapGroupFloor(groupId, mapId) {
  return apiRequest(`/api/map-groups/${groupId}/floors/${mapId}`, {
    method: "DELETE",
  });
}

export async function deleteMapGroup(groupId) {
  return apiRequest(`/api/map-groups/${groupId}`, { method: "DELETE" });
}

// ── Multipart batch endpoints (create group / add floors) ──────────────────
// Mirrors mapsApi.js's uploadMap: raw fetch (never apiRequest, which forces
// a JSON Content-Type that would break the multipart boundary), manual
// bearer-token attachment, manual 401 -> clearStoredAuth handling.

async function postMultipart(path, formData) {
  const token = getStoredToken();

  const response = await fetch(`${API_BASE_URL}${path}`, {
    method: "POST",
    headers: {
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: formData,
  });

  if (!response.ok) {
    let message = await response.text();
    try {
      const parsed = JSON.parse(message);
      message = parsed.detail || message;
    } catch {
      // message stays as the raw response text
    }
    if (response.status === 401) {
      clearStoredAuth();
    }
    throw new Error(
      typeof message === "string" ? message : JSON.stringify(message),
    );
  }

  return response.json();
}

// groupFields: { name, code?, buildingId?, campus?, address?, description? }
// floors: [{ file, title, floor, floorLabel?, scale?, useOpenAI?, autoGenerateGraph? }, ...]
export async function createMapGroup(groupFields, floors) {
  const formData = new FormData();

  formData.append("name", groupFields.name);
  if (groupFields.code) formData.append("code", groupFields.code);
  if (groupFields.buildingId) formData.append("building_id", groupFields.buildingId);
  if (groupFields.campus) formData.append("campus", groupFields.campus);
  if (groupFields.address) formData.append("address", groupFields.address);
  if (groupFields.description) formData.append("description", groupFields.description);

  const floorsJson = floors.map((floor) => ({
    title: floor.title,
    floor: Number(floor.floor),
    floor_label: floor.floorLabel || null,
    scale: Number(floor.scale) > 0 ? Number(floor.scale) : 1,
    use_openai: Boolean(floor.useOpenAI),
    auto_generate_graph: floor.autoGenerateGraph !== false,
  }));

  formData.append("floors_json", JSON.stringify(floorsJson));
  floors.forEach((floor) => formData.append("files", floor.file));

  const data = await postMultipart("/api/map-groups", formData);
  return normalizeMapGroup(data);
}

// Same `floors` shape as createMapGroup, added to an EXISTING group.
export async function addMapGroupFloors(groupId, floors) {
  const formData = new FormData();

  const floorsJson = floors.map((floor) => ({
    title: floor.title,
    floor: Number(floor.floor),
    floor_label: floor.floorLabel || null,
    scale: Number(floor.scale) > 0 ? Number(floor.scale) : 1,
    use_openai: Boolean(floor.useOpenAI),
    auto_generate_graph: floor.autoGenerateGraph !== false,
  }));

  formData.append("floors_json", JSON.stringify(floorsJson));
  floors.forEach((floor) => formData.append("files", floor.file));

  const data = await postMultipart(`/api/map-groups/${groupId}/floors`, formData);
  return normalizeMapGroup(data);
}
