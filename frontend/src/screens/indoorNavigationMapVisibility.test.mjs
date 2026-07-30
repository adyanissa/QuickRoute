// Source-text contract test — REWRITTEN AGAIN for the "Fix three connected
// end-user navigation issues" task (Section 2: "Remove the map from
// end-user navigation UI").
//
// History of this file's contract, for context:
//   1. "QuickRoute User Experience Final Cleanup, Part 1" removed the
//      architectural map entirely — this file originally asserted that.
//   2. A later "professional navigation UX redesign" task explicitly
//      REVERSED that decision and reintroduced a redesigned map component
//      (components/NavigationRouteMap.jsx) — this file was rewritten to
//      assert the map WAS rendered.
//   3. THIS task reverses that decision again: map images have proven
//      unreliable for end users (the reported problem), so the end-user
//      IndoorNavigationScreen goes back to being entirely text/instruction
//      -based. This file is rewritten a second time to assert the map is
//      NOT rendered here — while confirming NavigationRouteMap.jsx itself
//      is left in place (not deleted, in case it's used elsewhere), map
//      ids/floor segments/route coordinates are never removed from state,
//      and AdminMapScreen.jsx is untouched.
//
// A full render test would need a React/DOM test runner, which this repo
// does not have installed (see the other *.test.mjs files' own comments on
// this). Instead — same pattern as components/fullMapWorkspaceLayout.test.mjs
// — this asserts directly on the relevant files' source text.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const screenSource = fs.readFileSync(path.join(__dirname, 'IndoorNavigationScreen.jsx'), 'utf8');
const mapComponentPath = path.join(__dirname, '..', 'components', 'NavigationRouteMap.jsx');

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

// 1. IndoorNavigationScreen.jsx no longer imports or renders
//    NavigationRouteMap — no architectural floor-plan image, route
//    polyline, or start/destination markers on the end-user screen.
test('IndoorNavigationScreen.jsx does not import or render NavigationRouteMap', () => {
  assert.doesNotMatch(
    screenSource,
    /import\s+NavigationRouteMap\s+from\s+['"]\.\.\/components\/NavigationRouteMap['"]/,
  );
  assert.doesNotMatch(screenSource, /<NavigationRouteMap/);
});

// 2. No zoom/pan map controls or floor-map "card" wrapper survive either.
test('IndoorNavigationScreen.jsx has no zoom/pan map controls or floor-map card markup', () => {
  assert.doesNotMatch(screenSource, /s18-map-zoom/);
  assert.doesNotMatch(screenSource, /s18-map-pan/);
  assert.doesNotMatch(screenSource, /s18-map-card/);
});

// 3. NavigationRouteMap.jsx itself is left in place, unmodified/undeleted —
//    only its use on THIS screen was removed (it may still be used
//    elsewhere, e.g. a future admin/preview surface).
test('components/NavigationRouteMap.jsx still exists on disk (not deleted)', () => {
  assert.ok(fs.existsSync(mapComponentPath), 'expected NavigationRouteMap.jsx to still exist');
});

// 4. Backend map/route information is never stripped from state — map ids,
//    floor segments, and route coordinates are still fully computed and
//    held, just never rendered as an image (Section 2: "Do not delete...
//    map IDs from route data; floor segments; route coordinates; backend
//    map information.").
//
//    The literal expression `floorSegments[activeFloorIndex]` no longer
//    appears verbatim: it existed ONLY to feed NavigationRouteMap's
//    `segment` prop (`segment={floorSegments[activeFloorIndex]}`), which
//    was removed along with the map itself. The underlying contract —
//    "the active floor is selected via activeFloorIndex, and every
//    per-floor derived value (instructions, transitions) is indexed by
//    it" — is still fully intact, just expressed through the floor-tab
//    list (`floorSegments.map((segment, index) => ...)`, highlighted via
//    `index === activeFloorIndex`) and `instructionGroups[activeFloorIndex]`
//    (the real per-floor data this text-only screen actually needs) rather
//    than a single raw-segment lookup no longer used by anything.
test('floorSegments/map data are still computed and held in state, and the active floor is still correctly selected by activeFloorIndex', () => {
  assert.match(screenSource, /getFloorSegments\(routeResult\?\.segments\)/);

  // Floor segments are still fully computed and available (never deleted
  // from state) — iterated to render one tab per floor.
  assert.match(screenSource, /floorSegments\.map\(\(segment, index\) => /);

  // The active floor tab is determined by comparing the array index to
  // activeFloorIndex — this IS "how the active floor segment is
  // currently selected" now that the raw segment object itself is only
  // ever needed by index, never as a standalone lookup.
  assert.match(screenSource, /index === activeFloorIndex/);
  assert.match(screenSource, /onClick=\{\(\) => setActiveFloorIndex\(index\)\}/);

  // The current instruction shown to the user is derived from the
  // active floor's own instruction group — the real "which floor's data
  // is currently displayed" contract for this text-only screen.
  assert.match(screenSource, /instructionGroups\[activeFloorIndex\]/);

  // Floor transitions (Section 2's "explicit floor-transition cards")
  // are also indexed by the active floor, and the next floor's segment
  // is still read directly from floorSegments for that purpose.
  assert.match(screenSource, /transitionSegments\[activeFloorIndex\]/);
  assert.match(screenSource, /floorSegments\[activeFloorIndex \+ 1\]/);
});

// 5. Distance/ETA/estimated-steps/remaining-metres/time remain hidden from
//    this screen (unchanged carry-over requirement from the prior redesign,
//    still explicitly required by this task's Section 2).
test('distance/ETA/estimated step count remain hidden, though still backend-calculated', () => {
  assert.doesNotMatch(screenSource, /formatDistance\(/);
  assert.doesNotMatch(screenSource, /formatTime\(/);
  assert.doesNotMatch(screenSource, /estimateSteps\(/);
  assert.match(screenSource, /routeResult\?\.total_distance_meters/);
  assert.match(screenSource, /routeResult\?\.total_estimated_time_seconds/);
});

// 6. Text-layout replacement pieces required by Section 2 are all present:
//    destination name, current floor, current instruction with a large
//    direction icon, next instruction, "Step X of Y", Previous/Next
//    controls, explicit floor-transition cards, arrival state, and a
//    Stop/End Navigation button.
test('the required text-only layout elements are all present', () => {
  assert.match(screenSource, /s18-nav-destination-to/); // destination name
  assert.match(screenSource, /s18-nav-destination-floor/); // current floor
  assert.match(screenSource, /BigDirectionArrow/); // large direction icon
  assert.match(screenSource, /s18-current-text/); // current instruction
  assert.match(screenSource, /s18-next-preview/); // next instruction
  assert.match(screenSource, /t\.stepOf\(overallStepNumber, overallProgress\.totalSteps\)/); // Step X of Y
  assert.match(screenSource, /handlePreviousStep/); // Previous control
  assert.match(screenSource, /handleReachedStep/); // Next/Reached control
  assert.match(screenSource, /s18-transition-card/); // floor-transition card
  assert.match(screenSource, /s18-arrival"/); // arrival state
  assert.match(screenSource, /s18-stop-nav-btn/); // Stop/End Navigation button
});

// 7. AdminMapScreen.jsx was never touched by this reversal.
test('AdminMapScreen.jsx is not referenced/imported by this screen', () => {
  assert.doesNotMatch(screenSource, /from\s+['"][^'"]*AdminMapScreen['"]/);
});

console.log(`\n${passed} test(s) passed.`);
if (process.exitCode) {
  console.error('One or more tests FAILED.');
} else {
  console.log('All tests passed.');
}
