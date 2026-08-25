// Pure helpers for the REAL automatic semantic-map-analysis backend
// (replaces the old speculative "detections/apply" contract that used to
// live in this file — that contract generated x/y coordinates directly,
// which conflicted with the final architecture: AI semantic analysis must
// NEVER produce routing coordinates or graph data; only an admin, using
// QuickRoute's existing Map Management tools, ever places a RoutePoint).
//
// Kept framework- and fetch-free — same convention as the rest of this
// repo's utils/*.js — so every normalizer/mutator here is directly
// unit-testable with `node mapAnalysisHelpers.test.mjs`.

import { getLocalizedText } from './localization.js';
//
// Three completely separate document shapes flow through this module,
// matching the backend's own layer separation:
//   - a "summary" (list/status-card view — no ai_result/reviewed_result)
//   - a "detail" (summary + local_validation)
//   - a "result" (ai_result + reviewed_result + local_validation, only
//     ever fetched by the Review screen for an authorised admin)

// ── Status ──────────────────────────────────────────────────────────────

export const ANALYSIS_STATUSES = [
  'queued',
  'processing',
  'completed',
  'invalid_output',
  'failed',
  'configuration_required',
  'superseded',
  'cancelled',
];

// UI bucket for the status card — never a raw backend string shown
// directly to an admin without going through a translation key.
export function statusBucket(status) {
  if (status === 'completed') return 'success';
  if (status === 'queued' || status === 'processing') return 'in_progress';
  if (status === 'configuration_required') return 'configuration';
  if (status === 'failed' || status === 'invalid_output') return 'error';
  if (status === 'cancelled' || status === 'superseded') return 'inactive';
  return 'unknown';
}

export function canRetry(status) {
  return ['failed', 'invalid_output', 'configuration_required'].includes(status);
}

export function canReview(status) {
  return status === 'completed';
}

export function isTerminal(status) {
  return ['completed', 'failed', 'invalid_output', 'cancelled', 'superseded'].includes(
    status,
  );
}

// ── Normalizers (backend snake_case -> frontend camelCase) ─────────────

export function normalizeAnalysisSummary(raw) {
  if (!raw) return null;

  return {
    analysisId: raw.analysis_id ?? null,
    scopeType: raw.scope_type ?? 'map',
    mapId: raw.map_id ?? null,
    mapGroupId: raw.map_group_id ?? null,
    buildingId: raw.building_id ?? null,
    status: raw.status || 'unknown',
    progress: Number.isFinite(Number(raw.progress)) ? Number(raw.progress) : 0,
    attemptCount: Number(raw.attempt_count) || 0,
    promptVersion: raw.prompt_version ?? null,
    promptSha256: raw.prompt_sha256 ?? null,
    model: raw.model ?? null,
    reviewStatus: raw.review_status ?? 'pending',
    reviewRevision: Number(raw.review_revision) || 0,
    errorCode: raw.error_code ?? null,
    errorMessage: raw.error_message ?? null,
    createdAt: raw.created_at ?? null,
    startedAt: raw.started_at ?? null,
    completedAt: raw.completed_at ?? null,
    updatedAt: raw.updated_at ?? null,
    publishedAnalysisId: raw.published_analysis_id ?? null,
    publishedAt: raw.published_at ?? null,
  };
}

export function normalizeAnalysisDetail(raw) {
  const summary = normalizeAnalysisSummary(raw);
  if (!summary) return null;
  return {
    ...summary,
    localValidation: raw?.local_validation ?? null,
  };
}

export function normalizeAnalysisResult(raw) {
  if (!raw) return null;
  return {
    analysisId: raw.analysis_id ?? null,
    status: raw.status ?? 'unknown',
    promptVersion: raw.prompt_version ?? null,
    promptSha256: raw.prompt_sha256 ?? null,
    reviewRevision: Number(raw.review_revision) || 0,
    aiResult: raw.ai_result ?? null,
    reviewedResult: raw.reviewed_result ?? null,
    localValidation: raw.local_validation ?? null,
  };
}

export function normalizePublishedEntity(raw) {
  if (!raw) return null;
  return {
    entityExternalId: raw.entity_external_id ?? null,
    entityType: raw.entity_type ?? null,
    mapId: raw.map_id ?? null,
    floorExternalId: raw.floor_external_id ?? null,
    names: {
      original: raw.names?.original ?? null,
      en: raw.names?.en ?? null,
      ar: raw.names?.ar ?? null,
      he: raw.names?.he ?? null,
    },
    category: raw.category ?? null,
    subcategory: raw.subcategory ?? null,
    displayedNumber: raw.displayed_number ?? null,
    confidence: raw.confidence ?? null,
    publicationId: raw.publication_id ?? null,
  };
}

// Best display label for a published entity in a selector list — prefers
// a real name over a bare category, and a category over a raw external
// id, so the "Choose name from approved map data" list never shows a
// blank row (Section 16).
export function publishedEntityLabel(entity, lang = 'en') {
  if (!entity) return '';
  const names = entity.names || {};
  // Delegates to the single shared fallback chain (Section 8: "never
  // duplicate this fallback logic across screens") instead of this
  // function's own ad-hoc lang -> en -> original -> category -> id chain.
  // `original` (the AI's raw detected text, not a real ar/he/en
  // translation) plus category/entityExternalId are passed as the
  // final legacy `fallback` argument, preserving the exact same
  // "never show a blank row" guarantee this had before.
  return getLocalizedText(
    names,
    lang,
    names.original || entity.category || entity.entityExternalId || '',
  );
}

// ── Reviewed-result entity iteration (works across every entity array) ──

export const REVIEWABLE_ENTITY_ARRAYS = [
  { key: 'places', idField: 'place_external_id', label: 'Places' },
  { key: 'facilities', idField: 'facility_external_id', label: 'Facilities' },
  { key: 'access_points', idField: 'access_external_id', label: 'Access Points' },
  { key: 'public_areas', idField: 'area_external_id', label: 'Public Areas' },
  {
    key: 'vertical_connections',
    idField: 'connection_external_id',
    label: 'Vertical Connections',
  },
  { key: 'outdoor_areas', idField: 'outdoor_external_id', label: 'Outdoor Areas' },
  { key: 'parking_areas', idField: 'parking_external_id', label: 'Parking Areas' },
  {
    key: 'parking_spaces',
    idField: 'parking_space_external_id',
    label: 'Parking Spaces',
  },
];

// Flattened { entityType, item } list across every reviewable array — the
// Review screen's "Show uncertain only" / "Show blocking review items"
// filters and the accept/correct/reject action all operate on this.
export function flattenReviewableEntities(reviewedResult) {
  if (!reviewedResult) return [];
  const flattened = [];
  REVIEWABLE_ENTITY_ARRAYS.forEach(({ key }) => {
    const array = Array.isArray(reviewedResult[key]) ? reviewedResult[key] : [];
    array.forEach((item) => flattened.push({ entityType: key, item }));
  });
  return flattened;
}

export function countByReviewStatus(reviewedResult) {
  const counts = { pending: 0, accepted: 0, corrected: 0, rejected: 0 };
  flattenReviewableEntities(reviewedResult).forEach(({ item }) => {
    const status = item?.review?.status || 'pending';
    if (counts[status] !== undefined) counts[status] += 1;
  });
  return counts;
}

export function unresolvedBlockingReviewItems(reviewedResult) {
  const items = Array.isArray(reviewedResult?.review_items)
    ? reviewedResult.review_items
    : [];
  return items.filter(
    (item) => item?.blocks_publication && (item?.review?.status || 'pending') === 'pending',
  );
}

// True only when every entity has a non-pending review status AND every
// blocking review item is resolved — the exact two conditions Section 13
// requires before Publish may be enabled. Purely a UI-gating helper; the
// backend's own validate/publish endpoints are the actual source of truth
// and are re-checked server-side regardless of what this returns.
export function isReadyToPublish(reviewedResult) {
  if (!reviewedResult) return false;
  const counts = countByReviewStatus(reviewedResult);
  if (counts.pending > 0) return false;
  if (unresolvedBlockingReviewItems(reviewedResult).length > 0) return false;
  return true;
}

export function idsForAcceptAllHighConfidence(reviewedResult, threshold = 0.85) {
  return flattenReviewableEntities(reviewedResult)
    .filter(
      ({ item }) =>
        Number(item?.confidence) >= threshold &&
        (item?.review?.status || 'pending') === 'pending',
    )
    .map(({ entityType, item }) => ({
      entityType,
      externalId: idFieldValue(entityType, item),
    }));
}

function idFieldValue(entityType, item) {
  const config = REVIEWABLE_ENTITY_ARRAYS.find((entry) => entry.key === entityType);
  return config ? item?.[config.idField] : undefined;
}

// ── Reviewed-result mutation helpers (pure — return a NEW object, never
// mutate the input) ──────────────────────────────────────────────────────

// Deep-ish clone sufficient for this JSON-shaped document (no functions,
// no Dates, no cycles) — avoids a structuredClone dependency so this file
// stays runnable under plain `node file.test.mjs` in every environment.
function cloneJson(value) {
  return value === undefined ? value : JSON.parse(JSON.stringify(value));
}

// Sets one entity's review.status/notes (accept/correct/reject) —
// operates ONLY on the caller's reviewed_result copy; the caller is
// responsible for persisting it via saveReviewedResult(). Never touches
// ai_result (that document is never passed to this function at all).
export function setEntityReviewStatus(
  reviewedResult,
  entityType,
  externalId,
  status,
  notes = null,
) {
  const config = REVIEWABLE_ENTITY_ARRAYS.find((entry) => entry.key === entityType);
  if (!config || !reviewedResult) return reviewedResult;

  const next = cloneJson(reviewedResult);
  const array = Array.isArray(next[entityType]) ? next[entityType] : [];
  const index = array.findIndex((item) => item?.[config.idField] === externalId);
  if (index === -1) return reviewedResult;

  array[index] = {
    ...array[index],
    review: { ...(array[index].review || {}), status, notes },
  };
  next[entityType] = array;
  return next;
}

// "Correct" is the same status transition as accept but also patches one
// or more fields on the entity (e.g. a corrected name/category) in the
// same update — kept as a distinct helper so the review UI's "Correct"
// action reads as one clear intent instead of two separate calls.
export function correctEntity(reviewedResult, entityType, externalId, patch, notes = null) {
  const config = REVIEWABLE_ENTITY_ARRAYS.find((entry) => entry.key === entityType);
  if (!config || !reviewedResult) return reviewedResult;

  const next = cloneJson(reviewedResult);
  const array = Array.isArray(next[entityType]) ? next[entityType] : [];
  const index = array.findIndex((item) => item?.[config.idField] === externalId);
  if (index === -1) return reviewedResult;

  array[index] = {
    ...array[index],
    ...patch,
    review: { ...(array[index].review || {}), status: 'corrected', notes },
  };
  next[entityType] = array;
  return next;
}

export function resolveReviewItem(
  reviewedResult,
  reviewItemExternalId,
  { status, selectedResolution = null, correctedValue = null, notes = null },
) {
  if (!reviewedResult) return reviewedResult;
  const next = cloneJson(reviewedResult);
  const items = Array.isArray(next.review_items) ? next.review_items : [];
  const index = items.findIndex(
    (item) => item?.review_item_external_id === reviewItemExternalId,
  );
  if (index === -1) return reviewedResult;

  items[index] = {
    ...items[index],
    review: {
      ...(items[index].review || {}),
      status,
      selected_resolution: selectedResolution,
      corrected_value: correctedValue,
      notes,
    },
  };
  next.review_items = items;
  return next;
}

// ── Development mock (dev/demo only) ────────────────────────────────────
// Deterministic and CLEARLY labeled (schema_version carries the real
// value but every name is prefixed "[MOCK]" so it can never be mistaken
// for a real AI result if VITE_USE_MAP_ANALYSIS_MOCK is left on by
// accident). Only start/latest/status/result are ever mocked — save/
// validate/publish always hit the real backend so nothing fabricated is
// ever "published" (mirrors the old module's "Apply is never mocked"
// rule).
export function buildMockAnalysisResult(mapId) {
  return {
    schema_version: 'quickroute_semantic_map_import_v2',
    import_draft: {
      status: 'ready_for_review',
      source_type: 'ai_extraction',
      requires_human_review: true,
      can_publish_immediately: false,
    },
    source_documents: [
      {
        source_document_id: 'source_001',
        source_file: `${mapId}-mock.png`,
        file_type: 'image',
        page_type: 'complete_floor_plan',
        included_in_extraction: true,
      },
    ],
    site: { site_external_id: 'site_001', names: { original: '[MOCK] Site' } },
    buildings: [],
    zones: [],
    floors: [{ floor_external_id: 'floor_001', names: { label_original: '[MOCK] Floor 1' } }],
    places: [
      {
        place_external_id: 'place_001',
        floor_external_id: 'floor_001',
        names: { original: '[MOCK] Pharmacy', en: '[MOCK] Pharmacy' },
        category: 'pharmacy',
        status: 'probable',
        confidence: 0.8,
        review: { status: 'pending', notes: null },
        evidence_sources: [{ text: '[MOCK] evidence', source_file: null, source_page: null }],
      },
    ],
    facilities: [],
    access_points: [],
    public_areas: [],
    vertical_connections: [],
    outdoor_areas: [],
    parking_areas: [],
    parking_spaces: [],
    cross_building_connections: [],
    review_items: [],
    unreadable_areas: [],
    summary: {
      total_places: 1,
      total_floors: 1,
      plain_language_summary: '[MOCK] development data — not a real analysis.',
    },
    validation: {
      ready_for_admin_review: true,
      ready_for_publish: false,
      contains_routing_coordinates: false,
      contains_routing_graph_data: false,
      errors: [],
      warnings: [],
    },
  };
}

export function buildMockAnalysisSummary(mapId) {
  return {
    analysis_id: `mock-analysis-${mapId}`,
    scope_type: 'map',
    map_id: mapId,
    status: 'completed',
    progress: 100,
    attempt_count: 1,
    prompt_version: 'quickroute_semantic_map_import_v2',
    prompt_sha256: 'mock',
    model: 'mock',
    review_status: 'pending',
    review_revision: 0,
    error_code: null,
    error_message: null,
  };
}
