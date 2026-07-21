import { apiRequest } from "./api";
import API_BASE_URL from "./api";

// ── Helpers ─────────────────────────────────────────────────────────────────

// Turns a relative backend path (e.g. "/static/maps/source/x.png") into an
// absolute URL against the API host. Leaves absolute URLs / data URLs as-is.
export const buildMapAssetUrl = (value) => {
  if (!value) return null;

  if (/^https?:\/\//i.test(value) || value.startsWith("data:")) {
    return value;
  }

  const cleanBase = String(API_BASE_URL || "").replace(/\/$/, "");
  const cleanPath = value.startsWith("/") ? value : `/${value}`;

  return `${cleanBase}${cleanPath}`;
};

// Normalizes a backend MapResponse (snake_case) into the view-model shape
// used across the admin and end-user screens.
export const normalizeMap = (map) => {
  if (!map) return null;

  const imageUrl = buildMapAssetUrl(map.image_url ?? map.imageUrl);
  const sourceImageUrl = buildMapAssetUrl(map.source_image_url ?? map.sourceImageUrl);
  const displayImageUrl = buildMapAssetUrl(map.display_image_url ?? map.displayImageUrl);

  return {
    ...map,
    id: map.id ?? map._id,
    imageUrl,
    sourceImageUrl,
    displayImageUrl,
    hasImage: Boolean(imageUrl || sourceImageUrl || displayImageUrl),
    isCurrent: Boolean(map.is_current ?? map.isCurrent),
    processingStatus: map.processing_status ?? map.processingStatus ?? "not_started",
    processingProgress: Number(map.processing_progress ?? map.processingProgress ?? 0),
    processingError: map.processing_error ?? map.processingError ?? null,
    generationMethod: map.generation_method ?? map.generationMethod ?? null,
  };
};

// ── Read endpoints ──────────────────────────────────────────────────────────

export async function getMaps() {
  const data = await apiRequest("/api/maps");
  return Array.isArray(data) ? data.map(normalizeMap) : [];
}

export async function getCurrentMap() {
  const data = await apiRequest("/api/maps/current");
  return normalizeMap(data);
}

export async function getMapById(mapId) {
  const data = await apiRequest(`/api/maps/${mapId}`);
  return normalizeMap(data);
}

export async function getMapProcessingStatus(mapId) {
  return apiRequest(`/api/maps/${mapId}/processing-status`);
}

// ── Write endpoints ─────────────────────────────────────────────────────────

export async function createMap(mapData) {
  const data = await apiRequest("/api/maps", {
    method: "POST",
    body: JSON.stringify(mapData),
  });
  return normalizeMap(data);
}

export async function updateMap(mapId, mapData) {
  const data = await apiRequest(`/api/maps/${mapId}`, {
    method: "PUT",
    body: JSON.stringify(mapData),
  });
  return normalizeMap(data);
}

export async function deleteMap(mapId) {
  return apiRequest(`/api/maps/${mapId}`, { method: "DELETE" });
}

export async function retryMapProcessing(mapId, useOpenai = true) {
  return apiRequest(
    `/api/maps/${mapId}/retry-processing?use_openai=${useOpenai ? "true" : "false"}`,
    { method: "POST" }
  );
}

// Upload is multipart/form-data, so it cannot go through the JSON-only
// apiRequest helper. It uses the same API_BASE_URL as everything else —
// no hardcoded host.
export async function uploadMap(formData) {
  const response = await fetch(`${API_BASE_URL}/api/maps/upload`, {
    method: "POST",
    body: formData,
  });

  if (!response.ok) {
    let message = await response.text();

    try {
      const parsed = JSON.parse(message);
      message = parsed.detail || message;
    } catch {
      // Keep the raw backend text if it isn't JSON.
    }

    throw new Error(message);
  }

  const data = await response.json();
  return normalizeMap(data);
}
