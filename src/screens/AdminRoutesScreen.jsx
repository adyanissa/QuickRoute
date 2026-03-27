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

const UI = {
  en: {
    title: 'Route Points',
    back: 'Back',
    addBtn: 'Add Route Point',
    addTitle: 'Add Route Point',
    editTitle: 'Edit Route Point',
    section: 'Navigation Nodes',
    fields: {
      name: 'Node Name', floor: 'Floor', x: 'X Coordinate', y: 'Y Coordinate',
      connectedTo: 'Connected To (IDs, comma-separated)',
    },
    save: 'Save', cancel: 'Cancel',
    confirmDelete: 'Delete this route point?',
    yes: 'Yes, Delete',
    empty: 'No route points yet',
    emptyHint: 'Tap "Add Route Point" to create one',
    count: (n) => `${n} node${n !== 1 ? 's' : ''}`,
    nodeLabel: 'Node',
    coordLabel: 'Coords',
    connectLabel: 'Connects to',
  },
  ar: {
    title: 'نقاط المسار',
    back: 'رجوع',
    addBtn: 'إضافة نقطة مسار',
    addTitle: 'إضافة نقطة مسار',
    editTitle: 'تعديل نقطة مسار',
    section: 'عقد التنقل',
    fields: {
      name: 'اسم العقدة', floor: 'الطابق', x: 'إحداثي X', y: 'إحداثي Y',
      connectedTo: 'متصل بـ (معرفات مفصولة بفاصلة)',
    },
    save: 'حفظ', cancel: 'إلغاء',
    confirmDelete: 'حذف نقطة المسار هذه؟',
    yes: 'نعم، احذف',
    empty: 'لا توجد نقاط مسار',
    emptyHint: 'اضغط "إضافة نقطة مسار" للإنشاء',
    count: (n) => `${n} نقطة`,
    nodeLabel: 'عقدة',
    coordLabel: 'إحداثيات',
    connectLabel: 'متصل بـ',
  },
  he: {
    title: 'נקודות מסלול',
    back: 'חזרה',
    addBtn: 'הוסף נקודת מסלול',
    addTitle: 'הוסף נקודת מסלול',
    editTitle: 'ערוך נקודת מסלול',
    section: 'צמתי ניווט',
    fields: {
      name: 'שם צומת', floor: 'קומה', x: 'קואורדינטה X', y: 'קואורדינטה Y',
      connectedTo: 'מחובר ל (מזהים, מופרדים בפסיק)',
    },
    save: 'שמור', cancel: 'ביטול',
    confirmDelete: 'למחוק נקודת מסלול זו?',
    yes: 'כן, מחק',
    empty: 'אין נקודות מסלול',
    emptyHint: 'לחץ "הוסף נקודת מסלול" ליצירה',
    count: (n) => `${n} נקודות`,
    nodeLabel: 'צומת',
    coordLabel: 'קואורד',
    connectLabel: 'מחובר ל',
  },
};

const BackArrow = ({ flip }) => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none"
    style={flip ? { transform: 'scaleX(-1)' } : undefined}>
    <path d="M19 12H5M11 18l-6-6 6-6" stroke="currentColor" strokeWidth="2.2"
      strokeLinecap="round" strokeLinejoin="round"/>
  </svg>
);

const RouteIcon = () => (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
    <circle cx="6" cy="6" r="3" stroke="currentColor" strokeWidth="1.8"/>
    <circle cx="18" cy="18" r="3" stroke="currentColor" strokeWidth="1.8"/>
    <path d="M9 6h3a3 3 0 0 1 3 3v6a3 3 0 0 0 3 3"
      stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"/>
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

const EMPTY_ROUTE = { id: '', name: '', floor: 0, x: 0, y: 0, connectedTo: [] };

// ── AdminRoutesScreen ─────────────────────────────────────────────────────────
const AdminRoutesScreen = () => {
  const { lang, setLang } = useLang();
  const navigate          = useNavigate();
  const { routePoints, addRoute, updateRoute, deleteRoute } = useAdmin();

  const isRTL = lang === 'ar' || lang === 'he';
  const t     = UI[lang];

  const [view,      setView]      = useState('list');
  const [form,      setForm]      = useState({ ...EMPTY_ROUTE, connectedTo: '' });
  const [confirmId, setConfirmId] = useState(null);

  const setField = (k, v) => setForm((p) => ({ ...p, [k]: v }));

  const openAdd = () => {
    setForm({ ...EMPTY_ROUTE, id: `rt-${Date.now()}`, connectedTo: '' });
    setView('add');
  };

  const openEdit = (r) => {
    setForm({ ...r, connectedTo: (r.connectedTo || []).join(', ') });
    setView('edit');
  };

  const handleSave = () => {
    const connectedTo = String(form.connectedTo || '')
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean);
    const entry = { ...form, connectedTo, floor: Number(form.floor), x: Number(form.x), y: Number(form.y) };
    if (view === 'add') addRoute(entry);
    else updateRoute(entry);
    setView('list');
  };

  const handleDelete = (id) => {
    deleteRoute(id);
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
            <div className="adm-inner-icon"><RouteIcon /></div>
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
              <div className="adm-btn-row">
                <button className="adm-btn adm-btn-primary" onClick={openAdd}>
                  <AddIcon /> {t.addBtn}
                </button>
              </div>

              <div className="adm-section-row">
                <span className="adm-section-lbl">{t.section}</span>
                <span className="adm-section-count">{t.count(routePoints.length)}</span>
              </div>

              {routePoints.length === 0 ? (
                <div className="adm-empty">
                  <div className="adm-empty-icon"><RouteIcon /></div>
                  <div className="adm-empty-txt">{t.empty}</div>
                  <div className="adm-empty-hint">{t.emptyHint}</div>
                </div>
              ) : (
                <div className="adm-list">
                  {routePoints.map((r) => (
                    <div key={r.id} className="adm-list-item">
                      <div className="adm-list-item-row">
                        <div className="adm-list-item-info">
                          <div className="adm-list-item-name">{r.name}</div>
                          <div className="adm-list-item-meta">
                            <span className="adm-tag adm-tag-orange">{t.nodeLabel} {r.id}</span>
                            <span className="adm-tag-txt">({r.x}, {r.y})</span>
                            {r.connectedTo?.length > 0 && (
                              <span className="adm-tag-txt">
                                → [{r.connectedTo.join(', ')}]
                              </span>
                            )}
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
              </div>

              <div className="adm-form-group">
                <label className="adm-form-label">{t.fields.name}</label>
                <input className="adm-form-input" value={form.name || ''}
                  onChange={(e) => setField('name', e.target.value)}
                  placeholder="e.g. Lobby Junction" />
              </div>

              <div className="adm-form-row">
                <div className="adm-form-group">
                  <label className="adm-form-label">{t.fields.x}</label>
                  <input className="adm-form-input" type="number" value={form.x ?? 0}
                    onChange={(e) => setField('x', e.target.value)}
                    placeholder="120" />
                </div>
                <div className="adm-form-group">
                  <label className="adm-form-label">{t.fields.y}</label>
                  <input className="adm-form-input" type="number" value={form.y ?? 0}
                    onChange={(e) => setField('y', e.target.value)}
                    placeholder="280" />
                </div>
              </div>

              <div className="adm-form-row">
                <div className="adm-form-group">
                  <label className="adm-form-label">{t.fields.floor}</label>
                  <input className="adm-form-input" type="number" value={form.floor ?? 0}
                    onChange={(e) => setField('floor', e.target.value)}
                    placeholder="0" />
                </div>
                <div className="adm-form-group">
                  <label className="adm-form-label">{t.fields.connectedTo}</label>
                  <input className="adm-form-input"
                    value={form.connectedTo || ''}
                    onChange={(e) => setField('connectedTo', e.target.value)}
                    placeholder="rt-1, rt-2" />
                </div>
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

export default AdminRoutesScreen;
