// Unit tests for the QR payload URL builder.
//
// Dependency-free — run with:  node src/config/publicUrl.test.mjs
//
// Under plain Node `import.meta.env` is undefined and there is no `window`,
// so getPublicFrontendUrl() returns '' and every test here passes the base
// explicitly. That is deliberate: it proves the builder is a pure function
// of (code, baseUrl) and never reaches for ambient state.

import assert from 'node:assert/strict';
import test from 'node:test';

import {
  LOCATION_CODE_QUERY_PARAM,
  PUBLIC_FRONTEND_URL_ENV_KEY,
  buildLocationCodeUrl,
  getPublicFrontendUrl,
} from './publicUrl.js';

const PROD = 'https://example-distribution.cloudfront.example';

// ── 1. The QR payload is a URL, not a bare code ──────────────────────────

test('the payload is an absolute https URL, never the bare code', () => {
  const url = buildLocationCodeUrl('2B8RLYRP', PROD);

  assert.notEqual(url, '2B8RLYRP');
  assert.ok(url.startsWith('https://'), url);

  // Parseable as a real URL — the whole point of encoding one.
  const parsed = new URL(url);
  assert.equal(parsed.protocol, 'https:');
});

test('the payload is the ROOT query-parameter form, not a deep route', () => {
  const parsed = new URL(buildLocationCodeUrl('2B8RLYRP', PROD));

  assert.equal(parsed.pathname, '/');
  assert.doesNotMatch(parsed.pathname, /scan/);
});

// ── 2. The correct LocationCode is included ──────────────────────────────

test('the exact LocationCode is carried in the locationCode parameter', () => {
  const parsed = new URL(buildLocationCodeUrl('2B8RLYRP', PROD));

  assert.equal(parsed.searchParams.get('locationCode'), '2B8RLYRP');
  assert.equal(
    parsed.searchParams.get(LOCATION_CODE_QUERY_PARAM),
    '2B8RLYRP',
  );
});

test('the full production shape is exactly {base}/?locationCode={CODE}', () => {
  assert.equal(
    buildLocationCodeUrl('2B8RLYRP', PROD),
    `${PROD}/?locationCode=2B8RLYRP`,
  );
});

test('the code is passed through verbatim — never rewritten or regenerated', () => {
  // Every character of the real alphabet (A-Z minus I/O, 2-9) survives.
  for (const code of ['ABCDEFGH', 'JKLMNPQR', 'STUVWXYZ', '23456789']) {
    const parsed = new URL(buildLocationCodeUrl(code, PROD));
    assert.equal(parsed.searchParams.get('locationCode'), code);
  }
});

test('case is preserved — the resolve endpoint matches codes exactly', () => {
  const parsed = new URL(buildLocationCodeUrl('AbCdEfGh', PROD));
  assert.equal(parsed.searchParams.get('locationCode'), 'AbCdEfGh');
});

// ── 3. Robust construction, not string concatenation ─────────────────────

test('a trailing slash on the base never produces a doubled slash', () => {
  assert.equal(
    buildLocationCodeUrl('2B8RLYRP', `${PROD}/`),
    `${PROD}/?locationCode=2B8RLYRP`,
  );
  assert.doesNotMatch(
    buildLocationCodeUrl('2B8RLYRP', `${PROD}/`).replace('https://', ''),
    /\/\//,
  );
});

test('a stray path or query on the base is normalised back to the root form', () => {
  assert.equal(
    buildLocationCodeUrl('2B8RLYRP', `${PROD}/screen/01?x=1#frag`),
    `${PROD}/?locationCode=2B8RLYRP`,
  );
});

test('a code needing percent-encoding is encoded, not concatenated raw', () => {
  const url = buildLocationCodeUrl('A B&C', PROD);

  assert.doesNotMatch(url, / /);
  assert.equal(new URL(url).searchParams.get('locationCode'), 'A B&C');
});

test('surrounding whitespace on the code and base is trimmed', () => {
  assert.equal(
    buildLocationCodeUrl('  2B8RLYRP  ', `  ${PROD}  `),
    `${PROD}/?locationCode=2B8RLYRP`,
  );
});

// ── 4. Safe degradation — never a plausible-looking broken QR ────────────

test('a missing code or base yields no URL at all', () => {
  assert.equal(buildLocationCodeUrl('', PROD), '');
  assert.equal(buildLocationCodeUrl('   ', PROD), '');
  assert.equal(buildLocationCodeUrl(null, PROD), '');
  assert.equal(buildLocationCodeUrl(undefined, PROD), '');
  assert.equal(buildLocationCodeUrl('2B8RLYRP', ''), '');
  assert.equal(buildLocationCodeUrl('2B8RLYRP', null), '');
});

test('an unparseable base yields no URL rather than a malformed one', () => {
  assert.equal(buildLocationCodeUrl('2B8RLYRP', 'not a url'), '');
  assert.equal(buildLocationCodeUrl('2B8RLYRP', '///'), '');
});

test('a bare code is never a fallback payload', () => {
  // If the base is unusable the builder returns '' and the caller shows its
  // error state — it must never quietly fall back to encoding "2B8RLYRP",
  // which would look like a working QR but open nothing.
  assert.notEqual(buildLocationCodeUrl('2B8RLYRP', ''), '2B8RLYRP');
  assert.notEqual(buildLocationCodeUrl('2B8RLYRP', 'not a url'), '2B8RLYRP');
});

// ── 5. Configuration contract ────────────────────────────────────────────

test('the env key is the documented VITE_ convention', () => {
  assert.equal(PUBLIC_FRONTEND_URL_ENV_KEY, 'VITE_PUBLIC_FRONTEND_URL');
});

test('the query parameter name is locationCode', () => {
  assert.equal(LOCATION_CODE_QUERY_PARAM, 'locationCode');
});

test('with no env and no window, the origin resolves to empty, not a guess', () => {
  assert.equal(getPublicFrontendUrl(), '');
});

test('window.location.origin is used when no env value is configured', () => {
  // Simulate a browser with no VITE_PUBLIC_FRONTEND_URL set.
  globalThis.window = { location: { origin: 'https://served-from.example' } };

  try {
    assert.equal(getPublicFrontendUrl(), 'https://served-from.example');
    assert.equal(
      buildLocationCodeUrl('2B8RLYRP'),
      'https://served-from.example/?locationCode=2B8RLYRP',
    );
  } finally {
    delete globalThis.window;
  }
});
