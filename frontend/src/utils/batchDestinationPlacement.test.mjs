// Plain-Node tests for the fast batch destination placement helpers
// (frontend/src/utils/batchDestinationPlacement.js). Same pattern as the
// repo's other *.test.mjs files — no jest/vitest installed, run directly
// via `node batchDestinationPlacement.test.mjs`.
import assert from 'node:assert/strict';
import {
  buildBatchQueueItemIds,
  initialBatchStatuses,
  findNextActiveIndex,
  computeBatchProgress,
  isBatchReadyToSave,
  buildBatchAcceptedPayload,
  buildBatchDraftStorageKey,
  serializeBatchDraft,
  deserializeBatchDraft,
} from './batchDestinationPlacement.js';

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

function makeProposal(overrides = {}) {
  return {
    semantic_item_id: 'p1',
    entity_kind: 'place',
    placement_source: 'needs_manual_placement',
    localStatus: 'pending',
    x: null,
    y: null,
    name_en: 'Office 263',
    ...overrides,
  };
}

// ── buildBatchQueueItemIds ───────────────────────────────────────────────
// (spec test 1: "Starting batch mode selects the first unresolved
// destination" — this is the queue the batch panel walks in order.)

test('buildBatchQueueItemIds: includes only needs_manual_placement, non-rejected/excluded proposals, in array order', () => {
  const proposals = [
    makeProposal({ semantic_item_id: 'p1' }),
    makeProposal({ semantic_item_id: 'p2', placement_source: 'existing_route_point' }),
    makeProposal({ semantic_item_id: 'p3', localStatus: 'rejected' }),
    makeProposal({ semantic_item_id: 'p4', localStatus: 'excluded' }),
    makeProposal({ semantic_item_id: 'p5' }),
  ];

  assert.deepEqual(buildBatchQueueItemIds(proposals), ['p1', 'p5']);
});

test('buildBatchQueueItemIds: empty/undefined input never throws, returns []', () => {
  assert.deepEqual(buildBatchQueueItemIds([]), []);
  assert.deepEqual(buildBatchQueueItemIds(undefined), []);
});

test('initialBatchStatuses: every queue item starts pending — never pre-placed/pre-rejected', () => {
  assert.deepEqual(initialBatchStatuses(['p1', 'p2']), { p1: 'pending', p2: 'pending' });
});

// ── findNextActiveIndex (spec test 3: auto-advance; test 9: Skip returns
//    the item later) ────────────────────────────────────────────────────

test('findNextActiveIndex: starting fresh (fromIndex -1) returns the first pending item', () => {
  const queue = ['p1', 'p2', 'p3'];
  const statuses = initialBatchStatuses(queue);
  assert.equal(findNextActiveIndex(queue, statuses, -1), 0);
});

test('findNextActiveIndex: advances to the next pending item after the current one is placed', () => {
  const queue = ['p1', 'p2', 'p3'];
  const statuses = { p1: 'placed', p2: 'pending', p3: 'pending' };
  assert.equal(findNextActiveIndex(queue, statuses, 0), 1);
});

test('findNextActiveIndex: a skipped item is revisited only after every other pending item is resolved', () => {
  const queue = ['p1', 'p2', 'p3'];
  // p1 skipped, p2 still pending, p3 already placed — from p1's own index,
  // the next stop must be p2 (still pending), NOT p1 again yet.
  const statuses = { p1: 'skipped', p2: 'pending', p3: 'placed' };
  assert.equal(findNextActiveIndex(queue, statuses, 0), 1);

  // Once nothing is 'pending' anymore, the skipped item IS revisited.
  const statusesAfterP2 = { p1: 'skipped', p2: 'placed', p3: 'placed' };
  assert.equal(findNextActiveIndex(queue, statusesAfterP2, 1), 0);
});

test('findNextActiveIndex: returns -1 once every item is placed or rejected (queue fully resolved)', () => {
  const queue = ['p1', 'p2'];
  const statuses = { p1: 'placed', p2: 'rejected' };
  assert.equal(findNextActiveIndex(queue, statuses, 0), -1);
});

test('findNextActiveIndex: an empty queue returns -1 immediately', () => {
  assert.equal(findNextActiveIndex([], {}, -1), -1);
});

// ── computeBatchProgress (spec test 11: progress counters) ─────────────

test('computeBatchProgress: counts placed/rejected/skipped correctly, remaining = pending + skipped', () => {
  const queue = ['p1', 'p2', 'p3', 'p4', 'p5'];
  const statuses = {
    p1: 'placed',
    p2: 'placed',
    p3: 'rejected',
    p4: 'skipped',
    p5: 'pending',
  };

  const progress = computeBatchProgress(queue, statuses);
  assert.deepEqual(progress, {
    total: 5,
    placed: 2,
    rejected: 1,
    skipped: 1,
    remaining: 2, // 1 skipped + 1 pending
  });
});

test('computeBatchProgress: an empty queue is all zeros', () => {
  assert.deepEqual(computeBatchProgress([], {}), {
    total: 0,
    placed: 0,
    rejected: 0,
    skipped: 0,
    remaining: 0,
  });
});

// ── isBatchReadyToSave (spec test 12: Final save disabled while missing
//    locations) ──────────────────────────────────────────────────────────

test('isBatchReadyToSave: false while any item is still pending or skipped', () => {
  assert.equal(
    isBatchReadyToSave(['p1', 'p2'], { p1: 'placed', p2: 'pending' }),
    false,
  );
  assert.equal(
    isBatchReadyToSave(['p1', 'p2'], { p1: 'placed', p2: 'skipped' }),
    false,
  );
});

test('isBatchReadyToSave: true once every item is placed or rejected', () => {
  assert.equal(
    isBatchReadyToSave(['p1', 'p2'], { p1: 'placed', p2: 'rejected' }),
    true,
  );
});

test('isBatchReadyToSave: an empty queue (nothing needed manual placement) is trivially ready', () => {
  assert.equal(isBatchReadyToSave([], {}), true);
});

// ── buildBatchAcceptedPayload (spec test 10: Reject excludes the item
//    from final save) ───────────────────────────────────────────────────

test('buildBatchAcceptedPayload: excludes rejected/excluded proposals entirely', () => {
  const proposals = [
    makeProposal({ semantic_item_id: 'p1', localStatus: 'accepted', x: 10, y: 20 }),
    makeProposal({ semantic_item_id: 'p2', localStatus: 'rejected' }),
    makeProposal({ semantic_item_id: 'p3', localStatus: 'excluded' }),
  ];

  const payload = buildBatchAcceptedPayload(proposals);
  assert.deepEqual(payload.map((p) => p.semantic_item_id), ['p1']);
});

test('buildBatchAcceptedPayload: a needs-manual-placement item without x/y is never included (never invents coordinates)', () => {
  const proposals = [
    makeProposal({ semantic_item_id: 'p1', localStatus: 'accepted', x: null, y: null }),
  ];
  assert.deepEqual(buildBatchAcceptedPayload(proposals), []);
});

test('buildBatchAcceptedPayload: an existing-linked-point proposal is included even without a NEW x/y click', () => {
  const proposals = [
    makeProposal({
      semantic_item_id: 'p1',
      placement_source: 'existing_route_point',
      localStatus: 'accepted',
      x: 5,
      y: 5,
    }),
  ];
  assert.equal(buildBatchAcceptedPayload(proposals).length, 1);
});

test('buildBatchAcceptedPayload: carries entity_kind/x/y/nested/allow_transit exactly like the single-item apply payload', () => {
  const proposals = [
    makeProposal({
      semantic_item_id: 'p1',
      localStatus: 'accepted',
      x: 42,
      y: 84,
      entity_kind: 'facility',
      confirmNested: true,
      nested_parent_candidate: { semantic_item_id: 'parent-1' },
      allowTransitThrough: true,
    }),
  ];

  assert.deepEqual(buildBatchAcceptedPayload(proposals), [
    {
      semantic_item_id: 'p1',
      entity_kind: 'facility',
      x: 42,
      y: 84,
      parent_semantic_item_id: 'parent-1',
      allow_transit_through: true,
    },
  ]);
});

// ── Draft recovery (spec tests 14/15) ───────────────────────────────────

test('buildBatchDraftStorageKey: scoped by map, publication, and admin', () => {
  const key = buildBatchDraftStorageKey({ mapId: 'map-1', publicationId: 'pub-1', adminId: 'admin-1' });
  assert.match(key, /map-1/);
  assert.match(key, /pub-1/);
  assert.match(key, /admin-1/);

  const otherAdminKey = buildBatchDraftStorageKey({ mapId: 'map-1', publicationId: 'pub-1', adminId: 'admin-2' });
  assert.notEqual(key, otherAdminKey);
});

test('serializeBatchDraft / deserializeBatchDraft: round-trips queue, statuses, and placements', () => {
  const draft = {
    queueItemIds: ['p1', 'p2'],
    statuses: { p1: 'placed', p2: 'pending' },
    placements: { p1: { x: 10, y: 20 } },
  };

  const raw = serializeBatchDraft(draft);
  const restored = deserializeBatchDraft(raw);

  assert.deepEqual(restored.queueItemIds, draft.queueItemIds);
  assert.deepEqual(restored.statuses, draft.statuses);
  assert.deepEqual(restored.placements, draft.placements);
});

test('deserializeBatchDraft: a missing/corrupted value is treated as "no draft found", never crashes', () => {
  assert.equal(deserializeBatchDraft(null), null);
  assert.equal(deserializeBatchDraft(''), null);
  assert.equal(deserializeBatchDraft('{not valid json'), null);
  assert.equal(deserializeBatchDraft('"just a string"'), null);
});

console.log(`\n${passed} passed`);
