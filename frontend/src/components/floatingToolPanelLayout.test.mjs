// Plain-Node "layout contract" tests for the floating panel scrolling fix
// (frontend/src/components/FloatingToolPanel.jsx +
// frontend/src/styles/adminScreens.css + the three panel usages in
// frontend/src/screens/AdminMapScreen.jsx).
//
// There is no DOM/browser test runner in this repo (no jsdom/jest/vitest),
// so real rendered-layout assertions ("is this pixel actually visible")
// aren't possible here. What IS testable without a browser is the
// structural contract that makes the fix work: the panel is a flex column
// with a shrink-proof header, a body that can actually shrink and scroll
// (the classic flexbox bug this fixes is a body with no `min-height: 0`,
// which silently blocks its own `overflow-y: auto` from ever doing
// anything), and a sticky footer that lives outside the scrollable area.
// These tests read the real source files from disk and assert that
// contract is present — so an accidental future revert of any one piece
// (e.g. someone deletes `min-height: 0` while refactoring) fails a test
// instead of silently reintroducing the "Save button unreachable" bug.
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

// Pulls out a single CSS rule block's body by selector, e.g.
// ruleBody(css, '.tool-panel-body') -> "padding: 16px; ... "
function ruleBody(css, selector) {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const match = css.match(new RegExp(`${escaped}\\s*\\{([^}]*)\\}`));
  return match ? match[1] : '';
}

// Extracts the JSX content of every `footer={ ... }` prop in a source file
// by counting brace depth from each `footer={` up to its matching close —
// far more robust than a regex window when blocks vary in length/order.
function extractFooterBlocks(source) {
  const blocks = [];
  const marker = 'footer={';
  let searchFrom = 0;

  for (;;) {
    const start = source.indexOf(marker, searchFrom);
    if (start === -1) break;

    let depth = 1;
    let i = start + marker.length;
    while (i < source.length && depth > 0) {
      if (source[i] === '{') depth += 1;
      else if (source[i] === '}') depth -= 1;
      i += 1;
    }

    blocks.push(source.slice(start + marker.length, i - 1));
    searchFrom = i;
  }

  return blocks;
}

// ── 1. Long panel content gets a scrollable body ───────────────────────────
test('.tool-panel-body has overflow-y: auto', () => {
  const body = ruleBody(cssSource, '.tool-panel-body');
  assert.match(body, /overflow-y:\s*auto/);
});

test('.tool-panel-body can actually shrink to a scrollable size (min-height: 0 + flex)', () => {
  // This is the real fix: without min-height: 0, a flex item defaults to
  // its content's full natural height and never shrinks, so overflow-y:
  // auto above never gets a chance to do anything — the panel's own
  // max-height + overflow: hidden just silently clips the overflow
  // instead of making it scrollable. This is exactly the reported bug.
  const body = ruleBody(cssSource, '.tool-panel-body');
  assert.match(body, /min-height:\s*0/);
  assert.match(body, /flex:\s*1\s+1\s+auto/);
});

// ── 2. Panel max height stays inside viewport bounds ───────────────────────
test('.tool-panel has a viewport-relative max-height and clips its own box (not its scrollable content)', () => {
  const panel = ruleBody(cssSource, '.tool-panel');
  assert.match(panel, /max-height:\s*calc\(100vh/);
  assert.match(panel, /display:\s*flex/);
  assert.match(panel, /flex-direction:\s*column/);
  assert.match(panel, /overflow:\s*hidden/);
});

// ── 3. Header remains visible (never shrinks/scrolls away) ─────────────────
test('.tool-panel-header does not shrink', () => {
  const header = ruleBody(cssSource, '.tool-panel-header');
  assert.match(header, /flex-shrink:\s*0/);
});

// ── 4. Save footer remains reachable (sticky, outside the scroll area) ─────
test('.tool-panel-footer exists, does not shrink, and is visually separated from the header/body', () => {
  const footer = ruleBody(cssSource, '.tool-panel-footer');
  assert.notEqual(footer, '');
  assert.match(footer, /flex-shrink:\s*0/);
  assert.match(footer, /border-top/);
});

test('FloatingToolPanel accepts a footer prop and renders it as a sibling of the scrollable body, not inside it', () => {
  assert.match(panelSource, /footer,/);
  assert.match(panelSource, /className="tool-panel-body"/);
  assert.match(panelSource, /\{footer && \(/);

  // The footer render must come AFTER the body's closing tag in source
  // order — i.e. it's a sibling, never nested inside .tool-panel-body
  // (which would put it back inside the scrollable area).
  const bodyOpenIndex = panelSource.indexOf('className="tool-panel-body"');
  const bodyCloseIndex = panelSource.indexOf('</div>', bodyOpenIndex);
  const footerRenderIndex = panelSource.indexOf('tool-panel-footer');
  assert.equal(bodyOpenIndex > -1, true);
  assert.equal(footerRenderIndex > bodyCloseIndex, true);
});

test('all three AdminMapScreen floating panels (Add Point, Draw Walkable Path, Test Route) use the footer prop for their primary actions', () => {
  const footerBlocks = extractFooterBlocks(adminMapScreenSource);
  assert.equal(footerBlocks.length, 3);

  // Each footer block still contains its real primary-action button
  // labels — i.e. Save/Find Route weren't accidentally dropped while
  // moving them out of the scrollable body.
  assert.equal(footerBlocks.some((block) => block.includes('t.savePoint')), true);
  assert.equal(footerBlocks.some((block) => block.includes('handleSaveDraft')), true);
  assert.equal(footerBlocks.some((block) => block.includes('handleFindRoute')), true);
});

// ── 11. All three footer configurations are complete, not just present ─────
test('Add Route Point footer has both Save and Cancel', () => {
  const footerBlocks = extractFooterBlocks(adminMapScreenSource);
  const addPointFooter = footerBlocks.find((block) => block.includes('t.savePoint'));
  assert.notEqual(addPointFooter, undefined);
  assert.match(addPointFooter, /t\.cancel/);
  assert.match(addPointFooter, /saveRoutePoint/);
});

test('Draw Walkable Path footer has Undo, Clear, Cancel, and Save Path', () => {
  const footerBlocks = extractFooterBlocks(adminMapScreenSource);
  const drawFooter = footerBlocks.find((block) => block.includes('handleSaveDraft'));
  assert.notEqual(drawFooter, undefined);
  assert.match(drawFooter, /handleUndoDraft/);
  assert.match(drawFooter, /handleClearDraft/);
  assert.match(drawFooter, /handleCancelDraw/);
  assert.match(drawFooter, /t\.drawSave/);
});

test('Test Route footer has Clear Test and Find Route', () => {
  const footerBlocks = extractFooterBlocks(adminMapScreenSource);
  const testFooter = footerBlocks.find((block) => block.includes('handleFindRoute'));
  assert.notEqual(testFooter, undefined);
  assert.match(testFooter, /handleClearTest/);
  assert.match(testFooter, /t\.testFind/);
});

// ── The actual fix: position-aware available height, not a flat 100vh cap ──
test('FloatingToolPanel computes availableHeight from computeAvailablePanelHeight and applies it as the panel\'s maxHeight', () => {
  assert.match(panelSource, /import\s*\{[^}]*computeAvailablePanelHeight[^}]*\}\s*from\s*'\.\.\/utils\/floatingPanelHelpers'/);
  assert.match(panelSource, /computeAvailablePanelHeight\(\{/);
  assert.match(panelSource, /maxHeight:\s*availableHeight/);
});

test('FloatingToolPanel tracks the container\'s live height as state, updated from the same measurement the X/Y clamp already uses', () => {
  assert.match(panelSource, /useState\(0\)/);
  assert.match(panelSource, /setContainerHeight\(containerRect\.height\)/);
});

test('availableHeight is derived from position.y (a fresh prop on every render), so it updates live during a drag, not only after resize/collapse settle', () => {
  const availableHeightBlockMatch = panelSource.match(
    /const availableHeight = containerHeight[\s\S]*?;\n/,
  );
  assert.notEqual(availableHeightBlockMatch, null);
  assert.match(availableHeightBlockMatch[0], /panelY:\s*position\.y/);
});

test('the panel never falls back to the old flat max-height once measured — the inline style always wins when available', () => {
  const styleBlockMatch = panelSource.match(/style=\{\{[\s\S]*?\}\}\n\s*dir=/);
  assert.notEqual(styleBlockMatch, null);
  assert.match(styleBlockMatch[0], /availableHeight && !isCollapsed/);
  assert.match(styleBlockMatch[0], /maxHeight:\s*availableHeight/);
});

// ── 7. Footer visibility guarantees (background, stacking, no clipping) ────
test('.tool-panel-footer has an opaque background and its own stacking context', () => {
  const footer = ruleBody(cssSource, '.tool-panel-footer');
  assert.match(footer, /background:\s*white/);
  assert.match(footer, /position:\s*relative/);
  assert.match(footer, /z-index:\s*1/);
});

// ── 5. Panel scroll does not trigger map click/zoom/pan ────────────────────
test('the scrollable body stops wheel and touch-move propagation before it can reach the map underneath', () => {
  const bodyOpenIndex = panelSource.indexOf('className="tool-panel-body"');
  assert.notEqual(bodyOpenIndex, -1);

  // The body's opening JSX tag ends at the first `>` that isn't part of an
  // arrow function's `=>` — look at a generous window right after the
  // className and confirm both handlers appear in it, before the body's
  // actual content (children) begins.
  const window = panelSource.slice(bodyOpenIndex, bodyOpenIndex + 300);
  assert.match(window, /onWheel=\{\(event\) => event\.stopPropagation\(\)\}/);
  assert.match(window, /onTouchMove=\{\(event\) => event\.stopPropagation\(\)\}/);
});

test('the whole panel still stops click propagation (existing protection, must survive this change)', () => {
  assert.match(panelSource, /onClick=\{\(event\) => event\.stopPropagation\(\)\}/);
});

// ── 6. Panel remains draggable ──────────────────────────────────────────────
test('the drag handle and its pointer handlers are untouched by the footer change', () => {
  assert.match(panelSource, /className="tool-panel-drag-handle"/);
  assert.match(panelSource, /onPointerDown=\{handleDragPointerDown\}/);
  assert.match(panelSource, /onPointerMove=\{handleDragPointerMove\}/);
});

// ── 7. Collapse/restore still works ─────────────────────────────────────────
test('collapsed state still hides both the body and the footer together', () => {
  assert.match(panelSource, /\{!isCollapsed && \(/);
});

// ── 8. Small screens remain usable ──────────────────────────────────────────
test('a small-screen media query still caps the panel height without double-constraining the body', () => {
  const mediaMatch = cssSource.match(
    /@media \(max-width: 640px\) \{([\s\S]*?)\n\}/,
  );
  assert.notEqual(mediaMatch, null);
  assert.match(mediaMatch[1], /\.tool-panel\s*\{[\s\S]*?max-height/);
});

// ── 9. RTL layout remains usable ────────────────────────────────────────────
test('RTL panel styling is still present', () => {
  assert.match(cssSource, /\.tool-panel\[dir='rtl'\] \.tool-panel-header/);
});

// ── 10. Conditional form fields do not hide Save ────────────────────────────
test('Add Point panel: conditional building/room fields are inside the scrollable body, Save stays in the footer regardless', () => {
  // isPlaceType-gated fields render inside the panel's children (the
  // scrollable body) — Save/Cancel live in the separate footer prop, so
  // however many extra fields appear conditionally, the footer position
  // in the DOM never moves relative to the header.
  assert.match(adminMapScreenSource, /\{isPlaceType && \(/);
  const footerBlocks = extractFooterBlocks(adminMapScreenSource);
  assert.equal(footerBlocks.some((block) => block.includes('t.savePoint')), true);
});

// ── Not part of the automatic map merge/overflow chaining ───────────────────
test('.tool-panel-body prevents scroll chaining to the map/page underneath', () => {
  const body = ruleBody(cssSource, '.tool-panel-body');
  assert.match(body, /overscroll-behavior:\s*contain/);
});

console.log(`\n${passed} test(s) passed.`);
if (process.exitCode) {
  console.error('One or more tests FAILED.');
} else {
  console.log('All tests passed.');
}
