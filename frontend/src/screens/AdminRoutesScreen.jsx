import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useLang } from '../context/LangContext';
import { getCurrentMap } from '../api/mapsApi';
import {
  getRoutePoints,
  createRoutePoint,
  updateRoutePoint,
  deleteRoutePoint,
} from '../api/routePointsApi';
import '../styles/adminScreens.css';

const LANGUAGES = [
  { code: 'ar', label: 'عربي' },
  { code: 'he', label: 'עברית' },
  { code: 'en', label: 'EN' },
];

const UI = {
  en: {
    title: 'Route Points',
    back: 'Back',
    addBtn: 'Add Route Point',
    addTitle: 'Add Route Point',
    editTitle: 'Edit Route Point',
    section: 'Navigation Nodes',

    fields: {
      name: 'Node Name',
      pointType: 'Point Type',
      floor: 'Floor',
      x: 'X Coordinate',
      y: 'Y Coordinate',
      accessible: 'Accessible',
    },

    save: 'Save',
    cancel: 'Cancel',
    loading: 'Loading route points...',
    loadError: 'Failed to load route points',
    saveError: 'Failed to save route point',
    deleteError: 'Failed to delete route point',

    confirmDelete: 'Delete this route point?',
    yes: 'Yes, Delete',

    empty: 'No routes found',
    emptyHint: 'Tap "Add Route Point" to create one',

    count: (n) => `${n} node${n !== 1 ? 's' : ''}`,
    nodeLabel: 'Node',
    floorLabel: 'Floor',
    noMap: 'No map set up yet',
    noMapHint: 'Upload a map in Map Management first',
  },

  ar: {
    title: 'نقاط المسار',
    back: 'رجوع',
    addBtn: 'إضافة نقطة مسار',
    addTitle: 'إضافة نقطة مسار',
    editTitle: 'تعديل نقطة مسار',
    section: 'عقد التنقل',

    fields: {
      name: 'اسم العقدة',
      pointType: 'نوع النقطة',
      floor: 'الطابق',
      x: 'إحداثي X',
      y: 'إحداثي Y',
      accessible: 'متاحة لذوي الاحتياجات',
    },

    save: 'حفظ',
    cancel: 'إلغاء',
    loading: 'جاري تحميل نقاط المسار...',
    loadError: 'فشل تحميل نقاط المسار',
    saveError: 'فشل حفظ نقطة المسار',
    deleteError: 'فشل حذف نقطة المسار',

    confirmDelete: 'حذف نقطة المسار هذه؟',
    yes: 'نعم، احذف',

    empty: 'لا توجد مسارات',
    emptyHint: 'اضغط "إضافة نقطة مسار" للإنشاء',

    count: (n) => `${n} نقطة`,
    nodeLabel: 'عقدة',
    floorLabel: 'طابق',
    noMap: 'لا توجد خريطة بعد',
    noMapHint: 'ارفع خريطة في إدارة الخريطة أولاً',
  },

  he: {
    title: 'נקודות מסלול',
    back: 'חזרה',
    addBtn: 'הוסף נקודת מסלול',
    addTitle: 'הוסף נקודת מסלול',
    editTitle: 'ערוך נקודת מסלול',
    section: 'צמתי ניווט',

    fields: {
      name: 'שם צומת',
      pointType: 'סוג נקודה',
      floor: 'קומה',
      x: 'קואורדינטה X',
      y: 'קואורדינטה Y',
      accessible: 'נגיש',
    },

    save: 'שמור',
    cancel: 'ביטול',
    loading: 'טוען נקודות מסלול...',
    loadError: 'טעינת נקודות המסלול נכשלה',
    saveError: 'שמירת נקודת המסלול נכשלה',
    deleteError: 'מחיקת נקודת המסלול נכשלה',

    confirmDelete: 'למחוק נקודת מסלול זו?',
    yes: 'כן, מחק',

    empty: 'לא נמצאו מסלולים',
    emptyHint: 'לחץ "הוסף נקודת מסלול" ליצירה',

    count: (n) => `${n} נקודות`,
    nodeLabel: 'צומת',
    floorLabel: 'קומה',
    noMap: 'עדיין לא הוגדרה מפה',
    noMapHint: 'העלה מפה תחת ניהול מפה תחילה',
  },
};

const BackArrow = ({ flip }) => (
  <svg
    width="15"
    height="15"
    viewBox="0 0 24 24"
    fill="none"
    style={flip ? { transform: 'scaleX(-1)' } : undefined}
  >
    <path
      d="M19 12H5M11 18l-6-6 6-6"
      stroke="currentColor"
      strokeWidth="2.2"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);

const RouteIcon = () => (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
    <circle
      cx="6"
      cy="6"
      r="3"
      stroke="currentColor"
      strokeWidth="1.8"
    />

    <circle
      cx="18"
      cy="18"
      r="3"
      stroke="currentColor"
      strokeWidth="1.8"
    />

    <path
      d="M9 6h3a3 3 0 0 1 3 3v6a3 3 0 0 0 3 3"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
    />
  </svg>
);

const AddIcon = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
    <line
      x1="12"
      y1="5"
      x2="12"
      y2="19"
      stroke="currentColor"
      strokeWidth="2.2"
      strokeLinecap="round"
    />

    <line
      x1="5"
      y1="12"
      x2="19"
      y2="12"
      stroke="currentColor"
      strokeWidth="2.2"
      strokeLinecap="round"
    />
  </svg>
);

const EditIcon = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
    <path
      d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    />

    <path
      d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);

const DeleteIcon = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
    <polyline
      points="3 6 5 6 21 6"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
    />

    <path
      d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6M10 11v6M14 11v6M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);

const EMPTY_ROUTE = {
  name: '',
  point_type: 'hallway',
  floor: 0,
  x: 0,
  y: 0,
  is_accessible: true,
};

const AdminRoutesScreen = () => {
  const { lang, setLang } = useLang();
  const navigate = useNavigate();

  const isRTL = lang === 'ar' || lang === 'he';
  const t = UI[lang];

  const [routePoints, setRoutePoints] = useState([]);

  const [view, setView] = useState('list');

  const [form, setForm] = useState({
    ...EMPTY_ROUTE,
  });

  const [confirmId, setConfirmId] = useState(null);

  const [loading, setLoading] = useState(true);

  const [error, setError] = useState('');

  const [currentMapId, setCurrentMapId] = useState(null);
  const [mapLoading, setMapLoading] = useState(true);

  const setField = (key, value) => {
    setForm((previous) => ({
      ...previous,
      [key]: value,
    }));
  };

  const loadRoutePoints = async (mapId) => {
    try {
      setLoading(true);
      setError('');

      const data = await getRoutePoints({ map_id: mapId });

      setRoutePoints(data);
    } catch (err) {
      console.error(err);
      setError(t.loadError);
    } finally {
      setLoading(false);
    }
  };

  // The current map is no longer a hardcoded id - it's whatever map is
  // marked as current in the backend (set from Map Management).
  useEffect(() => {
    const loadCurrentMapId = async () => {
      setMapLoading(true);

      try {
        const data = await getCurrentMap();
        setCurrentMapId(data?.id ?? null);
      } catch (err) {
        console.error('Failed to load current map:', err);
        setCurrentMapId(null);
      } finally {
        setMapLoading(false);
      }
    };

    loadCurrentMapId();
  }, []);

  useEffect(() => {
    if (currentMapId) {
      loadRoutePoints(currentMapId);
    } else {
      setRoutePoints([]);
      setLoading(false);
    }
  }, [currentMapId]);

  const openAdd = () => {
    setForm({
      ...EMPTY_ROUTE,
    });

    setError('');
    setView('add');
  };

  const openEdit = (routePoint) => {
    setForm({
      id: routePoint.id,
      name: routePoint.name,
      point_type: routePoint.point_type,
      floor: routePoint.floor,
      x: routePoint.x,
      y: routePoint.y,
      is_accessible: routePoint.is_accessible,
    });

    setError('');
    setView('edit');
  };

  const handleSave = async () => {
    if (!currentMapId) return;

    try {
      setError('');

      const payload = {
        map_id: currentMapId,
        name: form.name.trim(),
        point_type: form.point_type,
        x: Number(form.x),
        y: Number(form.y),
        floor: Number(form.floor),
        building_id: null,
        room_id: null,
        is_accessible: Boolean(form.is_accessible),
      };

      if (view === 'add') {
        await createRoutePoint(payload);
      } else {
        await updateRoutePoint(form.id, payload);
      }

      await loadRoutePoints(currentMapId);

      setView('list');
    } catch (err) {
      console.error(err);
      setError(t.saveError);
    }
  };

  const handleDelete = async (id) => {
    try {
      setError('');

      await deleteRoutePoint(id);

      setConfirmId(null);

      await loadRoutePoints(currentMapId);
    } catch (err) {
      console.error(err);
      setError(t.deleteError);
    }
  };

  return (
    <div className="layout-wrapper">
      <div
        className="layout-shell adm-shell"
        dir={isRTL ? 'rtl' : 'ltr'}
      >
        <div className="adm-inner-header">
          <div className="adm-topbar">
            <button
              className={`adm-back-btn${
                isRTL ? ' adm-back-btn-rtl' : ''
              }`}
              onClick={() =>
                view !== 'list'
                  ? setView('list')
                  : navigate('/screen/05')
              }
            >
              <BackArrow flip={isRTL} />
              {t.back}
            </button>

            <div
              className="adm-lang-pill"
              role="group"
            >
              {LANGUAGES.map((language) => (
                <button
                  key={language.code}
                  className={`adm-lang-btn${
                    lang === language.code
                      ? ' active'
                      : ''
                  }`}
                  onClick={() =>
                    setLang(language.code)
                  }
                >
                  {language.label}
                </button>
              ))}
            </div>
          </div>

          <div className="adm-inner-heading">
            <div className="adm-inner-icon">
              <RouteIcon />
            </div>

            <h1 className="adm-inner-title">
              {view === 'add'
                ? t.addTitle
                : view === 'edit'
                  ? t.editTitle
                  : t.title}
            </h1>
          </div>
        </div>

        <div className="adm-content">
          {error && (
            <div
              style={{
                marginBottom: 16,
                padding: 12,
                borderRadius: 12,
                background: '#ffe9e9',
                color: '#a92323',
                fontSize: 14,
              }}
            >
              {error}
            </div>
          )}

          {view === 'list' && mapLoading && (
            <div className="adm-empty">
              <div className="adm-empty-txt">{t.loading}</div>
            </div>
          )}

          {view === 'list' && !mapLoading && !currentMapId && (
            <div className="adm-empty">
              <div className="adm-empty-icon">
                <RouteIcon />
              </div>
              <div className="adm-empty-txt">{t.noMap}</div>
              <div className="adm-empty-hint">{t.noMapHint}</div>
            </div>
          )}

          {view === 'list' && !mapLoading && currentMapId && (
            <>
              <div className="adm-btn-row">
                <button
                  className="adm-btn adm-btn-primary"
                  onClick={openAdd}
                >
                  <AddIcon />
                  {t.addBtn}
                </button>
              </div>

              <div className="adm-section-row">
                <span className="adm-section-lbl">
                  {t.section}
                </span>

                <span className="adm-section-count">
                  {t.count(routePoints.length)}
                </span>
              </div>

              {loading ? (
                <div className="adm-empty">
                  <div className="adm-empty-txt">
                    {t.loading}
                  </div>
                </div>
              ) : routePoints.length === 0 ? (
                <div className="adm-empty">
                  <div className="adm-empty-icon">
                    <RouteIcon />
                  </div>

                  <div className="adm-empty-txt">
                    {t.empty}
                  </div>

                  <div className="adm-empty-hint">
                    {t.emptyHint}
                  </div>
                </div>
              ) : (
                <div className="adm-list">
                  {routePoints.map((routePoint) => (
                    <div
                      key={routePoint.id}
                      className="adm-list-item"
                    >
                      <div className="adm-list-item-row">
                        <div className="adm-list-item-info">
                          <div className="adm-list-item-name">
                            {routePoint.name}
                          </div>

                          <div className="adm-list-item-meta">
                            <span className="adm-tag adm-tag-orange">
                              {routePoint.point_type}
                            </span>

                            <span className="adm-tag-txt">
                              ({routePoint.x}, {routePoint.y})
                            </span>

                            <span className="adm-tag-txt">
                              {t.floorLabel}: {routePoint.floor}
                            </span>
                          </div>
                        </div>

                        <div className="adm-list-item-acts">
                          <button
                            className="adm-icon-btn"
                            onClick={() =>
                              openEdit(routePoint)
                            }
                          >
                            <EditIcon />
                          </button>

                          <button
                            className="adm-icon-btn adm-icon-btn-danger"
                            onClick={() =>
                              setConfirmId(
                                confirmId === routePoint.id
                                  ? null
                                  : routePoint.id
                              )
                            }
                          >
                            <DeleteIcon />
                          </button>
                        </div>
                      </div>

                      {confirmId === routePoint.id && (
                        <div className="adm-delete-strip">
                          <span className="adm-delete-strip-msg">
                            {t.confirmDelete}
                          </span>

                          <div className="adm-delete-strip-acts">
                            <button
                              className="adm-btn adm-btn-cancel"
                              style={{
                                padding: '5px 12px',
                                fontSize: 12,
                              }}
                              onClick={() =>
                                setConfirmId(null)
                              }
                            >
                              {t.cancel}
                            </button>

                            <button
                              className="adm-btn adm-btn-confirm-delete"
                              style={{
                                padding: '5px 12px',
                                fontSize: 12,
                              }}
                              onClick={() =>
                                handleDelete(routePoint.id)
                              }
                            >
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

          {(view === 'add' || view === 'edit') && (
            <div className="adm-form-card">
              <div className="adm-form-card-title">
                {view === 'add'
                  ? t.addTitle
                  : t.editTitle}
              </div>

              <div className="adm-form-group">
                <label className="adm-form-label">
                  {t.fields.name}
                </label>

                <input
                  className="adm-form-input"
                  value={form.name || ''}
                  onChange={(event) =>
                    setField('name', event.target.value)
                  }
                  placeholder="e.g. Main Entrance"
                />
              </div>

              <div className="adm-form-group">
                <label className="adm-form-label">
                  {t.fields.pointType}
                </label>

                <select
                  className="adm-form-input"
                  value={form.point_type}
                  onChange={(event) =>
                    setField(
                      'point_type',
                      event.target.value
                    )
                  }
                >
                  <option value="entrance">
                    entrance
                  </option>

                  <option value="hallway">
                    hallway
                  </option>

                  <option value="stairs">
                    stairs
                  </option>

                  <option value="elevator">
                    elevator
                  </option>

                  <option value="room">
                    room
                  </option>
                </select>
              </div>

              <div className="adm-form-row">
                <div className="adm-form-group">
                  <label className="adm-form-label">
                    {t.fields.x}
                  </label>

                  <input
                    className="adm-form-input"
                    type="number"
                    value={form.x ?? 0}
                    onChange={(event) =>
                      setField('x', event.target.value)
                    }
                  />
                </div>

                <div className="adm-form-group">
                  <label className="adm-form-label">
                    {t.fields.y}
                  </label>

                  <input
                    className="adm-form-input"
                    type="number"
                    value={form.y ?? 0}
                    onChange={(event) =>
                      setField('y', event.target.value)
                    }
                  />
                </div>
              </div>

              <div className="adm-form-group">
                <label className="adm-form-label">
                  {t.fields.floor}
                </label>

                <input
                  className="adm-form-input"
                  type="number"
                  value={form.floor ?? 0}
                  onChange={(event) =>
                    setField('floor', event.target.value)
                  }
                />
              </div>

              <div className="adm-form-group">
                <label
                  className="adm-form-label"
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 8,
                  }}
                >
                  <input
                    type="checkbox"
                    checked={Boolean(
                      form.is_accessible
                    )}
                    onChange={(event) =>
                      setField(
                        'is_accessible',
                        event.target.checked
                      )
                    }
                  />

                  {t.fields.accessible}
                </label>
              </div>

              <div className="adm-form-actions">
                <button
                  className="adm-btn adm-btn-cancel"
                  onClick={() =>
                    setView('list')
                  }
                >
                  {t.cancel}
                </button>

                <button
                  className="adm-btn adm-btn-primary"
                  onClick={handleSave}
                  disabled={!form.name.trim()}
                >
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

export default AdminRoutesScreen;