import { apiRequest } from "./api";

// POST /api/navigation/route — LEGACY same-floor-only endpoint, left
// completely untouched/still used by AdminMapScreen's Test Route. Do not
// build new multi-floor-aware features on top of this one.
// body: { map_id, start_point_id, end_point_id }
// response: { map_id, start_point_id, end_point_id, path_point_ids,
//              path_details, total_distance }
export function calculateRoute({ mapId, startPointId, endPointId }) {
  return apiRequest("/api/navigation/route", {
    method: "POST",
    body: JSON.stringify({
      map_id: mapId,
      start_point_id: startPointId,
      end_point_id: endPointId,
    }),
  });
}

// POST /api/navigation/multi-floor-route (PHASES 6-14) — works for both
// same-floor AND cross-floor requests (a same-floor request simply comes
// back as a single floor segment with zero transitions), so this is the
// one route IndoorNavigationScreen needs regardless of whether the
// destination happens to share the start's floor.
// optimizationMode: "shortest" | "fastest" | "accessible"
// avoid: { avoidStairs?, avoidEscalators?, preferElevators? }
// verticalTransportPreference: "any" | "elevator" | "stairs" — the
// backend's new MultiFloorRouteRequest.vertical_transport_preference field
// (backend/routes/navigation_routes.py). Defaults to "any" so omitting it
// (or any older client that never sends it) behaves exactly as before —
// this is a per-request graph-edge filter applied before the existing
// Dijkstra call, never a permanent/global change. Kept separate from the
// existing avoidStairs/avoidEscalators/preferElevators checkboxes (Phase
// 14), which continue to work unchanged; the backend unions both sets of
// exclusions.
// lang: "en" | "ar" | "he" — the backend's MultiFloorRouteRequest.lang
// field already exists and already drives generate_instructions_for_route()
// (see backend/logic/instruction_generator.py's TEXT_TEMPLATES), it was
// simply never sent from here before. Passing it through is the ONLY
// change needed to get real Arabic/Hebrew turn-by-turn instruction text —
// no new backend instruction engine, no frontend recalculation of turns.
// response: { start_point_id, destination_point_id, map_group_id,
//   optimization_mode, total_distance_meters, total_estimated_time_seconds,
//   is_accessible, segments: [...], instructions: [...] }
export function calculateMultiFloorRoute({
  startPointId,
  endPointId,
  optimizationMode = "shortest",
  avoid = {},
  verticalTransportPreference = "any",
  lang = "en",
}) {
  return apiRequest("/api/navigation/multi-floor-route", {
    method: "POST",
    body: JSON.stringify({
      start_point_id: startPointId,
      end_point_id: endPointId,
      optimization_mode: optimizationMode,
      avoid_stairs: Boolean(avoid.avoidStairs),
      avoid_escalators: Boolean(avoid.avoidEscalators),
      prefer_elevators: Boolean(avoid.preferElevators),
      vertical_transport_preference: verticalTransportPreference,
      lang,
    }),
  });
}
