// RBAC/dashboard cleanup task (frontend completion) — single source of
// truth for "where does this user land right after logging in / after a
// direct hit on an authenticated root route". Kept as a pure function
// (no React, no navigate() call) so it is trivially unit-testable and so
// LoginScreen.jsx, RequireRole.jsx and any future caller can never
// disagree about the rule.
//
// Rules (exactly matching the task spec):
//   - super_admin        -> the Admin Dashboard (Super Admin experience,
//                            dispatched by role inside AdminDashboardScreen.jsx)
//   - global_manager     -> the Admin Dashboard (Global Manager experience)
//   - building_manager   -> if they have EXACTLY ONE assigned map
//                            (user.map_ids.length === 1), go straight to
//                            that map's workspace; otherwise the Admin
//                            Dashboard (Building Manager experience)
//   - regular_user / anything else -> the normal end-user home screen
//
// `user` is the exact UserResponse shape returned by /api/auth/login,
// /api/auth/signup and /api/auth/me (id, full_name, email, role,
// building_ids, all_buildings, map_group_ids, map_ids).
export const ADMIN_DASHBOARD_ROUTE = '/screen/05';
export const END_USER_HOME_ROUTE = '/screen/15';

export function resolvePostLoginRoute(user) {
  if (!user || !user.role) {
    return END_USER_HOME_ROUTE;
  }

  if (user.role === 'super_admin' || user.role === 'global_manager') {
    return ADMIN_DASHBOARD_ROUTE;
  }

  if (user.role === 'building_manager') {
    const mapIds = Array.isArray(user.map_ids) ? user.map_ids : [];
    if (mapIds.length === 1 && mapIds[0]) {
      return `/admin/map?mapId=${encodeURIComponent(mapIds[0])}`;
    }
    return ADMIN_DASHBOARD_ROUTE;
  }

  return END_USER_HOME_ROUTE;
}

// Same admin-role list AuthContext.ADMIN_ROLES already exports — kept
// here too (duplicated, not imported) so this module has zero React/
// context dependencies and can be unit-tested with plain Node.
export const ADMIN_ROLES = ['super_admin', 'global_manager', 'building_manager'];

export function isAdminRole(role) {
  return ADMIN_ROLES.includes(role);
}

// Section 3 requirement: a building_manager/global_manager scoped to
// nothing yet (no buildings, or a building_manager with no maps) must see
// a clear localized empty state on their dashboard rather than a route
// guard bounce or a blank screen — this helper just tells the dashboard
// component whether that state applies; the actual localized copy lives
// in each dashboard screen's own UI translation object.
export function hasAnyAssignedScope(user) {
  if (!user) return false;
  if (user.role === 'super_admin') return true;
  if (user.all_buildings) return true;
  return Boolean((user.building_ids || []).length);
}
