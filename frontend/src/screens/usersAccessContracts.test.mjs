// Source-contract tests for the final admin user/access model, in the
// same style as the repo's other contract tests. These pin the rules that
// are cheap to break silently: which roles the invitation form offers,
// that a Building Manager assignment is single-select, and that Users &
// Access never renders an action the backend would refuse.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import {
  getAllowedRoleOptions,
  isCreateEnabled,
  selectAssignedBuilding,
  requiresBuildingSelection,
} from '../utils/invitationCodeFormHelpers.js';
import {
  canManageUsers,
  getAssignableRoles,
  buildSidebarItems,
  canDeleteMapResources,
  canOpenMapWorkspace,
} from '../utils/dashboardPermissions.js';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const read = (...parts) => fs.readFileSync(path.join(__dirname, '..', ...parts), 'utf8');

const usersScreen = read('screens', 'admin', 'UsersAccessScreen.jsx');
const usersCss = read('styles', 'usersAccess.css');
const mapScreen = read('screens', 'AdminMapScreen.jsx');
const usersApi = read('api', 'usersApi.js');
const app = read('App.jsx');

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

// ── Invitation role choices ────────────────────────────────────────────

test('Regular User is no longer offered as an admin invitation role', () => {
  for (const creator of ['super_admin', 'global_manager']) {
    assert.equal(getAllowedRoleOptions(creator).includes('regular_user'), false, creator);
  }
  assert.deepEqual(getAllowedRoleOptions('super_admin'), [
    'super_admin',
    'global_manager',
    'building_manager',
  ]);
  // The privileged half of the hierarchy is unchanged: a global_manager
  // still cannot mint a super_admin or another global_manager.
  assert.deepEqual(getAllowedRoleOptions('global_manager'), ['building_manager']);
  assert.deepEqual(getAllowedRoleOptions('building_manager'), []);
  assert.deepEqual(getAllowedRoleOptions('regular_user'), []);
});

test('a Building Manager invitation needs EXACTLY one building', () => {
  assert.equal(requiresBuildingSelection('building_manager'), true);
  const base = { role: 'building_manager' };
  assert.equal(isCreateEnabled({ ...base, buildingIds: [] }), false);
  assert.equal(isCreateEnabled({ ...base, buildingIds: ['b1'] }), true);
  // Two buildings is now invalid — the backend rejects it too.
  assert.equal(isCreateEnabled({ ...base, buildingIds: ['b1', 'b2'] }), false);
});

test('choosing a building replaces the previous one instead of accumulating', () => {
  const form = { role: 'building_manager', buildingIds: ['b1'] };
  assert.deepEqual(selectAssignedBuilding(form, 'b2').buildingIds, ['b2']);
  // Clicking the selected building clears it.
  assert.deepEqual(selectAssignedBuilding(form, 'b1').buildingIds, []);
  // Roles without a building assignment are left untouched.
  const other = { role: 'global_manager', buildingIds: [] };
  assert.deepEqual(selectAssignedBuilding(other, 'b2'), other);
});

// ── Users & Access visibility ──────────────────────────────────────────

test('Users & Access is offered to the manager tiers only', () => {
  const roles = {
    super_admin: { role: 'super_admin' },
    global_manager: { role: 'global_manager' },
    building_manager: { role: 'building_manager', building_ids: ['b1'] },
    regular_user: { role: 'regular_user' },
  };
  assert.equal(canManageUsers(roles.super_admin), true);
  assert.equal(canManageUsers(roles.global_manager), true);
  assert.equal(canManageUsers(roles.building_manager), false);
  assert.equal(canManageUsers(roles.regular_user), false);

  assert.equal(buildSidebarItems(roles.super_admin).some((i) => i.key === 'users'), true);
  assert.equal(buildSidebarItems(roles.global_manager).some((i) => i.key === 'users'), true);
  assert.equal(buildSidebarItems(roles.building_manager).some((i) => i.key === 'users'), false);
  assert.deepEqual(buildSidebarItems(roles.regular_user), []);
});

test('the route is behind the same guard as the API', () => {
  assert.match(
    app,
    /path=\{ADMIN_ROUTES\.users\}[\s\S]{0,160}<RequireGlobalAdmin>[\s\S]{0,80}<UsersAccessScreen \/>/,
  );
});

test('a global_manager is never offered super_admin in the edit form', () => {
  assert.deepEqual(getAssignableRoles({ role: 'global_manager' }), ['building_manager']);
  assert.equal(getAssignableRoles({ role: 'global_manager' }).includes('super_admin'), false);
  assert.equal(getAssignableRoles({ role: 'building_manager' }).length, 0);
});

// ── Users & Access screen contracts ────────────────────────────────────

test('row actions come from the backend decision, never re-derived locally', () => {
  // can_edit / can_delete are computed server-side (including the
  // last-super-admin and self-delete rules); the screen only reads them.
  assert.match(usersScreen, /record\.can_edit/);
  assert.match(usersScreen, /record\.can_delete/);
  assert.equal(/role === 'super_admin'\s*\?/.test(usersScreen), false);
});

test('delete is behind an action menu plus a confirmation dialog', () => {
  assert.match(usersScreen, /className="qra-menu-btn"/);
  assert.match(usersScreen, /ConfirmDeleteDialog/);
  assert.match(usersScreen, /role="alertdialog"/);
  assert.match(usersScreen, /ui\.deleteConfirm/);
});

test('the screen never sends scope fields or password material', () => {
  // Strip comments first: the file legitimately EXPLAINS why passwords
  // are never handled here, and a naive substring match would trip on the
  // explanation rather than on real code.
  const code = usersScreen.replace(/\/\/[^\n]*/g, '').replace(/\/\*[\s\S]*?\*\//g, '');
  for (const forbidden of ['password', 'map_ids', 'map_group_ids', 'all_buildings']) {
    assert.equal(code.includes(forbidden), false, forbidden);
  }
  // Only the three fields the backend schema accepts are ever sent; scope
  // itself is derived server-side from role + building_id.
  assert.match(usersScreen, /changes = \{ full_name: draft\.fullName, role: draft\.role \}/);
  assert.match(usersScreen, /changes\.building_id = draft\.buildingId/);
  assert.equal(/building_ids:/.test(code), false);
});

test('the API client talks to the project-consistent admin endpoints only', () => {
  assert.match(usersApi, /\/api\/admin\/users/);
  const apiCode = usersApi.replace(/\/\/[^\n]*/g, '');
  assert.equal(/password/.test(apiCode), false);
  for (const verb of ['PUT', 'DELETE']) assert.match(usersApi, new RegExp(`method: "${verb}"`));
});

test('the assigned-building control appears only for the role that has one', () => {
  assert.match(usersScreen, /const needsBuilding = role === 'building_manager'/);
  assert.match(usersScreen, /\{needsBuilding && \(/);
  // ...and it shows Site — Building names, never a raw id.
  assert.match(usersScreen, /resolveSiteName\(building, unassignedSiteLabel\)/);
});

test('responsibility is rendered from resolved names, never from raw ids', () => {
  assert.match(usersScreen, /record\.assigned_building\.name/);
  assert.match(usersScreen, /ui\.scope\[record\.scope_kind\]/);
  assert.equal(/building_ids\[0\]\}<\//.test(usersScreen), false);
});

test('the screen renders inside the shared admin shell', () => {
  assert.match(usersScreen, /<AdminScreenHeader pageKey="users" \/>/);
  assert.equal(usersScreen.includes('adm-inner-header'), false);
  assert.equal(usersScreen.includes('layout-wrapper'), false);
});

// ── Users & Access scroll architecture ─────────────────────────────────
// The document is the single vertical scroll owner for the whole admin
// shell. This page must not introduce a second one, and must not clip the
// absolutely-positioned row action menu (which is what made the last
// row's Delete item unreachable).

test('the users table creates no vertical scroll container of its own', () => {
  const rules = usersCss.replace(/\/\*[\s\S]*?\*\//g, '');
  const table = rules.slice(rules.indexOf('.qra-table {'), rules.indexOf('.qra-row:first-child'));
  assert.equal(/overflow(-y)?:\s*(auto|scroll|hidden)/.test(table), false);
  assert.equal(/max-height/.test(table), false);
  assert.equal(/[^-]height:/.test(table), false);
});

test('the only overflow container on the page is the modal body', () => {
  const rules = usersCss.replace(/\/\*[\s\S]*?\*\//g, '');
  const scrollers = [...rules.matchAll(/([.#][\w-]+)\s*\{[^}]*overflow-y:\s*auto/g)].map((m) => m[1]);
  assert.deepEqual(scrollers, ['.qra-dialog']);
  // ...and that one contains its scroll rather than chaining to the page.
  assert.match(rules, /\.qra-dialog\s*\{[^}]*overscroll-behavior:\s*contain/);
});

test('rounded corners come from the first/last row, not from clipping', () => {
  assert.match(usersCss, /\.qra-row:first-child\s*\{[^}]*border-start-start-radius/);
  assert.match(usersCss, /\.qra-row:last-child\s*\{[^}]*border-end-end-radius/);
});

test('the page leaves room below the table for a last-row action menu', () => {
  assert.match(usersCss, /\.qra-page-tail\s*\{[^}]*padding-block-end/);
  assert.match(usersScreen, /className="qrd-section qra-page-tail"/);
});

// ── Structural deletion is global-tier only ────────────────────────────

test('permanent map/group/floor deletion is super_admin + global_manager only', () => {
  assert.equal(canDeleteMapResources({ role: 'super_admin' }), true);
  assert.equal(canDeleteMapResources({ role: 'global_manager' }), true);
  assert.equal(canDeleteMapResources({ role: 'building_manager', building_ids: ['b1'] }), false);
  assert.equal(canDeleteMapResources({ role: 'regular_user' }), false);
  assert.equal(canDeleteMapResources(null), false);
});

test('a Building Manager keeps its whole operational surface', () => {
  const bm = { role: 'building_manager', building_ids: ['b1'] };
  // Map Management stays reachable...
  assert.equal(canOpenMapWorkspace(bm), true);
  assert.equal(buildSidebarItems(bm).some((i) => i.key === 'mapManagement'), true);
  // ...only the destructive capability is withheld.
  assert.equal(canDeleteMapResources(bm), false);
});

test('every structural delete control in Map Management is behind that check', () => {
  assert.match(mapScreen, /const canDeleteStructures = canDeleteMapResources\(user\)/);

  // Each of the three destructive controls is CONDITIONALLY RENDERED —
  // never rendered disabled, which would still advertise the capability.
  for (const handler of [
    'handleDeleteMapGroupFloor\\(group, floorMap\\)',
    'handleDeleteMapGroup\\(group\\)',
  ]) {
    const at = mapScreen.search(new RegExp(handler));
    assert.notEqual(at, -1, handler);
    const before = mapScreen.slice(Math.max(0, at - 400), at);
    assert.match(before, /\{canDeleteStructures && \(/);
  }

  const deleteMapAt = mapScreen.indexOf("setView(\n                        'confirm-delete',");
  assert.notEqual(deleteMapAt, -1);
  assert.match(mapScreen.slice(Math.max(0, deleteMapAt - 300), deleteMapAt), /\{canDeleteStructures && \(/);

  // The confirmation step in front of deletion is preserved.
  assert.match(mapScreen, /'confirm-delete'/);
});

console.log(`\n${passed} passed`);
