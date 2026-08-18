import { clampPanelPosition } from './floatingPanelHelpers.js';

// Layout, persistence and stacking bookkeeping for the Admin Map's
// floating panels.
//
// SCOPE — deliberately narrow. This module covers ONLY the panels that
// were converted from fixed absolutely-positioned boxes into real
// FloatingToolPanel instances:
//
//   autoConnectPreview    Auto Connect Destinations — preview review
//   semanticDestPreview   Preview Destinations
//   semanticBatchReview   Fast batch placement — final review screen
//   navBuild              Automatic Navigation Build preview
//   editPoint             Edit Route Point details
//
// The five panels that were ALREADY draggable — Add Point, Draw Walkable
// Path, Vertical Connections, Test Route and the Fast Batch sequential
// placement panel — keep sharing AdminMapScreen's single `panelPosition`
// / `isPanelCollapsed` state and are intentionally NOT registered here.
// Nothing in this file runs for them, so converting the five above
// cannot change how those five behave.

export const MAP_PANEL_STORAGE_PREFIX = 'quickroute:mapPanel:v1:';

// Stacking window for converted panels. Chosen to sit above every
// in-workspace overlay (the SVG route layer, mode instruction bubbles and
// the floor switcher all use z-index 1–30) and far below every modal
// backdrop (10020 / 10030), so raising a floating panel to the front can
// never put it on top of a destructive confirmation dialog.
export const MAP_PANEL_BASE_Z_INDEX = 40;
export const MAP_PANEL_MAX_Z_INDEX = 9000;

export const MAP_PANEL_IDS = {
  autoConnectPreview: 'autoConnectPreview',
  semanticDestPreview: 'semanticDestPreview',
  semanticBatchReview: 'semanticBatchReview',
  navBuild: 'navBuild',
  editPoint: 'editPoint',
  legacyRepair: 'legacyRepair',
};

// side          'left' / 'right' / 'center' in READING order — left and
//               right are mirrored under RTL by
//               computeMapPanelDefaultPosition, so "the review panel sits
//               on the far side from the toolbox" stays true in Arabic
//               and Hebrew. 'center' is direction-neutral.
// vAlign        'top' anchors below the workspace's top offset; 'bottom'
//               anchors above its bottom margin.
// estimatedHeight  the panel's assumed height before it has ever been
//               measured. Used for the first clamp AND, for
//               vAlign: 'bottom', as the offset up from the bottom
//               margin — so it is also what keeps a bottom-anchored
//               panel clear of a top-anchored one. FloatingToolPanel
//               re-clamps against the real measured height on mount, and
//               caps a panel's max-height by its own Y, so a generous
//               estimate here costs nothing but a too-large one eats the
//               gap between the two rows.
//
// Defaults are chosen so that no two panels which can be open AT THE SAME
// TIME start on top of each other. That constraint is the whole reason
// the table is not simply "everything on the left":
//
//   top-left      autoConnectPreview, semanticBatchReview — and, already,
//                 the five shared-position panels (Add Point, Draw, Test
//                 Route, Vertical Connections, batch placement), whose
//                 default this module must not change.
//   bottom-left   semanticDestPreview. It looks like it belongs top-left
//                 with the other review panels, but Preview Destinations
//                 stays mounted while the batch placement panel and the
//                 batch review screen are open — semanticDestPhase is
//                 never moved off 'preview' by
//                 handleStartSemanticBatchPlacement — so top-left is
//                 already taken whenever it matters.
//   top-centre    navBuild. Independent of `mode` entirely, so it can
//                 coexist with literally every other panel; the centre
//                 column is the only slot nothing else claims.
//   top-right     the Navigation Tools toolbox (owned by AdminMapScreen,
//                 not registered here).
//   bottom-right  editPoint — the "opposite side" slot, below the
//                 toolbox rather than under it.
const FALLBACK_LAYOUT = {
  width: 360,
  side: 'left',
  vAlign: 'top',
  estimatedHeight: 400,
};

export const MAP_PANEL_LAYOUT = {
  [MAP_PANEL_IDS.autoConnectPreview]: {
    width: 400,
    side: 'left',
    vAlign: 'top',
    estimatedHeight: 460,
  },
  [MAP_PANEL_IDS.semanticDestPreview]: {
    width: 400,
    side: 'left',
    vAlign: 'bottom',
    estimatedHeight: 380,
  },
  [MAP_PANEL_IDS.semanticBatchReview]: {
    width: 420,
    side: 'left',
    vAlign: 'top',
    estimatedHeight: 400,
  },
  [MAP_PANEL_IDS.navBuild]: {
    width: 360,
    side: 'center',
    vAlign: 'top',
    estimatedHeight: 400,
  },
  [MAP_PANEL_IDS.editPoint]: {
    width: 340,
    side: 'right',
    vAlign: 'bottom',
    estimatedHeight: 420,
  },
  // Legacy repair is a one-off maintenance panel opened on its own, so it
  // shares the top-left review slot — nothing an admin would have open at
  // the same time lives there.
  [MAP_PANEL_IDS.legacyRepair]: {
    width: 420,
    side: 'left',
    vAlign: 'top',
    estimatedHeight: 400,
  },
};

export function getMapPanelLayout(panelId) {
  return MAP_PANEL_LAYOUT[panelId] || FALLBACK_LAYOUT;
}

export function getMapPanelWidth(panelId) {
  return getMapPanelLayout(panelId).width;
}

export function mapPanelStorageKey(panelId) {
  return `${MAP_PANEL_STORAGE_PREFIX}${panelId}`;
}

function toFinite(value, fallback) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

// Storage is resolved lazily and defensively: private mode, a disabled
// storage policy or SSR all just mean "no persistence", never a throw.
// Tests pass their own Map-backed stub instead of touching window.
function resolveStorage(storage) {
  if (storage) return storage;

  try {
    if (typeof window === 'undefined' || !window.localStorage) return null;
    return window.localStorage;
  } catch {
    return null;
  }
}

export function readStoredMapPanelState(panelId, storage) {
  const store = resolveStorage(storage);
  if (!store) return null;

  try {
    const raw = store.getItem(mapPanelStorageKey(panelId));
    if (!raw) return null;

    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== 'object') return null;

    const x = Number(parsed.position?.x);
    const y = Number(parsed.position?.y);

    return {
      position:
        Number.isFinite(x) && Number.isFinite(y) ? { x, y } : null,
      collapsed: parsed.collapsed === true,
    };
  } catch {
    // Unparseable or unreadable — fall back to the default position
    // rather than letting one bad key break the whole map screen.
    return null;
  }
}

export function writeStoredMapPanelState(panelId, state, storage) {
  const store = resolveStorage(storage);
  if (!store || !state?.position) return false;

  try {
    store.setItem(
      mapPanelStorageKey(panelId),
      JSON.stringify({
        position: { x: state.position.x, y: state.position.y },
        collapsed: state.collapsed === true,
      }),
    );
    return true;
  } catch {
    return false;
  }
}

export function computeMapPanelDefaultPosition({
  panelId,
  containerWidth,
  containerHeight,
  isRTL = false,
  margin = 20,
  topOffset = 76,
}) {
  const layout = getMapPanelLayout(panelId);
  const safeWidth = Math.max(1, toFinite(containerWidth, 1));
  const safeHeight = Math.max(1, toFinite(containerHeight, 1));

  let x;
  if (layout.side === 'center') {
    x = Math.round((safeWidth - layout.width) / 2);
  } else {
    const wantsRight = isRTL
      ? layout.side === 'left'
      : layout.side === 'right';
    x = wantsRight ? safeWidth - layout.width - margin : margin;
  }

  const y =
    layout.vAlign === 'bottom'
      ? safeHeight - layout.estimatedHeight - margin
      : topOffset;

  return clampPanelPosition({
    x,
    y,
    panelWidth: layout.width,
    panelHeight: layout.estimatedHeight,
    containerWidth: safeWidth,
    containerHeight: safeHeight,
    margin,
  });
}

// Called once per panel, the first time it becomes visible in a given
// full-map session. A previously dragged position wins over the default,
// but is re-clamped first so a position saved on a wide monitor can never
// strand the panel off-screen on a narrow one.
export function createInitialMapPanelState({
  panelId,
  containerWidth,
  containerHeight,
  isRTL = false,
  zIndex = MAP_PANEL_BASE_Z_INDEX,
  storage,
}) {
  const layout = getMapPanelLayout(panelId);
  const stored = readStoredMapPanelState(panelId, storage);

  const position = stored?.position
    ? clampPanelPosition({
        x: stored.position.x,
        y: stored.position.y,
        panelWidth: layout.width,
        panelHeight: layout.estimatedHeight,
        containerWidth,
        containerHeight,
      })
    : computeMapPanelDefaultPosition({
        panelId,
        containerWidth,
        containerHeight,
        isRTL,
      });

  return {
    position,
    collapsed: stored ? stored.collapsed === true : false,
    zIndex,
  };
}

// Bring `panelId` to the front.
//
// Returns the SAME object reference when the panel is already frontmost.
// That matters: this runs on every pointer-down inside a panel, including
// the one that starts a drag, and returning a new object there would
// re-render mid-gesture for no reason.
export function raiseMapPanel(panels, panelId) {
  if (!panels || typeof panels !== 'object') return panels;

  const entry = panels[panelId];
  if (!entry) return panels;

  const own = toFinite(entry.zIndex, MAP_PANEL_BASE_Z_INDEX);

  let highestOther = MAP_PANEL_BASE_Z_INDEX - 1;
  Object.keys(panels).forEach((id) => {
    if (id === panelId) return;
    const z = toFinite(panels[id]?.zIndex, MAP_PANEL_BASE_Z_INDEX);
    if (z > highestOther) highestOther = z;
  });

  if (own > highestOther) return panels;

  const raised = highestOther + 1;

  // One increment per click is unbounded in principle. Renormalising well
  // below the modal layer keeps a long editing session from ever climbing
  // into it, while preserving the current front-to-back order.
  if (raised >= MAP_PANEL_MAX_Z_INDEX) {
    const order = Object.keys(panels)
      .filter((id) => id !== panelId)
      .sort(
        (a, b) =>
          toFinite(panels[a]?.zIndex, MAP_PANEL_BASE_Z_INDEX) -
          toFinite(panels[b]?.zIndex, MAP_PANEL_BASE_Z_INDEX),
      );

    const next = {};
    order.forEach((id, index) => {
      next[id] = { ...panels[id], zIndex: MAP_PANEL_BASE_Z_INDEX + index };
    });
    next[panelId] = {
      ...entry,
      zIndex: MAP_PANEL_BASE_Z_INDEX + order.length,
    };
    return next;
  }

  return { ...panels, [panelId]: { ...entry, zIndex: raised } };
}
