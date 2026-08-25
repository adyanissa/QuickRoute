// Admin shell identity — the ONE place that decides what name, initial and
// role label the header and the welcome line show.
//
// Every value is derived from the authenticated user object returned by
// /api/auth/login | /api/auth/signup | /api/auth/me (the UserResponse
// shape: id, full_name, email, role, building_ids, all_buildings,
// map_group_ids, map_ids). Nothing here is ever hard-coded to a person:
// there is deliberately no default/placeholder name in this module, so a
// missing name renders as an empty string or a neutral fallback rather
// than somebody else's identity.

// full_name -> the local part of the email -> '' (never an invented name).
export function resolveUserDisplayName(user) {
  if (!user) return '';

  const fullName = String(user.full_name || '').trim();
  if (fullName) return fullName;

  const email = String(user.email || '').trim();
  if (email) {
    const localPart = email.split('@')[0].trim();
    return localPart || email;
  }

  return '';
}

// First character of the display name, uppercased. Array.from() (not [0])
// so a Hebrew/Arabic name or an astral-plane character yields one whole
// character rather than half a surrogate pair.
export function resolveUserInitial(user) {
  const name = resolveUserDisplayName(user);
  const first = Array.from(name.trim())[0];
  return first ? first.toLocaleUpperCase() : '?';
}

// `roleLabels` is the active language's role dictionary (see
// screens/dashboards/dashboardUi.js). An unknown/absent role falls back to
// the raw role string rather than to a guessed label — the header must
// never claim a permission level the backend did not report.
export function resolveRoleLabel(user, roleLabels) {
  const role = user?.role;
  if (!role) return '';
  return (roleLabels && roleLabels[role]) || role;
}
