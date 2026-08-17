// Dashboard redesign — frontend MIRROR of the authorization rules that
// backend/core/auth_deps.py already enforces. Nothing in this file is a
// security boundary: every helper here only decides whether a UI control
// is WORTH RENDERING. The backend dependency named in each comment is the
// real gate, and it is unchanged by this redesign.
//
// Rules this file follows:
//   * never invent a permission the backend does not already have;
//   * never widen anything (a helper may only hide UI the backend would
//     have rejected anyway);
//   * every role list below is a copy of one specific FastAPI dependency,
//     named in the comment above it, so a backend change has exactly one
//     place to be reflected here.

import { ADMIN_ROUTES, withMapContext } from './adminNavigation.js';

// backend/core/auth_deps.py -> require_any_admin
export const ANY_ADMIN_ROLES = ['super_admin', 'global_manager', 'building_manager'];

// backend/core/auth_deps.py -> require_global_admin
export const GLOBAL_ADMIN_ROLES = ['super_admin', 'global_manager'];

// backend/core/auth_deps.py -> require_super_admin
export const SUPER_ADMIN_ROLES = ['super_admin'];

export function isAdminRole(role) {
  return ANY_ADMIN_ROLES.includes(role);
}

// ── Feature-level checks ───────────────────────────────────────────────
// Each of these answers "would the backend accept this user on the screen
// this control opens", using that screen's OWN strictest gate.

// /admin/invitation-codes — every /api/invitation-codes endpoint is
// Depends(require_global_admin); the route is additionally wrapped in
// <RequireGlobalAdmin> in App.jsx.
export function canManageInvitationCodes(user) {
  return Boolean(user) && GLOBAL_ADMIN_ROLES.includes(user.role);
}

// /admin/locations — the screen is wrapped in <RequireRole> and
// PUT /api/locations/buildings/{id} accepts any admin within scope.
export function canOpenBuildingAdmin(user) {
  return Boolean(user) && ANY_ADMIN_ROLES.includes(user.role);
}

// POST/DELETE /api/locations/buildings and POST /api/map-groups are
// Depends(require_global_admin) — creating a site/building or a new map
// group is NOT available to a building_manager.
export function canCreateBuildings(user) {
  return Boolean(user) && GLOBAL_ADMIN_ROLES.includes(user.role);
}

// /admin/map, /admin/rooms, /admin/routes, /admin/location-codes,
// /admin/map-analysis — all <RequireRole> screens whose write endpoints
// are Depends(require_any_admin) (plus per-resource scope checks).
export function canOpenMapWorkspace(user) {
  return Boolean(user) && ANY_ADMIN_ROLES.includes(user.role);
}

// PERMANENT STRUCTURAL DELETION of a Map, a Map Group or an uploaded
// Floor. Mirrors the backend's role gate on DELETE /api/maps/{id},
// DELETE /api/map-groups/{id} and DELETE /api/map-groups/{id}/floors/{id},
// all of which are Depends(require_global_admin) plus a scope check.
//
// A building_manager remains a full OPERATIONAL administrator of its
// assigned building — it uploads maps, creates map groups, adds floors,
// edits metadata and manages rooms/route points/location codes there —
// but it cannot permanently destroy structure, because those deletes
// cascade and are unrecoverable. The control is not rendered disabled for
// it; it is not rendered at all.
export function canDeleteMapResources(user) {
  return Boolean(user) && GLOBAL_ADMIN_ROLES.includes(user.role);
}

// /admin/users — Users & Access. Mirrors the backend's own predicate
// (logic/user_admin_logic.can_manage_users): super_admin and
// global_manager only. A building_manager administers a building, never
// the installation's accounts, so it gets no sidebar entry, no route and
// no request — and GET /api/admin/users 403s it regardless.
export function canManageUsers(user) {
  return Boolean(user) && GLOBAL_ADMIN_ROLES.includes(user.role);
}

// Which roles THIS account may hand out in Users & Access. Mirrors
// backend logic/user_admin_logic.ASSIGNABLE_ROLES_BY_ACTOR exactly, so
// the edit form can never offer an option the backend would reject —
// most importantly, a global_manager is never offered super_admin.
const ASSIGNABLE_ROLES_BY_ACTOR = {
  super_admin: ['super_admin', 'global_manager', 'building_manager'],
  global_manager: ['building_manager'],
};

export function getAssignableRoles(user) {
  return ASSIGNABLE_ROLES_BY_ACTOR[user?.role] || [];
}

// /admin/navigation-cleanup — <RequireSuperAdmin>, and every
// /api/navigation-cleanup write endpoint is Depends(require_super_admin).
export function canOpenNavigationCleanup(user) {
  return Boolean(user) && SUPER_ADMIN_ROLES.includes(user.role);
}

// ── Resource-scope checks ──────────────────────────────────────────────
// Straight ports of get_accessible_building_ids() / user_can_access_*()
// from backend/core/auth_deps.py, including the three documented
// global_manager scope shapes. Used ONLY to avoid rendering (and
// requesting) resources the backend would 403 on anyway.

export function getAccessibleBuildingIds(user) {
  if (!user) return [];
  if (user.role === 'super_admin') return null;
  if (
    (user.role === 'global_manager' || user.role === 'building_manager') &&
    user.all_buildings
  ) {
    return null;
  }
  // global_manager scope shape (c): an empty building list means "not
  // narrowed", never "narrowed to nothing".
  if (user.role === 'global_manager' && !(user.building_ids || []).length) {
    return null;
  }
  if (user.role === 'global_manager' || user.role === 'building_manager') {
    return [...(user.building_ids || [])];
  }
  return [];
}

export function userCanAccessBuilding(user, buildingId) {
  if (!user) return false;
  if (user.role === 'super_admin') return true;
  if (user.role === 'global_manager' && !(user.building_ids || []).length) return true;
  if (!buildingId) return false;
  if (user.role === 'global_manager' || user.role === 'building_manager') {
    return Boolean(user.all_buildings) || (user.building_ids || []).includes(buildingId);
  }
  return false;
}

// `group` only needs { id, buildingId }.
export function userCanAccessMapGroup(user, group) {
  if (!user || !group) return false;
  if (user.role === 'super_admin') return true;
  if (!userCanAccessBuilding(user, group.buildingId)) return false;
  if (user.role !== 'building_manager') return true;
  if ((user.map_group_ids || []).length) {
    return Boolean(group.id) && user.map_group_ids.includes(group.id);
  }
  // A building_manager narrowed only by map_ids is deliberately denied
  // group-level access, exactly as _building_and_group_allowed() does.
  if ((user.map_ids || []).length) return false;
  return true;
}

// `map` only needs { id, buildingId, mapGroupId }. map_ids is the most
// restrictive scope and wins over map_group_ids when both are set.
export function userCanAccessMap(user, map) {
  if (!user || !map) return false;
  if (user.role === 'super_admin') return true;
  if (!userCanAccessBuilding(user, map.buildingId)) return false;
  if (user.role !== 'building_manager') return true;
  if ((user.map_ids || []).length) {
    return Boolean(map.id) && user.map_ids.includes(map.id);
  }
  if ((user.map_group_ids || []).length) {
    return Boolean(map.mapGroupId) && user.map_group_ids.includes(map.mapGroupId);
  }
  return true;
}

// ── Navigation model ───────────────────────────────────────────────────
// The global sidebar carries GLOBAL administration only: Overview, the
// Sites & Buildings browser/manager, Map Management (the one global place
// to upload a map, create a map group or add a floor — reachable WITHOUT
// first selecting an existing map) and Invitation Codes.
//
// Map-scoped tools (Map Workspace, Rooms & Destinations, Route Points,
// Location Codes, Semantic Analysis, Navigation Data Cleanup) deliberately
// never appear here — they are rendered contextually once a specific floor
// has been selected (see buildMapContextTools below), so the global home
// never turns into a wall of map actions and an admin can never act on a
// map without having chosen it first.
//
// "Global" means globally REACHABLE, never globally unrestricted: Map
// Management's own contents are scoped by the same backend rules as every
// other screen (GET /api/maps and GET /api/map-groups are admin-only and
// scope-narrowed).
//
// Returns entries as { key, route } — labels/icons are resolved by the
// component so this stays a pure, translation-free, testable function.
export function buildSidebarItems(user) {
  if (!user || !isAdminRole(user.role)) return [];

  const items = [{ key: 'overview', route: ADMIN_ROUTES.overview }];

  if (canOpenBuildingAdmin(user)) {
    items.push({ key: 'sites', route: ADMIN_ROUTES.sites });
  }
  if (canOpenMapWorkspace(user)) {
    items.push({ key: 'mapManagement', route: ADMIN_ROUTES.mapManagement });
  }
  if (canManageInvitationCodes(user)) {
    items.push({ key: 'invitations', route: ADMIN_ROUTES.invitations });
  }
  if (canManageUsers(user)) {
    items.push({ key: 'users', route: ADMIN_ROUTES.users });
  }

  return items;
}

// Tools shown ONLY after a specific map (floor) is selected. `mapId` is
// appended only to the screens that actually read it from the query
// string today (AdminMapScreen, AdminMapAnalysisScreen); the others open
// with their own existing selectors, unchanged.
export function buildMapContextTools(user, mapId) {
  if (!user || !mapId) return [];

  const tools = [];

  if (canOpenMapWorkspace(user)) {
    tools.push({ key: 'workspace', route: withMapContext(ADMIN_ROUTES.mapManagement, mapId) });
    tools.push({ key: 'rooms', route: withMapContext(ADMIN_ROUTES.rooms, mapId) });
    tools.push({ key: 'routes', route: withMapContext(ADMIN_ROUTES.routePoints, mapId) });
    tools.push({ key: 'locationCodes', route: withMapContext(ADMIN_ROUTES.locationCodes, mapId) });
    tools.push({ key: 'analysis', route: withMapContext(ADMIN_ROUTES.analysis, mapId) });
  }

  if (canOpenNavigationCleanup(user)) {
    tools.push({
      key: 'cleanup',
      route: withMapContext(ADMIN_ROUTES.cleanup, mapId),
      destructive: true,
    });
  }

  return tools;
}
