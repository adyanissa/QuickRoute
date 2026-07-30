// Source-text contract tests for Section 7/8/9/11 of the "Fix three
// connected end-user navigation issues" task: the single-choice
// vertical-transport preference control (any / elevator / stairs) on
// IndoorNavigationScreen.jsx, and its wiring through to the backend
// request + state-reset behavior.
//
// Same pattern as the other *.test.mjs files in this repo (no jest/
// testing-library installed) — asserts directly on source text rather
// than mounting a real DOM.

import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

function readFile(...parts) {
  return fs.readFileSync(path.join(__dirname, ...parts), 'utf8');
}

const screenSource = readFile('IndoorNavigationScreen.jsx');
const navigationApiSource = readFile('..', 'api', 'navigationApi.js');
const helpersSource = readFile('..', 'utils', 'multiFloorRouteHelpers.js');

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

// 1. The old three-checkbox row is gone.
test('the old avoidStairs/avoidEscalators/preferElevators checkbox state and row are removed', () => {
  assert.doesNotMatch(screenSource, /const \[avoidStairs, setAvoidStairs\]/);
  assert.doesNotMatch(screenSource, /const \[avoidEscalators, setAvoidEscalators\]/);
  assert.doesNotMatch(screenSource, /const \[preferElevators, setPreferElevators\]/);
  assert.doesNotMatch(screenSource, /s18-avoid-row/);
});

// 2. A single verticalPreference state variable exists, defaulting to 'any'.
test('a single verticalPreference state variable exists and defaults to "any"', () => {
  assert.match(screenSource, /const \[verticalPreference, setVerticalPreference\] = useState\('any'\)/);
});

// 3. The three required option values/labels exist, in the required order.
test('the three vertical-preference options (any/elevator/stairs) exist with translated labels in en/ar/he', () => {
  assert.match(screenSource, /\{ value: 'any', label: t\.vertPrefAny \}/);
  assert.match(screenSource, /\{ value: 'elevator', label: t\.vertPrefElevator \}/);
  assert.match(screenSource, /\{ value: 'stairs', label: t\.vertPrefStairs \}/);

  // Exact required strings (Section 7).
  assert.match(screenSource, /vertPrefAny: 'Any available route'/);
  assert.match(screenSource, /vertPrefElevator: 'Prefer elevator'/);
  assert.match(screenSource, /vertPrefStairs: 'Prefer stairs'/);
  assert.match(screenSource, /vertPrefAny: 'أي مسار متاح'/);
  assert.match(screenSource, /vertPrefElevator: 'أفضل المصعد'/);
  assert.match(screenSource, /vertPrefStairs: 'أفضل الدرج'/);
  assert.match(screenSource, /vertPrefAny: 'כל מסלול זמין'/);
  assert.match(screenSource, /vertPrefElevator: 'העדפת מעלית'/);
  assert.match(screenSource, /vertPrefStairs: 'העדפת מדרגות'/);
});

// 4. It renders as a single-choice control (radiogroup), not checkboxes.
test('the control is rendered as a single-choice radiogroup', () => {
  assert.match(screenSource, /role="radiogroup"/);
  assert.match(screenSource, /role="radio"/);
  assert.match(screenSource, /aria-checked=\{verticalPreference === option\.value\}/);
});

// 5. Selecting an option calls setVerticalPreference with that option's value.
test('clicking an option sets verticalPreference to that option\'s value', () => {
  assert.match(screenSource, /onClick=\{\(\) => setVerticalPreference\(option\.value\)\}/);
});

// 6. verticalPreference is sent to the backend as vertical_transport_preference.
test('calculateMultiFloorRoute is called with verticalTransportPreference, which navigationApi.js sends as vertical_transport_preference', () => {
  assert.match(screenSource, /verticalTransportPreference: verticalPreference/);
  assert.match(navigationApiSource, /verticalTransportPreference = "any"/);
  assert.match(navigationApiSource, /vertical_transport_preference: verticalTransportPreference/);
});

// 7. Changing verticalPreference re-requests the route for the SAME
//    start/destination (it's a dependency of the route-loading effect).
test('verticalPreference is a dependency of the route-loading effect (a change re-requests the route)', () => {
  const effectDepsMatch = screenSource.match(
    /}, \[building\?\.id, room\?\.id, optimizationMode, verticalPreference, lang\]\);/,
  );
  assert.ok(effectDepsMatch, 'expected verticalPreference in the route-loading effect dependency array');
});

// 8. routeStateKey incorporates the preference, so a change resets
//    activeFloorIndex/completedByFloor/floor-confirmation state exactly
//    like an optimization-mode change already does (Section 11).
test('routeStateKey incorporates verticalPreference (Section 11 state reset)', () => {
  assert.match(screenSource, /verticalPreference,\s*\}\)/);
  assert.match(helpersSource, /verticalPreference/);
});

// 9. routeResult/instructions are cleared at the START of every load —
//    including a load triggered purely by a preference change — so the
//    previous route (e.g. an elevator route) is never shown stale while
//    waiting for the new one (e.g. a stairs route).
test('setRouteResult(null) runs before the new request, never leaving a stale previous route visible', () => {
  const loadRouteMatch = screenSource.match(/const loadRoute = async \(\) => \{[\s\S]*?setRouteResult\(null\);/);
  assert.ok(loadRouteMatch, 'expected setRouteResult(null) near the start of loadRoute');
  assert.match(screenSource, /setRouteLoading\(true\)/);
});

console.log(`\n${passed} test(s) passed.`);
if (process.exitCode) {
  console.error('One or more tests FAILED.');
} else {
  console.log('All tests passed.');
}
