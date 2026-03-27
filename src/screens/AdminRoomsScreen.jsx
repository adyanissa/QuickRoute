import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useLang } from '../context/LangContext';
import { useAdmin } from '../context/AdminContext';
import '../styles/adminScreens.css';

const LANGUAGES = [
  { code: 'ar', label: 'عربي' },
  { code: 'he', label: 'עברית' },
  { code: 'en', label: 'EN' },
];

const ROOM_TYPES = [
  'emergency','room','clinic','office','lab','waiting_area',
  'reception','imaging','pharmacy','operating',
];

const UI = {
  en: {
    title: 'Rooms & Destinations',
    back: 'Back',
    selectBuilding: 'Select Building',
    allBuildings: 'All',
    addBtn: 'Add Room',
    addTitle: 'Add Room / Destination',
    editTitle: 'Edit Room / Destination',
    section: 'Rooms',
    fields: {
      name: 'Room Name', type: 'Type',
      floor: 'Floor', description: 'Description',
    },
    save: 'Save', cancel: 'Cancel',
    confirmDelete: 'Delete this room?',
    yes: 'Yes, Delete',
    empty: 'No rooms for this building',
    emptyHint: 'Tap "Add Room" to create one',
    count: (n) => `${n} room${n !== 1 ? 's' : ''}`,
    floor: 'Floor',
  },
  ar: {
    title: 'الغرف والوجهات',
    back: 'رجوع',
    selectBuilding: 'اختر المبنى',
    allBuildings: 'الكل',
    addBtn: 'إضافة غرفة',
    addTitle: 'إضافة غرفة / وجهة',
    editTitle: 'تعديل غرفة / وجهة',
    section: 'الغرف',
    fields: { name: 'اسم الغرفة', type: 'النوع', floor: 'الطابق', description: 'الوصف' },
    save: 'حفظ', cancel: 'إلغاء',
    confirmDelete: 'حذف هذه الغرفة؟',
    yes: 'نعم، احذف',
    empty: 'لا توجد غرف لهذا المبنى',
    emptyHint: 'اضغط "إضافة غرفة" للإنشاء',
    count: (n) => `${n} غرفة`,
    floor: 'طابق',
  },
  he: {
    title: 'חדרים ויעדים',
    back: 'חזרה',
    selectBuilding: 'בחר מבנה',
    allBuildings: 'הכל',
    addBtn: 'הוסף חדר',
    addTitle: 'הוסף חדר / יעד',
    editTitle: 'ערוך חדר / יעד',
    section: 'חדרים',
    fields: { name: 'שם חדר', type: 'סוג', floor: 'קומה', description: 'תיאור' },
    save: 'שמור', cancel: 'ביטול',
    confirmDelete: 'למחוק חדר זה?',
    yes: 'כן, מחק',
    empty: 'אין חדרים למבנה זה',
    emptyHint: 'לחץ "הוסף חדר" ליצירה',
    count: (n) => `${n} חדרים`,
    floor: 'קומה',
  },
};

const TYPE_COLOR = {
  emergency: 'adm-tag-red', room: 'adm-tag-blue', clinic: 'adm-tag-green',
  office: 'adm-tag-blue', lab: 'adm-tag-purple', waiting_area: 'adm-tag-orange',
  reception: 'adm-tag-blue', imaging: 'adm-tag-purple', pharmacy: 'adm-tag-green',
  operating: 'adm-tag-red',
};

const BackArrow = ({ flip }) => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none"
    style={flip ? { transform: 'scaleX(-1)' } : undefined}>
    <path d="M19 12H5M11 18l-6-6 6-6" stroke="currentColor" strokeWidth="2.2"
      strokeLinecap="round" strokeLinejoin="round"/>
  </svg>
);

const RoomIcon = () => (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
    <rect x="3" y="3" width="18" height="18" rx="2" stroke="currentColor" strokeWidth="1.8"/>
    <path d="M9 3v18M3 9h6M3 15h6" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"/>
  </svg>
);

const AddIcon = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
    <line x1="12" y1="5" x2="12" y2="19" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round"/>
    <line x1="5" y1="12" x2="19" y2="12" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round"/>
  </svg>
);

const EditIcon = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
    <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"
      stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
    <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"
      stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
  </svg>
);

const DeleteIcon = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
    <polyline points="3 6 5 6 21 6" stroke="currentColor" strokeWidth="2" strokeLinecap="round"/>
    <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6M10 11v6M14 11v6M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"
      stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
  </svg>
);

const EMPTY_ROOM = { id: '', name: '', type: 'clinic', floor: 0, description: '' };

// ── AdminRoomsScreen ──────────────────────────────────────────────────────────
const AdminRoomsScreen = () => {
  const { lang, setLang } = useLang();
  const navigate          = useNavigate();
  const { buildings, rooms, addRoom, updateRoom, deleteRoom } = useAdmin();

  const isRTL = lang === 'ar' || lang === 'he';
  const t     = UI[lang];

  const [selectedBldId, setSelectedBldId] = useState(buildings[0]?.id ?? null);
  const [view,          setView]          = useState('list');
  const [form,          setForm]          = useState({ ...EMPTY_ROOM });
  const [confirmId,     setConfirmId]     = useState(null);

  const currentRooms = selectedBldId ? (rooms[selectedBldId] || []) : [];
  const currentBld   = buildings.find((b) => b.id === selectedBldId);

  const setField = (k, v) => setForm((p) => ({ ...p, [k]: v }));

  const openAdd = () => {
    setForm({ ...EMPTY_ROOM, id: `rm-${Date.now()}` });
    setView('add');
  };

  const openEdit = (r) => {
    setForm({ ...r });
    setView('edit');
  };

  const handleSave = () => {
    if (!selectedBldId) return;
    const entry = { ...form, floor: Number(form.floor) };
    if (view === 'add') addRoom(selectedBldId, entry);
    else updateRoom(selectedBldId, entry);
    setView('list');
  };

  const handleDelete = (id) => {
    if (!selectedBldId) return;
    deleteRoom(selectedBldId, id);
    setConfirmId(null);
  };

  return (
    <div className="layout-wrapper">
      <div className="layout-shell adm-shell" dir={isRTL ? 'rtl' : 'ltr'}>

        {/* ── Header ──────────────────────────────────────────────────── */}
        <div className="adm-inner-header">
          <div className="adm-topbar">
            <button
              className={`adm-back-btn${isRTL ? ' adm-back-btn-rtl' : ''}`}
              onClick={() => view !== 'list' ? setView('list') : navigate('/screen/05')}
            >
              <BackArrow flip={isRTL} />
              {t.back}
            </button>
            <div className="adm-lang-pill" role="group">
              {LANGUAGES.map((l) => (
                <button key={l.code}
                  className={`adm-lang-btn${lang === l.code ? ' active' : ''}`}
                  onClick={() => setLang(l.code)}>
                  {l.label}
                </button>
              ))}
            </div>
          </div>
          <div className="adm-inner-heading">
            <div className="adm-inner-icon"><RoomIcon /></div>
            <h1 className="adm-inner-title">
              {view === 'add' ? t.addTitle : view === 'edit' ? t.editTitle : t.title}
            </h1>
          </div>
        </div>

        {/* ── Content ─────────────────────────────────────────────────── */}
        <div className="adm-content">

          {/* ── List view ── */}
          {view === 'list' && (
            <>
              {/* Building selector tabs */}
              <div className="adm-building-tabs">
                {buildings.map((b) => (
                  <button
                    key={b.id}
                    className={`adm-building-tab${selectedBldId === b.id ? ' active' : ''}`}
                    style={selectedBldId === b.id
                      ? { background: `linear-gradient(135deg, ${b.iconColor}cc, ${b.iconColor})` }
                      : {}}
                    onClick={() => { setSelectedBldId(b.id); setConfirmId(null); }}
                  >
                    {b.tag}
                  </button>
                ))}
              </div>

              {/* Building label */}
              {currentBld && (
                <div className="adm-section-row">
                  <span className="adm-section-lbl">{currentBld.nameEn}</span>
                  <span className="adm-section-count">{t.count(currentRooms.length)}</span>
                </div>
              )}

              <div className="adm-btn-row">
                <button className="adm-btn adm-btn-primary" onClick={openAdd}
                  disabled={!selectedBldId}>
                  <AddIcon /> {t.addBtn}
                </button>
              </div>

              {currentRooms.length === 0 ? (
                <div className="adm-empty">
                  <div className="adm-empty-icon"><RoomIcon /></div>
                  <div className="adm-empty-txt">{t.empty}</div>
                  <div className="adm-empty-hint">{t.emptyHint}</div>
                </div>
              ) : (
                <div className="adm-list">
                  {currentRooms.map((r) => (
                    <div key={r.id} className="adm-list-item">
                      <div className="adm-list-item-row">
                        <div className="adm-list-item-info">
                          <div className="adm-list-item-name">{r.name}</div>
                          <div className="adm-list-item-meta">
                            <span className={`adm-tag ${TYPE_COLOR[r.type] || 'adm-tag-blue'}`}>
                              {r.type.replace('_', ' ')}
                            </span>
                            <span className="adm-tag-txt">{t.floor} {r.floor}</span>
                          </div>
                        </div>
                        <div className="adm-list-item-acts">
                          <button className="adm-icon-btn" onClick={() => openEdit(r)}>
                            <EditIcon />
                          </button>
                          <button className="adm-icon-btn adm-icon-btn-danger"
                            onClick={() => setConfirmId(confirmId === r.id ? null : r.id)}>
                            <DeleteIcon />
                          </button>
                        </div>
                      </div>

                      {confirmId === r.id && (
                        <div className="adm-delete-strip">
                          <span className="adm-delete-strip-msg">{t.confirmDelete}</span>
                          <div className="adm-delete-strip-acts">
                            <button className="adm-btn adm-btn-cancel"
                              style={{ padding: '5px 12px', fontSize: 12 }}
                              onClick={() => setConfirmId(null)}>
                              {t.cancel}
                            </button>
                            <button className="adm-btn adm-btn-confirm-delete"
                              style={{ padding: '5px 12px', fontSize: 12 }}
                              onClick={() => handleDelete(r.id)}>
                              {t.yes}
                            </button>
                          </div>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </>
          )}

          {/* ── Add / Edit form ── */}
          {(view === 'add' || view === 'edit') && (
            <div className="adm-form-card">
              <div className="adm-form-card-title">
                {view === 'add' ? t.addTitle : t.editTitle}
                {currentBld && (
                  <span style={{ fontSize: 12, color: '#8aaacb', fontWeight: 600,
                    marginLeft: 8, marginRight: 8 }}>
                    — {currentBld.nameEn}
                  </span>
                )}
              </div>

              <div className="adm-form-group">
                <label className="adm-form-label">{t.fields.name}</label>
                <input className="adm-form-input" value={form.name || ''}
                  onChange={(e) => setField('name', e.target.value)}
                  placeholder="e.g. Cardiac Emergency Unit" />
              </div>
              <div className="adm-form-row">
                <div className="adm-form-group">
                  <label className="adm-form-label">{t.fields.type}</label>
                  <select className="adm-form-select" value={form.type || 'clinic'}
                    onChange={(e) => setField('type', e.target.value)}>
                    {ROOM_TYPES.map((tp) => (
                      <option key={tp} value={tp}>{tp.replace('_', ' ')}</option>
                    ))}
                  </select>
                </div>
                <div className="adm-form-group">
                  <label className="adm-form-label">{t.fields.floor}</label>
                  <input className="adm-form-input" type="number" value={form.floor ?? 0}
                    onChange={(e) => setField('floor', e.target.value)}
                    placeholder="0" />
                </div>
              </div>
              <div className="adm-form-group">
                <label className="adm-form-label">{t.fields.description}</label>
                <textarea className="adm-form-textarea" value={form.description || ''}
                  onChange={(e) => setField('description', e.target.value)}
                  placeholder="Brief description…" />
              </div>

              <div className="adm-form-actions">
                <button className="adm-btn adm-btn-cancel" onClick={() => setView('list')}>
                  {t.cancel}
                </button>
                <button className="adm-btn adm-btn-primary" onClick={handleSave}>
                  {t.save}
                </button>
              </div>
            </div>
          )}

        </div>
      </div>
    </div>
  );
};

export default AdminRoomsScreen;
