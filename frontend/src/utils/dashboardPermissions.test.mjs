// Dashboard redesign — dependency-free Node tests for
// dashboardPermissions.js. These assert that the frontend mirror never
// widens what backend/core/auth_deps.py already allows.
import assert from 'node:assert/strict';
import {
  isAdminRole,
  canManageInvitationCodes,
  canCreateBuildings,
  canOpenBuildingAdmin,
  canOpenMapWorkspace,
  canOpenNavigationCleanup,
  getAccessibleBuildingIds,
  userCanAccessBuilding,
  userCanAccessMapGroup,
  userCanAccessMap,
  buildSidebarItems,
  buildMapContextTools,
  canManageUsers,
  getAssignableRoles,
} from './dashboardPermissions.js';

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

const superAdmin = { role: 'super_admin', building_ids: [], all_buildings: false };
const globalWide = { role: 'global_manager', building_ids: [], all_buildings: false };
const globalScoped = { role: 'global_manager', building_ids: ['b1'], all_buildings: false };
const buildingMgr = { role: 'building_manager', building_ids: ['b1'], all_buildings: false };
const regular = { role: 'regular_user', building_ids: [], all_buildings: false };

test('regular_user is never an admin and gets no sidebar at all', () => {
  assert.equal(isAdminRole('regular_user'), false);
  assert.deepEqual(buildSidebarItems(regular), []);
  assert.deepEqual(buildSidebarItems(null), []);
  assert.equal(canOpenMapWorkspace(regular), false);
  assert.equal(canOpenBuildingAdmin(regular), false);
});

test('invitation codes mirror require_global_admin exactly', () => {
  assert.equal(canManageInvitationCodes(superAdmin), true);
  assert.equal(canManageInvitationCodes(globalWide), true);
  assert.equal(canManageInvitationCodes(buildingMgr), false);
  assert.equal(canManageInvitationCodes(regular), false);
});

test('creating buildings/map groups mirrors require_global_admin, not require_any_admin', () => {
  assert.equal(canCreateBuildings(buildingMgr), false);
  assert.equal(canOpenBuildingAdmin(buildingMgr), true);
});

test('navigation cleanup mirrors require_super_admin exactly', () => {
  assert.equal(canOpenNavigationCleanup(superAdmin), true);
  assert.equal(canOpenNavigationCleanup(globalWide), false);
  assert.equal(canOpenNavigationCleanup(buildingMgr), false);
});

test('the three documented global_manager scope shapes', () => {
  // (a) all_buildings -> everything
  assert.equal(getAccessibleBuildingIds({ ...globalWide, all_buildings: true }), null);
  // (b) explicit list -> narrowed exactly like a building_manager
  assert.deepEqual(getAccessibleBuildingIds(globalScoped), ['b1']);
  assert.equal(userCanAccessBuilding(globalScoped, 'b2'), false);
  // (c) empty list -> project-wide by role, never "no access"
  assert.equal(getAccessibleBuildingIds(globalWide), null);
  assert.equal(userCanAccessBuilding(globalWide, 'anything'), true);
});

test('super_admin is unrestricted; regular_user has no admin scope', () => {
  assert.equal(getAccessibleBuildingIds(superAdmin), null);
  assert.deepEqual(getAccessibleBuildingIds(regular), []);
  assert.equal(userCanAccessBuilding(regular, 'b1'), false);
});

test('building_manager map_ids is the most restrictive scope and wins over map_group_ids', () => {
  const user = { role: 'building_manager', building_ids: ['b1'], map_group_ids: ['g1'], map_ids: ['m1'] };
  assert.equal(userCanAccessMap(user, { id: 'm1', buildingId: 'b1', mapGroupId: 'g1' }), true);
  assert.equal(userCanAccessMap(user, { id: 'm2', buildingId: 'b1', mapGroupId: 'g1' }), false);
  // map-group level access is denied for a map_ids-only style narrowing
  const mapsOnly = { role: 'building_manager', building_ids: ['b1'], map_group_ids: [], map_ids: ['m1'] };
  assert.equal(userCanAccessMapGroup(mapsOnly, { id: 'g1', buildingId: 'b1' }), false);
});

test('building_manager map_group_ids narrows groups and maps when map_ids is empty', () => {
  const user = { role: 'building_manager', building_ids: ['b1'], map_group_ids: ['g1'], map_ids: [] };
  assert.equal(userCanAccessMapGroup(user, { id: 'g1', buildingId: 'b1' }), true);
  assert.equal(userCanAccessMapGroup(user, { id: 'g2', buildingId: 'b1' }), false);
  assert.equal(userCanAccessMap(user, { id: 'm9', buildingId: 'b1', mapGroupId: 'g1' }), true);
  assert.equal(userCanAccessMap(user, { id: 'm9', buildingId: 'b1', mapGroupId: 'g2' }), false);
  // out-of-scope building is refused before any map-level check
  assert.equal(userCanAccessMap(user, { id: 'm9', buildingId: 'bX', mapGroupId: 'g1' }), false);
});

test('an unscoped building_manager sees every map in its assigned buildings', () => {
  const user = { role: 'building_manager', building_ids: ['b1'], map_group_ids: [], map_ids: [] };
  assert.equal(userCanAccessMap(user, { id: 'm1', buildingId: 'b1', mapGroupId: 'g1' }), true);
  assert.equal(userCanAccessMapGroup(user, { id: 'g1', buildingId: 'b1' }), true);
});

test('sidebar carries global administration only, per role', () => {
  assert.deepEqual(
    buildSidebarItems(superAdmin).map((i) => i.key),
    ['overview', 'sites', 'mapManagement', 'invitations', 'users'],
  );
  assert.deepEqual(
    buildSidebarItems(globalWide).map((i) => i.key),
    ['overview', 'sites', 'mapManagement', 'invitations', 'users'],
  );
  // Map Management is globally reachable for every admin tier (its
  // CONTENTS are still scoped); Invitation Codes is global-admin only.
  assert.deepEqual(
    buildSidebarItems(buildingMgr).map((i) => i.key),
    ['overview', 'sites', 'mapManagement'],
  );
  // no map-scoped tool ever leaks into the global sidebar
  for (const user of [superAdmin, globalWide, buildingMgr]) {
    const keys = buildSidebarItems(user).map((i) => i.key);
    for (const forbidden of ['workspace', 'rooms', 'routes', 'locationCodes', 'analysis', 'cleanup']) {
      assert.equal(keys.includes(forbidden), false);
    }
  }
});

test('map tools appear only with a selected map, and cleanup only for super_admin', () => {
  assert.deepEqual(buildMapContextTools(superAdmin, null), []);
  assert.deepEqual(buildMapContextTools(regular, 'm1'), []);

  const superTools = buildMapContextTools(superAdmin, 'm1').map((t) => t.key);
  assert.deepEqual(superTools, ['workspace', 'rooms', 'routes', 'locationCodes', 'analysis', 'cleanup']);

  const bmTools = buildMapContextTools(buildingMgr, 'm1').map((t) => t.key);
  assert.equal(bmTools.includes('cleanup'), false);

  const workspace = buildMapContextTools(buildingMgr, 'm 1').find((t) => t.key === 'workspace');
  assert.equal(workspace.route, '/admin/map?mapId=m%201');

  // Every contextual tool carries the map context so Back can return to
  // the exact Floor Workspace it was opened from.
  for (const tool of buildMapContextTools(superAdmin, 'm1')) {
    assert.equal(tool.route.includes('mapId=m1'), true, tool.key);
  }
});

test('Users & Access is offered to the two manager tiers only', () => {
  assert.equal(canManageUsers(superAdmin), true);
  assert.equal(canManageUsers(globalWide), true);
  assert.equal(canManageUsers(globalScoped), true);
  assert.equal(canManageUsers(buildingMgr), false);
  assert.equal(canManageUsers(regular), false);
  assert.equal(canManageUsers(null), false);

  // ...so a building_manager's sidebar never carries the entry.
  assert.equal(buildSidebarItems(buildingMgr).map((i) => i.key).includes('users'), false);
});

test('a global_manager is never offered super_admin as an assignable role', () => {
  assert.deepEqual(getAssignableRoles(superAdmin), [
    'super_admin',
    'global_manager',
    'building_manager',
  ]);
  // Mirrors the backend table: a global_manager may only hand out
  // building_manager — it cannot promote anyone (including itself).
  assert.deepEqual(getAssignableRoles(globalWide), ['building_manager']);
  assert.deepEqual(getAssignableRoles(buildingMgr), []);
  assert.deepEqual(getAssignableRoles(regular), []);
});

console.log(`\n${passed} passed`);
