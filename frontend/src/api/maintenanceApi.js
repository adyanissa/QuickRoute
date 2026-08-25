// Explicit ".js" extension (unlike some sibling *Api.js files) so this
// module resolves under both Vite and plain Node ESM — the latter is what
// runs maintenanceApi.test.mjs, since this repo has no jest/vitest
// installed.
import { apiRequest } from "./api.js";

// Admin-triggered data-consistency maintenance operations. These map
// directly to backend/routes/maintenance_routes.py — kept as explicit,
// deliberate admin actions (not something that runs automatically) so an
// admin always sees exactly what changed.

// Backfills building_id onto every Map/RoutePoint currently missing one,
// creating or reusing a Building per campus/title as needed. Goes through
// the same shared apiRequest() helper as every other authenticated call,
// so it automatically attaches the stored JWT and never needs a manually
// copied token. Idempotent — safe to call more than once. Returns the
// backend's structured summary as-is (maps_updated, points_updated,
// buildings_created_or_reused, rooms_with_missing_building,
// location_codes_inconsistent) — see maintenance_routes.py for the exact
// current shape.
export function runBackfillBuildings() {
  return apiRequest("/api/maintenance/backfill-buildings", {
    method: "POST",
  });
}
