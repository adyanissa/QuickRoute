// Semantic routing contract.
//
// Dependency-free — run with:  node src/config/routes.test.mjs
//
// QuickRoute's public routes used to be opaque numbers (/screen/01 …
// /screen/18) scattered as bare strings across App.jsx, three auth guards,
// eleven screens and two helper modules. They are now semantic paths defined
// once, here.
//
// Two things must hold forever:
//
//   1. every legacy numeric path still resolves — QR labels, bookmarks and
//      shared links predate the rename and cannot be recalled, and
//   2. the redirect carries ?query and #hash through, because a scanned
//      QuickRoute QR arrives as /?locationCode=CODE and a redirect that
//      drops the query string silently loses the code.
//
// The behavioural proof (a real browser following each redirect) runs
// alongside this file; these assertions pin the data and the wiring.

import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';

import {
  ADMIN_DASHBOARD_ROUTE,
  END_USER_HOME_ROUTE,
  LEGACY_ROUTE_REDIRECTS,
  NOT_FOUND_REDIRECT,
  ROUTES,
} from './routes.js';

import {
  ADMIN_DASHBOARD_ROUTE as ROLE_ADMIN_ROUTE,
  END_USER_HOME_ROUTE as ROLE_HOME_ROUTE,
  resolvePostLoginRoute,
} from './../utils/roleRouting.js';

import { getPostAuthRedirectPath } from './../utils/invitationCodeFormHelpers.js';
import { ADMIN_ROUTES } from './../utils/adminNavigation.js';

const here = dirname(fileURLToPath(import.meta.url));
const read = (relative) => readFileSync(resolve(here, relative), 'utf8');

const appSource = read('./../App.jsx');

const stripComments = (source) =>
  source
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/^\s*\/\/.*$/gm, '')
    .replace(/\{\/\*[\s\S]*?\*\/\}/g, '');

const app = stripComments(appSource);

// The approved mapping, written out literally so a silent edit to
// config/routes.js cannot pass unnoticed.
const APPROVED_MAPPING = {
  '/screen/01': '/start',
  '/screen/02': '/login',
  '/screen/03': '/signup',
  '/screen/04': '/signup/account',
  '/screen/05': '/admin',
  '/screen/15': '/welcome',
  '/screen/16': '/buildings',
  '/screen/17': '/destinations',
  '/screen/18': '/navigation',
  '/map': '/navigation',
};

// ── 1. The canonical paths ───────────────────────────────────────────────

test('every canonical route is the approved semantic path', () => {
  assert.equal(ROUTES.root, '/');
  assert.equal(ROUTES.start, '/start');
  assert.equal(ROUTES.login, '/login');
  assert.equal(ROUTES.signup, '/signup');
  assert.equal(ROUTES.signupAccount, '/signup/account');
  assert.equal(ROUTES.welcome, '/welcome');
  assert.equal(ROUTES.buildings, '/buildings');
  assert.equal(ROUTES.destinations, '/destinations');
  assert.equal(ROUTES.navigation, '/navigation');
  assert.equal(ROUTES.adminOverview, '/admin');
});

test('no canonical route is a numeric screen path', () => {
  for (const [key, path] of Object.entries(ROUTES)) {
    assert.doesNotMatch(path, /^\/screen\//, `${key} -> ${path}`);
  }
});

test('canonical paths are unique', () => {
  const paths = Object.values(ROUTES);
  assert.equal(new Set(paths).size, paths.length);
});

test('every canonical route is declared in App.jsx', () => {
  for (const key of [
    'start', 'login', 'signup', 'signupAccount',
    'welcome', 'buildings', 'destinations', 'navigation',
  ]) {
    assert.match(
      app,
      new RegExp(`<Route path=\\{ROUTES\\.${key}\\}`),
      `ROUTES.${key} must have a <Route>`,
    );
  }

  // The admin overview is declared through ADMIN_ROUTES.overview, which is
  // ROUTES.adminOverview — one definition, reached two ways.
  assert.match(app, /<Route path=\{ADMIN_ROUTES\.overview\}/);
  assert.equal(ADMIN_ROUTES.overview, ROUTES.adminOverview);
});

// ── 2. Legacy redirects ──────────────────────────────────────────────────

test('the legacy map is exactly the approved mapping', () => {
  assert.deepEqual(LEGACY_ROUTE_REDIRECTS, APPROVED_MAPPING);
});

test('every legacy path redirects to a real canonical route', () => {
  const canonical = new Set(Object.values(ROUTES));

  for (const [legacy, target] of Object.entries(LEGACY_ROUTE_REDIRECTS)) {
    assert.ok(canonical.has(target), `${legacy} -> ${target} is not canonical`);
  }
});

test('/screen/18 and /map fold into the one navigation route', () => {
  assert.equal(LEGACY_ROUTE_REDIRECTS['/screen/18'], ROUTES.navigation);
  assert.equal(LEGACY_ROUTE_REDIRECTS['/map'], ROUTES.navigation);

  // ...and there is only ONE <Route> rendering the navigation screen.
  assert.equal(
    (app.match(/element=\{<IndoorNavigationScreen \/>\}/g) || []).length,
    1,
  );
});

test('App.jsx renders a redirect for every legacy path', () => {
  assert.match(app, /Object\.entries\(LEGACY_ROUTE_REDIRECTS\)\.map\(/);
  assert.match(app, /path=\{legacyPath\}/);
  assert.match(app, /element=\{<PreserveQueryRedirect to=\{target\} \/>\}/);
});

// ── 3. Query string and hash preservation ────────────────────────────────

test('the redirect component reads search and hash off the location', () => {
  assert.match(app, /const PreserveQueryRedirect = \(\{ to \}\) => \{/);
  assert.match(app, /const \{ search, hash \} = useLocation\(\)/);
  assert.match(app, /<Navigate to=\{\{ pathname: to, search, hash \}\} replace \/>/);
});

test('NO route anywhere uses a bare string redirect target', () => {
  // `<Navigate to="/x">` silently drops ?query and #hash — that is exactly
  // how a scanned ?locationCode= would be lost.
  assert.doesNotMatch(app, /<Navigate to="/);
});

test('every redirect is `replace`, so browser Back is not polluted', () => {
  const navigates = app.match(/<Navigate[^>]*>/g) || [];
  assert.ok(navigates.length > 0);

  for (const tag of navigates) {
    assert.match(tag, /replace/, tag);
  }
});

test('the catch-all preserves the query string too', () => {
  assert.match(
    app,
    /path="\*"\s*element=\{<PreserveQueryRedirect to=\{NOT_FOUND_REDIRECT\} \/>\}/,
  );
  assert.equal(NOT_FOUND_REDIRECT, ROUTES.start);

  // The old catch-all was a bare string and dropped the code.
  assert.doesNotMatch(app, /path="\*" element=\{<Navigate/);
});

test('the QR entry point still lands on the screen that resolves codes', () => {
  // /?locationCode=CODE -> /start?locationCode=CODE -> BarcodeEntryScreen
  assert.match(
    app,
    /<Route\s*path=\{ROUTES\.root\}\s*element=\{<PreserveQueryRedirect to=\{ROUTES\.start\} \/>\}\s*\/>/,
  );
  assert.match(app, /<Route path=\{ROUTES\.start\} element=\{<BarcodeEntryScreen \/>\} \/>/);

  // ...and the legacy printed-label path reaches the same screen.
  assert.equal(LEGACY_ROUTE_REDIRECTS['/screen/01'], ROUTES.start);
});

// ── 4. Nothing internal depends on a legacy redirect ─────────────────────

test('App.jsx contains no hard-coded numeric route string', () => {
  assert.doesNotMatch(app, /'\/screen\/\d/);
  assert.doesNotMatch(app, /"\/screen\/\d/);
});

// ── 5. The post-auth rule has exactly one definition ─────────────────────

test('roleRouting re-exports the shared constants rather than its own', () => {
  assert.equal(ROLE_ADMIN_ROUTE, ADMIN_DASHBOARD_ROUTE);
  assert.equal(ROLE_HOME_ROUTE, END_USER_HOME_ROUTE);
});

test('both post-auth helpers agree, because they share one source', () => {
  for (const role of ['super_admin', 'global_manager', 'building_manager']) {
    assert.equal(getPostAuthRedirectPath(role), ADMIN_DASHBOARD_ROUTE);
  }

  assert.equal(getPostAuthRedirectPath('regular_user'), END_USER_HOME_ROUTE);

  // resolvePostLoginRoute keeps its own extra rule (a building_manager with
  // exactly one map goes straight to that map) — unchanged by this pass.
  assert.equal(resolvePostLoginRoute({ role: 'super_admin' }), ADMIN_DASHBOARD_ROUTE);
  assert.equal(resolvePostLoginRoute({ role: 'regular_user' }), END_USER_HOME_ROUTE);
  assert.equal(
    resolvePostLoginRoute({ role: 'building_manager', map_ids: ['m1'] }),
    '/admin/map?mapId=m1',
  );
});

test('the post-auth destinations are the semantic paths', () => {
  assert.equal(ADMIN_DASHBOARD_ROUTE, '/admin');
  assert.equal(END_USER_HOME_ROUTE, '/welcome');
});

// ── 6. The /admin parent-path hazard ─────────────────────────────────────

test('the admin overview does not swallow the admin routes beneath it', () => {
  // ROUTES.adminOverview is '/admin', and every other admin path lives
  // under it. Anything doing a prefix match would treat /admin/sites as
  // Overview. adminNavigation.test.mjs asserts the helper behaviour; this
  // asserts the shape that makes it a hazard, so the risk stays documented.
  for (const key of ['sites', 'mapManagement', 'users', 'invitations']) {
    assert.ok(
      ADMIN_ROUTES[key].startsWith(`${ROUTES.adminOverview}/`),
      `${key} is expected to live under the overview path`,
    );
    assert.notEqual(ADMIN_ROUTES[key], ROUTES.adminOverview);
  }
});
