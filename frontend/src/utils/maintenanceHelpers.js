// Pure helper for the Admin Dashboard's "Initialize Project Data" action
// (backend/routes/maintenance_routes.py's POST /api/maintenance/backfill-buildings).
// Kept separate from AdminDashboardScreen.jsx so the error-classification
// logic can be unit-tested without a React/DOM test harness — see
// maintenanceHelpers.test.mjs.

// Given an Error thrown by apiRequest() (which attaches `.status` from the
// HTTP response — see api.js), decides which of the three UI outcomes the
// screen should show:
//   - "sessionExpired": the JWT is missing/invalid/expired (401) — the
//     admin must log in again.
//   - "forbidden": the authenticated user's role isn't allowed to run this
//     operation (403).
//   - "generic": any other failure (network error, 500, validation, etc.)
//     — show the backend's message if there is one, otherwise a fallback.
// Returning a `kind` + `message` pair (rather than doing the branching
// inline in the component) is what makes this testable in plain Node.
export function classifyInitializeError(error, messages) {
  const status = error && typeof error === 'object' ? error.status : undefined;

  if (status === 401) {
    return { kind: 'sessionExpired', message: messages.sessionExpired };
  }

  if (status === 403) {
    return { kind: 'forbidden', message: messages.forbidden };
  }

  const detail = error && typeof error === 'object' ? error.message : null;

  return { kind: 'generic', message: detail || messages.failed };
}

// Extracts a simple, safe-to-render summary from the real
// backfill-buildings response shape:
//   { maps_updated, points_updated, buildings_created_or_reused,
//     rooms_with_missing_building, location_codes_inconsistent }
// Never invents fields that aren't present — anything missing/malformed
// just falls back to 0 / an empty list instead of throwing, since this
// runs directly against live backend JSON.
export function summarizeInitializeResult(result) {
  const buildingsMap =
    result && typeof result === 'object' && result.buildings_created_or_reused
      ? result.buildings_created_or_reused
      : {};

  return {
    mapsUpdated: Number(result?.maps_updated) || 0,
    pointsUpdated: Number(result?.points_updated) || 0,
    buildingsTouchedCount: Object.keys(buildingsMap).length,
    buildingsTouchedNames: Object.values(buildingsMap),
    roomsWithMissingBuilding: Number(result?.rooms_with_missing_building) || 0,
    locationCodesInconsistent: Number(result?.location_codes_inconsistent) || 0,
  };
}
