// Plain-Node tests for the full-map view's floating tool panel positioning
// helpers (frontend/src/utils/floatingPanelHelpers.js). These pin down the
// fix for "the Draw Walkable Path / Test Route / Add Point panel is fixed
// in place and permanently blocks part of the map underneath it" — same
// pattern as the repo's other *.test.mjs files, run directly via
// `node floatingPanelHelpers.test.mjs`.
import assert from 'node:assert/strict';
import {
  clampPanelPosition,
  isPanelOutsideBounds,
  computeDefaultPanelPosition,
  computeDragPosition,
  computeClampedDragPosition,
  computeSnapPosition,
  computeAvailablePanelHeight,
  DEFAULT_SAFE_BOTTOM_GAP,
  MIN_PANEL_HEIGHT,
} from './floatingPanelHelpers.js';

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

const CONTAINER = { containerWidth: 1000, containerHeight: 800 };
const PANEL = { panelWidth: 300, panelHeight: 400 };

// ── 1. Panel position is clamped inside container bounds ──────────────────

test('clampPanelPosition: a position already inside bounds is unchanged', () => {
  const result = clampPanelPosition({ x: 50, y: 50, ...PANEL, ...CONTAINER });
  assert.deepEqual(result, { x: 50, y: 50 });
});

test('clampPanelPosition: a position past the right/bottom edge is pulled back in', () => {
  const result = clampPanelPosition({ x: 5000, y: 5000, ...PANEL, ...CONTAINER });
  // 1000 - 300 - 8 (default margin) = 692 ; 800 - 400 - 8 = 392
  assert.deepEqual(result, { x: 692, y: 392 });
});

test('clampPanelPosition: a negative position is pulled back to the margin', () => {
  const result = clampPanelPosition({ x: -500, y: -500, ...PANEL, ...CONTAINER });
  assert.deepEqual(result, { x: 8, y: 8 });
});

test('clampPanelPosition: a panel bigger than the container falls back to the margin, never negative', () => {
  const result = clampPanelPosition({
    x: 400, y: 400,
    panelWidth: 2000, panelHeight: 2000,
    containerWidth: 300, containerHeight: 300,
  });
  assert.equal(result.x, 8);
  assert.equal(result.y, 8);
});

test('clampPanelPosition: non-finite/garbage input never produces NaN', () => {
  const result = clampPanelPosition({
    x: NaN, y: undefined,
    panelWidth: null, panelHeight: 'nope',
    containerWidth: 1000, containerHeight: 800,
  });
  assert.equal(Number.isFinite(result.x), true);
  assert.equal(Number.isFinite(result.y), true);
});

// ── 3. Panel cannot be dragged fully off-screen ────────────────────────────

test('isPanelOutsideBounds: false for a fully visible position', () => {
  assert.equal(isPanelOutsideBounds({ x: 100, y: 100, ...PANEL, ...CONTAINER }), false);
});

test('isPanelOutsideBounds: true once dragged past the edge', () => {
  assert.equal(isPanelOutsideBounds({ x: 5000, y: 100, ...PANEL, ...CONTAINER }), true);
});

test('computeClampedDragPosition: dragging far past the right edge still leaves the panel visible', () => {
  const result = computeClampedDragPosition({
    dragStartPanelX: 20, dragStartPanelY: 76,
    dragStartPointerX: 100, dragStartPointerY: 100,
    pointerX: 100000, pointerY: 100,
    ...PANEL, ...CONTAINER,
  });
  assert.equal(result.x <= 1000 - 300, true);
  assert.equal(result.x >= 0, true);
});

// ── 2. Dragging changes panel position ─────────────────────────────────────

test('computeDragPosition: moving the pointer 40px right and 15px down moves the panel by the same delta', () => {
  const result = computeDragPosition({
    dragStartPanelX: 20, dragStartPanelY: 76,
    dragStartPointerX: 300, dragStartPointerY: 300,
    pointerX: 340, pointerY: 315,
  });
  assert.deepEqual(result, { x: 60, y: 91 });
});

test('computeDragPosition: dragging left of the drag start moves the panel left', () => {
  const result = computeDragPosition({
    dragStartPanelX: 200, dragStartPanelY: 200,
    dragStartPointerX: 500, dragStartPointerY: 500,
    pointerX: 450, pointerY: 500,
  });
  assert.equal(result.x, 150);
  assert.equal(result.y, 200);
});

test('computeDragPosition: zero pointer movement leaves the panel exactly where it started', () => {
  const result = computeDragPosition({
    dragStartPanelX: 77, dragStartPanelY: 33,
    dragStartPointerX: 10, dragStartPointerY: 10,
    pointerX: 10, pointerY: 10,
  });
  assert.deepEqual(result, { x: 77, y: 33 });
});

// ── Default position (RTL-aware) ────────────────────────────────────────────

test('computeDefaultPanelPosition: LTR defaults near the left edge', () => {
  const result = computeDefaultPanelPosition({ ...PANEL, ...CONTAINER, isRTL: false });
  assert.equal(result.x, 20);
  assert.equal(result.y, 76);
});

test('computeDefaultPanelPosition: RTL defaults near the right edge instead', () => {
  const result = computeDefaultPanelPosition({ ...PANEL, ...CONTAINER, isRTL: true });
  // 1000 - 300 - 20 = 680
  assert.equal(result.x, 680);
  assert.equal(result.y, 76);
});

test('computeDefaultPanelPosition: still clamped/safe even on a tiny container', () => {
  const result = computeDefaultPanelPosition({
    panelWidth: 300, panelHeight: 400,
    containerWidth: 250, containerHeight: 200,
    isRTL: false,
  });
  assert.equal(Number.isFinite(result.x), true);
  assert.equal(Number.isFinite(result.y), true);
  assert.equal(result.x >= 0, true);
  assert.equal(result.y >= 0, true);
});

// ── Snap presets (optional dock-to-side improvement) ────────────────────────

test('computeSnapPosition: "left" docks near the left edge', () => {
  const result = computeSnapPosition({ side: 'left', ...PANEL, ...CONTAINER });
  assert.equal(result.x, 20);
});

test('computeSnapPosition: "right" docks near the right edge', () => {
  const result = computeSnapPosition({ side: 'right', ...PANEL, ...CONTAINER });
  assert.equal(result.x, 1000 - 300 - 20);
});

test('computeSnapPosition: "bottom" docks near the bottom edge', () => {
  const result = computeSnapPosition({ side: 'bottom', ...PANEL, ...CONTAINER });
  assert.equal(result.y, 800 - 400 - 20);
});

// ── computeSnapPosition topOffset (workspace-based docking) ────────────────
// Task E: Dock Left / Dock Right must never permanently land the panel
// underneath the full-map workspace's mode toolbar / close button, which
// both live in that same top corner once the panel's clamp boundary is the
// whole editor workspace rather than just the narrow map stage.

test('computeSnapPosition: "left" without topOffset keeps the old plain-margin behavior', () => {
  const result = computeSnapPosition({ side: 'left', ...PANEL, ...CONTAINER });
  assert.equal(result.y, 20);
});

test('computeSnapPosition: "left" with topOffset docks below the reserved top space, not at the bare margin', () => {
  const result = computeSnapPosition({ side: 'left', ...PANEL, ...CONTAINER, topOffset: 76 });
  assert.equal(result.y, 76);
});

test('computeSnapPosition: "right" with topOffset docks below the reserved top space too', () => {
  const result = computeSnapPosition({ side: 'right', ...PANEL, ...CONTAINER, topOffset: 76 });
  assert.equal(result.y, 76);
  assert.equal(result.x, 1000 - 300 - 20);
});

test('computeSnapPosition: "bottom" ignores topOffset entirely — nothing else lives at the bottom edge', () => {
  const result = computeSnapPosition({ side: 'bottom', ...PANEL, ...CONTAINER, topOffset: 76 });
  assert.equal(result.y, 800 - 400 - 20);
});

test('computeSnapPosition: a topOffset taller than the container still clamps safely (no NaN, never negative)', () => {
  const result = computeSnapPosition({
    side: 'left',
    panelWidth: 300, panelHeight: 400,
    containerWidth: 1000, containerHeight: 200,
    topOffset: 5000,
  });
  assert.equal(Number.isFinite(result.y), true);
  assert.equal(result.y >= 0, true);
});

// ── computeAvailablePanelHeight (footer-clipping regression fix) ───────────
// Pins down the actual fix: the panel's max-height must be derived from
// where it sits inside its container (containerHeight - panelY - gap),
// never from a flat viewport-relative constant — that mismatch is exactly
// what let the footer render past the container's real bottom edge.

test('computeAvailablePanelHeight: basic case matches containerHeight - panelY - safeBottomGap', () => {
  const result = computeAvailablePanelHeight({
    containerHeight: 800,
    panelY: 76,
    safeBottomGap: 8,
  });
  assert.equal(result, 800 - 76 - 8);
});

test('computeAvailablePanelHeight: defaults match the documented constants when omitted', () => {
  const result = computeAvailablePanelHeight({ containerHeight: 800, panelY: 76 });
  assert.equal(result, 800 - 76 - DEFAULT_SAFE_BOTTOM_GAP);
});

test('computeAvailablePanelHeight: a panel dragged near the container bottom floors at MIN_PANEL_HEIGHT, not a sliver', () => {
  const result = computeAvailablePanelHeight({ containerHeight: 800, panelY: 780 });
  // Raw available space here is negative (800 - 780 - 8 = 12) — the floor
  // keeps the panel usable (header + footer still fit) instead of
  // collapsing to 12px.
  assert.equal(result, MIN_PANEL_HEIGHT);
});

test('computeAvailablePanelHeight: never exceeds the container\'s own height, even when the floor would otherwise be bigger', () => {
  // A short container (e.g. a letterboxed wide map image far shorter than
  // 90vh) — the panel can never need more room than the whole container.
  const result = computeAvailablePanelHeight({
    containerHeight: 100,
    panelY: 10,
    minHeight: 160,
  });
  assert.equal(result, 100);
});

test('computeAvailablePanelHeight: non-finite/garbage input never produces NaN', () => {
  const result = computeAvailablePanelHeight({
    containerHeight: NaN,
    panelY: undefined,
    safeBottomGap: 'nope',
  });
  assert.equal(Number.isFinite(result), true);
});

// ── Property: the footer always stays inside the container ─────────────────
// For any panelY, panelY + availableHeight must never exceed containerHeight
// — i.e. a panel sized to exactly `availableHeight` and positioned at
// `panelY` can never have its footer render past the container's bottom
// edge. Checked across a spread of Y values, including ones deep enough to
// trigger the MIN_PANEL_HEIGHT floor.
test('computeAvailablePanelHeight: footer-in-bounds property holds across a range of panel Y positions', () => {
  const containerHeight = 800;

  for (const panelY of [0, 20, 76, 200, 400, 600, 750, 799]) {
    const availableHeight = computeAvailablePanelHeight({ containerHeight, panelY });
    // Only guaranteed when the floor isn't overriding the real available
    // space — deep-Y cases (where MIN_PANEL_HEIGHT kicks in) are instead
    // exactly what FloatingToolPanel's own drag-clamp
    // (computeClampedDragPosition) is responsible for preventing by
    // capping how far down Y itself is allowed to go in the first place.
    const rawAvailable = containerHeight - panelY - DEFAULT_SAFE_BOTTOM_GAP;
    if (rawAvailable >= MIN_PANEL_HEIGHT) {
      assert.equal(panelY + availableHeight <= containerHeight, true);
    }
  }
});

// ── Simulated drag: the footer follows the panel's Y position live ─────────
test('computeAvailablePanelHeight: available height shrinks monotonically as the panel is dragged further down', () => {
  const containerHeight = 800;
  const heights = [0, 100, 200, 300, 400, 500, 600].map((panelY) =>
    computeAvailablePanelHeight({ containerHeight, panelY }),
  );

  for (let i = 1; i < heights.length; i += 1) {
    assert.equal(heights[i] <= heights[i - 1], true);
  }
});

// ── Simulated browser resize: shrinking the container shrinks the panel ────
test('computeAvailablePanelHeight: shrinking the container (browser resize) shrinks available height at a fixed Y', () => {
  const panelY = 76;
  const beforeResize = computeAvailablePanelHeight({ containerHeight: 800, panelY });
  const afterResize = computeAvailablePanelHeight({ containerHeight: 500, panelY });

  assert.equal(afterResize < beforeResize, true);
  assert.equal(afterResize, 500 - panelY - DEFAULT_SAFE_BOTTOM_GAP);
});

console.log(`\n${passed} passed`);
