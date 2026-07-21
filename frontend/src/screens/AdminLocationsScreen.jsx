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

const CATEGORY_OPTIONS = [
  'pediatrics','cardiology','imaging','rehabilitation','oncology','maternity',
  'neurology','general','inpatient','outpatient','surgery','research',
  'children','mri','support','logistics','warehouse','religious',
];

const UI = {
  en: {
    title: 'Locations',
    back: 'Back',
    section: 'Buildings & Centers',
    addBtn: 'Add Building',
    editTitle: 'Edit Building',
    addTitle: 'Add Building',
    fields: {
      nameEn: 'Name (English)', name: 'Name (Hebrew/Local)', subtitle: 'Subtitle / Description',
      tag: 'Short Tag', category: 'Category', iconColor: 'Icon Color (hex)',
    },
    save: 'Save', cancel: 'Cancel', delete: 'Delete',
    confirmDelete: 'Delete this building?',
    yes: 'Yes, Delete',
    empty: 'No buildings found',
    emptyHint: 'Tap "Add Building" to create one',
    count: (n) => `${n} building${n !== 1 ? 's' : ''}`,
    loading: 'Loading buildings...',
    saveError: 'Failed to save building',
    deleteError: 'Failed to delete building',
  },
  ar: {
    title: 'المواقع',
    back: 'رجوع',
    section: 'المباني والمراكز',
    addBtn: 'إضافة مبنى',
    editTitle: 'تعديل المبنى',
    addTitle: 'إضافة مبنى',
    fields: {
      nameEn: 'الاسم (إنجليزي)', name: 'الاسم (محلي)', subtitle: 'وصف قصير',
      tag: 'وسم قصير', category: 'التصنيف', iconColor: 'لون الأيقونة (hex)',
    },
    save: 'حفظ', cancel: 'إلغاء', delete: 'حذف',
    confirmDelete: 'حذف هذا المبنى؟',
    yes: 'نعم، احذف',
    empty: 'لا توجد مباني',
    emptyHint: 'اضغط "إضافة مبنى" للإنشاء',
    count: (n) => `${n} مبنى`,
    loading: 'جاري تحميل المباني...',
    saveError: 'فشل حفظ المبنى',
    deleteError: 'فشل حذف المبنى',
  },
  he: {
    title: 'מיקומים',
    back: 'חזרה',
    section: 'מבנים ומרכזים',
    addBtn: 'הוסף מבנה',
    editTitle: 'ערוך מבנה',
    addTitle: 'הוסף מבנה',
    fields: {
      nameEn: 'שם (אנגלית)', name: 'שם (עברית/מקומי)', subtitle: 'תיאור קצר',
      tag: 'תגית קצרה', category: 'קטגוריה', iconColor: 'צבע אייקון (hex)',
    },
    save: 'שמור', cancel: 'ביטול', delete: 'מחק',
    confirmDelete: 'למחוק מבנה זה?',
    yes: 'כן, מחק',
    empty: 'אין מבנים',
    emptyHint: 'לחץ "הוסף מבנה" ליצירה',
    count: (n) => `${n} מבנים`,
    loading: 'טוען מבנים...',
    saveError: 'שמירת המבנה נכשלה',
    deleteError: 'מחיקת המבנה נכשלה',
  },
};

const BackArrow = ({ flip }) => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none"
    style={flip ? { transform: 'scaleX(-1)' } : undefined}>
    <path d="M19 12H5M11 18l-6-6 6-6" stroke="currentColor" strokeWidth="2.2"
      strokeLinecap="round" strokeLinejoin="round"/>
  </svg>
);

const LocationIcon = () => (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
    <path d="M12 2C8.686 2 6 4.686 6 8c0 5.25 6 13 6 13s6-7.75 6-13c0-3.314-2.686-6-6-6z"
      stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/>
    <circle cx="12" cy="8" r="2" stroke="currentColor" strokeWidth="1.8"/>
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

const EMPTY_BUILDING = {
  id: '', nameEn: '', name: '', subtitle: '', tag: '', category: 'general', iconColor: '#2a5298',
  iconBg: 'rgba(42,82,152,0.12)',
};

// ── AdminLocationsScreen ──────────────────────────────────────────────────────
const AdminLocationsScreen = () => {
  const { lang, setLang } = useLang();
  const navigate          = useNavigate();
  const {
    buildings,
    buildingsLoading,
    addBuilding,
    updateBuilding,
    deleteBuilding,
  } = useAdmin();

  const isRTL = lang === 'ar' || lang === 'he';
  const t     = UI[lang];

  const [view,      setView]      = useState('list');  // 'list' | 'add' | 'edit'
  const [form,      setForm]      = useState({ ...EMPTY_BUILDING });
  const [confirmId, setConfirmId] = useState(null);
  const [error,     setError]     = useState('');

  const setField = (k, v) => setForm((p) => ({ ...p, [k]: v }));

  const openAdd = () => {
    setForm({ ...EMPTY_BUILDING });
    setError('');
    setView('add');
  };

  const openEdit = (b) => {
    setForm({ ...b });
    setError('');
    setView('edit');
  };

  const handleSave = async () => {
    const entry = { ...form, iconBg: `${form.iconColor}1f` };

    try {
      if (view === 'add') await addBuilding(entry);
      else await updateBuilding(entry);
      setView('list');
    } catch (err) {
      console.error('Failed to save building:', err);
      setError(err.message || t.saveError);
    }
  };

  const handleDelete = async (id) => {
    try {
      await deleteBuilding(id);
      setConfirmId(null);
    } catch (err) {
      console.error('Failed to delete building:', err);
      setError(err.message || t.deleteError);
      setConfirmId(null);
    }
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
            <div className="adm-inner-icon"><LocationIcon /></div>
            <h1 className="adm-inner-title">
              {view === 'add' ? t.addTitle : view === 'edit' ? t.editTitle : t.title}
            </h1>
          </div>
        </div>

        {/* ── Content ─────────────────────────────────────────────────── */}
        <div className="adm-content">

          {error && (
            <div style={{
              marginBottom: 16, padding: 12, borderRadius: 12,
              background: '#ffe9e9', color: '#a92323', fontSize: 14,
            }}>
              {error}
            </div>
          )}

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
                <span className="adm-section-count">{t.count(buildings.length)}</span>
              </div>

              {buildingsLoading ? (
                <div className="adm-empty">
                  <div className="adm-empty-txt">{t.loading}</div>
                </div>
              ) : buildings.length === 0 ? (
                <div className="adm-empty">
                  <div className="adm-empty-icon"><LocationIcon /></div>
                  <div className="adm-empty-txt">{t.empty}</div>
                  <div className="adm-empty-hint">{t.emptyHint}</div>
                </div>
              ) : (
                <div className="adm-list">
                  {buildings.map((b) => (
                    <div key={b.id} className="adm-list-item">
                      <div className="adm-list-item-row">
                        <div className="adm-list-item-dot"
                          style={{ background: b.iconColor, width: 12, height: 12, borderRadius: '50%' }} />
                        <div className="adm-list-item-info">
                          <div className="adm-list-item-name">{b.nameEn}</div>
                          <div className="adm-list-item-meta">
                            <span className="adm-tag adm-tag-blue">{b.tag}</span>
                            <span className="adm-tag-txt">{b.subtitle}</span>
                          </div>
                        </div>
                        <div className="adm-list-item-acts">
                          <button className="adm-icon-btn" onClick={() => openEdit(b)} title="Edit">
                            <EditIcon />
                          </button>
                          <button className="adm-icon-btn adm-icon-btn-danger"
                            onClick={() => setConfirmId(confirmId === b.id ? null : b.id)}
                            title="Delete">
                            <DeleteIcon />
                          </button>
                        </div>
                      </div>

                      {/* Inline delete confirmation */}
                      {confirmId === b.id && (
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
                              onClick={() => handleDelete(b.id)}>
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
                <label className="adm-form-label">{t.fields.nameEn}</label>
                <input className="adm-form-input" value={form.nameEn || ''}
                  onChange={(e) => setField('nameEn', e.target.value)}
                  placeholder="e.g. Heart Center" />
              </div>
              <div className="adm-form-group">
                <label className="adm-form-label">{t.fields.name}</label>
                <input className="adm-form-input" value={form.name || ''}
                  onChange={(e) => setField('name', e.target.value)}
                  placeholder="e.g. מרכז הלב" />
              </div>
              <div className="adm-form-group">
                <label className="adm-form-label">{t.fields.subtitle}</label>
                <input className="adm-form-input" value={form.subtitle || ''}
                  onChange={(e) => setField('subtitle', e.target.value)}
                  placeholder="e.g. Cardiology & cardiac surgery" />
              </div>
              <div className="adm-form-row">
                <div className="adm-form-group">
                  <label className="adm-form-label">{t.fields.tag}</label>
                  <input className="adm-form-input" value={form.tag || ''}
                    onChange={(e) => setField('tag', e.target.value)}
                    placeholder="e.g. Cardiology" />
                </div>
                <div className="adm-form-group">
                  <label className="adm-form-label">{t.fields.iconColor}</label>
                  <input className="adm-form-input" value={form.iconColor || ''}
                    onChange={(e) => setField('iconColor', e.target.value)}
                    placeholder="#2a5298" />
                </div>
              </div>
              <div className="adm-form-group">
                <label className="adm-form-label">{t.fields.category}</label>
                <select className="adm-form-select" value={form.category || ''}
                  onChange={(e) => setField('category', e.target.value)}>
                  {CATEGORY_OPTIONS.map((c) => (
                    <option key={c} value={c}>{c}</option>
                  ))}
                </select>
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

export default AdminLocationsScreen;
