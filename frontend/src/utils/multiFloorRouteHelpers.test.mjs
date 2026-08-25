// Plain-Node tests for multiFloorRouteHelpers.js (no jest/vitest in this
// repo — run directly via `node multiFloorRouteHelpers.test.mjs`).
import assert from 'node:assert/strict';
import {
  groupInstructionsByFloor,
  getTransitionInstructions,
  getFloorSegments,
  getTransitionSegments,
  instructionToStep,
  buildRouteStateKey,
  isFloorComplete,
  computeOverallProgress,
} from './multiFloorRouteHelpers.js';

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

const SAMPLE_INSTRUCTIONS = [
  { type: 'start', text: 'Proceed toward Junction 0.' },
  { type: 'right', text: 'Turn right at Junction 0, then continue 5 m.' },
  { type: 'arrive', text: 'You have arrived at Elevator A.' },
  { type: 'transition', transition_type: 'elevator', text: 'Use Elevator A and go to Floor 1.' },
  { type: 'start', text: 'Proceed toward Super-Pharm.' },
  { type: 'arrive', text: 'You have arrived at Super-Pharm.' },
];

test('groupInstructionsByFloor: splits on transition markers into N+1 floor groups for N transitions', () => {
  const groups = groupInstructionsByFloor(SAMPLE_INSTRUCTIONS);
  assert.equal(groups.length, 2);
  assert.equal(groups[0].length, 3);
  assert.equal(groups[1].length, 2);
  assert.equal(groups[0][0].type, 'start');
  assert.equal(groups[1][0].text, 'Proceed toward Super-Pharm.');
});

test('groupInstructionsByFloor: a same-floor route (no transitions) is a single group', () => {
  const groups = groupInstructionsByFloor([
    { type: 'start', text: 'Proceed toward X.' },
    { type: 'arrive', text: 'You have arrived at X.' },
  ]);
  assert.equal(groups.length, 1);
  assert.equal(groups[0].length, 2);
});

test('groupInstructionsByFloor: empty/non-array input returns one empty group, never throws', () => {
  assert.deepEqual(groupInstructionsByFloor([]), [[]]);
  assert.deepEqual(groupInstructionsByFloor(undefined), [[]]);
  assert.deepEqual(groupInstructionsByFloor(null), [[]]);
});

test('getTransitionInstructions: returns only transition-type entries, in order', () => {
  const transitions = getTransitionInstructions(SAMPLE_INSTRUCTIONS);
  assert.equal(transitions.length, 1);
  assert.equal(transitions[0].transition_type, 'elevator');
});

test('getFloorSegments / getTransitionSegments: partition a segments array by segment_type', () => {
  const segments = [
    { segment_type: 'floor', floor: 0 },
    { segment_type: 'transition', transition_type: 'elevator' },
    { segment_type: 'floor', floor: 1 },
  ];
  assert.equal(getFloorSegments(segments).length, 2);
  assert.equal(getTransitionSegments(segments).length, 1);
  assert.equal(getFloorSegments(segments)[1].floor, 1);
});

test('instructionToStep: maps every known instruction type to a RouteSteps-understood icon', () => {
  assert.equal(instructionToStep({ type: 'start' }).type, 'exit');
  assert.equal(instructionToStep({ type: 'straight' }).type, 'walk');
  assert.equal(instructionToStep({ type: 'left' }).type, 'turn');
  assert.equal(instructionToStep({ type: 'sharp_right' }).type, 'turn');
  assert.equal(instructionToStep({ type: 'u_turn' }).type, 'turn');
  assert.equal(instructionToStep({ type: 'arrive' }).type, 'arrive');
});

test('instructionToStep: an unrecognized type falls back to "info" rather than throwing/blank', () => {
  assert.equal(instructionToStep({ type: 'something_new' }).type, 'info');
  assert.equal(instructionToStep({}).type, 'info');
});

test('instructionToStep: preserves the exact backend text verbatim', () => {
  const step = instructionToStep({ type: 'right', text: 'Turn right at Sakara Junction.' });
  assert.equal(step.text, 'Turn right at Sakara Junction.');
});

test('instructionToStep: carries the raw direction and distance through for the big-arrow card (Part 8)', () => {
  const step = instructionToStep({ type: 'sharp_left', text: 'Sharp left.', distance_meters: 12 });
  assert.equal(step.direction, 'sharp_left');
  assert.equal(step.distanceMeters, 12);
});

test('instructionToStep: distanceMeters is null (not NaN/undefined) for start/arrive instructions', () => {
  assert.equal(instructionToStep({ type: 'start', text: 'Go.' }).distanceMeters, null);
  assert.equal(instructionToStep({ type: 'arrive', text: 'Arrived.' }).distanceMeters, null);
});

test('buildRouteStateKey: identical requests produce identical keys', () => {
  const a = buildRouteStateKey({ startPointId: 'p1', endPointId: 'p2', optimizationMode: 'fastest' });
  const b = buildRouteStateKey({ startPointId: 'p1', endPointId: 'p2', optimizationMode: 'fastest' });
  assert.equal(a, b);
});

test('buildRouteStateKey: a different optimization mode produces a different key (state must not be reused across modes)', () => {
  const shortest = buildRouteStateKey({ startPointId: 'p1', endPointId: 'p2', optimizationMode: 'shortest' });
  const accessible = buildRouteStateKey({ startPointId: 'p1', endPointId: 'p2', optimizationMode: 'accessible' });
  assert.notEqual(shortest, accessible);
});

// Section 11 — changing the vertical-transport preference must reset
// stale floor-transition/step-progress state exactly like an
// optimization-mode change already does, so buildRouteStateKey must
// produce a different key for a different preference (same start/end/mode).
test('buildRouteStateKey: a different vertical preference produces a different key (Section 11 state reset)', () => {
  const any = buildRouteStateKey({
    startPointId: 'p1', endPointId: 'p2', optimizationMode: 'shortest', verticalPreference: 'any',
  });
  const stairs = buildRouteStateKey({
    startPointId: 'p1', endPointId: 'p2', optimizationMode: 'shortest', verticalPreference: 'stairs',
  });
  const elevator = buildRouteStateKey({
    startPointId: 'p1', endPointId: 'p2', optimizationMode: 'shortest', verticalPreference: 'elevator',
  });
  assert.notEqual(any, stairs);
  assert.notEqual(any, elevator);
  assert.notEqual(stairs, elevator);
});

test('buildRouteStateKey: an omitted vertical preference defaults consistently (never undefined in the key)', () => {
  const omitted = buildRouteStateKey({ startPointId: 'p1', endPointId: 'p2', optimizationMode: 'shortest' });
  const explicitAny = buildRouteStateKey({
    startPointId: 'p1', endPointId: 'p2', optimizationMode: 'shortest', verticalPreference: 'any',
  });
  assert.equal(omitted, explicitAny);
  assert.doesNotMatch(omitted, /undefined/);
});

test('isFloorComplete: true for a zero-step floor (nothing to complete)', () => {
  assert.equal(isFloorComplete(0, new Set()), true);
});

test('isFloorComplete: false until every index 0..stepCount-1 is present', () => {
  assert.equal(isFloorComplete(3, new Set([0, 1])), false);
  assert.equal(isFloorComplete(3, new Set([0, 1, 2])), true);
});

// ── computeOverallProgress (Part 10) ────────────────────────────────────────

test('computeOverallProgress: 0 completed steps means 0 progress and full remaining time/distance', () => {
  const result = computeOverallProgress({
    instructionGroups: [[{}, {}], [{}]],
    completedByFloor: {},
    totalDistanceMeters: 100,
    totalTimeSeconds: 200,
  });
  assert.equal(result.totalSteps, 3);
  assert.equal(result.completedSteps, 0);
  assert.equal(result.progressFraction, 0);
  assert.equal(result.remainingDistanceMeters, 100);
  assert.equal(result.remainingTimeSeconds, 200);
});

test('computeOverallProgress: sums completed steps across ALL floors, not just the active one', () => {
  const result = computeOverallProgress({
    instructionGroups: [[{}, {}], [{}, {}]],
    completedByFloor: { 0: new Set([0, 1]), 1: new Set([0]) },
    totalDistanceMeters: 100,
    totalTimeSeconds: 100,
  });
  assert.equal(result.totalSteps, 4);
  assert.equal(result.completedSteps, 3);
  assert.equal(result.progressFraction, 0.75);
  assert.equal(result.remainingDistanceMeters, 25);
  assert.equal(result.remainingTimeSeconds, 25);
});

test('computeOverallProgress: every step completed means zero remaining, never negative', () => {
  const result = computeOverallProgress({
    instructionGroups: [[{}, {}]],
    completedByFloor: { 0: new Set([0, 1]) },
    totalDistanceMeters: 50,
    totalTimeSeconds: 60,
  });
  assert.equal(result.progressFraction, 1);
  assert.equal(result.remainingDistanceMeters, 0);
  assert.equal(result.remainingTimeSeconds, 0);
});

test('computeOverallProgress: missing total distance/time surfaces null, never NaN', () => {
  const result = computeOverallProgress({
    instructionGroups: [[{}]],
    completedByFloor: {},
    totalDistanceMeters: null,
    totalTimeSeconds: undefined,
  });
  assert.equal(result.remainingDistanceMeters, null);
  assert.equal(result.remainingTimeSeconds, null);
});

test('computeOverallProgress: zero total steps never divides by zero', () => {
  const result = computeOverallProgress({
    instructionGroups: [],
    completedByFloor: {},
    totalDistanceMeters: 10,
    totalTimeSeconds: 10,
  });
  assert.equal(result.totalSteps, 0);
  assert.equal(result.progressFraction, 0);
  assert.equal(result.remainingDistanceMeters, 10);
});

console.log(`\n${passed} test(s) passed.`);
if (process.exitCode) {
  console.error('One or more tests FAILED.');
} else {
  console.log('All tests passed.');
}
