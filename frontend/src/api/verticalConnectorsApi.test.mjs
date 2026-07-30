// Plain-Node tests for verticalConnectorsApi.js's pure normalizers (no
// network access — mirrors this repo's other *.test.mjs files, run
// directly via `node verticalConnectorsApi.test.mjs`).
import assert from 'node:assert/strict';
import { normalizeConnector, normalizeConnectorStop } from './verticalConnectorsApi.js';

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

test('normalizeConnector: null input returns null', () => {
  assert.equal(normalizeConnector(null), null);
});

test('normalizeConnector: maps every snake_case backend field to a camelCase alias', () => {
  const raw = {
    id: 'c1',
    building_id: 'b1',
    map_group_id: 'g1',
    connector_code: 'ELEVATOR-A',
    name: 'Elevator A',
    connector_type: 'elevator',
    is_bidirectional: true,
    is_accessible: true,
    is_active: true,
    wait_time_seconds: 30,
    seconds_per_floor: 6,
    distance_per_floor_meters: 4,
    is_fully_connected: true,
    stops: [
      {
        route_point_id: 'p1',
        map_id: 'm0',
        floor: 0,
        x: 10,
        y: 10,
        name: 'Elevator A',
        connected_to_floor_graph: true,
      },
    ],
  };

  const normalized = normalizeConnector(raw);

  assert.equal(normalized.id, 'c1');
  assert.equal(normalized.buildingId, 'b1');
  assert.equal(normalized.mapGroupId, 'g1');
  assert.equal(normalized.connectorCode, 'ELEVATOR-A');
  assert.equal(normalized.connectorType, 'elevator');
  assert.equal(normalized.isBidirectional, true);
  assert.equal(normalized.isAccessible, true);
  assert.equal(normalized.isActive, true);
  assert.equal(normalized.waitTimeSeconds, 30);
  assert.equal(normalized.secondsPerFloor, 6);
  assert.equal(normalized.distancePerFloorMeters, 4);
  assert.equal(normalized.isFullyConnected, true);
  assert.equal(normalized.stops.length, 1);
  assert.equal(normalized.stops[0].routePointId, 'p1');
  assert.equal(normalized.stops[0].connectedToFloorGraph, true);
});

test('normalizeConnector: is_active defaults to true only when genuinely absent, not when explicitly false', () => {
  const activeByDefault = normalizeConnector({ id: 'c1', name: 'X', connector_type: 'stairs' });
  assert.equal(activeByDefault.isActive, true);

  const explicitlyInactive = normalizeConnector({
    id: 'c1',
    name: 'X',
    connector_type: 'stairs',
    is_active: false,
  });
  assert.equal(explicitlyInactive.isActive, false);
});

test('normalizeConnector: missing stops array becomes an empty array, never undefined/null', () => {
  const normalized = normalizeConnector({ id: 'c1', name: 'X', connector_type: 'ramp' });
  assert.deepEqual(normalized.stops, []);
});

test('normalizeConnectorStop: null input returns null', () => {
  assert.equal(normalizeConnectorStop(null), null);
});

test('normalizeConnectorStop: connectedToFloorGraph is coerced to a real boolean', () => {
  const stop = normalizeConnectorStop({
    route_point_id: 'p1',
    map_id: 'm0',
    floor: 0,
    x: 1,
    y: 2,
    name: 'Stop',
    connected_to_floor_graph: undefined,
  });
  assert.equal(stop.connectedToFloorGraph, false);
});

console.log(`\n${passed} test(s) passed.`);
if (process.exitCode) {
  console.error('One or more tests FAILED.');
} else {
  console.log('All tests passed.');
}
