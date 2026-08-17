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
  indexAutoPlacementSuggestions,
  applyAutoPlacementSuggestions,
  buildAutoPlacementReviewList,
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

// ── Seeding the queue from the server's automatic-placement preview ─────
// The server suggests a position from the map's own printed labels. These
// tests are mostly about what must NOT happen: no unproven suggestion may
// become a coordinate, and no admin-supplied coordinate may be overwritten.

function autoPlaced(id, x, y, overrides = {}) {
  return {
    semantic_item_id: id,
    status: 'auto_connectable',
    suggested_room_point: [x, y],
    suggested_arrival_point: [x, y],
    geometry_confidence: 0.9,
    semantic_match_confidence: 1.0,
    diagnostics: { matched_label: 'OFFICE 263' },
    matched_graph_element: { route_point_id: 'c1', name: 'Corridor A' },
    ...overrides,
  };
}

test('indexAutoPlacementSuggestions: only auto_connectable proposals with a real coordinate are usable', () => {
  const index = indexAutoPlacementSuggestions([
    autoPlaced('p1', 120, 240),
    { semantic_item_id: 'p2', status: 'needs_arrival_confirmation', suggested_room_point: null },
    { semantic_item_id: 'p3', status: 'ambiguous_label' },
    { semantic_item_id: 'p4', status: 'no_label_match' },
    // Claims success but carries nothing usable — must still be ignored.
    { semantic_item_id: 'p5', status: 'auto_connectable', suggested_room_point: [null, 3] },
  ]);

  assert.deepEqual(Object.keys(index), ['p1']);
  assert.equal(index.p1.x, 120);
  assert.equal(index.p1.y, 240);
  assert.equal(index.p1.matchedLabel, 'OFFICE 263');
});

test('applyAutoPlacementSuggestions: seeds x/y and marks the proposal as auto placed', () => {
  const [seeded] = applyAutoPlacementSuggestions(
    [makeProposal({ semantic_item_id: 'p1' })],
    indexAutoPlacementSuggestions([autoPlaced('p1', 120, 240)]),
  );

  assert.equal(seeded.x, 120);
  assert.equal(seeded.y, 240);
  assert.equal(seeded.autoPlaced, true);
  assert.equal(seeded.autoPlacement.geometryConfidence, 0.9);
  // placement_source is untouched, so the payload builder still refuses
  // to include it unless x/y are genuinely set.
  assert.equal(seeded.placement_source, 'needs_manual_placement');
});

test('applyAutoPlacementSuggestions: never overwrites a location the admin already set', () => {
  const [kept] = applyAutoPlacementSuggestions(
    [makeProposal({ semantic_item_id: 'p1', x: 10, y: 20 })],
    indexAutoPlacementSuggestions([autoPlaced('p1', 999, 999)]),
  );

  assert.equal(kept.x, 10);
  assert.equal(kept.y, 20);
  assert.equal(kept.autoPlaced, undefined);
});

test('applyAutoPlacementSuggestions: leaves rejected, excluded and already-linked proposals alone', () => {
  const suggestions = indexAutoPlacementSuggestions([
    autoPlaced('p1', 1, 1),
    autoPlaced('p2', 2, 2),
    autoPlaced('p3', 3, 3),
  ]);

  const result = applyAutoPlacementSuggestions(
    [
      makeProposal({ semantic_item_id: 'p1', localStatus: 'rejected' }),
      makeProposal({ semantic_item_id: 'p2', localStatus: 'excluded' }),
      makeProposal({ semantic_item_id: 'p3', placement_source: 'existing_route_point' }),
    ],
    suggestions,
  );

  result.forEach((proposal) => {
    assert.equal(proposal.x, null);
    assert.equal(proposal.autoPlaced, undefined);
  });
});

test('an auto placed item starts "placed" and a manual one still starts "pending"', () => {
  const statuses = initialBatchStatuses(['p1', 'p2'], ['p1']);

  assert.equal(statuses.p1, 'placed');
  assert.equal(statuses.p2, 'pending');
  // The old single-argument call must keep behaving exactly as before.
  assert.deepEqual(initialBatchStatuses(['p1', 'p2']), { p1: 'pending', p2: 'pending' });
});

test('seeding most of a batch leaves exactly the unproven rooms to click', () => {
  const proposals = [
    makeProposal({ semantic_item_id: 'p1' }),
    makeProposal({ semantic_item_id: 'p2' }),
    makeProposal({ semantic_item_id: 'p3' }),
  ];
  const autoPlacement = [
    autoPlaced('p1', 10, 10),
    autoPlaced('p2', 20, 20),
    { semantic_item_id: 'p3', status: 'ambiguous_label', message: 'Two labels match.' },
  ];

  const seeded = applyAutoPlacementSuggestions(
    proposals,
    indexAutoPlacementSuggestions(autoPlacement),
  );
  const queue = buildBatchQueueItemIds(seeded);
  const statuses = initialBatchStatuses(
    queue,
    Object.keys(indexAutoPlacementSuggestions(autoPlacement)),
  );

  assert.deepEqual(queue, ['p1', 'p2', 'p3']);
  assert.equal(computeBatchProgress(queue, statuses).remaining, 1);
  assert.equal(isBatchReadyToSave(queue, statuses), false);

  // Only the seeded pair may be sent; the ambiguous one has no coordinate.
  const payload = buildBatchAcceptedPayload(seeded);
  assert.deepEqual(
    payload.map((item) => item.semantic_item_id),
    ['p1', 'p2'],
  );
});

test('buildAutoPlacementReviewList: names the rooms still needing a click, with the reason', () => {
  const list = buildAutoPlacementReviewList([
    autoPlaced('p1', 10, 10),
    {
      semantic_item_id: 'p2',
      status: 'no_safe_graph_connection',
      room_name: 'Storage 12',
      message: 'No clear line to a corridor point.',
    },
    {
      semantic_item_id: 'p3',
      status: 'needs_arrival_confirmation',
      room_name: 'Lobby',
      message: 'This destination already has a map location — it was left exactly as it is.',
    },
  ]);

  assert.deepEqual(list, [
    {
      semanticItemId: 'p2',
      name: 'Storage 12',
      status: 'no_safe_graph_connection',
      message: 'No clear line to a corridor point.',
    },
  ]);
});

console.log(`\n${passed} passed`);
