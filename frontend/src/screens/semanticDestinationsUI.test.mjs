// Tests for "Create Destinations from Approved Analysis" — the admin
// workflow that turns admin-approved semantic-analysis places/facilities
// into real Rooms + destination RoutePoints (Stage 1), including the
// nested-room ("Possible nested destination" / pass-through) review UI,
// added to AdminMapScreen.jsx.
//
// Same plain-node source-text contract-test convention as the rest of this
// repo's *.test.mjs files (no jest/testing-library installed — see
// autoConnectDestinationsUI.test.mjs, this feature's closest sibling in
// both scope, workflow shape (scan -> preview -> confirm -> result), and
// test style; Stage 2 — the actual nested access RouteEdge — reuses the
// EXISTING Auto Connect Destinations apply endpoint rather than a new one,
// so a couple of these tests also touch that feature's own proposal row).
//
// Covers spec scenarios 32-48:
//  32. toolbar button exists
//  33. preview performs no write
//  34. approved items appear in preview
//  35. temporary overlays appear
//  36. existing-point vs needs-manual-placement is distinguishable
//      (this codebase's real placement_source set — see
//      schemas/semantic_destination_schema.py's own docstring for why
//      there is no door/centroid data to distinguish here)
//  37. multilingual names reviewable
//  38. nested relationship visible
//  39. pass-through requires explicit confirmation
//  40. nested-parent candidate is never conflated with the independent
//      "this room itself may be passed through" toggle
//  41. rejecting excludes from apply
//  42. apply sends only accepted items
//  43. existing manual Add Point flow is untouched
//  44. result summary renders
//  45. Auto Connect's own proposal UI understands nested destinations
//  46. all EN/AR/HE strings exist
//  47. existing Semantic Analysis/Sync Rooms/Auto Connect/Delete
//      Connection/Draw Walkable Path modes remain functional
//  48. Stage 1 handlers never call Stage 2's edge-creation APIs directly

import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

function readScreen(filename) {
  return fs.readFileSync(path.join(__dirname, filename), 'utf8');
}

function readApi(filename) {
  return fs.readFileSync(path.join(__dirname, '..', 'api', filename), 'utf8');
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

// ── 32. Toolbar button exists ───────────────────────────────────────────────

// The mode controls are entries in the draggable toolbox's data-driven
// `mapToolGroups` array now, not inline buttons in a fixed toolbar.
function toolboxConfigSlice(src) {
  const start = src.indexOf('const mapToolGroups = [');
  assert.notEqual(start, -1, 'expected the mapToolGroups toolbox config');
  const end = src.indexOf('\n  ];', start);
  assert.notEqual(end, -1, 'expected the mapToolGroups config to terminate');
  return src.slice(start, end);
}

test('AdminMapScreen.jsx: a "Create Destinations from Approved Analysis" toolbox entry exists, rendering t.semanticDestMode', () => {
  const toolbox = toolboxConfigSlice(source);

  assert.match(toolbox, /handleStartSemanticDestinations\(\)/);
  // A short label is preferred where one exists, falling back to the full
  // string, so both spellings are acceptable.
  assert.match(toolbox, /label:\s*t\.semanticDestMode(Short)?/);
  assert.match(
    toolbox,
    /id:\s*'semantic-destinations'[\s\S]*?handleStartSemanticDestinations\(\)/,
  );
});

test("AdminMapScreen.jsx: clicking the button sets mode to 'semantic-destinations', a new value distinct from every other mode", () => {
  assert.match(source, /setMode\('semantic-destinations'\)/);
  assert.match(source, /mode === 'semantic-destinations'/);
  // None of the pre-existing modes were removed.
  assert.match(source, /mode === 'auto-connect'/);
  assert.match(source, /mode === 'draw'/);
  assert.match(source, /mode === 'delete-connection'/);
});

test('AdminMapScreen.jsx: handleStartSemanticDestinations enters semantic-destinations mode, clears prior apply-result/manual-placement state, and immediately triggers a fresh preview scan', () => {
  const fnMatch = source.match(
    /const handleStartSemanticDestinations = \(\) => \{[\s\S]*?\n  \};/,
  );
  assert.ok(fnMatch, 'expected handleStartSemanticDestinations');
  const body = fnMatch[0];

  assert.match(body, /setMode\('semantic-destinations'\)/);
  assert.match(body, /setSemanticDestApplyResult\(null\)/);
  assert.match(body, /setSemanticDestManualPlaceTargetId\(null\)/);
  assert.match(body, /runSemanticDestPreview\(\);/);
});

// ── 33. Preview performs no write ───────────────────────────────────────────

test('AdminMapScreen.jsx: runSemanticDestPreview only calls previewSemanticDestinations — never applySemanticDestinations', () => {
  const fnMatch = source.match(
    /const runSemanticDestPreview = async \(\) => \{[\s\S]*?\n  \};/,
  );
  assert.ok(fnMatch, 'expected runSemanticDestPreview');
  const body = fnMatch[0];

  assert.match(body, /await previewSemanticDestinations\(/);
  assert.doesNotMatch(body, /applySemanticDestinations/);
});

test('AdminMapScreen.jsx: imports previewSemanticDestinations and applySemanticDestinations from the existing mapAnalysisApi module (no new API module introduced)', () => {
  // Bounded via indexOf on the exact closing line, then checked backward to
  // the nearest preceding "import {" — more robust than a single lazy
  // regex spanning the whole 260KB+ file, which could in principle latch
  // onto an unrelated earlier "import {" block.
  const closer = "} from '../api/mapAnalysisApi';";
  const closerIndex = source.indexOf(closer);
  assert.ok(closerIndex > -1, 'expected the mapAnalysisApi import to close with this exact line');
  const openerIndex = source.lastIndexOf('import {', closerIndex);
  assert.ok(openerIndex > -1, 'expected a preceding import { for this block');
  const importBlock = source.slice(openerIndex, closerIndex + closer.length);

  assert.match(importBlock, /previewSemanticDestinations/);
  assert.match(importBlock, /applySemanticDestinations/);
});

test('mapAnalysisApi.js: previewSemanticDestinations POSTs to the preview endpoint and applySemanticDestinations POSTs to a separate apply endpoint', () => {
  const apiSource = readApi('mapAnalysisApi.js');
  assert.match(apiSource, /export async function previewSemanticDestinations\(/);
  assert.match(apiSource, /\/semantic-analysis\/destinations\/preview/);
  assert.match(apiSource, /export async function applySemanticDestinations\(/);
  assert.match(apiSource, /\/semantic-analysis\/destinations\/apply/);
});

// ── 34. Approved items appear in preview ────────────────────────────────────

test('AdminMapScreen.jsx: runSemanticDestPreview maps every response.proposals entry into local review state (localStatus/x/y/confirmNested/allowTransitThrough), never dropping excluded items silently', () => {
  const fnMatch = source.match(
    /const runSemanticDestPreview = async \(\) => \{[\s\S]*?\n  \};/,
  );
  const body = fnMatch[0];

  assert.match(body, /response\.proposals \|\| \[\]/);
  assert.match(body, /localStatus: proposal\.excluded \? 'excluded' : 'pending'/);
  assert.match(body, /x: proposal\.proposed_x/);
  assert.match(body, /y: proposal\.proposed_y/);
  assert.match(body, /confirmNested: false/);
  assert.match(body, /allowTransitThrough: false/);
  assert.match(body, /setSemanticDestProposals\(proposals\)/);
  assert.match(body, /setSemanticDestPhase\('preview'\)/);
});

// ── 35. Proposals render as temporary overlays only ─────────────────────────

function getSemanticDestOverlaySection() {
  // The FIRST "mode === 'semantic-destinations' &&" occurrence in the file
  // is this overlay block — every later occurrence (the four workspace
  // panels) is further down, after the routePoints marker comment below.
  const start = source.indexOf("mode === 'semantic-destinations' &&");
  const end = source.indexOf('{/* Existing saved route points */}');
  assert.ok(start > -1, 'expected the semantic-destinations proposal overlay to exist');
  assert.ok(end > -1 && end > start, 'expected the routePoints marker section to follow it');
  return source.slice(start, end);
}

test('AdminMapScreen.jsx: proposed destination locations are drawn as a temporary SVG overlay resolved from semanticDestProposals state only, gated on mode, and never mutate routePoints/rooms state', () => {
  const body = getSemanticDestOverlaySection();

  assert.match(body, /<circle/);
  assert.match(body, /proposal\.localStatus !== 'rejected'/);
  assert.match(body, /proposal\.localStatus !== 'excluded'/);
  assert.doesNotMatch(body, /setRoutePoints/);
  assert.doesNotMatch(body, /setRooms/);
});

// ── 36. Existing-point vs needs-manual-placement is distinguishable ────────

test('AdminMapScreen.jsx: the preview panel shows a distinct message for placement_source === "needs_manual_placement" vs an existing linked point, and only offers manual on-map picking for the former', () => {
  const start = source.indexOf('{semanticDestProposals.map((proposal) => (');
  // The panel's primary actions live in its FloatingToolPanel `footer`
  // prop, declared before the children — so the rows end at the panel's
  // closing tag, not at the Review-complete button.
  const end = source.indexOf('</FloatingToolPanel>', start);
  assert.ok(start > -1 && end > start, 'expected the semantic destination proposal row block');
  const body = source.slice(start, end);

  assert.match(body, /proposal\.placement_source === 'needs_manual_placement'/);
  assert.match(body, /t\.semanticDestNeedsLocationReview/);
  assert.match(body, /t\.semanticDestExistingLocation/);
  assert.match(body, /handleStartManualSemanticPlacement\(proposal\.semantic_item_id\)/);
  assert.match(body, /t\.semanticDestPickLocation/);
});

// ── 37. Multilingual names reviewable ───────────────────────────────────────

test('AdminMapScreen.jsx: each proposal shows its Arabic/Hebrew names alongside the primary name, never only English', () => {
  const start = source.indexOf('{semanticDestProposals.map((proposal) => (');
  // The panel's primary actions live in its FloatingToolPanel `footer`
  // prop, declared before the children — so the rows end at the panel's
  // closing tag, not at the Review-complete button.
  const end = source.indexOf('</FloatingToolPanel>', start);
  const body = source.slice(start, end);

  assert.match(body, /proposal\.name_en \|\| proposal\.name_original \|\| proposal\.semantic_item_id/);
  assert.match(body, /\[proposal\.name_ar, proposal\.name_he\]\.filter\(Boolean\)\.join\(' \/ '\)/);
});

// ── 38. Nested relationship visible ─────────────────────────────────────────

test('AdminMapScreen.jsx: a proposal with a nested_parent_candidate renders the "Possible nested destination" section naming the candidate parent', () => {
  const start = source.indexOf('{semanticDestProposals.map((proposal) => (');
  // The panel's primary actions live in its FloatingToolPanel `footer`
  // prop, declared before the children — so the rows end at the panel's
  // closing tag, not at the Review-complete button.
  const end = source.indexOf('</FloatingToolPanel>', start);
  const body = source.slice(start, end);

  assert.match(body, /proposal\.nested_parent_candidate &&/);
  assert.match(body, /\{t\.semanticDestNestedTitle\}/);
  assert.match(body, /t\.semanticDestNestedLine\(proposal\.nested_parent_candidate\.name\)/);
});

// ── 39. Pass-through requires explicit confirmation ─────────────────────────

test('AdminMapScreen.jsx: confirmNested always starts false on a fresh preview, and only an explicit checkbox toggle (handleToggleSemanticNested) can set it true for one specific proposal', () => {
  const previewFnMatch = source.match(
    /const runSemanticDestPreview = async \(\) => \{[\s\S]*?\n  \};/,
  );
  assert.match(previewFnMatch[0], /confirmNested: false/);

  const toggleMatch = source.match(
    /const handleToggleSemanticNested = \(itemId, confirmed\) => \{[\s\S]*?\n  \};/,
  );
  assert.ok(toggleMatch, 'expected handleToggleSemanticNested');
  assert.match(
    toggleMatch[0],
    /proposal\.semantic_item_id === itemId\s*\?\s*\{ \.\.\.proposal, confirmNested: confirmed \}\s*:\s*proposal/,
  );

  const start = source.indexOf('{semanticDestProposals.map((proposal) => (');
  // The panel's primary actions live in its FloatingToolPanel `footer`
  // prop, declared before the children — so the rows end at the panel's
  // closing tag, not at the Review-complete button.
  const end = source.indexOf('</FloatingToolPanel>', start);
  const body = source.slice(start, end);
  assert.match(body, /checked=\{Boolean\(proposal\.confirmNested\)\}/);
  assert.match(
    body,
    /handleToggleSemanticNested\(\s*proposal\.semantic_item_id,\s*event\.target\.checked,\s*\)/,
  );
  assert.match(body, /\{t\.semanticDestConfirmNested\}/);

  // The exact required confirmation text (Section 10) is shown in the
  // confirming-step modal once at least one proposal has confirmNested set.
  assert.match(
    source,
    /semanticDestProposals\.some\(\(p\) => p\.confirmNested\)\s*\?\s*t\.semanticDestNestedConfirmBody/,
  );
});

// ── 40. Nested-parent candidate is never conflated with the independent
//        "this room may be passed through" toggle ─────────────────────────

test('AdminMapScreen.jsx: handleToggleSemanticAllowTransit is a separate handler/state field (allowTransitThrough) from handleToggleSemanticNested/confirmNested — confirming a child\'s nested parent never implicitly sets the parent\'s own pass-through flag from this row', () => {
  const allowMatch = source.match(
    /const handleToggleSemanticAllowTransit = \(itemId, allowed\) => \{[\s\S]*?\n  \};/,
  );
  assert.ok(allowMatch, 'expected handleToggleSemanticAllowTransit');
  assert.match(
    allowMatch[0],
    /proposal\.semantic_item_id === itemId\s*\?\s*\{ \.\.\.proposal, allowTransitThrough: allowed \}\s*:\s*proposal/,
  );

  // Confirms the apply payload keeps the two concepts independent: a
  // proposal's OWN allow_transit_through reflects only its own toggle,
  // while parent_semantic_item_id reflects only confirmNested.
  const applyMatch = source.match(
    /const handleConfirmSemanticDestApply = async \(\) => \{[\s\S]*?\n  \};/,
  );
  assert.match(applyMatch[0], /allow_transit_through: Boolean\(proposal\.allowTransitThrough\)/);
  assert.match(
    applyMatch[0],
    /parent_semantic_item_id:\s*\n?\s*proposal\.confirmNested && proposal\.nested_parent_candidate/,
  );
});

// ── 41. Rejecting excludes from apply ───────────────────────────────────────

test('AdminMapScreen.jsx: handleAcceptSemanticProposal / handleRejectSemanticProposal only change localStatus for the single matching semantic_item_id', () => {
  const acceptMatch = source.match(
    /const handleAcceptSemanticProposal = \(itemId\) => \{[\s\S]*?\n  \};/,
  );
  const rejectMatch = source.match(
    /const handleRejectSemanticProposal = \(itemId\) => \{[\s\S]*?\n  \};/,
  );
  assert.ok(acceptMatch, 'expected handleAcceptSemanticProposal');
  assert.ok(rejectMatch, 'expected handleRejectSemanticProposal');

  assert.match(
    acceptMatch[0],
    /proposal\.semantic_item_id === itemId\s*\?\s*\{ \.\.\.proposal, localStatus: 'accepted' \}\s*:\s*proposal/,
  );
  assert.match(
    rejectMatch[0],
    /proposal\.semantic_item_id === itemId\s*\?\s*\{ \.\.\.proposal, localStatus: 'rejected' \}\s*:\s*proposal/,
  );
});

// ── 42. Apply sends only accepted items ─────────────────────────────────────

test('AdminMapScreen.jsx: handleConfirmSemanticDestApply filters to only localStatus === "accepted" proposals and sends exactly the fields the backend apply contract expects', () => {
  const fnMatch = source.match(
    /const handleConfirmSemanticDestApply = async \(\) => \{[\s\S]*?\n  \};/,
  );
  assert.ok(fnMatch, 'expected handleConfirmSemanticDestApply');
  const body = fnMatch[0];

  assert.match(body, /proposal\.localStatus === 'accepted'/);
  assert.match(body, /semantic_item_id: proposal\.semantic_item_id/);
  assert.match(body, /entity_kind: proposal\.entity_kind/);
  assert.match(body, /x: proposal\.x/);
  assert.match(body, /y: proposal\.y/);
  assert.match(body, /await applySemanticDestinations\(/);

  // Refuses to call apply at all when nothing was accepted.
  assert.match(body, /if \(accepted\.length === 0\) \{/);
  assert.match(body, /setSemanticDestError\(t\.semanticDestNoAccepted\)/);
});

test('AdminMapScreen.jsx: a failed apply call never advances to the result phase and keeps the admin on the confirming step with an error message', () => {
  const fnMatch = source.match(
    /const handleConfirmSemanticDestApply = async \(\) => \{[\s\S]*?\n  \};/,
  );
  const body = fnMatch[0];

  const tryMatch = body.match(/try \{([\s\S]*?)\} catch \(error\) \{([\s\S]*?)\}\s*\};/);
  assert.ok(tryMatch, 'expected a try/catch structure');
  const [, tryBody, catchBody] = tryMatch;

  assert.match(tryBody, /setSemanticDestPhase\('result'\)/);
  assert.doesNotMatch(catchBody, /setSemanticDestPhase\('result'\)/);
  assert.match(catchBody, /setSemanticDestPhase\('confirming'\)/);
  assert.match(catchBody, /setSemanticDestError\(error\.message \|\| t\.semanticDestApplyFailed\)/);
});

// ── 43. Existing manual Add Point flow is untouched ─────────────────────────

test('AdminMapScreen.jsx: handleFullMapClick returns early for semantic-destinations mode (routing a click either to manual-placement selection or nowhere) before the normal Add Point fallback runs — a plain map click in this mode never falls through to the ordinary "add a new point" flow', () => {
  const handlerMatch = source.match(
    /const handleFullMapClick = \(event\) => \{[\s\S]*?\n  \};/,
  );
  assert.ok(handlerMatch, 'expected to find handleFullMapClick');
  const handlerBody = handlerMatch[0];

  const semanticIndex = handlerBody.indexOf("mode === 'semantic-destinations'");
  const setClickedPointIndex = handlerBody.indexOf('setClickedPoint({ x, y });');

  assert.ok(semanticIndex > -1, 'expected a semantic-destinations mode check inside handleFullMapClick');
  assert.ok(setClickedPointIndex > -1, 'expected the normal Add Point fallback to still exist');
  assert.ok(
    semanticIndex < setClickedPointIndex,
    'semantic-destinations branch must return before the normal Add Point click action runs',
  );

  // The manual-placement path itself only ever updates x/y on the ONE
  // targeted proposal — it never touches routePoints/rooms directly.
  const targetSlice = handlerBody.slice(semanticIndex, setClickedPointIndex);
  assert.match(targetSlice, /semanticDestManualPlaceTargetId/);
  assert.match(targetSlice, /proposal\.semantic_item_id === semanticDestManualPlaceTargetId/);
  assert.doesNotMatch(targetSlice, /setRoutePoints/);
});

// ── 44. Result summary renders ──────────────────────────────────────────────

test('AdminMapScreen.jsx: on a successful apply, the result phase is entered, the route graph is refreshed, and the result modal renders every required Section-19 summary line plus warnings', () => {
  const fnMatch = source.match(
    /const handleConfirmSemanticDestApply = async \(\) => \{[\s\S]*?\n  \};/,
  );
  const body = fnMatch[0];
  assert.match(body, /setSemanticDestApplyResult\(result\)/);
  assert.match(body, /await refreshRouteGraph\(activeMap\.id\)/);
  assert.match(body, /setSemanticDestPhase\('result'\)/);

  const resultStart = source.indexOf("semanticDestPhase === 'result' &&");
  const resultEnd = source.indexOf("{mode === 'draw' && panelPosition && (");
  assert.ok(resultStart > -1, 'expected the result-phase gate to exist');
  assert.ok(resultEnd > -1 && resultEnd > resultStart, 'expected the Draw Walkable Path panel gate to follow it');
  const resultModalBody = source.slice(resultStart, resultEnd);

  assert.match(resultModalBody, /\{t\.semanticDestResultTitle\}/);
  assert.match(resultModalBody, /t\.semanticDestResultRoomsLine\(semanticDestApplyResult\)/);
  assert.match(resultModalBody, /t\.semanticDestResultPointsLine\(semanticDestApplyResult\)/);
  assert.match(resultModalBody, /t\.semanticDestResultUpdatedLine\(semanticDestApplyResult\)/);
  assert.match(resultModalBody, /t\.semanticDestResultNestedLine\(semanticDestApplyResult\)/);
  assert.match(resultModalBody, /t\.semanticDestResultNeedsReviewLine\(semanticDestApplyResult\)/);
  assert.match(resultModalBody, /t\.semanticDestResultFailedLine\(semanticDestApplyResult\)/);
  assert.match(resultModalBody, /semanticDestApplyResult\.warnings/);
});

// ── 45. Auto Connect's own proposal UI understands nested destinations ────

test('AdminMapScreen.jsx: an Auto Connect proposal with is_nested_access renders a distinguishing badge in its own proposal row', () => {
  const start = source.indexOf('{autoConnectProposals.map((proposal) => {');
  const end = source.indexOf('</FloatingToolPanel>', start);
  assert.ok(start > -1 && end > start, 'expected the auto-connect proposal row block');
  const body = source.slice(start, end);

  assert.match(body, /proposal\.is_nested_access &&/);
  assert.match(body, /\{t\.autoConnectNestedAccessBadge\}/);
});

// ── 46. All EN/AR/HE strings exist ──────────────────────────────────────────

const REQUIRED_KEYS = [
  'semanticDestMode',
  'semanticDestScanning',
  'semanticDestPreviewTitle',
  'semanticDestManualPlaceInstructions',
  'semanticDestNothingToReview',
  'semanticDestExcluded',
  'semanticDestNeedsLocationReview',
  'semanticDestExistingLocation',
  'semanticDestNestedTitle',
  'semanticDestConfirmNested',
  'semanticDestAllowTransit',
  'semanticDestPickLocation',
  'semanticDestConfirmTitle',
  'semanticDestConfirmBody',
  'semanticDestNestedConfirmBody',
  'semanticDestCreateAccepted',
  'semanticDestResultTitle',
  'semanticDestPreviewFailed',
  'semanticDestNoAccepted',
  'semanticDestApplyFailed',
  'autoConnectNestedAccessBadge',
];

test('AdminMapScreen.jsx: every required semantic-destinations translation key exists in en, ar, and he blocks', () => {
  const enBlock = source.slice(source.indexOf('en: {'), source.indexOf('ar: {'));
  const arBlock = source.slice(source.indexOf('ar: {'), source.indexOf('he: {'));
  const heBlock = source.slice(source.indexOf('he: {'), source.length);

  REQUIRED_KEYS.forEach((key) => {
    assert.match(enBlock, new RegExp(`${key}:`), `missing ${key} in en block`);
    assert.match(arBlock, new RegExp(`${key}:`), `missing ${key} in ar block`);
    assert.match(heBlock, new RegExp(`${key}:`), `missing ${key} in he block`);
  });
});

test('AdminMapScreen.jsx: the exact required nested pass-through confirmation text (Section 10) is present verbatim in en/ar/he', () => {
  assert.match(
    source,
    /semanticDestNestedConfirmBody:\s*\n?\s*'Users will be allowed to pass through the outer room to reach the inner destination\.'/,
  );
  assert.match(
    source,
    /semanticDestNestedConfirmBody:\s*\n?\s*'سيُسمح للمستخدم بالمرور عبر الغرفة الخارجية للوصول إلى الوجهة الداخلية\.'/,
  );
  assert.match(
    source,
    /semanticDestNestedConfirmBody:\s*\n?\s*'המשתמשים יורשו לעבור דרך החדר החיצוני כדי להגיע ליעד הפנימי\.'/,
  );
});

// ── 47. Existing modes remain functional ────────────────────────────────────

test('AdminMapScreen.jsx: Semantic Analysis review link, Sync Rooms, Auto Connect Destinations, Delete Connection and Draw Walkable Path are all fully intact after adding Create Destinations from Approved Analysis', () => {
  // Tool labels are toolbox entries (`label: t.x`) rather than JSX
  // children now; the tools themselves are all still present.
  assert.match(source, /label:\s*t\.syncRoomsAction(Short)?/);
  assert.match(source, /label:\s*t\.autoConnectMode(Short)?/);
  assert.match(source, /label:\s*t\.deleteConnectionMode/);
  assert.match(source, /label:\s*t\.drawMode/);
  assert.match(source, /const handleStartAutoConnect = \(\) => \{/);
  assert.match(source, /const handleEdgeClickForDeletion = \(/);
});

// ── 48. Stage 1 handlers never call Stage 2's edge-creation APIs directly ──

test('AdminMapScreen.jsx: none of the semantic-destinations Stage-1 handlers call createRouteEdge / previewAutoConnectDestinations / applyAutoConnectDestinations directly — the actual access connection is always created afterward through the separate, existing Auto Connect Destinations workflow', () => {
  const sectionStart = source.indexOf('const runSemanticDestPreview = async () => {');
  const sectionEnd = source.indexOf('const handleCloseSemanticDestResult');
  assert.ok(sectionStart > -1 && sectionEnd > sectionStart, 'expected the semantic-destinations handlers block');
  const body = source.slice(sectionStart, sectionEnd);

  assert.doesNotMatch(body, /createRouteEdge/);
  assert.doesNotMatch(body, /previewAutoConnectDestinations/);
  assert.doesNotMatch(body, /applyAutoConnectDestinations/);
});

console.log(`\n${passed} test(s) passed.`);
if (process.exitCode) {
  console.error('Some tests FAILED.');
} else {
  console.log('All tests passed.');
}
