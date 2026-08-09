// Pure helpers for the "fast batch destination placement" workflow
// (AdminMapScreen.jsx "Place All Destinations" — Create Destinations from
// Approved Analysis, batch mode). Kept dependency-free, exactly like
// destinationPlacement.js, so the queue/progress/readiness logic can be
// unit-tested without a DOM/React harness — see
// batchDestinationPlacement.test.mjs.
//
// Terminology: every item in the queue is one semantic_item_id awaiting a
// manually-clicked map location. Its status is exactly one of:
//   'pending'  — not yet placed, not yet visited by Skip.
//   'skipped'  — admin chose "Skip for now"; revisited after every other
//                pending item, never silently dropped.
//   'placed'   — admin clicked a map location for it (or it already had
//                one from an existing linked point).
//   'rejected' — admin explicitly excluded it; never sent to Save All.
// 'placed' and 'rejected' are the only two TERMINAL statuses — a batch is
// ready to save only once every item is one of those two (Section 5/6:
// "Final save remains disabled while accepted destinations are missing
// locations").

// Builds the ordered queue of semantic_item_ids that need a manually
// clicked location — i.e. every proposal whose placement_source is
// "needs_manual_placement" (Section 8: an item with an existing linked
// point is auto-included elsewhere and never enters this queue at all;
// picking a NEW location for one of those is only ever an explicit
// "Change location" action, never automatic). Preserves the proposals'
// own array order — never re-sorts, so "Destination 1 of N" is stable and
// predictable across a page reload/resume.
export function buildBatchQueueItemIds(proposals) {
  return (proposals || [])
    .filter(
      (proposal) =>
        proposal &&
        proposal.placement_source === 'needs_manual_placement' &&
        proposal.localStatus !== 'rejected' &&
        proposal.localStatus !== 'excluded',
    )
    .map((proposal) => proposal.semantic_item_id);
}

// Every queue item starts 'pending' — never pre-placed, never
// pre-rejected (Section 1: "must not require clicking Accept separately
// for every destination", but that is not the same as silently
// pre-accepting a location no admin ever clicked).
export function initialBatchStatuses(queueItemIds) {
  const statuses = {};
  (queueItemIds || []).forEach((id) => {
    statuses[id] = 'pending';
  });
  return statuses;
}

// Finds the next item to make active after the one at `fromIndex` is
// resolved (placed/skipped/rejected/undone) — first pass looks for any
// other still-'pending' item (queue order), second pass revisits
// 'skipped' items (Section 4: "Skip for now must leave the destination
// unresolved and return to it after the other items"). Returns -1 when
// nothing is left to visit (queue fully placed/rejected).
export function findNextActiveIndex(queueItemIds, statuses, fromIndex) {
  const n = (queueItemIds || []).length;
  if (n === 0) return -1;

  for (let offset = 1; offset <= n; offset += 1) {
    const idx = (fromIndex + offset) % n;
    if (statuses[queueItemIds[idx]] === 'pending') return idx;
  }
  for (let offset = 1; offset <= n; offset += 1) {
    const idx = (fromIndex + offset) % n;
    if (statuses[queueItemIds[idx]] === 'skipped') return idx;
  }
  return -1;
}

// Live progress counters (Section 5): remaining counts BOTH 'pending' and
// 'skipped' items, since neither is resolved yet.
export function computeBatchProgress(queueItemIds, statuses) {
  const ids = queueItemIds || [];
  let placed = 0;
  let rejected = 0;
  let skipped = 0;
  let pending = 0;

  ids.forEach((id) => {
    const status = statuses[id];
    if (status === 'placed') placed += 1;
    else if (status === 'rejected') rejected += 1;
    else if (status === 'skipped') skipped += 1;
    else pending += 1;
  });

  return {
    total: ids.length,
    placed,
    rejected,
    skipped,
    remaining: pending + skipped,
  };
}

// Section 6: "Save All Destinations" must stay disabled while any
// accepted destination is still missing a location — true only once
// every queue item is 'placed' or 'rejected' (never while any is
// 'pending'/'skipped'). An empty queue (nothing needed manual placement
// at all) is trivially ready.
export function isBatchReadyToSave(queueItemIds, statuses) {
  return (queueItemIds || []).every((id) => {
    const status = statuses[id];
    return status === 'placed' || status === 'rejected';
  });
}

// The exact accepted-item list to send in the final "Save All
// Destinations" request: every non-rejected proposal that has a usable
// location — both existing-linked-point proposals (auto-included,
// Section 8) and freshly-placed batch-queue proposals. Mirrors the shape
// handleConfirmSemanticDestApply already sends for the single-item flow,
// so the SAME apply endpoint/schema can be reused unchanged.
export function buildBatchAcceptedPayload(proposals) {
  return (proposals || [])
    .filter((proposal) => {
      if (!proposal) return false;
      if (proposal.localStatus === 'rejected' || proposal.localStatus === 'excluded') return false;
      // A needs-manual-placement item must actually have been placed
      // (x/y set) before it can be part of the payload — never invent
      // coordinates, never silently include an unplaced item.
      if (proposal.placement_source === 'needs_manual_placement') {
        return proposal.x != null && proposal.y != null;
      }
      return true;
    })
    .map((proposal) => ({
      semantic_item_id: proposal.semantic_item_id,
      entity_kind: proposal.entity_kind,
      x: proposal.x,
      y: proposal.y,
      parent_semantic_item_id:
        proposal.confirmNested && proposal.nested_parent_candidate
          ? proposal.nested_parent_candidate.semantic_item_id
          : null,
      allow_transit_through: Boolean(proposal.allowTransitThrough),
    }));
}

// localStorage draft key — scoped by map, publication, and admin, exactly
// as required (Section 9), so two different admins (or the same admin on
// two different maps/analyses) never collide or silently resume the
// wrong draft.
export function buildBatchDraftStorageKey({ mapId, publicationId, adminId }) {
  return `quickroute:semanticBatchDraft:${mapId || 'unknown-map'}:${publicationId || 'unknown-publication'}:${adminId || 'unknown-admin'}`;
}

// Serializes only what's needed to resume — never the full proposal
// objects (those are re-fetched fresh from the server on resume so
// approved names/categories/etc. can't go stale in a long-lived draft).
export function serializeBatchDraft({ queueItemIds, statuses, placements }) {
  return JSON.stringify({
    version: 1,
    savedAt: new Date().toISOString(),
    queueItemIds: queueItemIds || [],
    statuses: statuses || {},
    // itemId -> { x, y } for every item that has ever been placed/changed
    // in this session — kept separate from `statuses` so a 'rejected'
    // item's last-known coordinates (if any) are never lost by Undo.
    placements: placements || {},
  });
}

export function deserializeBatchDraft(rawText) {
  if (!rawText) return null;
  try {
    const parsed = JSON.parse(rawText);
    if (!parsed || typeof parsed !== 'object') return null;
    if (!Array.isArray(parsed.queueItemIds)) return null;
    return parsed;
  } catch {
    // A corrupted/foreign localStorage value must never crash the admin
    // screen — treat exactly like "no draft found".
    return null;
  }
}
