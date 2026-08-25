// Draw Walkable Path and Delete Connection must stay OPEN across
// operations, and finishing a draw session must retry the floor's pending
// destination attachments exactly once.
//
// Source-text contract tests, matching the convention of the other
// *UI.test.mjs files in this directory: AdminMapScreen.jsx is far too
// large and too stateful to mount, so the invariants are asserted against
// the code that implements them.
//
// Run with: node src/screens/editingSessionPersistence.test.mjs

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const source = readFileSync(join(here, 'AdminMapScreen.jsx'), 'utf8');

let passed = 0;
let failed = 0;

function test(name, fn) {
  try {
    fn();
    console.log(`PASS: ${name}`);
    passed += 1;
  } catch (error) {
    console.error(`FAIL: ${name}`);
    console.error(error.message);
    failed += 1;
  }
}

// Slice from a handler's declaration to the next top-level declaration.
// A brace/`\n  };` scan is not reliable here: several of these handlers
// contain nested blocks that close at the same indentation, so a lazy
// match runs past the end of the function and into the next one.
function extractFunction(name) {
  const start = source.indexOf(`const ${name} = `);
  assert.notEqual(start, -1, `expected to find ${name}`);

  const after = source.slice(start + 1);
  const nextMatch = after.match(/\n  const [A-Za-z_$][\w$]* = /);
  const end = nextMatch ? start + 1 + nextMatch.index : source.length;

  return source.slice(start, end);
}

// Comments in these handlers deliberately quote the very calls the tests
// forbid ("this used to call setMode('point')"), so a negative assertion
// has to look at code only.
function codeOnly(body) {
  return body
    .split('\n')
    .filter((line) => !line.trim().startsWith('//'))
    .join('\n');
}

// ── 27. Draw mode remains persistent ──────────────────────────────────

test('handleSaveDraft never leaves draw mode — only the finished path is cleared', () => {
  const body = extractFunction('handleSaveDraft');

  // The single line that used to end the session after one path.
  assert.doesNotMatch(codeOnly(body), /setMode\('point'\)/);

  assert.match(body, /setDraftPoints\(\[\]\)/);
  assert.match(body, /setDrawSessionSummaries\(/);
});

test('each drawn path is still persisted as it is saved, not batched', () => {
  const body = extractFunction('handleSaveDraft');
  // Real API calls per path — nothing is held in memory awaiting a final
  // commit, so a mid-session refresh cannot lose completed work.
  assert.match(body, /createRoutePoint|saveRoutePoint|createRouteEdge/);
  assert.match(body, /refreshRouteGraph\(activeMap\.id\)/);
});

test('a mis-clicked path can be discarded without ending the session', () => {
  const body = extractFunction('handleDiscardCurrentPath');
  assert.match(body, /setDraftPoints\(\[\]\)/);
  assert.doesNotMatch(codeOnly(body), /setMode\(/);
});

test('entering draw mode starts a fresh session tally', () => {
  const toolboxStart = source.indexOf('const mapToolGroups = [');
  const toolbox = source.slice(toolboxStart, source.indexOf('\n  ];', toolboxStart));
  const drawTool = toolbox.slice(
    toolbox.indexOf("id: 'draw',"),
    toolbox.indexOf("id: 'test',"),
  );
  assert.match(drawTool, /setDrawSessionSummaries\(\[\]\)/);
});

// ── 28. Delete mode remains persistent ────────────────────────────────

test('handleConfirmDeleteConnection never leaves delete mode', () => {
  const body = extractFunction('handleConfirmDeleteConnection');

  assert.doesNotMatch(codeOnly(body), /setMode\('point'\)/);

  // Only the selection is cleared, so the next edge can be picked
  // immediately.
  assert.match(body, /setSelectedEdgeForDeletion\(null\)/);
  assert.match(body, /setDeleteSessionCount\(/);
});

test('deletion still persists immediately — no batching was introduced', () => {
  const body = extractFunction('handleConfirmDeleteConnection');
  assert.match(body, /await deleteRouteEdge\(edgeId\)/);
  assert.match(body, /await refreshRouteGraph\(activeMap\?\.id\)/);
});

test('Done is what exits delete mode, and it resets the session tally', () => {
  const body = extractFunction('handleCancelDeleteConnectionMode');
  assert.match(body, /setMode\('point'\)/);
  assert.match(body, /setDeleteSessionCount\(0\)/);
});

// ── Bulk retry is wired to the end of the draw session ────────────────

test('finishing a draw session retries the floor\'s pending attachments once', () => {
  const body = extractFunction('handleCancelDraw');

  assert.match(body, /runPendingAttachmentRetry\(\)/);
  // Only when the session actually saved something — finishing an empty
  // session changes no graph and needs no retry.
  assert.match(body, /savedPathCount > 0/);
});

test('the retry is one call for the whole map, never per room', () => {
  const body = extractFunction('runPendingAttachmentRetry');
  assert.match(body, /retryPendingAttachments\(\{ map_id: activeMap\.id \}\)/);
  assert.doesNotMatch(codeOnly(body), /\.map\(|for \(/);
});

test('the retry refreshes the rendered graph so new edges appear', () => {
  const body = extractFunction('runPendingAttachmentRetry');
  assert.match(body, /refreshRouteGraph\(activeMap\.id\)/);
});

// ── Legacy repair panel is wired, and only repairs what the backend
//    marked repairable ─────────────────────────────────────────────────

test('the legacy repair apply sends only the map id — the backend decides', () => {
  const body = extractFunction('handleApplyLegacyRepair');
  assert.match(body, /applyLegacyConnections\(\{ map_id: activeMap\.id \}\)/);
  // No client-side edge selection: the frontend never decides what is
  // safe to delete.
  assert.doesNotMatch(codeOnly(body), /edge_ids/);
});

test('the legacy repair preview is read-only and rescans after a repair', () => {
  const scan = extractFunction('runLegacyRepairScan');
  assert.match(scan, /previewLegacyConnections\(\{ map_id: activeMap\.id \}\)/);

  const apply = extractFunction('handleApplyLegacyRepair');
  assert.match(apply, /await runLegacyRepairScan\(\)/);
  assert.match(apply, /await refreshRouteGraph\(activeMap\.id\)/);
});

test('every legacy repair string exists in all three languages', () => {
  const keys = [
    'legacyRepairTitle',
    'legacyRepairScan',
    'legacyRepairRepair',
    'legacyRepairInvalid',
    'legacyRepairNeedsReview',
    'legacyRepairReconnected',
    'legacyRepairNothingFound',
    'retryPendingResult',
  ];
  keys.forEach((key) => {
    const occurrences = source.split(`${key}:`).length - 1;
    assert.equal(occurrences, 3, `${key} should exist in en/ar/he`);
  });
});

console.log(`\n${passed} test(s) passed.`);
if (failed > 0) {
  console.error(`${failed} test(s) FAILED.`);
  process.exit(1);
}
