// Which floors the destination list may be filtered by, derived from real
// data only.
//
// WHERE THE OPTIONS COME FROM
// ---------------------------
// The already-loaded destination list itself. GET /api/rooms returns
// `map_id`, `map_group_id` and `floor` for every room (see
// backend/schemas/room_schema.py and utils/viewModels.js's
// roomToViewModel), so the set of real floors that actually contain
// destinations is fully determined by data the screen has already
// fetched. No extra request for Maps or MapGroups is made, and none is
// needed — see the "do not overfetch" rule.
//
// Deriving from the rooms also means a floor can never appear as an
// option unless a real destination exists on it, which is the only thing
// a destination filter can usefully offer.
//
// WHAT LIMITS THE SCOPE
// ---------------------
// The resolved starting location, not a frontend assumption:
//
//   start has a map_group_id  ->  only rooms whose map_group_id matches;
//                                 that group IS the set of related floors
//   start has only a map_id   ->  only rooms on that same map (an
//                                 ungrouped single-floor map has exactly
//                                 one related floor: itself)
//   no resolved start at all  ->  no extra narrowing; the request was
//                                 already scoped to one building
//
// map_group_id is resolved by the backend from Map.map_group_id at
// response time, so this reuses the existing relationship rather than
// re-deriving one. Maps belonging to another building or another group
// therefore cannot contribute an option.
//
// Nothing here is specific to any building, floor count, floor numbering
// scheme or label style: a building with one floor yields one option, a
// building with seven yields seven, and the labels come from the
// project's existing formatFloorDisplay helper rather than an assumed
// G/1/2/3 sequence.

import { formatFloorDisplay, sortFloorsByNumber } from './mapGroupHelpers.js';

// The "no floor selected" value. Deliberately null rather than a string
// like 'all', so it can never collide with a real map id.
export const ALL_FLOORS = null;

const asKey = (value) =>
  value === null || value === undefined ? '' : String(value);

/**
 * Is this room on a map that is genuinely related to where the user is
 * standing?
 *
 * A missing start context is not treated as "exclude everything" — the
 * room list is already scoped to one building by the API call that
 * produced it, and narrowing further on data we do not have would hide
 * real destinations.
 */
export function isInRelatedScope(room, startContext = null) {
  const groupId = startContext?.mapGroupId ?? null;
  const mapId = startContext?.mapId ?? null;

  if (groupId) return asKey(room?.mapGroupId) === asKey(groupId);
  if (mapId) return asKey(room?.mapId) === asKey(mapId);

  return true;
}

/**
 * The real, selectable floors — one entry per distinct map that actually
 * holds a destination in the related scope.
 *
 * @param {Array}   rooms         room view models (utils/viewModels.js)
 * @param {?object} startContext  the persisted resolved start location
 * @returns {Array<{mapId: string, floor: ?number, label: string,
 *                  count: number, isCurrent: boolean}>}
 */
export function resolveFloorOptions(rooms, startContext = null) {
  const list = Array.isArray(rooms) ? rooms : [];
  const currentMapId = asKey(startContext?.mapId ?? null);

  const byMapId = new Map();

  for (const room of list) {
    const mapId = asKey(room?.mapId ?? null);

    // A destination that was entered manually has no map placement at
    // all. It belongs to no floor, so it contributes no option — but it
    // is still listed under "All" (see filterRoomsByFloor), exactly as
    // it is today.
    if (!mapId) continue;

    if (!isInRelatedScope(room, startContext)) continue;

    const existing = byMapId.get(mapId);

    if (existing) {
      existing.count += 1;
      continue;
    }

    byMapId.set(mapId, {
      mapId,
      floor: room?.floor ?? null,
      // formatFloorDisplay prefers an explicit human label over the
      // numeric floor, so a map titled "Mezzanine" or "B1" keeps its own
      // wording instead of being normalized into "Floor N". Rooms do not
      // carry that label today; passing it through means they will be
      // honoured automatically if they ever do, and nothing is invented
      // in the meantime.
      label: formatFloorDisplay(room?.floor ?? null, room?.floorLabel ?? null),
      count: 1,
      isCurrent: Boolean(currentMapId) && mapId === currentMapId,
    });
  }

  return sortFloorsByNumber([...byMapId.values()]);
}

/**
 * A filter with one option filters nothing — it only takes up space and
 * implies the building has floors it does not have.
 */
export function shouldShowFloorFilter(options) {
  return Array.isArray(options) && options.length > 1;
}

/**
 * Pure UI filtering. Returns the same room objects, never copies or
 * mutates them, and never touches anything but the visible list.
 */
export function filterRoomsByFloor(rooms, selectedMapId = ALL_FLOORS) {
  const list = Array.isArray(rooms) ? rooms : [];

  if (!selectedMapId) return list;

  return list.filter((room) => asKey(room?.mapId) === asKey(selectedMapId));
}

/**
 * Keeps a selection honest across a data change: if the selected floor
 * is no longer one of the real options (the rooms reloaded, the user
 * arrived from a different start), fall back to All rather than showing
 * an empty list under a chip that is no longer there.
 */
export function reconcileFloorSelection(selectedMapId, options) {
  if (!selectedMapId) return ALL_FLOORS;

  const exists = (Array.isArray(options) ? options : []).some(
    (option) => asKey(option?.mapId) === asKey(selectedMapId),
  );

  return exists ? selectedMapId : ALL_FLOORS;
}
