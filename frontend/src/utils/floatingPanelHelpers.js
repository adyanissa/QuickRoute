// Pure positioning helpers for the full-map view's floating tool panel
// (Add Point / Draw Walkable Path / Test Route control panel). Kept
// dependency-free so the clamp/drag/default-position math that fixes the
// "panel permanently blocks part of the map" bug can be unit-tested
// without a DOM/React harness — see floatingPanelHelpers.test.mjs.
//
// Every position is a plain { x, y } pair of CSS pixels, always measured
// relative to the full-map container's top-left corner (the same origin
// `getBoundingClientRect()` uses), regardless of language direction —
// dragging is inherently a physical/visual action, so positions here are
// never "logical" (start/end) coordinates. RTL only affects the panel's
// *default* starting side and its own internal text direction, both of
// which are handled by the caller.

// Smallest on-screen box the panel is ever clamped against, even if the
// caller passes a bogus/zero width or height (e.g. before the panel has
// actually been measured yet) — keeps clamping math from producing NaN or
// letting the panel be treated as having no footprint at all.
const MIN_DIMENSION = 1;

// Minimum space (in CSS px) to always leave between the panel's bottom
// edge and the container's bottom edge — same purpose as clampPanelPosition's
// `margin`, kept as its own named constant since it specifically protects
// the footer, not general X/Y positioning.
export const DEFAULT_SAFE_BOTTOM_GAP = 8;

// A panel this short can still show its header, footer, and at least a
// sliver of scrollable body — used as a floor so computeAvailablePanelHeight
// never returns something so small the panel becomes useless, even when the
// panel has been dragged very close to the container's bottom edge.
export const MIN_PANEL_HEIGHT = 160;

function toFiniteNumber(value, fallback = 0) {
  return Number.isFinite(value) ? value : fallback;
}

// Clamps a candidate panel position so its full bounding box — width and
// height included — stays within [margin, container - margin] on both
// axes. If the panel is bigger than the available space (e.g. a very
// narrow phone viewport), it falls back to sitting flush against the
// margin rather than being pushed to a negative/off-screen coordinate.
export function clampPanelPosition({
  x,
  y,
  panelWidth,
  panelHeight,
  containerWidth,
  containerHeight,
  margin = 8,
}) {
  const safeWidth = Math.max(MIN_DIMENSION, toFiniteNumber(panelWidth, MIN_DIMENSION));
  const safeHeight = Math.max(MIN_DIMENSION, toFiniteNumber(panelHeight, MIN_DIMENSION));
  const safeContainerWidth = Math.max(MIN_DIMENSION, toFiniteNumber(containerWidth, MIN_DIMENSION));
  const safeContainerHeight = Math.max(MIN_DIMENSION, toFiniteNumber(containerHeight, MIN_DIMENSION));

  const maxX = Math.max(margin, safeContainerWidth - safeWidth - margin);
  const maxY = Math.max(margin, safeContainerHeight - safeHeight - margin);

  const clampedX = Math.min(Math.max(toFiniteNumber(x, margin), margin), maxX);
  const clampedY = Math.min(Math.max(toFiniteNumber(y, margin), margin), maxY);

  return { x: clampedX, y: clampedY };
}

// True when clamping `position` would actually move it — i.e. it is
// currently (at least partly) outside the visible container. Used to
// decide whether a saved/previous position needs to be pulled back into
// view (e.g. after a resize).
export function isPanelOutsideBounds({
  x,
  y,
  panelWidth,
  panelHeight,
  containerWidth,
  containerHeight,
  margin = 8,
}) {
  const clamped = clampPanelPosition({
    x,
    y,
    panelWidth,
    panelHeight,
    containerWidth,
    containerHeight,
    margin,
  });

  return clamped.x !== x || clamped.y !== y;
}

// A sensible starting position: near the top, on the leading side for the
// current text direction (left for LTR, right for RTL) so the panel opens
// somewhere natural without the caller needing to know anything about
// RTL itself. Still always clamped, so it is safe to call before the
// container has ever been measured (falls back to the margin).
export function computeDefaultPanelPosition({
  containerWidth,
  containerHeight,
  panelWidth,
  panelHeight,
  isRTL = false,
  topOffset = 76,
  margin = 20,
}) {
  const safeContainerWidth = Math.max(MIN_DIMENSION, toFiniteNumber(containerWidth, MIN_DIMENSION));
  const safeWidth = Math.max(MIN_DIMENSION, toFiniteNumber(panelWidth, MIN_DIMENSION));

  const x = isRTL ? safeContainerWidth - safeWidth - margin : margin;

  return clampPanelPosition({
    x,
    y: topOffset,
    panelWidth,
    panelHeight,
    containerWidth,
    containerHeight,
    margin,
  });
}

// Delta-based drag: the new panel position is the position it had when
// the drag started, plus however far the pointer has moved since. Using a
// delta (rather than re-deriving an absolute position from the pointer
// every move) means the panel doesn't jump to align its top-left corner
// with the cursor the instant a drag starts — it moves exactly as far as
// the pointer does, from wherever the admin grabbed it.
export function computeDragPosition({
  dragStartPanelX,
  dragStartPanelY,
  dragStartPointerX,
  dragStartPointerY,
  pointerX,
  pointerY,
}) {
  return {
    x: toFiniteNumber(dragStartPanelX) + (toFiniteNumber(pointerX) - toFiniteNumber(dragStartPointerX)),
    y: toFiniteNumber(dragStartPanelY) + (toFiniteNumber(pointerY) - toFiniteNumber(dragStartPointerY)),
  };
}

// Convenience wrapper combining the two steps every real drag-move needs:
// compute the raw delta-based position, then clamp it into bounds. Kept
// separate from computeDragPosition/clampPanelPosition individually so
// each can still be tested and reasoned about on its own.
export function computeClampedDragPosition({
  dragStartPanelX,
  dragStartPanelY,
  dragStartPointerX,
  dragStartPointerY,
  pointerX,
  pointerY,
  panelWidth,
  panelHeight,
  containerWidth,
  containerHeight,
  margin = 8,
}) {
  const raw = computeDragPosition({
    dragStartPanelX,
    dragStartPanelY,
    dragStartPointerX,
    dragStartPointerY,
    pointerX,
    pointerY,
  });

  return clampPanelPosition({
    x: raw.x,
    y: raw.y,
    panelWidth,
    panelHeight,
    containerWidth,
    containerHeight,
    margin,
  });
}

// The actual fix for "footer clipped below the visible area": the panel's
// max-height must be derived from where it currently sits inside its
// container, not from a flat 100vh-based constant. A panel positioned at
// `panelY` inside a container of `containerHeight` only ever has
// `containerHeight - panelY - safeBottomGap` px of real room below it —
// regardless of how tall the viewport itself is, or how short the
// container is relative to the viewport (e.g. a letterboxed map image far
// shorter than 90vh). Every position here is in the same container-local
// coordinate space as `position.{x,y}` elsewhere in this module, so
// `containerBottom` in that space is simply `containerHeight` (the
// container's own top is always local y = 0).
//
// Never returns more than the container's own full height (a panel can
// never need to be taller than its entire container), and never less than
// `minHeight` (so an aggressively-dragged-down panel still shows a usable
// header + footer instead of collapsing to a sliver) — when the container
// itself is shorter than `minHeight`, the container's height wins, since
// the panel can never exceed its container either way.
export function computeAvailablePanelHeight({
  containerHeight,
  panelY,
  safeBottomGap = DEFAULT_SAFE_BOTTOM_GAP,
  minHeight = MIN_PANEL_HEIGHT,
}) {
  const safeContainerHeight = Math.max(
    MIN_DIMENSION,
    toFiniteNumber(containerHeight, MIN_DIMENSION),
  );
  const safeY = Math.max(0, toFiniteNumber(panelY, 0));
  const safeGap = Math.max(0, toFiniteNumber(safeBottomGap, DEFAULT_SAFE_BOTTOM_GAP));
  const safeMinHeight = Math.max(MIN_DIMENSION, toFiniteNumber(minHeight, MIN_DIMENSION));

  const available = safeContainerHeight - safeY - safeGap;
  const flooredAtMin = Math.max(safeMinHeight, available);

  return Math.min(safeContainerHeight, flooredAtMin);
}

// Optional "snap to side" presets (left / right / bottom docking). Pure
// position math only — no opinion on width/height changes, so a panel
// that merely repositions (rather than visually re-docking/resizing)
// still behaves predictably.
//
// `side` is always a physical direction — 'left' always means the
// geometric left edge of the container and 'right' always means the
// geometric right edge, regardless of text direction. This is deliberate:
// callers expose "Dock left" / "Dock right" as two distinct, explicit
// buttons (not a single RTL-flipping "leading/trailing" toggle), so a
// click always docks to the side the button visually points at, in every
// language. Only a panel's *default/initial* placement (see
// computeDefaultPanelPosition above) adapts to RTL — manual docking never
// does.
//
// `topOffset` (defaults to `margin`, i.e. the previous, plain top-corner
// behavior) lets a caller reserve vertical space above the container's own
// top edge for anything else that lives up there — e.g. a mode toolbar or
// a modal close button positioned in that same corner — so docking left or
// right can never permanently land the panel underneath them. Bottom
// docking has no such concern (nothing else lives at the bottom edge) and
// always continues to use `margin`.
export function computeSnapPosition({
  side,
  panelWidth,
  panelHeight,
  containerWidth,
  containerHeight,
  margin = 20,
  topOffset = margin,
}) {
  const safeContainerWidth = Math.max(MIN_DIMENSION, toFiniteNumber(containerWidth, MIN_DIMENSION));
  const safeContainerHeight = Math.max(MIN_DIMENSION, toFiniteNumber(containerHeight, MIN_DIMENSION));
  const safeWidth = Math.max(MIN_DIMENSION, toFiniteNumber(panelWidth, MIN_DIMENSION));
  const safeHeight = Math.max(MIN_DIMENSION, toFiniteNumber(panelHeight, MIN_DIMENSION));
  const safeTopOffset = Math.max(0, toFiniteNumber(topOffset, margin));

  let x = margin;
  let y = safeTopOffset;

  if (side === 'right') {
    x = safeContainerWidth - safeWidth - margin;
    y = safeTopOffset;
  } else if (side === 'bottom') {
    x = margin;
    y = safeContainerHeight - safeHeight - margin;
  } else {
    // 'left' (and any unrecognized value) — default dock.
    x = margin;
    y = safeTopOffset;
  }

  return clampPanelPosition({
    x,
    y,
    panelWidth,
    panelHeight,
    containerWidth,
    containerHeight,
    margin,
  });
}
