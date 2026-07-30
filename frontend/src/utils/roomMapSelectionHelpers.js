// Pure helpers for the Add/Edit Room Map selector's Building -> Map Group
// -> Floor Map hierarchy (Part 3). Kept dependency-free (no React) so the
// grouping/auto-select/label logic is directly unit-testable, same
// pattern as utils/mapGroupHelpers.js.
import { groupMapsByMapGroup, formatFloorDisplay, sortFloorsByNumber } from './mapGroupHelpers.js';

// Synthetic key representing "every standalone map with no Map Group" —
// lets a building that mixes grouped floors and legacy standalone maps
// still go through one consistent two-step picker instead of a special
// case the admin has to understand.
export const UNGROUPED_MAP_GROUP_KEY = '__ungrouped__';

// The selectable "Map Group" step — one entry per real Map Group already
// used by this building's maps, plus (if any exist) one entry for
// ungrouped standalone maps.
export function buildRoomMapGroupOptions(buildingMaps) {
  const { groups, ungrouped } = groupMapsByMapGroup(
    Array.isArray(buildingMaps) ? buildingMaps : [],
  );

  const options = groups.map((group) => ({
    key: group.groupId,
    code: group.groupCode || null,
    floorCount: group.floors.length,
  }));

  if (ungrouped.length > 0) {
    options.push({
      key: UNGROUPED_MAP_GROUP_KEY,
      code: null,
      floorCount: ungrouped.length,
    });
  }

  return options;
}

// The selectable "Floor Map" step for a chosen Map Group key (already
// sorted numerically by floor via groupMapsByMapGroup/sortFloorsByNumber).
export function floorMapsForGroup(buildingMaps, groupKey) {
  if (!groupKey) return [];

  const { groups, ungrouped } = groupMapsByMapGroup(
    Array.isArray(buildingMaps) ? buildingMaps : [],
  );

  if (groupKey === UNGROUPED_MAP_GROUP_KEY) return sortFloorsByNumber(ungrouped);

  const match = groups.find((group) => group.groupId === groupKey);
  return match ? match.floors : [];
}

// "If there is only one Map Group, it may be auto-selected."
export function resolveAutoSelectedMapGroupKey(buildingMaps) {
  const options = buildRoomMapGroupOptions(buildingMaps);
  return options.length === 1 ? options[0].key : null;
}

// "If there is only one Floor Map, it may be auto-selected."
export function resolveAutoSelectedFloorMapId(buildingMaps, groupKey) {
  const floors = floorMapsForGroup(buildingMaps, groupKey);
  return floors.length === 1 ? floors[0].id : null;
}

// Example from the spec: "AF-123 · Floor 1 · QuickRoute Mall – Floor 1".
// Only ever joins pieces that actually exist — never renders a blank
// separator like "— — QuickRoute Mall" when a group code or title is
// missing (each missing piece is simply omitted, not left as an empty
// slot between separators).
export function buildFloorMapOptionLabel(map) {
  const parts = [];

  if (map?.mapGroupCode) parts.push(map.mapGroupCode);
  parts.push(formatFloorDisplay(map?.floor, map?.floorLabel));

  const title = map?.title && String(map.title).trim();
  if (title) parts.push(title);

  return parts.join(' · ');
}
