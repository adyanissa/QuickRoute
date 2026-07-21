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
  type: r.room_type || 'clinic',
  floor: r.floor ?? 0,
  description: r.description || '',
});

const roomToApiPayload = (r, buildingId) => ({
  building_id: buildingId,
  name_en: r.name,
  room_type: r.type || null,
  floor: r.floor === '' || r.floor === undefined ? null : Number(r.floor),
  description: r.description || null,
});

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
    setRooms((prev) => ({
      ...prev,
      [buildingId]: [...(prev[buildingId] || []), roomToViewModel(created)],
    }));
  };

  const updateRoom = async (buildingId, r) => {
    const updated = await apiRequest(`/api/rooms/${r.id}`, {
      method: 'PUT',
      body: JSON.stringify(roomToApiPayload(r, buildingId)),
    });
    setRooms((prev) => ({
      ...prev,
      [buildingId]: (prev[buildingId] || []).map((x) =>
        x.id === r.id ? roomToViewModel(updated) : x
      ),
    }));
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
        addBuilding,
        updateBuilding,
        deleteBuilding,

        rooms,
        roomsLoading,
        addRoom,
        updateRoom,
        deleteRoom,

        routePoints,
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
