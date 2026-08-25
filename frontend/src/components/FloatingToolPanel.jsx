import { useEffect, useRef, useState } from 'react';
import {
  clampPanelPosition,
  computeClampedDragPosition,
  computeSnapPosition,
  computeAvailablePanelHeight,
  DEFAULT_SAFE_BOTTOM_GAP,
} from '../utils/floatingPanelHelpers';

// Draggable, collapsible floating tool panel used by the full-map view's
// Add Point / Draw Walkable Path / Test Route control panels.
//
// Fixes the "panel is fixed in the top-left corner and permanently blocks
// part of the map underneath it" bug: the panel now has a dedicated drag
// handle (pointer events, not the whole panel) so it can be moved anywhere
// inside the map container, a minimize/restore control so it can be
// collapsed down to a small pill, and is always clamped to stay fully
// inside the container — including after a window resize or after its own
// content changes size (e.g. switching modes).
//
// Position/collapsed state are owned by the caller (AdminMapScreen) so a
// single shared state object naturally persists across mode switches —
// only one of the three mode panels is ever mounted at a time, and they
// all render through this same component.
const FloatingToolPanel = ({
  title,
  position,
  onPositionChange,
  isCollapsed,
  onToggleCollapse,
  onDragStateChange,
  containerRef,
  isRTL = false,
  width = 300,
  children,
  // Optional sticky action footer (Save/Cancel and similar primary
  // actions). Rendered as a flex sibling of the scrollable body — NOT
  // inside it — so it is never scrolled out of reach no matter how tall
  // the body's content grows. When omitted, panels behave exactly as
  // before (all content simply lives in the scrollable body).
  footer,
  moveLabel = 'Move panel',
  minimizeLabel = 'Minimize panel',
  restoreLabel = 'Restore panel',
  showSnapControls = false,
  snapLabels,
  // Reserves vertical space above the container's top edge when docking
  // left/right (e.g. so the panel never lands underneath a mode toolbar or
  // a modal close button living in that same corner). Bottom docking is
  // unaffected. Defaults to computeSnapPosition's own default (its margin)
  // when omitted, matching the pre-existing plain top-corner dock.
  snapTopOffset,
  // Stacking order for this panel. Optional and additive: when omitted no
  // z-index is emitted at all, so the panels that render one-at-a-time
  // (Add Point / Draw / Vertical Connections / Test Route / batch
  // placement / the toolbox) keep the exact stacking they had before —
  // the CSS class's own `z-index: 1`. Only callers that can show several
  // panels simultaneously pass a number here.
  zIndex,
  // Fired on pointer-down anywhere inside the panel. Lets a multi-panel
  // caller raise the clicked panel to the front. Optional — undefined for
  // every pre-existing caller, in which case React attaches no handler.
  onFocusRequest,
  className = '',
}) => {
  const panelRef = useRef(null);
  const dragStateRef = useRef(null);

  // The container's live height, in the same container-local coordinate
  // space as `position.{x,y}` — kept as state (not just read ad hoc)
  // so `availableHeight` below can be recomputed on every render,
  // including the ones a live drag triggers (see `availableHeight` below
  // for why that matters). Updated by the same `reclamp()` effect that
  // already measures the container for X/Y clamping, so no separate
  // ResizeObserver is needed just for this.
  const [containerHeight, setContainerHeight] = useState(0);

  // Refs mirroring the latest props so the ResizeObserver/resize-listener
  // effect below never closes over a stale `position` or `onPositionChange`
  // — without this, re-running that effect on every position change (i.e.
  // every single pixel of a drag) would mean constantly tearing down and
  // re-creating the ResizeObserver, which is both wasteful and can miss
  // resize events during the gap.
  const positionRef = useRef(position);
  positionRef.current = position;
  const onPositionChangeRef = useRef(onPositionChange);
  onPositionChangeRef.current = onPositionChange;

  const KEYBOARD_STEP = 24;

  // Requirement: recalculate safe bounds whenever the browser is resized,
  // the panel changes size (mode switch, collapse/restore, dynamic content
  // like a Test Route result appearing), or the container itself changes.
  // A ResizeObserver on the panel element covers "panel changed size" for
  // any reason (including a mode switch, since that swaps the rendered
  // children); the window resize listener covers viewport/container
  // changes that don't necessarily resize the panel itself.
  useEffect(() => {
    const panelEl = panelRef.current;
    const container = containerRef?.current;

    if (!panelEl || !container) return undefined;

    const reclamp = () => {
      const panelRect = panelEl.getBoundingClientRect();
      const containerRect = container.getBoundingClientRect();

      if (!containerRect.width || !containerRect.height) return;

      // Feeds `availableHeight` below — also covers "browser resize" and
      // "the container itself changed size" (e.g. a differently-shaped
      // map image loaded) directly, since this whole function already
      // reruns on window resize / container ref change / panel resize.
      setContainerHeight(containerRect.height);

      const current = positionRef.current || { x: 0, y: 0 };

      const clamped = clampPanelPosition({
        x: current.x,
        y: current.y,
        panelWidth: panelRect.width,
        panelHeight: panelRect.height,
        containerWidth: containerRect.width,
        containerHeight: containerRect.height,
      });

      if (clamped.x !== current.x || clamped.y !== current.y) {
        onPositionChangeRef.current?.(clamped);
      }
    };

    const resizeObserver = new ResizeObserver(reclamp);
    resizeObserver.observe(panelEl);
    window.addEventListener('resize', reclamp);

    // Run once immediately too — covers "the full-map modal just opened"
    // and "the panel just switched modes" without waiting for an actual
    // resize event to fire.
    reclamp();

    return () => {
      resizeObserver.disconnect();
      window.removeEventListener('resize', reclamp);
    };
    // Deliberately excludes `position` — see positionRef above.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [containerRef, isCollapsed]);

  // ── Drag handling (pointer events + native pointer capture) ───────────
  // Pointer capture means move/up events keep firing on the handle itself
  // even once the cursor leaves it, so no window-level listener wiring is
  // needed. The handle is a small, dedicated sub-element — buttons, the
  // collapse control, and all form inputs inside the panel body live
  // outside it, so clicking/typing in them can never also start a drag.
  const handleDragPointerDown = (event) => {
    // Primary button / primary touch point only.
    if (event.button !== undefined && event.button !== 0) return;

    event.stopPropagation();

    const panelEl = panelRef.current;
    if (!panelEl) return;

    dragStateRef.current = {
      startPointerX: event.clientX,
      startPointerY: event.clientY,
      startPanelX: position.x,
      startPanelY: position.y,
    };

    onDragStateChange?.(true);

    try {
      event.currentTarget.setPointerCapture?.(event.pointerId);
    } catch {
      // Pointer capture isn't available in every test/legacy environment —
      // dragging still works via the move handler below either way.
    }
  };

  const handleDragPointerMove = (event) => {
    if (!dragStateRef.current) return;

    event.stopPropagation();

    const container = containerRef?.current;
    const panelEl = panelRef.current;
    if (!container || !panelEl) return;

    const containerRect = container.getBoundingClientRect();
    const panelRect = panelEl.getBoundingClientRect();

    const next = computeClampedDragPosition({
      dragStartPanelX: dragStateRef.current.startPanelX,
      dragStartPanelY: dragStateRef.current.startPanelY,
      dragStartPointerX: dragStateRef.current.startPointerX,
      dragStartPointerY: dragStateRef.current.startPointerY,
      pointerX: event.clientX,
      pointerY: event.clientY,
      panelWidth: panelRect.width,
      panelHeight: panelRect.height,
      containerWidth: containerRect.width,
      containerHeight: containerRect.height,
    });

    onPositionChange?.(next);
  };

  const endDrag = (event) => {
    if (!dragStateRef.current) return;

    event.stopPropagation();
    dragStateRef.current = null;
    onDragStateChange?.(false);

    try {
      event.currentTarget.releasePointerCapture?.(event.pointerId);
    } catch {
      // Ignore — nothing to release in environments without pointer capture.
    }
  };

  // Keyboard alternative to dragging: with the drag handle focused, arrow
  // keys nudge the panel by a fixed step, always going back through the
  // same clamp logic as a pointer drag.
  const handleHandleKeyDown = (event) => {
    const deltas = {
      ArrowLeft: { x: -KEYBOARD_STEP, y: 0 },
      ArrowRight: { x: KEYBOARD_STEP, y: 0 },
      ArrowUp: { x: 0, y: -KEYBOARD_STEP },
      ArrowDown: { x: 0, y: KEYBOARD_STEP },
    };

    const delta = deltas[event.key];
    if (!delta) return;

    event.preventDefault();
    event.stopPropagation();

    const container = containerRef?.current;
    const panelEl = panelRef.current;
    if (!container || !panelEl) return;

    const containerRect = container.getBoundingClientRect();
    const panelRect = panelEl.getBoundingClientRect();

    const clamped = clampPanelPosition({
      x: position.x + delta.x,
      y: position.y + delta.y,
      panelWidth: panelRect.width,
      panelHeight: panelRect.height,
      containerWidth: containerRect.width,
      containerHeight: containerRect.height,
    });

    onPositionChange?.(clamped);
  };

  const handleSnap = (side) => {
    const container = containerRef?.current;
    const panelEl = panelRef.current;
    if (!container || !panelEl) return;

    const containerRect = container.getBoundingClientRect();
    const panelRect = panelEl.getBoundingClientRect();

    onPositionChange?.(
      computeSnapPosition({
        side,
        panelWidth: panelRect.width,
        panelHeight: panelRect.height,
        containerWidth: containerRect.width,
        containerHeight: containerRect.height,
        ...(Number.isFinite(snapTopOffset) ? { topOffset: snapTopOffset } : {}),
      }),
    );
  };

  const labels = {
    left: snapLabels?.left || 'Dock left',
    right: snapLabels?.right || 'Dock right',
    bottom: snapLabels?.bottom || 'Dock bottom',
  };

  // The actual fix: derived fresh on every render (not just when the
  // reclamp effect runs) from `position.y` — a plain prop that is always
  // current, including on every single render a live drag triggers (each
  // pointermove calls onPositionChange, which updates the parent's state,
  // which re-renders this component with a new `position.y`). This is
  // what makes the footer track the panel's Y position live while
  // dragging, not just after a resize/collapse/mode-switch settles.
  //
  // Before the container has been measured at least once (containerHeight
  // is still 0), `availableHeight` is left undefined so the CSS class's
  // static `calc(100vh - 40px)` applies as a safe initial default —
  // exactly one frame, until the mount-time reclamp() effect runs.
  const availableHeight = containerHeight
    ? computeAvailablePanelHeight({
        containerHeight,
        panelY: position.y,
        safeBottomGap: DEFAULT_SAFE_BOTTOM_GAP,
      })
    : undefined;

  return (
    <div
      ref={panelRef}
      // Stops a click anywhere in the panel (buttons, inputs, the header)
      // from ever bubbling up to the full-map backdrop's own onClick
      // (which closes the modal) or the map image's onClick (which would
      // otherwise place/select a point). This is defense-in-depth on top
      // of the fact that the panel and the map image are separate,
      // non-overlapping-in-the-DOM-tree elements to begin with.
      onClick={(event) => event.stopPropagation()}
      // Capture phase, so a click that lands on a button *inside* the
      // panel still raises the panel first. This handler only reads the
      // event — it never calls preventDefault or stopPropagation — so it
      // cannot interfere with the drag handle's own pointer handlers or
      // with any control's onClick.
      onPointerDownCapture={onFocusRequest}
      className={`tool-panel${isCollapsed ? ' tool-panel-collapsed' : ''} ${className}`}
      style={{
        position: 'absolute',
        left: position.x,
        top: position.y,
        width: isCollapsed ? 'auto' : width,
        // Only emitted when the caller actually asked for one — see the
        // `zIndex` prop comment above.
        ...(Number.isFinite(zIndex) ? { zIndex } : {}),
        // Overrides the CSS class's static calc(100vh - 40px) with the
        // real, position-aware limit once the container has been
        // measured. Collapsed panels are just a small pill and never
        // need this. Inline style wins over the CSS class, and falls
        // back to that class's viewport-relative value (via `undefined`)
        // for the one frame before the container is first measured.
        ...(availableHeight && !isCollapsed
          ? { maxHeight: availableHeight }
          : {}),
      }}
      dir={isRTL ? 'rtl' : 'ltr'}
    >
      <div
        className="tool-panel-header"
        // The handle itself starts the drag; the collapse/restore button
        // is a sibling, not a descendant of the handle, so it never also
        // triggers a drag when clicked.
      >
        <div
          className="tool-panel-drag-handle"
          role="button"
          tabIndex={0}
          aria-label={moveLabel}
          onPointerDown={handleDragPointerDown}
          onPointerMove={handleDragPointerMove}
          onPointerUp={endDrag}
          onPointerCancel={endDrag}
          onKeyDown={handleHandleKeyDown}
        >
          <span className="tool-panel-grip" aria-hidden="true">
            <span />
            <span />
            <span />
          </span>
          <span className="tool-panel-title">{title}</span>
        </div>

        <div className="tool-panel-header-actions">
          {showSnapControls && !isCollapsed && (
            <>
              <button
                type="button"
                className="tool-panel-snap-btn"
                aria-label={labels.left}
                title={labels.left}
                onClick={() => handleSnap('left')}
              >
                ⇤
              </button>
              <button
                type="button"
                className="tool-panel-snap-btn"
                aria-label={labels.right}
                title={labels.right}
                onClick={() => handleSnap('right')}
              >
                ⇥
              </button>
              <button
                type="button"
                className="tool-panel-snap-btn"
                aria-label={labels.bottom}
                title={labels.bottom}
                onClick={() => handleSnap('bottom')}
              >
                ⇓
              </button>
            </>
          )}

          <button
            type="button"
            className="tool-panel-collapse-btn"
            aria-label={isCollapsed ? restoreLabel : minimizeLabel}
            aria-expanded={!isCollapsed}
            title={isCollapsed ? restoreLabel : minimizeLabel}
            onClick={onToggleCollapse}
          >
            {isCollapsed ? '▢' : '—'}
          </button>
        </div>
      </div>

      {!isCollapsed && (
        <>
          {/* The only scrollable region in the panel. `min-height: 0` (in
              CSS) is what actually lets this shrink below its content's
              natural size inside the flex-column parent — without it, a
              tall form would just push the panel's own box past its
              max-height instead of scrolling internally, silently hiding
              whatever's below the visible viewport (the exact "Save button
              unreachable" bug this fixes). stopPropagation on wheel/touch
              keeps a scroll gesture over the panel from ever reaching the
              map underneath (no zoom/pan/click side effects), the same way
              the panel's own onClick already does for pointer clicks. */}
          <div
            className="tool-panel-body"
            onWheel={(event) => event.stopPropagation()}
            onTouchMove={(event) => event.stopPropagation()}
          >
            {children}
          </div>

          {footer && (
            <div className="tool-panel-footer">
              {footer}
            </div>
          )}
        </>
      )}
    </div>
  );
};

export default FloatingToolPanel;
