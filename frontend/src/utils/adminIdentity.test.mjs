// Dependency-free Node tests for adminIdentity.js — the guarantee that no
// personal identity is ever hard-coded into the admin shell.
import assert from 'node:assert/strict';
import {
  resolveUserDisplayName,
  resolveUserInitial,
  resolveRoleLabel,
} from './adminIdentity.js';

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

const ROLE_LABELS = {
  super_admin: 'Super Admin',
  global_manager: 'Global Manager',
  building_manager: 'Building Manager',
};

test('identity comes from the authenticated user, and changes with the account', () => {
  const first = { full_name: 'Adyan Issa', email: 'adyan@example.com', role: 'super_admin' };
  const second = { full_name: 'Layal Zoubi', email: 'layal@example.com', role: 'global_manager' };
  const third = { full_name: 'Ahmad Nasser', email: 'ahmad@example.com', role: 'building_manager' };

  assert.equal(resolveUserDisplayName(first), 'Adyan Issa');
  assert.equal(resolveUserDisplayName(second), 'Layal Zoubi');
  assert.equal(resolveUserDisplayName(third), 'Ahmad Nasser');

  assert.equal(resolveUserInitial(first), 'A');
  assert.equal(resolveUserInitial(second), 'L');
  assert.equal(resolveUserInitial(third), 'A');

  assert.equal(resolveRoleLabel(first, ROLE_LABELS), 'Super Admin');
  assert.equal(resolveRoleLabel(second, ROLE_LABELS), 'Global Manager');
  assert.equal(resolveRoleLabel(third, ROLE_LABELS), 'Building Manager');
});

test('no name is ever invented when the account has none', () => {
  assert.equal(resolveUserDisplayName(null), '');
  assert.equal(resolveUserDisplayName({}), '');
  assert.equal(resolveUserDisplayName({ full_name: '   ' }), '');
  assert.equal(resolveUserInitial(null), '?');
  assert.equal(resolveUserInitial({}), '?');
});

test('a missing full_name falls back to the account, never to another person', () => {
  assert.equal(resolveUserDisplayName({ email: 'ops.team@hospital.org' }), 'ops.team');
  assert.equal(resolveUserDisplayName({ full_name: '', email: 'x@y.z' }), 'x');
  assert.equal(resolveUserInitial({ email: 'ops@x.io' }), 'O');
});

test('RTL and multi-byte names yield one whole initial character', () => {
  assert.equal(resolveUserInitial({ full_name: 'ליאל כהן' }), 'ל');
  assert.equal(resolveUserInitial({ full_name: 'عدنان عيسى' }), 'ع');
  assert.equal(resolveUserInitial({ full_name: '🙂 test' }), '🙂');
});

test('role label falls back to the raw backend role, never to a guessed level', () => {
  assert.equal(resolveRoleLabel({ role: 'regular_user' }, ROLE_LABELS), 'regular_user');
  assert.equal(resolveRoleLabel({ role: 'future_role' }, ROLE_LABELS), 'future_role');
  assert.equal(resolveRoleLabel({}, ROLE_LABELS), '');
  assert.equal(resolveRoleLabel(null, ROLE_LABELS), '');
});

console.log(`\n${passed} passed`);
