import { createContext, useContext, useEffect, useState } from 'react';
import { BUILDINGS, ROOMS } from '../data/hospitalData';

const API_BASE_URL = 'http://127.0.0.1:8000';

const INITIAL_ROUTES = [];

const FALLBACK_MAP = {
  id: null,
  title: '',
  campus: '',
  address: '',
  description: '',
  hasImage: false,

  imageUrl: null,
  sourceImageUrl: null,
  displayImageUrl: null,

  scale: 1,
  floor_scales: {},
  is_current: false,
};

const normalizeMap = (map) => {
  if (!map) return FALLBACK_MAP;

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
  const [mapData, setMapData] = useState(FALLBACK_MAP);
  const [maps, setMaps] = useState([]);
  const [isMapLoading, setIsMapLoading] = useState(false);
  const [mapError, setMapError] = useState('');

  const [buildings, setBuildings] = useState([...BUILDINGS]);

  const [rooms, setRooms] = useState(() =>
    Object.fromEntries(
      Object.entries(ROOMS).map(([k, v]) => [
        k,
        v.map((r) => ({ ...r })),
      ])
    )
  );

  const [routePoints, setRoutePoints] = useState([...INITIAL_ROUTES]);

  const loadMaps = async () => {
    setIsMapLoading(true);
    setMapError('');

    try {
      const response = await fetch(`${API_BASE_URL}/api/maps`);

      if (!response.ok) {
        throw new Error('Failed to load maps');
      }

      const data = await response.json();
      const normalizedMaps = Array.isArray(data)
        ? data.map(normalizeMap)
        : [normalizeMap(data)];

      setMaps(normalizedMaps);

      const currentMap =
        normalizedMaps.find((map) => map.is_current) || normalizedMaps[0] || FALLBACK_MAP;

      setMapData(currentMap);
    } catch (error) {
      console.error(error);
      setMapError('Failed to load maps');
      setMapData(FALLBACK_MAP);
    } finally {
      setIsMapLoading(false);
    }
  };

  useEffect(() => {
    loadMaps();
  }, []);

  const updateMap = async (data) => {
    const normalized = normalizeMap(data);

    if (!normalized.id) {
      setMapData(normalized);
      return;
    }

    try {
      const response = await fetch(`${API_BASE_URL}/api/maps/${normalized.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(mapToApiPayload(normalized)),
      });

      if (!response.ok) {
        throw new Error('Failed to update map');
      }

      const updatedMap = normalizeMap(await response.json());

      setMapData(updatedMap);
      setMaps((previousMaps) =>
        previousMaps.map((map) => (map.id === updatedMap.id ? updatedMap : map))
      );
    } catch (error) {
      console.error(error);
      alert('Failed to update map');
    }
  };

  const addBuilding = (b) => {
    setBuildings((p) => [
      ...p,
      {
        ...b,
        id: b.id || `bld-${Date.now()}`,
      },
    ]);
  };

  const updateBuilding = (b) => {
    setBuildings((p) => p.map((x) => (x.id === b.id ? { ...b } : x)));
  };

  const deleteBuilding = (id) => {
    setBuildings((p) => p.filter((x) => x.id !== id));

    setRooms((p) => {
      const n = { ...p };
      delete n[id];
      return n;
    });
  };

  const addRoom = (bId, r) => {
    setRooms((p) => ({
      ...p,
      [bId]: [
        ...(p[bId] || []),
        {
          ...r,
          id: r.id || `rm-${Date.now()}`,
        },
      ],
    }));
  };

  const updateRoom = (bId, r) => {
    setRooms((p) => ({
      ...p,
      [bId]: (p[bId] || []).map((x) => (x.id === r.id ? { ...r } : x)),
    }));
  };

  const deleteRoom = (bId, id) => {
    setRooms((p) => ({
      ...p,
      [bId]: (p[bId] || []).filter((x) => x.id !== id),
    }));
  };

  const addRoute = (r) => {
    setRoutePoints((p) => [
      ...p,
      {
        ...r,
        id: r.id || `rt-${Date.now()}`,
      },
    ]);
  };

  const updateRoute = (r) => {
    setRoutePoints((p) => p.map((x) => (x.id === r.id ? { ...r } : x)));
  };

  const deleteRoute = (id) => {
    setRoutePoints((p) => p.filter((x) => x.id !== id));
  };

  return (
    <AdminContext.Provider
      value={{
        API_BASE_URL,

        mapData,
        maps,
        isMapLoading,
        mapError,
        loadMaps,
        updateMap,

        buildings,
        addBuilding,
        updateBuilding,
        deleteBuilding,

        rooms,
        addRoom,
        updateRoom,
        deleteRoom,

        routePoints,
        addRoute,
        updateRoute,
        deleteRoute,
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