// Frontend adapter for the REAL automatic semantic-map-analysis backend
// (see backend/routes/semantic_analysis_routes.py). This REPLACES the
// previous speculative "detections/apply" contract that used to live
// here — that contract generated x/y coordinates directly and had no
// real backend at all; this one matches the actual, now-implemented
// three-layer architecture (AI draft -> admin review -> explicit
// publish), and every function below calls a route that genuinely
// exists.
//
// Every call goes through this one module — components never call
// fetch()/apiRequest() for analysis directly, so a future backend
// contract change only needs to change this file.
//
// Dev mock: set VITE_USE_MAP_ANALYSIS_MOCK=true in the frontend's .env to
// exercise start/latest/status/result with synthetic, clearly-labeled
// ("[MOCK]"-prefixed) data instead of hitting the real backend. This flag
// must never be true in a production build. save/validate/publish are
// NEVER mocked — they always call the real endpoint, so nothing is ever
// fabricated as reviewed or published.
import { apiRequest } from './api.js';
import {
  normalizeAnalysisSummary,
  normalizeAnalysisDetail,
  normalizeAnalysisResult,
  normalizePublishedEntity,
  buildMockAnalysisResult,
  buildMockAnalysisSummary,
} from '../utils/mapAnalysisHelpers.js';

const USE_MOCK =
  String(import.meta.env?.VITE_USE_MAP_ANALYSIS_MOCK).toLowerCase() === 'true';

export const SERVICE_UNAVAILABLE_MESSAGE =
  'Semantic map analysis is not currently available. Manual Map Management tools remain available.';

function isServiceUnavailableError(err) {
  if (!err) return false;
  if ([404, 501, 503].includes(err.status)) return true;
  if (
    err.status === undefined &&
    /failed to fetch|networkerror|load failed|network request failed/i.test(
      err.message || '',
    )
  ) {
    return true;
  }
  return false;
}

async function callRealEndpointOrExplainUnavailable(fn) {
  try {
    return await fn();
  } catch (err) {
    // A real, useful backend error message (e.g. "409: blocking review
    // items unresolved") must always reach the admin as-is — only a
    // genuinely missing/unreachable service gets rewritten to the
    // generic SERVICE_UNAVAILABLE_MESSAGE. Never show a bare
    // "Failed to fetch" when the backend actually explained itself.
    if (isServiceUnavailableError(err)) {
      const unavailable = new Error(SERVICE_UNAVAILABLE_MESSAGE);
      unavailable.isServiceUnavailable = true;
      unavailable.cause = err;
      throw unavailable;
    }
    throw err;
  }
}

export function isMapAnalysisMockEnabled() {
  return USE_MOCK;
}

export async function startMapAnalysis(mapId, { force = false } = {}) {
  if (USE_MOCK) {
    return { ...normalizeAnalysisSummary(buildMockAnalysisSummary(mapId)), isMock: true };
  }
  return callRealEndpointOrExplainUnavailable(async () => {
    const raw = await apiRequest(`/api/maps/${mapId}/semantic-analysis/start`, {
      method: 'POST',
      body: JSON.stringify({ force }),
    });
    return { ...normalizeAnalysisSummary(raw), isMock: false };
  });
}

export async function getLatestMapAnalysis(mapId) {
  if (USE_MOCK) {
    return { ...normalizeAnalysisSummary(buildMockAnalysisSummary(mapId)), isMock: true };
  }
  return callRealEndpointOrExplainUnavailable(async () => {
    const raw = await apiRequest(`/api/maps/${mapId}/semantic-analysis/latest`);
    return raw ? { ...normalizeAnalysisSummary(raw), isMock: false } : null;
  });
}

export async function getAnalysisStatus(analysisId) {
  if (USE_MOCK) {
    const mapId = analysisId.replace(/^mock-analysis-/, '');
    return { ...normalizeAnalysisDetail(buildMockAnalysisSummary(mapId)), isMock: true };
  }
  return callRealEndpointOrExplainUnavailable(async () => {
    const raw = await apiRequest(`/api/semantic-analyses/${analysisId}`);
    return { ...normalizeAnalysisDetail(raw), isMock: false };
  });
}

export async function getAnalysisResult(analysisId) {
  if (USE_MOCK) {
    const mapId = analysisId.replace(/^mock-analysis-/, '');
    return {
      ...normalizeAnalysisResult({
        analysis_id: analysisId,
        status: 'completed',
        prompt_version: 'quickroute_semantic_map_import_v2',
        prompt_sha256: 'mock',
        review_revision: 0,
        ai_result: buildMockAnalysisResult(mapId),
        reviewed_result: null,
        local_validation: { valid: true, errors: [], warnings: [] },
      }),
      isMock: true,
    };
  }
  return callRealEndpointOrExplainUnavailable(async () => {
    const raw = await apiRequest(`/api/semantic-analyses/${analysisId}/result`);
    return { ...normalizeAnalysisResult(raw), isMock: false };
  });
}

// Always calls the real backend — an admin's edits must always actually
// persist. `expectedRevision` implements optimistic concurrency: a stale
// value is rejected (409) by the backend rather than silently
// overwriting a concurrent edit.
export async function saveReviewedResult(analysisId, { expectedRevision, reviewedResult }) {
  return callRealEndpointOrExplainUnavailable(async () => {
    const raw = await apiRequest(`/api/semantic-analyses/${analysisId}/reviewed-result`, {
      method: 'PUT',
      body: JSON.stringify({
        expected_revision: expectedRevision,
        reviewed_result: reviewedResult,
      }),
    });
    return normalizeAnalysisDetail(raw);
  });
}

export async function validateAnalysis(analysisId) {
  return callRealEndpointOrExplainUnavailable(async () => {
    const raw = await apiRequest(`/api/semantic-analyses/${analysisId}/validate`, {
      method: 'POST',
    });
    return {
      valid: Boolean(raw?.valid),
      errors: Array.isArray(raw?.errors) ? raw.errors : [],
      warnings: Array.isArray(raw?.warnings) ? raw.warnings : [],
      blockingReviewItems: Array.isArray(raw?.blocking_review_items)
        ? raw.blocking_review_items
        : [],
    };
  });
}

export async function publishAnalysis(analysisId, { quickrouteLinks = null } = {}) {
  return callRealEndpointOrExplainUnavailable(async () => {
    const raw = await apiRequest(`/api/semantic-analyses/${analysisId}/publish`, {
      method: 'POST',
      body: JSON.stringify({ quickroute_links: quickrouteLinks }),
    });
    return {
      publicationId: raw?.publication_id ?? null,
      analysisId: raw?.analysis_id ?? null,
      mapId: raw?.map_id ?? null,
      publicationRevision: raw?.publication_revision ?? null,
      publishedAt: raw?.published_at ?? null,
    };
  });
}

export async function retryAnalysis(analysisId) {
  return callRealEndpointOrExplainUnavailable(async () => {
    const raw = await apiRequest(`/api/semantic-analyses/${analysisId}/retry`, {
      method: 'POST',
    });
    return normalizeAnalysisSummary(raw);
  });
}

export async function cancelAnalysis(analysisId) {
  return callRealEndpointOrExplainUnavailable(async () => {
    const raw = await apiRequest(`/api/semantic-analyses/${analysisId}/cancel`, {
      method: 'POST',
    });
    return normalizeAnalysisSummary(raw);
  });
}

// Powers "Choose name from approved map data" (Section 16). Never
// mocked with fabricated destinations — when mock mode is on this simply
// returns [], so the selector honestly shows its real "No approved
// semantic data for this Map" empty state instead of a fake list an
// admin could mistake for a real publication.
export async function getPublishedSemanticEntitiesForMap(mapId, { entityType = null } = {}) {
  if (USE_MOCK) return [];
  return callRealEndpointOrExplainUnavailable(async () => {
    const query = entityType ? `?entity_type=${encodeURIComponent(entityType)}` : '';
    const raw = await apiRequest(`/api/maps/${mapId}/semantic-entities${query}`);
    return Array.isArray(raw) ? raw.map(normalizePublishedEntity) : [];
  });
}

// "Approved Semantic Analysis -> Automatic Destinations" — preview/apply
// pair (see backend/services/semantic_destination_service.py). Never
// mocked: preview must always reflect the real, currently-published
// semantic data, and apply always writes to the real backend.
export async function previewSemanticDestinations(mapId, { itemExternalIds = null, lang = 'en' } = {}) {
  return callRealEndpointOrExplainUnavailable(async () => {
    return apiRequest(`/api/maps/${mapId}/semantic-analysis/destinations/preview`, {
      method: 'POST',
      body: JSON.stringify({
        item_external_ids: itemExternalIds,
        lang,
      }),
    });
  });
}

// applyOptions: { publicationId, accepted: [{ semantic_item_id, entity_kind,
// x, y, parent_semantic_item_id, allow_transit_through }], allOrNothing }
// allOrNothing (fast batch placement's single "Save All Destinations"):
// when true, the backend validates the ENTIRE batch before writing
// anything — see backend/services/semantic_destination_service.py's
// `all_or_nothing` parameter. Defaults to false, which is byte-for-byte
// the same request this function has always sent.
export async function applySemanticDestinations(mapId, applyOptions) {
  return callRealEndpointOrExplainUnavailable(async () => {
    return apiRequest(`/api/maps/${mapId}/semantic-analysis/destinations/apply`, {
      method: 'POST',
      body: JSON.stringify({
        publication_id: applyOptions.publicationId ?? null,
        accepted: applyOptions.accepted || [],
        all_or_nothing: Boolean(applyOptions.allOrNothing),
      }),
    });
  });
}

export async function getSemanticPromptInfo() {
  return callRealEndpointOrExplainUnavailable(async () => {
    const raw = await apiRequest('/api/prompts/semantic-map-import/info');
    return {
      promptVersion: raw?.prompt_version ?? null,
      promptSha256: raw?.prompt_sha256 ?? null,
    };
  });
}
