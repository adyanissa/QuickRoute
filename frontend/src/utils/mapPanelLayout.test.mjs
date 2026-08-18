import assert from 'node:assert/strict';
import test from 'node:test';

import {
  MAP_PANEL_BASE_Z_INDEX,
  MAP_PANEL_IDS,
  MAP_PANEL_MAX_Z_INDEX,
  MAP_PANEL_STORAGE_PREFIX,
  MAP_PANEL_LAYOUT,
  computeMapPanelDefaultPosition,
  createInitialMapPanelState,
  getMapPanelWidth,
  mapPanelStorageKey,
  raiseMapPanel,
  readStoredMapPanelState,
  raiseMapPanel as raise,
  writeStoredMapPanelState,
} from './mapPanelLayout.js';

// A localStorage stand-in. The module never touches `window` when one of
// these is passed in, so these tests run under plain node.
function makeStorage(initial = {}) {
  const map = new Map(Object.entries(initial));
  return {
    getItem: (key) => (map.has(key) ? map.get(key) : null),
    setItem: (key, value) => map.set(key, String(value)),
    _map: map,
  };
}

function throwingStorage() {
  return {
    getItem() {
      throw new Error('storage disabled');
    },
    setItem() {
      throw new Error('storage disabled');
    },
  };
}

const WORKSPACE = { containerWidth: 1400, containerHeight: 900 };

test('each registered panel has its own storage key', () => {
  const keys = Object.values(MAP_PANEL_IDS).map(mapPanelStorageKey);

  assert.equal(new Set(keys).size, keys.length);
  keys.forEach((key) => assert.ok(key.startsWith(MAP_PANEL_STORAGE_PREFIX)));
});

test('the five already-draggable panels are NOT registered here', () => {
  // Guard against someone later folding the shared-position panels into
  // this module — the whole point is that they keep their old behaviour.
  const registered = Object.keys(MAP_PANEL_IDS);

  ['addPoint', 'draw', 'test', 'connector', 'semanticBatch', 'toolbox'].forEach(
    (id) => assert.ok(!registered.includes(id), `${id} must not be registered`),
  );
  assert.equal(registered.length, 6);
});

// Rectangles overlap unless one is entirely to the side of, or entirely
// above/below, the other.
function overlaps(a, b) {
  return (
    a.x < b.x + b.width &&
    b.x < a.x + a.width &&
    a.y < b.y + b.height &&
    b.y < a.y + a.height
  );
}

function rectFor(panelId, workspace = WORKSPACE, isRTL = false) {
  const { x, y } = computeMapPanelDefaultPosition({
    panelId,
    ...workspace,
    isRTL,
  });
  const layout = MAP_PANEL_LAYOUT[panelId];
  return { x, y, width: layout.width, height: layout.estimatedHeight };
}

// The five panels AdminMapScreen still positions through the shared
// `panelPosition` state, plus the toolbox. Their defaults are fixed by
// AdminMapScreen (computeDefaultPanelPosition -> leading side, y = 76;
// toolbox -> trailing side, y = 20) and this module must route around
// them rather than move them.
const SHARED_PANEL_DEFAULT = { x: 20, y: 76, width: 300, height: 320 };
const TOOLBOX_DEFAULT = {
  x: WORKSPACE.containerWidth - 268 - 20,
  y: 20,
  width: 268,
  height: 360,
};

// Pairs that can genuinely be on screen together. Preview Destinations is
// the interesting one: semanticDestPhase stays 'preview' for the whole
// batch flow, so it coexists with both batch panels.
const COEXISTING = [
  [MAP_PANEL_IDS.semanticDestPreview, MAP_PANEL_IDS.semanticBatchReview],
  [MAP_PANEL_IDS.semanticDestPreview, MAP_PANEL_IDS.navBuild],
  [MAP_PANEL_IDS.semanticBatchReview, MAP_PANEL_IDS.navBuild],
  [MAP_PANEL_IDS.autoConnectPreview, MAP_PANEL_IDS.navBuild],
  [MAP_PANEL_IDS.editPoint, MAP_PANEL_IDS.navBuild],
];

test('default positions do not overlap for panels that can coexist', () => {
  COEXISTING.forEach(([a, b]) => {
    assert.ok(
      !overlaps(rectFor(a), rectFor(b)),
      `${a} and ${b} must not start on top of each other`,
    );
  });
});

test('defaults clear the panels this module is not allowed to move', () => {
  // Preview Destinations coexists with the shared-position batch
  // placement panel; navBuild coexists with every shared-position panel.
  [MAP_PANEL_IDS.semanticDestPreview, MAP_PANEL_IDS.navBuild].forEach(
    (panelId) => {
      assert.ok(
        !overlaps(rectFor(panelId), SHARED_PANEL_DEFAULT),
        `${panelId} must clear the shared-position panels`,
      );
    },
  );

  // Everything must clear the always-present toolbox.
  Object.values(MAP_PANEL_IDS).forEach((panelId) => {
    assert.ok(
      !overlaps(rectFor(panelId), TOOLBOX_DEFAULT),
      `${panelId} must clear the toolbox`,
    );
  });
});

test('the centre slot is direction-neutral', () => {
  const ltr = rectFor(MAP_PANEL_IDS.navBuild, WORKSPACE, false);
  const rtl = rectFor(MAP_PANEL_IDS.navBuild, WORKSPACE, true);

  assert.deepEqual({ x: ltr.x, y: ltr.y }, { x: rtl.x, y: rtl.y });
});

test('sides mirror under RTL', () => {
  const ltr = computeMapPanelDefaultPosition({
    panelId: MAP_PANEL_IDS.editPoint,
    ...WORKSPACE,
    isRTL: false,
  });
  const rtl = computeMapPanelDefaultPosition({
    panelId: MAP_PANEL_IDS.editPoint,
    ...WORKSPACE,
    isRTL: true,
  });

  assert.ok(ltr.x > WORKSPACE.containerWidth / 2, 'LTR: trailing side is the right');
  assert.ok(rtl.x < WORKSPACE.containerWidth / 2, 'RTL: trailing side is the left');
});

test('default positions stay inside a tiny workspace', () => {
  Object.values(MAP_PANEL_IDS).forEach((panelId) => {
    const position = computeMapPanelDefaultPosition({
      panelId,
      containerWidth: 320,
      containerHeight: 240,
    });

    assert.ok(position.x >= 0, `${panelId} x`);
    assert.ok(position.y >= 0, `${panelId} y`);
    assert.ok(Number.isFinite(position.x) && Number.isFinite(position.y));
  });
});

test('default position survives missing/garbage container dimensions', () => {
  const position = computeMapPanelDefaultPosition({
    panelId: MAP_PANEL_IDS.navBuild,
    containerWidth: undefined,
    containerHeight: Number.NaN,
  });

  assert.ok(Number.isFinite(position.x));
  assert.ok(Number.isFinite(position.y));
});

test('a stored position is restored, and re-clamped into the workspace', () => {
  const storage = makeStorage({
    [mapPanelStorageKey(MAP_PANEL_IDS.navBuild)]: JSON.stringify({
      position: { x: 4000, y: 3000 },
      collapsed: true,
    }),
  });

  const state = createInitialMapPanelState({
    panelId: MAP_PANEL_IDS.navBuild,
    ...WORKSPACE,
    storage,
  });

  assert.equal(state.collapsed, true);
  assert.ok(state.position.x < WORKSPACE.containerWidth);
  assert.ok(state.position.y < WORKSPACE.containerHeight);
});

test('a corrupt stored value falls back to the default position', () => {
  const storage = makeStorage({
    [mapPanelStorageKey(MAP_PANEL_IDS.navBuild)]: '{not json',
  });

  const state = createInitialMapPanelState({
    panelId: MAP_PANEL_IDS.navBuild,
    ...WORKSPACE,
    storage,
  });
  const fallback = computeMapPanelDefaultPosition({
    panelId: MAP_PANEL_IDS.navBuild,
    ...WORKSPACE,
  });

  assert.deepEqual(state.position, fallback);
  assert.equal(state.collapsed, false);
});

test('unavailable storage never throws', () => {
  const storage = throwingStorage();

  assert.equal(readStoredMapPanelState(MAP_PANEL_IDS.navBuild, storage), null);
  assert.equal(
    writeStoredMapPanelState(
      MAP_PANEL_IDS.navBuild,
      { position: { x: 1, y: 2 } },
      storage,
    ),
    false,
  );
  assert.doesNotThrow(() =>
    createInitialMapPanelState({
      panelId: MAP_PANEL_IDS.navBuild,
      ...WORKSPACE,
      storage,
    }),
  );
});

test('write then read round-trips through one panel-specific key', () => {
  const storage = makeStorage();

  writeStoredMapPanelState(
    MAP_PANEL_IDS.editPoint,
    { position: { x: 120, y: 240 }, collapsed: true },
    storage,
  );

  assert.deepEqual(readStoredMapPanelState(MAP_PANEL_IDS.editPoint, storage), {
    position: { x: 120, y: 240 },
    collapsed: true,
  });
  // ...and nothing leaked into a different panel's key.
  assert.equal(readStoredMapPanelState(MAP_PANEL_IDS.navBuild, storage), null);
  assert.equal(storage._map.size, 1);
});

test('raiseMapPanel brings a panel to the front', () => {
  const panels = {
    a: { zIndex: MAP_PANEL_BASE_Z_INDEX },
    b: { zIndex: MAP_PANEL_BASE_Z_INDEX + 1 },
  };

  const next = raiseMapPanel(panels, 'a');

  assert.ok(next.a.zIndex > next.b.zIndex);
  assert.equal(next.b.zIndex, panels.b.zIndex, 'other panels are untouched');
});

test('raiseMapPanel returns the SAME object when already frontmost', () => {
  const panels = {
    a: { zIndex: MAP_PANEL_BASE_Z_INDEX + 5 },
    b: { zIndex: MAP_PANEL_BASE_Z_INDEX },
  };

  assert.equal(raise(panels, 'a'), panels);
});

test('raiseMapPanel ignores unknown panel ids', () => {
  const panels = { a: { zIndex: MAP_PANEL_BASE_Z_INDEX } };
  assert.equal(raiseMapPanel(panels, 'nope'), panels);
  assert.equal(raiseMapPanel(undefined, 'a'), undefined);
});

test('raiseMapPanel renormalises instead of climbing into the modal layer', () => {
  const panels = {
    a: { zIndex: MAP_PANEL_MAX_Z_INDEX - 1 },
    b: { zIndex: MAP_PANEL_MAX_Z_INDEX - 3 },
    c: { zIndex: MAP_PANEL_MAX_Z_INDEX - 2 },
  };

  const next = raiseMapPanel(panels, 'b');
  const values = Object.values(next).map((entry) => entry.zIndex);

  values.forEach((z) => {
    assert.ok(z >= MAP_PANEL_BASE_Z_INDEX);
    assert.ok(z < MAP_PANEL_MAX_Z_INDEX);
    // Modal backdrops live at 10020/10030 — never reachable from here.
    assert.ok(z < 10020);
  });
  assert.ok(next.b.zIndex > next.a.zIndex && next.b.zIndex > next.c.zIndex);
  // Relative order of the others is preserved.
  assert.ok(next.a.zIndex > next.c.zIndex);
});

test('panel widths are within the requested 340-460px range', () => {
  Object.values(MAP_PANEL_IDS).forEach((panelId) => {
    const width = getMapPanelWidth(panelId);
    assert.ok(width >= 340 && width <= 460, `${panelId} width ${width}`);
  });
});
