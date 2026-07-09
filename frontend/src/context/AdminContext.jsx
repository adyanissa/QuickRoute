import { createContext, useContext, useState } from 'react';
import { BUILDINGS, ROOMS } from '../data/hospitalData';

// ── Dummy route-point data (ready for future backend) ─────────────────────────
const INITIAL_ROUTES = [
  {
    id: 'rt-1',
    name: 'Main Entrance Node',
    floor: 0,
    x: 120,
    y: 380,
    connectedTo: ['rt-2', 'rt-6'],
  },
  {
    id: 'rt-2',
    name: 'Lobby Junction',
    floor: 0,
    x: 120,
    y: 280,
    connectedTo: ['rt-1', 'rt-3', 'rt-4'],
  },
  {
    id: 'rt-3',
    name: 'Corridor A-West',
    floor: 0,
    x: 220,
    y: 280,
    connectedTo: ['rt-2', 'rt-5'],
  },
  {
    id: 'rt-4',
    name: 'Elevator Landing',
    floor: 0,
    x: 120,
    y: 180,
    connectedTo: ['rt-2'],
  },
  {
    id: 'rt-5',
    name: 'East Wing Gate',
    floor: 0,
    x: 320,
    y: 280,
    connectedTo: ['rt-3'],
  },
  {
    id: 'rt-6',
    name: 'Emergency Entrance',
    floor: 0,
    x: 50,
    y: 350,
    connectedTo: ['rt-1'],
  },
];

// ── Real Quick Route map ──────────────────────────────────────────────────────
const INITIAL_MAP = {
  id: '6a4cf16aa921ae9dc1c84616',
  title: 'Quick Route Real Residential Area',
  campus: 'Afula Residential Complex',
  address: 'Yitzhak Sadeh Street, Afula',
  description:
    'Real navigation area based on architectural development plan',
  hasImage: true,
  imageUrl: '/maps/quick_route_ground_floor.png',
  scale: 1,
  floor_scales: {},
  is_current: true,
};

const AdminContext = createContext(null);

export const AdminProvider = ({ children }) => {
  const [mapData, setMapData] = useState(INITIAL_MAP);

  const [buildings, setBuildings] = useState([...BUILDINGS]);

  const [rooms, setRooms] = useState(() =>
    Object.fromEntries(
      Object.entries(ROOMS).map(([k, v]) => [
        k,
        v.map((r) => ({ ...r })),
      ])
    )
  );

  const [routePoints, setRoutePoints] = useState([
    ...INITIAL_ROUTES,
  ]);

  // ── Map ────────────────────────────────────────────────────────────────────
  const updateMap = (data) => {
    setMapData({ ...data });
  };

  // ── Buildings ──────────────────────────────────────────────────────────────
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
    setBuildings((p) =>
      p.map((x) =>
        x.id === b.id ? { ...b } : x
      )
    );
  };

  const deleteBuilding = (id) => {
    setBuildings((p) =>
      p.filter((x) => x.id !== id)
    );

    setRooms((p) => {
      const n = { ...p };
      delete n[id];
      return n;
    });
  };

  // ── Rooms ──────────────────────────────────────────────────────────────────
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
      [bId]: (p[bId] || []).map((x) =>
        x.id === r.id ? { ...r } : x
      ),
    }));
  };

  const deleteRoom = (bId, id) => {
    setRooms((p) => ({
      ...p,
      [bId]: (p[bId] || []).filter(
        (x) => x.id !== id
      ),
    }));
  };

  // ── Route points ───────────────────────────────────────────────────────────
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
    setRoutePoints((p) =>
      p.map((x) =>
        x.id === r.id ? { ...r } : x
      )
    );
  };

  const deleteRoute = (id) => {
    setRoutePoints((p) =>
      p.filter((x) => x.id !== id)
    );
  };

  return (
    <AdminContext.Provider
      value={{
        mapData,
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
    throw new Error(
      'useAdmin must be used inside <AdminProvider>'
    );
  }

  return ctx;
};