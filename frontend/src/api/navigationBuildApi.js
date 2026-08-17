import { apiRequest } from "./api";

// Automatic Navigation Build — PHASE A, PREVIEW ONLY.
//
// Asks the server what a fully automatic navigation build WOULD produce
// for one map: the building region it detected, the hidden transit graph
// it would generate, where each accepted room's arrival point would go,
// which rooms it could not resolve, and how many QR codes an apply would
// issue.
//
// It writes nothing. There is deliberately no apply function in this file
// because there is no apply endpoint yet — persistence, QR issuance and
// the end-to-end orchestration are Phase B, gated on a human inspecting
// this preview against a real floor plan first.
//
// A refusal is a normal outcome and comes back as HTTP 200 with
// `available: false`, a named `failed_stage` and a readable `reason`, so
// callers must check `available` rather than relying on the request
// throwing.
export async function previewNavigationBuild(
  mapId,
  { itemExternalIds = null, lang = 'en' } = {},
) {
  return apiRequest(`/api/maps/${mapId}/navigation-build/preview`, {
    method: 'POST',
    body: JSON.stringify({
      item_external_ids: itemExternalIds,
      lang,
    }),
  });
}

export default previewNavigationBuild;
