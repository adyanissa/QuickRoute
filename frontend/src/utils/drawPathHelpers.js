// Pure helper functions for Draw Walkable Path's existing-point selection
// and Save Path ID resolution. Kept framework-free (no React, no fetch) so
// they can be exercised directly from a plain Node script — the frontend
// has no test runner installed, and this is the exact logic responsible
// for the previously-reported "reused point gets duplicated" bug, so it
// needs to be independently verifiable without a browser.
//
// Design note: clicking directly on a rendered existing RoutePoint marker
// must be a DETERMINISTIC selection — the marker IS the RoutePoint, so its
// click handler already has the real object in hand. It must never fall
// back to coordinate-proximity math to "rediscover" which point was
// clicked; that class of check (screen px -> native px -> distance
// threshold) is a heuristic for clicks that land NEAR a point, not a
// substitute for identity when the exact object is already known.

import { normalizeId, normalizeFloorNumber } from './mapGroupHelpers.js';

// Normalizes a RoutePoint's database id to a string, regardless of whether
// the backend/response shape used `id` or `_id` for a given call site.
// Returns '' (never null) when no usable id is present, matching every
// existing caller's `if (!routePointId)` falsy check.
export function normalizePointId(point) {
  return normalizeId(point?.id, point?._id) || '';
}

// Decides whether a direct click on an existing saved RoutePoint marker
// (while Draw Walkable Path is active) may be turned into an
// `kind: "existing"` draft item. Every check here is a hard reject — a
// point that fails ANY of them must never be silently reused, per the
// project's graph rule that connections only ever happen through explicit
// admin action, never through incidental proximity.
//
// Returns { ok: true, draftItem } or { ok: false, reason }.
export function resolveExistingPointSelection({
  point,
  activeMapId,
  drawFloor,
  lastDraftPoint,
}) {
  if (!point) {
    return { ok: false, reason: 'missing-point' };
  }

  const routePointId = normalizePointId(point);

  if (!routePointId) {
    return { ok: false, reason: 'missing-id' };
  }

  // A point loaded for a different map must never be reusable here, even
  // if its raw x/y happen to coincide on screen — maps are independent
  // graphs. Accepts both the real backend field (map_id) and a camelCase
  // variant defensively, and normalizes both sides through the same
  // normalizeId() used by mapsApi.js/mapGroupHelpers.js so an ObjectId
  // arriving on one side and an already-stringified id on the other can
  // never falsely mismatch (Section 1/5: "normalize both IDs before
  // comparison").
  const pointMapId = normalizeId(point.map_id, point.mapId);
  const normalizedActiveMapId = normalizeId(activeMapId);

  if (normalizedActiveMapId && pointMapId && pointMapId !== normalizedActiveMapId) {
    return { ok: false, reason: 'wrong-map' };
  }

  // Floor is stored as a number everywhere on the backend, but UI state
  // (a <input type="number">) and stored point data have both been known
  // to carry it as a numeric-looking string in intermediate frontend
  // state. Normalize both sides the same way before comparing so "1" and
  // 1 are never treated as different floors. A null/unknown drawFloor
  // (the active Map's own floor could not be determined — see
  // AdminMapScreen.jsx's activeFloor) intentionally SKIPS this check
  // rather than defaulting to Ground Floor — the map-id check above is
  // already the authoritative match (RoutePoints are always fetched
  // scoped to one exact map_id), so an unknown floor must never produce a
  // false "wrong floor" rejection for a point that is genuinely on the
  // currently active map.
  const normalizedDrawFloor = normalizeFloorNumber(drawFloor);
  const normalizedPointFloor = normalizeFloorNumber(point.floor, point.floor_number, point.floorNumber);

  if (
    normalizedDrawFloor !== null &&
    normalizedPointFloor !== null &&
    normalizedPointFloor !== normalizedDrawFloor
  ) {
    return { ok: false, reason: 'wrong-floor' };
  }

  if (point.is_active === false || point.isActive === false) {
    return { ok: false, reason: 'inactive' };
  }

  // Selecting the same existing point twice in a row would create a
  // zero-length segment — same guard the proximity-fallback path already
  // applies for newly-placed points.
  if (
    lastDraftPoint?.kind === 'existing' &&
    lastDraftPoint.routePointId === routePointId
  ) {
    return { ok: false, reason: 'duplicate-consecutive' };
  }

  return {
    ok: true,
    draftItem: {
      tempId: `existing-${routePointId}-${Date.now()}`,
      kind: 'existing',
      routePointId,
      x: Number(point.x),
      y: Number(point.y),
      floor: Number(point.floor),
      name: point.name,
      point_type: point.point_type,
    },
  };
}

// Splits an ordered draftPoints array into what Save Path must actually do:
// which indices already resolve to a real database id (kind: "existing",
// reused verbatim, never recreated) and which indices still need a fresh
// RoutePoint created. Pure and order-preserving so the caller can run the
// actual async createRoutePoint() calls and drop results back into
// `resolvedIds[index]` before building edges.
export function partitionDraftForSave(draftPoints) {
  const reuses = [];
  const creates = [];

  draftPoints.forEach((draftPoint, index) => {
    if (draftPoint.kind === 'existing') {
      reuses.push({
        index,
        routePointId: draftPoint.routePointId,
      });
    } else {
      creates.push({
        index,
        x: draftPoint.x,
        y: draftPoint.y,
        floor: draftPoint.floor,
        name: draftPoint.name,
      });
    }
  });

  return { reuses, creates };
}

// ── RoutePoint naming (admin-entered names for new draft points) ──────────
// Mirrors the backend's RoutePointCreate/RoutePointUpdate `name` field
// constraints (backend/schemas/route_point_schema.py) so an invalid name is
// caught here — with a message next to the specific point — instead of
// only surfacing as a generic failed-save error after Save Path is already
// in flight.
export const ROUTE_POINT_NAME_MIN_LENGTH = 2;
export const ROUTE_POINT_NAME_MAX_LENGTH = 120;

// Short, sequential, human-meaningful placeholder for a brand new draft
// point — deliberately NOT a timestamp (the exact "Corridor Point
// 1784655469774-0" complaint this feature replaces). Numbered by how many
// "new" (not existing/reused) points are already in the draft, so a draft
// of existing-existing-new-new gets "Point 1", "Point 2" for its two new
// points, not "Point 3"/"Point 4".
export function generateDefaultDraftPointName(draftPoints) {
  const newPointCountSoFar = Array.isArray(draftPoints)
    ? draftPoints.filter((point) => point.kind === 'new').length
    : 0;

  return `Point ${newPointCountSoFar + 1}`;
}

// Validates a single point name. Trims whitespace first — a name that is
// only whitespace is treated as empty, matching what the backend would
// effectively receive as meaningless. Returns { ok: true, trimmed } or
// { ok: false, reason }.
export function validateDraftPointName(name) {
  const trimmed = typeof name === 'string' ? name.trim() : '';

  if (trimmed.length === 0) {
    return { ok: false, reason: 'empty' };
  }

  if (trimmed.length < ROUTE_POINT_NAME_MIN_LENGTH) {
    return { ok: false, reason: 'too-short' };
  }

  if (trimmed.length > ROUTE_POINT_NAME_MAX_LENGTH) {
    return { ok: false, reason: 'too-long' };
  }

  return { ok: true, trimmed };
}

// Returns a NEW draftPoints array with only `draftPoints[index].name`
// changed to `value` — every other item (and every other field of the
// target item) is copied by reference, unchanged. Pure/immutable so it is
// safe to use directly as React state, and so "does editing one point's
// name ever affect another point" is provable independent of React itself
// (this is exactly what keeps typed names intact across Undo, panel drag,
// and panel collapse/restore — none of those ever call this function for
// any index other than the one actually being edited).
export function updateDraftPointName(draftPoints, index, value) {
  if (!Array.isArray(draftPoints)) return draftPoints;

  return draftPoints.map((point, i) =>
    i === index ? { ...point, name: value } : point,
  );
}

// Save Path must be disabled whenever any "new" draft point's name is
// invalid — existing/reused points are never renamed by this flow (their
// current saved name is display-only), so only "new" items are checked.
// Returns true (valid/safe to save) when there are no "new" points at all,
// so this never blocks an all-existing-points draft.
export function isDraftNamingValid(draftPoints) {
  if (!Array.isArray(draftPoints)) return true;

  return draftPoints
    .filter((point) => point.kind === 'new')
    .every((point) => validateDraftPointName(point.name).ok);
}

// Builds the set of already-connected point-id pairs (both directions) so
// re-saving a path that overlaps an already-connected segment doesn't
// attempt a duplicate edge. Pure — takes the currently-loaded routeEdges
// array, returns a plain Set of "fromId::toId" keys.
export function buildEdgeKeySet(routeEdges) {
  const keys = new Set();

  routeEdges.forEach((edge) => {
    keys.add(`${edge.from_point_id}::${edge.to_point_id}`);
    keys.add(`${edge.to_point_id}::${edge.from_point_id}`);
  });

  return keys;
}

// Given the final resolvedIds sequence (existing ids reused verbatim, new
// ids filled in after creation) and the current edge-key set, returns the
// consecutive pairs that still need a RouteEdge created plus how many were
// skipped as already-connected. Never emits a self-edge (fromId === toId)
// or a pair missing either id.
export function buildEdgePlan(resolvedIds, existingEdgeKeys) {
  const toCreate = [];
  let skippedCount = 0;

  for (let i = 0; i < resolvedIds.length - 1; i += 1) {
    const fromId = resolvedIds[i];
    const toId = resolvedIds[i + 1];

    if (!fromId || !toId || fromId === toId) {
      continue;
    }

    const key = `${fromId}::${toId}`;

    if (existingEdgeKeys.has(key)) {
      skippedCount += 1;
      continue;
    }

    toCreate.push({ fromId, toId });
    existingEdgeKeys.add(key);
    existingEdgeKeys.add(`${toId}::${fromId}`);
  }

  return { toCreate, skippedCount };
}

// Preview-only radius for the dashed "possible automatic merge" line drawn
// while "Merge with safe nearby graph points" is selected. Deliberately
// smaller than the backend's DEFAULT_MAX_DISTANCE_PX (600) — the backend
// is the real authority (it also checks walls and existing connections),
// this is just a visual hint so the admin isn't surprised by a merge that
// happens well outside anything they could see coming.
export const DEFAULT_NEARBY_MERGE_PREVIEW_PX = 150;

// For every "new" (not-yet-created) draft point, finds the single nearest
// active existing RoutePoint on the same map/floor within maxDistancePx,
// excluding any point already resolved into this same draft (so the
// preview never draws a line back to a point the draft itself just placed
// or reused). Pure — used both for rendering the dashed preview line and
// is independently testable without a DOM. Returns an array parallel to
// (a subset of) draftPoints: [{ draftIndex, fromX, fromY, toPointId, toX,
// toY, distance }, ...].
export function computeNearbyMergePreview({
  draftPoints,
  routePoints,
  activeMapId,
  drawFloor,
  maxDistancePx = DEFAULT_NEARBY_MERGE_PREVIEW_PX,
}) {
  if (!Array.isArray(draftPoints) || !Array.isArray(routePoints)) {
    return [];
  }

  const draftExistingIds = new Set(
    draftPoints
      .filter((point) => point.kind === 'existing')
      .map((point) => point.routePointId),
  );

  const candidates = routePoints.filter((point) => {
    if (point.is_active === false) return false;

    if (
      activeMapId !== undefined &&
      activeMapId !== null &&
      point.map_id !== undefined &&
      point.map_id !== null &&
      String(point.map_id) !== String(activeMapId)
    ) {
      return false;
    }

    if (
      drawFloor !== undefined &&
      drawFloor !== null &&
      point.floor !== undefined &&
      point.floor !== null &&
      Number(point.floor) !== Number(drawFloor)
    ) {
      return false;
    }

    return !draftExistingIds.has(normalizePointId(point));
  });

  const preview = [];

  draftPoints.forEach((draftPoint, draftIndex) => {
    if (draftPoint.kind !== 'new') return;

    let nearest = null;
    let nearestDistance = Infinity;

    candidates.forEach((candidate) => {
      const distance = Math.sqrt(
        (Number(candidate.x) - Number(draftPoint.x)) ** 2 +
          (Number(candidate.y) - Number(draftPoint.y)) ** 2,
      );

      if (distance <= maxDistancePx && distance < nearestDistance) {
        nearest = candidate;
        nearestDistance = distance;
      }
    });

    if (nearest) {
      preview.push({
        draftIndex,
        fromX: draftPoint.x,
        fromY: draftPoint.y,
        toPointId: normalizePointId(nearest),
        toX: Number(nearest.x),
        toY: Number(nearest.y),
        distance: nearestDistance,
      });
    }
  });

  return preview;
}
