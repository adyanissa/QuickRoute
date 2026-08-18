import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import QuickRouteLogo from '../components/QuickRouteLogo';
import { ROUTES } from '../config/routes';
import '../styles/adminDashboard.css';

// ── Icons ─────────────────────────────────────────────────────────────────────

const MapIcon = () => (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
    <path d="M9 20L3 17V4l6 3M9 20l6-3M9 20V7M15 17l6 3V7l-6-3M15 17V4M9 7l6-3"
      stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

const LocationIcon = () => (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
    <path d="M12 2C8.686 2 6 4.686 6 8c0 5.25 6 13 6 13s6-7.75 6-13c0-3.314-2.686-6-6-6z"
      stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
    <circle cx="12" cy="8" r="2" stroke="currentColor" strokeWidth="1.8" />
  </svg>
);

const RoomIcon = () => (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
    <rect x="3" y="3" width="18" height="18" rx="2" stroke="currentColor" strokeWidth="1.8" />
    <path d="M9 3v18M3 9h6M3 15h6" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
  </svg>
);

const RouteIcon = () => (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
    <circle cx="6" cy="6" r="3" stroke="currentColor" strokeWidth="1.8" />
    <circle cx="18" cy="18" r="3" stroke="currentColor" strokeWidth="1.8" />
    <path d="M9 6h3a3 3 0 0 1 3 3v6a3 3 0 0 0 3 3"
      stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
  </svg>
);

const UploadIcon = () => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none">
    <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M17 8l-5-5-5 5M12 3v12"
      stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

const EditIcon = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
    <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"
      stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"
      stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

const DeleteIcon = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
    <polyline points="3 6 5 6 21 6" stroke="currentColor" strokeWidth="2"
      strokeLinecap="round" strokeLinejoin="round" />
    <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6M10 11v6M14 11v6M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"
      stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

const AddIcon = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
    <line x1="12" y1="5" x2="12" y2="19" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" />
    <line x1="5" y1="12" x2="19" y2="12" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" />
  </svg>
);

const LogoutIcon = () => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none">
    <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9"
      stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

const ShieldIcon = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
    <path d="M12 2L4 6v6c0 5.25 3.5 10.2 8 11.5C16.5 22.2 20 17.25 20 12V6L12 2z"
      stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
    <path d="M9 12l2 2 4-4" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

const CloseIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
    <line x1="18" y1="6" x2="6" y2="18" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" />
    <line x1="6" y1="6" x2="18" y2="18" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" />
  </svg>
);

const WarningIcon = () => (
  <svg width="28" height="28" viewBox="0 0 24 24" fill="none">
    <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"
      stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
    <line x1="12" y1="9" x2="12" y2="13" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
    <line x1="12" y1="17" x2="12.01" y2="17" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" />
  </svg>
);

// ── Dummy data ────────────────────────────────────────────────────────────────

const INITIAL_MAP = {
  id: 1,
  title: 'CMC Ground Floor Map',
  buildingName: 'Central Medical Center',
  floor: 'Ground Floor (Floor 0)',
  mapImage: 'uploaded',
  description: 'Main building ground floor — entrances, emergency, reception, pharmacy.',
};

const INITIAL_LOCATIONS = [
  { id: 1, name: 'Main Entrance',     type: 'entrance',  floor: '0', description: 'North-facing main entrance with accessibility ramp' },
  { id: 2, name: 'Emergency Room',    type: 'emergency', floor: '0', description: '24/7 emergency services, triage unit' },
  { id: 3, name: 'Central Pharmacy',  type: 'pharmacy',  floor: '0', description: 'Ground floor pharmacy near main lobby' },
  { id: 4, name: 'Elevator A',        type: 'elevator',  floor: '0', description: 'Central elevator bank, serves all floors' },
  { id: 5, name: 'Staircase West',    type: 'stairs',    floor: '0', description: 'West-wing staircase, accessible' },
  { id: 6, name: 'Information Desk',  type: 'service',   floor: '0', description: 'Patient information and wayfinding assistance' },
];

const INITIAL_ROOMS = [
  { id: 1, name: 'Cardiology Clinic',    type: 'clinic',     floor: '2', code: 'CAR-201', description: 'Heart and vascular care unit' },
  { id: 2, name: 'Pediatrics Ward',      type: 'ward',       floor: '3', code: 'PED-301', description: 'Children medical care' },
  { id: 3, name: 'Radiology Lab',        type: 'lab',        floor: '1', code: 'RAD-102', description: 'X-Ray, CT, and MRI services' },
  { id: 4, name: 'Oncology Department',  type: 'department', floor: '4', code: 'ONC-401', description: 'Cancer diagnosis and treatment' },
  { id: 5, name: 'Cafeteria',            type: 'facility',   floor: '0', code: 'FAC-003', description: 'Open 7am–8pm, ground floor' },
  { id: 6, name: 'Admin Office',         type: 'office',     floor: '1', code: 'ADM-105', description: 'Hospital administration' },
];

const INITIAL_ROUTES = [
  { id: 1, name: 'Entrance Node',    x: 120, y: 380, connectedTo: [2, 3] },
  { id: 2, name: 'Lobby Junction',   x: 120, y: 280, connectedTo: [1, 3, 4] },
  { id: 3, name: 'Corridor A',       x: 220, y: 280, connectedTo: [2, 5] },
  { id: 4, name: 'Elevator Landing', x: 120, y: 180, connectedTo: [2] },
  { id: 5, name: 'East Wing Gate',   x: 320, y: 280, connectedTo: [3] },
];

const LOCATION_TYPES = [
  { value: 'entrance',  label: 'Entrance' },
  { value: 'elevator',  label: 'Elevator' },
  { value: 'stairs',    label: 'Stairs' },
  { value: 'emergency', label: 'Emergency' },
  { value: 'pharmacy',  label: 'Pharmacy' },
  { value: 'service',   label: 'Service Desk' },
  { value: 'other',     label: 'Other' },
];

const ROOM_TYPES = [
  { value: 'clinic',     label: 'Clinic' },
  { value: 'ward',       label: 'Ward' },
  { value: 'lab',        label: 'Lab' },
  { value: 'department', label: 'Department' },
  { value: 'office',     label: 'Office' },
  { value: 'facility',   label: 'Facility' },
  { value: 'other',      label: 'Other' },
];

// ── ModalForm ─────────────────────────────────────────────────────────────────

const ModalForm = ({ title, fields, values, onChange, onSave, onCancel }) => (
  <div className="adm-overlay" onClick={onCancel}>
    <div className="adm-modal" onClick={(e) => e.stopPropagation()}>
      <div className="adm-modal-head">
        <h3 className="adm-modal-title">{title}</h3>
        <button className="adm-modal-close" onClick={onCancel} aria-label="Close">
          <CloseIcon />
        </button>
      </div>
      <div className="adm-modal-body">
        {fields.map((field) => (
          <div key={field.key} className="adm-field">
            <label className="adm-field-label">{field.label}</label>
            {field.type === 'textarea' ? (
              <textarea
                className="adm-field-textarea"
                value={values[field.key] || ''}
                onChange={(e) => onChange(field.key, e.target.value)}
                placeholder={field.placeholder || ''}
                rows={3}
              />
            ) : field.type === 'select' ? (
              <select
                className="adm-field-select"
                value={values[field.key] || ''}
                onChange={(e) => onChange(field.key, e.target.value)}
              >
                <option value="">Select type…</option>
                {field.options.map((opt) => (
                  <option key={opt.value} value={opt.value}>{opt.label}</option>
                ))}
              </select>
            ) : (
              <input
                className="adm-field-input"
                type={field.type || 'text'}
                value={values[field.key] || ''}
                onChange={(e) => onChange(field.key, e.target.value)}
                placeholder={field.placeholder || ''}
              />
            )}
          </div>
        ))}
      </div>
      <div className="adm-modal-foot">
        <button className="adm-btn-cancel" onClick={onCancel}>Cancel</button>
        <button className="adm-btn-save"   onClick={onSave}>Save Changes</button>
      </div>
    </div>
  </div>
);

// ── ConfirmModal ──────────────────────────────────────────────────────────────

const ConfirmModal = ({ message, onConfirm, onCancel }) => (
  <div className="adm-overlay" onClick={onCancel}>
    <div className="adm-confirm" onClick={(e) => e.stopPropagation()}>
      <div className="adm-confirm-icon"><WarningIcon /></div>
      <h3 className="adm-confirm-title">Confirm Delete</h3>
      <p className="adm-confirm-msg">{message}</p>
      <div className="adm-modal-foot">
        <button className="adm-btn-cancel"    onClick={onCancel}>Cancel</button>
        <button className="adm-btn-delete"    onClick={onConfirm}>Delete</button>
      </div>
    </div>
  </div>
);

// ── StatCard ──────────────────────────────────────────────────────────────────

const StatCard = ({ icon, label, value, accent }) => (
  <div className="adm-stat" style={{ '--acc': accent }}>
    <div className="adm-stat-icon">{icon}</div>
    <div className="adm-stat-val">{value}</div>
    <div className="adm-stat-lbl">{label}</div>
  </div>
);

// ── SectionHeader ─────────────────────────────────────────────────────────────

const SectionHeader = ({ icon, title, desc, gradient }) => (
  <div className="adm-sec-head">
    <div className="adm-sec-icon" style={{ background: gradient }}>{icon}</div>
    <div>
      <h2 className="adm-sec-title">{title}</h2>
      <p  className="adm-sec-desc">{desc}</p>
    </div>
  </div>
);

// ── DataRow ───────────────────────────────────────────────────────────────────

const DataRow = ({ name, tags, onEdit, onDelete }) => (
  <div className="adm-row">
    <div className="adm-row-info">
      <div className="adm-row-name">{name}</div>
      <div className="adm-row-tags">{tags}</div>
    </div>
    <div className="adm-row-acts">
      <button className="adm-icon-btn"        onClick={onEdit}   title="Edit"><EditIcon /></button>
      <button className="adm-icon-btn adm-icon-btn-danger" onClick={onDelete} title="Delete"><DeleteIcon /></button>
    </div>
  </div>
);

// ── Tag helpers ───────────────────────────────────────────────────────────────

const Tag = ({ children, color = 'blue' }) => (
  <span className={`adm-tag adm-tag-${color}`}>{children}</span>
);

const TagText = ({ children }) => (
  <span className="adm-tag-txt">{children}</span>
);

// ── AdminDashboard ────────────────────────────────────────────────────────────

const AdminDashboard = () => {
  const navigate = useNavigate();

  // ── Data state ────────────────────────────────────────────────────────────
  const [mapData,    setMapData]    = useState(INITIAL_MAP);
  const [locations,  setLocations]  = useState(INITIAL_LOCATIONS);
  const [rooms,      setRooms]      = useState(INITIAL_ROOMS);
  const [routes,     setRoutes]     = useState(INITIAL_ROUTES);

  // ── UI state ──────────────────────────────────────────────────────────────
  const [modal,       setModal]      = useState(null); // { section, type }
  const [formValues,  setFormValues] = useState({});
  const [confirm,     setConfirm]    = useState(null); // { message, onConfirm }

  // ── Modal helpers ─────────────────────────────────────────────────────────
  const openModal = (section, type, data = {}) => {
    setFormValues({ ...data });
    setModal({ section, type });
  };

  const closeModal = () => {
    setModal(null);
    setFormValues({});
  };

  const setField = (key, val) => setFormValues((p) => ({ ...p, [key]: val }));

  // ── Map actions ───────────────────────────────────────────────────────────
  const handleUpload  = () => setMapData((p) => ({ ...p, mapImage: 'uploaded' }));
  const handleEditMap = () => openModal('map', 'edit', mapData);

  const handleDeleteMap = () =>
    setConfirm({
      message: 'Delete the current map? All metadata will be cleared.',
      onConfirm: () => {
        setMapData({ id: 1, title: '', buildingName: '', floor: '', mapImage: null, description: '' });
        setConfirm(null);
      },
    });

  const handleSaveMap = () => {
    setMapData({ ...formValues });
    closeModal();
  };

  // ── Location actions ──────────────────────────────────────────────────────
  const handleAddLoc  = ()    => openModal('location', 'add',  { name: '', type: '', floor: '', description: '' });
  const handleEditLoc = (loc) => openModal('location', 'edit', loc);

  const handleDeleteLoc = (id) =>
    setConfirm({
      message: 'Delete this location entry?',
      onConfirm: () => { setLocations((p) => p.filter((l) => l.id !== id)); setConfirm(null); },
    });

  const handleSaveLoc = () => {
    if (modal.type === 'add') setLocations((p) => [...p, { ...formValues, id: Date.now() }]);
    else setLocations((p) => p.map((l) => l.id === formValues.id ? { ...formValues } : l));
    closeModal();
  };

  // ── Room actions ──────────────────────────────────────────────────────────
  const handleAddRoom  = ()     => openModal('room', 'add',  { name: '', type: '', floor: '', code: '', description: '' });
  const handleEditRoom = (room) => openModal('room', 'edit', room);

  const handleDeleteRoom = (id) =>
    setConfirm({
      message: 'Delete this room / destination?',
      onConfirm: () => { setRooms((p) => p.filter((r) => r.id !== id)); setConfirm(null); },
    });

  const handleSaveRoom = () => {
    if (modal.type === 'add') setRooms((p) => [...p, { ...formValues, id: Date.now() }]);
    else setRooms((p) => p.map((r) => r.id === formValues.id ? { ...formValues } : r));
    closeModal();
  };

  // ── Route actions ─────────────────────────────────────────────────────────
  const handleAddRoute  = ()      => openModal('route', 'add',  { name: '', x: '', y: '', connectedTo: '' });
  const handleEditRoute = (route) =>
    openModal('route', 'edit', { ...route, connectedTo: route.connectedTo?.join(', ') || '' });

  const handleDeleteRoute = (id) =>
    setConfirm({
      message: 'Delete this route point?',
      onConfirm: () => { setRoutes((p) => p.filter((r) => r.id !== id)); setConfirm(null); },
    });

  const handleSaveRoute = () => {
    const connectedTo = formValues.connectedTo
      ? String(formValues.connectedTo).split(',').map((v) => parseInt(v.trim())).filter(Boolean)
      : [];
    const data = { ...formValues, connectedTo, x: Number(formValues.x), y: Number(formValues.y) };
    if (modal.type === 'add') setRoutes((p) => [...p, { ...data, id: Date.now() }]);
    else setRoutes((p) => p.map((r) => r.id === data.id ? data : r));
    closeModal();
  };

  // ── Modal config lookup ───────────────────────────────────────────────────
  const modalConfig = (() => {
    if (!modal) return null;
    const isEdit = modal.type === 'edit';
    switch (modal.section) {
      case 'map':
        return {
          title: 'Edit Map Details',
          fields: [
            { key: 'title',        label: 'Map Title',     placeholder: 'e.g. CMC Ground Floor Map' },
            { key: 'buildingName', label: 'Building Name', placeholder: 'e.g. Central Medical Center' },
            { key: 'floor',        label: 'Floor',         placeholder: 'e.g. Ground Floor (Floor 0)' },
            { key: 'description',  label: 'Description',   type: 'textarea', placeholder: 'Brief description…' },
          ],
          onSave: handleSaveMap,
        };
      case 'location':
        return {
          title: isEdit ? 'Edit Location' : 'Add Location',
          fields: [
            { key: 'name',        label: 'Location Name', placeholder: 'e.g. Main Entrance' },
            { key: 'type',        label: 'Type',          type: 'select', options: LOCATION_TYPES },
            { key: 'floor',       label: 'Floor',         placeholder: 'e.g. 0, 1, 2…' },
            { key: 'description', label: 'Description',   type: 'textarea', placeholder: 'Brief description…' },
          ],
          onSave: handleSaveLoc,
        };
      case 'room':
        return {
          title: isEdit ? 'Edit Room / Destination' : 'Add Room / Destination',
          fields: [
            { key: 'name',        label: 'Room Name',   placeholder: 'e.g. Cardiology Clinic' },
            { key: 'code',        label: 'Room Code',   placeholder: 'e.g. CAR-201' },
            { key: 'type',        label: 'Type',        type: 'select', options: ROOM_TYPES },
            { key: 'floor',       label: 'Floor',       placeholder: 'e.g. 0, 1, 2…' },
            { key: 'description', label: 'Description', type: 'textarea', placeholder: 'Brief description…' },
          ],
          onSave: handleSaveRoom,
        };
      case 'route':
        return {
          title: isEdit ? 'Edit Route Point' : 'Add Route Point',
          fields: [
            { key: 'name',        label: 'Node Name',                            placeholder: 'e.g. Lobby Junction' },
            { key: 'x',           label: 'X Coordinate',  type: 'number',        placeholder: 'e.g. 120' },
            { key: 'y',           label: 'Y Coordinate',  type: 'number',        placeholder: 'e.g. 280' },
            { key: 'connectedTo', label: 'Connected Nodes (IDs, comma-separated)', placeholder: 'e.g. 1, 3, 4' },
          ],
          onSave: handleSaveRoute,
        };
      default:
        return null;
    }
  })();

  // ── Type label maps ───────────────────────────────────────────────────────
  const locLabel  = { entrance:'Entrance', elevator:'Elevator', stairs:'Stairs', emergency:'Emergency', pharmacy:'Pharmacy', service:'Service', other:'Other' };
  const roomLabel = { clinic:'Clinic', ward:'Ward', lab:'Lab', department:'Dept.', office:'Office', facility:'Facility', other:'Other' };

  // ─────────────────────────────────────────────────────────────────────────
  return (
    <div className="adm-wrap">

      {/* ── Header ─────────────────────────────────────────────────────── */}
      <header className="adm-header">
        <div className="adm-header-brand">
          <div className="adm-header-logo"><QuickRouteLogo size={26} /></div>
          <div>
            <div className="adm-header-name">Quick<span>Route</span></div>
            <div className="adm-header-sub">
              <ShieldIcon /> Admin Portal
            </div>
          </div>
        </div>
        <button className="adm-logout" onClick={() => navigate(ROUTES.adminOverview)}>
          <LogoutIcon /> Logout
        </button>
      </header>

      <div className="adm-body">

        {/* ── Page title ─────────────────────────────────────────────── */}
        <div className="adm-page-head">
          <h1 className="adm-page-title">Dashboard</h1>
          <p  className="adm-page-sub">Manage building maps, locations &amp; navigation data</p>
        </div>

        {/* ── Stats ─────────────────────────────────────────────────── */}
        <div className="adm-stats">
          <StatCard icon={<MapIcon />}      label="Map"       value={mapData.mapImage ? '1' : '—'} accent="#2a5298" />
          <StatCard icon={<LocationIcon />} label="Locations" value={locations.length}              accent="#2aaa8a" />
          <StatCard icon={<RoomIcon />}     label="Rooms"     value={rooms.length}                  accent="#7c5cbf" />
          <StatCard icon={<RouteIcon />}    label="Routes"    value={routes.length}                 accent="#c06030" />
        </div>

        {/* ════════════════════════════════════════════════════════════ */}
        {/* SECTION 1 — Map Management                                   */}
        {/* ════════════════════════════════════════════════════════════ */}
        <section className="adm-sec">
          <SectionHeader
            icon={<MapIcon />}
            title="Map Management"
            desc="Upload and manage the building floor plan image"
            gradient="linear-gradient(135deg, #1a3a6b, #2a5298)"
          />

          {/* Map status card */}
          {mapData.mapImage ? (
            <div className="adm-map-card adm-map-card-active">
              <div className="adm-map-thumb">
                <MapIcon />
              </div>
              <div className="adm-map-info">
                <div className="adm-map-name">{mapData.title || 'Untitled Map'}</div>
                {mapData.buildingName && (
                  <div className="adm-map-meta">{mapData.buildingName} · {mapData.floor}</div>
                )}
                {mapData.description && (
                  <div className="adm-map-desc">{mapData.description}</div>
                )}
              </div>
              <span className="adm-badge-active">Active</span>
            </div>
          ) : (
            <div className="adm-map-card adm-map-card-empty">
              <div className="adm-map-empty-icon"><MapIcon /></div>
              <div className="adm-map-empty-txt">No map uploaded</div>
              <div className="adm-map-empty-hint">Upload a building floor plan to get started</div>
            </div>
          )}

          {/* Detail chips */}
          {mapData.mapImage && mapData.buildingName && (
            <div className="adm-chips">
              <span className="adm-chip"><strong>Building:</strong> {mapData.buildingName}</span>
              <span className="adm-chip"><strong>Floor:</strong> {mapData.floor}</span>
            </div>
          )}

          {/* Actions */}
          <div className="adm-acts">
            <button className="adm-btn adm-btn-primary" onClick={handleUpload}>
              <UploadIcon /> {mapData.mapImage ? 'Replace Map' : 'Upload Map'}
            </button>
            <button className="adm-btn adm-btn-secondary" onClick={handleEditMap}>
              <EditIcon /> Edit Details
            </button>
            {mapData.mapImage && (
              <button className="adm-btn adm-btn-danger" onClick={handleDeleteMap}>
                <DeleteIcon /> Delete Map
              </button>
            )}
          </div>
        </section>

        {/* ════════════════════════════════════════════════════════════ */}
        {/* SECTION 2 — Location Management                              */}
        {/* ════════════════════════════════════════════════════════════ */}
        <section className="adm-sec">
          <SectionHeader
            icon={<LocationIcon />}
            title="Location Management"
            desc="Manage entrances, elevators, emergency rooms & service points"
            gradient="linear-gradient(135deg, #1d7a6a, #2aaa8a)"
          />

          <div className="adm-acts">
            <button className="adm-btn adm-btn-primary" onClick={handleAddLoc}>
              <AddIcon /> Add Location
            </button>
          </div>

          <div className="adm-list">
            {locations.length === 0 && (
              <div className="adm-empty">No locations yet — click Add Location to begin</div>
            )}
            {locations.map((loc) => (
              <DataRow
                key={loc.id}
                name={loc.name}
                tags={
                  <>
                    <Tag color="green">{locLabel[loc.type] || loc.type}</Tag>
                    <TagText>Floor {loc.floor}</TagText>
                  </>
                }
                onEdit={()   => handleEditLoc(loc)}
                onDelete={()  => handleDeleteLoc(loc.id)}
              />
            ))}
          </div>
        </section>

        {/* ════════════════════════════════════════════════════════════ */}
        {/* SECTION 3 — Room / Destination Management                    */}
        {/* ════════════════════════════════════════════════════════════ */}
        <section className="adm-sec">
          <SectionHeader
            icon={<RoomIcon />}
            title="Room & Destination Management"
            desc="Manage clinics, wards, labs, offices and searchable destinations"
            gradient="linear-gradient(135deg, #5c3d9b, #7c5cbf)"
          />

          <div className="adm-acts">
            <button className="adm-btn adm-btn-primary" onClick={handleAddRoom}>
              <AddIcon /> Add Room
            </button>
          </div>

          <div className="adm-list">
            {rooms.length === 0 && (
              <div className="adm-empty">No rooms yet — click Add Room to begin</div>
            )}
            {rooms.map((room) => (
              <DataRow
                key={room.id}
                name={room.name}
                tags={
                  <>
                    <Tag color="purple">{roomLabel[room.type] || room.type}</Tag>
                    <TagText>Floor {room.floor}</TagText>
                    {room.code && <TagText className="adm-code">{room.code}</TagText>}
                  </>
                }
                onEdit={()   => handleEditRoom(room)}
                onDelete={()  => handleDeleteRoom(room.id)}
              />
            ))}
          </div>
        </section>

        {/* ════════════════════════════════════════════════════════════ */}
        {/* SECTION 4 — Route / Navigation Data                          */}
        {/* ════════════════════════════════════════════════════════════ */}
        <section className="adm-sec">
          <SectionHeader
            icon={<RouteIcon />}
            title="Route & Navigation Data"
            desc="Manage navigation nodes and path connections for wayfinding"
            gradient="linear-gradient(135deg, #9a4020, #c06030)"
          />

          <div className="adm-acts">
            <button className="adm-btn adm-btn-primary" onClick={handleAddRoute}>
              <AddIcon /> Add Route Point
            </button>
          </div>

          <div className="adm-list">
            {routes.length === 0 && (
              <div className="adm-empty">No route points yet — click Add Route Point to begin</div>
            )}
            {routes.map((route) => (
              <DataRow
                key={route.id}
                name={route.name}
                tags={
                  <>
                    <Tag color="orange">Node #{route.id}</Tag>
                    <TagText>({route.x}, {route.y})</TagText>
                    {route.connectedTo?.length > 0 && (
                      <TagText>→ [{route.connectedTo.join(', ')}]</TagText>
                    )}
                  </>
                }
                onEdit={()   => handleEditRoute(route)}
                onDelete={()  => handleDeleteRoute(route.id)}
              />
            ))}
          </div>
        </section>

        {/* ── Footer ─────────────────────────────────────────────────── */}
        <footer className="adm-footer">
          <div className="adm-footer-brand">Quick<span>Route</span> Admin</div>
          <div className="adm-footer-note">
            Data is stored in-memory — connect to backend for persistence
          </div>
        </footer>

      </div>{/* /adm-body */}

      {/* ── Modal ──────────────────────────────────────────────────────── */}
      {modal && modalConfig && (
        <ModalForm
          title={modalConfig.title}
          fields={modalConfig.fields}
          values={formValues}
          onChange={setField}
          onSave={modalConfig.onSave}
          onCancel={closeModal}
        />
      )}

      {/* ── Confirm ────────────────────────────────────────────────────── */}
      {confirm && (
        <ConfirmModal
          message={confirm.message}
          onConfirm={confirm.onConfirm}
          onCancel={() => setConfirm(null)}
        />
      )}

    </div>
  );
};

export default AdminDashboard;
