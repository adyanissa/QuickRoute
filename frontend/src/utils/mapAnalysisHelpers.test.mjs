// Plain-Node tests for the REAL semantic-map-analysis pure helpers
// (frontend/src/utils/mapAnalysisHelpers.js). No jest/vitest installed in
// this repo — run directly via `node mapAnalysisHelpers.test.mjs`, same
// convention as every other *.test.mjs file here.
//
// This file REPLACES the old test suite for the speculative "detections/
// apply" contract (deleted along with that contract) — see
// mapAnalysisApi.js's header comment for why.
import assert from 'node:assert/strict';
import {
  statusBucket,
  canRetry,
  canReview,
  isTerminal,
  normalizeAnalysisSummary,
  normalizeAnalysisDetail,
  normalizeAnalysisResult,
  normalizePublishedEntity,
  publishedEntityLabel,
  flattenReviewableEntities,
  countByReviewStatus,
  unresolvedBlockingReviewItems,
  isReadyToPublish,
  idsForAcceptAllHighConfidence,
  setEntityReviewStatus,
  correctEntity,
  resolveReviewItem,
  buildMockAnalysisResult,
} from './mapAnalysisHelpers.js';

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

// ── status helpers ───────────────────────────────────────────────────────

test('statusBucket: completed -> success', () => {
  assert.equal(statusBucket('completed'), 'success');
});

test('statusBucket: queued/processing -> in_progress', () => {
  assert.equal(statusBucket('queued'), 'in_progress');
  assert.equal(statusBucket('processing'), 'in_progress');
});

test('statusBucket: configuration_required -> configuration', () => {
  assert.equal(statusBucket('configuration_required'), 'configuration');
});

test('statusBucket: failed/invalid_output -> error', () => {
  assert.equal(statusBucket('failed'), 'error');
  assert.equal(statusBucket('invalid_output'), 'error');
});

test('canRetry: true only for failed/invalid_output/configuration_required', () => {
  assert.equal(canRetry('failed'), true);
  assert.equal(canRetry('invalid_output'), true);
  assert.equal(canRetry('configuration_required'), true);
  assert.equal(canRetry('completed'), false);
  assert.equal(canRetry('queued'), false);
});

test('canReview: true only for completed', () => {
  assert.equal(canReview('completed'), true);
  assert.equal(canReview('processing'), false);
});

test('isTerminal: queued/processing are not terminal', () => {
  assert.equal(isTerminal('queued'), false);
  assert.equal(isTerminal('processing'), false);
  assert.equal(isTerminal('completed'), true);
  assert.equal(isTerminal('cancelled'), true);
});

// ── normalizers ───────────────────────────────────────────────────────────

test('normalizeAnalysisSummary: maps every snake_case field to camelCase', () => {
  const result = normalizeAnalysisSummary({
    analysis_id: 'a1',
    scope_type: 'map',
    map_id: 'm1',
    status: 'completed',
    progress: 100,
    attempt_count: 2,
    prompt_version: 'v2',
    prompt_sha256: 'abc',
    model: 'gpt-5',
    review_status: 'in_progress',
    review_revision: 3,
    error_code: null,
    error_message: null,
  });
  assert.equal(result.analysisId, 'a1');
  assert.equal(result.mapId, 'm1');
  assert.equal(result.status, 'completed');
  assert.equal(result.progress, 100);
  assert.equal(result.attemptCount, 2);
  assert.equal(result.promptVersion, 'v2');
  assert.equal(result.promptSha256, 'abc');
  assert.equal(result.reviewRevision, 3);
});

test('normalizeAnalysisSummary: null input returns null (never throws)', () => {
  assert.equal(normalizeAnalysisSummary(null), null);
  assert.equal(normalizeAnalysisSummary(undefined), null);
});

test('normalizeAnalysisDetail: includes local_validation', () => {
  const result = normalizeAnalysisDetail({
    analysis_id: 'a1',
    status: 'invalid_output',
    local_validation: { valid: false, errors: ['bad'], warnings: [] },
  });
  assert.deepEqual(result.localValidation, { valid: false, errors: ['bad'], warnings: [] });
});

test('normalizeAnalysisResult: never exposes ai_result under a snake_case key', () => {
  const result = normalizeAnalysisResult({
    analysis_id: 'a1',
    status: 'completed',
    ai_result: { schema_version: 'quickroute_semantic_map_import_v2' },
    reviewed_result: null,
  });
  assert.ok(result.aiResult);
  assert.equal(result.ai_result, undefined);
  assert.equal(result.reviewedResult, null);
});

test('normalizePublishedEntity + publishedEntityLabel prefers requested language', () => {
  const entity = normalizePublishedEntity({
    entity_external_id: 'place_001',
    entity_type: 'place',
    names: { original: 'صيدلية', en: 'Pharmacy', ar: 'صيدلية', he: null },
    category: 'pharmacy',
  });
  assert.equal(publishedEntityLabel(entity, 'en'), 'Pharmacy');
  assert.equal(publishedEntityLabel(entity, 'ar'), 'صيدلية');
  // Falls back to English, then original, then category when the
  // requested language has no translation.
  assert.equal(publishedEntityLabel(entity, 'he'), 'Pharmacy');
});

test('publishedEntityLabel: never returns blank for a category-only entity', () => {
  const entity = normalizePublishedEntity({
    entity_external_id: 'facility_001',
    names: {},
    category: 'toilet',
  });
  assert.equal(publishedEntityLabel(entity), 'toilet');
});

// ── reviewed-result fixtures ─────────────────────────────────────────────

function fixtureReviewedResult() {
  return {
    schema_version: 'quickroute_semantic_map_import_v2',
    places: [
      {
        place_external_id: 'place_001',
        names: { original: 'Pharmacy' },
        confidence: 0.95,
        review: { status: 'pending', notes: null },
      },
      {
        place_external_id: 'place_002',
        names: { original: 'Office' },
        confidence: 0.5,
        review: { status: 'accepted', notes: null },
      },
    ],
    facilities: [
      {
        facility_external_id: 'facility_001',
        confidence: 0.9,
        review: { status: 'pending', notes: null },
      },
    ],
    access_points: [],
    public_areas: [],
    vertical_connections: [],
    outdoor_areas: [],
    parking_areas: [],
    parking_spaces: [],
    review_items: [
      {
        review_item_external_id: 'review_001',
        blocks_publication: true,
        review: { status: 'pending' },
      },
      {
        review_item_external_id: 'review_002',
        blocks_publication: false,
        review: { status: 'pending' },
      },
    ],
  };
}

// ── flatten / count ───────────────────────────────────────────────────────

test('flattenReviewableEntities: flattens every entity array with its type tag', () => {
  const flat = flattenReviewableEntities(fixtureReviewedResult());
  assert.equal(flat.length, 3); // 2 places + 1 facility
  assert.ok(flat.some((entry) => entry.entityType === 'facilities'));
});

test('flattenReviewableEntities: empty/null input never throws', () => {
  assert.deepEqual(flattenReviewableEntities(null), []);
  assert.deepEqual(flattenReviewableEntities({}), []);
});

test('countByReviewStatus: counts pending/accepted/corrected/rejected correctly', () => {
  const counts = countByReviewStatus(fixtureReviewedResult());
  assert.equal(counts.pending, 2); // place_001 + facility_001
  assert.equal(counts.accepted, 1); // place_002
  assert.equal(counts.corrected, 0);
  assert.equal(counts.rejected, 0);
});

test('unresolvedBlockingReviewItems: only returns blocking + still-pending items', () => {
  const blocking = unresolvedBlockingReviewItems(fixtureReviewedResult());
  assert.equal(blocking.length, 1);
  assert.equal(blocking[0].review_item_external_id, 'review_001');
});

test('isReadyToPublish: false while any entity is pending', () => {
  assert.equal(isReadyToPublish(fixtureReviewedResult()), false);
});

test('isReadyToPublish: false while a blocking review item is unresolved even with zero pending entities', () => {
  let reviewed = fixtureReviewedResult();
  reviewed = setEntityReviewStatus(reviewed, 'places', 'place_001', 'accepted');
  reviewed = setEntityReviewStatus(reviewed, 'facilities', 'facility_001', 'rejected');
  // Still has the unresolved blocking review_001.
  assert.equal(isReadyToPublish(reviewed), false);
});

test('isReadyToPublish: true once every entity is decided and blocking items resolved', () => {
  let reviewed = fixtureReviewedResult();
  reviewed = setEntityReviewStatus(reviewed, 'places', 'place_001', 'accepted');
  reviewed = setEntityReviewStatus(reviewed, 'facilities', 'facility_001', 'rejected');
  reviewed = resolveReviewItem(reviewed, 'review_001', { status: 'accepted' });
  assert.equal(isReadyToPublish(reviewed), true);
});

test('idsForAcceptAllHighConfidence: only pending entities at/above the threshold', () => {
  const ids = idsForAcceptAllHighConfidence(fixtureReviewedResult(), 0.85);
  // place_001 (0.95, pending) and facility_001 (0.9, pending) qualify;
  // place_002 (0.5) is below threshold; nothing already-decided is
  // re-included even if it happened to be high confidence.
  assert.equal(ids.length, 2);
  assert.ok(ids.some((entry) => entry.externalId === 'place_001'));
  assert.ok(ids.some((entry) => entry.externalId === 'facility_001'));
});

// ── mutation helpers (must never mutate the input) ───────────────────────

test('setEntityReviewStatus: returns a new object, never mutates the input', () => {
  const original = fixtureReviewedResult();
  const originalJson = JSON.stringify(original);
  const updated = setEntityReviewStatus(original, 'places', 'place_001', 'rejected', 'no');

  assert.equal(JSON.stringify(original), originalJson, 'input must be unchanged');
  assert.equal(updated.places[0].review.status, 'rejected');
  assert.equal(updated.places[0].review.notes, 'no');
  // Untouched entity stays untouched.
  assert.equal(updated.places[1].review.status, 'accepted');
});

test('setEntityReviewStatus: unknown external id returns the original object unchanged', () => {
  const original = fixtureReviewedResult();
  const result = setEntityReviewStatus(original, 'places', 'does-not-exist', 'accepted');
  assert.equal(result, original);
});

test('correctEntity: patches fields AND sets review.status to "corrected"', () => {
  const original = fixtureReviewedResult();
  const updated = correctEntity(
    original,
    'places',
    'place_001',
    { names: { original: 'Corrected Pharmacy' } },
    'fixed typo',
  );
  assert.equal(updated.places[0].names.original, 'Corrected Pharmacy');
  assert.equal(updated.places[0].review.status, 'corrected');
  assert.equal(updated.places[0].review.notes, 'fixed typo');
  // Original object still unchanged.
  assert.equal(original.places[0].review.status, 'pending');
});

test('resolveReviewItem: sets status/selected_resolution/corrected_value/notes', () => {
  const original = fixtureReviewedResult();
  const updated = resolveReviewItem(original, 'review_001', {
    status: 'accepted',
    selectedResolution: 'Pharmacy',
    correctedValue: null,
    notes: 'confirmed on second image',
  });
  const item = updated.review_items.find(
    (entry) => entry.review_item_external_id === 'review_001',
  );
  assert.equal(item.review.status, 'accepted');
  assert.equal(item.review.selected_resolution, 'Pharmacy');
  assert.equal(item.review.notes, 'confirmed on second image');
  // The other review item is untouched.
  const other = updated.review_items.find(
    (entry) => entry.review_item_external_id === 'review_002',
  );
  assert.equal(other.review.status, 'pending');
});

// ── mock data ─────────────────────────────────────────────────────────────

test('buildMockAnalysisResult: is clearly labeled and structurally matches the real schema', () => {
  const mock = buildMockAnalysisResult('map-123');
  assert.equal(mock.schema_version, 'quickroute_semantic_map_import_v2');
  assert.ok(mock.places[0].names.original.includes('[MOCK]'));
  assert.equal(mock.validation.ready_for_publish, false);
  assert.equal(mock.validation.contains_routing_coordinates, false);
  // Never contains a routing/pixel field.
  assert.equal(mock.places[0].x, undefined);
  assert.equal(mock.places[0].y, undefined);
});

console.log(`\n${passed} test(s) passed.`);
