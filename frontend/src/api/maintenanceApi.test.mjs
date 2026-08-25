// Plain-Node tests for maintenanceApi.js + its use of the shared
// apiRequest() helper (api.js) — verifies the "Initialize Project Data"
// request actually goes through the same authenticated request mechanism
// as every other admin call (attaches the JWT from quickroute_token,
// never needs a manually copied token) and that 401/403 are distinguishable
// by the caller. No jest/vitest in this repo, so this runs directly via
// `node maintenanceApi.test.mjs`, polyfilling the two browser globals
// (localStorage, fetch) that api.js/maintenanceApi.js rely on.

import assert from 'node:assert/strict';

// ── Minimal localStorage polyfill ───────────────────────────────────────────
// api.js reads/writes localStorage directly (not via React), so it needs a
// real global here — Node has no DOM. A tiny Map-backed implementation is
// enough to exercise the real getStoredToken()/clearStoredAuth() code paths.
class FakeLocalStorage {
  constructor() {
    this._store = new Map();
  }
  getItem(key) {
    return this._store.has(key) ? this._store.get(key) : null;
  }
  setItem(key, value) {
    this._store.set(key, String(value));
  }
  removeItem(key) {
    this._store.delete(key);
  }
}

globalThis.localStorage = new FakeLocalStorage();

// ── fetch mock ───────────────────────────────────────────────────────────
// Records every call so tests can assert on method/URL/headers, and
// replays a queued response so each test controls what "the backend" says.
const fetchCalls = [];
let nextResponse = null;

globalThis.fetch = async (url, options) => {
  fetchCalls.push({ url, options });
  const response = nextResponse;
  nextResponse = null;
  return response;
};

function queueJsonResponse(status, body) {
  nextResponse = {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  };
}

const { getStoredToken } = await import('./api.js');
const { runBackfillBuildings } = await import('./maintenanceApi.js');

let passed = 0;
async function test(name, fn) {
  try {
    await fn();
    passed += 1;
    console.log(`PASS: ${name}`);
  } catch (err) {
    console.error(`FAIL: ${name}`);
    console.error(err);
    process.exitCode = 1;
  }
}

await test('runBackfillBuildings: POSTs to the maintenance endpoint via the shared helper', async () => {
  globalThis.localStorage.setItem('quickroute_token', 'test-jwt-token');
  queueJsonResponse(200, {
    maps_updated: 1,
    points_updated: 17,
    buildings_created_or_reused: { b1: 'QuickRoute Mall' },
    rooms_with_missing_building: 0,
    location_codes_inconsistent: 0,
  });

  fetchCalls.length = 0;
  const result = await runBackfillBuildings();

  assert.equal(fetchCalls.length, 1);
  const call = fetchCalls[0];
  assert.ok(call.url.endsWith('/api/maintenance/backfill-buildings'));
  assert.equal(call.options.method, 'POST');

  // The key requirement: the JWT under quickroute_token is attached
  // automatically — nothing in this call site set the header itself.
  assert.equal(call.options.headers.Authorization, 'Bearer test-jwt-token');

  assert.equal(result.maps_updated, 1);
  assert.equal(result.points_updated, 17);
});

await test('runBackfillBuildings: 401 throws with status attached and clears the stored token', async () => {
  globalThis.localStorage.setItem('quickroute_token', 'expired-token');
  queueJsonResponse(401, { detail: 'Invalid or expired access token' });

  await assert.rejects(
    () => runBackfillBuildings(),
    (error) => {
      assert.equal(error.status, 401);
      assert.equal(error.message, 'Invalid or expired access token');
      return true;
    }
  );

  // apiRequest() clears the session on 401 so a stale token isn't reused.
  assert.equal(getStoredToken(), null);
});

await test('runBackfillBuildings: 403 throws with status attached and does NOT clear the token', async () => {
  globalThis.localStorage.setItem('quickroute_token', 'valid-but-wrong-role-token');
  queueJsonResponse(403, {
    detail: 'You do not have permission to perform this action',
  });

  await assert.rejects(
    () => runBackfillBuildings(),
    (error) => {
      assert.equal(error.status, 403);
      assert.equal(
        error.message,
        'You do not have permission to perform this action'
      );
      return true;
    }
  );

  // A 403 means "wrong role", not "bad session" — the token is still valid
  // and should not be thrown away.
  assert.equal(getStoredToken(), 'valid-but-wrong-role-token');
});

console.log(`\n${passed} passed`);
