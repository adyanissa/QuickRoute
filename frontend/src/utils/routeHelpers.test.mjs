// Tests for utils/routeHelpers.js's display-only step estimate
// (estimateSteps) added alongside the map-calibration walkway-edge
// recalculation fix. Same plain-node convention as the rest of this
// repo's utils/*.test.mjs (no jest/testing-library installed).

import assert from 'node:assert/strict';
import { formatDistance, formatTime, estimateSteps } from './routeHelpers.js';

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

test('estimateSteps: rounds meters / 0.75 to the nearest whole step', () => {
  assert.equal(estimateSteps(75), 100);
  assert.equal(estimateSteps(7.5), 10);
  assert.equal(estimateSteps(0), 0);
});

test('estimateSteps: null/undefined/NaN/negative input never throws, returns null', () => {
  assert.equal(estimateSteps(null), null);
  assert.equal(estimateSteps(undefined), null);
  assert.equal(estimateSteps(NaN), null);
  assert.equal(estimateSteps(-5), null);
});

test('estimateSteps: never returns a fractional value (always a whole step count)', () => {
  const result = estimateSteps(123.4);
  assert.equal(Number.isInteger(result), true);
});

// Regression guard — formatDistance/formatTime (used right next to the
// new step estimate) are unchanged.
test('formatDistance/formatTime are unchanged by this addition', () => {
  assert.equal(formatDistance(120), '120 m');
  assert.equal(formatDistance(1500), '1.5 km');
  assert.equal(formatDistance(null), '—');
  assert.equal(formatTime(12), '~12 min');
  assert.equal(formatTime(0), '—');
});

console.log(`\n${passed} test(s) passed.`);
if (process.exitCode) {
  console.error('Some tests FAILED.');
} else {
  console.log('All tests passed.');
}
