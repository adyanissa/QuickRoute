/**
 * routeHelpers.js
 *
 * Central helper for the X → Y routing model:
 *
 *   X = current user location  (always the campus roundabout entrance)
 *   Y = selected destination   (the building the user tapped in the list)
 *
 * Every exported function takes a `buildingId` and works relative to
 * these two points.  When a building has a pre-defined curved path it is
 * used; otherwise a straight line X→Y is generated automatically so that
 * every building always has a route.
 */

import {
  CURRENT_LOCATION,
  BUILDING_POSITIONS,
  ROUTES,
  ROUTE_STEPS,
  GENERIC_STEPS,
  INDOOR_STEPS,
} from '../data/routeData';

// Internal key format used in ROUTES lookup
const _routeKey = (buildingId) => `entrance-${buildingId}`;

// ── Core X / Y accessors ──────────────────────────────────────────────────────

/** X — the user's current location (fixed campus roundabout). */
export function getCurrentLocation() {
  return CURRENT_LOCATION;   // { x: 192, y: 213 }
}

/**
 * Y — the SVG map position of the selected building.
 * Falls back to the center of the map if the id is unknown.
 */
export function getDestinationPoint(buildingId) {
  return BUILDING_POSITIONS[buildingId] ?? { x: 200, y: 112 };
}

// ── Route path (X → Y) ────────────────────────────────────────────────────────

/** Raw route data object (waypoints, distance, time) or null. */
export function getRouteData(buildingId) {
  return ROUTES[_routeKey(buildingId)] ?? null;
}

/**
 * SVG path string from X to Y.
 * Uses the pre-defined curved path when available; always falls back to a
 * direct straight line so every building has a route.
 */
export function getRouteSVGPath(buildingId) {
  const X     = getCurrentLocation();
  const Y     = getDestinationPoint(buildingId);
  const route = getRouteData(buildingId);

  if (route && route.points.length >= 2) {
    return route.points
      .map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x} ${p.y}`)
      .join(' ');
  }

  // Straight line X → Y (guaranteed fallback for every building)
  return `M ${X.x} ${X.y} L ${Y.x} ${Y.y}`;
}

/**
 * Waypoint dots to render along the path (interior points only,
 * evenly sampled so the map doesn't get cluttered).
 */
export function getWaypoints(buildingId) {
  const route = getRouteData(buildingId);
  if (!route || route.points.length <= 2) return [];
  const interior = route.points.slice(1, -1);
  const step = Math.max(1, Math.floor(interior.length / 3));
  return interior.filter((_, i) => i % step === 0);
}

// ── Distance & time estimates (X → Y) ────────────────────────────────────────

/** Walking distance in metres. */
export function getEstimatedDistance(buildingId) {
  const route = getRouteData(buildingId);
  if (route) return route.distanceM;

  // Euclidean fallback (SVG units ≈ metres on this campus scale)
  const { x: x1, y: y1 } = getCurrentLocation();
  const { x: x2, y: y2 } = getDestinationPoint(buildingId);
  return Math.round(Math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2) * 2.5);
}

/** Walking time in minutes (80 m / min average). */
export function getEstimatedTime(buildingId) {
  const route = getRouteData(buildingId);
  if (route) return route.timeMin;
  const dist = getEstimatedDistance(buildingId);
  return Math.max(1, Math.round(dist / 80));
}

// ── Legacy aliases (keep existing call-sites working) ─────────────────────────

/** @deprecated use getCurrentLocation() */
export const getStartPosition = getCurrentLocation;

/** @deprecated use getDestinationPoint(id) */
export const getDestinationPosition = getDestinationPoint;

// ── Step-by-step directions ───────────────────────────────────────────────────

/** Outdoor directions from X to Y (building entrance). */
export function getOutdoorSteps(buildingId, lang, buildingName) {
  const stepSet = ROUTE_STEPS[_routeKey(buildingId)];
  if (stepSet?.[lang]) return stepSet[lang];
  const l = lang in GENERIC_STEPS ? lang : 'en';
  return GENERIC_STEPS[l](buildingName);
}

/** Indoor directions from building entrance to the specific room. */
export function getIndoorSteps(room, lang) {
  if (!room) return [];
  const fn = INDOOR_STEPS[lang] ?? INDOOR_STEPS.en;
  return fn(room.name, room.floor ?? 0);
}

/** Full combined route: outdoor steps (X→building) + indoor steps (→room). */
export function getFullRoute(buildingId, room, lang, buildingName) {
  return {
    outdoor: getOutdoorSteps(buildingId, lang, buildingName),
    indoor:  room ? getIndoorSteps(room, lang) : [],
  };
}

// ── Formatting helpers ────────────────────────────────────────────────────────

export function formatDistance(meters) {
  if (!meters) return '—';
  if (meters >= 1000) return `${(meters / 1000).toFixed(1)} km`;
  return `${meters} m`;
}

export function formatTime(minutes) {
  if (!minutes) return '—';
  return `~${minutes} min`;
}
