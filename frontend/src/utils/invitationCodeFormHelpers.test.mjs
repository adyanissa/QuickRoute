// Plain-Node tests for the Invitation Codes admin form + Sign Up flow
// helpers (frontend/src/utils/invitationCodeFormHelpers.js). Same
// pattern as the repo's other *.test.mjs files — no jest/vitest
// installed, run directly via `node invitationCodeFormHelpers.test.mjs`.
import assert from 'node:assert/strict';
import {
  getAllowedRoleOptions,
  requiresBuildingSelection,
  isSystemWideRole,
  resetScopeOnRoleChange,
  isCreateEnabled,
  buildCreateInvitationCodePayload,
  getStatusLabel,
  canRevoke,
  getCopyableCode,
  shouldLockEmailField,
  getInitialEmail,
  buildSignupPayload,
  getPostAuthRedirectPath,
} from './invitationCodeFormHelpers.js';

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

// ── 1. Allowed role options depend on creator role ─────────────────────

test('getAllowedRoleOptions: super_admin can create every role', () => {
  assert.deepEqual(getAllowedRoleOptions('super_admin'), [
    'super_admin',
    'global_manager',
    'building_manager',
    'regular_user',
  ]);
});

test('getAllowedRoleOptions: global_manager can only create building_manager/regular_user', () => {
  assert.deepEqual(getAllowedRoleOptions('global_manager'), ['building_manager', 'regular_user']);
});

test('getAllowedRoleOptions: building_manager and regular_user get no creatable roles', () => {
  assert.deepEqual(getAllowedRoleOptions('building_manager'), []);
  assert.deepEqual(getAllowedRoleOptions('regular_user'), []);
});

// ── 2. building_manager role requires building selection ───────────────

test('requiresBuildingSelection: true only for building_manager', () => {
  assert.equal(requiresBuildingSelection('building_manager'), true);
  assert.equal(requiresBuildingSelection('global_manager'), false);
  assert.equal(requiresBuildingSelection('regular_user'), false);
  assert.equal(requiresBuildingSelection('super_admin'), false);
});

test('isCreateEnabled: building_manager needs at least one building', () => {
  assert.equal(isCreateEnabled({ role: 'building_manager', buildingIds: [] }), false);
  assert.equal(isCreateEnabled({ role: 'building_manager', buildingIds: ['b1'] }), true);
});

test('isCreateEnabled: other roles do not require a building selection', () => {
  assert.equal(isCreateEnabled({ role: 'regular_user', buildingIds: [] }), true);
  assert.equal(isCreateEnabled({ role: 'global_manager', buildingIds: [] }), true);
});

// ── 3. super_admin role selects system-wide scope ───────────────────────

test('isSystemWideRole: true only for super_admin', () => {
  assert.equal(isSystemWideRole('super_admin'), true);
  assert.equal(isSystemWideRole('global_manager'), false);
});

test('resetScopeOnRoleChange: super_admin forces all_buildings=true with no individual selection', () => {
  const next = resetScopeOnRoleChange(
    { role: 'building_manager', allBuildings: false, buildingIds: ['b1'] },
    'super_admin'
  );
  assert.equal(next.role, 'super_admin');
  assert.equal(next.allBuildings, true);
  assert.deepEqual(next.buildingIds, []);
});

// ── 4. Changing role resets incompatible scope fields ───────────────────

test('resetScopeOnRoleChange: switching away from super_admin clears the forced all-buildings scope', () => {
  const next = resetScopeOnRoleChange(
    { role: 'super_admin', allBuildings: true, buildingIds: [] },
    'building_manager'
  );
  assert.equal(next.allBuildings, false);
  assert.deepEqual(next.buildingIds, []);
});

test('resetScopeOnRoleChange: switching between two non-super_admin roles still clears a stale building list', () => {
  const next = resetScopeOnRoleChange(
    { role: 'building_manager', allBuildings: false, buildingIds: ['b1', 'b2'] },
    'global_manager'
  );
  assert.deepEqual(next.buildingIds, []);
  assert.equal(next.role, 'global_manager');
});

// ── 5. Create request sends IDs, not display names ──────────────────────

test('buildCreateInvitationCodePayload: sends building IDs, never names', () => {
  const payload = buildCreateInvitationCodePayload({
    role: 'building_manager',
    allBuildings: false,
    buildingIds: ['64f0000000000000000000aa', '64f0000000000000000000bb'],
  });
  assert.deepEqual(payload.building_ids, ['64f0000000000000000000aa', '64f0000000000000000000bb']);
  assert.equal(payload.all_buildings, false);
  assert.equal(payload.role, 'building_manager');
});

test('buildCreateInvitationCodePayload: super_admin always forces all_buildings=true, empty building_ids', () => {
  const payload = buildCreateInvitationCodePayload({
    role: 'super_admin',
    allBuildings: false, // even if the form somehow disagrees
    buildingIds: ['should-be-dropped'],
  });
  assert.equal(payload.all_buildings, true);
  assert.deepEqual(payload.building_ids, []);
});

test('buildCreateInvitationCodePayload: intended email is trimmed and lowercased, omitted when blank', () => {
  const withEmail = buildCreateInvitationCodePayload({
    role: 'regular_user',
    buildingIds: [],
    intendedEmail: '  Someone@Example.com  ',
  });
  assert.equal(withEmail.intended_email, 'someone@example.com');

  const withoutEmail = buildCreateInvitationCodePayload({ role: 'regular_user', buildingIds: [] });
  assert.equal('intended_email' in withoutEmail, false);
});

// ── 6. Code result is copyable ───────────────────────────────────────────

test('getCopyableCode: returns the plain code string ready for the clipboard', () => {
  assert.equal(getCopyableCode({ code: 'QR-ABCD1234' }), 'QR-ABCD1234');
  assert.equal(getCopyableCode({}), '');
});

// ── 7. used/revoked/expired status displays correctly ───────────────────

test('getStatusLabel: maps every status to a distinct label', () => {
  assert.equal(getStatusLabel('active'), 'Active');
  assert.equal(getStatusLabel('used'), 'Used');
  assert.equal(getStatusLabel('expired'), 'Expired');
  assert.equal(getStatusLabel('revoked'), 'Revoked');
});

test('canRevoke: only an active, unused code can be revoked', () => {
  assert.equal(canRevoke({ status: 'active' }), true);
  assert.equal(canRevoke({ status: 'used' }), false);
  assert.equal(canRevoke({ status: 'expired' }), false);
  assert.equal(canRevoke({ status: 'revoked' }), false);
});

// ── 8. Signup cannot edit the role received from the code ───────────────

test('buildSignupPayload: never forwards a role/building field, even if present on the form', () => {
  const accountForm = {
    fullName: 'Jane Admin',
    email: 'jane@example.com',
    password: 'secret123',
    // A role/building field should never exist on this form in the first
    // place — but even if something upstream attached one, the payload
    // builder must not forward it.
    role: 'super_admin',
    buildingIds: ['sneaky-building'],
  };

  const payload = buildSignupPayload(accountForm, 'qr-code123');
  assert.deepEqual(Object.keys(payload).sort(), ['code', 'email', 'full_name', 'password']);
  assert.equal(payload.code, 'QR-CODE123');
});

// ── 9. Intended email is enforced ────────────────────────────────────────

test('shouldLockEmailField / getInitialEmail: locks and prefills when the code restricts an email', () => {
  const preview = { valid: true, intended_email: 'invited@example.com' };
  assert.equal(shouldLockEmailField(preview), true);
  assert.equal(getInitialEmail(preview), 'invited@example.com');
});

test('shouldLockEmailField: false when the code has no email restriction', () => {
  const preview = { valid: true };
  assert.equal(shouldLockEmailField(preview), false);
  assert.equal(getInitialEmail(preview), '');
});

// ── 10. Successful signup redirects by role ──────────────────────────────

test('getPostAuthRedirectPath: admin-tier roles go to the Admin Dashboard', () => {
  assert.equal(getPostAuthRedirectPath('super_admin'), '/screen/05');
  assert.equal(getPostAuthRedirectPath('global_manager'), '/screen/05');
  assert.equal(getPostAuthRedirectPath('building_manager'), '/screen/05');
});

test('getPostAuthRedirectPath: regular_user goes to the normal user flow', () => {
  assert.equal(getPostAuthRedirectPath('regular_user'), '/screen/15');
});

console.log(`\n${passed} passed`);
