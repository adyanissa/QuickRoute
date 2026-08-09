// RBAC/dashboard cleanup task (frontend completion), Section 2 —
// dependency-free Node tests for apiErrors.js (backend 403 -> localized
// message classification).
import assert from 'node:assert/strict';
import {
  isForbiddenError,
  isNotFoundError,
  isSessionExpiredError,
  resolveApiErrorMessage,
} from './apiErrors.js';

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

test('scenario 8: a 403 error is classified as forbidden', () => {
  const err = Object.assign(new Error('nope'), { status: 403 });
  assert.equal(isForbiddenError(err), true);
  assert.equal(isNotFoundError(err), false);
  assert.equal(isSessionExpiredError(err), false);
});

test('scenario 8: resolveApiErrorMessage picks the localized forbidden message for a 403', () => {
  const err = Object.assign(new Error('Forbidden'), { status: 403 });
  const messages = { forbidden: 'You do not have permission.', loadError: 'Failed to load.' };
  assert.equal(resolveApiErrorMessage(err, messages), 'You do not have permission.');
});

test('resolveApiErrorMessage falls back to loadError if forbidden key is missing', () => {
  const err = Object.assign(new Error('Forbidden'), { status: 403 });
  assert.equal(resolveApiErrorMessage(err, { loadError: 'Failed to load.' }), 'Failed to load.');
});

test('a 401 is classified as session-expired and uses the sessionExpired message', () => {
  const err = Object.assign(new Error('Unauthorized'), { status: 401 });
  assert.equal(isSessionExpiredError(err), true);
  assert.equal(
    resolveApiErrorMessage(err, { sessionExpired: 'Please log in again.' }),
    'Please log in again.',
  );
});

test('a 404 is classified as not-found and uses the notFound message', () => {
  const err = Object.assign(new Error('Missing'), { status: 404 });
  assert.equal(isNotFoundError(err), true);
  assert.equal(resolveApiErrorMessage(err, { notFound: 'Not found.' }), 'Not found.');
});

test('a plain 500/unknown error falls back to error.message', () => {
  const err = Object.assign(new Error('Server exploded'), { status: 500 });
  assert.equal(resolveApiErrorMessage(err, {}), 'Server exploded');
});

test('isForbiddenError/isNotFoundError/isSessionExpiredError never throw on null/undefined', () => {
  assert.equal(isForbiddenError(null), false);
  assert.equal(isNotFoundError(undefined), false);
  assert.equal(isSessionExpiredError(null), false);
});

console.log(`\n${passed} passed`);
