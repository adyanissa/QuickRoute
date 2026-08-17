import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import AdminScreenHeader from '../components/dashboard/AdminScreenHeader';
import { useLang } from '../context/LangContext';
import { useAdmin } from '../context/AdminContext';
import { useAuth } from '../context/AuthContext';
import { canCreateBuildings } from '../utils/dashboardPermissions';
import { buildingRoute } from '../utils/adminNavigation';
import {
  buildSites,
  buildCategoryTabs,
  filterBuildingsByCategory,
  ALL_CATEGORIES_KEY,
} from '../utils/dashboardModel';
import { CategoryTabs } from '../components/dashboard/DashboardCards';
import { ChevronIcon } from '../components/dashboard/DashboardPrimitives';
import { SiteIcon, BuildingIcon } from '../components/dashboard/DashboardIcons';
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
    allCategories: 'All',
    uncategorized: 'Uncategorized',
    unassignedSite: 'Unspecified site',
    emptyFiltered: 'No buildings match this category',
    openWorkspace: 'Open workspace',
    back: 'Back',
    section: 'Buildings & Centers',
    addBtn: 'Add Building',
    editTitle: 'Edit Building',
    addTitle: 'Add Building',
    fields: {
      campus: 'Site / Campus',
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
    allCategories: 'الكل',
    uncategorized: 'بدون تصنيف',
    unassignedSite: 'موقع غير محدد',
    emptyFiltered: 'لا توجد مبانٍ ضمن هذا التصنيف',
    openWorkspace: 'فتح مساحة العمل',
    back: 'رجوع',
    section: 'المباني والمراكز',
    addBtn: 'إضافة مبنى',
    editTitle: 'تعديل المبنى',
    addTitle: 'إضافة مبنى',
    fields: {
      campus: 'الموقع / الحرم',
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
    allCategories: 'הכל',
    uncategorized: 'ללא קטגוריה',
    unassignedSite: 'אתר לא מוגדר',
    emptyFiltered: 'אין מבנים בקטגוריה הזו',
    openWorkspace: 'פתח סביבת עבודה',
    back: 'חזרה',
    section: 'מבנים ומרכזים',
    addBtn: 'הוסף מבנה',
    editTitle: 'ערוך מבנה',
    addTitle: 'הוסף מבנה',
    fields: {
      campus: 'אתר / קמפוס',
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
  // Site/campus is a real persisted Building field the backend has always
  // accepted; this form simply never offered it, which is why buildings
  // ended up grouped under whatever value the automatic map-upload setup
  // wrote (often the map group's code).
  campus: '',
};

// ── AdminLocationsScreen ──────────────────────────────────────────────────────
const AdminLocationsScreen = () => {
  const { lang } = useLang();
  const navigate = useNavigate();
  const { user } = useAuth();
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
  const [categoryKey, setCategoryKey] = useState(ALL_CATEGORIES_KEY);
  const [form,      setForm]      = useState({ ...EMPTY_BUILDING });
  const [confirmId, setConfirmId] = useState(null);
  const [error,     setError]     = useState('');

  const setField = (k, v) => setForm((p) => ({ ...p, [k]: v }));

  // `buildings` arrives already narrowed to this account by the backend
  // (GET /api/locations/buildings), so grouping/filtering here only decides
  // presentation — it never widens what was returned.
  const canCreate = canCreateBuildings(user);

  const categoryTabs = useMemo(
    () => buildCategoryTabs(buildings, t.allCategories, t.uncategorized),
    [buildings, t.allCategories, t.uncategorized],
  );

  const visibleBuildings = useMemo(
    () => filterBuildingsByCategory(buildings, categoryKey),
    [buildings, categoryKey],
  );

  const sites = useMemo(
    () => buildSites(visibleBuildings, t.unassignedSite),
    [visibleBuildings, t.unassignedSite],
  );

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
    <div className="qrd-page">
      <div className="qrd-pagebody" dir={isRTL ? 'rtl' : 'ltr'}>

        {/* ── Header ──────────────────────────────────────────────────── */}
        <div className="qrd-headwrap">
          <AdminScreenHeader
            pageKey="sites"
            onBack={view !== 'list' ? () => setView('list') : undefined}
            title={view === 'add' ? t.addTitle : view === 'edit' ? t.editTitle : undefined}
          />
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
              {/* Creating a building is require_global_admin on the backend
                  (POST /api/locations/buildings), so a building_manager
                  browses and edits its own buildings here but is never shown
                  an Add action it would be rejected for. */}
              {canCreate && (
                <div className="adm-btn-row">
                  <button className="adm-btn adm-btn-primary" onClick={openAdd}>
                    <AddIcon /> {t.addBtn}
                  </button>
                </div>
              )}

              {/* Tabs are built only from Building.category values that
                  actually exist on the authorized buildings — never from a
                  building's name, and never rendered when there is nothing
                  to filter by. */}
              <CategoryTabs
                tabs={categoryTabs}
                activeKey={categoryKey}
                onSelect={setCategoryKey}
              />

              <div className="adm-section-row">
                <span className="adm-section-lbl">{t.section}</span>
                <span className="adm-section-count">{t.count(visibleBuildings.length)}</span>
              </div>

              {buildingsLoading ? (
                <div className="adm-empty">
                  <div className="adm-empty-txt">{t.loading}</div>
                </div>
              ) : visibleBuildings.length === 0 ? (
                <div className="adm-empty">
                  <div className="adm-empty-icon"><LocationIcon /></div>
                  <div className="adm-empty-txt">
                    {buildings.length === 0 ? t.empty : t.emptyFiltered}
                  </div>
                  {buildings.length === 0 && (
                    <div className="adm-empty-hint">{t.emptyHint}</div>
                  )}
                </div>
              ) : (
                /* Grouped by the building's REAL persisted Site (campus).
                   A building with no campus falls under one neutral label —
                   its own name/code is never promoted to a site name. */
                sites.map((site) => (
                  <div className="qrd-group" key={site.key} style={{ marginBottom: 14 }}>
                    <div className="qrd-group-head" style={{ cursor: 'default' }}>
                      <span className="qrd-group-icon" aria-hidden="true">
                        <SiteIcon size={22} />
                      </span>
                      <span className="qrd-group-body">
                        <span className="qrd-group-name">{site.name}</span>
                        <span className="qrd-group-meta">{t.count(site.buildings.length)}</span>
                      </span>
                    </div>

                    <div className="qrd-floors">
                      {site.buildings.map((b) => (
                        <div key={b.id}>
                          <div className="qrd-floor" style={{ cursor: 'default' }}>
                            <span
                              className="qrd-floor-icon"
                              aria-hidden="true"
                              style={{ color: b.iconColor }}
                            >
                              <BuildingIcon size={18} />
                            </span>

                            <button
                              type="button"
                              className="qrd-floor-name"
                              title={t.openWorkspace}
                              onClick={() => navigate(buildingRoute(b.id))}
                              style={{
                                border: 'none',
                                background: 'transparent',
                                cursor: 'pointer',
                                textAlign: 'start',
                                color: 'inherit',
                                padding: 0,
                              }}
                            >
                              {b.nameEn || b.name}
                              {b.tag ? (
                                <span className="adm-tag adm-tag-blue" style={{ marginInlineStart: 8 }}>
                                  {b.tag}
                                </span>
                              ) : null}
                            </button>

                            <div className="adm-list-item-acts">
                              <button className="adm-icon-btn" onClick={() => openEdit(b)} title={t.editTitle}>
                                <EditIcon />
                              </button>
                              <button className="adm-icon-btn adm-icon-btn-danger"
                                onClick={() => setConfirmId(confirmId === b.id ? null : b.id)}
                                title={t.delete}>
                                <DeleteIcon />
                              </button>
                              <span className="qrd-floor-chev" aria-hidden="true">
                                <ChevronIcon rtl={isRTL} />
                              </span>
                            </div>
                          </div>

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
                  </div>
                ))
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
                <label className="adm-form-label">{t.fields.campus}</label>
                <input className="adm-form-input" value={form.campus || ''}
                  onChange={(e) => setField('campus', e.target.value)}
                  placeholder="e.g. Main Campus" />
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
