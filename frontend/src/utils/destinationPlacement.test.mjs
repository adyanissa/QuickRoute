// Plain-Node tests for the map-based destination placement helpers
// (frontend/src/utils/destinationPlacement.js). Same pattern as the
// repo's other *.test.mjs files — no jest/vitest installed, run directly
// via `node destinationPlacement.test.mjs`.
import assert from 'node:assert/strict';
import {
  computeOriginalImageCoords,
  getDestinationRoutePointId,
  pointBelongsToMap,
  applySuggestedName,
  summarizeOcrSuggestion,
} from './destinationPlacement.js';

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

// ── computeOriginalImageCoords ─────────────────────────────────────────────

test('computeOriginalImageCoords: converts a scaled-down display click to native pixels', () => {
  // A 4000x2000 native image rendered at 800x400 on screen (5x scale) —
  // clicking at (400, 200) on screen should land at (2000, 1000) native.
  const result = computeOriginalImageCoords({
    clientX: 400,
    clientY: 200,
    rectLeft: 0,
    rectTop: 0,
    rectWidth: 800,
    rectHeight: 400,
    naturalWidth: 4000,
    naturalHeight: 2000,
  });

  assert.deepEqual(result, { x: 2000, y: 1000 });
});

test('computeOriginalImageCoords: accounts for the container offset (rectLeft/rectTop)', () => {
  const result = computeOriginalImageCoords({
    clientX: 450,
    clientY: 250,
    rectLeft: 50,
    rectTop: 50,
    rectWidth: 800,
    rectHeight: 400,
    naturalWidth: 4000,
    naturalHeight: 2000,
  });

  assert.deepEqual(result, { x: 2000, y: 1000 });
});

test('computeOriginalImageCoords: clamps a click right at the edge into bounds', () => {
  const result = computeOriginalImageCoords({
    clientX: 800.4, // fractional rect measurement can push this past the edge
    clientY: 0,
    rectLeft: 0,
    rectTop: 0,
    rectWidth: 800,
    rectHeight: 400,
    naturalWidth: 4000,
    naturalHeight: 2000,
  });

  assert.ok(result.x <= 4000);
  assert.ok(result.x >= 0);
});

test('computeOriginalImageCoords: returns null when the image has not measured yet', () => {
  const result = computeOriginalImageCoords({
    clientX: 10,
    clientY: 10,
    rectLeft: 0,
    rectTop: 0,
    rectWidth: 0,
    rectHeight: 0,
    naturalWidth: 0,
    naturalHeight: 0,
  });

  assert.equal(result, null);
});

// ── getDestinationRoutePointId ─────────────────────────────────────────────

test('getDestinationRoutePointId: reads the directly-stored id (camelCase view-model)', () => {
  assert.equal(
    getDestinationRoutePointId({ routePointId: 'point-1' }),
    'point-1'
  );
});

test('getDestinationRoutePointId: reads the directly-stored id (raw backend snake_case)', () => {
  assert.equal(
    getDestinationRoutePointId({ route_point_id: 'point-2' }),
    'point-2'
  );
});

test('getDestinationRoutePointId: a room with no linked point resolves to null, never a guess', () => {
  assert.equal(getDestinationRoutePointId({ id: 'room-without-point' }), null);
  assert.equal(getDestinationRoutePointId(null), null);
  assert.equal(getDestinationRoutePointId(undefined), null);
});

// ── pointBelongsToMap ───────────────────────────────────────────────────────

test('pointBelongsToMap: true when the point is on the given map', () => {
  assert.equal(pointBelongsToMap({ map_id: 'map-1' }, 'map-1'), true);
});

test('pointBelongsToMap: false when the point belongs to a different map', () => {
  assert.equal(pointBelongsToMap({ map_id: 'map-1' }, 'map-2'), false);
});

test('pointBelongsToMap: false for a missing point or missing mapId', () => {
  assert.equal(pointBelongsToMap(null, 'map-1'), false);
  assert.equal(pointBelongsToMap({ map_id: 'map-1' }, null), false);
});

// ── applySuggestedName ──────────────────────────────────────────────────────

test('applySuggestedName: trims the suggestion text', () => {
  assert.equal(applySuggestedName('  Pharmacy  '), 'Pharmacy');
});

test('applySuggestedName: empty/undefined suggestion becomes an empty string, never a fake name', () => {
  assert.equal(applySuggestedName(''), '');
  assert.equal(applySuggestedName(undefined), '');
});

// ── summarizeOcrSuggestion ──────────────────────────────────────────────────

test('summarizeOcrSuggestion: unavailable result cannot be applied', () => {
  const summary = summarizeOcrSuggestion({
    available: false,
    text: '',
    reason: 'OCR engine not installed',
  });

  assert.equal(summary.canApply, false);
  assert.equal(summary.message, 'OCR engine not installed');
});

test('summarizeOcrSuggestion: available but empty text cannot be applied (no fake name)', () => {
  const summary = summarizeOcrSuggestion({
    available: true,
    text: '',
    confidence: 0,
    reason: 'No legible text found at the selected location.',
  });

  assert.equal(summary.canApply, false);
  assert.equal(summary.text, '');
});

test('summarizeOcrSuggestion: high-confidence text is applicable and not flagged low-confidence', () => {
  const summary = summarizeOcrSuggestion({
    available: true,
    text: 'Radiology',
    confidence: 0.82,
    low_confidence: false,
  });

  assert.equal(summary.canApply, true);
  assert.equal(summary.text, 'Radiology');
  assert.equal(summary.lowConfidence, false);
});

test('summarizeOcrSuggestion: low-confidence text is still returned (never withheld) but flagged', () => {
  const summary = summarizeOcrSuggestion({
    available: true,
    text: 'R4d1o1ogy?',
    confidence: 0.2,
    low_confidence: true,
  });

  // The admin can still see and choose to use it — the UI must never
  // silently discard a suggestion — but it must be clearly marked so the
  // name field is never treated as pre-confirmed.
  assert.equal(summary.canApply, true);
  assert.equal(summary.lowConfidence, true);
  assert.ok(summary.message);
});

console.log(`\n${passed} passed`);
