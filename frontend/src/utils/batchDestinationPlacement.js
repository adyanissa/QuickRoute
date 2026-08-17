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
//
// `autoPlacedItemIds` is the one exception, and it is not a silent one:
// those items have a location suggested by the map's OWN printed labels,
// already checked against the wall mask and line of sight by the server
// (see backend/services/destination_auto_placement_service.py). They
// start 'placed' so the admin only has to visit the ones the drawing
// could not answer for — but they stay in the queue, keep their marker,
// and can be moved or rejected exactly like any other item.
export function initialBatchStatuses(queueItemIds, autoPlacedItemIds) {
  const autoPlaced = new Set(autoPlacedItemIds || []);
  const statuses = {};
  (queueItemIds || []).forEach((id) => {
    statuses[id] = autoPlaced.has(id) ? 'placed' : 'pending';
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

// ---------------------------------------------------------------------
// Seeding the queue from the server's automatic-placement preview
// (POST .../destinations/auto-place/preview).
//
// The server suggests a location for a room by matching its name to a
// label PRINTED on the map and checking positions near that label against
// the wall mask and line of sight. It is NOT door detection and it invents
// nothing: anything it cannot prove comes back with a status other than
// 'auto_connectable' and stays a manual click.
//
// Nothing here changes what gets SENT: a seeded item is still
// placement_source 'needs_manual_placement' as far as the payload builder
// is concerned, so it is still only included once x/y are actually set —
// there is no path by which an unplaced item slips into a save.
// ---------------------------------------------------------------------

// itemId -> suggestion, for the auto-placed items only. A proposal
// missing a usable coordinate is ignored no matter what status it claims.
export function indexAutoPlacementSuggestions(autoPlacementProposals) {
  const byItemId = {};

  (autoPlacementProposals || []).forEach((proposal) => {
    if (!proposal || proposal.status !== 'auto_connectable') return;

    const point = proposal.suggested_arrival_point || proposal.suggested_room_point;
    if (!Array.isArray(point) || point.length < 2) return;

    const [x, y] = point;
    if (typeof x !== 'number' || typeof y !== 'number') return;

    byItemId[proposal.semantic_item_id] = {
      x,
      y,
      geometryConfidence: proposal.geometry_confidence,
      semanticMatchConfidence: proposal.semantic_match_confidence,
      matchedLabel: proposal.diagnostics ? proposal.diagnostics.matched_label : null,
      matchedGraphElement: proposal.matched_graph_element || null,
      diagnostics: proposal.diagnostics || null,
    };
  });

  return byItemId;
}

// Copies each suggestion onto its proposal as x/y plus an `autoPlacement`
// record the UI uses for the badge and the "why here?" detail. Never
// overwrites a coordinate the admin (or an existing linked point) already
// supplied, and never touches a rejected/excluded proposal.
export function applyAutoPlacementSuggestions(proposals, suggestionsByItemId) {
  const suggestions = suggestionsByItemId || {};

  return (proposals || []).map((proposal) => {
    if (!proposal) return proposal;
    if (proposal.localStatus === 'rejected' || proposal.localStatus === 'excluded') {
      return proposal;
    }
    if (proposal.placement_source !== 'needs_manual_placement') return proposal;
    if (proposal.x != null || proposal.y != null) return proposal;

    const suggestion = suggestions[proposal.semantic_item_id];
    if (!suggestion) return proposal;

    return {
      ...proposal,
      x: suggestion.x,
      y: suggestion.y,
      autoPlaced: true,
      autoPlacement: suggestion,
    };
  });
}

// The rooms the drawing could NOT answer for, in the order the server
// reported them, each with the reason — this is the "still needs one
// click" list the admin actually works through. Items already carrying a
// location are not in it: there is nothing to do for those.
export function buildAutoPlacementReviewList(autoPlacementProposals) {
  return (autoPlacementProposals || [])
    .filter(
      (proposal) =>
        proposal &&
        proposal.status !== 'auto_connectable' &&
        proposal.status !== undefined &&
        !(proposal.message || '').includes('already has a map location'),
    )
    .map((proposal) => ({
      semanticItemId: proposal.semantic_item_id,
      name: proposal.room_name || proposal.semantic_item_id,
      status: proposal.status,
      message: proposal.message || null,
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
