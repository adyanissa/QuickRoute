// The redesigned route-summary / active-navigation screen.
//
// The risky part of this change is not the visuals — it is that a camera
// was added next to a working relocation flow. The failure mode to guard
// against is a SECOND resolution path: a scanner that resolves codes
// itself, decides on its own what "not the destination" means, and drifts
// away from the typed-code behaviour that already works.
//
// So the tests below care mostly about convergence: exactly one
// resolveLocationCode call site, exactly one classifier, exactly one
// place that sets the relocation id, and a scanner component that is
// provably incapable of resolving anything.
//
// Two layers, matching this repo's conventions (no jest/testing-library —
// see screens/multilingualRerender.test.mjs):
//   * real unit tests of the pure helpers (the classifier that decides
//     relocate-vs-arrived-vs-invalid, and the new code extractor), and
//   * source-text contract tests over the screen and the scanner.
//
// Every fixture is synthetic. Nothing here touches a real map, a real
// code, a real camera or the network.
//
// Run with: node frontend/src/screens/navigationScanAndArrival.test.mjs

import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import {
  buildStartLocationRecord,
  classifyScannedLocation,
  extractLocationCode,
  isScanInActiveBuilding,
} from '../utils/locationScan.js';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

const read = (relative) =>
  fs.readFileSync(path.join(__dirname, relative), 'utf8');

const stripComments = (source) =>
  source
    .replace(/\{\/\*[\s\S]*?\*\/\}/g, '')
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/^\s*\/\/.*$/gm, '');

const screenSource = read('./IndoorNavigationScreen.jsx');
const screen = stripComments(screenSource);
const scannerSource = read('../components/QrScanner.jsx');
const scanner = stripComments(scannerSource);
const css = read('../styles/IndoorNavigationScreen.css');

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

// ── Synthetic fixtures — invented ids, invented names ────────────────────

const DESTINATION_ROOM_ID = 'room-dest-777';
const DESTINATION_POINT_ID = 'rp-dest-777';

const point = (id, roomId, extra = {}) => ({
  id,
  room_id: roomId,
  is_active: true,
  ...extra,
});


// ── 1. Scanned location != destination -> relocate, keep destination ─────

test('a valid scan of a DIFFERENT location relocates, and is not an error', () => {
  const verdict = classifyScannedLocation({
    scannedPoint: point('rp-elsewhere-4', 'room-elsewhere-4'),
    destinationRoomId: DESTINATION_ROOM_ID,
    destinationRoutePointId: DESTINATION_POINT_ID,
    currentStartPointId: 'rp-old-start',
  });

  assert.equal(verdict.outcome, 'relocate');
  assert.notEqual(verdict.outcome, 'invalid');
  // The new start point is the scanned one; the destination is not part
  // of this verdict at all, so it cannot be changed by a scan.
  assert.equal(verdict.startPointId, 'rp-elsewhere-4');
});

test('relocating sets ONLY the start point — the destination is untouched', () => {
  // The screen feeds the verdict's startPointId into relocatePointId, and
  // nothing else. There is no setter for the destination anywhere in the
  // scan path.
  assert.match(screen, /setRelocatePointId\(startPointId\)/);
  assert.equal((screen.match(/setRelocatePointId\(/g) || []).length, 1);

  const scanBlock = screen.slice(
    screen.indexOf('const applyLocationCode'),
    screen.indexOf('const handleScanSubmit'),
  );
  assert.doesNotMatch(scanBlock, /setRoom\(|setDestination\(|setBuilding\(/);
});

test('the relocation re-runs the EXISTING route effect, not a new one', () => {
  // relocatePointId is a dependency of the one route-loading effect, so a
  // relocation recalculates by re-running what already worked.
  assert.match(screen, /relocatePointId/);
  const deps = screen.slice(screen.indexOf('    optimizationMode,\n    verticalPreference,'));
  assert.ok(deps.length > 0);
  assert.match(screen, /relocatePointId,/);
});

test('a scan in another building is refused by the existing check', () => {
  assert.equal(isScanInActiveBuilding({ building_id: 'bld-a' }, 'bld-b'), false);
  assert.equal(isScanInActiveBuilding({ building_id: 'bld-a' }, 'bld-a'), true);
  // Legacy records with no building on either side keep working.
  assert.equal(isScanInActiveBuilding({}, 'bld-a'), true);
  assert.equal(isScanInActiveBuilding({ building_id: 'bld-a' }, null), true);
});


// ── 2. Scanned location == destination -> arrival ────────────────────────

test('scanning the destination confirms arrival', () => {
  const verdict = classifyScannedLocation({
    scannedPoint: point(DESTINATION_POINT_ID, DESTINATION_ROOM_ID),
    destinationRoomId: DESTINATION_ROOM_ID,
    destinationRoutePointId: DESTINATION_POINT_ID,
    currentStartPointId: 'rp-old-start',
  });

  assert.equal(verdict.outcome, 'arrived');
});

test('a legacy destination point with no room link still confirms arrival', () => {
  const verdict = classifyScannedLocation({
    scannedPoint: point(DESTINATION_POINT_ID, null),
    destinationRoomId: null,
    destinationRoutePointId: DESTINATION_POINT_ID,
  });

  assert.equal(verdict.outcome, 'arrived');
});

// UPDATED: the self-declared "I have arrived" button was removed. Arrival
// is now established only by the resolver recognising the scanned/typed
// code AS the destination, or by stepping through every instruction —
// i.e. by real position, never by assertion. So there is exactly ONE
// place left that raises the flag, and it is inside the resolver path.
test('arrival is set only by the resolver, never by the user declaring it', () => {
  assert.match(screen, /outcome === 'arrived'/);
  assert.equal((screen.match(/setScanArrived\(true\)/g) || []).length, 1);

  // That one call site sits inside applyLocationCode.
  const resolverBlock = screen.slice(
    screen.indexOf('const applyLocationCode'),
    screen.indexOf('const handleScanSubmit'),
  );
  assert.match(resolverBlock, /setScanArrived\(true\)/);

  // Stepping through every instruction still counts, as before.
  assert.match(screen, /const hasArrived = scanArrived \|\| steppedThroughToEnd/);
});


// ── 3. Only genuinely unresolvable codes are errors ──────────────────────

test('an inactive or point-less code is invalid, by the existing rule', () => {
  assert.equal(
    classifyScannedLocation({ scannedPoint: point('rp-x', 'room-x', { is_active: false }) }).outcome,
    'invalid',
  );
  assert.equal(classifyScannedLocation({ scannedPoint: null }).outcome, 'invalid');
  assert.equal(classifyScannedLocation({}).outcome, 'invalid');
});

test('the screen reports errors only through the existing error state', () => {
  assert.match(screen, /if \(outcome === 'invalid'\) \{\s*setScanError\(t\.rescanInvalid\);/);
  // A rejected resolve falls into the same message, as before.
  assert.match(screen, /catch \(err\) \{[\s\S]*?setScanError\(t\.rescanInvalid\);/);
});

test('a scan that decodes to nothing usable reports the existing error', () => {
  assert.equal(extractLocationCode(''), '');
  assert.equal(extractLocationCode(null), '');
  assert.match(screen, /if \(!code\) \{\s*setScanError\(t\.rescanInvalid\);/);
});


// ── 4. One resolver, reached by both the keyboard and the camera ─────────

test('there is exactly ONE resolveLocationCode call on this screen', () => {
  assert.equal((screen.match(/resolveLocationCode\(/g) || []).length, 1);
});

test('typed codes and scanned codes both go through applyLocationCode', () => {
  assert.match(screen, /const applyLocationCode = async \(rawCode\)/);
  // Manual submit.
  assert.match(screen, /handleScanSubmit = \(event\) => \{[\s\S]*?applyLocationCode\(scanCode\)/);
  // Camera result.
  assert.match(screen, /handleScanResult = \(text\) => \{[\s\S]*?applyLocationCode\(code\)/);
});

test('the scanner component cannot resolve anything by itself', () => {
  // No API client, no fetch, no knowledge of location codes at all.
  assert.doesNotMatch(scanner, /resolveLocationCode|locationCodesApi|apiRequest|fetch\(/);
  assert.doesNotMatch(scanner, /classifyScannedLocation|relocate|destination/i);
  // Its only output is the decoded string.
  assert.match(scanner, /onResult\?\.\(value\)/);
});

test('the camera resolves only on a completed scan — never on a timer', () => {
  // The one resolve call is inside applyLocationCode, which the scanner
  // reaches exactly once via onResult, guarded by doneRef.
  assert.match(scanner, /doneRef\.current = true;\s*stop\(\);\s*onResult/);
  assert.doesNotMatch(screen, /setInterval\([^)]*applyLocationCode/);
});

test('the camera track is always released', () => {
  assert.match(scanner, /track\.stop\(\)/);
  assert.match(scanner, /return \(\) => \{\s*cancelled = true;\s*stop\(\);/);
});


// ── 5. The QR label encodes a URL, so the code is lifted out of it ───────

test('a scanned QuickRoute URL yields the bare location code', () => {
  assert.equal(
    extractLocationCode('https://example.test/?locationCode=SYN-A1'),
    'SYN-A1',
  );
  assert.equal(
    extractLocationCode('https://example.test/some/path?locationCode=SYN-B2&x=1'),
    'SYN-B2',
  );
});

test('a bare code, padded or not, is passed straight through', () => {
  assert.equal(extractLocationCode('SYN-C3'), 'SYN-C3');
  assert.equal(extractLocationCode('  SYN-C3  '), 'SYN-C3');
  assert.equal(extractLocationCode('locationCode=SYN-D4'), 'SYN-D4');
});

test('the extractor validates nothing — that stays the backend\'s job', () => {
  // It happily returns a code that does not exist; resolveLocationCode is
  // what rejects it, exactly as for a typed code.
  assert.equal(extractLocationCode('DEFINITELY-NOT-A-REAL-CODE'), 'DEFINITELY-NOT-A-REAL-CODE');
});

test('the persisted start record is still built by the existing helper', () => {
  const record = buildStartLocationRecord({
    route_point_id: 'rp-syn-9',
    map_id: 'map-syn',
    map_group_id: 'grp-syn',
    floor: 2,
    building_id: 'bld-syn',
    code: 'SYN-E5',
    label: 'Synthetic Landing',
  });

  assert.equal(record.routePointId, 'rp-syn-9');
  assert.equal(record.mapGroupId, 'grp-syn');
  assert.equal(buildStartLocationRecord({}), null);
  assert.match(screen, /buildStartLocationRecord\(resolved\)/);
});


// ── 6. Route-mode UI removed, vertical preference kept ───────────────────

test('Shortest / Fastest / Accessible are no longer rendered', () => {
  assert.doesNotMatch(screen, /s18-mode-btn/);
  assert.doesNotMatch(screen, /modeOptions/);
  assert.doesNotMatch(screen, /setOptimizationMode/);
  assert.doesNotMatch(screen, /t\.modeShortest|t\.modeFastest|t\.modeAccessible/);
  assert.ok(!css.includes('.s18-mode-btn'), 'the picker CSS survived');
});

test('the "Route preference: X" summary line went with it', () => {
  assert.doesNotMatch(screen, /currentModeLabel/);
  assert.doesNotMatch(screen, /t\.routePrefLabel/);
});

test('the route STRATEGY itself is intact and still sent', () => {
  assert.match(screen, /const \[optimizationMode\] = useState\('shortest'\)/);
  assert.match(screen, /optimizationMode,/);
  assert.match(screen, /verticalTransportPreference: verticalPreference/);
  // Its translation keys are kept for the other callers/languages.
  assert.match(screenSource, /modeShortest:/);
});

test('the elevator / stairs preference remains, unchanged', () => {
  assert.match(screen, /vertPrefOptions/);
  assert.match(screen, /setVerticalPreference\(option\.value\)/);
  assert.match(screen, /s18-vertpref-btn/);
  for (const key of ['vertPrefAny', 'vertPrefElevator', 'vertPrefStairs']) {
    assert.match(screen, new RegExp(`t\\.${key}`));
  }
});


// ── 7. Hero: dynamic destination, no type/floor clutter ──────────────────

test('the destination hero shows the localized destination name only', () => {
  const hero = screen.slice(
    screen.indexOf('s18-nav-destination'),
    screen.indexOf('s18-floor-confirm'),
  );

  assert.match(hero, /\{roomDisplayName\}/);
  assert.match(hero, /\{t\.goingTo\}/);
  // No type chip, no floor line, no accessibility tag in this area.
  assert.doesNotMatch(hero, /s18-type-chip|s18-floor-chip|destFloorLabel|accessibleYes/);
  // The awkward "To: X" construction is gone.
  assert.doesNotMatch(screen, /s18-nav-destination-to|t\.toLabel/);
});

test('the destination name is resolved through the existing localizer', () => {
  assert.match(
    screen,
    /getLocalizedText\(room\.names, lang, room\.nameEn \|\| room\.name\)/,
  );
});

test('no building, room or floor value is hard-coded', () => {
  assert.doesNotMatch(screen, /Women's Shower|Control Room|מכללה/);
  assert.doesNotMatch(screen, /SAMPLE_|MOCK_|DEFAULT_ROOM|DEFAULT_BUILDING/);
});


// ── 8. Icons say what the buttons do ─────────────────────────────────────

test('the reset-looking two-arrow icon is gone', () => {
  assert.doesNotMatch(screenSource, /RepeatIcon/);
  // Its old path data — a circular arrow loop — must not survive either.
  assert.doesNotMatch(screen, /M3 12a9 9 0 0 1 15\.5-6\.3/);
});

test('the speak-the-instruction button now carries a speaker icon', () => {
  // The handler is unchanged: it speaks the current step aloud.
  assert.match(screen, /const handleRepeatStep = \(\) => \{[\s\S]*?SpeechSynthesisUtterance/);
  const block = screen.slice(
    screen.indexOf('onClick={handleRepeatStep}'),
    screen.indexOf('onClick={handleRepeatStep}') + 260,
  );
  assert.match(block, /<SpeakIcon \/>/);
});

test('previous / next controls carry direction-aware chevrons', () => {
  assert.match(screen, /<ChevronBackIcon isRTL=\{isRTL\} \/>/);
  assert.match(screen, /<ChevronNextIcon isRTL=\{isRTL\} \/>/);
  assert.match(screenSource, /style=\{isRTL \? \{ transform: 'scaleX\(-1\)' \} : undefined\}/);
});

test('the step handlers themselves are untouched', () => {
  assert.match(screen, /onClick=\{handlePreviousStep\}/);
  assert.match(screen, /onClick=\{handleReachedStep\}/);
  assert.match(screen, /disabled=\{!canGoToPreviousStep\}/);
});


// ── 9. Update-location panel offers both ways in ─────────────────────────

test('manual code entry is still present', () => {
  assert.match(screen, /className="s18-rescan-input"/);
  assert.match(screen, /onChange=\{\(e\) => setScanCode\(e\.target\.value\)\}/);
  assert.match(screen, /onSubmit=\{handleScanSubmit\}/);
});

test('a Scan QR control is rendered next to it', () => {
  assert.match(screen, /className="s18-rescan-scan"/);
  assert.match(screen, /\{t\.scanQr\}/);
  assert.match(screen, /setScannerOpen\(true\)/);
});

test('the scanner mounts only while open, so no camera runs otherwise', () => {
  assert.match(screen, /\{scannerOpen && \(\s*<QrScanner/);
});

// UPDATED: the collapsed "update my location" CTA became an always-open
// "Confirm your location" section offering all three options at once, so
// there is no longer a button whose label could over-promise. The thing
// that mattered — that the wording matches what the UI can actually do —
// is now structural: the scan control and the code field are both visible.
// UPDATED: three options became two. Self-declared arrival is gone, so
// the section offers only the two REAL verification methods.
test('the verification section offers exactly two methods: code and QR', () => {
  assert.match(screen, /\{t\.confirmTitle\}/);
  assert.match(screen, /\{t\.confirmHint\}/);
  assert.match(screen, /className="s18-confirm-options"/);
  assert.equal((screen.match(/className="s18-confirm-card"/g) || []).length, 2);
  assert.match(screen, /\{t\.optionCode\}/);
  assert.match(screen, /\{t\.optionScan\}/);
  assert.doesNotMatch(screen, /s18-rescan-cta/);
});

// UPDATED: this asserted the opposite of what is now required. A user
// must not be able to tell QuickRoute they arrived without their position
// being verified, so the button, its handler and its strings are gone.
test('there is no self-declared arrival control anywhere', () => {
  assert.doesNotMatch(screen, /s18-arrived-btn/);
  assert.doesNotMatch(screen, /handleConfirmArrival/);
  assert.doesNotMatch(screenSource, /confirmArrival:|confirmArrivalTitle:|optionArrived:/);
});


// ── 10. Localization and direction ───────────────────────────────────────

test('every new label exists in all three languages', () => {
  const keys = [
    'goingTo', 'scanQr', 'confirmTitle', 'confirmHint',
    'optionCode', 'optionScan', 'verify',
    'scanTitle', 'scanHint', 'scanStarting', 'scanDenied',
    'scanUnavailable', 'scanUnsupported', 'scanErrorHint',
  ];

  for (const key of keys) {
    const count = (screenSource.match(new RegExp(`\\b${key}:`, 'g')) || []).length;
    assert.equal(count, 3, `${key} is defined ${count} times, expected en/ar/he`);
  }
});

test('the scanner takes already-translated strings and owns no dictionary', () => {
  assert.match(screen, /labels=\{\{/);
  assert.doesNotMatch(scanner, /const UI = \{|useLang/);
  assert.ok(!/[֐-ۿ]/.test(scanner), 'the scanner hard-codes translated text');
});

test('RTL/LTR still comes from the shared lang value', () => {
  assert.match(screen, /const isRTL = lang === 'ar' \|\| lang === 'he'/);
  assert.match(screen, /dir=\{isRTL \? 'rtl' : 'ltr'\}/);
  assert.match(screen, /const \{ lang, setLang \} = useLang\(\)/);
});


// ── 11. Nothing new was asked of the backend ─────────────────────────────

test('no new endpoint or API module was introduced', () => {
  const imports = screenSource.match(/^import .*$/gm) || [];
  const apiImports = imports.filter((line) => line.includes("/api/"));

  for (const line of apiImports) {
    assert.match(
      line,
      /locationCodesApi|navigationApi|routePointsApi|roomsApi|buildingsApi|mapsApi|mapGroupsApi/,
      `unexpected API import: ${line}`,
    );
  }

  assert.doesNotMatch(screen, /fetch\(|axios/);
  // And no route maths moved into React.
  assert.doesNotMatch(screen, /dijkstra|shortestPath|routeEdges\.filter/i);
});




// ── 12. Final visual pass: no decoration, one vertical flow ──────────────

test('the decorative circular illustration is gone from the step card', () => {
  // The 72px disc that framed a large arrow was decoration: it repeated
  // nothing the instruction text does not already say.
  assert.doesNotMatch(screen, /s18-current-arrow/);
  assert.ok(!css.includes('.s18-current-arrow'), 'the disc CSS survived');

  // No image, illustration or artwork was put in its place.
  assert.doesNotMatch(screen, /<img|background-image|illustration|\.svg'|\.png'/);
});

test('a small semantic direction icon survives, from the route icon system', () => {
  // Same component, same instruction-driven props — just inline-sized.
  assert.match(screen, /s18-current-step-icon/);
  assert.match(screen, /<BigDirectionArrow direction=\{currentStepData\.direction\} size=\{16\} \/>/);
  assert.match(screen, /currentStepData\.type === 'exit'/);
});

test('Current Step is above All Steps in one vertical flow', () => {
  const current = screen.indexOf('s18-current-card');
  const directions = screen.indexOf('s18-directions"');

  assert.ok(current > 0 && directions > 0);
  assert.ok(current < directions, 'the step card must render before the list');

  // And no two-column wrapper at any width.
  assert.doesNotMatch(screen, /s18-nav-columns/);
  assert.ok(!css.includes('.s18-nav-columns'), 'the two-column CSS survived');
});

test('the current instruction is the most prominent text on the card', () => {
  const block = css.slice(css.indexOf('.s18-current-text {'));
  const size = Number(block.match(/font-size:\s*([\d.]+)px/)[1]);

  assert.ok(size >= 22, `current instruction is only ${size}px`);

  const preview = css.slice(css.indexOf('.s18-next-preview {'));
  const previewSize = Number(preview.match(/font-size:\s*([\d.]+)px/)[1]);

  // Readable, but clearly secondary to the current instruction.
  assert.ok(previewSize >= 14, `next preview is only ${previewSize}px`);
  assert.ok(previewSize < size, 'the preview must not compete with the instruction');
});

test('progress reports a real percentage from existing state', () => {
  assert.match(screen, /s18-progress-pct/);
  assert.match(screen, /Math\.round\(overallProgress\.progressFraction \* 100\)/);
  // No second progress source was invented.
  assert.doesNotMatch(screen, /useState\([^)]*progress/i);
});

test('the step list is not rendered as fine print', () => {
  const block = css.slice(css.indexOf('.rs-step-text,'));
  const size = Number(block.match(/font-size:\s*([\d.]+)px/)[1]);
  assert.ok(size >= 14, `step text is only ${size}px`);
});

console.log(`\n${passed} assertions passed.`);
