// Plain-Node tests for the Location Codes dependent Building -> Map ->
// Start Point form helpers (frontend/src/utils/locationCodeFormHelpers.js).
// These pin down the exact root cause of the "Map dropdown stays empty"
// bug (AdminContext's map normalization silently dropped building_id) and
// the fix's id-normalization/filtering/reset rules. Same pattern as the
// repo's other *.test.mjs files — no jest/vitest installed, run directly
// via `node locationCodeFormHelpers.test.mjs`.
import assert from 'node:assert/strict';
import {
  normalizeId,
  idsMatch,
  buildBuildingOptions,
  buildMapOptions,
  buildRoutePointOptions,
  filterMapsForBuilding,
  filterEntrancePointsForMap,
  hasNoEntranceForSelectedMap,
  filterPointsForMap,
  hasNoPointsForMap,
  resolveMapDerivedInfo,
  buildEditFormFromEntry,
  isEditSaveEnabled,
  buildEditSavePayload,
  resetOnBuildingChange,
  resetOnMapChange,
  isManualSaveEnabled,
  isGenerateEnabled,
  buildManualSavePayload,
  buildGeneratePayload,
} from './locationCodeFormHelpers.js';

let passed = 0;
function test(name, fn) {
  try {
    fn();
    passed += 1;
    console.log(`PASS: ${name}`);
  } catch (err) {
    console.error(`FAIL: ${name}`);
    console.error(err);
    process.exitCode = 1;
  }
}

// Real-shaped fixtures, matching what AdminContext's buildingToViewModel /
// (fixed) normalizeMap / raw RoutePointResponse actually produce.
const QUICKROUTE_MALL_BUILDING = { id: 'bld-1', nameEn: 'QuickRoute Mall' };
const OTHER_BUILDING = { id: 'bld-2', nameEn: 'Other Campus' };

const MALL_MAP_FLOOR_1 = { id: 'map-1', title: 'QuickRoute Mall - Floor 1', buildingId: 'bld-1', floor: 1 };
const OTHER_MAP = { id: 'map-2', title: 'Other Campus Map', buildingId: 'bld-2', floor: 1 };

const MAIN_ENTRANCE = { id: 'pt-1', name: 'Main Entrance', map_id: 'map-1', point_type: 'entrance', is_active: true };
const HALLWAY_POINT = { id: 'pt-2', name: 'Hallway Junction', map_id: 'map-1', point_type: 'hallway', is_active: true };
const INACTIVE_ENTRANCE = { id: 'pt-3', name: 'Old Entrance', map_id: 'map-1', point_type: 'entrance', is_active: false };
const OTHER_MAP_ENTRANCE = { id: 'pt-4', name: 'Other Entrance', map_id: 'map-2', point_type: 'entrance', is_active: true };

// ── normalizeId / idsMatch ─────────────────────────────────────────────────

test('normalizeId: stringifies a plain id', () => {
  assert.equal(normalizeId('abc123'), 'abc123');
});

test('normalizeId: stringifies an ObjectId-like object (has a real toString)', () => {
  const objectIdLike = { toString: () => 'abc123' };
  assert.equal(normalizeId(objectIdLike), 'abc123');
});

test('normalizeId: null/undefined/empty all normalize to empty string', () => {
  assert.equal(normalizeId(null), '');
  assert.equal(normalizeId(undefined), '');
  assert.equal(normalizeId(''), '');
});

test('idsMatch: a string id and an ObjectId-like id that stringify the same are equal', () => {
  const objectIdLike = { toString: () => 'bld-1' };
  assert.equal(idsMatch(objectIdLike, 'bld-1'), true);
});

test('idsMatch: two empty/missing ids are never considered a match', () => {
  assert.equal(idsMatch(null, null), false);
  assert.equal(idsMatch(undefined, ''), false);
});

// ── Building options — the actual root-cause regression guard ─────────────

test('buildBuildingOptions: uses the Building name, never a map title', () => {
  const options = buildBuildingOptions([QUICKROUTE_MALL_BUILDING]);
  assert.equal(options.length, 1);
  assert.equal(options[0].label, 'QuickRoute Mall');
  assert.notEqual(options[0].label, 'QuickRoute Mall - Floor 1');
});

test('buildBuildingOptions: option value is the Building id', () => {
  const options = buildBuildingOptions([QUICKROUTE_MALL_BUILDING]);
  assert.equal(options[0].value, 'bld-1');
});

// ── Map filtering — the confirmed root cause ───────────────────────────────

test('filterMapsForBuilding: returns [] when no building is selected (never "all maps")', () => {
  const result = filterMapsForBuilding([MALL_MAP_FLOOR_1, OTHER_MAP], '');
  assert.deepEqual(result, []);
});

test('filterMapsForBuilding: QuickRoute Mall - Floor 1 appears for QuickRoute Mall', () => {
  const result = filterMapsForBuilding([MALL_MAP_FLOOR_1, OTHER_MAP], 'bld-1');
  assert.equal(result.length, 1);
  assert.equal(result[0].title, 'QuickRoute Mall - Floor 1');
});

test('filterMapsForBuilding: a map for a different building is excluded', () => {
  const result = filterMapsForBuilding([MALL_MAP_FLOOR_1, OTHER_MAP], 'bld-1');
  assert.ok(!result.some((m) => m.id === 'map-2'));
});

test('filterMapsForBuilding: works even when the map\'s building_id arrives as an ObjectId-like object', () => {
  const objectIdMap = { id: 'map-1', title: 'QuickRoute Mall - Floor 1', building_id: { toString: () => 'bld-1' } };
  const result = filterMapsForBuilding([objectIdMap], 'bld-1');
  assert.equal(result.length, 1);
});

test('buildMapOptions: shows the floor + map title as the label and the map id as the value', () => {
  const options = buildMapOptions([MALL_MAP_FLOOR_1]);
  assert.deepEqual(options, [{ value: 'map-1', label: 'Floor 1 — QuickRoute Mall - Floor 1' }]);
});

test('buildMapOptions: sorts floors ascending regardless of input order (Final Submission Part 2)', () => {
  const floor2 = { id: 'map-3', title: 'Floor Two', buildingId: 'bld-1', floor: 2 };
  const floor0 = { id: 'map-4', title: 'Ground', buildingId: 'bld-1', floor: 0 };
  const options = buildMapOptions([MALL_MAP_FLOOR_1, floor2, floor0]);
  assert.deepEqual(options.map((o) => o.value), ['map-4', 'map-1', 'map-3']);
});

test('buildMapOptions: includes the Map Group code prefix when present', () => {
  const withGroup = { id: 'map-5', title: 'Concourse', buildingId: 'bld-1', floor: 1, mapGroupCode: 'MALL-A' };
  const options = buildMapOptions([withGroup]);
  assert.equal(options[0].label, '[MALL-A] Floor 1 — Concourse');
});

// ── RoutePoint filtering ────────────────────────────────────────────────────

test('filterEntrancePointsForMap: Main Entrance appears for its map', () => {
  const result = filterEntrancePointsForMap(
    [MAIN_ENTRANCE, HALLWAY_POINT, INACTIVE_ENTRANCE, OTHER_MAP_ENTRANCE],
    'map-1'
  );
  assert.equal(result.length, 1);
  assert.equal(result[0].name, 'Main Entrance');
});

test('filterEntrancePointsForMap: a non-entrance point on the same map is excluded', () => {
  const result = filterEntrancePointsForMap([MAIN_ENTRANCE, HALLWAY_POINT], 'map-1');
  assert.ok(!result.some((p) => p.point_type !== 'entrance'));
});

test('filterEntrancePointsForMap: an inactive entrance is excluded', () => {
  const result = filterEntrancePointsForMap([INACTIVE_ENTRANCE], 'map-1');
  assert.deepEqual(result, []);
});

test('filterEntrancePointsForMap: an entrance belonging to a different map is excluded', () => {
  const result = filterEntrancePointsForMap([OTHER_MAP_ENTRANCE], 'map-1');
  assert.deepEqual(result, []);
});

test('filterEntrancePointsForMap: returns [] when no map is selected', () => {
  assert.deepEqual(filterEntrancePointsForMap([MAIN_ENTRANCE], ''), []);
});

test('hasNoEntranceForSelectedMap: true for a map with only non-entrance points (no first-point fallback)', () => {
  assert.equal(hasNoEntranceForSelectedMap([HALLWAY_POINT], 'map-1'), true);
});

test('hasNoEntranceForSelectedMap: false once a real entrance exists', () => {
  assert.equal(hasNoEntranceForSelectedMap([MAIN_ENTRANCE, HALLWAY_POINT], 'map-1'), false);
});

test('hasNoEntranceForSelectedMap: false when no map is selected yet (distinct empty state)', () => {
  assert.equal(hasNoEntranceForSelectedMap([], ''), false);
});

// ── Dependent-field reset rules (Step 5) ────────────────────────────────────

test('resetOnBuildingChange: clears mapId and routePointId, sets the new buildingId', () => {
  const previous = { buildingId: 'bld-1', mapId: 'map-1', routePointId: 'pt-1', label: 'kept', code: 'kept' };
  const next = resetOnBuildingChange(previous, 'bld-2');
  assert.equal(next.buildingId, 'bld-2');
  assert.equal(next.mapId, '');
  assert.equal(next.routePointId, '');
  // Unrelated fields survive the reset.
  assert.equal(next.label, 'kept');
  assert.equal(next.code, 'kept');
});

test('resetOnMapChange: clears routePointId only, leaves buildingId alone', () => {
  const previous = { buildingId: 'bld-1', mapId: 'map-1', routePointId: 'pt-1' };
  const next = resetOnMapChange(previous, 'map-2');
  assert.equal(next.buildingId, 'bld-1');
  assert.equal(next.mapId, 'map-2');
  assert.equal(next.routePointId, '');
});

// ── Save/Generate enablement + request payload consistency (Step 6) ───────

test('isManualSaveEnabled: false until building, map, point, label AND code are all set', () => {
  const complete = { buildingId: 'bld-1', mapId: 'map-1', routePointId: 'pt-1', label: 'Main Entrance QR', code: 'ABC123' };
  assert.equal(isManualSaveEnabled(complete), true);

  for (const missingField of ['buildingId', 'mapId', 'routePointId', 'label', 'code']) {
    const incomplete = { ...complete, [missingField]: '' };
    assert.equal(isManualSaveEnabled(incomplete), false, `should be disabled without ${missingField}`);
  }
});

test('isGenerateEnabled: requires building/map/point but not label or code', () => {
  assert.equal(
    isGenerateEnabled({ buildingId: 'bld-1', mapId: 'map-1', routePointId: 'pt-1', label: '', code: '' }),
    true
  );
  assert.equal(
    isGenerateEnabled({ buildingId: 'bld-1', mapId: 'map-1', routePointId: '', label: '', code: '' }),
    false
  );
});

test('buildManualSavePayload: request stays consistent with the three selected ids', () => {
  const form = { buildingId: 'bld-1', mapId: 'map-1', routePointId: 'pt-1', label: '  Main Entrance QR  ', code: ' ABC123 ' };
  const payload = buildManualSavePayload(form);
  assert.deepEqual(payload, {
    code: 'ABC123',
    building_id: 'bld-1',
    map_id: 'map-1',
    route_point_id: 'pt-1',
    label: 'Main Entrance QR',
  });
});

test('buildGeneratePayload: only sends route_point_id and label', () => {
  const form = { buildingId: 'bld-1', mapId: 'map-1', routePointId: 'pt-1', label: 'Kiosk', code: '' };
  assert.deepEqual(buildGeneratePayload(form), { route_point_id: 'pt-1', label: 'Kiosk' });
});

test('buildRoutePointOptions: label is the point name, value is the point id', () => {
  const options = buildRoutePointOptions([MAIN_ENTRANCE]);
  assert.deepEqual(options, [{ value: 'pt-1', label: 'Main Entrance' }]);
});

// ── Edit action — Admin Location Codes "Edit" (Part: display/edit label,
// building_id, map_group_id, map_id, floor, route_point_id, active) ───────

const MALL_MAP_FLOOR_1_GROUPED = {
  id: 'map-1', title: 'QuickRoute Mall - Floor 1', buildingId: 'bld-1',
  floor: 1, mapGroupId: 'grp-1', mapGroupCode: 'AF-1',
};

test('filterPointsForMap: includes every active point on the map, not just entrances', () => {
  const points = filterPointsForMap([MAIN_ENTRANCE, HALLWAY_POINT, INACTIVE_ENTRANCE, OTHER_MAP_ENTRANCE], 'map-1');
  const ids = points.map((p) => p.id).sort();
  assert.deepEqual(ids, ['pt-1', 'pt-2']);
});

test('filterPointsForMap: excludes inactive points and points on a different map', () => {
  const points = filterPointsForMap([INACTIVE_ENTRANCE, OTHER_MAP_ENTRANCE], 'map-1');
  assert.deepEqual(points, []);
});

test('filterPointsForMap: returns [] when no map is selected', () => {
  assert.deepEqual(filterPointsForMap([MAIN_ENTRANCE], ''), []);
});

test('hasNoPointsForMap: true only when a map is selected and has zero active points', () => {
  assert.equal(hasNoPointsForMap([INACTIVE_ENTRANCE], 'map-1'), true);
  assert.equal(hasNoPointsForMap([MAIN_ENTRANCE], 'map-1'), false);
  assert.equal(hasNoPointsForMap([], ''), false);
});

test('resolveMapDerivedInfo: derives building/map group/floor straight from the selected Map', () => {
  const info = resolveMapDerivedInfo(MALL_MAP_FLOOR_1_GROUPED);
  assert.equal(info.buildingId, 'bld-1');
  assert.equal(info.mapGroupId, 'grp-1');
  assert.equal(info.mapGroupCode, 'AF-1');
  assert.equal(info.floor, 1);
  assert.equal(info.floorDisplay, 'Floor 1');
});

test('resolveMapDerivedInfo: no map selected yields a clear empty state, never invented values', () => {
  const info = resolveMapDerivedInfo(null);
  assert.equal(info.buildingId, '');
  assert.equal(info.mapGroupId, null);
  assert.equal(info.floor, null);
  assert.equal(info.floorDisplay, '—');
});

test('buildEditFormFromEntry: builds the Edit form straight from the real API response, never display text', () => {
  const entry = {
    id: 'code-1', code: 'QR-MAIN-01', building_id: 'bld-1', map_id: 'map-1',
    route_point_id: 'pt-1', label: 'Main Entrance', is_active: true,
  };
  assert.deepEqual(buildEditFormFromEntry(entry), {
    id: 'code-1', buildingId: 'bld-1', mapId: 'map-1', routePointId: 'pt-1',
    code: 'QR-MAIN-01', label: 'Main Entrance', isActive: true,
  });
});

test('buildEditFormFromEntry: a falsy is_active is preserved as false, never defaulted to true', () => {
  const entry = { id: 'code-2', code: 'QR-X', building_id: 'bld-1', map_id: 'map-1', route_point_id: 'pt-1', is_active: false };
  assert.equal(buildEditFormFromEntry(entry).isActive, false);
});

test('isEditSaveEnabled: requires building/map/point; label and active are optional', () => {
  const complete = { buildingId: 'bld-1', mapId: 'map-1', routePointId: 'pt-1', label: '', isActive: false };
  assert.equal(isEditSaveEnabled(complete), true);

  for (const missingField of ['buildingId', 'mapId', 'routePointId']) {
    assert.equal(isEditSaveEnabled({ ...complete, [missingField]: '' }), false, `should be disabled without ${missingField}`);
  }
});

test('buildEditSavePayload: never includes `code` — Edit reassigns what the code points at, never the code text itself', () => {
  const form = { id: 'code-1', buildingId: 'bld-1', mapId: 'map-1', routePointId: 'pt-1', code: 'QR-MAIN-01', label: ' Main Entrance ', isActive: true };
  const payload = buildEditSavePayload(form);
  assert.deepEqual(payload, {
    building_id: 'bld-1', map_id: 'map-1', route_point_id: 'pt-1',
    label: 'Main Entrance', is_active: true,
  });
  assert.ok(!('code' in payload));
});

test('buildEditSavePayload: reassigning to a different map/point is reflected exactly (Main Entrance QR reassignment case)', () => {
  const form = {
    id: 'code-1', buildingId: 'bld-1', mapId: MALL_MAP_FLOOR_1_GROUPED.id,
    routePointId: 'pt-connected-main-entrance', code: 'QR-MAIN-01', label: 'Main Entrance', isActive: true,
  };
  const payload = buildEditSavePayload(form);
  assert.equal(payload.map_id, 'map-1');
  assert.equal(payload.route_point_id, 'pt-connected-main-entrance');
});

console.log(`\n${passed} passed`);
