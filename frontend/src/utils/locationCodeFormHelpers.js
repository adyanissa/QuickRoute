// Pure helpers for the Admin "Location Codes" dependent Building -> Map ->
// Start Point form (AdminLocationCodesScreen.jsx). Kept dependency-free so
// the id-normalization and filtering rules that were the actual root cause
// of the "Map dropdown stays empty" bug can be unit-tested without a
// DOM/React harness — see locationCodeFormHelpers.test.mjs.

import { sortFloorsByNumber, buildMapOptionLabel, formatFloorDisplay } from './mapGroupHelpers.js';

// Building/Map ids arrive from a few different shapes depending on which
// API response they came from (a plain string id, an ObjectId-like object
// with a .toString(), or occasionally still undefined/null while data is
// loading). Every comparison in this form must go through this first, or
// a perfectly valid "the ids really do match" case can silently fail a
// strict `===` check (e.g. comparing a string to an object).
export function normalizeId(value) {
  if (value === null || value === undefined || value === '') return '';
  return String(value);
}

export function idsMatch(a, b) {
  const normalizedA = normalizeId(a);
  const normalizedB = normalizeId(b);
  return normalizedA !== '' && normalizedA === normalizedB;
}

// Building dropdown options — the ONLY source is the real Building
// collection (never Maps). value is always the Building id (normalized to
// a string); label is the building's display name, never a map title.
export function buildBuildingOptions(buildings) {
  return (Array.isArray(buildings) ? buildings : [])
    .filter((b) => b && b.id != null)
    .map((b) => ({
      value: normalizeId(b.id),
      label: b.nameEn || b.name || b.name_local || '',
    }));
}

// Maps belonging to the selected building — filtered by building_id, never
// by campus text and never showing every map regardless of building.
// Returns [] (not "all maps") when no building is selected, so the Map
// dropdown can never appear populated before a building is chosen.
export function filterMapsForBuilding(maps, selectedBuildingId) {
  if (!normalizeId(selectedBuildingId)) return [];

  return (Array.isArray(maps) ? maps : []).filter((m) =>
    idsMatch(m?.buildingId ?? m?.building_id, selectedBuildingId)
  );
}

// PHASE "Final Submission" Part 2 — same Building -> Map Group -> Floor
// Map consistency required for Rooms also applies here: floors sorted
// ascending (never raw fetch order) and each option labeled with its
// Map Group code + floor label, not just a bare map title, so an admin
// creating a Location Code can actually tell Floor 1 from Floor 2 in a
// building with several near-identically-named floor maps.
export function buildMapOptions(maps) {
  const sorted = sortFloorsByNumber(
    (Array.isArray(maps) ? maps : []).filter((m) => m && m.id != null)
  );

  return sorted.map((m) => ({
    value: normalizeId(m.id),
    label: buildMapOptionLabel(m),
  }));
}

// Active entrance points belonging to the selected map. Deliberately never
// falls back to "the first point" or "the nearest point" when no entrance
// exists for the map — callers must show an explicit empty state instead
// (see hasNoEntranceForSelectedMap below).
export function filterEntrancePointsForMap(routePoints, selectedMapId) {
  if (!normalizeId(selectedMapId)) return [];

  return (Array.isArray(routePoints) ? routePoints : []).filter(
    (p) =>
      idsMatch(p?.map_id ?? p?.mapId, selectedMapId) &&
      p?.is_active !== false &&
      p?.point_type === 'entrance'
  );
}

export function buildRoutePointOptions(routePoints) {
  return (Array.isArray(routePoints) ? routePoints : [])
    .filter((p) => p && p.id != null)
    .map((p) => ({
      value: normalizeId(p.id),
      label: p.name || '',
    }));
}

// A map is genuinely selected but has no entrance point to offer — the
// screen must show a clear message for this, distinct from "no map chosen
// yet", and must never silently substitute a non-entrance point.
export function hasNoEntranceForSelectedMap(routePoints, selectedMapId) {
  return (
    Boolean(normalizeId(selectedMapId)) &&
    filterEntrancePointsForMap(routePoints, selectedMapId).length === 0
  );
}

// Editing an existing Location Code must let the admin reassign it to ANY
// real, currently-active RoutePoint on the exact selected map — not just
// ones tagged point_type "entrance" (unlike the Add flow above). This is
// what "verify and reassign the Main Entrance QR to the exact connected
// Main Entrance RoutePoint" needs: the real candidate point may not be
// tagged "entrance" in every legacy dataset, so the Edit picker must never
// hide it. Still requires the point to belong to this exact map_id and be
// active — the backend's own validate_location_code_references rejects an
// inactive point at save time regardless.
export function filterPointsForMap(routePoints, selectedMapId) {
  if (!normalizeId(selectedMapId)) return [];

  return (Array.isArray(routePoints) ? routePoints : []).filter(
    (p) =>
      idsMatch(p?.map_id ?? p?.mapId, selectedMapId) &&
      p?.is_active !== false
  );
}

export function hasNoPointsForMap(routePoints, selectedMapId) {
  return (
    Boolean(normalizeId(selectedMapId)) &&
    filterPointsForMap(routePoints, selectedMapId).length === 0
  );
}

// The auto-derived, read-only Building/Map Group/Floor display for the
// currently-selected Map in the Edit form ("When a Map is selected:
// derive its building, map group, and floor automatically"). A
// LocationCode has no floor/map_group_id fields of its own at all — both
// are always resolved live from the linked Map/RoutePoint (see
// backend/routes/location_code_routes.py's
// resolve_location_code_group_and_floor) — so this mirrors that exact
// same "Map.floor is authoritative" rule client-side for the live preview
// shown before Save, rather than inventing a second, possibly-diverging
// notion of a Location Code's floor.
export function resolveMapDerivedInfo(map) {
  if (!map) {
    return { buildingId: '', mapGroupId: null, mapGroupCode: null, floor: null, floorDisplay: '—' };
  }

  return {
    buildingId: normalizeId(map.buildingId ?? map.building_id),
    mapGroupId: map.mapGroupId ?? map.map_group_id ?? null,
    mapGroupCode: map.mapGroupCode ?? map.map_group_code ?? null,
    floor: map.floor ?? null,
    floorDisplay: formatFloorDisplay(map.floor, map.floorLabel ?? map.floor_label),
  };
}

// Builds the Edit form's initial state from a real LocationCode API
// response — never from display text, so re-opening Edit always starts
// from the entry's actual current ids.
export function buildEditFormFromEntry(entry) {
  return {
    id: normalizeId(entry?.id),
    buildingId: normalizeId(entry?.building_id),
    mapId: normalizeId(entry?.map_id),
    routePointId: normalizeId(entry?.route_point_id),
    code: entry?.code || '',
    label: entry?.label || '',
    isActive: entry?.is_active !== false,
  };
}

// Building/Map/RoutePoint must all still be real, selected ids before
// Save is allowed — label and active status are always optional/valid on
// their own. This never fires the PUT request itself (see
// buildEditSavePayload) — it only gates the Save button so an admin can
// never submit a half-finished reassignment.
export function isEditSaveEnabled(form) {
  return Boolean(
    normalizeId(form?.buildingId) &&
      normalizeId(form?.mapId) &&
      normalizeId(form?.routePointId)
  );
}

// Exact PUT /api/location-codes/{id} body — building_id/map_id/
// route_point_id/label/is_active only (never `code`; this Edit action
// intentionally never lets the admin rewrite the printed/scanned code
// itself, only what it points at). Nothing here touches the database —
// this is a pure object builder; the actual write only happens when the
// caller sends it via updateLocationCode() after Save is pressed.
export function buildEditSavePayload(form) {
  return {
    building_id: normalizeId(form.buildingId),
    map_id: normalizeId(form.mapId),
    route_point_id: normalizeId(form.routePointId),
    label: (form.label || '').trim() || null,
    is_active: Boolean(form.isActive),
  };
}

// Dependent-field reset rules (Step 5): changing the building must never
// leave an incompatible map/start-point selected, and changing the map
// must never leave an incompatible start point selected.
export function resetOnBuildingChange(form, newBuildingId) {
  return { ...form, buildingId: normalizeId(newBuildingId), mapId: '', routePointId: '' };
}

export function resetOnMapChange(form, newMapId) {
  return { ...form, mapId: normalizeId(newMapId), routePointId: '' };
}

// Save (manual code entry) requires every field, including a non-empty
// code — this button performs POST /api/location-codes, which rejects a
// missing code. Generate (auto code) only requires the three selections;
// label is optional there (the backend falls back to the point's name).
export function isManualSaveEnabled(form) {
  return Boolean(
    normalizeId(form?.buildingId) &&
      normalizeId(form?.mapId) &&
      normalizeId(form?.routePointId) &&
      (form?.label || '').trim() &&
      (form?.code || '').trim()
  );
}

export function isGenerateEnabled(form) {
  return Boolean(
    normalizeId(form?.buildingId) &&
      normalizeId(form?.mapId) &&
      normalizeId(form?.routePointId)
  );
}

// Exact request bodies the two save actions send — kept here so the
// "does the request stay internally consistent" contract (Step 6) is
// tested independently of any network/component code.
export function buildManualSavePayload(form) {
  return {
    code: (form.code || '').trim(),
    building_id: normalizeId(form.buildingId),
    map_id: normalizeId(form.mapId),
    route_point_id: normalizeId(form.routePointId),
    label: (form.label || '').trim() || undefined,
  };
}

export function buildGeneratePayload(form) {
  return {
    route_point_id: normalizeId(form.routePointId),
    label: (form.label || '').trim() || undefined,
  };
}
