/**
 * routeHelpers.js
 *
 * Pure formatting + step-building helpers for indoor navigation.
 *
 * This file no longer contains any hardcoded campus coordinates or
 * canned routes — those came from `data/routeData.js`, which has been
 * removed from the navigation flow. Real paths now come from the
 * backend's `POST /api/navigation/route` endpoint (see `api/navigationApi.js`),
 * which returns a real `path_details` list of RoutePoint records and a
 * real `total_distance`. The helpers below turn that real response into
 * display text; they invent no data of their own.
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

// Walking-time estimate from a real distance (no data invented — just a
// generic average walking speed applied to the backend's own distance).
export function estimateTimeFromDistance(meters) {
  if (!meters && meters !== 0) return 0;
  return Math.max(1, Math.round(meters / 80));
}

// ── Turn-by-turn step generation from a real path ──────────────────────────

// Maps a real RoutePoint.point_type to a RouteSteps icon type.
const STEP_ICON_BY_POINT_TYPE = {
  entrance: 'enter',
  hallway: 'walk',
  junction: 'turn',
  room: 'arrive',
  store: 'arrive',
  stairs: 'turn',
  elevator: 'elevator',
};

const STEP_LABELS = {
  en: {
    start: (name) => `Start at ${name}`,
    stairs: (name) => `Take the stairs to ${name}`,
    elevator: (name) => `Take the elevator to ${name}`,
    enter: (name) => `Enter ${name}`,
    head: (name) => `Continue to ${name}`,
    arrive: (name) => `Arrive at ${name}`,
  },
  ar: {
    start: (name) => `ابدأ من ${name}`,
    stairs: (name) => `اصعد الدرج إلى ${name}`,
    elevator: (name) => `استخدم المصعد إلى ${name}`,
    enter: (name) => `ادخل إلى ${name}`,
    head: (name) => `تابع إلى ${name}`,
    arrive: (name) => `وصلت إلى ${name}`,
  },
  he: {
    start: (name) => `התחל ב-${name}`,
    stairs: (name) => `עלה במדרגות אל ${name}`,
    elevator: (name) => `קח את המעלית אל ${name}`,
    enter: (name) => `היכנס אל ${name}`,
    head: (name) => `המשך אל ${name}`,
    arrive: (name) => `הגעת אל ${name}`,
  },
};

/**
 * Builds a { type, text }[] step list directly from the real
 * `path_details` array returned by POST /api/navigation/route.
 * Returns [] when there is no real path — callers must not fall back
 * to invented steps.
 */
export function buildStepsFromPath(pathDetails, lang = 'en') {
  if (!Array.isArray(pathDetails) || pathDetails.length === 0) return [];

  const labels = STEP_LABELS[lang] || STEP_LABELS.en;

  return pathDetails.map((point, index) => {
    const isFirst = index === 0;
    const isLast = index === pathDetails.length - 1;
    const name = point.name || '';

    if (isFirst) {
      return { type: 'exit', text: labels.start(name) };
    }

    if (isLast) {
      return { type: 'arrive', text: labels.arrive(name) };
    }

    if (point.point_type === 'stairs') {
      return { type: 'turn', text: labels.stairs(name) };
    }

    if (point.point_type === 'elevator') {
      return { type: 'elevator', text: labels.elevator(name) };
    }

    if (point.point_type === 'entrance') {
      return { type: 'enter', text: labels.enter(name) };
    }

    return {
      type: STEP_ICON_BY_POINT_TYPE[point.point_type] || 'walk',
      text: labels.head(name),
    };
  });
}
