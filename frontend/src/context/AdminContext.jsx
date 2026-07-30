import { createContext, useContext, useEffect, useState, useCallback } from 'react';
import { apiRequest } from '../api/api';
import {
  getBuildings,
  createBuilding as apiCreateBuilding,
  updateBuilding as apiUpdateBuilding,
  deleteBuilding as apiDeleteBuilding,
} from '../api/buildingsApi';

// ── View-model <-> backend shape adapters ──────────────────────────────────
// The backend Building/Room documents use snake_case field names
// (name_en, short_tag, icon_color, room_type, ...). The admin screens were
// built against a simpler view-model shape (nameEn, tag, iconColor, type, ...).
// These helpers translate both ways so the screens don't need to know about
// the backend schema.

const buildingToViewModel = (b) => ({
  id: b.id,
  nameEn: b.name_en || '',
  name: b.name_local || '',
  subtitle: b.description || '',
  tag: b.short_tag || '',
  category: b.category || 'general',
  iconColor: b.icon_color || '#2a5298',
  iconBg: `${b.icon_color || '#2a5298'}1f`,
});

const buildingToApiPayload = (b) => ({
  name_en: b.nameEn,
  name_local: b.name || null,
  description: b.subtitle || null,
  short_tag: b.tag || null,
  icon_color: b.iconColor || null,
  category: b.category || null,
});

const roomToViewModel = (r) => ({
  id: r.id,
  name: r.name_en || '',
  type: r.room_type || 'room',
  floor: r.floor ?? 0,
  description: r.description || '',

  // Independently-editable AR/HE translations (Section 4/5 of the
  // multilingual spec) — sourced from the same nested `names` object the
  // end-user-facing screens read via utils/viewModels.js, never a second
  // independently-drifting field. `name` above stays the legacy EN value
  // (name_en) for full backward compatibility with the rest of this
  // admin screen; `names` is the raw object kept alongside it so a
  // Correct/edit form can show empty languages clearly instead of
  // guessing them from name_en.
  names: r.names || null,
  nameAr: r.names?.ar || '',
  nameHe: r.names?.he || '',
  // Traceability link to the semantic entity this Destination was
  // created from (Section 6) — null for a manually-entered Room.
  semanticPublicationId: r.semantic_publication_id ?? null,
  semanticEntityExternalId: r.semantic_entity_external_id ?? null,
  semanticEntityType: r.semantic_entity_type ?? null,

  // Map-based destination placement — null/false for a room created
  // through the manual-only fallback flow.
  mapId: r.map_id ?? null,
  mapGroupId: r.map_group_id ?? r.mapGroupId ?? null,
  x: r.x ?? null,
  y: r.y ?? null,
  routePointId: r.route_point_id ?? null,
  // One-shot signal — only meaningful on the exact create/update response
  // that just performed the map-linking step; the backend always returns
  // it as false on a plain GET (see backend/schemas/room_schema.py). Do
  // not use this to render a room's connection status in a plain list —
  // use isNavigable below instead, which the backend computes live from
  // the real current RoutePoint/RouteEdge state on every response.
  routePointWasReused: Boolean(r.route_point_was_reused),
  routePointConnected: Boolean(r.route_point_connected),
  isNavigable: Boolean(r.is_navigable),
  navigationUnavailableReason: r.navigation_unavailable_reason ?? null,
});

const roomToApiPayload = (r, buildingId) => {
  const payload = {
    building_id: buildingId,
    name_en: r.name,
    // The AR/HE/EN Correct-style inputs are edited together as one form
    // (same convention as AdminMapAnalysisScreen's per-language Correct
    // UI), so the whole `names` object is sent every save — this is a
    // deliberate full overwrite of these three keys, never a silent
    // partial guess. name_en (EN, required) is kept in sync with
    // names.en so both the legacy field and the new structure agree.
    names: { en: r.name || null, ar: r.nameAr || null, he: r.nameHe || null },
    room_type: r.type || null,
    floor: r.floor === '' || r.floor === undefined ? null : Number(r.floor),
    description: r.description || null,
  };

  // Semantic-entity traceability (Section 6) — only ever forwarded when
  // this room was actually created from/already linked to a published
  // semantic entity; never invented for an ordinary manual room, and
  // never cleared by an unrelated edit (only sent when present).
  if (r.semanticPublicationId) payload.semantic_publication_id = r.semanticPublicationId;
  if (r.semanticEntityExternalId) payload.semantic_entity_external_id = r.semanticEntityExternalId;
  if (r.semanticEntityType) payload.semantic_entity_type = r.semanticEntityType;

  // Map placement is opt-in and all-or-nothing on the backend: only send
  // map_id/x/y when a location was actually picked on the map, so a
  // manual-only save behaves exactly as before (no RoutePoint created).
  if (r.mapId && r.x !== null && r.x !== undefined && r.y !== null && r.y !== undefined) {
    payload.map_id = r.mapId;
    payload.x = Number(r.x);
    payload.y = Number(r.y);
  }

  return payload;
};

// ── Map view-model <-> backend shape adapter ────────────────────────────────
// Handles both the old simple map fields (image_url, scale, floor_scales)
// and the map-upload-backend fields (source_image_url, display_image_url,
// processing_status/progress/error, generation_method).

const EMPTY_MAP = { hasImage: false };

const normalizeMap = (map) => {
  if (!map) return EMPTY_MAP;

  return {
    id: map.id || map._id || null,
    title: map.title || map.name || '',
    campus: map.campus || map.location || '',
    address: map.address || '',
    description: map.description || '',

    // Was silently dropped here before — this object literal only ever
    // returned the fields explicitly listed, so any screen reading
    // `map.buildingId`/`map.building_id` off AdminContext's `maps` (e.g.
    // Location Codes' Building -> Map dependent dropdown) always saw
    // `undefined` and could never match a selected building, even though
    // the backend has correctly returned building_id since the automatic
    // building-setup work. building_id is always stringified so it
    // compares equal to a Building.id (also always a string) without a
    // separate normalization step at every call site.
    buildingId: map.building_id != null ? String(map.building_id)
      : map.buildingId != null ? String(map.buildingId)
      : null,
    floor: map.floor ?? null,
    floor_label: map.floor_label ?? map.floorLabel ?? null,
    map_group_id: map.map_group_id ?? map.mapGroupId ?? null,
    map_group_code: map.map_group_code ?? map.mapGroupCode ?? null,

    imageUrl: map.imageUrl || map.image_url || null,
    sourceImageUrl: map.sourceImageUrl || map.source_image_url || null,
    displayImageUrl: map.displayImageUrl || map.display_image_url || null,

    hasImage: Boolean(
      map.hasImage ||
        map.has_image ||
        map.imageUrl ||
        map.image_url ||
        map.sourceImageUrl ||
        map.source_image_url ||
        map.displayImageUrl ||
        map.display_image_url
    ),

    processingStatus: map.processingStatus || map.processing_status || 'not_started',
    processingProgress: map.processingProgress ?? map.processing_progress ?? 0,
    processingError: map.processingError || map.processing_error || null,
    generationMethod: map.generationMethod || map.generation_method || null,

    scale: map.scale ?? 1,
    floor_scales: map.floor_scales || {},
    is_current: Boolean(map.is_current || map.isCurrent),
  };
};

const mapToApiPayload = (map) => ({
  title: map.title || '',
  campus: map.campus || '',
  address: map.address || '',
  description: map.description || '',
  image_url: map.imageUrl || null,
  source_image_url: map.sourceImageUrl || null,
  display_image_url: map.displayImageUrl || null,
  scale: Number(map.scale || 1),
  floor_scales: map.floor_scales || {},
  is_current: Boolean(map.is_current),
});

const AdminContext = createContext(null);

export const AdminProvider = ({ children }) => {
  // ── Map state (list + current + upload/processing status) ────────────────
  const [mapData, setMapData] = useState(EMPTY_MAP);
  const [maps, setMaps] = useState([]);
  const [isMapLoading, setIsMapLoading] = useState(false);
  const [mapError, setMapError] = useState('');

  // ── Buildings ──────────────────────────────────────────────────────────────
  const [buildings, setBuildings] = useState([]);
  const [buildingsLoading, setBuildingsLoading] = useState(true);

  // ── Rooms ──────────────────────────────────────────────────────────────────
  const [rooms, setRooms] = useState({});
  const [roomsLoading, setRoomsLoading] = useState(true);

  // ── Route points (read-only here; managed by AdminRoutesScreen) ───────────
  const [routePoints, setRoutePoints] = useState([]);

  // ── Loaders ──────────────────────────────────────────────────────────────
  const loadMaps = useCallback(async () => {
    setIsMapLoading(true);
    setMapError('');

    try {
      const data = await apiRequest('/api/maps');
      const normalizedMaps = Array.isArray(data)
        ? data.map(normalizeMap)
        : [normalizeMap(data)];

      setMaps(normalizedMaps);

      const currentMap =
        normalizedMaps.find((map) => map.is_current) || normalizedMaps[0] || EMPTY_MAP;

      setMapData(currentMap);
    } catch (error) {
      console.error('Failed to load maps:', error);
      setMapError('Failed to load maps');
      setMapData(EMPTY_MAP);
    } finally {
      setIsMapLoading(false);
    }
  }, []);

  const loadBuildings = useCallback(async () => {
    setBuildingsLoading(true);
    try {
      const data = await getBuildings();
      setBuildings((Array.isArray(data) ? data : []).map(buildingToViewModel));
    } catch (err) {
      console.error('Failed to load buildings:', err);
      setBuildings([]);
    } finally {
      setBuildingsLoading(false);
    }
  }, []);

  const loadRooms = useCallback(async () => {
    setRoomsLoading(true);
    try {
      const data = await apiRequest('/api/rooms');
      const grouped = {};
      (Array.isArray(data) ? data : []).forEach((room) => {
        if (!grouped[room.building_id]) grouped[room.building_id] = [];
        grouped[room.building_id].push(roomToViewModel(room));
      });
      setRooms(grouped);
    } catch (err) {
      console.error('Failed to load rooms:', err);
      setRooms({});
    } finally {
      setRoomsLoading(false);
    }
  }, []);

  const loadRoutePoints = useCallback(async () => {
    try {
      const data = await apiRequest('/api/route-points');
      setRoutePoints(Array.isArray(data) ? data : []);
    } catch (err) {
      console.error('Failed to load route points:', err);
      setRoutePoints([]);
    }
  }, []);

  useEffect(() => {
    loadMaps();
    loadBuildings();
    loadRooms();
    loadRoutePoints();
  }, [loadMaps, loadBuildings, loadRooms, loadRoutePoints]);

  // ── Map mutation ───────────────────────────────────────────────────────────
  const updateMap = async (data) => {
    const normalized = normalizeMap(data);

    if (!normalized.id) {
      setMapData(normalized);
      return;
    }

    try {
      const updatedMap = normalizeMap(
        await apiRequest(`/api/maps/${normalized.id}`, {
          method: 'PUT',
          body: JSON.stringify(mapToApiPayload(normalized)),
        })
      );

      setMapData(updatedMap);
      setMaps((previousMaps) =>
        previousMaps.map((map) => (map.id === updatedMap.id ? updatedMap : map))
      );
    } catch (error) {
      console.error('Failed to update map:', error);
      alert('Failed to update map');
    }
  };

  // ── Buildings ──────────────────────────────────────────────────────────────
  const addBuilding = async (b) => {
    const created = await apiCreateBuilding(buildingToApiPayload(b));
    setBuildings((prev) => [...prev, buildingToViewModel(created)]);
  };

  const updateBuilding = async (b) => {
    const updated = await apiUpdateBuilding(b.id, buildingToApiPayload(b));
    setBuildings((prev) =>
      prev.map((x) => (x.id === b.id ? buildingToViewModel(updated) : x))
    );
  };

  const deleteBuilding = async (id) => {
    await apiDeleteBuilding(id);
    setBuildings((prev) => prev.filter((x) => x.id !== id));
    setRooms((prev) => {
      const next = { ...prev };
      delete next[id];
      return next;
    });
  };

  // ── Rooms ──────────────────────────────────────────────────────────────────
  const addRoom = async (buildingId, r) => {
    const created = await apiRequest('/api/rooms', {
      method: 'POST',
      body: JSON.stringify(roomToApiPayload(r, buildingId)),
    });
    const viewModel = roomToViewModel(created);
    setRooms((prev) => ({
      ...prev,
      [buildingId]: [...(prev[buildingId] || []), viewModel],
    }));
    // Returned (not just stored) so the map-based placement flow can show
    // a real result summary — RoutePoint created/reused, graph connected
    // or not — straight from the backend's actual response.
    return viewModel;
  };

  const updateRoom = async (buildingId, r) => {
    const updated = await apiRequest(`/api/rooms/${r.id}`, {
      method: 'PUT',
      body: JSON.stringify(roomToApiPayload(r, buildingId)),
    });
    const viewModel = roomToViewModel(updated);
    setRooms((prev) => ({
      ...prev,
      [buildingId]: (prev[buildingId] || []).map((x) =>
        x.id === r.id ? viewModel : x
      ),
    }));
    return viewModel;
  };

  const deleteRoom = async (buildingId, id) => {
    await apiRequest(`/api/rooms/${id}`, { method: 'DELETE' });
    setRooms((prev) => ({
      ...prev,
      [buildingId]: (prev[buildingId] || []).filter((x) => x.id !== id),
    }));
  };

  return (
    <AdminContext.Provider
      value={{
        mapData,
        maps,
        isMapLoading,
        mapError,
        loadMaps,
        updateMap,

        buildings,
        buildingsLoading,
        loadBuildings,
        addBuilding,
        updateBuilding,
        deleteBuilding,

        rooms,
        roomsLoading,
        loadRooms,
        addRoom,
        updateRoom,
        deleteRoom,

        routePoints,
        loadRoutePoints,
      }}
    >
      {children}
    </AdminContext.Provider>
  );
};

export const useAdmin = () => {
  const ctx = useContext(AdminContext);

  if (!ctx) {
    throw new Error('useAdmin must be used inside <AdminProvider>');
  }

  return ctx;
};
