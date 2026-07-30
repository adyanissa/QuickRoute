import { apiRequest, getStoredToken, clearStoredAuth } from "./api";
import API_BASE_URL from "./api";
import { normalizeId, normalizeFloorNumber } from "../utils/mapGroupHelpers";

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
// used across the admin and end-user screens. This is the SINGLE place
// that decides what a Map's real id/floor/group/building are — every
// other consumer (AdminMapScreen.jsx's activeMap, floor-option building,
// existing-point reuse checks) trusts these fields verbatim rather than
// re-deriving them, so it must be defensive about real-world shape
// variance rather than assuming exactly one backend response shape:
//   - id: also accepts `_id`/`map_id`/`mapId` (defensive — the backend's
//     MapResponse always uses `id`, but a raw Mongo document or a
//     differently-shaped response should never silently resolve to
//     `undefined`).
//   - floor: also accepts `floor_number`/`floorNumber`/`level`, coerced
//     through normalizeFloorNumber() which explicitly preserves 0 (Ground
//     Floor) instead of the old `?? null`-only check, which itself was
//     safe for 0 but gave every consumer no way to tell "explicitly
//     unknown" apart from a genuinely-absent value — normalizeFloorNumber
//     centralizes that so mapGroupHelpers.js's buildFloorOptions() can
//     never disagree with this layer about what counts as a known floor.
//   - mapGroupId/buildingId: run through the same normalizeId() as
//     buildFloorOptions() so an ObjectId-shaped value on either side of a
//     later comparison can never mismatch a plain string just because one
//     side wasn't stringified.
//   - isActive: new field (defaults true) so a soft-deleted/disabled Map
//     can be told apart from a normal one without every caller having to
//     know the raw `is_active`/`isActive` field names.
export const normalizeMap = (map) => {
  if (!map) return null;

  const imageUrl = buildMapAssetUrl(map.image_url ?? map.imageUrl);
  const sourceImageUrl = buildMapAssetUrl(map.source_image_url ?? map.sourceImageUrl);
  const displayImageUrl = buildMapAssetUrl(map.display_image_url ?? map.displayImageUrl);

  return {
    ...map,
    id: normalizeId(map.id, map._id, map.map_id, map.mapId),
    imageUrl,
    sourceImageUrl,
    displayImageUrl,
    hasImage: Boolean(imageUrl || sourceImageUrl || displayImageUrl),
    isCurrent: Boolean(map.is_current ?? map.isCurrent),
    isActive: Boolean(map.is_active ?? map.isActive ?? true),
    processingStatus: map.processing_status ?? map.processingStatus ?? "not_started",
    processingProgress: Number(map.processing_progress ?? map.processingProgress ?? 0),
    processingError: map.processing_error ?? map.processingError ?? null,
    generationMethod: map.generation_method ?? map.generationMethod ?? null,
    buildingId: normalizeId(map.building_id, map.buildingId),
    floor: normalizeFloorNumber(map.floor, map.floor_number, map.floorNumber, map.level),
    floorLabel: map.floor_label ?? map.floorLabel ?? null,
    mapGroupId: normalizeId(map.map_group_id, map.mapGroupId, map.group_id),
    mapGroupCode: map.map_group_code ?? map.mapGroupCode ?? null,
    isCurrentForFloor: Boolean(
      map.is_current_for_floor ?? map.isCurrentForFloor ?? true,
    ),
    graphGenerationStatus: map.graph_generation_status ?? map.graphGenerationStatus ?? null,
    graphGenerationConfidence: map.graph_generation_confidence ?? map.graphGenerationConfidence ?? null,
    graphGenerationNote: map.graph_generation_note ?? map.graphGenerationNote ?? null,
    // PHASE 8 — scale=1 (the pre-calibration placeholder) must never be
    // mistaken for "measured": every consumer must check isCalibrated
    // rather than inferring accuracy from the scale value itself.
    scale: Number(map.scale ?? 1),
    isCalibrated: Boolean(map.is_calibrated ?? map.isCalibrated),
    calibratedAt: map.calibrated_at ?? map.calibratedAt ?? null,
    calibrationSource: map.calibration_source ?? map.calibrationSource ?? null,
    // Only present on the two calibration endpoints' responses
    // (MapCalibrationResponse) — every other Map response simply has
    // neither snake_case field, so these default safely to 0 and never
    // appear anywhere except right after a calibration save.
    edgesRecalculated: Number(map.edges_recalculated ?? map.edgesRecalculated ?? 0),
    edgesRecalculationSkipped: Number(
      map.edges_recalculation_skipped ?? map.edgesRecalculationSkipped ?? 0,
    ),
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

// Runs (or re-runs) automatic walkable-graph generation against this
// map's already-processed source image. See backend generate_map_graph —
// safe to call repeatedly, never duplicates a previous auto-generated
// graph, and never touches manually drawn points/edges.
export async function generateMapGraph(mapId) {
  const data = await apiRequest(`/api/maps/${mapId}/generate-graph`, {
    method: "POST",
  });
  return normalizeMap(data);
}

// Removes only this map's auto-generated points/edges.
export async function clearGeneratedMapGraph(mapId) {
  return apiRequest(`/api/maps/${mapId}/generated-graph`, {
    method: "DELETE",
  });
}

// PHASE 8 — two-click scale calibration. pointA/pointB are original-image
// pixel coordinates the admin clicked; realDistanceMeters is what the
// admin measured/knows in the real world between those two exact spots.
// meters_per_pixel is always computed server-side — never trust a
// client-computed scale.
export async function calibrateMapScale(mapId, { pointA, pointB, realDistanceMeters }) {
  const data = await apiRequest(`/api/maps/${mapId}/calibrate-scale`, {
    method: "POST",
    body: JSON.stringify({
      point_a_x: pointA.x,
      point_a_y: pointA.y,
      point_b_x: pointB.x,
      point_b_y: pointB.y,
      real_distance_meters: realDistanceMeters,
    }),
  });
  return normalizeMap(data);
}

// Explicit admin-only action (PHASE 8): copy an already-measured scale
// from one already-calibrated floor onto another floor that shares the
// same architectural scale — never chains an uncalibrated placeholder.
export async function copyMapCalibration(mapId, sourceMapId) {
  const data = await apiRequest(`/api/maps/${mapId}/copy-calibration`, {
    method: "POST",
    body: JSON.stringify({ source_map_id: sourceMapId }),
  });
  return normalizeMap(data);
}

// Best-effort OCR name suggestion for a map-based destination click.
// {x, y} are original-image pixel coordinates (never browser/display
// pixels). This never creates, updates, or deletes anything — it only
// reads the map's source image and returns a suggestion for the admin to
// confirm or edit; see AdminRoomsScreen.jsx's "Suggest Name from Map".
export async function suggestDestinationName(mapId, { x, y, width, height } = {}) {
  const body = { x, y };
  if (width !== undefined && width !== null) body.width = width;
  if (height !== undefined && height !== null) body.height = height;

  return apiRequest(`/api/maps/${mapId}/ocr-suggest`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

// Upload is multipart/form-data, so it cannot go through the JSON-only
// apiRequest helper (that helper always sets Content-Type: application/json,
// which would break the multipart boundary the browser needs to generate
// for FormData). It still needs the same Authorization header every other
// protected request sends, so it reads the token from the same shared
// storage helper apiRequest() itself uses — no separate/duplicated token
// logic — and deliberately does NOT set Content-Type here: the browser
// must set it (including the multipart boundary) itself.
export async function uploadMap(formData) {
  const token = getStoredToken();

  const response = await fetch(`${API_BASE_URL}/api/maps/upload`, {
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
      // Keep the raw backend text if it isn't JSON.
    }

    // Same as apiRequest(): an expired/invalid token means the stored
    // session is no longer valid anywhere, so clear it here too instead of
    // leaving mapsApi.js as the one place a stale token silently lingers.
    if (response.status === 401) {
      clearStoredAuth();
    }

    throw new Error(message);
  }

  const data = await response.json();
  return normalizeMap(data);
}
