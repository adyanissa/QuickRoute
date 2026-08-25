// The one place QuickRoute's frontend route paths are written down.
//
// Every route used to be a bare string repeated across App.jsx, three auth
// guards, eleven screens and two helper modules — including the post-auth
// "admin goes here, everyone else goes there" rule, which existed twice in
// two files that had to be kept in sync by hand. Importing from here means a
// path can be changed in one place and cannot silently diverge.
//
// Pure data — no React, no router, no import.meta — so plain Node can import
// it in this repo's dependency-free *.test.mjs files.

export const ROUTES = {
  // Public / end-user flow
  root: '/',
  start: '/start',                    // enter or auto-resolve a LocationCode
  login: '/login',
  signup: '/signup',                  // step 1: verify the invitation code
  signupAccount: '/signup/account',   // step 2: create the account
  welcome: '/welcome',                // end-user home
  buildings: '/buildings',            // choose a building
  destinations: '/destinations',      // choose a destination
  navigation: '/navigation',          // active turn-by-turn navigation

  // Admin overview. The rest of the admin routes live in
  // utils/adminNavigation.js's ADMIN_ROUTES, which imports this value so
  // there is still exactly one definition of it.
  adminOverview: '/admin',
};

// Where a user lands straight after logging in or signing up. Named
// separately from ROUTES because they are a POLICY ("admins land on the
// dashboard, everyone else on the end-user home"), not merely a path — and
// because utils/roleRouting.js and utils/invitationCodeFormHelpers.js each
// had their own hard-coded copy of that policy before this module existed.
export const ADMIN_DASHBOARD_ROUTE = ROUTES.adminOverview;
export const END_USER_HOME_ROUTE = ROUTES.welcome;

// Old numeric routes, kept working forever.
//
// Nothing inside the app navigates to these any more — every internal
// navigate()/<Navigate>/guard now targets a canonical path directly, so the
// app never depends on a redirect at runtime. They exist for what we cannot
// change retroactively:
//
//   * QR labels and bookmarks already printed or saved
//   * links shared before the rename
//   * anyone's browser history
//
// The redirect MUST carry the query string and hash through — a bare
// `<Navigate to="/start">` drops them, which would silently discard the
// ?locationCode= a scanned QuickRoute QR arrives with. App.jsx renders every
// entry below through one query-preserving redirect component.
//
// /screen/18 and /map both rendered IndoorNavigationScreen; they now fold
// into the single canonical /navigation.
export const LEGACY_ROUTE_REDIRECTS = {
  '/screen/01': ROUTES.start,
  '/screen/02': ROUTES.login,
  '/screen/03': ROUTES.signup,
  '/screen/04': ROUTES.signupAccount,
  '/screen/05': ROUTES.adminOverview,
  '/screen/15': ROUTES.welcome,
  '/screen/16': ROUTES.buildings,
  '/screen/17': ROUTES.destinations,
  '/screen/18': ROUTES.navigation,
  '/map': ROUTES.navigation,
};

// Where an unrecognised URL goes. Same target the catch-all has always
// used — it just carries the query string and hash now, so a mistyped or
// stale deep link with ?locationCode= still reaches the resolver.
export const NOT_FOUND_REDIRECT = ROUTES.start;
