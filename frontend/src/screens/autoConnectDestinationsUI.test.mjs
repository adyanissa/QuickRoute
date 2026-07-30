// Tests for the "Auto Connect Destinations to Corridors" admin feature added
// to AdminMapScreen.jsx — a bulk preview-and-confirm workflow that proposes
// ordinary same-floor walkway RouteEdges between unconnected Room/Store
// destinations and nearby hallway/junction transit points, and only ever
// writes to MongoDB for pairs the admin explicitly accepts.
//
// Same plain-node source-text contract-test convention as the rest of this
// repo's *.test.mjs files (no jest/testing-library installed — see
// deleteConnectionUI.test.mjs and mapCalibrationUI.test.mjs, this feature's
// closest siblings in both scope and test style).
//
// Covers spec scenarios 18-29:
//  18. toolbar button exists
//  19. preview mode disables conflicting actions
//  20. proposals render as temporary overlays
//  21. preview does not call edge-creation API
//  22. accept/reject works independently
//  23. alternative candidate can be selected
//  24. cancel creates nothing
//  25. apply sends only accepted pairs
//  26. result summary is shown
//  27. RoutePoints remain visible
//  28. existing Delete Connection and Draw Walkable Path still work
//  29. all EN/AR/HE strings exist

import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

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
const source = readScreen(ADMIN_MAP_SCREEN);

// ── 18. Toolbar button exists ───────────────────────────────────────────────

test('AdminMapScreen.jsx: an Auto Connect Destinations toolbar button exists, rendering t.autoConnectMode', () => {
  // Bounded to the mode toolbar itself (between the Delete Connection button
  // and the Sync Rooms action button, its immediate neighbors) so this
  // can't accidentally match some unrelated <button> elsewhere in this
  // 260KB+ file.
  const toolbarSlice = source.slice(
    source.indexOf('{t.deleteConnectionMode}'),
    source.indexOf('{t.syncRoomsAction}'),
  );
  assert.match(toolbarSlice, /handleStartAutoConnect\(\)/);
  assert.match(toolbarSlice, /\{t\.autoConnectMode\}/);
  assert.match(
    toolbarSlice,
    /<button[\s\S]*?handleStartAutoConnect\(\)[\s\S]*?\{t\.autoConnectMode\}[\s\S]*?<\/button>/,
  );
});

test("AdminMapScreen.jsx: clicking the button sets mode to 'auto-connect', a new value distinct from every other mode", () => {
  assert.match(source, /const \[mode, setMode\] = useState\('point'\);/);
  assert.match(source, /setMode\('auto-connect'\)/);
  assert.match(source, /mode === 'auto-connect'/);
  // None of the pre-existing modes were removed.
  assert.match(source, /mode === 'draw'/);
  assert.match(source, /mode === 'test'/);
  assert.match(source, /mode === 'connector'/);
  assert.match(source, /mode === 'calibrate'/);
  assert.match(source, /mode === 'delete-connection'/);
});

test('AdminMapScreen.jsx: handleStartAutoConnect enters auto-connect mode, clears prior manual-pick/apply-result state, and immediately triggers a fresh preview scan', () => {
  const fnMatch = source.match(
    /const handleStartAutoConnect = \(\) => \{[\s\S]*?\n  \};/,
  );
  assert.ok(fnMatch, 'expected handleStartAutoConnect');
  const body = fnMatch[0];

  assert.match(body, /setMode\('auto-connect'\)/);
  assert.match(body, /setAutoConnectApplyResult\(null\)/);
  assert.match(body, /setAutoConnectManualPickTargetId\(null\)/);
  assert.match(body, /runAutoConnectPreview\(\);/);
});

// ── 19. Preview mode disables conflicting actions ───────────────────────────

test('AdminMapScreen.jsx: handleFullMapClick returns early for auto-connect mode before the normal Add Point fallback runs (a plain map click never creates a RoutePoint while in this mode)', () => {
  const handlerMatch = source.match(
    /const handleFullMapClick = \(event\) => \{[\s\S]*?\n  \};/,
  );
  assert.ok(handlerMatch, 'expected to find handleFullMapClick');
  const handlerBody = handlerMatch[0];

  const autoConnectIndex = handlerBody.indexOf("mode === 'auto-connect'");
  const setClickedPointIndex = handlerBody.indexOf('setClickedPoint({ x, y });');

  assert.ok(autoConnectIndex > -1, 'expected an auto-connect mode check inside handleFullMapClick');
  assert.ok(setClickedPointIndex > -1, 'expected the normal Add Point fallback to still exist');
  assert.ok(
    autoConnectIndex < setClickedPointIndex,
    'auto-connect branch must return before the normal Add Point click action runs',
  );
});

test('AdminMapScreen.jsx: every other toolbar mode button (Add Point/Draw/Test/Vertical Connections/Calibrate/Delete Connection) is mutually exclusive with auto-connect via the single shared mode state — switching to any of them changes mode away from \'auto-connect\', which hides every auto-connect panel', () => {
  // All four auto-connect workspace panels (scanning/preview/confirming/
  // result) are gated by `mode === 'auto-connect'`, so switching mode to
  // anything else is what "disables" them — the same mutual-exclusivity
  // mechanism already used by every other admin tool mode on this screen.
  const panelGates = [
    /mode === 'auto-connect' && autoConnectPhase === 'scanning'/,
    /mode === 'auto-connect' && autoConnectPhase === 'preview'/,
    /mode === 'auto-connect' && autoConnectPhase === 'confirming'/,
    /mode === 'auto-connect' &&\s*autoConnectPhase === 'result'/,
  ];
  panelGates.forEach((pattern) => {
    assert.match(source, pattern);
  });

  // Each of the other mode toolbar buttons unconditionally calls setMode
  // with its own mode value when clicked (point/draw/test/connector/
  // calibrate/delete-connection) — none of them are blocked by, or need to
  // know about, auto-connect mode; they simply take over `mode`.
  assert.match(source, /if \(mode !== 'point'\) \{\s*setMode\('point'\);/);
  assert.match(source, /if \(mode !== 'draw'\) \{\s*setMode\('draw'\);/);
  assert.match(source, /if \(mode !== 'test'\) \{\s*setMode\('test'\);/);
  assert.match(source, /if \(mode !== 'connector'\) \{\s*setMode\('connector'\);/);
  assert.match(source, /if \(mode !== 'calibrate'\) \{\s*setMode\('calibrate'\);/);
  assert.match(source, /if \(mode !== 'delete-connection'\) \{\s*setMode\('delete-connection'\);/);
});

// ── 20. Proposals render as temporary overlays only ─────────────────────────

// Bounded via indexOf on two unique, stable anchor strings rather than an
// exact-indentation regex (the delete-connection test file's own comment
// explains why: Python/JS have no reliable "end of block" token to
// brace-match against, so indexOf-slicing between two known landmarks is
// the more robust convention already used elsewhere in this repo's tests).
function getAutoConnectOverlaySection() {
  const start = source.indexOf(
    ".filter((proposal) => proposal.status === 'proposed')",
  );
  const end = source.indexOf('{/* Existing saved route points */}');
  assert.ok(start > -1, 'expected the auto-connect proposal filter to exist');
  assert.ok(end > -1 && end > start, 'expected the routePoints marker section to follow it');
  return source.slice(start, end);
}

test('AdminMapScreen.jsx: proposed connections are drawn as dashed SVG overlay lines resolved from existing in-memory state (pointsById via destination_point_id/selectedCandidateId), never a new fetch, and are only rendered while mode is auto-connect', () => {
  const body = getAutoConnectOverlaySection();

  assert.match(body, /pointsById\.get\(\s*proposal\.destination_point_id,?\s*\)/);
  assert.match(body, /pointsById\.get\(\s*proposal\.selectedCandidateId,?\s*\)/);
  assert.match(body, /strokeDasharray="6 6"/);
  assert.match(body, /<line/);

  // Gated on mode, immediately before the .filter/.map chain.
  const gateSlice = source.slice(
    source.lastIndexOf("mode === 'auto-connect'", source.indexOf(body)),
    source.indexOf(body) + 40,
  );
  assert.match(gateSlice, /mode === 'auto-connect'/);
});

test('AdminMapScreen.jsx: the proposal overlay block never mutates routeEdges (a preview overlay is not real edge data)', () => {
  const body = getAutoConnectOverlaySection();
  assert.doesNotMatch(body, /setRouteEdges/);
});

// ── 21. Preview does not call edge-creation API ─────────────────────────────

test('AdminMapScreen.jsx: runAutoConnectPreview only calls previewAutoConnectDestinations — never createRouteEdge or applyAutoConnectDestinations', () => {
  const fnMatch = source.match(
    /const runAutoConnectPreview = async \(scopeOverride\) => \{[\s\S]*?\n  \};/,
  );
  assert.ok(fnMatch, 'expected runAutoConnectPreview');
  const body = fnMatch[0];

  assert.match(body, /await previewAutoConnectDestinations\(\{/);
  assert.doesNotMatch(body, /createRouteEdge/);
  assert.doesNotMatch(body, /applyAutoConnectDestinations/);
});

test('AdminMapScreen.jsx: imports previewAutoConnectDestinations and applyAutoConnectDestinations from the existing routeEdgesApi module (no new API module introduced)', () => {
  assert.match(
    source,
    /import\s*\{[\s\S]*?previewAutoConnectDestinations[\s\S]*?\}\s*from\s*['"]\.\.\/api\/routeEdgesApi['"]/,
  );
  assert.match(
    source,
    /import\s*\{[\s\S]*?applyAutoConnectDestinations[\s\S]*?\}\s*from\s*['"]\.\.\/api\/routeEdgesApi['"]/,
  );
});

test('routeEdgesApi.js: previewAutoConnectDestinations POSTs to the preview endpoint and applyAutoConnectDestinations POSTs to a separate apply endpoint (existing, already-implemented contract)', () => {
  const apiSource = readApi('routeEdgesApi.js');
  assert.match(apiSource, /export function previewAutoConnectDestinations\(previewOptions\)/);
  assert.match(apiSource, /\/api\/route-edges\/auto-connect-destinations\/preview/);
  assert.match(apiSource, /export function applyAutoConnectDestinations\(applyOptions\)/);
  assert.match(apiSource, /\/api\/route-edges\/auto-connect-destinations\/apply/);
});

// ── 22. Accept/reject works independently ───────────────────────────────────

test('AdminMapScreen.jsx: handleAcceptProposal and handleRejectProposal only change localStatus for the single matching destination_point_id, leaving every other proposal untouched', () => {
  const acceptMatch = source.match(
    /const handleAcceptProposal = \(destinationId\) => \{[\s\S]*?\n  \};/,
  );
  const rejectMatch = source.match(
    /const handleRejectProposal = \(destinationId\) => \{[\s\S]*?\n  \};/,
  );
  assert.ok(acceptMatch, 'expected handleAcceptProposal');
  assert.ok(rejectMatch, 'expected handleRejectProposal');

  assert.match(
    acceptMatch[0],
    /proposal\.destination_point_id === destinationId\s*\?\s*\{ \.\.\.proposal, localStatus: 'accepted' \}\s*:\s*proposal/,
  );
  assert.match(
    rejectMatch[0],
    /proposal\.destination_point_id === destinationId\s*\?\s*\{ \.\.\.proposal, localStatus: 'rejected' \}\s*:\s*proposal/,
  );
});

// Bounded via indexOf on two unique, stable anchor strings (see the same
// convention used by getAutoConnectOverlaySection above) rather than an
// exact-indentation regex.
function getProposalRowSection() {
  const start = source.indexOf('{autoConnectProposals.map((proposal) => {');
  const end = source.indexOf('{t.autoConnectReviewComplete}');
  assert.ok(start > -1, 'expected the proposals.map row-rendering block to exist');
  assert.ok(end > -1 && end > start, 'expected the Review complete footer button to follow it');
  return source.slice(start, end);
}

test('AdminMapScreen.jsx: each proposal row wires its own Accept/Reject buttons to the corresponding handler using that exact proposal\'s destination_point_id', () => {
  const body = getProposalRowSection();

  assert.match(body, /onClick=\{\(\) =>\s*handleAcceptProposal\(proposal\.destination_point_id\)\s*\}/);
  assert.match(body, /onClick=\{\(\) =>\s*handleRejectProposal\(proposal\.destination_point_id\)\s*\}/);
  assert.match(body, /\{t\.autoConnectAccept\}/);
  assert.match(body, /\{t\.autoConnectReject\}/);
});

// ── 23. Alternative candidate can be selected ───────────────────────────────

test('AdminMapScreen.jsx: handleSelectAlternativeCandidate updates only the matching proposal\'s selectedCandidateId, and each candidate chip in the row wires to it with the real candidate.point_id', () => {
  const fnMatch = source.match(
    /const handleSelectAlternativeCandidate = \(destinationId, candidateId\) => \{[\s\S]*?\n  \};/,
  );
  assert.ok(fnMatch, 'expected handleSelectAlternativeCandidate');
  assert.match(
    fnMatch[0],
    /proposal\.destination_point_id === destinationId\s*\?\s*\{ \.\.\.proposal, selectedCandidateId: candidateId \}\s*:\s*proposal/,
  );

  const body = getProposalRowSection();
  assert.match(
    body,
    /handleSelectAlternativeCandidate\(\s*proposal\.destination_point_id,\s*candidate\.point_id,\s*\)/,
  );
});

test('AdminMapScreen.jsx: a manual on-map corridor pick is also supported — handleStartManualCorridorPick/selectManualCorridorPoint reject anything that is not a confirmed transit-candidate point type before accepting it', () => {
  assert.match(source, /const handleStartManualCorridorPick = \(destinationId\) => \{/);
  const selectMatch = source.match(
    /const selectManualCorridorPoint = \(point\) => \{[\s\S]*?\n  \};/,
  );
  assert.ok(selectMatch, 'expected selectManualCorridorPoint');
  assert.match(selectMatch[0], /AUTO_CONNECT_TRANSIT_TYPES\.has\(point\.point_type\)/);
  assert.match(selectMatch[0], /localStatus: 'accepted'/);
});

// ── 24. Cancel creates nothing ───────────────────────────────────────────────

test('AdminMapScreen.jsx: handleCancelAutoConnect never calls any create/apply API and always returns to point mode', () => {
  const fnMatch = source.match(
    /const handleCancelAutoConnect = \(\) => \{[\s\S]*?\n  \};/,
  );
  assert.ok(fnMatch, 'expected handleCancelAutoConnect');
  const body = fnMatch[0];

  assert.doesNotMatch(body, /applyAutoConnectDestinations/);
  assert.doesNotMatch(body, /createRouteEdge/);
  assert.doesNotMatch(body, /await /);
  assert.match(body, /setMode\('point'\)/);
  assert.match(body, /setAutoConnectPhase\('idle'\)/);
  assert.match(body, /setAutoConnectProposals\(\[\]\)/);
});

test('AdminMapScreen.jsx: Cancel is reachable both from the preview panel footer and the confirmation modal, both wired to handleCancelAutoConnect', () => {
  const previewFooterMatch = source.match(
    /onClick=\{handleCancelAutoConnect\}\s*style=\{\{ flex: 1 \}\}\s*>\s*\{t\.cancel\}/,
  );
  assert.ok(previewFooterMatch, 'expected the preview-panel footer Cancel button');

  const confirmModalMatch = source.match(
    /onClick=\{handleCancelAutoConnect\}\s*disabled=\{autoConnectPhase === 'applying'\}\s*>\s*\{t\.cancel\}/,
  );
  assert.ok(confirmModalMatch, 'expected the confirmation-modal Cancel button');
});

// ── 25. Apply sends only accepted pairs ─────────────────────────────────────

test('AdminMapScreen.jsx: handleConfirmAutoConnectApply filters to only localStatus === "accepted" proposals that have a selectedCandidateId, and sends only destination_point_id/corridor_point_id pairs', () => {
  const fnMatch = source.match(
    /const handleConfirmAutoConnectApply = async \(\) => \{[\s\S]*?\n  \};/,
  );
  assert.ok(fnMatch, 'expected handleConfirmAutoConnectApply');
  const body = fnMatch[0];

  assert.match(
    body,
    /proposal\.localStatus === 'accepted' && proposal\.selectedCandidateId/,
  );
  assert.match(body, /destination_point_id: proposal\.destination_point_id/);
  assert.match(body, /corridor_point_id: proposal\.selectedCandidateId/);
  assert.match(body, /await applyAutoConnectDestinations\(\{/);

  // Refuses to call apply at all when nothing was accepted.
  assert.match(body, /if \(accepted\.length === 0\) \{/);
  assert.match(body, /setAutoConnectError\(t\.autoConnectNoAccepted\)/);
});

test('AdminMapScreen.jsx: a failed apply call never advances to the result phase and keeps the admin on the confirming step with an error message', () => {
  const fnMatch = source.match(
    /const handleConfirmAutoConnectApply = async \(\) => \{[\s\S]*?\n  \};/,
  );
  const body = fnMatch[0];

  const tryMatch = body.match(/try \{([\s\S]*?)\} catch \(error\) \{([\s\S]*?)\}\s*\};/);
  assert.ok(tryMatch, 'expected a try/catch structure');
  const [, tryBody, catchBody] = tryMatch;

  assert.match(tryBody, /setAutoConnectPhase\('result'\)/);
  assert.doesNotMatch(catchBody, /setAutoConnectPhase\('result'\)/);
  assert.match(catchBody, /setAutoConnectPhase\('confirming'\)/);
  assert.match(catchBody, /setAutoConnectError\(error\.message \|\| t\.autoConnectApplyFailed\)/);
});

// ── 26. Result summary is shown ─────────────────────────────────────────────

test('AdminMapScreen.jsx: on a successful apply, the result phase is entered, RouteEdges are refreshed, and the result modal renders t.autoConnectResultLine(autoConnectApplyResult) plus any warnings', () => {
  const fnMatch = source.match(
    /const handleConfirmAutoConnectApply = async \(\) => \{[\s\S]*?\n  \};/,
  );
  const body = fnMatch[0];
  assert.match(body, /setAutoConnectApplyResult\(result\)/);
  assert.match(body, /await refreshRouteGraph\(activeMap\.id\)/);
  assert.match(body, /setAutoConnectPhase\('result'\)/);

  // Bounded via indexOf on two unique, stable anchor strings — the result
  // modal is the last auto-connect block before the pre-existing Draw
  // Walkable Path floating panel, which reliably marks its end.
  const resultStart = source.indexOf("autoConnectPhase === 'result' &&");
  const resultEnd = source.indexOf("{mode === 'draw' && panelPosition && (");
  assert.ok(resultStart > -1, 'expected the result-phase gate to exist');
  assert.ok(resultEnd > -1 && resultEnd > resultStart, 'expected the Draw Walkable Path panel gate to follow it');
  const resultModalBody = source.slice(resultStart, resultEnd);

  assert.match(resultModalBody, /\{t\.autoConnectResultTitle\}/);
  assert.match(resultModalBody, /t\.autoConnectResultLine\(autoConnectApplyResult\)/);
  assert.match(resultModalBody, /autoConnectApplyResult\.warnings/);
});

// ── 27. RoutePoints remain visible during preview ───────────────────────────

test('AdminMapScreen.jsx: the existing routePoints.map() marker rendering is not gated behind any mode check — every RoutePoint stays visible and unmodified while auto-connect preview is open', () => {
  const markerSectionMatch = source.match(
    /\{\/\* Existing saved route points \*\/\}\s*\{routePoints\.map\(\(point\) => \{/,
  );
  assert.ok(markerSectionMatch, 'expected the routePoints marker rendering block to be unconditional');

  // The only mode-specific behaviour on a point marker is which invisible
  // hit-target circle (if any) is layered on top — not whether the marker
  // itself renders.
  assert.match(source, /const isAutoConnectPickTarget =\s*mode === 'auto-connect' &&/);
});

// ── 28. Existing Delete Connection and Draw Walkable Path still work ───────

test('AdminMapScreen.jsx: Delete Connection mode (button, handlers, confirmation modal) is fully intact after adding Auto Connect Destinations', () => {
  assert.match(source, /setMode\('delete-connection'\)/);
  assert.match(source, /const handleEdgeClickForDeletion = \(/);
  assert.match(source, /const handleConfirmDeleteConnection = async \(\) => \{/);
  assert.match(source, /\{t\.deleteConnectionMode\}/);
});

test("AdminMapScreen.jsx: Draw Walkable Path mode (button, draft point flow) is fully intact after adding Auto Connect Destinations", () => {
  assert.match(source, /setMode\('draw'\);\s*setClickedPoint\(null\);\s*setPointName\(''\);/);
  assert.match(source, /\{t\.drawMode\}/);
  assert.match(source, /selectExistingPointForDraft/);
});

// ── 29. All EN/AR/HE strings exist ──────────────────────────────────────────

const REQUIRED_KEYS = [
  'autoConnectMode',
  'autoConnectPreviewTitle',
  'autoConnectAccept',
  'autoConnectReject',
  'autoConnectNeedsReview',
  'autoConnectAlreadyConnected',
  'autoConnectNoCorridorPointFound',
  'autoConnectAcceptAllHighConfidence',
  'autoConnectCreateAccepted',
  'autoConnectResultTitle',
  'autoConnectConfirmBody',
  'autoConnectConfirmTitle',
  'autoConnectScanning',
  'autoConnectScopeMap',
  'autoConnectScopeMapGroup',
  'autoConnectRejectAllLowConfidence',
  'autoConnectBackToPreview',
  'autoConnectApplying',
];

test('AdminMapScreen.jsx: every required Auto Connect Destinations translation key exists in en, ar, and he blocks', () => {
  const enBlock = source.slice(source.indexOf('en: {'), source.indexOf('ar: {'));
  const arBlock = source.slice(source.indexOf('ar: {'), source.indexOf('he: {'));
  const heBlock = source.slice(source.indexOf('he: {'), source.length);

  REQUIRED_KEYS.forEach((key) => {
    assert.match(enBlock, new RegExp(`${key}:`), `missing ${key} in en block`);
    assert.match(arBlock, new RegExp(`${key}:`), `missing ${key} in ar block`);
    assert.match(heBlock, new RegExp(`${key}:`), `missing ${key} in he block`);
  });
});

test('AdminMapScreen.jsx: English toolbar/confirmation strings match the spec exactly', () => {
  assert.match(source, /autoConnectMode: 'Auto Connect Destinations'/);
  assert.match(source, /autoConnectPreviewTitle: 'Preview Connections'/);
  assert.match(source, /autoConnectAccept: 'Accept'/);
  assert.match(source, /autoConnectReject: 'Reject'/);
  assert.match(source, /autoConnectNeedsReview: 'Needs review'/);
  assert.match(source, /autoConnectAlreadyConnected: 'Already connected'/);
  assert.match(source, /autoConnectNoCorridorPointFound: 'No corridor point found'/);
  assert.match(source, /autoConnectAcceptAllHighConfidence: 'Accept all high-confidence proposals'/);
  assert.match(source, /autoConnectCreateAccepted: 'Create Accepted Connections'/);
  assert.match(source, /autoConnectResultTitle: 'Connections created successfully'/);
  assert.match(
    source,
    /autoConnectConfirmBody:\s*'Only the accepted destination-to-corridor connections will be created\. Existing points and connections will not be changed\.'/,
  );
});

test('AdminMapScreen.jsx: Arabic toolbar/confirmation strings match the spec exactly', () => {
  assert.match(source, /autoConnectMode: 'ربط الوجهات تلقائيًا'/);
  assert.match(source, /autoConnectPreviewTitle: 'معاينة الروابط'/);
  assert.match(source, /autoConnectAccept: 'قبول'/);
  assert.match(source, /autoConnectReject: 'رفض'/);
  assert.match(source, /autoConnectNeedsReview: 'يحتاج إلى مراجعة'/);
  assert.match(source, /autoConnectAlreadyConnected: 'مربوط مسبقًا'/);
  assert.match(source, /autoConnectNoCorridorPointFound: 'لم يتم العثور على نقطة ممر'/);
  assert.match(source, /autoConnectAcceptAllHighConfidence: 'قبول جميع الاقتراحات عالية الثقة'/);
  assert.match(source, /autoConnectCreateAccepted: 'إنشاء الروابط المقبولة'/);
  assert.match(source, /autoConnectResultTitle: 'تم إنشاء الروابط بنجاح'/);
});

test('AdminMapScreen.jsx: Hebrew toolbar/confirmation strings match the spec exactly', () => {
  assert.match(source, /autoConnectMode: 'חיבור יעדים אוטומטי'/);
  assert.match(source, /autoConnectPreviewTitle: 'תצוגה מקדימה של חיבורים'/);
  assert.match(source, /autoConnectAccept: 'אישור'/);
  assert.match(source, /autoConnectReject: 'דחייה'/);
  assert.match(source, /autoConnectNeedsReview: 'דורש בדיקה'/);
  assert.match(source, /autoConnectAlreadyConnected: 'מחובר כבר'/);
  assert.match(source, /autoConnectNoCorridorPointFound: 'לא נמצאה נקודת מסדרון'/);
  assert.match(source, /autoConnectAcceptAllHighConfidence: 'אישור כל ההצעות בביטחון גבוה'/);
  assert.match(source, /autoConnectCreateAccepted: 'יצירת החיבורים שאושרו'/);
  assert.match(source, /autoConnectResultTitle: 'החיבורים נוצרו בהצלחה'/);
});

// ── Bonus safety check: no Dijkstra/graph-generation code was pulled into
//    any of the new handlers ─────────────────────────────────────────────────

test('AdminMapScreen.jsx: the auto-connect feature code never imports or calls a route-generation/Dijkstra endpoint directly', () => {
  const featureSection = source.slice(
    source.indexOf('// ── Auto Connect Destinations to Corridors handlers'),
    source.indexOf('const handleCloseAutoConnectResult'),
  );
  assert.ok(featureSection.includes('runAutoConnectPreview'));
  assert.ok(featureSection.includes('handleConfirmAutoConnectApply'));
  assert.doesNotMatch(featureSection, /generateMapGraph/);
  assert.doesNotMatch(featureSection, /calculateRoute/);
});

console.log(`\n${passed} test(s) passed.`);
if (process.exitCode) {
  console.error('Some tests FAILED.');
} else {
  console.log('All tests passed.');
}
