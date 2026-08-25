// Plain-Node "layout contract" tests for the full-map editor's workspace
// architecture (Task E: portrait/vertical map floating panel movement fix).
//
// There is no DOM/browser test runner in this repo (no jsdom/jest/vitest),
// so these tests read the real source files from disk and assert the
// structural contract that makes the fix work:
//
//   - Editor workspace (fullMapWorkspaceRef) = the FloatingToolPanel's
//     drag/dock/clamp boundary — the full modal area, not the map image.
//   - Map stage (fullMapContainerRef) = the map image + SVG overlay ONLY —
//     the exclusive source of every click-to-map-coordinate calculation,
//     completely independent of the workspace's size.
//
// An accidental future revert of either half of that split (e.g. someone
// "simplifies" by pointing the panel back at the map-stage ref, or starts
// computing map coordinates from the workspace) fails a test here instead
// of silently reintroducing the "panel stuck on a narrow portrait map"
// bug or a much worse coordinate-corruption bug.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

const panelSource = readFileSync(
  path.join(__dirname, 'FloatingToolPanel.jsx'),
  'utf8',
);
const cssSource = readFileSync(
  path.join(__dirname, '..', 'styles', 'adminScreens.css'),
  'utf8',
);
const adminMapScreenSource = readFileSync(
  path.join(__dirname, '..', 'screens', 'AdminMapScreen.jsx'),
  'utf8',
);
const helpersSource = readFileSync(
  path.join(__dirname, '..', 'utils', 'floatingPanelHelpers.js'),
  'utf8',
);

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

// ── 1. A dedicated workspace ref exists and is distinct from the map stage ─
test('fullMapWorkspaceRef is declared as its own ref, separate from fullMapContainerRef', () => {
  assert.match(adminMapScreenSource, /const fullMapWorkspaceRef = useRef\(null\);/);
  assert.match(adminMapScreenSource, /const fullMapContainerRef = useRef\(null\);/);
});

// ── 2. Clamping/docking uses workspace dimensions, never the map stage ─────
// 4 usages: Add Point / Draw Walkable Path / Test Route (each renders
// FloatingToolPanel directly) plus Vertical Connections (renders it
// indirectly via VerticalConnectionsPanel, but AdminMapScreen still passes
// the same workspace ref through as that component's containerRef prop).
test('all four panel usages use the workspace ref as their containerRef', () => {
  const matches = adminMapScreenSource.match(/containerRef=\{fullMapWorkspaceRef\}/g) || [];
  assert.equal(matches.length, 4);
});

test('fullMapContainerRef is never passed as a FloatingToolPanel containerRef (map stage must never be the drag/clamp boundary)', () => {
  assert.equal(/containerRef=\{fullMapContainerRef\}/.test(adminMapScreenSource), false);
});

// ── 3. The panel is a DOM sibling of the map stage, not nested inside it ───
// (required for position:absolute left/top to actually be workspace-local —
// see the workspace div's own position:relative below). The map stage div
// must close (via its own closing comment marker) before any
// <FloatingToolPanel appears in source order.
test('the map stage closes before the first FloatingToolPanel is rendered (panels are workspace-level siblings, not map-stage children)', () => {
  const mapStageCloseIndex = adminMapScreenSource.indexOf(
    'map stage (fullMapContainerRef) closes here',
  );
  const firstPanelIndex = adminMapScreenSource.indexOf('<FloatingToolPanel');
  assert.notEqual(mapStageCloseIndex, -1);
  assert.notEqual(firstPanelIndex, -1);
  assert.equal(mapStageCloseIndex < firstPanelIndex, true);
});

// ── 4. Workspace establishes its own positioning context ───────────────────
test('the workspace div is position:relative so the panel/close button\'s absolute coordinates are workspace-local, not map-stage-local', () => {
  const workspaceOpenIndex = adminMapScreenSource.indexOf('ref={fullMapWorkspaceRef}');
  assert.notEqual(workspaceOpenIndex, -1);
  const window = adminMapScreenSource.slice(workspaceOpenIndex, workspaceOpenIndex + 400);
  assert.match(window, /position:\s*'relative'/);
});

// ── 6. Portrait map stays centered within the workspace ────────────────────
test('the workspace centers the map stage (flex + centered alignment), leaving symmetric leftover space as usable gutters', () => {
  const workspaceOpenIndex = adminMapScreenSource.indexOf('ref={fullMapWorkspaceRef}');
  const window = adminMapScreenSource.slice(workspaceOpenIndex, workspaceOpenIndex + 400);
  assert.match(window, /display:\s*'flex'/);
  assert.match(window, /alignItems:\s*'center'/);
  assert.match(window, /justifyContent:\s*'center'/);
});

// ── 7. Landscape maps: map stage sizing/aspect-ratio logic is untouched ────
test('the map stage still caps its own size independently (maxWidth/maxHeight), unrelated to the workspace size', () => {
  const stageOpenIndex = adminMapScreenSource.indexOf('ref={fullMapContainerRef}');
  const window = adminMapScreenSource.slice(stageOpenIndex, stageOpenIndex + 300);
  assert.match(window, /maxWidth:\s*'96vw'/);
  assert.match(window, /maxHeight:\s*'90vh'/);
});

// ── 8 & 18. Coordinates are computed ONLY from the map image, never from
// the workspace/backdrop/panel — the single most important safety
// guarantee of this whole change. ──────────────────────────────────────────
test('handleFullMapClick never references the workspace ref — coordinates come only from the clicked image element', () => {
  const fnStart = adminMapScreenSource.indexOf('const handleFullMapClick = (event) => {');
  const fnEnd = adminMapScreenSource.indexOf('\n  };', fnStart);
  assert.notEqual(fnStart, -1);
  assert.notEqual(fnEnd, -1);
  const fnBody = adminMapScreenSource.slice(fnStart, fnEnd);

  assert.equal(fnBody.includes('fullMapWorkspaceRef'), false);
  assert.match(fnBody, /image\.getBoundingClientRect\(\)/);
  assert.match(fnBody, /image\.naturalWidth/);
  assert.match(fnBody, /image\.naturalHeight/);
});

test('syncFullMapMetrics still measures fullMapImageRef for map metrics — the workspace ref is only used for the panel\'s default position', () => {
  const fnStart = adminMapScreenSource.indexOf('const syncFullMapMetrics = () => {');
  const fnEnd = adminMapScreenSource.indexOf('\n  };', fnStart);
  assert.notEqual(fnStart, -1);
  const fnBody = adminMapScreenSource.slice(fnStart, fnEnd);

  assert.match(fnBody, /fullMapImageRef\.current/);
  assert.match(fnBody, /image\.naturalWidth/);
  // The default panel position is workspace-relative (so it lands in the
  // portrait gutter, not on top of the image) — but this must be the ONLY
  // role the workspace ref plays here.
  assert.match(fnBody, /fullMapWorkspaceRef\.current\?\.getBoundingClientRect\(\)/);
});

// ── 9. Gutter clicks never create a RoutePoint ──────────────────────────────
test('the workspace stops click propagation so an empty-gutter click never reaches the backdrop\'s close handler or any point-creation logic', () => {
  const workspaceOpenIndex = adminMapScreenSource.indexOf('ref={fullMapWorkspaceRef}');
  const window = adminMapScreenSource.slice(workspaceOpenIndex - 50, workspaceOpenIndex + 200);
  assert.match(window, /onClick=\{\(event\) => event\.stopPropagation\(\)\}/);
});

test('handleFullMapClick defensively verifies the click actually landed on the map image before computing coordinates', () => {
  const fnStart = adminMapScreenSource.indexOf('const handleFullMapClick = (event) => {');
  const fnEnd = adminMapScreenSource.indexOf('\n  };', fnStart);
  const fnBody = adminMapScreenSource.slice(fnStart, fnEnd);
  assert.match(fnBody, /image !== fullMapImageRef\.current/);
});

// ── 10 & 11. Map clicks / drag-through-gutter safety are unaffected ────────
test('the map image click handler and the panel-dragging guard are both still wired up', () => {
  assert.match(adminMapScreenSource, /onClick=\{\s*handleFullMapClick\s*\}/);
  const fnStart = adminMapScreenSource.indexOf('const handleFullMapClick = (event) => {');
  const fnEnd = adminMapScreenSource.indexOf('\n  };', fnStart);
  const fnBody = adminMapScreenSource.slice(fnStart, fnEnd);
  assert.match(fnBody, /isPanelDraggingRef\.current/);
});

// ── 15. RTL: docking stays physical/explicit, only the default position adapts ─
test('Dock Left / Dock Right call handleSnap with a literal, non-RTL-conditioned side', () => {
  assert.match(panelSource, /onClick=\{\(\) => handleSnap\('left'\)\}/);
  assert.match(panelSource, /onClick=\{\(\) => handleSnap\('right'\)\}/);
});

test('computeSnapPosition never branches on RTL — left/right are always physical directions', () => {
  const fnMatch = helpersSource.match(/export function computeSnapPosition\([\s\S]*?\n\}/);
  assert.notEqual(fnMatch, null);
  assert.equal(/isRTL/.test(fnMatch[0]), false);
});

test('the panel default position is computed against the workspace and adapts to RTL for its starting side', () => {
  assert.match(adminMapScreenSource, /computeDefaultPanelPosition\(\{/);
  const callIndex = adminMapScreenSource.indexOf('computeDefaultPanelPosition({');
  const window = adminMapScreenSource.slice(callIndex, callIndex + 250);
  assert.match(window, /containerWidth:\s*workspaceRect\.width/);
  assert.match(window, /isRTL/);
});

// ── 17. Toolbar / close button are never permanently covered by the panel ──
test('Dock Left/Right reserve top space (snapTopOffset) so docking never lands under the toolbar/close button', () => {
  const matches = adminMapScreenSource.match(/snapTopOffset=\{76\}/g) || [];
  assert.equal(matches.length, 4);
  assert.match(panelSource, /snapTopOffset/);
});

test('the close button explicitly outranks the panel in stacking order', () => {
  const buttonBlockIndex = adminMapScreenSource.indexOf("aria-label={t.back}");
  const window = adminMapScreenSource.slice(buttonBlockIndex, buttonBlockIndex + 600);
  assert.match(window, /zIndex:\s*2/);

  const panelRule = cssSource.match(/\.tool-panel\s*\{([^}]*)\}/);
  assert.notEqual(panelRule, null);
  assert.match(panelRule[1], /z-index:\s*1/);
});

test('the close button is rendered after every FloatingToolPanel usage in source order (paints correctly, stays reachable)', () => {
  const lastPanelCloseIndex = adminMapScreenSource.lastIndexOf('</FloatingToolPanel>');
  const buttonIndex = adminMapScreenSource.indexOf("aria-label={t.back}");
  assert.notEqual(lastPanelCloseIndex, -1);
  assert.notEqual(buttonIndex, -1);
  assert.equal(lastPanelCloseIndex < buttonIndex, true);
});

// ── 16. Mobile: the panel is capped and can never cover the whole map ──────
test('the small-screen media query still caps the panel\'s own box size (unaffected by the workspace boundary widening)', () => {
  const mediaMatch = cssSource.match(/@media \(max-width: 640px\) \{([\s\S]*?)\n\}/);
  assert.notEqual(mediaMatch, null);
  assert.match(mediaMatch[1], /\.tool-panel\s*\{[\s\S]*?max-width/);
  assert.match(mediaMatch[1], /\.tool-panel\s*\{[\s\S]*?max-height/);
});

console.log(`\n${passed} test(s) passed.`);
if (process.exitCode) {
  console.error('One or more tests FAILED.');
} else {
  console.log('All tests passed.');
}
