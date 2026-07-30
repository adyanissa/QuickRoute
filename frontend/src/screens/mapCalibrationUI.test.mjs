// Tests for the minimal frontend "Calibrate Scale" admin UI added to
// AdminMapScreen.jsx, wired to the existing POST
// /api/maps/{map_id}/calibrate-scale endpoint.
//
// Same plain-node convention as the rest of this repo's *.test.mjs files
// (no jest/testing-library installed — see
// screens/multilingualRerender.test.mjs and
// screens/destinationNavigability.test.mjs). Two layers:
//   1. Real unit tests of computeOriginalImageCoords — the shared,
//      already-existing coordinate-transform helper this feature reuses
//      (never duplicates) for converting a click into RoutePoint-compatible
//      original-image pixel coordinates.
//   2. Source-text contract tests confirming AdminMapScreen.jsx actually
//      wires the calibration flow up correctly: reuses the shared helper,
//      never touches Dijkstra/graph topology, disables normal Add Point/
//      Draw Path while calibrating, validates the distance input, sends
//      the correct payload shape, restores normal interaction on cancel,
//      and displays the recalculated/skipped edge counts.

import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { computeOriginalImageCoords } from '../utils/destinationPlacement.js';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

function readScreen(filename) {
  return fs.readFileSync(path.join(__dirname, filename), 'utf8');
}

function readApi(filename) {
  return fs.readFileSync(
    path.join(__dirname, '..', 'api', filename),
    'utf8',
  );
}

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

const ADMIN_MAP_SCREEN = 'AdminMapScreen.jsx';

// ── 1. computeOriginalImageCoords: two selected points produce correct
//       image coordinates (Point A and Point B) ────────────────────────────

test('computeOriginalImageCoords: Point A and Point B resolve to correct original-image coordinates', () => {
  // 1000x500 natural image rendered at 500x250 on screen (2x scale),
  // offset by (100, 50) from the viewport.
  const rect = { rectLeft: 100, rectTop: 50, rectWidth: 500, rectHeight: 250 };
  const naturalSize = { naturalWidth: 1000, naturalHeight: 500 };

  const pointA = computeOriginalImageCoords({
    clientX: 350, // displayX = 250 -> 50% across
    clientY: 175, // displayY = 125 -> 50% down
    ...rect,
    ...naturalSize,
  });
  assert.deepEqual(pointA, { x: 500, y: 250 });

  const pointB = computeOriginalImageCoords({
    clientX: 140, // displayX = 40 -> 8% across
    clientY: 57, // displayY = 7 -> 2.8% down
    ...rect,
    ...naturalSize,
  });
  assert.deepEqual(pointB, { x: 80, y: 14 });

  // The two points must be distinguishable (never collapse to the same
  // pixel) — otherwise the calibration distance would be meaningless.
  assert.notDeepEqual(pointA, pointB);
});

// ── 2. Zoom/display resizing does not change the saved image coordinates
//       for the same physical spot on the map ──────────────────────────────

test('computeOriginalImageCoords: zoom/display resizing does not change the resolved native coordinate for the same relative click position', () => {
  const naturalSize = { naturalWidth: 1000, naturalHeight: 500 };

  // Same relative position (dead center of the image) clicked at three
  // different zoom levels / container sizes.
  const zoomedOut = computeOriginalImageCoords({
    clientX: 125,
    clientY: 62.5,
    rectLeft: 0,
    rectTop: 0,
    rectWidth: 250,
    rectHeight: 125,
    ...naturalSize,
  });

  const normal = computeOriginalImageCoords({
    clientX: 350,
    clientY: 175,
    rectLeft: 100,
    rectTop: 50,
    rectWidth: 500,
    rectHeight: 250,
    ...naturalSize,
  });

  const zoomedIn = computeOriginalImageCoords({
    clientX: 500,
    clientY: 250,
    rectLeft: 0,
    rectTop: 0,
    rectWidth: 1000,
    rectHeight: 500,
    ...naturalSize,
  });

  assert.deepEqual(zoomedOut, { x: 500, y: 250 });
  assert.deepEqual(normal, { x: 500, y: 250 });
  assert.deepEqual(zoomedIn, { x: 500, y: 250 });
});

// ── 3. AdminMapScreen.jsx reuses the shared helper, never duplicates the
//       coordinate transform for calibration ───────────────────────────────

test('AdminMapScreen.jsx: imports and reuses computeOriginalImageCoords for calibration instead of a duplicate transform', () => {
  const source = readScreen(ADMIN_MAP_SCREEN);
  assert.match(
    source,
    /import\s*\{\s*computeOriginalImageCoords\s*\}\s*from\s*['"]\.\.\/utils\/destinationPlacement['"]/,
  );

  // Used specifically inside the calibrate-mode branch of the click
  // handler, not just imported and left unused.
  const calibrateBranchMatch = source.match(
    /if \(mode === 'calibrate'\) \{[\s\S]*?\n {4}\}/,
  );
  assert.ok(calibrateBranchMatch, 'expected a mode === "calibrate" branch in handleFullMapClick');
  assert.match(calibrateBranchMatch[0], /computeOriginalImageCoords\(/);
});

// ── 4. calibrate mode disables normal Add Point / Draw Path click actions ──

test("AdminMapScreen.jsx: mode === 'calibrate' is checked before the normal Add Point click action, so calibration clicks never create a route point draft", () => {
  const source = readScreen(ADMIN_MAP_SCREEN);
  const handlerMatch = source.match(
    /const handleFullMapClick = \(event\) => \{[\s\S]*?\n  \};/,
  );
  assert.ok(handlerMatch, 'expected to find handleFullMapClick');
  const handlerBody = handlerMatch[0];

  const calibrateIndex = handlerBody.indexOf("mode === 'calibrate'");
  const setClickedPointIndex = handlerBody.indexOf('setClickedPoint({ x, y });');

  assert.ok(calibrateIndex > -1, 'expected a calibrate-mode check inside handleFullMapClick');
  assert.ok(setClickedPointIndex > -1, 'expected the normal Add Point fallback');
  assert.ok(
    calibrateIndex < setClickedPointIndex,
    'calibrate-mode branch must return before the normal Add Point click action runs',
  );
});

// ── 5. Invalid distance cannot be submitted ─────────────────────────────────

test('AdminMapScreen.jsx: calibration distance validation requires a finite number greater than 0', () => {
  const source = readScreen(ADMIN_MAP_SCREEN);
  assert.match(
    source,
    /isCalibrationDistanceValid\s*=[\s\S]*?Number\.isFinite\(parsedCalibrationDistance\)[\s\S]*?parsedCalibrationDistance > 0/,
  );
  // Submission is gated on both two selected points AND a valid distance.
  assert.match(
    source,
    /canSubmitCalibration\s*=\s*Boolean\(\s*[\s\S]*?calibrationPointA\s*&&\s*calibrationPointB\s*&&\s*isCalibrationDistanceValid/,
  );
  assert.match(source, /disabled=\{!canSubmitCalibration\}/);
});

// ── 6. The correct endpoint payload is sent ─────────────────────────────────

test('AdminMapScreen.jsx: submits the existing map id, both clicked coordinates, and the known distance to calibrateMapScale', () => {
  const source = readScreen(ADMIN_MAP_SCREEN);
  assert.match(
    source,
    /import\s*\{[^}]*calibrateMapScale[^}]*\}\s*from\s*['"]\.\.\/api\/mapsApi['"]/,
  );
  assert.match(
    source,
    /calibrateMapScale\(activeMap\.id,\s*\{\s*pointA:\s*calibrationPointA,\s*pointB:\s*calibrationPointB,\s*realDistanceMeters:\s*parsedCalibrationDistance,?\s*\}\)/,
  );
});

test('mapsApi.js: calibrateMapScale sends the exact backend contract (point_a_x/point_a_y/point_b_x/point_b_y/real_distance_meters)', () => {
  const source = readApi('mapsApi.js');
  assert.match(source, /point_a_x:\s*pointA\.x/);
  assert.match(source, /point_a_y:\s*pointA\.y/);
  assert.match(source, /point_b_x:\s*pointB\.x/);
  assert.match(source, /point_b_y:\s*pointB\.y/);
  assert.match(source, /real_distance_meters:\s*realDistanceMeters/);
  assert.match(source, /\/api\/maps\/\$\{mapId\}\/calibrate-scale/);
});

// ── 7. Cancel restores normal map interaction ───────────────────────────────

test('AdminMapScreen.jsx: Cancel Calibration returns to point mode and clears calibration state, restoring normal interaction', () => {
  const source = readScreen(ADMIN_MAP_SCREEN);
  const fnMatch = source.match(
    /const handleCancelCalibration = \(\) => \{[\s\S]*?\n {2}\};/,
  );
  assert.ok(fnMatch, 'expected handleCancelCalibration');
  assert.match(fnMatch[0], /setMode\('point'\)/);
  assert.match(fnMatch[0], /resetCalibrationPoints\(\)/);
});

// ── 8. Success shows recalculated/skipped counts ────────────────────────────

test('AdminMapScreen.jsx: shows "Calibration saved successfully", the scale, recalculated count, and skipped count only when > 0', () => {
  const source = readScreen(ADMIN_MAP_SCREEN);
  assert.match(source, /\{t\.calibrateSuccess\}/);
  assert.match(source, /t\.calibrateScaleResult\(calibrationResult\.scale\)/);
  assert.match(source, /t\.calibrateEdgesRecalculated\(calibrationResult\.edgesRecalculated\)/);
  assert.match(
    source,
    /calibrationResult\.edgesRecalculationSkipped > 0 &&[\s\S]{0,400}t\.calibrateEdgesSkipped\(/,
  );
});

test('mapsApi.js normalizeMap: exposes edgesRecalculated/edgesRecalculationSkipped from the calibration response, defaulting to 0 for every other Map response', () => {
  const source = readApi('mapsApi.js');
  assert.match(
    source,
    /edgesRecalculated:\s*Number\(map\.edges_recalculated \?\? map\.edgesRecalculated \?\? 0\)/,
  );
  assert.match(
    source,
    /edgesRecalculationSkipped:\s*Number\(\s*map\.edges_recalculation_skipped \?\? map\.edgesRecalculationSkipped \?\? 0,?\s*\)/,
  );
});

// ── 9. Existing behaviors are untouched: Dijkstra/graph endpoints are never
//       imported or called from this screen's calibration code, and the
//       original mode values still exist ───────────────────────────────────

test('AdminMapScreen.jsx: calibration code never imports or calls a route-generation/graph endpoint', () => {
  const source = readScreen(ADMIN_MAP_SCREEN);
  // Scoped tightly to the calibration HANDLERS block only (not the whole
  // file, and not the state-declarations block either) — the wider file
  // legitimately calls calculateRoute/createRouteEdge/createRoutePoint
  // elsewhere (Test Route, Add Point, Connect Place), which must stay
  // untouched by this feature; this assertion only guards that none of
  // that machinery was pulled into the new calibration code path itself.
  const calibrationSection = source.slice(
    source.indexOf('// ── Calibrate Scale mode handlers'),
    source.indexOf('// ── SVG overlay: point/edge lookups'),
  );
  assert.ok(calibrationSection.includes('handleSubmitCalibration'));
  assert.doesNotMatch(calibrationSection, /generateMapGraph/);
  assert.doesNotMatch(calibrationSection, /calculateRoute/);
  assert.doesNotMatch(calibrationSection, /createRouteEdge/);
  assert.doesNotMatch(calibrationSection, /createRoutePoint/);
});

test("AdminMapScreen.jsx: 'calibrate' is added as a new mode alongside the existing point/draw/test/connector modes (none removed)", () => {
  const source = readScreen(ADMIN_MAP_SCREEN);
  assert.match(source, /const \[mode, setMode\] = useState\('point'\);/);
  assert.match(source, /setMode\('calibrate'\)/);
  assert.match(source, /mode === 'draw'/);
  assert.match(source, /mode === 'test'/);
  assert.match(source, /mode === 'connector'/);
  assert.match(source, /mode === 'calibrate'/);
});

// ── 10. Translations exist in English, Arabic, and Hebrew ──────────────────

const REQUIRED_KEYS = [
  'calibrateMode',
  'calibrateInstructions',
  'calibratePointA',
  'calibratePointB',
  'calibrateDistanceTitle',
  'calibrateDistanceInvalid',
  'calibrateSubmit',
  'calibrateSuccess',
  'calibrateEdgesRecalculated',
  'calibrateEdgesSkipped',
  'calibrateCancel',
  'calibrateReset',
];

test('AdminMapScreen.jsx: every required calibration translation key exists in en, ar, and he blocks', () => {
  const source = readScreen(ADMIN_MAP_SCREEN);
  const enBlock = source.slice(source.indexOf('en: {'), source.indexOf('ar: {'));
  const arBlock = source.slice(source.indexOf('ar: {'), source.indexOf('he: {'));
  const heBlock = source.slice(source.indexOf('he: {'), source.length);

  REQUIRED_KEYS.forEach((key) => {
    assert.match(enBlock, new RegExp(`${key}:`), `missing ${key} in en block`);
    assert.match(arBlock, new RegExp(`${key}:`), `missing ${key} in ar block`);
    assert.match(heBlock, new RegExp(`${key}:`), `missing ${key} in he block`);
  });
});

test('AdminMapScreen.jsx: Arabic calibration strings match the required phrases', () => {
  const source = readScreen(ADMIN_MAP_SCREEN);
  assert.match(source, /calibrateMode: 'معايرة مقياس الخريطة'/);
  assert.match(source, /calibrateInstructions: 'اختاري نقطتين على الخريطة'/);
  assert.match(source, /calibrateDistanceTitle: 'المسافة الحقيقية بالمتر'/);
  assert.match(source, /calibrateSuccess: 'تم حفظ المعايرة بنجاح'/);
  assert.match(source, /calibrateCancel: 'إلغاء المعايرة'/);
  assert.match(source, /calibrateReset: 'إعادة اختيار النقاط'/);
});

test('AdminMapScreen.jsx: Hebrew calibration strings match the required phrases', () => {
  const source = readScreen(ADMIN_MAP_SCREEN);
  assert.match(source, /calibrateMode: 'כיול קנה מידה'/);
  assert.match(source, /calibrateInstructions: 'בחר שתי נקודות במפה'/);
  assert.match(source, /calibrateDistanceTitle: 'מרחק אמיתי במטרים'/);
  assert.match(source, /calibrateSuccess: 'הכיול נשמר בהצלחה'/);
  assert.match(source, /calibrateCancel: 'ביטול כיול'/);
  assert.match(source, /calibrateReset: 'איפוס נקודות'/);
});

console.log(`\n${passed} test(s) passed.`);
if (process.exitCode) {
  console.error('Some tests FAILED.');
} else {
  console.log('All tests passed.');
}
