// Plain-Node tests for the Draw Walkable Path selection/save-resolution
// helpers (frontend/src/utils/drawPathHelpers.js). The repo has no
// frontend test runner installed (no jest/vitest in package.json), so this
// runs directly via `node drawPathHelpers.test.mjs` and uses only the
// built-in `assert` module. This is the logic responsible for the
// previously-reported "existing point gets duplicated instead of reused"
// bug, so it is verified independently of any browser/DOM behavior.
import assert from 'node:assert/strict';
import {
  normalizePointId,
  resolveExistingPointSelection,
  partitionDraftForSave,
  buildEdgeKeySet,
  buildEdgePlan,
  computeNearbyMergePreview,
  generateDefaultDraftPointName,
  validateDraftPointName,
  isDraftNamingValid,
  updateDraftPointName,
  ROUTE_POINT_NAME_MAX_LENGTH,
} from './drawPathHelpers.js';

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

const MAP_ID = 'map-1';
const pointC = {
  id: 'point-c-id',
  map_id: MAP_ID,
  x: 1200,
  y: 850,
  floor: 1,
  name: 'Corridor Point',
  point_type: 'hallway',
  is_active: true,
};

// 1 & 2 & 3 — clicking an existing marker creates exactly one draft item,
// kind "existing", real database id preserved verbatim.
test('direct selection of an existing point creates one draft item with kind existing and the real id', () => {
  const result = resolveExistingPointSelection({
    point: pointC,
    activeMapId: MAP_ID,
    drawFloor: 1,
    lastDraftPoint: undefined,
  });

  assert.equal(result.ok, true);
  assert.equal(result.draftItem.kind, 'existing');
  assert.equal(result.draftItem.routePointId, 'point-c-id');
  assert.equal(typeof result.draftItem, 'object');
});

// 4 — event propagation does not create a second new draft item. There is
// no real DOM here, but the contract this depends on is: a successful
// selectExistingPointForDraft() call must stop propagation exactly once
// and must be the *only* thing that appends to the draft for that click.
// Simulate the wrapper's contract directly.
test('selection handler stops propagation exactly once and yields exactly one draft append', () => {
  let stopCount = 0;
  const fakeEvent = { stopPropagation: () => { stopCount += 1; } };

  // Mirrors selectExistingPointForDraft's shape in AdminMapScreen.jsx:
  // stopPropagation happens unconditionally before resolution runs.
  function simulateMarkerClick(point, event) {
    event.stopPropagation();
    const result = resolveExistingPointSelection({
      point,
      activeMapId: MAP_ID,
      drawFloor: 1,
      lastDraftPoint: undefined,
    });
    return result.ok ? [result.draftItem] : [];
  }

  const draftAppends = simulateMarkerClick(pointC, fakeEvent);

  assert.equal(stopCount, 1);
  assert.equal(draftAppends.length, 1);
});

// 5 — existing point + two new points causes only two createRoutePoint
// calls (i.e. exactly the two "new" kind drafts, never the existing one).
test('partitionDraftForSave: existing + 2 new only creates 2 points', () => {
  const draftPoints = [
    { kind: 'existing', routePointId: 'point-c-id', x: 1200, y: 850, floor: 1 },
    { kind: 'new', x: 1350, y: 900, floor: 1 },
    { kind: 'new', x: 1500, y: 950, floor: 1 },
  ];

  const { reuses, creates } = partitionDraftForSave(draftPoints);

  assert.equal(reuses.length, 1);
  assert.equal(reuses[0].routePointId, 'point-c-id');
  assert.equal(creates.length, 2);
});

// 6 — edge creation uses existing ID -> new ID (order preserved).
test('buildEdgePlan connects existing id to new ids in draft order', () => {
  const resolvedIds = ['point-c-id', 'new-d-id', 'new-e-id'];
  const existingEdgeKeys = buildEdgeKeySet([]);

  const { toCreate, skippedCount } = buildEdgePlan(resolvedIds, existingEdgeKeys);

  assert.equal(skippedCount, 0);
  assert.deepEqual(toCreate, [
    { fromId: 'point-c-id', toId: 'new-d-id' },
    { fromId: 'new-d-id', toId: 'new-e-id' },
  ]);
});

// 7 — floor "1" (string) and floor 1 (number) are normalized consistently.
test('floor "1" (string, from UI state) matches floor 1 (number, from DB)', () => {
  const result = resolveExistingPointSelection({
    point: { ...pointC, floor: 1 },
    activeMapId: MAP_ID,
    drawFloor: '1',
    lastDraftPoint: undefined,
  });

  assert.equal(result.ok, true);
  assert.equal(result.draftItem.floor, 1);
});

test('floor 2 (number, drawFloor) is correctly rejected against floor 1 (point)', () => {
  const result = resolveExistingPointSelection({
    point: { ...pointC, floor: 1 },
    activeMapId: MAP_ID,
    drawFloor: 2,
    lastDraftPoint: undefined,
  });

  assert.equal(result.ok, false);
  assert.equal(result.reason, 'wrong-floor');
});

// 8 — database object ids and string ids compare consistently.
test('normalizePointId treats an object-like id and its string form as equal after normalization', () => {
  const objectIdLike = { toString: () => 'abc123' };
  const pointWithObjectId = { ...pointC, id: objectIdLike };
  const pointWithStringId = { ...pointC, id: 'abc123' };

  assert.equal(normalizePointId(pointWithObjectId), normalizePointId(pointWithStringId));
});

// 9 — a point from another map cannot be reused.
test('a point belonging to a different map is rejected', () => {
  const result = resolveExistingPointSelection({
    point: { ...pointC, map_id: 'some-other-map' },
    activeMapId: MAP_ID,
    drawFloor: 1,
    lastDraftPoint: undefined,
  });

  assert.equal(result.ok, false);
  assert.equal(result.reason, 'wrong-map');
});

// 10 — an inactive point cannot be reused.
test('an inactive point is rejected', () => {
  const result = resolveExistingPointSelection({
    point: { ...pointC, is_active: false },
    activeMapId: MAP_ID,
    drawFloor: 1,
    lastDraftPoint: undefined,
  });

  assert.equal(result.ok, false);
  assert.equal(result.reason, 'inactive');
});

// 11 — existing point -> existing point can create one edge without
// creating any points.
test('existing -> existing draft creates zero points and exactly one edge', () => {
  const draftPoints = [
    { kind: 'existing', routePointId: 'point-a-id', x: 0, y: 0, floor: 1 },
    { kind: 'existing', routePointId: 'point-c-id', x: 1200, y: 850, floor: 1 },
  ];

  const { reuses, creates } = partitionDraftForSave(draftPoints);
  assert.equal(creates.length, 0);
  assert.equal(reuses.length, 2);

  const resolvedIds = new Array(draftPoints.length).fill(null);
  reuses.forEach(({ index, routePointId }) => {
    resolvedIds[index] = routePointId;
  });

  const { toCreate, skippedCount } = buildEdgePlan(resolvedIds, buildEdgeKeySet([]));
  assert.equal(skippedCount, 0);
  assert.deepEqual(toCreate, [{ fromId: 'point-a-id', toId: 'point-c-id' }]);
});

// Selecting the same existing point twice in a row is a no-op, not a
// zero-length duplicate segment.
test('selecting the same existing point twice consecutively is rejected', () => {
  const first = resolveExistingPointSelection({
    point: pointC,
    activeMapId: MAP_ID,
    drawFloor: 1,
    lastDraftPoint: undefined,
  });

  const second = resolveExistingPointSelection({
    point: pointC,
    activeMapId: MAP_ID,
    drawFloor: 1,
    lastDraftPoint: first.draftItem,
  });

  assert.equal(second.ok, false);
  assert.equal(second.reason, 'duplicate-consecutive');
});

// A duplicate edge already present (either direction) is skipped, not
// recreated.
test('buildEdgePlan skips an edge that already exists in either direction', () => {
  const existingEdgeKeys = buildEdgeKeySet([
    { from_point_id: 'point-d-id', to_point_id: 'point-c-id' },
  ]);

  const { toCreate, skippedCount } = buildEdgePlan(
    ['point-c-id', 'point-d-id'],
    existingEdgeKeys,
  );

  assert.equal(toCreate.length, 0);
  assert.equal(skippedCount, 1);
});

// ── Exact acceptance scenario: existing A-B-C-D, redraw B-C-D-E-F ─────────
// The originally-reported bug only ever checked the first/last draft point
// for reuse. This pins down that EVERY selected point is independently
// resolved — B, C and D are all in the *middle* or *start* of this second
// draft (not just the very first click) and must all still come back as
// "existing", never recreated.
test('middle existing points (not only the first) are reused: B/C/D of a B-C-D-E-F redraw', () => {
  const draftPoints = [
    { kind: 'existing', routePointId: 'point-b-id', x: 10, y: 0, floor: 0 },
    { kind: 'existing', routePointId: 'point-c-id', x: 20, y: 0, floor: 0 },
    { kind: 'existing', routePointId: 'point-d-id', x: 30, y: 0, floor: 0 },
    { kind: 'new', x: 40, y: 0, floor: 0 },
    { kind: 'new', x: 50, y: 0, floor: 0 },
  ];

  const { reuses, creates } = partitionDraftForSave(draftPoints);

  // All three of B, C, D reused — including the two that are NOT the first
  // draft item — and only E, F (genuinely new) trigger a create call.
  assert.equal(reuses.length, 3);
  assert.deepEqual(
    reuses.map((r) => r.routePointId),
    ['point-b-id', 'point-c-id', 'point-d-id'],
  );
  assert.equal(creates.length, 2);

  const resolvedIds = new Array(draftPoints.length).fill(null);
  reuses.forEach(({ index, routePointId }) => {
    resolvedIds[index] = routePointId;
  });
  creates.forEach(({ index }, i) => {
    resolvedIds[index] = `new-id-${i}`;
  });

  // Existing B-C and C-D edges from the first saved path must be skipped,
  // not recreated — only D-E and E-F (the genuinely new segment) plan out.
  const existingEdgeKeys = buildEdgeKeySet([
    { from_point_id: 'point-a-id', to_point_id: 'point-b-id' },
    { from_point_id: 'point-b-id', to_point_id: 'point-c-id' },
    { from_point_id: 'point-c-id', to_point_id: 'point-d-id' },
  ]);

  const { toCreate, skippedCount } = buildEdgePlan(resolvedIds, existingEdgeKeys);

  assert.equal(skippedCount, 2); // B-C and C-D already existed
  assert.deepEqual(toCreate, [
    { fromId: 'point-d-id', toId: 'new-id-0' },
    { fromId: 'new-id-0', toId: 'new-id-1' },
  ]);
});

// ── Branch paths must never remove/replace old edges ───────────────────────
// Drawing a new branch (C-G-H off an existing A-B-C-D) must only ever ADD
// edges — buildEdgePlan/buildEdgeKeySet have no delete path, so this pins
// down that every pre-existing key set from the first path survives
// untouched after planning the second, unrelated branch.
test('branch draft (C-G-H) plans only its own new edges and leaves A-B-C-D edges untouched', () => {
  const originalEdges = [
    { from_point_id: 'point-a-id', to_point_id: 'point-b-id' },
    { from_point_id: 'point-b-id', to_point_id: 'point-c-id' },
    { from_point_id: 'point-c-id', to_point_id: 'point-d-id' },
  ];
  const existingEdgeKeys = buildEdgeKeySet(originalEdges);
  const keysBefore = new Set(existingEdgeKeys);

  const branchDraft = [
    { kind: 'existing', routePointId: 'point-c-id', x: 20, y: 0, floor: 0 },
    { kind: 'new', x: 20, y: 20, floor: 0 },
    { kind: 'new', x: 20, y: 40, floor: 0 },
  ];

  const { reuses, creates } = partitionDraftForSave(branchDraft);
  const resolvedIds = new Array(branchDraft.length).fill(null);
  reuses.forEach(({ index, routePointId }) => {
    resolvedIds[index] = routePointId;
  });
  resolvedIds[creates[0].index] = 'point-g-id';
  resolvedIds[creates[1].index] = 'point-h-id';

  const { toCreate, skippedCount } = buildEdgePlan(resolvedIds, existingEdgeKeys);

  assert.equal(skippedCount, 0);
  assert.deepEqual(toCreate, [
    { fromId: 'point-c-id', toId: 'point-g-id' },
    { fromId: 'point-g-id', toId: 'point-h-id' },
  ]);

  // Every original A-B-C-D key is still present (never deleted/replaced) —
  // buildEdgePlan only ever adds keys for the pair(s) it just planned.
  keysBefore.forEach((key) => {
    assert.equal(existingEdgeKeys.has(key), true);
  });
});

// ── computeNearbyMergePreview (safe automatic nearby merging preview) ─────
test('computeNearbyMergePreview: a new draft point near an existing point gets a preview line', () => {
  const draftPoints = [
    { kind: 'existing', routePointId: 'point-a-id', x: 0, y: 0, floor: 0 },
    { kind: 'new', x: 100, y: 0, floor: 0 },
  ];
  const routePoints = [
    { id: 'point-a-id', map_id: MAP_ID, x: 0, y: 0, floor: 0, is_active: true },
    { id: 'point-z-id', map_id: MAP_ID, x: 120, y: 0, floor: 0, is_active: true },
  ];

  const preview = computeNearbyMergePreview({
    draftPoints,
    routePoints,
    activeMapId: MAP_ID,
    drawFloor: 0,
  });

  assert.equal(preview.length, 1);
  assert.equal(preview[0].toPointId, 'point-z-id');
  assert.equal(preview[0].draftIndex, 1);
});

test('computeNearbyMergePreview: a point already selected into the draft is never offered again as a merge target', () => {
  const draftPoints = [
    { kind: 'existing', routePointId: 'point-z-id', x: 120, y: 0, floor: 0 },
    { kind: 'new', x: 100, y: 0, floor: 0 },
  ];
  const routePoints = [
    { id: 'point-z-id', map_id: MAP_ID, x: 120, y: 0, floor: 0, is_active: true },
  ];

  const preview = computeNearbyMergePreview({
    draftPoints,
    routePoints,
    activeMapId: MAP_ID,
    drawFloor: 0,
  });

  assert.equal(preview.length, 0);
});

test('computeNearbyMergePreview: an inactive or wrong-map/floor point is never suggested', () => {
  const draftPoints = [{ kind: 'new', x: 0, y: 0, floor: 0 }];
  const routePoints = [
    { id: 'inactive', map_id: MAP_ID, x: 5, y: 0, floor: 0, is_active: false },
    { id: 'wrong-map', map_id: 'other-map', x: 5, y: 0, floor: 0, is_active: true },
    { id: 'wrong-floor', map_id: MAP_ID, x: 5, y: 0, floor: 1, is_active: true },
  ];

  const preview = computeNearbyMergePreview({
    draftPoints,
    routePoints,
    activeMapId: MAP_ID,
    drawFloor: 0,
  });

  assert.equal(preview.length, 0);
});

// ── RoutePoint custom naming (Draw Walkable Path) ──────────────────────────

// 11 — new draft points get a short, sequential, non-timestamp default.
test('generateDefaultDraftPointName: short sequential defaults, never a timestamp', () => {
  assert.equal(generateDefaultDraftPointName([]), 'Point 1');

  const afterOneNew = [{ kind: 'new', name: 'Point 1' }];
  assert.equal(generateDefaultDraftPointName(afterOneNew), 'Point 2');

  // Existing/reused points in the draft don't bump the "new" counter.
  const withExistingMixedIn = [
    { kind: 'existing', routePointId: 'a' },
    { kind: 'new', name: 'Point 1' },
    { kind: 'existing', routePointId: 'b' },
  ];
  assert.equal(generateDefaultDraftPointName(withExistingMixedIn), 'Point 2');

  // Never looks like the old bug's timestamp-based name.
  assert.equal(/\d{10,}/.test(generateDefaultDraftPointName([])), false);
});

// 12/13/14 — Arabic, Hebrew, and English names are all preserved verbatim.
test('validateDraftPointName preserves Arabic, Hebrew, and English names exactly', () => {
  const arabic = validateDraftPointName('تقاطع القهوة');
  assert.equal(arabic.ok, true);
  assert.equal(arabic.trimmed, 'تقاطع القهوة');

  const hebrew = validateDraftPointName('צומת הקפה');
  assert.equal(hebrew.ok, true);
  assert.equal(hebrew.trimmed, 'צומת הקפה');

  const english = validateDraftPointName('Coffee Junction');
  assert.equal(english.ok, true);
  assert.equal(english.trimmed, 'Coffee Junction');
});

test('validateDraftPointName trims surrounding whitespace', () => {
  const result = validateDraftPointName('  East Hall  ');
  assert.equal(result.ok, true);
  assert.equal(result.trimmed, 'East Hall');
});

// 15 — empty (or whitespace-only) names prevent Save.
test('isDraftNamingValid: an empty or whitespace-only new-point name blocks save', () => {
  const emptyName = [
    { kind: 'existing', routePointId: 'a' },
    { kind: 'new', name: '' },
  ];
  assert.equal(isDraftNamingValid(emptyName), false);

  const whitespaceOnlyName = [{ kind: 'new', name: '   ' }];
  assert.equal(isDraftNamingValid(whitespaceOnlyName), false);

  const validName = [{ kind: 'new', name: 'Coffee Junction' }];
  assert.equal(isDraftNamingValid(validName), true);

  // All-existing drafts (no new points at all) are never blocked by naming.
  assert.equal(
    isDraftNamingValid([{ kind: 'existing', routePointId: 'a' }]),
    true,
  );
});

test('validateDraftPointName rejects a name over the max length', () => {
  const tooLong = validateDraftPointName('x'.repeat(ROUTE_POINT_NAME_MAX_LENGTH + 1));
  assert.equal(tooLong.ok, false);
  assert.equal(tooLong.reason, 'too-long');

  const exactlyMax = validateDraftPointName('x'.repeat(ROUTE_POINT_NAME_MAX_LENGTH));
  assert.equal(exactlyMax.ok, true);
});

// 16/17 — an existing reused point keeps its saved id and current name,
// and is never renamed just by being selected into a new draft.
test('resolveExistingPointSelection carries the existing point\'s real id and current name, never a draft-derived one', () => {
  const savedPoint = {
    id: 'point-b-id',
    map_id: MAP_ID,
    x: 10,
    y: 0,
    floor: 0,
    name: 'Coffee Junction',
    point_type: 'hallway',
    is_active: true,
  };

  const result = resolveExistingPointSelection({
    point: savedPoint,
    activeMapId: MAP_ID,
    drawFloor: 0,
    lastDraftPoint: undefined,
  });

  assert.equal(result.ok, true);
  assert.equal(result.draftItem.routePointId, 'point-b-id');
  assert.equal(result.draftItem.name, 'Coffee Junction');
});

// 18 — partitionDraftForSave's "creates" entries carry the custom name so
// it reaches the createRoutePoint payload.
test('partitionDraftForSave: new-point entries include the custom name for the create payload', () => {
  const draftPoints = [
    { kind: 'existing', routePointId: 'point-a-id', x: 0, y: 0, floor: 0, name: 'Main Corridor' },
    { kind: 'new', x: 10, y: 0, floor: 0, name: 'Coffee Junction' },
    { kind: 'new', x: 20, y: 0, floor: 0, name: 'East Hall' },
  ];

  const { creates } = partitionDraftForSave(draftPoints);

  assert.deepEqual(
    creates.map((c) => c.name),
    ['Coffee Junction', 'East Hall'],
  );
});

// 19 — a name typed into one point survives Undo of a LATER point (Undo
// only ever drops the last item).
test('typed names survive Undo of another (later) point', () => {
  const draftPoints = [
    { tempId: 'p1', kind: 'new', x: 0, y: 0, floor: 0, name: 'Coffee Junction' },
    { tempId: 'p2', kind: 'new', x: 10, y: 0, floor: 0, name: 'Point 2' },
  ];

  // Simulates handleUndoDraft: drop only the last item.
  const afterUndo = draftPoints.slice(0, -1);

  assert.equal(afterUndo.length, 1);
  assert.equal(afterUndo[0].name, 'Coffee Junction');
});

// 20 — updateDraftPointName only ever changes the target index; every
// other point (and its name) is structurally untouched. This is the
// property that keeps names intact across panel drag/collapse/restore —
// none of those ever call this function at all, and this proves that even
// a real name edit never has any side effect on other points.
test('updateDraftPointName only changes the targeted index, leaving every other point untouched', () => {
  const draftPoints = [
    { tempId: 'p1', kind: 'new', x: 0, y: 0, floor: 0, name: 'Point 1' },
    { tempId: 'p2', kind: 'new', x: 10, y: 0, floor: 0, name: 'Point 2' },
    { tempId: 'p3', kind: 'new', x: 20, y: 0, floor: 0, name: 'Point 3' },
  ];

  const updated = updateDraftPointName(draftPoints, 1, 'Coffee Junction');

  assert.equal(updated[0].name, 'Point 1');
  assert.equal(updated[1].name, 'Coffee Junction');
  assert.equal(updated[2].name, 'Point 3');
  // Original array is untouched (immutable update).
  assert.equal(draftPoints[1].name, 'Point 2');
  // Untouched items are the exact same object reference (cheap to verify
  // nothing else about them changed).
  assert.equal(updated[0], draftPoints[0]);
  assert.equal(updated[2], draftPoints[2]);
});

console.log(`\n${passed} test(s) passed.`);
if (process.exitCode) {
  console.error('One or more tests FAILED.');
} else {
  console.log('All tests passed.');
}
