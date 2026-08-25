// Tests for the "Professional end-user indoor navigation experience"
// redesign of IndoorNavigationScreen.jsx (see task Section 13 for the
// required 21 scenarios this file covers).
//
// Two layers, matching this repo's existing convention (no jest/
// testing-library installed — see screens/destinationNavigability.test.mjs
// and screens/multilingualRerender.test.mjs):
//   1. Real unit tests of the new pure display-transformation helpers in
//      utils/multiFloorRouteHelpers.js (stripInstructionDistanceClause,
//      getNextMeaningfulInstruction) — these prove the actual logic works,
//      not just that some text exists somewhere.
//   2. Source-text contract tests confirming IndoorNavigationScreen.jsx
//      wires everything up: metrics hidden, badge/next-preview/progress
//      rendered, RTL correctness, floor transitions, arrival state, and
//      that nothing backend/admin was touched.

import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import {
  stripInstructionDistanceClause,
  getNextMeaningfulInstruction,
  instructionToStep,
} from '../utils/multiFloorRouteHelpers.js';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

function readFile(...parts) {
  return fs.readFileSync(path.join(__dirname, ...parts), 'utf8');
}

const screenSource = readFile('IndoorNavigationScreen.jsx');
const helpersSource = readFile('..', 'utils', 'multiFloorRouteHelpers.js');
const navigationApiSource = readFile('..', 'api', 'navigationApi.js');

let passed = 0;
function test(name, fn) {
  try {
    fn();
    passed += 1;
    console.log(`PASS: ${name}`);
  } catch (err) {
    console.error(`FAIL: ${name}`);
    console.error(err);
    process.exitCode = 1;
  }
}

// ── Pure-function tests: stripInstructionDistanceClause ─────────────────────

test('stripInstructionDistanceClause: strips the English "for N m." clause', () => {
  assert.equal(
    stripInstructionDistanceClause('Continue straight for 12 m.'),
    'Continue straight.',
  );
});

test('stripInstructionDistanceClause: strips the English ", then continue N m." clause, keeping the landmark', () => {
  assert.equal(
    stripInstructionDistanceClause('Turn left at Reception, then continue 12 m.'),
    'Turn left at Reception.',
  );
  assert.equal(
    stripInstructionDistanceClause('Turn right, then continue 5 m.'),
    'Turn right.',
  );
});

test('stripInstructionDistanceClause: strips the Arabic distance clauses', () => {
  assert.equal(
    stripInstructionDistanceClause('تابع مستقيمًا لمسافة 12 م.'),
    'تابع مستقيمًا.',
  );
  assert.equal(
    stripInstructionDistanceClause('انعطف يسارًا عند الاستقبال، ثم تابع 12 م.'),
    'انعطف يسارًا عند الاستقبال.',
  );
});

test('stripInstructionDistanceClause: strips the Hebrew distance clauses', () => {
  assert.equal(
    stripInstructionDistanceClause('המשך ישר למרחק 12 מ׳.'),
    'המשך ישר.',
  );
  assert.equal(
    stripInstructionDistanceClause('פנה שמאלה ליד הקבלה, ולאחר מכן המשך 12 מ׳.'),
    'פנה שמאלה ליד הקבלה.',
  );
});

test('stripInstructionDistanceClause: leaves distance-free text (arrive/transition/start) unchanged', () => {
  assert.equal(
    stripInstructionDistanceClause('You have arrived at Women’s Restroom.'),
    'You have arrived at Women’s Restroom.',
  );
  assert.equal(
    stripInstructionDistanceClause('Use the elevator and go to Floor 2.'),
    'Use the elevator and go to Floor 2.',
  );
  assert.equal(stripInstructionDistanceClause(''), '');
  // Non-string input (e.g. a missing instruction.text) safely coerces to
  // an empty string rather than throwing or returning null.
  assert.equal(stripInstructionDistanceClause(null), '');
});

test('instructionToStep: keeps the raw backend text (with distance) as rawText, only cleans the displayed text', () => {
  const step = instructionToStep({
    type: 'left',
    text: 'Turn left at Reception, then continue 12 m.',
    distance_meters: 12,
  });
  assert.equal(step.text, 'Turn left at Reception.');
  assert.equal(step.rawText, 'Turn left at Reception, then continue 12 m.');
  assert.equal(step.distanceMeters, 12);
});

// ── Pure-function tests: getNextMeaningfulInstruction ────────────────────────

test('getNextMeaningfulInstruction: returns the next step on the same floor when one exists', () => {
  const currentFloorSteps = [
    { type: 'exit', text: 'Proceed toward Reception.' },
    { type: 'turn', text: 'Turn left at Reception.' },
    { type: 'arrive', text: 'You have arrived.' },
  ];
  const next = getNextMeaningfulInstruction({
    currentFloorSteps,
    activeStep: 0,
    isLastFloor: true,
    transitionInstructions: [],
    activeFloorIndex: 0,
  });
  assert.equal(next.text, 'Turn left at Reception.');
});

test('getNextMeaningfulInstruction: crosses into the transition instruction when the floor’s steps are exhausted', () => {
  const currentFloorSteps = [
    { type: 'exit', text: 'Proceed toward the elevator.' },
    { type: 'arrive', text: 'You have arrived at the elevator.' },
  ];
  const next = getNextMeaningfulInstruction({
    currentFloorSteps,
    activeStep: 1, // last step on this floor
    isLastFloor: false,
    transitionInstructions: [{ type: 'transition', text: 'Use the elevator and go to Floor 2.' }],
    activeFloorIndex: 0,
  });
  assert.equal(next.text, 'Use the elevator and go to Floor 2.');
});

test('getNextMeaningfulInstruction: returns null once there is truly nothing next (last step of the last floor)', () => {
  const currentFloorSteps = [{ type: 'arrive', text: 'You have arrived.' }];
  const next = getNextMeaningfulInstruction({
    currentFloorSteps,
    activeStep: 0,
    isLastFloor: true,
    transitionInstructions: [],
    activeFloorIndex: 0,
  });
  assert.equal(next, null);
});

// ── 1/2/3. Distance / ETA / estimated steps are never rendered ──────────────

test('IndoorNavigationScreen.jsx never renders total distance, ETA, or estimated step count', () => {
  // Regexes require the literal call syntax "name(" — this file's own
  // explanatory comments legitimately mention formatDistance/formatTime/
  // estimateSteps BY NAME (prose, no trailing paren) to document why they
  // were intentionally removed from this screen; only an actual call
  // would mean the metric is still being rendered.
  assert.doesNotMatch(screenSource, /formatDistance\(/);
  assert.doesNotMatch(screenSource, /formatTime\(/);
  assert.doesNotMatch(screenSource, /estimateSteps\(/);
  assert.doesNotMatch(screenSource, /t\.estimatedSteps/);
  assert.doesNotMatch(screenSource, /t\.totalTimeLabel/);
  assert.doesNotMatch(screenSource, /t\.totalDistanceLabel/);
  assert.doesNotMatch(screenSource, /s18-current-distance/);
  assert.doesNotMatch(screenSource, /s18-current-remaining/);
});

// ── 4. Backend route data remains accepted unchanged ─────────────────────────

test('routeResult still stores the real backend distance/time fields untouched (never stripped from state)', () => {
  assert.match(screenSource, /routeResult\?\.total_distance_meters/);
  assert.match(screenSource, /routeResult\?\.total_estimated_time_seconds/);
  assert.match(helpersSource, /remainingDistanceMeters/);
  assert.match(helpersSource, /remainingTimeSeconds/);
});

// ── 5. Shortest-route badge ───────────────────────────────────────────────────

// UPDATED: the badge was removed outright. Visible directions already
// tell the user a route exists, and a standing "Shortest route
// calculated" line read as a precision claim about the route rather than
// a status. The rule it protected — never assert accuracy — is now
// satisfied by there being no such claim anywhere on the screen.
test('no route-calculated badge is rendered, in any language', () => {
  assert.doesNotMatch(screenSource, /shortestRouteBadge:/);
  assert.doesNotMatch(screenSource, /t\.shortestRouteBadge/);
  assert.doesNotMatch(screenSource, /s18-route-badge/);
  // And nothing replaced it with an equivalent claim.
  assert.doesNotMatch(screenSource, /Shortest route calculated/);
});

// ── 6. Destination and floor are rendered (Section A) ────────────────────────

// UPDATED: the header used to read "To: <name>" with the destination's
// floor underneath. Both were removed on purpose — the "To:" prefix read
// awkwardly, and the floor/type metadata was clutter around the one thing
// the hero exists to state. The destination NAME is still the requirement,
// and it is still resolved the same way; only its presentation changed.
test('the destination header renders the localized destination name', () => {
  assert.match(screenSource, /s18-nav-destination"/);
  assert.match(screenSource, /s18-nav-dest-name/);
  assert.match(screenSource, /t\.goingTo/);
  assert.match(screenSource, /roomDisplayName/);
  // The removed pieces must stay removed.
  assert.doesNotMatch(screenSource, /s18-nav-destination-to/);
  assert.doesNotMatch(screenSource, /s18-nav-destination-floor/);
});

// ── 7/8. Current instruction + next-instruction preview ──────────────────────

test('the current instruction and next-instruction preview are both rendered', () => {
  assert.match(screenSource, /s18-current-text/);
  assert.match(screenSource, /currentStepData\.text/);
  assert.match(screenSource, /s18-next-preview/);
  assert.match(screenSource, /nextInstructionStep/);
  assert.match(screenSource, /t\.nextLabel/);
});

// ── 9. Progress shows "Step X of Y" (instruction count, cross-floor) ─────────

test('progress uses cross-floor instruction counts, never metres', () => {
  assert.match(screenSource, /t\.stepOf\(overallStepNumber, overallProgress\.totalSteps\)/);
  assert.match(screenSource, /overallStepNumber = Math\.min\(overallProgress\.completedSteps \+ 1/);
  assert.match(screenSource, /stepOf: \(i, n\) => `Step \$\{i\} of \$\{n\}`/);
});

// ── 10/11. Previous disabled on first step; advancing works ──────────────────

test('Previous is disabled when there is no confirmed previous step, and confirming advances activeStep', () => {
  assert.match(screenSource, /disabled=\{!canGoToPreviousStep\}/);
  assert.match(screenSource, /canGoToPreviousStep = previousStepIndex >= 0 && currentFloorCompleted\.has\(previousStepIndex\)/);
  assert.match(screenSource, /const activeStep = currentFloorSteps\.findIndex\(\(_, i\) => !currentFloorCompleted\.has\(i\)\)/);
  assert.match(screenSource, /handleReachedStep/);
});

// ── 12. Floor transition is an independent instruction/card ──────────────────

// UPDATED: the large standalone floor-transition CARD was removed. What
// it protected — that a floor change is surfaced and can be confirmed —
// is unchanged: the real transition instruction still renders, and the
// same handleAdvanceFloor still advances the stepper. Only the card's
// size and its floor/accessibility/estimated-time metadata rows went.
test('a floor change is still surfaced and still advances the stepper', () => {
  assert.match(screenSource, /s18-transition-bar/);
  assert.match(screenSource, /currentTransitionSegment \|\| currentTransitionInstruction/);
  assert.match(screenSource, /currentTransitionInstruction\?\.text/);
  assert.match(screenSource, /onClick=\{handleAdvanceFloor\}/);
  assert.match(screenSource, /t\.reachedFloor/);
  assert.match(screenSource, /youAreNowOnFloor/);
  // The removed clutter stays removed.
  assert.doesNotMatch(screenSource, /s18-transition-card/);
  assert.doesNotMatch(screenSource, /s18-transition-meta/);
});

// ── 13. Arrival state on the final step ───────────────────────────────────────

test('arrival state replaces the current-instruction card and shows destination + floor, no distance/ETA', () => {
  // UPDATED: the banner carries a --compact modifier now, so it no
  // longer spans the viewport; the class itself is unchanged.
  assert.match(screenSource, /s18-arrival s18-arrival--compact/);
  assert.match(screenSource, /t\.arrivedTitle/);
  // UPDATED: the arrival banner no longer repeats the destination's floor
  // — the destination name is the whole point of the state. The
  // no-distance/no-ETA rule below is unchanged and still enforced.
  assert.doesNotMatch(screenSource, /s18-arrival-floor/);
  // The arrival block itself must not reference time/distance formatting.
  const arrivalBlockMatch = screenSource.match(/\{hasArrived && \(\s*<div className="s18-arrival[^"]*">[\s\S]*?\)\}/);
  assert.ok(arrivalBlockMatch, 'expected to find the arrival banner JSX block');
  assert.doesNotMatch(arrivalBlockMatch[0], /formatTime/);
  assert.doesNotMatch(arrivalBlockMatch[0], /totalTimeMin/);
  assert.doesNotMatch(arrivalBlockMatch[0], /elapsedMin/);
});

// ── 14. Technical RoutePoint IDs are never shown ──────────────────────────────

test('the destination header displays the resolved display name, never a raw room/point id', () => {
  const destBlockMatch = screenSource.match(/\{room && \(\s*<div className="s18-nav-destination">[\s\S]*?<\/div>\s*\)\}/);
  assert.ok(destBlockMatch, 'expected to find the destination header JSX block');
  assert.doesNotMatch(destBlockMatch[0], /room\.id/);
  assert.doesNotMatch(destBlockMatch[0], /room\._id/);
  assert.match(destBlockMatch[0], /roomDisplayName/);
});

// ── 15. Semantic landmark names / localized instructions are used when
//        available — via the real backend lang parameter, never invented ──

test('calculateMultiFloorRoute is called with the current UI lang so backend-localized instruction/landmark text is used', () => {
  assert.match(screenSource, /calculateMultiFloorRoute\(\{[\s\S]*?lang,?\s*\}\)/);
  assert.match(navigationApiSource, /lang = "en"/);
  assert.match(navigationApiSource, /lang,/);
});

// ── 16/17/18. RTL for Arabic/Hebrew, LTR for English ──────────────────────────

test('isRTL is true for ar/he and false for en, and dir is driven by it', () => {
  assert.match(screenSource, /const isRTL = lang === 'ar' \|\| lang === 'he'/);
  assert.match(screenSource, /dir=\{isRTL \? 'rtl' : 'ltr'\}/);
});

// ── 19. Left/right instruction semantics are never reversed in RTL ───────────

test('the big direction arrow rotation table is independent of isRTL (physical left stays physically left)', () => {
  assert.match(
    screenSource,
    /deliberately ignores `isRTL`/,
  );
  const arrowFnMatch = screenSource.match(/const BigDirectionArrow = \(\{ direction, size = 56 \}\) => \{[\s\S]*?\n\};/);
  assert.ok(arrowFnMatch, 'expected to find BigDirectionArrow');
  assert.doesNotMatch(arrowFnMatch[0], /isRTL/);
});

// ── 20. The end-user screen has no architectural map at all (reversed by
//        the "Fix three connected end-user navigation issues" task —
//        see indoorNavigationMapVisibility.test.mjs for the full contract).
//        The underlying real route data is still used to drive the
//        text-only instruction list, via the same activeFloorIndex-
//        selected real segment the instructions/progress logic already
//        used when the map was present. ─────────────────────────────────

// The literal `floorSegments[activeFloorIndex]` expression no longer
// appears verbatim: it existed only to feed NavigationRouteMap's
// `segment` prop, which was removed along with the map itself (see the
// identical fix already applied in indoorNavigationMapVisibility.test.mjs
// — same root cause, same corrected approach reused here). The
// underlying "active floor selected via activeFloorIndex" contract is
// still fully intact, just expressed through the floor-tab list and the
// per-floor derived values (instructions, transitions) that this
// text-only screen actually needs.
test('no NavigationRouteMap is rendered, but the real activeFloorIndex-selected segment still drives instructions/progress', () => {
  assert.doesNotMatch(screenSource, /<NavigationRouteMap/);

  // Floor segments are still fully computed and iterated to render one
  // tab per floor.
  assert.match(screenSource, /floorSegments\.map\(\(segment, index\) => /);

  // The active floor tab is determined by comparing the array index to
  // activeFloorIndex, and switching floors updates that same state.
  assert.match(screenSource, /index === activeFloorIndex/);
  assert.match(screenSource, /onClick=\{\(\) => setActiveFloorIndex\(index\)\}/);

  // The current instruction shown to the user is derived from the
  // active floor's own instruction group.
  assert.match(screenSource, /instructionGroups\[activeFloorIndex\]/);

  // Floor transitions are indexed by the active floor, and the next
  // floor's segment is still read directly from floorSegments.
  assert.match(screenSource, /transitionSegments\[activeFloorIndex\]/);
  assert.match(screenSource, /floorSegments\[activeFloorIndex \+ 1\]/);
});

// ── 21. No backend, Dijkstra, graph, calibration, QR, or admin code was
//        touched by this screen/its new helpers/its new map component ──────

test('IndoorNavigationScreen.jsx and its new helpers never import or call backend/admin/calibration/QR/Dijkstra code', () => {
  // Deliberately NOT a bare substring/regex scan of the whole file — this
  // screen's own doc comments legitimately mention "AdminMapScreen.jsx"
  // (explaining where admin-only controls live instead) and "Dijkstra"
  // (explaining that routing stays backend-only) as PROSE, which a bare
  // /AdminMapScreen/ or /dijkstra/i match would wrongly flag. The real
  // contract is about imports/usage, not vocabulary, so each check below
  // targets an actual import statement, JSX usage, or call expression.
  [screenSource, helpersSource].forEach((source) => {
    // No import of, or JSX usage of, the admin map screen/its controls.
    assert.doesNotMatch(source, /from\s+['"][^'"]*AdminMapScreen['"]/);
    assert.doesNotMatch(source, /<AdminMapScreen\b/);

    // No import of, or call to, the calibration write endpoints.
    assert.doesNotMatch(source, /import\s*\{[^}]*\b(calibrateMapScale|copyMapCalibration)\b[^}]*\}/);
    assert.doesNotMatch(source, /\b(calibrateMapScale|copyMapCalibration)\s*\(/);

    // No QR-code module import/usage (this screen never scans/generates codes).
    assert.doesNotMatch(source, /from\s+['"][^'"]*qr[-_]?code[^'"]*['"]/i);

    // No client-side Dijkstra/pathfinding implementation or import —
    // routing stays entirely backend-side (Section 6).
    assert.doesNotMatch(source, /import\s*\{[^}]*dijkstra[^}]*\}/i);
    assert.doesNotMatch(source, /function\s+\w*[Dd]ijkstra\w*\s*\(/);
  });
});

console.log(`\n${passed} test(s) passed.`);
if (process.exitCode) {
  console.error('One or more tests FAILED.');
} else {
  console.log('All tests passed.');
}
