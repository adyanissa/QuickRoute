import { apiRequest } from "./api";

// Public — called from the Sign Up screen before the visitor has an
// account. Returns only safe preview information (role, buildings,
// intended email restriction, expiration) — never creator/usage identity.
export function validateInvitationCode(code) {
  return apiRequest("/api/invitation-codes/validate", {
    method: "POST",
    body: JSON.stringify({
      code: code,
    }),
  });
}

// Authenticated admin CRUD — every call below requires a super_admin or
// global_manager session; the backend rejects anyone else with 403.

export function listInvitationCodes(filters = {}) {
  const params = new URLSearchParams();

  if (filters.status) params.set("status", filters.status);
  if (filters.role) params.set("role", filters.role);
  if (filters.buildingId) params.set("building_id", filters.buildingId);

  const query = params.toString();
  return apiRequest(`/api/invitation-codes${query ? `?${query}` : ""}`);
}

export function getInvitationCode(id) {
  return apiRequest(`/api/invitation-codes/${id}`);
}

export function createInvitationCode(data) {
  return apiRequest("/api/invitation-codes", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export function revokeInvitationCode(id) {
  return apiRequest(`/api/invitation-codes/${id}/revoke`, {
    method: "POST",
  });
}
