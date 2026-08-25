// Plain-Node tests for the "Initialize Project Data" admin action helpers
// (frontend/src/utils/maintenanceHelpers.js). Same pattern as
// drawPathHelpers.test.mjs — no jest/vitest installed, so this runs
// directly via `node maintenanceHelpers.test.mjs` using only the built-in
// `assert` module.
import assert from 'node:assert/strict';
import {
  classifyInitializeError,
  summarizeInitializeResult,
} from './maintenanceHelpers.js';

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

const MESSAGES = {
  sessionExpired: 'Your session has expired. Please log in again.',
  forbidden: 'Only super admins and global managers can run this operation.',
  failed: 'Failed to initialize project data',
};

// ── classifyInitializeError ────────────────────────────────────────────────

test('classifyInitializeError: 401 maps to sessionExpired', () => {
  const error = new Error('Invalid or expired access token');
  error.status = 401;

  const result = classifyInitializeError(error, MESSAGES);
  assert.equal(result.kind, 'sessionExpired');
  assert.equal(result.message, MESSAGES.sessionExpired);
});

test('classifyInitializeError: 403 maps to forbidden', () => {
  const error = new Error('You do not have permission to perform this action');
  error.status = 403;

  const result = classifyInitializeError(error, MESSAGES);
  assert.equal(result.kind, 'forbidden');
  assert.equal(result.message, MESSAGES.forbidden);
});

test('classifyInitializeError: other status uses backend detail message', () => {
  const error = new Error('Something went wrong on the server');
  error.status = 500;

  const result = classifyInitializeError(error, MESSAGES);
  assert.equal(result.kind, 'generic');
  assert.equal(result.message, 'Something went wrong on the server');
});

test('classifyInitializeError: network failure (no status, no message) falls back', () => {
  const error = new Error('');
  const result = classifyInitializeError(error, MESSAGES);
  assert.equal(result.kind, 'generic');
  assert.equal(result.message, MESSAGES.failed);
});

test('classifyInitializeError: never mistakes a 403 for a 401 or vice versa', () => {
  const unauthorized = new Error('Not authenticated');
  unauthorized.status = 401;
  const forbidden = new Error('Forbidden');
  forbidden.status = 403;

  assert.notEqual(
    classifyInitializeError(unauthorized, MESSAGES).kind,
    classifyInitializeError(forbidden, MESSAGES).kind
  );
});

// ── summarizeInitializeResult ──────────────────────────────────────────────

test('summarizeInitializeResult: reads the real backend response shape', () => {
  const backendResponse = {
    maps_updated: 1,
    points_updated: 17,
    buildings_created_or_reused: { abc123: 'QuickRoute Mall' },
    rooms_with_missing_building: 0,
    location_codes_inconsistent: 0,
  };

  const summary = summarizeInitializeResult(backendResponse);
  assert.equal(summary.mapsUpdated, 1);
  assert.equal(summary.pointsUpdated, 17);
  assert.equal(summary.buildingsTouchedCount, 1);
  assert.deepEqual(summary.buildingsTouchedNames, ['QuickRoute Mall']);
  assert.equal(summary.roomsWithMissingBuilding, 0);
  assert.equal(summary.locationCodesInconsistent, 0);
});

test('summarizeInitializeResult: second (no-op) run reports zero updates', () => {
  const backendResponse = {
    maps_updated: 0,
    points_updated: 0,
    buildings_created_or_reused: {},
    rooms_with_missing_building: 0,
    location_codes_inconsistent: 0,
  };

  const summary = summarizeInitializeResult(backendResponse);
  assert.equal(summary.mapsUpdated, 0);
  assert.equal(summary.pointsUpdated, 0);
  assert.equal(summary.buildingsTouchedCount, 0);
  assert.deepEqual(summary.buildingsTouchedNames, []);
});

test('summarizeInitializeResult: never throws on a missing/malformed field', () => {
  const summary = summarizeInitializeResult({});
  assert.equal(summary.mapsUpdated, 0);
  assert.equal(summary.pointsUpdated, 0);
  assert.equal(summary.buildingsTouchedCount, 0);
  assert.deepEqual(summary.buildingsTouchedNames, []);
});

console.log(`\n${passed} passed`);
