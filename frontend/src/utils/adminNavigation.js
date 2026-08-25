// One canonical map of admin routes, sidebar highlighting and Back
// targets, so every admin page agrees about where it sits and where Back
// goes. Pure (no React, no router) — unit-testable with plain Node.
//
// Back is DETERMINISTIC, never history.back(): a page reached by pasting a
// URL, by a redirect, or as the first page of a session must still have a
// Back control that lands inside QuickRoute rather than on whatever site
// the browser happened to visit before.

import { ROUTES } from '../config/routes.js';

export const ADMIN_ROUTES = {
  // Imported rather than re-declared, so the admin overview path has exactly
  // one definition shared with the post-login redirect rule in
  // config/routes.js.
  overview: ROUTES.adminOverview,
  sites: '/admin/sites',
  mapManagement: '/admin/map',
  invitations: '/admin/invitation-codes',
  users: '/admin/users',
  rooms: '/admin/rooms',
  routePoints: '/admin/routes',
  locationCodes: '/admin/location-codes',
  analysis: '/admin/map-analysis',
  cleanup: '/admin/navigation-cleanup',
};

// Legacy route kept working by redirecting to its canonical replacement —
// old bookmarks, the map screen's "back to locations" links and anything
// else pointing at /admin/locations must not 404 after the consolidation.
export const LEGACY_ADMIN_ROUTE_REDIRECTS = {
  '/admin/locations': ADMIN_ROUTES.sites,
};

export function buildingRoute(buildingId) {
  return `/admin/buildings/${encodeURIComponent(buildingId)}`;
}

export function floorRoute(mapId) {
  return `/admin/maps/${encodeURIComponent(mapId)}`;
}

// `mapId` is appended to every contextual tool link — including the tools
// that do not read it from the query string today — purely so Back from
// that tool can return to the exact floor the admin came from instead of
// guessing. A tool that ignores the parameter behaves exactly as before.
export function withMapContext(route, mapId) {
  if (!mapId) return route;
  const separator = route.includes('?') ? '&' : '?';
  return `${route}${separator}mapId=${encodeURIComponent(mapId)}`;
}

// Which sidebar entry is highlighted for a given pathname. Everything
// under the Sites branch (a Building Workspace, a Floor Workspace and the
// map tools opened from one) keeps "Sites & Buildings" lit, so the admin
// can always see which section of the product they are inside.
// Segment-aware prefix match: '/admin/map-analysis' must NEVER be treated
// as being under '/admin/map'. A plain startsWith() would do exactly that,
// which is why this helper exists and is used for every route comparison
// in this module.
export function isUnderRoute(pathname, route) {
  const path = String(pathname || '');
  return path === route || path.startsWith(`${route}/`) || path.startsWith(`${route}?`);
}

// Overview is the ONLY admin route that must be matched EXACTLY.
//
// Every other admin path now lives under it (/admin/sites, /admin/map, ...),
// so the segment-aware isUnderRoute() above would report all of them as
// "under Overview" — which would light the Overview sidebar item on every
// page and strip every page's Back control. This is specific to Overview
// being the parent path; the prefix match is still correct for the others,
// where a child route genuinely belongs to its section.
function isOverviewRoute(pathname) {
  const path = String(pathname || '').split('?')[0].split('#')[0];
  const normalized = path.length > 1 ? path.replace(/\/+$/, '') : path;

  return normalized === ADMIN_ROUTES.overview;
}

const SITES_BRANCH_ROUTES = [
  ADMIN_ROUTES.sites,
  '/admin/locations',
  '/admin/buildings',
  '/admin/maps',
  ADMIN_ROUTES.rooms,
  ADMIN_ROUTES.routePoints,
  ADMIN_ROUTES.locationCodes,
  ADMIN_ROUTES.analysis,
  ADMIN_ROUTES.cleanup,
];

export function resolveSidebarActiveKey(pathname) {
  const path = String(pathname || '');

  if (isOverviewRoute(path)) return 'overview';
  if (isUnderRoute(path, ADMIN_ROUTES.invitations)) return 'invitations';
  if (isUnderRoute(path, ADMIN_ROUTES.users)) return 'users';
  if (SITES_BRANCH_ROUTES.some((route) => isUnderRoute(path, route))) return 'sites';
  if (isUnderRoute(path, ADMIN_ROUTES.mapManagement)) return 'mapManagement';

  return null;
}

// The deterministic Back target for `pathname`. `search` is the raw query
// string (e.g. "?mapId=abc"): a map-scoped tool goes back to the Floor
// Workspace it was opened from, and falls back to Overview when it was
// opened without a map context.
export function resolveBackTarget(pathname, search = '') {
  const path = String(pathname || '');
  const mapId = readMapId(search);

  if (isOverviewRoute(path)) return null; // Overview is the root

  if (isUnderRoute(path, '/admin/buildings')) return ADMIN_ROUTES.sites;
  if (isUnderRoute(path, '/admin/maps')) return ADMIN_ROUTES.sites;

  const mapScopedTools = [
    ADMIN_ROUTES.rooms,
    ADMIN_ROUTES.routePoints,
    ADMIN_ROUTES.locationCodes,
    ADMIN_ROUTES.analysis,
    ADMIN_ROUTES.cleanup,
    ADMIN_ROUTES.mapManagement,
  ];

  if (mapScopedTools.some((route) => isUnderRoute(path, route))) {
    return mapId ? floorRoute(mapId) : ADMIN_ROUTES.overview;
  }

  return ADMIN_ROUTES.overview;
}

export function readMapId(search) {
  const raw = String(search || '');
  const match = /[?&]mapId=([^&]*)/.exec(raw);
  if (!match || !match[1]) return '';
  try {
    return decodeURIComponent(match[1]);
  } catch {
    return match[1];
  }
}
