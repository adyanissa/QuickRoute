// Pure helpers for the Admin "Invitation Codes" screen (create form,
// list/status display) and the Sign Up flow's invitation-code-driven
// account creation. Kept dependency-free so the creator permission
// hierarchy, dependent-field reset rules, and payload/redirect shape can
// be unit-tested without a DOM/React harness — same pattern as the
// repo's other *FormHelpers.js modules (see
// invitationCodeFormHelpers.test.mjs).

// ── Creator permission hierarchy (mirrors backend
// logic/invitation_code_logic.py:CREATABLE_ROLES_BY_CREATOR exactly —
// this list only decides which options the dropdown OFFERS; the backend
// is the real enforcement point) ──────────────────────────────────────
// Final admin user/access model: invitation codes are how ADMINISTRATORS
// are created, so `regular_user` is no longer offered here. An ordinary
// QuickRoute visitor never needs an invitation — they self-register
// through POST /api/auth/register, which requires no code at all, so
// removing the option cannot break the normal user flow.
//
// The backend still accepts a regular_user invitation (historical codes
// must keep validating and the role is not privileged); this list only
// decides what the admin UI OFFERS. The privileged part of the hierarchy
// — who may hand out super_admin / global_manager — still mirrors
// backend logic/invitation_code_logic.py:CREATABLE_ROLES_BY_CREATOR
// exactly, and the backend remains the enforcement point.
const CREATABLE_ROLES_BY_CREATOR = {
  super_admin: ['super_admin', 'global_manager', 'building_manager'],
  global_manager: ['building_manager'],
};

export function getAllowedRoleOptions(creatorRole) {
  return CREATABLE_ROLES_BY_CREATOR[creatorRole] || [];
}

export function requiresBuildingSelection(role) {
  return role === 'building_manager';
}

export function isSystemWideRole(role) {
  return role === 'super_admin';
}

// ── Dependent-field reset (Step 5 pattern, same as Location Codes'
// Building -> Map -> Start Point form): changing the role must never
// leave an incompatible building-scope selection in place. ────────────
export function resetScopeOnRoleChange(form, newRole) {
  if (newRole === 'super_admin') {
    return { ...form, role: newRole, allBuildings: true, buildingIds: [] };
  }

  // building_manager / global_manager / regular_user all start from a
  // cleared scope so the admin makes an explicit choice for the new role
  // rather than inheriting a stale selection from the previous one.
  return { ...form, role: newRole, allBuildings: false, buildingIds: [] };
}

export function isCreateEnabled(form) {
  if (!form?.role) return false;

  if (requiresBuildingSelection(form.role)) {
    // EXACTLY one building: a Building Manager administers one building
    // in full (including maps uploaded into it later), so the assignment
    // has to be unambiguous. The backend rejects any other count.
    return Array.isArray(form.buildingIds) && form.buildingIds.length === 1;
  }

  return true;
}

// A Building Manager's building choice is single-select: picking a second
// building REPLACES the first rather than adding to it.
export function selectAssignedBuilding(form, buildingId) {
  if (!requiresBuildingSelection(form?.role)) return form;
  const current = (form.buildingIds || [])[0];
  return {
    ...form,
    buildingIds: current === buildingId ? [] : [buildingId],
  };
}

// ── Expiration presets -> absolute ISO datetime the backend accepts. ──
export function resolveExpiresAt(preset, customDate, now = new Date()) {
  switch (preset) {
    case '24h':
      return new Date(now.getTime() + 24 * 60 * 60 * 1000).toISOString();
    case '7d':
      return new Date(now.getTime() + 7 * 24 * 60 * 60 * 1000).toISOString();
    case '30d':
      return new Date(now.getTime() + 30 * 24 * 60 * 60 * 1000).toISOString();
    case 'custom':
      return customDate ? new Date(customDate).toISOString() : null;
    case 'none':
    default:
      return null;
  }
}

// ── Create-request payload: always building IDs, never display names —
// the whole point of driving the form off real Building records. ──────
export function buildCreateInvitationCodePayload(form) {
  const payload = {
    role: form.role,
    all_buildings: form.role === 'super_admin' ? true : Boolean(form.allBuildings),
    building_ids:
      form.role === 'super_admin'
        ? []
        : (form.buildingIds || []).map((id) => String(id)),
  };

  if (form.intendedEmail && form.intendedEmail.trim()) {
    payload.intended_email = form.intendedEmail.trim().toLowerCase();
  }

  if (form.expiresAt) {
    payload.expires_at = form.expiresAt;
  }

  if (form.customCode && form.customCode.trim()) {
    payload.code = form.customCode.trim().toUpperCase();
  }

  return payload;
}

export function buildInvitationCodeSummary(form, buildingsById = {}) {
  const buildingNames = (form.buildingIds || [])
    .map((id) => buildingsById[id]?.nameEn || buildingsById[id]?.name_en || null)
    .filter(Boolean);

  let responsibility;
  if (form.role === 'super_admin') {
    responsibility = 'All buildings (system-wide)';
  } else if (form.allBuildings) {
    responsibility = 'All buildings';
  } else if (buildingNames.length) {
    responsibility = buildingNames.join(', ');
  } else {
    responsibility = 'No building selected';
  }

  return {
    role: form.role,
    responsibility,
    intendedEmail: form.intendedEmail || null,
    expiresAt: form.expiresAt || null,
    singleUse: true,
  };
}

// ── List/status display ────────────────────────────────────────────────
const STATUS_LABELS = {
  active: 'Active',
  used: 'Used',
  expired: 'Expired',
  revoked: 'Revoked',
};

export function getStatusLabel(status) {
  return STATUS_LABELS[status] || status || 'Unknown';
}

export function canRevoke(entry) {
  return entry?.status === 'active';
}

export function getCopyableCode(entry) {
  return String(entry?.code || '');
}

// ── Sign Up flow ─────────────────────────────────────────────────────
export function shouldLockEmailField(preview) {
  return Boolean(preview?.intended_email);
}

export function getInitialEmail(preview) {
  return preview?.intended_email || '';
}

// Deliberately whitelists only the fields the backend's SignupRequest
// schema accepts. Even if the account-creation form's local state
// somehow carried a role/building field (it never should — nothing in
// the UI writes one), this function cannot forward it: the invited
// role/building permissions come only from the stored invitation code,
// resolved server-side.
export function buildSignupPayload(accountForm, code) {
  return {
    full_name: (accountForm.fullName || '').trim(),
    email: (accountForm.email || '').trim(),
    password: accountForm.password || '',
    code: (code || '').trim().toUpperCase(),
  };
}

const ADMIN_ROLES = ['super_admin', 'global_manager', 'building_manager'];

export function getPostAuthRedirectPath(role) {
  return ADMIN_ROLES.includes(role) ? '/screen/05' : '/screen/15';
}
