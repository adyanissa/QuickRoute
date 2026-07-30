// Shared adapters that translate real backend Building/Room records
// (snake_case) into the simple view-model shape the UI components
// (DestinationCard, admin screens) expect. Kept separate from any one
// screen so BuildingSelectionScreen, DestinationSelectionScreen and the
// admin screens all read the same real data the same way.
//
// `lang` (the current useLang() value) resolves `.name` to the best
// available translation via the shared getLocalizedText() helper — see
// utils/localization.js. Every consumer of these view models (e.g.
// DestinationCard) keeps reading the plain `.name`/`.nameEn` fields
// completely unchanged; only the VALUE now depends on the requested
// language, never the shape.

import { getLocalizedText } from './localization.js';

export const buildingToViewModel = (b, lang = 'en') => ({
  id: b.id,
  nameEn: b.name_en || '',
  // Buildings have no AI-sourced/admin-approved multilingual `names`
  // source today (only semantic map ENTITIES do) — `b.names` is simply
  // absent on every real Building record, so this resolves to exactly
  // the same name_local fallback as before this helper existed. Passing
  // it through getLocalizedText keeps this forward-compatible without
  // changing today's behavior at all.
  name: getLocalizedText(b.names, lang, b.name_local || b.name_en || ''),
  // Raw translations object (or null for a building with no `names`
  // source today) kept alongside the resolved `name` above so a screen
  // can recompute the display name on a language change without
  // refetching — mirrors roomToViewModel's `names` passthrough.
  names: b.names || null,
  subtitle: b.description || '',
  campus: b.campus || '',
  tag: b.short_tag || '',
  category: b.category || 'general',
  iconColor: b.icon_color || '#2a5298',
  iconBg: `${b.icon_color || '#2a5298'}1f`,
  // GET /api/buildings returns every building regardless of status — the
  // UI is responsible for never showing an inactive one to a normal user.
  isActive: b.is_active !== false,
});

export const roomToViewModel = (r, lang = 'en') => ({
  id: r.id,
  name: getLocalizedText(r.names, lang, r.name_en || ''),
  nameEn: r.name_en || '',
  // Raw translations object (or null for a legacy Room that never had
  // one) — kept alongside the already-resolved `name` above so a screen
  // that needs to search across every stored language (see
  // DestinationSelectionScreen.jsx) doesn't have to re-fetch anything.
  names: r.names || null,
  // Traceability link to the semantic entity this Destination was
  // created from, when applicable — None for a manually-entered Room.
  semanticEntityExternalId: r.semantic_entity_external_id ?? null,
  semanticEntityType: r.semantic_entity_type ?? null,
  type: r.room_type || 'room',
  floor: r.floor ?? 0,
  description: r.description || '',
  buildingId: r.building_id,

  // Map-based destination placement (all null/false for a room created
  // through the manual-only fallback flow, which never sets these).
  mapId: r.map_id ?? null,
  mapGroupId: r.map_group_id ?? null,
  x: r.x ?? null,
  y: r.y ?? null,
  // The one and only way a destination's navigation point is resolved —
  // see utils/destinationPlacement.js's getDestinationRoutePointId().
  routePointId: r.route_point_id ?? null,
  // One-shot signal — only meaningful on the exact create/update response
  // that just performed the map-linking step; the backend always returns
  // it as false on a plain GET (see schemas/room_schema.py). Never use
  // this to decide whether a destination is navigable — use isNavigable
  // below instead, which the backend computes live on every response.
  routePointWasReused: Boolean(r.route_point_was_reused),
  routePointConnected: Boolean(r.route_point_connected),
  // The authoritative, LIVE navigability signal — computed fresh by the
  // backend on every response (list/get/create/update alike) by actually
  // querying current RoutePoint/RouteEdge state. This is what any
  // end-user screen must use to decide whether a destination is
  // clickable (see DestinationSelectionScreen.jsx).
  isNavigable: Boolean(r.is_navigable),
  navigationUnavailableReason: r.navigation_unavailable_reason ?? null,
  // GET /api/rooms returns every room regardless of status — the UI must
  // never display an inactive destination to a normal user (never merely
  // grey it out, per the task's explicit rule).
  isActive: r.is_active !== false,
});
