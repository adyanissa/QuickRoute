// Source-text contract tests — QuickRoute User Experience Final Cleanup,
// Part 10 items 22-28 (guided navigation UI, Part 2).
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const source = fs.readFileSync(path.join(__dirname, 'IndoorNavigationScreen.jsx'), 'utf8');

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

// 22. The current instruction is visible in the primary card.
test('the current instruction text is rendered in the primary card', () => {
  assert.match(source, /s18-current-text/);
  assert.match(source, /currentStepData\.text/);
});

// 23. Progress is computed via the shared, tested pure helper — never
//     inline ad-hoc math that could drift from computeOverallProgress's
//     own test coverage (multiFloorRouteHelpers.test.mjs).
test('progress uses computeOverallProgress, not inline math', () => {
  assert.match(source, /computeOverallProgress\(/);
  assert.match(source, /overallProgress\.progressFraction/);
});

// 24. Remaining ETA/distance come from the real route response's own
//     totals (routeResult), never a hardcoded or randomly generated
//     value.
test('remaining time/distance are derived from routeResult, never randomly generated', () => {
  assert.match(source, /total_distance_meters/);
  assert.match(source, /total_estimated_time_seconds/);
  assert.doesNotMatch(source, /Math\.random/);
});

// 25. The floor transition card appears whenever the current floor
//     boundary has a transition segment (covers elevator/stairs/
//     escalator/ramp — ConnectorIcon dispatches on transition_type).
test('the floor transition card renders for every connector type (elevator/stairs/escalator/ramp)', () => {
  assert.match(source, /ConnectorIcon/);
  assert.match(source, /type === 'stairs'/);
  assert.match(source, /type === 'escalator'/);
  assert.match(source, /type === 'ramp'/);
});

// 26. The arrival state appears once the last floor's steps are all
//     complete — hasArrived is derived, not manually toggled.
test('hasArrived is derived from isLastFloor + currentFloorDone, and gates the arrival banner', () => {
  assert.match(source, /const hasArrived = isNavigating && isLastFloor && currentFloorDone/);
  assert.match(source, /\{hasArrived && \(/);
  assert.match(source, /s18-arrival/);
});

// 27. Physical left/right stays physically correct in RTL — the
// direction-rotation table is never conditioned on isRTL.
test('the direction arrow rotation table ignores isRTL (physical left/right never mirrored)', () => {
  const rotationBlockMatch = source.match(/const DIRECTION_ROTATION = \{[\s\S]*?\};/);
  assert.ok(rotationBlockMatch, 'DIRECTION_ROTATION table must exist');
  assert.doesNotMatch(rotationBlockMatch[0], /isRTL/);
});

// 28. A missing backend ETA/distance shows "—", never a fabricated
//     number.
test('missing total time/distance render the "—" placeholder, never a fake number', () => {
  assert.match(source, /totalTimeMin != null \? formatTime\(totalTimeMin\) : '—'/);
  assert.match(source, /totalDistance != null \? formatDistance\(totalDistance\) : '—'/);
});

console.log(`\n${passed} test(s) passed.`);
if (process.exitCode) {
  console.error('One or more tests FAILED.');
} else {
  console.log('All tests passed.');
}
