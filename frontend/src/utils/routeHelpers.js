/**
 * routeHelpers.js
 *
 * Pure formatting helpers for indoor navigation display text.
 *
 * This file no longer contains any hardcoded campus coordinates, canned
 * routes, or step-building logic — the old `buildStepsFromPath` /
 * `estimateTimeFromDistance` helpers and their `STEP_LABELS` /
 * `STEP_ICON_BY_POINT_TYPE` tables were removed (QuickRoute User
 * Experience Final Cleanup, Part 6) because IndoorNavigationScreen now
 * builds its step list from the real multi-floor route response via
 * `utils/multiFloorRouteHelpers.js`'s `instructionToStep`, which passes
 * the backend's own instruction text straight through. Only the two
 * generic formatters below remain, and both are still used by
 * IndoorNavigationScreen.jsx to format real backend distance/time values.
 */

// ── Formatting helpers ────────────────────────────────────────────────────────

export function formatDistance(meters) {
  if (!meters && meters !== 0) return '—';
  if (meters >= 1000) return `${(meters / 1000).toFixed(1)} km`;
  return `${Math.round(meters)} m`;
}

export function formatTime(minutes) {
  if (!minutes) return '—';
  return `~${minutes} min`;
}

// Rough, DISPLAY-ONLY walking-step estimate from the real backend
// distance-in-meters value — never stored in MongoDB, never used as a
// Dijkstra/routing weight (meters stays the one canonical distance unit
// everywhere else in the app). 0.75 m is a simple average adult stride
// length; this is intentionally a coarse estimate, not a measurement, and
// callers must always label it as such (see IndoorNavigationScreen.jsx's
// "estimatedSteps" translation, which appends an explicit "(est.)"-style
// suffix next to this value).
const AVERAGE_STRIDE_METERS = 0.75;

export function estimateSteps(meters) {
  if (meters == null || Number.isNaN(meters) || meters < 0) return null;
  return Math.round(meters / AVERAGE_STRIDE_METERS);
}
