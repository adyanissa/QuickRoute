// RBAC/dashboard cleanup task (frontend completion) — dependency-free
// Node tests for roleRouting.js. Same pattern as the repo's other
// *.test.mjs files (custom test() runner, no jest/vitest) — run directly
// via `node roleRouting.test.mjs`.
import assert from 'node:assert/strict';
import {
  resolvePostLoginRoute,
  isAdminRole,
  hasAnyAssignedScope,
  ADMIN_DASHBOARD_ROUTE,
  END_USER_HOME_ROUTE,
} from './roleRouting.js';

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

// ── Login redirect (spec scenarios 1-5) ─────────────────────────────────

test('scenario 1: super_admin redirects to the Admin Dashboard', () => {
  assert.equal(resolvePostLoginRoute({ role: 'super_admin', map_ids: [] }), ADMIN_DASHBOARD_ROUTE);
});

test('scenario 2: global_manager redirects to the Admin Dashboard, never map-shortcutted', () => {
  assert.equal(resolvePostLoginRoute({ role: 'global_manager', map_ids: ['m1'] }), ADMIN_DASHBOARD_ROUTE);
});

test('scenario 3: building_manager with exactly one map redirects straight to it', () => {
  assert.equal(
    resolvePostLoginRoute({ role: 'building_manager', map_ids: ['map-123'] }),
    '/admin/map?mapId=map-123',
  );
});

test('scenario 4: building_manager with multiple maps goes to the (limited) dashboard', () => {
  assert.equal(
    resolvePostLoginRoute({ role: 'building_manager', map_ids: ['m1', 'm2'] }),
    ADMIN_DASHBOARD_ROUTE,
  );
});

test('building_manager with zero maps goes to the dashboard (empty state), not a broken map link', () => {
  assert.equal(resolvePostLoginRoute({ role: 'building_manager', map_ids: [] }), ADMIN_DASHBOARD_ROUTE);
});

test('scenario 5: regular_user goes to the normal end-user flow', () => {
  assert.equal(resolvePostLoginRoute({ role: 'regular_user', map_ids: [] }), END_USER_HOME_ROUTE);
});

test('missing/malformed user object falls back to the end-user flow, never throws', () => {
  assert.equal(resolvePostLoginRoute(null), END_USER_HOME_ROUTE);
  assert.equal(resolvePostLoginRoute({}), END_USER_HOME_ROUTE);
  assert.equal(resolvePostLoginRoute({ role: 'building_manager' }), ADMIN_DASHBOARD_ROUTE);
});

test('a mapId containing characters that need URL-encoding is encoded', () => {
  assert.equal(
    resolvePostLoginRoute({ role: 'building_manager', map_ids: ['abc def/123'] }),
    '/admin/map?mapId=abc%20def%2F123',
  );
});

// ── isAdminRole ──────────────────────────────────────────────────────────

test('isAdminRole matches exactly the three admin-tier roles', () => {
  assert.equal(isAdminRole('super_admin'), true);
  assert.equal(isAdminRole('global_manager'), true);
  assert.equal(isAdminRole('building_manager'), true);
  assert.equal(isAdminRole('regular_user'), false);
  assert.equal(isAdminRole(undefined), false);
});

// ── hasAnyAssignedScope (dashboard empty-state gating) ──────────────────

test('hasAnyAssignedScope: super_admin always true', () => {
  assert.equal(hasAnyAssignedScope({ role: 'super_admin' }), true);
});

test('hasAnyAssignedScope: all_buildings=true is always assigned', () => {
  assert.equal(
    hasAnyAssignedScope({ role: 'global_manager', all_buildings: true, building_ids: [] }),
    true,
  );
});

test('hasAnyAssignedScope: empty building_ids and no all_buildings is unassigned', () => {
  assert.equal(
    hasAnyAssignedScope({ role: 'building_manager', all_buildings: false, building_ids: [] }),
    false,
  );
});

test('hasAnyAssignedScope: non-empty building_ids is assigned', () => {
  assert.equal(
    hasAnyAssignedScope({ role: 'building_manager', all_buildings: false, building_ids: ['b1'] }),
    true,
  );
});

test('hasAnyAssignedScope: null user is unassigned, never throws', () => {
  assert.equal(hasAnyAssignedScope(null), false);
});

console.log(`\n${passed} passed`);
