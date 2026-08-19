// QuickRoute QR URL flow — source-text contract tests.
//
// Dependency-free — run with:  node src/screens/locationCodeUrlFlow.test.mjs
//
// These assert on the wiring that the unit tests in src/config/publicUrl.test.mjs
// cannot reach: which prop the QR is rendered from, that the root redirect
// forwards the query string, that BOTH entry paths funnel through one
// resolve function, and — most importantly — that a scanned code sets the
// START position and never the destination.
//
// Companion file: locationCodeFlow.test.mjs, which still passes unchanged and
// is itself the regression proof that manual entry behaves exactly as before.

import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const read = (relative) => readFileSync(resolve(here, relative), 'utf8');

const barcodeSource = read('./BarcodeEntryScreen.jsx');
const appSource = read('./../App.jsx');
const adminCodesSource = read('./AdminLocationCodesScreen.jsx');
const publicUrlSource = read('./../config/publicUrl.js');
const destSource = read('./DestinationSelectionScreen.jsx');
const indoorSource = read('./IndoorNavigationScreen.jsx');
const locationScanSource = read('./../utils/locationScan.js');

// Assertions about the ABSENCE of a token must not be defeated by the word
// appearing in an explanatory comment — same technique the users & access
// contract tests use.
const stripComments = (source) =>
  source
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/^\s*\/\/.*$/gm, '');

const barcodeCode = stripComments(barcodeSource);
const adminCodesCode = stripComments(adminCodesSource);
const publicUrlCode = stripComments(publicUrlSource);
const appCode = stripComments(appSource);

// ── 1. The QR payload is a URL ───────────────────────────────────────────

test('the QR is generated from the URL builder, not the raw code', () => {
  assert.match(
    adminCodesSource,
    /import \{ buildLocationCodeUrl \} from '\.\.\/config\/publicUrl'/,
  );
  assert.match(adminCodesCode, /buildLocationCodeUrl\(code\)/);
  // The payload handed to the QR library is the built URL.
  assert.match(adminCodesCode, /QRCode\.toDataURL\(payload,/);
  // ...and never the bare code again.
  assert.doesNotMatch(adminCodesCode, /QRCode\.toDataURL\(\s*code\b/);
  assert.doesNotMatch(adminCodesCode, /QRCode\.toDataURL\(\s*entry\.code/);
});

// ── 2. The correct LocationCode is included, and stays readable ──────────

test('QrPreview is passed the real LocationCode from the row', () => {
  assert.match(adminCodesCode, /<QrPreview code=\{entry\.code\} \/>/);
});

test('the visible caption under the QR is still the bare LocationCode', () => {
  // The <div> immediately under the <img> renders {code}, not the URL, so a
  // printed label can still be typed by hand on the start screen.
  assert.match(
    adminCodesCode,
    /letterSpacing: 1 \}\}>\{code\}<\/div>/,
  );
  assert.doesNotMatch(adminCodesCode, /letterSpacing: 1 \}\}>\{payload\}/);
});

// ── 3. Configuration — no hard-coded production hostname in src/ ─────────

test('the production hostname is never hard-coded in the URL builder', () => {
  assert.doesNotMatch(publicUrlCode, /cloudfront/i);
  assert.doesNotMatch(publicUrlCode, /dy18iemulrjcj/);
});

test('the URL builder reads the VITE_ env convention with a window fallback', () => {
  assert.match(publicUrlCode, /import\.meta\.env\?\.VITE_PUBLIC_FRONTEND_URL/);
  assert.match(publicUrlCode, /window\.location\?\.origin/);
});

test('the URL is assembled with URL/URLSearchParams, not concatenation', () => {
  assert.match(publicUrlCode, /new URL\(/);
  assert.match(publicUrlCode, /searchParams\.set\(/);
  // No template-literal splicing of a base and a code.
  assert.doesNotMatch(publicUrlCode, /`\$\{[^}]*base[^}]*\}\/\?locationCode=/i);
});

// ── 4. The root redirect preserves the query string ──────────────────────

test('"/" redirects to the start screen carrying search and hash through', () => {
  assert.match(appCode, /const PreserveQueryRedirect = \(\{ to \}\) => \{/);
  assert.match(appCode, /const \{ search, hash \} = useLocation\(\)/);
  assert.match(
    appCode,
    /<Navigate to=\{\{ pathname: to, search, hash \}\} replace \/>/,
  );
  assert.match(
    appCode,
    /<Route\s*path=\{ROUTES\.root\}\s*element=\{<PreserveQueryRedirect to=\{ROUTES\.start\} \/>\}\s*\/>/,
  );

  // A bare string target drops the query string — no route may use one.
  assert.doesNotMatch(appCode, /<Navigate to="\//);
});

test('no second navigation system was introduced for scanning', () => {
  // The root query-parameter form only — no /scan route, no new screen.
  assert.doesNotMatch(appCode, /path="\/scan/);
  assert.doesNotMatch(appCode, /ScanScreen/);
});

// ── 5. One shared resolve path for manual entry and ?locationCode= ───────

test('a single resolveAndContinue function serves both entry paths', () => {
  assert.match(barcodeCode, /const resolveAndContinue = useCallback\(async \(rawCode\) => \{/);

  // A. manual entry goes through it
  assert.match(barcodeCode, /const handleGo = \(\) => resolveAndContinue\(barcode\)/);

  // B. the URL parameter goes through the same function
  assert.match(barcodeCode, /resolveAndContinue\(urlCode\)/);
});

test('LocationCode resolution is not duplicated', () => {
  // Exactly one resolve call, one persisted start record, one navigation.
  assert.equal(
    (barcodeCode.match(/await resolveLocationCode\(/g) || []).length,
    1,
  );
  assert.equal(
    (barcodeCode.match(/localStorage\.setItem\(/g) || []).length,
    1,
  );
  assert.equal(
    (barcodeCode.match(/navigate\(ROUTES\.destinations,/g) || []).length,
    1,
  );
});

test('the URL parameter name matches the one the QR encodes', () => {
  assert.match(
    barcodeSource,
    /import \{ LOCATION_CODE_QUERY_PARAM \} from '\.\.\/config\/publicUrl'/,
  );
  assert.match(
    barcodeCode,
    /searchParams\.get\(LOCATION_CODE_QUERY_PARAM\)/,
  );
  // Never a second, hand-spelled literal that could drift.
  assert.doesNotMatch(barcodeCode, /get\('locationCode'\)/);
});

test('the mount auto-resolution is guarded against StrictMode double effects', () => {
  assert.match(barcodeCode, /const autoResolvedCodeRef = useRef\(null\)/);
  assert.match(barcodeCode, /if \(autoResolvedCodeRef\.current === urlCode\) return;/);
  assert.match(barcodeCode, /autoResolvedCodeRef\.current = urlCode;/);

  // The guard is set BEFORE the resolve is kicked off, otherwise the second
  // StrictMode invocation would slip past it.
  const guardAt = barcodeCode.indexOf('autoResolvedCodeRef.current = urlCode;');
  const callAt = barcodeCode.indexOf('resolveAndContinue(urlCode);');
  assert.ok(guardAt > -1 && callAt > -1);
  assert.ok(guardAt < callAt, 'ref must be claimed before resolving');
});

test('the auto-resolve effect writes no state synchronously', () => {
  // Deferred by a microtask — react-hooks/set-state-in-effect.
  assert.match(barcodeCode, /Promise\.resolve\(\)\.then\(\(\) => \{\s*resolveAndContinue\(urlCode\);/);
});

test('the input is seeded from the URL without a setState-in-effect', () => {
  assert.match(barcodeCode, /useState\(urlCode\)/);
  assert.doesNotMatch(barcodeCode, /useEffect\([^)]*setBarcode\(urlCode\)/);
});

// ── 6. The scanned point is the START, never the destination ─────────────

test('a resolved code is persisted only as the start location', () => {
  assert.match(barcodeCode, /START_LOCATION_KEY,/);
  assert.match(barcodeCode, /routePointId: resolved\.route_point_id/);
  assert.equal(START_KEY_COUNT(), 1);

  // Nothing in the entry screen ever sets a destination. Navigating TO the
  // destination-selection screen is the only mention of the word, and it is
  // a route constant, never a destination value written anywhere.
  assert.doesNotMatch(barcodeCode, /destination:/i);
  assert.doesNotMatch(barcodeCode, /setDestination/i);
  assert.doesNotMatch(barcodeCode, /roomId/);
  assert.equal(
    (barcodeCode.match(/destination/gi) || []).length,
    1,
    'the only occurrence must be the ROUTES.destinations navigation target',
  );
  assert.match(barcodeCode, /navigate\(ROUTES\.destinations,/);
});

function START_KEY_COUNT() {
  return (barcodeCode.match(/const START_LOCATION_KEY = 'quickroute_start_location'/g) || [])
    .length;
}

test('the destination is still chosen by the user on the next screen afterwards', () => {
  // The entry screen hands over to Destination Selection, which loads the
  // building's rooms for the user to pick from — unchanged.
  assert.match(barcodeCode, /navigate\(ROUTES\.destinations,/);
  // The filter argument is now followed by an options argument carrying the
  // AbortController signal, so this pins BOTH halves of the contract: the
  // call is scoped to a building id, and that id comes from the current
  // building rather than from anywhere else.
  assert.match(destSource, /getRooms\(\s*\{ building_id: buildingId \}/);
  assert.match(destSource, /const buildingId = building\?\.id \?\? null;/);
  assert.doesNotMatch(destSource, /getRooms\(\)/);
  assert.doesNotMatch(destSource, /getRooms\(\{\}\)/);
  assert.match(destSource, /START_LOCATION_KEY/);
});

test('the start record shape is unchanged from before the URL flow', () => {
  for (const field of [
    /routePointId: resolved\.route_point_id/,
    /mapId: resolved\.map_id/,
    /mapGroupId: resolved\.map_group_id \?\? null/,
    /floor: resolved\.floor \?\? null/,
    /buildingId: resolved\.building_id/,
    /code: resolved\.code/,
    /label: resolved\.label \?\? null/,
  ]) {
    assert.match(barcodeCode, field);
  }
});

// ── 7. Invalid codes are handled safely ──────────────────────────────────

test('an unresolvable URL code lands on the existing invalid-code message', () => {
  assert.match(barcodeCode, /setError\(t\.invalid\)/);
  assert.match(
    barcodeSource,
    /invalid:\s*'Invalid or inactive barcode\. Please try again\.'/,
  );
  // One catch, shared by both paths — no separate URL error handling.
  assert.equal((barcodeCode.match(/setError\(t\.invalid\)/g) || []).length, 1);
});

test('a code with no building still shows the specific honest error', () => {
  assert.match(barcodeCode, /if \(!resolved\?\.building_id\)/);
  assert.match(barcodeCode, /setError\(t\.noBuilding\)/);
});

test('an empty ?locationCode= does not auto-resolve or error on arrival', () => {
  assert.match(barcodeCode, /if \(!urlCode\) return;/);
});

// ── 8. Manual entry and downstream navigation are untouched ──────────────

test('manual entry keeps its input, Enter key and Go button wiring', () => {
  assert.match(barcodeCode, /onChange=\{\(e\) => \{ setBarcode\(e\.target\.value\)/);
  assert.match(barcodeCode, /e\.key === 'Enter' && !isResolving\) handleGo\(\)/);
  assert.match(barcodeCode, /onClick=\{handleGo\}/);
  assert.match(barcodeCode, /setError\(t\.required\)/);
});

test('the backend resolve endpoint call is unchanged', () => {
  const apiSource = read('./../api/locationCodesApi.js');

  assert.match(
    apiSource,
    /\/api\/location-codes\/resolve\/\$\{encodeURIComponent\(code\)\}/,
  );
});

test('mid-journey rescan / relocation logic is untouched', () => {
  // Still the same classifier, the same storage key, the same start-only
  // semantics — this pass changed nothing in the in-journey scan path.
  assert.match(indoorSource, /classifyScannedLocation\(\{/);
  assert.match(indoorSource, /buildStartLocationRecord\(resolved\)/);
  assert.match(indoorSource, /localStorage\.setItem\(START_LOCATION_KEY/);
  assert.match(locationScanSource, /export const START_LOCATION_KEY = 'quickroute_start_location'/);
});

test('no LocationCode is created, mutated or duplicated by the QR change', () => {
  // The admin screen renders QRs from existing rows only. Nothing in the QR
  // path calls a create/generate/update endpoint.
  assert.doesNotMatch(publicUrlCode, /createLocationCode|generateLocationCode|updateLocationCode/);

  // And the URL builder never invents a code — it only formats the one it
  // is given (proved exhaustively in src/config/publicUrl.test.mjs).
  assert.doesNotMatch(publicUrlCode, /Math\.random|crypto\.|secrets/);

  // The entry screen only ever READS a code.
  assert.doesNotMatch(barcodeCode, /createLocationCode|generateLocationCode|updateLocationCode/);
});
