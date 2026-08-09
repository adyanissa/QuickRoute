// RBAC/dashboard cleanup task (frontend completion), Section 3 — pure
// helper extracted out of SuperAdminDashboard.jsx so the "group buildings
// by Building.campus, bucket anything empty/whitespace-only under the
// exact translated Unassigned-location label" rule is unit-testable
// without React. Never invents a campus value, never falls back to a
// demo/placeholder building name — an empty group is simply an empty
// Map entry, and the caller decides what (if anything) to render for it.
export function groupBuildingsByCampus(buildings, unassignedLabel) {
  const groups = new Map();
  for (const building of buildings || []) {
    const campus = (building.campus || '').trim();
    const key = campus || unassignedLabel;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(building);
  }
  return groups;
}

// Every building whose campus is empty/whitespace-only lands in exactly
// one group, keyed by whatever label the caller passes in for
// "Unassigned location" (EN/AR/HE) — this helper never hardcodes the
// label itself, so it can never drift from the real translated string
// three different screens might use.
export function isUnassignedCampus(campus) {
  return !campus || !campus.trim();
}
