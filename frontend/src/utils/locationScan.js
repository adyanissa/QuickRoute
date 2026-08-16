// Scanning a room QR while a destination is already active.
//
// A QuickRoute location code identifies WHERE THE USER IS. It is never a
// graph edge: codes are never chained to other codes, and Dijkstra keeps
// running purely over RoutePoints/RouteEdges on the backend. All this
// module does is decide what a freshly scanned code MEANS relative to the
// journey already in progress:
//
//   scanned room === active destination room  ->  ARRIVED
//   scanned room is some other room           ->  RELOCATE + recalculate
//   scanned room is where we already are      ->  nothing to do
//
// Kept as pure functions with no React and no network so they can be unit
// tested by plain `node src/utils/locationScan.test.mjs`, exactly like the
// other helpers in this folder.

// The single localStorage key the whole app uses for "where the user is".
// Written by BarcodeEntryScreen on the first scan and re-written here on a
// mid-navigation rescan, so a page reload keeps the updated position.
export const START_LOCATION_KEY = 'quickroute_start_location';

/**
 * The record shape BarcodeEntryScreen already persists. Re-exported as a
 * builder so a rescan writes byte-identical data instead of a second,
 * slightly different shape that later readers would have to special-case.
 *
 * @param {object} resolved GET /api/location-codes/resolve/{code} response
 */
export function buildStartLocationRecord(resolved) {
  if (!resolved?.route_point_id) return null;

  return {
    routePointId: resolved.route_point_id,
    mapId: resolved.map_id ?? null,
    mapGroupId: resolved.map_group_id ?? null,
    floor: resolved.floor ?? null,
    buildingId: resolved.building_id ?? null,
    code: resolved.code ?? null,
    label: resolved.label ?? null,
  };
}

/**
 * Decide what a scanned code means for the journey in progress.
 *
 * Comparison is by STABLE ID, never by name. The preferred key is the room
 * id: a scanned code resolves to a RoutePoint, and the public route-point
 * endpoint already exposes that point's `room_id` (it is the same link
 * Room.route_point_id defines from the other side), so no `room_id` field
 * has to be added to LocationCode itself.
 *
 * Route-point equality is only a FALLBACK, for legacy points that predate
 * the room link and therefore have a null room_id.
 *
 * @param {object}  args
 * @param {object}  args.scannedPoint            public RoutePoint of the scanned code
 * @param {?string} args.destinationRoomId       active destination's Room id
 * @param {?string} args.destinationRoutePointId active destination's arrival point id
 * @param {?string} args.currentStartPointId     where we currently think the user is
 * @returns {{outcome: 'arrived'|'relocate'|'unchanged'|'invalid',
 *            startPointId: ?string, reason: ?string}}
 */
export function classifyScannedLocation({
  scannedPoint,
  destinationRoomId = null,
  destinationRoutePointId = null,
  currentStartPointId = null,
} = {}) {
  const scannedPointId = scannedPoint?.id ?? null;

  if (!scannedPointId) {
    return { outcome: 'invalid', startPointId: null, reason: 'no_route_point' };
  }

  if (scannedPoint?.is_active === false) {
    return { outcome: 'invalid', startPointId: null, reason: 'inactive_point' };
  }

  const scannedRoomId = scannedPoint?.room_id ?? null;

  // Preferred: both sides know their room.
  if (destinationRoomId && scannedRoomId) {
    if (String(scannedRoomId) === String(destinationRoomId)) {
      return { outcome: 'arrived', startPointId: scannedPointId, reason: 'room_id_match' };
    }
    // Explicitly a DIFFERENT room — do not fall through to the route-point
    // check below, which could only agree anyway.
    return {
      outcome:
        currentStartPointId && String(scannedPointId) === String(currentStartPointId)
          ? 'unchanged'
          : 'relocate',
      startPointId: scannedPointId,
      reason: 'room_id_mismatch',
    };
  }

  // Fallback: legacy point with no room link on one side or the other.
  if (
    destinationRoutePointId &&
    String(scannedPointId) === String(destinationRoutePointId)
  ) {
    return {
      outcome: 'arrived',
      startPointId: scannedPointId,
      reason: 'route_point_match',
    };
  }

  if (currentStartPointId && String(scannedPointId) === String(currentStartPointId)) {
    return { outcome: 'unchanged', startPointId: scannedPointId, reason: 'same_point' };
  }

  return { outcome: 'relocate', startPointId: scannedPointId, reason: 'different_point' };
}

/**
 * A scanned code from a different building cannot be a start point for the
 * journey in progress — the backend refuses to route across buildings
 * (routes/navigation_routes.py), so this is caught before a pointless
 * request is made. A missing building_id on either side is NOT treated as
 * a mismatch: legacy maps/points predate Building and must keep working.
 */
export function isScanInActiveBuilding(resolved, activeBuildingId) {
  if (!activeBuildingId) return true;
  if (!resolved?.building_id) return true;
  return String(resolved.building_id) === String(activeBuildingId);
}
