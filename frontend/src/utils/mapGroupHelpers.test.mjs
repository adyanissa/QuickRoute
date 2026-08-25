// Plain-Node tests for the multi-floor Map Group upload/management pure
// helpers (frontend/src/utils/mapGroupHelpers.js). Run directly via
// `node mapGroupHelpers.test.mjs`, matching this repo's other *.test.mjs
// files (no jest/vitest installed).
import assert from 'node:assert/strict';
import {
  createEmptyFloorRow,
  hasDuplicateFloors,
  validateFloorRows,
  isFloorBatchValid,
  sortFloorsByNumber,
  groupMapsByMapGroup,
  formatFloorDisplay,
  resolveMapReferenceStatus,
  buildMapOptionLabel,
  buildFloorSelectOptions,
  resolveFloorSwitch,
} from './mapGroupHelpers.js';

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

const FAKE_FILE = { name: 'floor.png' };

function validRow(overrides = {}) {
  return {
    rowId: 'row-1',
    file: FAKE_FILE,
    title: 'Ground Floor',
    floor: 0,
    floorLabel: 'Ground Floor',
    scale: 1,
    ...overrides,
  };
}

// ── createEmptyFloorRow ──────────────────────────────────────────────────

test('createEmptyFloorRow: first row defaults to floor 0', () => {
  const row = createEmptyFloorRow([]);
  assert.equal(row.floor, 0);
  assert.equal(row.file, null);
});

test('createEmptyFloorRow: defaults to one past the highest existing floor', () => {
  const row = createEmptyFloorRow([{ floor: 0 }, { floor: 2 }]);
  assert.equal(row.floor, 3);
});

test('createEmptyFloorRow: ignores non-numeric floors when computing the default', () => {
  const row = createEmptyFloorRow([{ floor: 'oops' }, { floor: 1 }]);
  assert.equal(row.floor, 2);
});

// ── hasDuplicateFloors ───────────────────────────────────────────────────

test('hasDuplicateFloors: false for distinct floors', () => {
  assert.equal(hasDuplicateFloors([{ floor: 0 }, { floor: 1 }, { floor: 2 }]), false);
});

test('hasDuplicateFloors: true when two rows share a floor number', () => {
  assert.equal(hasDuplicateFloors([{ floor: 0 }, { floor: 0 }]), true);
});

test('hasDuplicateFloors: supports negative (basement/parking) floors', () => {
  assert.equal(hasDuplicateFloors([{ floor: -1 }, { floor: -2 }]), false);
  assert.equal(hasDuplicateFloors([{ floor: -1 }, { floor: -1 }]), true);
});

// ── validateFloorRows / isFloorBatchValid ────────────────────────────────

test('validateFloorRows: three well-formed distinct-floor rows are valid', () => {
  const rows = [
    validRow({ floor: 0, title: 'Ground Floor' }),
    validRow({ floor: 1, title: 'First Floor' }),
    validRow({ floor: 2, title: 'Second Floor' }),
  ];
  assert.deepEqual(validateFloorRows(rows), {});
  assert.equal(isFloorBatchValid(rows), true);
});

test('validateFloorRows: empty list is rejected with a batch-level error', () => {
  const errors = validateFloorRows([]);
  assert.equal(typeof errors._batch, 'string');
  assert.equal(isFloorBatchValid([]), false);
});

test('validateFloorRows: duplicate floor numbers within the batch are flagged on both rows', () => {
  const rows = [validRow({ floor: 0 }), validRow({ floor: 0 })];
  const errors = validateFloorRows(rows);
  assert.equal(Object.keys(errors).length, 2);
  assert.equal(isFloorBatchValid(rows), false);
});

test('validateFloorRows: a floor colliding with an existing group floor is rejected', () => {
  const rows = [validRow({ floor: 1 })];
  const errors = validateFloorRows(rows, [0, 1, 2]);
  assert.equal(Object.keys(errors).length, 1);
  assert.match(errors[0][0], /already exists/);
});

test('validateFloorRows: missing file is flagged', () => {
  const rows = [validRow({ file: null })];
  const errors = validateFloorRows(rows);
  assert.match(errors[0].join(' '), /file is required/);
});

test('validateFloorRows: title shorter than 2 characters is flagged', () => {
  const rows = [validRow({ title: 'A' })];
  const errors = validateFloorRows(rows);
  assert.match(errors[0].join(' '), /at least 2 characters/);
});

test('validateFloorRows: non-integer floor is flagged (mezzanine labels not supported as numbers)', () => {
  const rows = [validRow({ floor: 1.5 })];
  const errors = validateFloorRows(rows);
  assert.match(errors[0].join(' '), /whole number/);
});

test('validateFloorRows: non-numeric floor is flagged', () => {
  const rows = [validRow({ floor: 'ground' })];
  const errors = validateFloorRows(rows);
  assert.match(errors[0].join(' '), /whole number/);
});

test('validateFloorRows: negative floors (parking/basement) are valid', () => {
  const rows = [validRow({ floor: -2, title: 'Parking B2' })];
  assert.deepEqual(validateFloorRows(rows), {});
});

test('validateFloorRows: zero/negative scale is flagged', () => {
  const rows = [validRow({ scale: 0 })];
  const errors = validateFloorRows(rows);
  assert.match(errors[0].join(' '), /Scale must be a positive number/);
});

// ── sortFloorsByNumber ───────────────────────────────────────────────────

test('sortFloorsByNumber: sorts ascending regardless of input order', () => {
  const floors = [{ floor: 2 }, { floor: 0 }, { floor: 1 }];
  const sorted = sortFloorsByNumber(floors);
  assert.deepEqual(sorted.map((f) => f.floor), [0, 1, 2]);
});

test('sortFloorsByNumber: supports negative floors sorting before ground', () => {
  const floors = [{ floor: 0 }, { floor: -1 }, { floor: 3 }, { floor: -2 }];
  const sorted = sortFloorsByNumber(floors);
  assert.deepEqual(sorted.map((f) => f.floor), [-2, -1, 0, 3]);
});

test('sortFloorsByNumber: does not mutate the original array', () => {
  const floors = [{ floor: 2 }, { floor: 0 }];
  const original = [...floors];
  sortFloorsByNumber(floors);
  assert.deepEqual(floors, original);
});

// ── groupMapsByMapGroup ──────────────────────────────────────────────────

test('groupMapsByMapGroup: maps sharing a mapGroupId become one group, sorted by floor', () => {
  const maps = [
    { id: 'm1', mapGroupId: 'g1', mapGroupCode: 'QRMALL-001', floor: 2 },
    { id: 'm2', mapGroupId: 'g1', mapGroupCode: 'QRMALL-001', floor: 0 },
    { id: 'm3', mapGroupId: 'g1', mapGroupCode: 'QRMALL-001', floor: 1 },
  ];
  const { groups, ungrouped } = groupMapsByMapGroup(maps);
  assert.equal(groups.length, 1);
  assert.equal(ungrouped.length, 0);
  assert.deepEqual(groups[0].floors.map((f) => f.id), ['m2', 'm3', 'm1']);
  assert.equal(groups[0].groupCode, 'QRMALL-001');
});

test('groupMapsByMapGroup: ungrouped single-floor maps stay in their own flat list', () => {
  const maps = [
    { id: 'legacy1', mapGroupId: null },
    { id: 'legacy2', mapGroupId: null },
  ];
  const { groups, ungrouped } = groupMapsByMapGroup(maps);
  assert.equal(groups.length, 0);
  assert.equal(ungrouped.length, 2);
});

test('groupMapsByMapGroup: a mix of grouped and ungrouped maps splits correctly', () => {
  const maps = [
    { id: 'm1', mapGroupId: 'g1', floor: 0 },
    { id: 'legacy1', mapGroupId: null },
    { id: 'm2', mapGroupId: 'g1', floor: 1 },
    { id: 'legacy2', mapGroupId: null },
  ];
  const { groups, ungrouped } = groupMapsByMapGroup(maps);
  assert.equal(groups.length, 1);
  assert.equal(groups[0].floors.length, 2);
  assert.equal(ungrouped.length, 2);
});

test('groupMapsByMapGroup: two distinct groups stay separate', () => {
  const maps = [
    { id: 'm1', mapGroupId: 'g1', floor: 0 },
    { id: 'm2', mapGroupId: 'g2', floor: 0 },
  ];
  const { groups } = groupMapsByMapGroup(maps);
  assert.equal(groups.length, 2);
});

// ── formatFloorDisplay ───────────────────────────────────────────────────

test('formatFloorDisplay: prefers an explicit floor label', () => {
  assert.equal(formatFloorDisplay(-1, 'Parking B1'), 'Parking B1');
});

test('formatFloorDisplay: falls back to "Ground Floor" for floor 0', () => {
  assert.equal(formatFloorDisplay(0, null), 'Ground Floor');
});

test('formatFloorDisplay: falls back to "Floor N" for positive floors', () => {
  assert.equal(formatFloorDisplay(3, ''), 'Floor 3');
});

test('formatFloorDisplay: falls back to "B<n>" for negative floors', () => {
  assert.equal(formatFloorDisplay(-2, undefined), 'B2');
});

test('formatFloorDisplay: em dash for a non-numeric floor with no label', () => {
  assert.equal(formatFloorDisplay(null, null), '—');
});

// ── resolveMapReferenceStatus / buildMapOptionLabel (Final Submission Part 2) ──

test('resolveMapReferenceStatus: "none" when no map id is set', () => {
  assert.deepEqual(resolveMapReferenceStatus(null, [{ id: 'map-1' }]), { status: 'none' });
  assert.deepEqual(resolveMapReferenceStatus('', [{ id: 'map-1' }]), { status: 'none' });
});

test('resolveMapReferenceStatus: "ok" when the map id is present in the current maps list', () => {
  const maps = [{ id: 'map-1', floor: 1 }, { id: 'map-2', floor: 2 }];
  const result = resolveMapReferenceStatus('map-2', maps);
  assert.equal(result.status, 'ok');
  assert.equal(result.map.id, 'map-2');
});

test('resolveMapReferenceStatus: "legacy" when the room/location code references a map not in the current list — the reported "shows an older map" bug', () => {
  const maps = [{ id: 'map-new-1', floor: 1 }];
  const result = resolveMapReferenceStatus('map-old-stale', maps);
  assert.deepEqual(result, { status: 'legacy' });
});

test('resolveMapReferenceStatus: compares ids as strings (ObjectId-vs-string safe)', () => {
  const maps = [{ id: 123 }];
  const result = resolveMapReferenceStatus('123', maps);
  assert.equal(result.status, 'ok');
});

test('buildMapOptionLabel: includes Map Group code, floor, and title', () => {
  const label = buildMapOptionLabel({ mapGroupCode: 'MALL-A', floor: 1, title: 'Concourse' });
  assert.equal(label, '[MALL-A] Floor 1 — Concourse');
});

test('buildMapOptionLabel: never leaves a trailing " — " when title is missing', () => {
  const label = buildMapOptionLabel({ floor: 2, title: '' });
  assert.equal(label, 'Floor 2');
  assert.ok(!label.includes('—'));
});

test('buildMapOptionLabel: omits the group prefix entirely when there is no map group', () => {
  const label = buildMapOptionLabel({ floor: 0, title: 'Lobby' });
  assert.equal(label, 'Ground Floor — Lobby');
});

// ── buildFloorSelectOptions (Admin Map Management floor-lock regression) ───
// Reported bug: Draw Walkable Path's Floor field was read-only ("Floor 0"),
// with no floor tabs actually reachable in the browser, so an admin could
// never get to Floor 1 to reuse an existing Floor 1 point. The fix is a
// real <select> in every tool panel, sourced from these floors only.

test('buildFloorSelectOptions: uses the Map Group siblings when the active map belongs to a group', () => {
  const floor0 = { id: 'map-0', floor: 0, floorLabel: '' };
  const floor1 = { id: 'map-1', floor: 1, floorLabel: '' };
  const options = buildFloorSelectOptions(floor0, [floor0, floor1]);
  assert.deepEqual(options.map((o) => o.id), ['map-0', 'map-1']);
});

test('buildFloorSelectOptions: falls back to just the active map for a legacy standalone map (no group)', () => {
  const standalone = { id: 'map-standalone', floor: 0 };
  const options = buildFloorSelectOptions(standalone, []);
  assert.deepEqual(options, [standalone]);
});

test('buildFloorSelectOptions: no active map and no group floors yields an empty (never crashing) list', () => {
  assert.deepEqual(buildFloorSelectOptions(null, []), []);
  assert.deepEqual(buildFloorSelectOptions(null, undefined), []);
});

test('buildFloorSelectOptions: never invents a floor that has no backing Map document', () => {
  // Only two real Map documents exist (Floor 0 and Floor 2) — a Floor 1
  // option must never appear just because it is numerically "between" them.
  const floor0 = { id: 'map-0', floor: 0 };
  const floor2 = { id: 'map-2', floor: 2 };
  const options = buildFloorSelectOptions(floor0, [floor0, floor2]);
  assert.equal(options.some((o) => o.floor === 1), false);
  assert.equal(options.length, 2);
});

// ── resolveFloorSwitch (selectedMapId/floor synchronization) ───────────────

test('resolveFloorSwitch: selecting a different floor proceeds and returns the target map id', () => {
  const result = resolveFloorSwitch({
    targetMapId: 'map-1',
    currentMapId: 'map-0',
    hasDraft: false,
    confirmFn: () => true,
  });
  assert.equal(result.proceed, true);
  assert.equal(result.nextMapId, 'map-1');
  assert.equal(result.clearDraft, true);
});

test('resolveFloorSwitch: re-selecting the already-active floor is a no-op', () => {
  const result = resolveFloorSwitch({
    targetMapId: 'map-0',
    currentMapId: 'map-0',
    hasDraft: false,
    confirmFn: () => true,
  });
  assert.equal(result.proceed, false);
  assert.equal(result.reason, 'no-op');
});

test('resolveFloorSwitch: an unsaved draft asks for confirmation before switching', () => {
  let wasAsked = false;
  resolveFloorSwitch({
    targetMapId: 'map-1',
    currentMapId: 'map-0',
    hasDraft: true,
    confirmFn: () => {
      wasAsked = true;
      return true;
    },
  });
  assert.equal(wasAsked, true, 'confirmFn must be called when a draft exists');
});

test('resolveFloorSwitch: confirming clears the draft and switches the map/floor together', () => {
  const result = resolveFloorSwitch({
    targetMapId: 'map-1',
    currentMapId: 'map-0',
    hasDraft: true,
    confirmFn: () => true,
  });
  assert.equal(result.proceed, true);
  assert.equal(result.nextMapId, 'map-1');
  assert.equal(result.clearDraft, true);
});

test('resolveFloorSwitch: cancelling preserves the current map/floor and does not clear the draft', () => {
  const result = resolveFloorSwitch({
    targetMapId: 'map-1',
    currentMapId: 'map-0',
    hasDraft: true,
    confirmFn: () => false,
  });
  assert.equal(result.proceed, false);
  assert.equal(result.reason, 'cancelled');
  assert.equal(result.nextMapId, undefined);
  assert.equal(result.clearDraft, undefined);
});

test('resolveFloorSwitch: no confirmation is asked when there is no unsaved draft', () => {
  let wasAsked = false;
  const result = resolveFloorSwitch({
    targetMapId: 'map-1',
    currentMapId: 'map-0',
    hasDraft: false,
    confirmFn: () => {
      wasAsked = true;
      return true;
    },
  });
  assert.equal(wasAsked, false);
  assert.equal(result.proceed, true);
});

test('resolveFloorSwitch: switching back to Ground Floor changes selectedMapId and floor together, same as any other floor', () => {
  const toGround = resolveFloorSwitch({
    targetMapId: 'map-ground',
    currentMapId: 'map-1',
    hasDraft: false,
    confirmFn: () => true,
  });
  assert.equal(toGround.proceed, true);
  assert.equal(toGround.nextMapId, 'map-ground');
});

console.log(`\n${passed} test(s) passed.`);
if (process.exitCode) {
  console.error('One or more tests FAILED.');
} else {
  console.log('All tests passed.');
}
