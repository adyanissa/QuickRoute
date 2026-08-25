import { apiRequest } from "./api";

// Users & Access — administrator account management.
//
// Every response here is already an allow-list on the backend
// (schemas/user_admin_schema.py): no password hash, no token material.
// Scope is never sent from here either — the backend derives it from the
// role + the single assigned building, so the browser cannot construct a
// scope the server would not have chosen.

export function getAdminUsers({ search = "", role = "" } = {}) {
  const params = new URLSearchParams();
  if (search) params.set("search", search);
  if (role) params.set("role", role);
  const query = params.toString();
  return apiRequest(`/api/admin/users${query ? `?${query}` : ""}`);
}

export function getAdminUser(userId) {
  return apiRequest(`/api/admin/users/${encodeURIComponent(userId)}`);
}

// `changes` accepts only { full_name, role, building_id } — anything else
// is ignored by the backend schema rather than silently applied.
export function updateAdminUser(userId, changes) {
  return apiRequest(`/api/admin/users/${encodeURIComponent(userId)}`, {
    method: "PUT",
    body: JSON.stringify(changes),
  });
}

export function deleteAdminUser(userId) {
  return apiRequest(`/api/admin/users/${encodeURIComponent(userId)}`, {
    method: "DELETE",
  });
}
