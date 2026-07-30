// Regression test for the exact reported bug (Admin Map Management floor-
// selection regression): "Draw Walkable Path shows a read-only Floor 0
// field, there are no visible floor-tab buttons, the admin is
// editing/reusing a RoutePoint belonging to Floor 1, and because the
// floor field is locked to Floor 0, the existing point is rejected with
// 'That point can't be reused here (different map/floor or inactive)'."
//
// A PRIOR fix made `floor`/`drawFloor` completely read-only, derived only
// from `activeMap` with no way for the admin to change it from inside a
// tool panel (the only way to change floor was an off-panel floor-tab
// strip that turned out not to be reliably reachable in the real
// browser UI). The actual fix restores admin control: a real <select>
// inside every tool panel (Add Point, Draw Walkable Path, Test Route,
// Vertical Connections), backed by `utils/mapGroupHelpers.js`'s
// `buildFloorSelectOptions`/`resolveFloorSwitch`, which is the ONLY thing
// that changes `selectedMapId` — so `activeMap`/`floor`/`drawFloor` still
// can never disagree with the selected map, but the admin now has a real
// way to change which one is selected. See mapGroupHelpers.test.mjs for
// the dedicated tests of those two functions; this file pins down the
// same bug at the level of the actual selection-validation logic
// (drawPathHelpers.resolveExistingPointSelection) that previously
// surfaced it, plus source-text contracts on AdminMapScreen.jsx so a
// regression back to a locked/read-only field would be caught even
// without a DOM test runner.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { resolveExistingPointSelection } from './drawPathHelpers.js';
import { buildFloorSelectOptions, resolveFloorSwitch } from './mapGroupHelpers.js';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

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

// Mirrors AdminMapScreen.jsx's derivation exactly:
//   const activeFloor = activeMap?.floor ?? 0;
//   const floor = activeFloor; const drawFloor = activeFloor;
function deriveActiveFloor(activeMap) {
  return activeMap?.floor ?? 0;
}

// ── 1. Selecting a Floor 1 map defaults the tool floor to 1 ────────────────
test('selecting a Floor 1 map defaults the tool floor to 1', () => {
  const floor1Map = { id: 'map-floor-1', floor: 1 };
  assert.equal(deriveActiveFloor(floor1Map), 1);
});

// ── 2. Selecting Floor 1 from the dropdown changes selectedMapId ───────────
test('selecting Floor 1 from the dropdown changes selectedMapId to the Floor 1 map', () => {
  const decision = resolveFloorSwitch({
    targetMapId: 'map-floor-1',
    currentMapId: 'map-floor-0',
    hasDraft: false,
    confirmFn: () => true,
  });
  assert.equal(decision.proceed, true);
  assert.equal(decision.nextMapId, 'map-floor-1');
});

// ── 3. RoutePoints reload for Floor 1 ────────────────────────────────────
// AdminMapScreen.jsx's route-point/route-edge loading effects are keyed
// on `selectedMapId` (`refreshRouteGraph(selectedMapId)` inside a
// `[selectedMapId, refreshRouteGraph]` dependency effect) — since the
// dropdown's onChange is the only path that changes `selectedMapId`
// (scenario 2 above), the reload is structurally guaranteed. Pinned here
// as a source-text contract so that guarantee can't silently break.
test('AdminMapScreen reloads the route graph whenever selectedMapId changes', () => {
  const source = fs.readFileSync(
    path.join(__dirname, '..', 'screens', 'AdminMapScreen.jsx'),
    'utf8',
  );
  assert.match(source, /refreshRouteGraph\(selectedMapId\)/);
  assert.match(source, /\[selectedMapId, refreshRouteGraph\]/);
});

// ── 4. A Floor 1 existing point can be reused ───────────────────────────
test('a Floor 1 existing point (e.g. "Sakara") is reusable once Floor 1 is selected — no false rejection', () => {
  const activeMap = { id: 'map-floor-1', floor: 1 };
  const drawFloor = deriveActiveFloor(activeMap);

  const sakaraPoint = {
    id: 'point-sakara',
    map_id: 'map-floor-1',
    floor: 1,
    is_active: true,
  };

  const result = resolveExistingPointSelection({
    point: sakaraPoint,
    activeMapId: activeMap.id,
    drawFloor,
    lastDraftPoint: null,
  });

  assert.equal(result.ok, true, `Expected the Floor 1 point to be reusable, got rejection: ${result.reason}`);
  assert.equal(result.draftItem.routePointId, 'point-sakara');
});

// ── 5. A Floor 0 point is rejected while Floor 1 is selected ───────────────
test('a Floor 0 point is still correctly rejected while Floor 1 is selected (no over-correction)', () => {
  const activeMap = { id: 'map-floor-1', floor: 1 };
  const drawFloor = deriveActiveFloor(activeMap);

  const floor0Point = { id: 'point-ground', map_id: 'map-floor-0', floor: 0, is_active: true };

  const result = resolveExistingPointSelection({
    point: floor0Point,
    activeMapId: activeMap.id,
    drawFloor,
    lastDraftPoint: null,
  });

  assert.equal(result.ok, false);
  assert.equal(result.reason, 'wrong-map');
});

// ── 6. Changing back to Ground Floor changes selectedMapId and floor together ──
test('changing back to Ground Floor changes selectedMapId and floor together', () => {
  const decision = resolveFloorSwitch({
    targetMapId: 'map-floor-0',
    currentMapId: 'map-floor-1',
    hasDraft: false,
    confirmFn: () => true,
  });
  assert.equal(decision.proceed, true);
  assert.equal(decision.nextMapId, 'map-floor-0');

  // The floor value itself is always re-derived from whichever map
  // selectedMapId now points to — never set independently.
  const nextActiveMap = { id: decision.nextMapId, floor: 0 };
  assert.equal(deriveActiveFloor(nextActiveMap), 0);
});

// ── 7. Floors without Maps do not appear in the dropdown ───────────────────
test('floors without a Map document do not appear in the floor dropdown options', () => {
  const floor0 = { id: 'map-0', floor: 0 };
  const floor2 = { id: 'map-2', floor: 2 };
  // Only Floor 0 and Floor 2 have real Map documents in this group —
  // Floor 1 must never appear as a selectable option.
  const options = buildFloorSelectOptions(floor0, [floor0, floor2]);
  assert.deepEqual(options.map((o) => o.floor), [0, 2]);
});

// ── 8. Switching floors with an unsaved draft asks for confirmation ────────
test('switching floors with an unsaved draft asks for confirmation', () => {
  let confirmCalled = false;
  resolveFloorSwitch({
    targetMapId: 'map-floor-1',
    currentMapId: 'map-floor-0',
    hasDraft: true,
    confirmFn: () => {
      confirmCalled = true;
      return true;
    },
  });
  assert.equal(confirmCalled, true);
});

// ── 9. Confirming clears the draft and switches Map/floor ──────────────────
test('confirming the floor switch clears the draft and switches Map/floor', () => {
  const decision = resolveFloorSwitch({
    targetMapId: 'map-floor-1',
    currentMapId: 'map-floor-0',
    hasDraft: true,
    confirmFn: () => true,
  });
  assert.equal(decision.proceed, true);
  assert.equal(decision.clearDraft, true);
  assert.equal(decision.nextMapId, 'map-floor-1');
});

// ── 10. Cancelling preserves the current Map/floor and draft ───────────────
test('cancelling the floor switch preserves the current Map/floor and draft', () => {
  const decision = resolveFloorSwitch({
    targetMapId: 'map-floor-1',
    currentMapId: 'map-floor-0',
    hasDraft: true,
    confirmFn: () => false,
  });
  assert.equal(decision.proceed, false);
  // Caller must not touch selectedMapId or clear the draft when proceed
  // is false — nextMapId/clearDraft are simply absent from the decision.
  assert.equal(decision.nextMapId, undefined);
  assert.equal(decision.clearDraft, undefined);
});

// ── Source-text contracts on the actual UI (no read-only lock) ─────────────

test('AdminMapScreen no longer renders a read-only/disabled floor <input>', () => {
  const source = fs.readFileSync(
    path.join(__dirname, '..', 'screens', 'AdminMapScreen.jsx'),
    'utf8',
  );
  assert.doesNotMatch(source, /value=\{activeFloorLabel\}/);
  assert.doesNotMatch(source, /floorDerivedHint/);
});

test('AdminMapScreen renders a real floor <select> shared by Add Point, Draw Walkable Path, and Test Route', () => {
  const source = fs.readFileSync(
    path.join(__dirname, '..', 'screens', 'AdminMapScreen.jsx'),
    'utf8',
  );
  assert.match(source, /const renderFloorSelect = /);
  assert.match(source, /renderFloorSelect\(t\.drawFloor, 'draw'\)/);
  assert.match(source, /renderFloorSelect\(t\.floor, 'point'\)/);
  assert.match(source, /renderFloorSelect\(t\.floor, 'test'\)/);
  assert.match(source, /onChange=\{\(event\) => handleFloorSwitch\(event\.target\.value\)\}/);
});

test('AdminMapScreen forwards floor-select props to VerticalConnectionsPanel', () => {
  const source = fs.readFileSync(
    path.join(__dirname, '..', 'screens', 'AdminMapScreen.jsx'),
    'utf8',
  );
  assert.match(source, /floorOptions=\{floorSelectOptions\}/);
  assert.match(source, /onFloorChange=\{handleFloorSwitch\}/);
});

test('VerticalConnectionsPanel renders its own floor <select> from the forwarded props', () => {
  const source = fs.readFileSync(
    path.join(__dirname, '..', 'components', 'VerticalConnectionsPanel.jsx'),
    'utf8',
  );
  assert.match(source, /id="floor-select-connector"/);
  assert.match(source, /onChange=\{\(event\) => onFloorChange\?\.\(event\.target\.value\)\}/);
});

console.log(`\n${passed} test(s) passed.`);
if (process.exitCode) {
  console.error('One or more tests FAILED.');
} else {
  console.log('All tests passed.');
}
