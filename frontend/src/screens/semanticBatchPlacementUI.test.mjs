// Tests for "Fast batch destination placement" ("Place All Destinations")
// added to AdminMapScreen.jsx's existing "Create Destinations from
// Approved Analysis" workflow. Same plain-node source-text contract-test
// convention as the rest of this repo's *.test.mjs files (no jest/
// testing-library installed) — see semanticDestinationsUI.test.mjs, this
// feature's own closest sibling and the file this one is deliberately
// kept separate from (that file's existing 48 scenarios are left
// completely untouched; this file only adds NEW coverage for the batch
// workflow layered on top).
//
// Covers the 16 required frontend scenarios:
//  1. Starting batch mode selects the first unresolved destination.
//  2. A map click stores x/y for the active destination.
//  3. The active destination changes automatically to the next item.
//  4. No separate Accept/OK action is required per destination.
//  5. Clicking directly on an existing RoutePoint still records the
//     placement click.
//  6. Coordinate conversion remains correct under zoom/pan.
//  7. Previous allows correction.
//  8. Undo removes the latest temporary placement.
//  9. Skip returns the item later.
//  10. Reject excludes the item from final save.
//  11. Progress counters are correct.
//  12. Final save remains disabled while accepted destinations are
//      missing locations.
//  13. One final confirmation submits the complete batch.
//  14. Refresh restores the local placement draft.
//  15. Successful save clears the local draft.
//  16. Frontend build succeeds (verified separately via `npm run build`,
//      not a source-text test — see the final report).

import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

function readScreen(filename) {
  return fs.readFileSync(path.join(__dirname, filename), 'utf8');
}

function readUtil(filename) {
  return fs.readFileSync(path.join(__dirname, '..', 'utils', filename), 'utf8');
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

function extractFunction(name, isAsync = false) {
  const pattern = isAsync
    ? new RegExp(`const ${name} = async \\([^)]*\\) => \\{[\\s\\S]*?\\n  \\};`)
    : new RegExp(`const ${name} = \\([^)]*\\) => \\{[\\s\\S]*?\\n  \\};`);
  const match = source.match(pattern);
  assert.ok(match, `expected to find ${name}`);
  return match[0];
}

// ── Section 1: "Place All Destinations" entry point ─────────────────────

test('AdminMapScreen.jsx: a "Place All Destinations" action exists, rendering t.semanticBatchPlaceAll and calling handleStartSemanticBatchPlacement', () => {
  assert.match(source, /handleStartSemanticBatchPlacement/);
  assert.match(source, /\{t\.semanticBatchPlaceAll\}/);
});

// ── 1. Starting batch mode selects the first unresolved destination ─────

test('AdminMapScreen.jsx: handleBeginFreshSemanticBatch builds the queue from buildBatchQueueItemIds and starts at index 0', () => {
  const body = extractFunction('handleBeginFreshSemanticBatch');
  assert.match(body, /buildBatchQueueItemIds\(semanticDestProposals\)/);
  assert.match(body, /setSemanticBatchQueue\(queueItemIds\)/);
  assert.match(body, /setSemanticBatchStatuses\(initialBatchStatuses\(queueItemIds\)\)/);
  assert.match(body, /setSemanticBatchIndex\(0\)/);
  assert.match(body, /setSemanticBatchActive\(true\)/);
});

test('AdminMapScreen.jsx: existing-linked-point proposals are auto-included (accepted) without ever entering the manual-placement queue', () => {
  const body = extractFunction('handleBeginFreshSemanticBatch');
  assert.match(body, /proposal\.placement_source !== 'needs_manual_placement'/);
  assert.match(body, /localStatus: 'accepted'/);
});

// ── 2. A map click stores x/y for the active destination ────────────────

test('AdminMapScreen.jsx: handleBatchDestinationMapClick assigns the clicked x/y to the CURRENT active queue item only', () => {
  const body = extractFunction('handleBatchDestinationMapClick');
  assert.match(body, /const activeItemId = semanticBatchQueue\[semanticBatchIndex\]/);
  assert.match(body, /candidate\.semantic_item_id === activeItemId/);
  assert.match(body, /\{ \.\.\.candidate, x, y, localStatus: 'accepted' \}/);
});

// ── 3. The active destination changes automatically to the next item ────

test('AdminMapScreen.jsx: handleBatchDestinationMapClick advances via findNextActiveIndex without any extra confirmation click', () => {
  const body = extractFunction('handleBatchDestinationMapClick');
  assert.match(body, /findNextActiveIndex\(semanticBatchQueue, nextStatuses, semanticBatchIndex\)/);
  assert.match(body, /setSemanticBatchIndex\(nextIndex\)/);
  // Opens the review screen automatically once nothing is left, rather
  // than requiring a manual "I'm done" action.
  assert.match(body, /nextIndex === -1/);
  assert.match(body, /setSemanticBatchReviewOpen\(true\)/);
});

// ── 4. No separate Accept/OK action is required per destination ─────────

test('AdminMapScreen.jsx: a batch placement click never calls the per-card handleAcceptSemanticProposal/handleRejectSemanticProposal handlers — placement itself is the only action needed', () => {
  const body = extractFunction('handleBatchDestinationMapClick');
  assert.doesNotMatch(body, /handleAcceptSemanticProposal/);
  assert.doesNotMatch(body, /handleRejectSemanticProposal/);
});

test('AdminMapScreen.jsx: the batch panel footer never renders a per-item Accept/OK button — only Previous/Skip/Reject/Undo/Change location/Exit', () => {
  const start = source.indexOf('title={t.semanticBatchPanelTitle}');
  const end = source.indexOf("mode === 'semantic-destinations' && semanticBatchActive && semanticBatchReviewOpen");
  assert.ok(start > -1 && end > start, 'expected the batch placement panel block');
  const body = source.slice(start, end);

  assert.match(body, /\{t\.semanticBatchPrevious\}/);
  assert.match(body, /\{t\.semanticBatchSkip\}/);
  assert.match(body, /\{t\.semanticBatchReject\}/);
  assert.match(body, /\{t\.semanticBatchUndo\}/);
  assert.match(body, /\{t\.semanticBatchChangeLocation\}/);
  assert.match(body, /\{t\.semanticBatchExit\}/);
  assert.doesNotMatch(body, /autoConnectAccept/);
});

// ── 5. Clicking directly on an existing RoutePoint still records the
//       placement click ────────────────────────────────────────────────

test('AdminMapScreen.jsx: existing RoutePoint markers only opt into pointerEvents "auto" for draw/auto-connect pick modes — never for semantic-destinations — so a click on one still reaches handleFullMapClick', () => {
  // isDrawTarget / isAutoConnectPickTarget are the only two conditions
  // this codebase uses to make a RoutePoint marker itself intercept a
  // click (see AdminMapScreen.jsx's own RoutePoint-rendering block) —
  // neither is ever gated on mode === 'semantic-destinations', so batch
  // placement clicks landing on top of an existing marker still fall
  // through to the image's own onClick exactly like any other map click.
  assert.doesNotMatch(source, /isDrawTarget[\s\S]{0,80}semantic-destinations/);
  assert.doesNotMatch(source, /semantic-destinations[\s\S]{0,80}pointerEvents:\s*'auto'/);
});

test('AdminMapScreen.jsx: handleFullMapClick routes to batch placement before any other semantic-destinations handling, with top priority inside that mode branch', () => {
  const handlerMatch = source.match(/const handleFullMapClick = \(event\) => \{[\s\S]*?\n  \};/);
  assert.ok(handlerMatch, 'expected to find handleFullMapClick');
  const body = handlerMatch[0];

  const semanticIndex = body.indexOf("mode === 'semantic-destinations'");
  const batchCheckIndex = body.indexOf('semanticBatchActive');
  const manualPlaceIndex = body.indexOf('semanticDestManualPlaceTargetId');
  const setClickedPointIndex = body.indexOf('setClickedPoint({ x, y });');

  assert.ok(semanticIndex > -1);
  assert.ok(batchCheckIndex > semanticIndex, 'batch check must be inside the semantic-destinations branch');
  assert.ok(
    batchCheckIndex < manualPlaceIndex,
    'batch placement must be checked BEFORE the older single-target Pick Location flow',
  );
  assert.ok(
    manualPlaceIndex < setClickedPointIndex,
    'both semantic-destinations paths must still return before the default Add Point fallback',
  );
  assert.match(body, /handleBatchDestinationMapClick\(x, y\)/);
});

// ── 6. Coordinate conversion remains correct under zoom/pan ─────────────

test('AdminMapScreen.jsx: the batch click handler receives x/y already computed from the shared naturalWidth/rect-ratio formula at the top of handleFullMapClick — it never re-derives coordinates from raw clientX/clientY itself', () => {
  const handlerMatch = source.match(/const handleFullMapClick = \(event\) => \{[\s\S]*?\n  \};/);
  const body = handlerMatch[0];

  // The one shared computation every mode (including batch placement)
  // is fed from — proven correct under zoom/pan/resize by
  // destinationPlacement.test.mjs's own coverage of the identical ratio
  // math in computeOriginalImageCoords.
  assert.match(body, /const scaleX = image\.naturalWidth \/ rect\.width;/);
  assert.match(body, /const scaleY = image\.naturalHeight \/ rect\.height;/);
  assert.match(body, /const x = Math\.round\(displayX \* scaleX\);/);
  assert.match(body, /const y = Math\.round\(displayY \* scaleY\);/);

  // The batch branch is textually AFTER this shared computation (uses
  // its result), never before it (which would mean acting on stale/raw
  // coordinates).
  const scaleIndex = body.indexOf('const scaleX = image.naturalWidth');
  const batchIndex = body.indexOf('handleBatchDestinationMapClick(x, y)');
  assert.ok(scaleIndex > -1 && batchIndex > scaleIndex);
});

test('destinationPlacement.js: computeOriginalImageCoords (the shared authoritative coordinate system) clamps to image bounds under any rect/zoom ratio', () => {
  const utilSource = readUtil('destinationPlacement.js');
  assert.match(utilSource, /Math\.min\(Math\.max\(x, 0\), naturalWidth\)/);
  assert.match(utilSource, /Math\.min\(Math\.max\(y, 0\), naturalHeight\)/);
});

// ── 7. Previous allows correction ────────────────────────────────────────

test('AdminMapScreen.jsx: handleBatchPrevious moves the active index back without changing any item\'s status (never destructive)', () => {
  const body = extractFunction('handleBatchPrevious');
  assert.match(body, /Math\.max\(0, previous - 1\)/);
  assert.doesNotMatch(body, /setSemanticBatchStatuses/);
});

test('AdminMapScreen.jsx: revisiting an already-placed item never silently overwrites it — only explicit "Change location" arms a re-click', () => {
  const body = extractFunction('handleBatchDestinationMapClick');
  assert.match(body, /currentStatus === 'placed' && !semanticBatchAwaitingReplace/);

  const changeLocationBody = extractFunction('handleBatchChangeLocation');
  assert.match(changeLocationBody, /setSemanticBatchAwaitingReplace\(true\)/);
});

// ── 8. Undo removes the latest temporary placement ───────────────────────

test('AdminMapScreen.jsx: handleBatchUndo restores the previous x/y/status from the history stack and pops exactly one entry', () => {
  const body = extractFunction('handleBatchUndo');
  assert.match(body, /semanticBatchHistory\[semanticBatchHistory\.length - 1\]/);
  assert.match(body, /x: last\.prevX/);
  assert.match(body, /y: last\.prevY/);
  assert.match(body, /previous\.slice\(0, -1\)/);
});

test('AdminMapScreen.jsx: every placement pushes exactly one history entry before mutating state, so Undo has something to restore', () => {
  const body = extractFunction('handleBatchDestinationMapClick');
  assert.match(body, /setSemanticBatchHistory\(\(previous\) => \[/);
  assert.match(body, /itemId: activeItemId/);
  assert.match(body, /prevStatus: currentStatus/);
});

// ── 9. Skip returns the item later ───────────────────────────────────────

test('AdminMapScreen.jsx: handleBatchSkip marks the item "skipped" (never "rejected") and advances via the same findNextActiveIndex that revisits skipped items', () => {
  const body = extractFunction('handleBatchSkip');
  assert.match(body, /\[activeItemId\]: 'skipped'/);
  assert.match(body, /findNextActiveIndex\(semanticBatchQueue, nextStatuses, semanticBatchIndex\)/);
});

// ── 10. Reject excludes the item from final save ─────────────────────────

test('AdminMapScreen.jsx: handleBatchReject sets localStatus "rejected" on the proposal itself, which buildBatchAcceptedPayload (used by Save All) excludes', () => {
  const body = extractFunction('handleBatchReject');
  assert.match(body, /candidate\.semantic_item_id === activeItemId\s*\n?\s*\? \{ \.\.\.candidate, localStatus: 'rejected' \}/);
  assert.match(body, /\[activeItemId\]: 'rejected'/);
});

// ── 11. Progress counters are correct ────────────────────────────────────

test('AdminMapScreen.jsx: the batch panel and review screen both render computeBatchProgress output via t.semanticBatchProgress* keys', () => {
  assert.match(source, /computeBatchProgress\(semanticBatchQueue, semanticBatchStatuses\)/);
  assert.match(source, /t\.semanticBatchProgressPlaced\(progress\.placed, progress\.total\)/);
  assert.match(source, /t\.semanticBatchProgressRemaining\(progress\.remaining\)/);
  assert.match(source, /t\.semanticBatchProgressRejected\(progress\.rejected\)/);
});

// ── 12. Final save remains disabled while accepted destinations are
//       missing locations ──────────────────────────────────────────────

test('AdminMapScreen.jsx: the "Save All Destinations" button in the review screen is disabled unless isBatchReadyToSave is true', () => {
  const reviewStart = source.indexOf('{t.semanticBatchReviewTitle}');
  const reviewEnd = source.indexOf('{semanticBatchConfirmOpen && (');
  assert.ok(reviewStart > -1 && reviewEnd > reviewStart, 'expected the batch review screen block');
  const body = source.slice(reviewStart, reviewEnd);

  assert.match(body, /disabled=\{!isBatchReadyToSave\(semanticBatchQueue, semanticBatchStatuses\)\}/);
  assert.match(body, /\{t\.semanticBatchSaveAll\}/);
});

// ── 13. One final confirmation submits the complete batch ───────────────

test('AdminMapScreen.jsx: Save All opens exactly one confirmation dialog showing a count, and only handleSaveAllSemanticBatchDestinations actually calls applySemanticDestinations with allOrNothing', () => {
  const openBody = extractFunction('handleOpenSemanticBatchSaveConfirm');
  assert.match(openBody, /setSemanticBatchConfirmOpen\(true\)/);

  const saveBody = extractFunction('handleSaveAllSemanticBatchDestinations', true);
  assert.match(saveBody, /buildBatchAcceptedPayload\(semanticDestProposals\)/);
  assert.match(saveBody, /await applySemanticDestinations\(activeMap\.id, \{/);
  assert.match(saveBody, /allOrNothing: true/);

  // The confirmation dialog itself shows a count before the admin
  // confirms — never a silent, uncountable action.
  assert.match(source, /semanticBatchSaveConfirmBody\(buildBatchAcceptedPayload\(semanticDestProposals\)\.length\)/);
});

test('AdminMapScreen.jsx: a batch save that returns item_errors writes nothing further on the frontend side (never advances to the result phase) and surfaces the errors in the review screen', () => {
  const saveBody = extractFunction('handleSaveAllSemanticBatchDestinations', true);
  const errorBranch = saveBody.match(/if \(result\.item_errors[\s\S]*?return;\s*\}/);
  assert.ok(errorBranch, 'expected an item_errors early-return branch');
  assert.doesNotMatch(errorBranch[0], /setSemanticDestPhase\('result'\)/);
  assert.match(errorBranch[0], /setSemanticBatchItemErrors\(result\.item_errors\)/);
  assert.match(errorBranch[0], /setSemanticBatchReviewOpen\(true\)/);
});

// ── 14. Refresh restores the local placement draft ───────────────────────

test('AdminMapScreen.jsx: handleStartSemanticBatchPlacement checks localStorage for an existing draft before starting fresh, and handleResumeSemanticBatchDraft re-applies its remembered placements', () => {
  const startBody = extractFunction('handleStartSemanticBatchPlacement');
  assert.match(startBody, /deserializeBatchDraft\(\s*window\.localStorage\.getItem\(getSemanticBatchDraftKey\(\)\),?\s*\)/);
  assert.match(startBody, /setSemanticBatchDraftPrompt\(existingDraft\)/);

  const resumeBody = extractFunction('handleResumeSemanticBatchDraft');
  assert.match(resumeBody, /draft\.placements\?\.\[proposal\.semantic_item_id\]/);
  assert.match(resumeBody, /setSemanticBatchQueue\(draft\.queueItemIds\)/);
  assert.match(resumeBody, /setSemanticBatchActive\(true\)/);
});

test('AdminMapScreen.jsx: batch progress is persisted to localStorage on every change while batch mode is active', () => {
  assert.match(source, /if \(!semanticBatchActive \|\| !activeMap\?\.id\) return undefined;/);
  assert.match(source, /window\.localStorage\.setItem\(\s*\n?\s*getSemanticBatchDraftKey\(\),/);
  assert.match(source, /serializeBatchDraft\(\{/);
});

test('AdminMapScreen.jsx: the resume/discard prompt is offered (never silently auto-resumed or auto-discarded)', () => {
  assert.match(source, /semanticBatchDraftPrompt &&/);
  assert.match(source, /\{t\.semanticBatchResumeDraft\}/);
  assert.match(source, /\{t\.semanticBatchDiscardDraft\}/);
  assert.match(source, /onClick=\{handleResumeSemanticBatchDraft\}/);
  assert.match(source, /onClick=\{handleDiscardSemanticBatchDraft\}/);
});

// ── 15. Successful save clears the local draft ───────────────────────────

test('AdminMapScreen.jsx: handleSaveAllSemanticBatchDestinations removes the localStorage draft only on the success path (never before, never on failure)', () => {
  const body = extractFunction('handleSaveAllSemanticBatchDestinations', true);

  const successIndex = body.indexOf('setSemanticDestApplyResult(result);');
  const removeIndex = body.indexOf('window.localStorage.removeItem(getSemanticBatchDraftKey());');
  const catchIndex = body.indexOf('} catch (error) {');

  assert.ok(successIndex > -1 && removeIndex > -1 && catchIndex > -1);
  assert.ok(
    successIndex < removeIndex && removeIndex < catchIndex,
    'the draft must only be cleared on the success path, before the catch block',
  );
});

test('AdminMapScreen.jsx: handleDiscardSemanticBatchDraft also clears the stored draft (the other allowed clearing moment, Section 9)', () => {
  const body = extractFunction('handleDiscardSemanticBatchDraft');
  assert.match(body, /window\.localStorage\.removeItem\(getSemanticBatchDraftKey\(\)\)/);
});

// ── Backend contract: all_or_nothing flows through the API client ───────

test('mapAnalysisApi.js: applySemanticDestinations sends all_or_nothing derived from applyOptions.allOrNothing', () => {
  const apiSource = fs.readFileSync(
    path.join(__dirname, '..', 'api', 'mapAnalysisApi.js'),
    'utf8',
  );
  assert.match(apiSource, /all_or_nothing: Boolean\(applyOptions\.allOrNothing\)/);
});

// ── Existing per-card flow + unrelated modes remain untouched ───────────

test('AdminMapScreen.jsx: the pre-existing per-card semantic-destinations flow (handleConfirmSemanticDestApply, handleAcceptSemanticProposal) is completely unmodified/still present', () => {
  assert.match(source, /const handleConfirmSemanticDestApply = async \(\) => \{/);
  assert.match(source, /const handleAcceptSemanticProposal = \(itemId\) => \{/);
  assert.match(source, /const handleRejectSemanticProposal = \(itemId\) => \{/);
  assert.match(source, /const handleStartManualSemanticPlacement = \(itemId\) => \{/);
});

test('AdminMapScreen.jsx: Auto Connect, Delete Connection, Draw Walkable Path, and Sync Rooms remain fully intact', () => {
  assert.match(source, /\{t\.autoConnectMode\}/);
  assert.match(source, /\{t\.deleteConnectionMode\}/);
  assert.match(source, /\{t\.drawMode\}/);
  assert.match(source, /\{t\.syncRoomsAction\}/);
});

// ── Translations: every new key exists in en/ar/he ──────────────────────

const REQUIRED_BATCH_KEYS = [
  'semanticBatchPlaceAll',
  'semanticBatchPanelTitle',
  'semanticBatchDestinationOf',
  'semanticBatchClickInstructions',
  'semanticBatchLocationRecorded',
  'semanticBatchLocationSelected',
  'semanticBatchProgressPlaced',
  'semanticBatchProgressRemaining',
  'semanticBatchProgressRejected',
  'semanticBatchPrevious',
  'semanticBatchSkip',
  'semanticBatchReject',
  'semanticBatchUndo',
  'semanticBatchChangeLocation',
  'semanticBatchExit',
  'semanticBatchReviewTitle',
  'semanticBatchSaveAll',
  'semanticBatchSaveConfirmTitle',
  'semanticBatchSaveConfirmBody',
  'semanticBatchExitWarningTitle',
  'semanticBatchExitWarningBody',
  'semanticBatchResumeDraftTitle',
  'semanticBatchResumeDraftBody',
  'semanticBatchResumeDraft',
  'semanticBatchDiscardDraft',
  'semanticBatchStatusReady',
  'semanticBatchStatusRejected',
  'semanticBatchStatusMissing',
];

test('AdminMapScreen.jsx: every required batch-placement translation key exists in en, ar, and he blocks', () => {
  const enBlock = source.slice(source.indexOf('en: {'), source.indexOf('ar: {'));
  const arBlock = source.slice(source.indexOf('ar: {'), source.indexOf('he: {'));
  const heBlock = source.slice(source.indexOf('he: {'), source.length);

  REQUIRED_BATCH_KEYS.forEach((key) => {
    assert.match(enBlock, new RegExp(`${key}:`), `missing ${key} in en block`);
    assert.match(arBlock, new RegExp(`${key}:`), `missing ${key} in ar block`);
    assert.match(heBlock, new RegExp(`${key}:`), `missing ${key} in he block`);
  });
});

test('AdminMapScreen.jsx: the exact required action labels (Section 1/6) are present verbatim in en/ar/he', () => {
  assert.match(source, /semanticBatchPlaceAll: 'Place All Destinations'/);
  assert.match(source, /semanticBatchPlaceAll: 'تحديد مواقع جميع الوجهات'/);
  assert.match(source, /semanticBatchPlaceAll: 'מיקום כל היעדים'/);

  assert.match(source, /semanticBatchSaveAll: 'Save All Destinations'/);
  assert.match(source, /semanticBatchSaveAll: 'حفظ جميع الوجهات'/);
  assert.match(source, /semanticBatchSaveAll: 'שמירת כל היעדים'/);
});

console.log(`\n${passed} test(s) passed.`);
if (process.exitCode) {
  console.error('Some tests FAILED.');
} else {
  console.log('All tests passed.');
}
