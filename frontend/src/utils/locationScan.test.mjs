// "Scan a room QR to relocate or confirm arrival" — dependency-free Node
// tests for locationScan.js. Same pattern as the repo's other *.test.mjs
// files (custom test() runner, no jest/vitest) — run directly via
// `node locationScan.test.mjs`.
import assert from 'node:assert/strict';
import {
  START_LOCATION_KEY,
  buildStartLocationRecord,
  classifyScannedLocation,
  isScanInActiveBuilding,
} from './locationScan.js';

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

// Fixtures mirroring the real payloads: a resolve response and the public
// RoutePoint the frontend then fetches with its route_point_id.
const ROOM_401 = { id: 'point401', room_id: 'room401', is_active: true, map_id: 'mapA' };
const ROOM_415 = { id: 'point415', room_id: 'room415', is_active: true, map_id: 'mapA' };
const ROOM_428 = { id: 'point428', room_id: 'room428', is_active: true, map_id: 'mapA' };

// ── The start-location record shape ─────────────────────────────────────

test('buildStartLocationRecord matches the shape BarcodeEntryScreen persists', () => {
  const record = buildStartLocationRecord({
    code: 'QR401',
    building_id: 'b1',
    map_id: 'mapA',
    route_point_id: 'point401',
    map_group_id: 'g1',
    floor: 4,
    label: 'Room 401',
  });

  assert.deepEqual(record, {
    routePointId: 'point401',
    mapId: 'mapA',
    mapGroupId: 'g1',
    floor: 4,
    buildingId: 'b1',
    code: 'QR401',
    label: 'Room 401',
  });
});

test('buildStartLocationRecord returns null without a route point', () => {
  assert.equal(buildStartLocationRecord({ code: 'QR401' }), null);
  assert.equal(buildStartLocationRecord(null), null);
});

test('the storage key is the one the rest of the app already uses', () => {
  assert.equal(START_LOCATION_KEY, 'quickroute_start_location');
});

// ── CASE 1: a scan with no active destination becomes the start ─────────

test('scan with no active destination is a plain relocate (new start)', () => {
  const result = classifyScannedLocation({ scannedPoint: ROOM_401 });

  assert.equal(result.outcome, 'relocate');
  assert.equal(result.startPointId, 'point401');
});

// ── CASE 2: scanning the destination room means ARRIVED ─────────────────

test('scanning the destination room QR produces ARRIVED, by room id', () => {
  const result = classifyScannedLocation({
    scannedPoint: ROOM_428,
    destinationRoomId: 'room428',
    destinationRoutePointId: 'point428',
    currentStartPointId: 'point415',
  });

  assert.equal(result.outcome, 'arrived');
  assert.equal(result.reason, 'room_id_match');
});

test('ARRIVED still works for a legacy point with no room link', () => {
  const legacyPoint = { id: 'point428', room_id: null, is_active: true };

  const result = classifyScannedLocation({
    scannedPoint: legacyPoint,
    destinationRoomId: 'room428',
    destinationRoutePointId: 'point428',
  });

  assert.equal(result.outcome, 'arrived');
  assert.equal(result.reason, 'route_point_match');
});

test('room ids are compared as strings, never as object identity', () => {
  const result = classifyScannedLocation({
    scannedPoint: { id: 'p', room_id: 428, is_active: true },
    destinationRoomId: '428',
  });

  assert.equal(result.outcome, 'arrived');
});

test('arrival is never decided by name similarity', () => {
  // Two different rooms that happen to share a display name must NOT be
  // treated as the same destination.
  const result = classifyScannedLocation({
    scannedPoint: { id: 'pX', room_id: 'roomX', is_active: true, name: 'Room 428' },
    destinationRoomId: 'room428',
    destinationRoutePointId: 'point428',
  });

  assert.equal(result.outcome, 'relocate');
});

// ── CASE 3: scanning another room relocates and recalculates ────────────

test('scanning a different room relocates and keeps the destination', () => {
  const result = classifyScannedLocation({
    scannedPoint: ROOM_415,
    destinationRoomId: 'room428',
    destinationRoutePointId: 'point428',
    currentStartPointId: 'point401',
  });

  assert.equal(result.outcome, 'relocate');
  assert.equal(result.startPointId, 'point415');
  assert.equal(result.reason, 'room_id_mismatch');
});

test('rescanning the room we are already in changes nothing', () => {
  const result = classifyScannedLocation({
    scannedPoint: ROOM_401,
    destinationRoomId: 'room428',
    destinationRoutePointId: 'point428',
    currentStartPointId: 'point401',
  });

  assert.equal(result.outcome, 'unchanged');
});

test('the full 401 -> 428 journey with a 415 checkpoint classifies correctly', () => {
  const destination = { destinationRoomId: 'room428', destinationRoutePointId: 'point428' };

  const atStart = classifyScannedLocation({ scannedPoint: ROOM_401, ...destination });
  assert.equal(atStart.outcome, 'relocate');

  const midway = classifyScannedLocation({
    scannedPoint: ROOM_415,
    ...destination,
    currentStartPointId: atStart.startPointId,
  });
  assert.equal(midway.outcome, 'relocate');
  assert.equal(midway.startPointId, 'point415');

  const atDestination = classifyScannedLocation({
    scannedPoint: ROOM_428,
    ...destination,
    currentStartPointId: midway.startPointId,
  });
  assert.equal(atDestination.outcome, 'arrived');
});

// ── Invalid scans ───────────────────────────────────────────────────────

test('a scan that resolves to nothing is invalid, never a silent relocate', () => {
  assert.equal(classifyScannedLocation({ scannedPoint: null }).outcome, 'invalid');
  assert.equal(classifyScannedLocation({}).outcome, 'invalid');
  assert.equal(classifyScannedLocation().outcome, 'invalid');
});

test('an inactive route point is rejected', () => {
  const result = classifyScannedLocation({
    scannedPoint: { id: 'pDead', room_id: 'roomDead', is_active: false },
    destinationRoomId: 'room428',
  });

  assert.equal(result.outcome, 'invalid');
  assert.equal(result.reason, 'inactive_point');
});

// ── Building scope ──────────────────────────────────────────────────────

test('a code from another building is refused before any route request', () => {
  assert.equal(isScanInActiveBuilding({ building_id: 'b2' }, 'b1'), false);
  assert.equal(isScanInActiveBuilding({ building_id: 'b1' }, 'b1'), true);
});

test('legacy records without a building are not treated as a mismatch', () => {
  assert.equal(isScanInActiveBuilding({ building_id: null }, 'b1'), true);
  assert.equal(isScanInActiveBuilding({ building_id: 'b1' }, null), true);
});

console.log(`\n${passed} passed`);
