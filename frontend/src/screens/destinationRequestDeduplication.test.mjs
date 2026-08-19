// DestinationSelectionScreen request-deduplication contract.
//
// Dependency-free — run with:
//   node src/screens/destinationRequestDeduplication.test.mjs
//
// Background: GET /api/rooms?building_id=... was being issued several times
// for one visit to this screen. Three causes, all in this file's effect:
//
//   1. React StrictMode double-invokes effects in development, and the
//      `cancelled` flag only suppressed the state write, never the request.
//   2. `focus` and `visibilitychange` were both registered on the same
//      handler, so one tab switch fired two refetches.
//   3. Nothing prevented a re-entrant fetch while one was still in flight.
//
// The behavioural proof lives in the browser check run alongside this
// suite; these assertions pin the structure so the fix cannot be
// accidentally unpicked, and confirm the surrounding contracts (the QR
// start-location read, the building-scoped fetch) are untouched.

import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const read = (relative) => readFileSync(resolve(here, relative), 'utf8');

const screenSource = read('./DestinationSelectionScreen.jsx');
const roomsApiSource = read('./../api/roomsApi.js');
const apiSource = read('./../api/api.js');
const mainSource = read('./../main.jsx');

const stripComments = (source) =>
  source
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/^\s*\/\/.*$/gm, '');

const screen = stripComments(screenSource);
const roomsApi = stripComments(roomsApiSource);

const countOf = (source, pattern) => (source.match(pattern) || []).length;

// ── 1. Concurrent duplicate requests are coalesced ───────────────────────

test('an in-flight rooms request is tracked in a ref', () => {
  assert.match(screen, /const roomsRequestRef = useRef\(null\)/);
});

test('a second caller reuses the in-flight promise instead of refetching', () => {
  assert.match(screen, /const requestRooms = useCallback\(\(buildingId\) => \{/);
  assert.match(screen, /if \(existing\.key === buildingId\) return existing\.promise;/);
});

test('there is exactly one getRooms call site in the screen', () => {
  // Every trigger funnels through requestRooms(); a second literal call
  // site would be a path that bypasses the coalescing.
  assert.equal(countOf(screen, /getRooms\(/g), 1);
});

test('the in-flight slot is released on success and on failure', () => {
  assert.match(screen, /\.finally\(\(\) => \{\s*if \(roomsRequestRef\.current === entry\) roomsRequestRef\.current = null;/);
  // The .catch(() => {}) before it is what makes the finally run for a
  // rejection without producing an unhandled rejection.
  assert.match(screen, /\.catch\(\(\) => \{\}\)\s*\.finally\(/);
});

// ── 2. AbortController, wired through the existing API helper ────────────

test('a superseded building request is aborted, not left to race', () => {
  assert.match(screen, /const controller = new AbortController\(\)/);
  assert.match(screen, /existing\.controller\.abort\(\)/);
});

test('the abort signal reaches fetch through the existing helper', () => {
  // getRooms forwards an options object...
  assert.match(roomsApi, /export function getRooms\(filters = \{\}, options = \{\}\)/);
  assert.match(roomsApi, /apiRequest\(`\/api\/rooms\$\{query \? `\?\$\{query\}` : ""\}`, options\)/);
  // ...apiRequest spreads it into fetch, which is what makes `signal` work.
  assert.match(apiSource, /\.\.\.options,/);
  // ...and the screen passes one.
  assert.match(screen, /\{ signal: controller\.signal \}/);
});

test('the options parameter is optional, so other call sites are unaffected', () => {
  assert.match(roomsApi, /options = \{\}/);
});

test('an aborted request never surfaces as a load error', () => {
  assert.match(screen, /if \(cancelled \|\| err\?\.name === 'AbortError'\) return;/);
});

// ── 3. One refresh per return, not two ───────────────────────────────────

test('leaving arms a flag that the first return event consumes', () => {
  assert.match(screen, /const wasAwayRef = useRef\(false\)/);
  assert.match(screen, /const markAway = \(\) => \{\s*wasAwayRef\.current = true;/);
  assert.match(screen, /if \(!wasAwayRef\.current\) return;/);
  assert.match(screen, /wasAwayRef\.current = false;\s*loadRooms\(\);/);
});

test('the flag is consumed BEFORE the refresh, so the second event is a no-op', () => {
  const handlerBody = screen.slice(
    screen.indexOf('const handleReturn = ()'),
    screen.indexOf("window.addEventListener('blur'"),
  );

  const consumeAt = handlerBody.indexOf('wasAwayRef.current = false;');
  const loadAt = handlerBody.indexOf('loadRooms();');

  assert.ok(consumeAt > -1, 'handler must clear the flag');
  assert.ok(loadAt > -1, 'handler must refresh');
  assert.ok(
    consumeAt < loadAt,
    'the flag must be cleared before loadRooms() runs, otherwise a second '
      + 'event arriving during the fetch would refresh again',
  );
});

test('a hidden document arms rather than refreshes', () => {
  assert.match(
    screen,
    /if \(document\.visibilityState === 'hidden'\) \{\s*markAway\(\);\s*return;\s*\}/,
  );
});

test('focus and visibilitychange share one guarded handler', () => {
  assert.match(screen, /window\.addEventListener\('focus', handleReturn\)/);
  assert.match(screen, /document\.addEventListener\('visibilitychange', handleReturn\)/);
  // The old shape called loadRooms() directly from the shared handler with
  // no guard — that is what produced two refetches per return.
  assert.doesNotMatch(
    screen,
    /const handleFocusOrVisible = \(\) => \{[^}]*loadRooms\(\);\s*\}/,
  );
});

test('every listener added is removed again', () => {
  for (const [target, event] of [
    ['window', 'blur'],
    ['window', 'focus'],
    ['document', 'visibilitychange'],
  ]) {
    assert.match(screen, new RegExp(`${target}\\.addEventListener\\('${event}'`));
    assert.match(screen, new RegExp(`${target}\\.removeEventListener\\('${event}'`));
  }

  assert.equal(
    countOf(screen, /addEventListener\(/g),
    countOf(screen, /removeEventListener\(/g),
  );
});

// ── 4. Refresh-on-return is preserved, StrictMode is preserved ───────────

test('returning to the tab still refreshes the navigability snapshot', () => {
  // The whole point of the listeners: a destination that became navigable
  // while this screen sat in a background tab must not stay disabled.
  assert.match(screen, /window\.addEventListener\('focus'/);
  assert.match(screen, /document\.addEventListener\('visibilitychange'/);
  assert.match(screen, /loadRooms\(\);/);
});

test('React StrictMode is still enabled', () => {
  assert.match(mainSource, /<StrictMode>/);
  assert.match(mainSource, /import \{ StrictMode \} from 'react'/);
});

test('the effect still keys on the building id', () => {
  assert.match(screen, /\}, \[building\?\.id, requestRooms\]\)/);
});

// ── 5. Surrounding behaviour untouched ───────────────────────────────────

test('rooms are still fetched scoped to exactly one building', () => {
  assert.match(screen, /getRooms\(\s*\{ building_id: buildingId \}/);
  assert.doesNotMatch(screen, /getRooms\(\)/);
  assert.doesNotMatch(screen, /getRooms\(\{\}\)/);
});

test('inactive destinations are still filtered out', () => {
  assert.match(screen, /\.filter\(\(r\) => r\.isActive !== false\)/);
});

test('the QR start-location contract is untouched', () => {
  assert.match(screen, /const START_LOCATION_KEY = 'quickroute_start_location'/);
  assert.match(screen, /localStorage\.getItem\(START_LOCATION_KEY\)/);
  // This screen only ever READS the start location — it never writes one,
  // and the destination is still chosen by the user here.
  assert.doesNotMatch(screen, /localStorage\.setItem/);
  assert.match(screen, /navigate\(ROUTES\.navigation, \{ state: \{ building, destination: room, lang \} \}\)/);
});

test('navigability is still taken from the backend verdict, never re-derived', () => {
  assert.match(screen, /if \(!room\.isNavigable\) return;/);
  assert.match(screen, /disabled=\{!room\.isNavigable\}/);
});
