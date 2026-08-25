/**
 * multiFloorRouteHelpers.js
 *
 * Pure helpers for turning a POST /api/navigation/multi-floor-route
 * response into what IndoorNavigationScreen renders: one step list per
 * floor segment, paired 1:1 with the transition that follows it (PHASE
 * 13's floor stepper + transition cards). No data is invented here — the
 * grouping only reorganizes the exact `segments`/`instructions` arrays the
 * backend already returned.
 */

// The backend's generate_instructions_for_route() (see
// backend/logic/instruction_generator.py) always emits every floor
// segment's own instructions in order, with exactly one `type: "transition"`
// instruction between consecutive floors — so splitting the flat
// `instructions` list on that marker reconstructs the same floor/transition
// grouping the `segments` array already has, without needing to re-match
// point ids.
export function groupInstructionsByFloor(instructions) {
  const list = Array.isArray(instructions) ? instructions : [];
  const floorGroups = [];
  let current = [];

  for (const instruction of list) {
    if (instruction?.type === 'transition') {
      floorGroups.push(current);
      current = [];
    } else {
      current.push(instruction);
    }
  }
  floorGroups.push(current);

  return floorGroups;
}

export function getTransitionInstructions(instructions) {
  const list = Array.isArray(instructions) ? instructions : [];
  return list.filter((instruction) => instruction?.type === 'transition');
}

export function getFloorSegments(segments) {
  const list = Array.isArray(segments) ? segments : [];
  return list.filter((segment) => segment?.segment_type === 'floor');
}

export function getTransitionSegments(segments) {
  const list = Array.isArray(segments) ? segments : [];
  return list.filter((segment) => segment?.segment_type === 'transition');
}

// Maps a backend instruction `type` (see instruction_generator.py's
// classify_turn) to the icon key RouteSteps.jsx already understands.
const STEP_ICON_BY_INSTRUCTION_TYPE = {
  start: 'exit',
  straight: 'walk',
  slight_left: 'turn',
  slight_right: 'turn',
  left: 'turn',
  right: 'turn',
  sharp_left: 'turn',
  sharp_right: 'turn',
  u_turn: 'turn',
  arrive: 'arrive',
};

// ── Presentation-only distance stripping ────────────────────────────────────
// The end-user navigation screen must never present a distance figure
// (the calibration on real maps isn't trustworthy enough for that — see
// the professional navigation UX spec, Section 3). The backend's real
// turn-by-turn instruction text (instruction_generator.py's TEXT_TEMPLATES,
// reused as-is, never recalculated here) bakes a meters figure straight
// into the sentence, e.g. "Turn left at Reception, then continue 12 m."
// or its Arabic/Hebrew equivalents. Rather than inventing a parallel
// instruction engine, this is a pure, frontend-only DISPLAY
// transformation: it trims the trailing distance clause each language's
// templates always add, leaving the exact same landmark/turn wording the
// backend generated (e.g. "Turn left at Reception."). The original text
// is always still available as `rawText` on the step object below — nothing
// is deleted, only what's rendered changes (Section 6/7: "frontend display
// transformation only").
const DISTANCE_CLAUSE_PATTERNS = [
  // en: "Continue straight for 12 m." -> "Continue straight."
  /\s+for\s+\d+(?:\.\d+)?\s*m\.\s*$/,
  // en: "Turn left at Reception, then continue 12 m." -> "...Reception."
  /,\s*then continue\s+\d+(?:\.\d+)?\s*m\.\s*$/,
  // ar: "تابع مستقيمًا لمسافة 12 م." -> "تابع مستقيمًا."
  /\s*لمسافة\s+\d+(?:\.\d+)?\s*م\.\s*$/,
  // ar: "انعطف يسارًا عند الاستقبال، ثم تابع 12 م." -> "...الاستقبال."
  /،\s*ثم تابع\s+\d+(?:\.\d+)?\s*م\.\s*$/,
  // he: "המשך ישר למרחק 12 מ׳." -> "המשך ישר."
  /\s*למרחק\s+\d+(?:\.\d+)?\s*מ[׳']\.\s*$/,
  // he: "פנה שמאלה ליד הקבלה, ולאחר מכן המשך 12 מ׳." -> "...הקבלה."
  /,\s*ולאחר מכן המשך\s+\d+(?:\.\d+)?\s*מ[׳']\.\s*$/,
];

export function stripInstructionDistanceClause(text) {
  const value = typeof text === 'string' ? text : '';
  if (!value) return value;

  for (const pattern of DISTANCE_CLAUSE_PATTERNS) {
    if (pattern.test(value)) {
      return `${value.replace(pattern, '')}.`;
    }
  }

  return value;
}

export function instructionToStep(instruction) {
  const rawText = instruction?.text || '';
  return {
    type: STEP_ICON_BY_INSTRUCTION_TYPE[instruction?.type] || 'info',
    // The cleaned, display-safe text — this is what the user actually
    // sees everywhere (current-instruction card, next-instruction
    // preview, full checklist).
    text: stripInstructionDistanceClause(rawText),
    // The original backend text, distance clause intact — kept only for
    // internal/debugging use (Section 7: "keep access to the original raw
    // route steps internally"), never rendered directly on the end-user
    // screen.
    rawText,
    // Raw backend turn classification (e.g. "left", "sharp_right",
    // "u_turn", "straight", "start", "arrive") — kept alongside the
    // RouteSteps icon key above so the big-arrow "current instruction"
    // card (Part 8) can pick a directional arrow, not just a generic
    // walk/turn/arrive icon. Never invented — passed straight through
    // from instruction_generator.py's classify_turn() output.
    direction: instruction?.type || null,
    // Only present on turn-type legs (instruction_generator.py's
    // `distance_meters`) — null for start/arrive/transition. Kept on the
    // step object for internal use (e.g. map rendering); the end-user UI
    // must never render this value directly (Section 3).
    distanceMeters: Number.isFinite(instruction?.distance_meters)
      ? instruction.distance_meters
      : null,
  };
}

// ── Next-instruction preview (Section 4.C) ──────────────────────────────────
// Selects the single next MEANINGFUL instruction to preview below the
// current-instruction card — never the whole remaining list. Crosses the
// floor boundary into the transition instruction when the current step is
// the last one on this floor, exactly mirroring the real route order the
// backend returned (never reordered, never invented).
export function getNextMeaningfulInstruction({
  currentFloorSteps,
  activeStep,
  isLastFloor,
  transitionInstructions,
  activeFloorIndex,
}) {
  const steps = Array.isArray(currentFloorSteps) ? currentFloorSteps : [];

  if (activeStep >= 0 && activeStep + 1 < steps.length) {
    return steps[activeStep + 1];
  }

  if (!isLastFloor) {
    const transition = (transitionInstructions || [])[activeFloorIndex];
    if (transition) {
      return instructionToStep(transition);
    }
  }

  return null;
}

// A stable key identifying "this exact route request" — used to decide
// whether a persisted in-progress navigation state (active floor,
// completed steps) is still safe to restore after a refresh (PHASE 13
// requirement #10). Deliberately does NOT include volatile progress state
// itself, only what defines "the same route request".
export function buildRouteStateKey({ startPointId, endPointId, optimizationMode, verticalPreference }) {
  return `${startPointId || ''}|${endPointId || ''}|${optimizationMode || 'shortest'}|${verticalPreference || 'any'}`;
}

// ── Overall (cross-floor) progress — Part 10 ────────────────────────────────
// Distinguishes ESTIMATED total time/distance (straight from the backend's
// path costs) from REMAINING estimated time/distance, which shrinks only as
// the user explicitly confirms steps — never from any assumed live
// position. `completedByFloor` is the exact same { [floorIndex]: Set } map
// IndoorNavigationScreen already keeps; summing every set's size (not just
// the active floor's) is deliberate — a step confirmed on an earlier floor
// stays confirmed even after advancing, so progress can only move forward.
export function computeOverallProgress({
  instructionGroups,
  completedByFloor,
  totalDistanceMeters,
  totalTimeSeconds,
}) {
  const groups = Array.isArray(instructionGroups) ? instructionGroups : [];
  const totalSteps = groups.reduce((sum, group) => sum + (group?.length || 0), 0);

  let completedSteps = 0;
  Object.values(completedByFloor || {}).forEach((set) => {
    completedSteps += set instanceof Set ? set.size : (Array.isArray(set) ? set.length : 0);
  });
  completedSteps = Math.min(completedSteps, totalSteps);

  const progressFraction = totalSteps > 0 ? completedSteps / totalSteps : 0;
  const remainingFraction = 1 - progressFraction;

  const remainingDistanceMeters = Number.isFinite(totalDistanceMeters)
    ? Math.max(0, totalDistanceMeters * remainingFraction)
    : null;
  const remainingTimeSeconds = Number.isFinite(totalTimeSeconds)
    ? Math.max(0, totalTimeSeconds * remainingFraction)
    : null;

  return {
    totalSteps,
    completedSteps,
    progressFraction,
    remainingDistanceMeters,
    remainingTimeSeconds,
  };
}

// True once every step in the given floor's step list has been marked
// completed — used to decide whether the transition-to-next-floor card
// should be enabled.
export function isFloorComplete(stepCount, completedIndexSet) {
  if (!stepCount) return true;
  if (!completedIndexSet) return false;
  for (let i = 0; i < stepCount; i += 1) {
    if (!completedIndexSet.has(i)) return false;
  }
  return true;
}
