// Regression tests for the missing editable Map.floor field: Edit Map
// Details previously had only Title/Campus/Address/Description — no way
// for an admin to ever set a legacy map's real Map.floor away from null,
// which is what caused both the RouteEdge "different floor" 400 and the
// RoutePoint floor-repair operation reporting "No RoutePoint floors need
// repair" for QuickRoute Mall - Floor 1.
//
// Backend persistence itself was already correct (see
// backend/tests/test_map_floor_edit.py) — this file covers the frontend
// half: a real Floor <select> exists, its initial value reflects the
// real backend Map.floor (never silently Ground Floor for null), 0 is
// preserved as a real value, and Save Changes sends the selected floor
// in the update payload.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { buildFloorEditOptions, normalizeFloorNumber } from './mapGroupHelpers.js';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const adminScreenSource = fs.readFileSync(
  path.join(__dirname, '..', 'screens', 'AdminMapScreen.jsx'),
  'utf8',
);

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

// Mirrors the exact <select> value derivation in AdminMapScreen.jsx's
// Edit Map Details Floor field.
function deriveSelectValue(formFloor) {
  return formFloor === null || formFloor === undefined ? '' : String(formFloor);
}

// ── 1. Map floor null renders "Floor is not configured" ────────────────
test('a null Map.floor renders as the empty select value + the "Floor is not configured" message, never a silently-assumed floor', () => {
  assert.equal(deriveSelectValue(null), '');
  assert.equal(deriveSelectValue(undefined), '');

  assert.match(adminScreenSource, /floorNotConfigured: 'Floor is not configured'/);
  // The message is rendered specifically when form.floor is null/undefined
  // — not unconditionally, and not defaulted to a Ground Floor label.
  assert.match(
    adminScreenSource,
    /\(form\.floor === null \|\| form\.floor === undefined\) && \(/,
  );
});

// ── 2. Floor 0 remains valid and is not treated as null ─────────────────
test('Floor 0 is a distinct, real select value — never coerced to the "not configured" empty state', () => {
  assert.equal(deriveSelectValue(0), '0');
  assert.notEqual(deriveSelectValue(0), '');

  assert.equal(normalizeFloorNumber(0), 0);
  assert.notEqual(normalizeFloorNumber(0), null);
});

test('buildFloorEditOptions always includes floor 0 (Ground Floor) as a selectable option', () => {
  const grouped = buildFloorEditOptions(
    { floor: null, mapGroupId: 'g1' },
    [{ floor: 1 }, { floor: 2 }],
  );
  assert.ok(grouped.some((o) => o.floor === 0), 'expected Ground Floor (0) to be offered for a grouped map');

  const legacy = buildFloorEditOptions({ floor: null, mapGroupId: null }, []);
  assert.ok(legacy.some((o) => o.floor === 0), 'expected Ground Floor (0) to be offered for a legacy standalone map');
});

// ── openEdit populates the real stored floor, not a derived/guessed one ──
test('openEdit sets form.floor directly from activeMap.floor (number or null), never `?? 0`', () => {
  const openEditMatch = adminScreenSource.match(/const openEdit = \(\) => \{[\s\S]*?\n  \};/);
  assert.ok(openEditMatch, 'expected to find openEdit');
  const body = openEditMatch[0];

  assert.match(body, /floor: activeMap\.floor,/);
  assert.doesNotMatch(body, /activeMap\.floor \?\? 0/);
  assert.doesNotMatch(body, /activeMap\.floor \|\| 0/);
});

// ── 3. Save Changes sends the selected floor in the update payload ─────
test('saveMapDetails always includes `floor` in the update payload sent to apiUpdateMap', () => {
  const saveMatch = adminScreenSource.match(/const saveMapDetails = async \(\) => \{[\s\S]*?\n  \};/);
  assert.ok(saveMatch, 'expected to find saveMapDetails');
  const body = saveMatch[0];

  assert.match(body, /floor: form\.floor === '' \? null : form\.floor,/);
  assert.match(body, /apiUpdateMap\(activeMap\.id, payload\)/);
});

test('saveMapDetails patches the updated Map back into `maps` state (reload + refresh activeMap/floor options), never a full-page reload', () => {
  const saveMatch = adminScreenSource.match(/const saveMapDetails = async \(\) => \{[\s\S]*?\n  \};/);
  const body = saveMatch[0];
  assert.match(body, /setMaps\(\(previousMaps\) =>/);
  assert.match(body, /map\.id === updatedMap\.id/);
});

// ── The Floor <select> itself is a real control (not free text) ────────
test('Edit Map Details renders a real Floor <select>, not a free-text input, driven by editFloorOptions', () => {
  assert.match(adminScreenSource, /const editFloorOptions = useMemo\(/);
  assert.match(adminScreenSource, /buildFloorEditOptions\(activeMap, activeMapGroupFloors\)/);
  assert.match(
    adminScreenSource,
    /\{t\.editFloorLabel\}[\s\S]{0,40}<\/label>\s*\n\s*<select/,
  );
  assert.match(adminScreenSource, /editFloorOptions\.map\(\(option\) => \(/);
});

console.log(`\n${passed} test(s) passed.`);
if (process.exitCode) {
  console.error('One or more tests FAILED.');
} else {
  console.log('All tests passed.');
}
