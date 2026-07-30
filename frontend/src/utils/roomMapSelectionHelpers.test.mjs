// Plain-Node tests for the Add/Edit Room Building -> Map Group -> Floor
// Map picker's pure helpers (frontend/src/utils/roomMapSelectionHelpers.js).
// Run via `node roomMapSelectionHelpers.test.mjs`, matching this repo's
// other *.test.mjs files (no jest/vitest installed).
import assert from 'node:assert/strict';
import {
  UNGROUPED_MAP_GROUP_KEY,
  buildRoomMapGroupOptions,
  floorMapsForGroup,
  resolveAutoSelectedMapGroupKey,
  resolveAutoSelectedFloorMapId,
  buildFloorMapOptionLabel,
} from './roomMapSelectionHelpers.js';

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

function map(overrides) {
  return {
    id: 'map-id', title: 'A Map', floor: 0, floorLabel: null,
    mapGroupId: null, mapGroupCode: null, ...overrides,
  };
}

// ── buildRoomMapGroupOptions ─────────────────────────────────────────────

test('one option per real Map Group, plus one for ungrouped standalone maps', () => {
  const maps = [
    map({ id: 'a', mapGroupId: 'g1', mapGroupCode: 'AF-1', floor: 0 }),
    map({ id: 'b', mapGroupId: 'g1', mapGroupCode: 'AF-1', floor: 1 }),
    map({ id: 'c', mapGroupId: 'g2', mapGroupCode: 'BF-1', floor: 0 }),
    map({ id: 'd', mapGroupId: null, floor: 0 }),
  ];
  const options = buildRoomMapGroupOptions(maps);
  const keys = options.map((o) => o.key);
  assert.ok(keys.includes('g1'));
  assert.ok(keys.includes('g2'));
  assert.ok(keys.includes(UNGROUPED_MAP_GROUP_KEY));
  assert.equal(options.length, 3);

  const g1 = options.find((o) => o.key === 'g1');
  assert.equal(g1.code, 'AF-1');
  assert.equal(g1.floorCount, 2);
});

test('no ungrouped entry when every map belongs to a group', () => {
  const maps = [map({ id: 'a', mapGroupId: 'g1', mapGroupCode: 'AF-1' })];
  const options = buildRoomMapGroupOptions(maps);
  assert.ok(!options.some((o) => o.key === UNGROUPED_MAP_GROUP_KEY));
});

test('empty buildingMaps list yields zero options, never throws', () => {
  assert.deepEqual(buildRoomMapGroupOptions([]), []);
  assert.deepEqual(buildRoomMapGroupOptions(undefined), []);
});

// ── floorMapsForGroup ─────────────────────────────────────────────────────

test('returns exactly the chosen group\'s floors, sorted ascending', () => {
  const maps = [
    map({ id: 'a', mapGroupId: 'g1', floor: 2 }),
    map({ id: 'b', mapGroupId: 'g1', floor: 0 }),
    map({ id: 'c', mapGroupId: 'g1', floor: 1 }),
    map({ id: 'd', mapGroupId: 'g2', floor: 0 }),
  ];
  const floors = floorMapsForGroup(maps, 'g1');
  assert.deepEqual(floors.map((m) => m.id), ['b', 'c', 'a']);
});

test('the ungrouped key returns standalone maps, sorted ascending (not pre-sorted upstream)', () => {
  const maps = [
    map({ id: 'a', mapGroupId: null, floor: 3 }),
    map({ id: 'b', mapGroupId: null, floor: -1 }),
  ];
  const floors = floorMapsForGroup(maps, UNGROUPED_MAP_GROUP_KEY);
  assert.deepEqual(floors.map((m) => m.id), ['b', 'a']);
});

test('a null/unknown group key returns an empty list, never throws', () => {
  assert.deepEqual(floorMapsForGroup([map({})], null), []);
  assert.deepEqual(floorMapsForGroup([map({})], 'does-not-exist'), []);
});

// ── auto-select — "may be auto-selected when there is only one" ─────────

test('resolveAutoSelectedMapGroupKey: auto-selects the single group', () => {
  const maps = [map({ id: 'a', mapGroupId: 'g1' }), map({ id: 'b', mapGroupId: 'g1', floor: 1 })];
  assert.equal(resolveAutoSelectedMapGroupKey(maps), 'g1');
});

test('resolveAutoSelectedMapGroupKey: null when there are multiple groups', () => {
  const maps = [map({ id: 'a', mapGroupId: 'g1' }), map({ id: 'b', mapGroupId: 'g2' })];
  assert.equal(resolveAutoSelectedMapGroupKey(maps), null);
});

test('resolveAutoSelectedFloorMapId: auto-selects the single floor map in a group', () => {
  const maps = [map({ id: 'only-one', mapGroupId: 'g1', floor: 0 })];
  assert.equal(resolveAutoSelectedFloorMapId(maps, 'g1'), 'only-one');
});

test('resolveAutoSelectedFloorMapId: null when the group has multiple floors', () => {
  const maps = [
    map({ id: 'a', mapGroupId: 'g1', floor: 0 }),
    map({ id: 'b', mapGroupId: 'g1', floor: 1 }),
  ];
  assert.equal(resolveAutoSelectedFloorMapId(maps, 'g1'), null);
});

// ── buildFloorMapOptionLabel — "AF-123 · Floor 1 · QuickRoute Mall – Floor 1" ─

test('joins code, floor, and title with the spec\'s separator', () => {
  const label = buildFloorMapOptionLabel(
    map({ mapGroupCode: 'AF-123', floor: 1, title: 'QuickRoute Mall – Floor 1' }),
  );
  assert.equal(label, 'AF-123 · Floor 1 · QuickRoute Mall – Floor 1');
});

test('never renders a blank separator when the group code is missing', () => {
  const label = buildFloorMapOptionLabel(map({ mapGroupCode: null, floor: 0, title: 'Ground' }));
  assert.equal(label, 'Ground Floor · Ground');
  assert.ok(!label.includes('·  ·'));
  assert.ok(!label.startsWith('·'));
});

test('never renders a blank separator when the title is missing', () => {
  const label = buildFloorMapOptionLabel(map({ mapGroupCode: 'AF-1', floor: 2, title: '' }));
  assert.equal(label, 'AF-1 · Floor 2');
  assert.ok(!label.endsWith('·'));
});

test('preserves floor 0 (never masked as unknown)', () => {
  const label = buildFloorMapOptionLabel(map({ mapGroupCode: null, floor: 0, title: '' }));
  assert.equal(label, 'Ground Floor');
});

console.log(`\n${passed} tests passed.`);
