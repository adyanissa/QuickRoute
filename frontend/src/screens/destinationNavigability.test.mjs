// Tests for the normal-user destination availability fix: the backend's
// live `is_navigable` field (never a stale one-shot boolean) must be what
// actually gates a destination card's enabled/disabled state.
//
// Two layers, matching this repo's existing conventions:
//   1. A real unit test of utils/viewModels.js's roomToViewModel() — the
//      one true normalization point for the Room API response (pure JS,
//      directly testable).
//   2. Source-text contract tests of DestinationSelectionScreen.jsx —
//      same pattern as screens/locationCodeFlow.test.mjs — since this repo
//      has no DOM/component test harness (no jest/testing-library
//      installed) to mount the real component.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { roomToViewModel } from '../utils/viewModels.js';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const destSource = fs.readFileSync(path.join(__dirname, 'DestinationSelectionScreen.jsx'), 'utf8');

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

function fakeRoomApiResponse(overrides = {}) {
  return {
    id: 'room-1',
    name_en: 'Sakara',
    room_type: 'store',
    floor: 1,
    building_id: 'bld-1',
    is_active: true,
    route_point_id: 'point-1',
    route_point_connected: false, // the old, always-false-on-GET field
    is_navigable: true,
    navigation_unavailable_reason: null,
    ...overrides,
  };
}

// ── 1. roomToViewModel — real unit tests of the normalization point ────

test('roomToViewModel: a connected Room (is_navigable=true) maps to isNavigable=true', () => {
  const vm = roomToViewModel(fakeRoomApiResponse({ is_navigable: true, navigation_unavailable_reason: null }));
  assert.equal(vm.isNavigable, true);
  assert.equal(vm.navigationUnavailableReason, null);
});

test('roomToViewModel: Room with no route_point_id maps to isNavigable=false, reason missing_route_point', () => {
  const vm = roomToViewModel(fakeRoomApiResponse({
    route_point_id: null,
    is_navigable: false,
    navigation_unavailable_reason: 'missing_route_point',
  }));
  assert.equal(vm.isNavigable, false);
  assert.equal(vm.navigationUnavailableReason, 'missing_route_point');
  assert.equal(vm.routePointId, null);
});

test('roomToViewModel: an isolated (disconnected) RoutePoint maps to isNavigable=false, reason disconnected_from_graph', () => {
  const vm = roomToViewModel(fakeRoomApiResponse({
    route_point_id: 'point-isolated',
    is_navigable: false,
    navigation_unavailable_reason: 'disconnected_from_graph',
  }));
  assert.equal(vm.isNavigable, false);
  assert.equal(vm.navigationUnavailableReason, 'disconnected_from_graph');
  // The point DOES exist on the Room — only the graph connection is
  // missing, so routePointId itself must still be preserved as-is.
  assert.equal(vm.routePointId, 'point-isolated');
});

test('roomToViewModel: never trusts the old one-shot route_point_connected field for navigability', () => {
  // A plain GET response where the backend legitimately reports
  // is_navigable=true (live-computed) but the one-shot signal is still
  // false (its documented always-false-on-GET default) — isNavigable
  // must follow is_navigable, not route_point_connected.
  const vm = roomToViewModel(fakeRoomApiResponse({
    route_point_connected: false,
    is_navigable: true,
  }));
  assert.equal(vm.isNavigable, true);
});

test('roomToViewModel: missing/undefined is_navigable field defaults to false, never assumed true', () => {
  const raw = fakeRoomApiResponse();
  delete raw.is_navigable;
  const vm = roomToViewModel(raw);
  assert.equal(vm.isNavigable, false);
});

// ── 2. DestinationSelectionScreen.jsx — source contract tests ──────────

test('the click/enable guard uses room.isNavigable, never routePointId/routePointConnected', () => {
  assert.match(destSource, /if \(!room\.isNavigable\) return;/);
  assert.doesNotMatch(destSource, /!room\.routePointId \|\| !room\.routePointConnected/);
});

test('the DestinationCard disabled prop is driven by room.isNavigable, never a re-derived "connected" local', () => {
  assert.match(destSource, /disabled=\{!room\.isNavigable\}/);
  assert.doesNotMatch(destSource, /const connected = Boolean\(room\.routePointId/);
});

test('the screen refetches rooms on window focus and document visibility change (no stale cache after Admin edits)', () => {
  // Both events are still listened for — they cover different departures (a
  // tab switch fires visibilitychange; moving to another window often only
  // fires blur/focus) — but they now share ONE guarded handler, so a single
  // departure-and-return refreshes exactly once instead of twice. The
  // handler's identifier was never the contract; the refetch-on-return is.
  assert.match(destSource, /addEventListener\('focus', handleReturn\)/);
  assert.match(destSource, /addEventListener\('visibilitychange', handleReturn\)/);
  assert.match(destSource, /wasAwayRef\.current = false;\s*loadRooms\(\);/);
  // And actually cleans the listeners up — never leaks across unmounts.
  assert.match(destSource, /removeEventListener\('focus', handleReturn\)/);
  assert.match(destSource, /removeEventListener\('visibilitychange', handleReturn\)/);
  assert.match(destSource, /removeEventListener\('blur', markAway\)/);
});

test('destinations stay scoped to a single building_id (unrelated-building rooms never reach this screen)', () => {
  // The filter argument is now followed by an options argument carrying the
  // AbortController signal, so this pins BOTH halves of the contract: the
  // call is scoped to a building id, and that id comes from the current
  // building rather than from anywhere else.
  assert.match(destSource, /getRooms\(\s*\{ building_id: buildingId \}/);
  assert.match(destSource, /const buildingId = building\?\.id \?\? null;/);
  assert.doesNotMatch(destSource, /getRooms\(\)/);
  assert.doesNotMatch(destSource, /getRooms\(\{\}\)/);
});

console.log(`\n${passed} test(s) passed.`);
if (process.exitCode) {
  console.error('One or more tests FAILED.');
} else {
  console.log('All tests passed.');
}
