import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useLang } from '../context/LangContext';
import { useAdmin } from '../context/AdminContext';
import {
  getRoutePointsList,
  createRoutePoint,
  updateRoutePoint,
  deleteRoutePoint,
  previewBulkDeleteRoutePoints,
  applyBulkDeleteRoutePoints,
} from '../api/routePointsApi';
import { getMapGroups } from '../api/mapGroupsApi';
import { resolveApiErrorMessage } from '../utils/apiErrors';
import '../styles/adminScreens.css';

// RBAC/dashboard cleanup task (frontend completion), Sections 5/6 — this
// screen was previously "load every RoutePoint on the current map,
// unpaginated, unfiltered beyond map_id" (see git history). It now uses
// the server-side paginated GET /api/route-points/list endpoint
// (RBAC/dashboard cleanup task, Phase 8) for every list render — never
// downloads the full RoutePoint set and paginates/filters in React — and
// adds the full bulk-delete preview/apply workflow against the matching
// backend endpoints added this same task.

const LANGUAGES = [
  { code: 'ar', label: 'عربي' },
  { code: 'he', label: 'עברית' },
  { code: 'en', label: 'EN' },
];

const POINT_TYPES = ['entrance', 'hallway', 'stairs', 'elevator', 'room', 'store', 'junction'];
const SOURCES = ['manual', 'generated', 'semantic_destination', 'vertical_connector', 'unknown_legacy'];
const PAGE_SIZE_OPTIONS = [25, 50, 100, 200];

const UI = {
  en: {
    title: 'Route Points',
    back: 'Back',
    addBtn: 'Add Route Point',
    addTitle: 'Add Route Point',
    editTitle: 'Edit Route Point',

    fields: {
      name: 'Node Name', pointType: 'Point Type', floor: 'Floor',
      x: 'X Coordinate', y: 'Y Coordinate', accessible: 'Accessible',
    },
    save: 'Save', cancel: 'Cancel',
    loading: 'Loading route points...',
    loadError: 'Failed to load route points',
    saveError: 'Failed to save route point',
    deleteError: 'Failed to delete route point',
    forbidden: 'You do not have permission to view or manage these route points.',
    sessionExpired: 'Your session has expired. Please log in again.',
    notFound: 'Route point not found.',

    confirmDelete: 'Delete this route point?',
    yes: 'Yes, Delete',
    empty: 'No route points match these filters',
    emptyHint: 'Try widening your filters, or add a new route point',
    nodeLabel: 'Node',
    openOnMap: 'Open on Map',

    filters: {
      title: 'Filters',
      campus: 'Campus', allCampuses: 'All campuses',
      building: 'Building', allBuildings: 'All buildings',
      mapGroup: 'Map Group', allMapGroups: 'All map groups',
      map: 'Map', allMaps: 'All maps',
      floor: 'Floor', allFloors: 'All floors',
      source: 'Source', allSources: 'All sources',
      pointType: 'Point Type', allTypes: 'All types',
      search: 'Search by name', searchPlaceholder: 'e.g. Main Entrance',
      clear: 'Clear filters',
    },
    sourceLabels: {
      manual: 'Manual', generated: 'Generated',
      semantic_destination: 'Semantic destination', vertical_connector: 'Vertical connector',
      unknown_legacy: 'Legacy',
    },

    pagination: {
      showing: (loaded, total) => `Showing ${loaded} of ${total} total nodes`,
      page: (page, totalPages) => `Page ${page} of ${totalPages}`,
      prev: 'Previous', next: 'Next', pageSize: 'Per page',
    },

    bulk: {
      selectAllVisible: 'Select all visible',
      selectAllOnMap: 'Select all on this map',
      clearSelection: 'Clear selection',
      selectedCount: (n) => `${n} selected`,
      previewDelete: 'Preview Delete',
      previewTitle: 'Preview Bulk Delete',
      deletable: 'Will be deleted',
      blocked: 'Blocked — will NOT be deleted',
      warnings: 'Warnings',
      reasonNotFound: 'Not found',
      reasonOutOfScope: 'Out of your scope',
      reasonHasEdges: (n) => `Has ${n} connected edge(s)`,
      reasonHasLocationCode: 'Used by a location code',
      reasonInvalidId: 'Invalid id',
      reasonRoomWillDeactivate: 'Linked room will be deactivated',
      cannotApplyAll: 'Some selected points cannot be deleted. Fix or deselect them before continuing.',
      confirmApply: (n) => `Permanently delete ${n} route point(s)? This cannot be undone.`,
      applyAction: 'Delete Selected',
      applying: 'Deleting…',
      applyFailed: 'Bulk delete was rejected — nothing was deleted.',
      applySuccess: (n) => `${n} route point(s) deleted.`,
      close: 'Close',
    },
  },

  ar: {
    title: 'نقاط المسار', back: 'رجوع',
    addBtn: 'إضافة نقطة مسار', addTitle: 'إضافة نقطة مسار', editTitle: 'تعديل نقطة مسار',
    fields: {
      name: 'اسم العقدة', pointType: 'نوع النقطة', floor: 'الطابق',
      x: 'إحداثي X', y: 'إحداثي Y', accessible: 'متاحة لذوي الاحتياجات',
    },
    save: 'حفظ', cancel: 'إلغاء',
    loading: 'جاري تحميل نقاط المسار...', loadError: 'فشل تحميل نقاط المسار',
    saveError: 'فشل حفظ نقطة المسار', deleteError: 'فشل حذف نقطة المسار',
    forbidden: 'ليست لديك صلاحية لعرض أو إدارة نقاط المسار هذه.',
    sessionExpired: 'انتهت صلاحية جلستك. يرجى تسجيل الدخول مرة أخرى.',
    notFound: 'نقطة المسار غير موجودة.',
    confirmDelete: 'حذف نقطة المسار هذه؟', yes: 'نعم، احذف',
    empty: 'لا توجد نقاط مسار مطابقة لهذه الفلاتر',
    emptyHint: 'وسّع الفلاتر أو أضف نقطة مسار جديدة',
    nodeLabel: 'عقدة', openOnMap: 'فتح على الخريطة',
    filters: {
      title: 'الفلاتر',
      campus: 'الحرم', allCampuses: 'كل الحرم الجامعي',
      building: 'المبنى', allBuildings: 'كل المباني',
      mapGroup: 'مجموعة الخرائط', allMapGroups: 'كل مجموعات الخرائط',
      map: 'الخريطة', allMaps: 'كل الخرائط',
      floor: 'الطابق', allFloors: 'كل الطوابق',
      source: 'المصدر', allSources: 'كل المصادر',
      pointType: 'نوع النقطة', allTypes: 'كل الأنواع',
      search: 'بحث بالاسم', searchPlaceholder: 'مثال: المدخل الرئيسي',
      clear: 'مسح الفلاتر',
    },
    sourceLabels: {
      manual: 'يدوي', generated: 'مولّد تلقائيًا',
      semantic_destination: 'وجهة دلالية', vertical_connector: 'موصل رأسي', unknown_legacy: 'قديم',
    },
    pagination: {
      showing: (loaded, total) => `عرض ${loaded} من ${total} عقدة إجمالًا`,
      page: (page, totalPages) => `صفحة ${page} من ${totalPages}`,
      prev: 'السابق', next: 'التالي', pageSize: 'لكل صفحة',
    },
    bulk: {
      selectAllVisible: 'تحديد الكل الظاهر', selectAllOnMap: 'تحديد الكل في هذه الخريطة',
      clearSelection: 'إلغاء التحديد', selectedCount: (n) => `${n} محدد`,
      previewDelete: 'معاينة الحذف', previewTitle: 'معاينة الحذف الجماعي',
      deletable: 'سيتم حذفها', blocked: 'محظورة — لن تُحذف', warnings: 'تحذيرات',
      reasonNotFound: 'غير موجودة', reasonOutOfScope: 'خارج نطاقك',
      reasonHasEdges: (n) => `لديها ${n} رابط متصل`,
      reasonHasLocationCode: 'مستخدمة برمز موقع', reasonInvalidId: 'معرّف غير صالح',
      reasonRoomWillDeactivate: 'سيتم إلغاء تنشيط الغرفة المرتبطة',
      cannotApplyAll: 'بعض النقاط المحددة لا يمكن حذفها. عدّل التحديد قبل المتابعة.',
      confirmApply: (n) => `حذف ${n} نقطة مسار نهائيًا؟ لا يمكن التراجع عن هذا.`,
      applyAction: 'حذف المحدد', applying: 'جارٍ الحذف…',
      applyFailed: 'تم رفض الحذف الجماعي — لم يُحذف شيء.',
      applySuccess: (n) => `تم حذف ${n} نقطة مسار.`, close: 'إغلاق',
    },
  },

  he: {
    title: 'נקודות מסלול', back: 'חזרה',
    addBtn: 'הוסף נקודת מסלול', addTitle: 'הוסף נקודת מסלול', editTitle: 'ערוך נקודת מסלול',
    fields: {
      name: 'שם צומת', pointType: 'סוג נקודה', floor: 'קומה',
      x: 'קואורדינטה X', y: 'קואורדינטה Y', accessible: 'נגיש',
    },
    save: 'שמור', cancel: 'ביטול',
    loading: 'טוען נקודות מסלול...', loadError: 'טעינת נקודות המסלול נכשלה',
    saveError: 'שמירת נקודת המסלול נכשלה', deleteError: 'מחיקת נקודת המסלול נכשלה',
    forbidden: 'אין לך הרשאה לצפות בנקודות מסלול אלה או לנהל אותן.',
    sessionExpired: 'תוקף ההתחברות שלך פג. יש להתחבר מחדש.',
    notFound: 'נקודת המסלול לא נמצאה.',
    confirmDelete: 'למחוק נקודת מסלול זו?', yes: 'כן, מחק',
    empty: 'אין נקודות מסלול התואמות לפילטרים אלה',
    emptyHint: 'הרחב את הפילטרים או הוסף נקודת מסלול חדשה',
    nodeLabel: 'צומת', openOnMap: 'פתח במפה',
    filters: {
      title: 'פילטרים',
      campus: 'קמפוס', allCampuses: 'כל הקמפוסים',
      building: 'מבנה', allBuildings: 'כל המבנים',
      mapGroup: 'קבוצת מפות', allMapGroups: 'כל קבוצות המפות',
      map: 'מפה', allMaps: 'כל המפות',
      floor: 'קומה', allFloors: 'כל הקומות',
      source: 'מקור', allSources: 'כל המקורות',
      pointType: 'סוג נקודה', allTypes: 'כל הסוגים',
      search: 'חיפוש לפי שם', searchPlaceholder: 'למשל: כניסה ראשית',
      clear: 'נקה פילטרים',
    },
    sourceLabels: {
      manual: 'ידני', generated: 'נוצר אוטומטית',
      semantic_destination: 'יעד סמנטי', vertical_connector: 'מחבר אנכי', unknown_legacy: 'ישן',
    },
    pagination: {
      showing: (loaded, total) => `מציג ${loaded} מתוך ${total} צמתים בסך הכול`,
      page: (page, totalPages) => `עמוד ${page} מתוך ${totalPages}`,
      prev: 'הקודם', next: 'הבא', pageSize: 'לעמוד',
    },
    bulk: {
      selectAllVisible: 'בחר הכל בעמוד זה', selectAllOnMap: 'בחר הכל במפה זו',
      clearSelection: 'נקה בחירה', selectedCount: (n) => `${n} נבחרו`,
      previewDelete: 'תצוגה מקדימה למחיקה', previewTitle: 'תצוגה מקדימה למחיקה מרובה',
      deletable: 'יימחקו', blocked: 'חסומים — לא יימחקו', warnings: 'אזהרות',
      reasonNotFound: 'לא נמצא', reasonOutOfScope: 'מחוץ להיקף שלך',
      reasonHasEdges: (n) => `יש ${n} קשרים מחוברים`,
      reasonHasLocationCode: 'בשימוש קוד מיקום', reasonInvalidId: 'מזהה לא תקין',
      reasonRoomWillDeactivate: 'החדר המקושר יושבת',
      cannotApplyAll: 'חלק מהנקודות שנבחרו לא ניתנות למחיקה. תקן או בטל בחירה לפני שתמשיך.',
      confirmApply: (n) => `למחוק לצמיתות ${n} נקודות מסלול? לא ניתן לבטל פעולה זו.`,
      applyAction: 'מחק את הנבחרים', applying: 'מוחק…',
      applyFailed: 'המחיקה המרובה נדחתה — שום דבר לא נמחק.',
      applySuccess: (n) => `${n} נקודות מסלול נמחקו.`, close: 'סגור',
    },
  },
};

const EMPTY_ROUTE = { name: '', point_type: 'hallway', floor: 0, x: 0, y: 0, is_accessible: true };

const AdminRoutesScreen = () => {
  const { lang, setLang } = useLang();
  const navigate = useNavigate();
  const { buildings } = useAdmin();

  const isRTL = lang === 'ar' || lang === 'he';
  const t = UI[lang] || UI.en;

  // ── Filters ────────────────────────────────────────────────────────────
  const [campus, setCampus] = useState('');
  const [buildingId, setBuildingId] = useState('');
  const [mapGroupId, setMapGroupId] = useState('');
  const [mapId, setMapId] = useState('');
  const [floor, setFloor] = useState('');
  const [pointType, setPointType] = useState('');
  const [source, setSource] = useState('');
  const [search, setSearch] = useState('');
  const [searchDraft, setSearchDraft] = useState('');

  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);

  const [mapGroups, setMapGroups] = useState([]);

  const [items, setItems] = useState([]);
  const [loadedCount, setLoadedCount] = useState(0);
  const [totalCount, setTotalCount] = useState(0);
  const [totalPages, setTotalPages] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const [view, setView] = useState('list');
  const [form, setForm] = useState({ ...EMPTY_ROUTE });
  const [confirmId, setConfirmId] = useState(null);

  // ── Bulk selection / delete ───────────────────────────────────────────
  const [selectedIds, setSelectedIds] = useState(() => new Set());
  const [previewResult, setPreviewResult] = useState(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [applyLoading, setApplyLoading] = useState(false);
  const [bulkError, setBulkError] = useState('');
  const [showPreviewDialog, setShowPreviewDialog] = useState(false);

  const campusOptions = useMemo(
    () => Array.from(new Set((buildings || []).map((b) => (b.campus || '').trim()).filter(Boolean))),
    [buildings],
  );

  const buildingsInCampus = useMemo(
    () => (campus ? (buildings || []).filter((b) => (b.campus || '').trim() === campus) : buildings || []),
    [buildings, campus],
  );

  // Map Groups for the selected building — dropdown options are already
  // implicitly scope-restricted because `buildings` itself only ever
  // contains buildings this account can access (backend-scoped GET
  // /api/locations/buildings), and getMapGroups(buildingId) requires a
  // buildingId this account already had to legitimately select.
  useEffect(() => {
    if (!buildingId) { setMapGroups([]); return undefined; }
    let cancelled = false;
    getMapGroups(buildingId)
      .then((groups) => { if (!cancelled) setMapGroups(groups); })
      .catch(() => { if (!cancelled) setMapGroups([]); });
    return () => { cancelled = true; };
  }, [buildingId]);

  const mapsInSelectedGroup = useMemo(() => {
    if (!mapGroupId) return [];
    const group = mapGroups.find((g) => g.id === mapGroupId);
    return group ? (group.floors || []) : [];
  }, [mapGroups, mapGroupId]);

  const loadList = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const result = await getRoutePointsList({
        buildingId: buildingId || undefined,
        mapGroupId: mapGroupId || undefined,
        mapId: mapId || undefined,
        floor: floor === '' ? undefined : Number(floor),
        pointType: pointType || undefined,
        source: source || undefined,
        search: search || undefined,
        page,
        pageSize,
      });
      setItems(result.items || []);
      setLoadedCount(result.loaded_count || 0);
      setTotalCount(result.total_count || 0);
      setTotalPages(result.total_pages || 1);
    } catch (err) {
      console.error('Failed to load route points:', err);
      setItems([]);
      setLoadedCount(0);
      setTotalCount(0);
      setTotalPages(1);
      setError(resolveApiErrorMessage(err, t));
    } finally {
      setLoading(false);
    }
  }, [buildingId, mapGroupId, mapId, floor, pointType, source, search, page, pageSize, t]);

  useEffect(() => { loadList(); }, [loadList]);

  // Any filter change resets to page 1 and clears the current selection —
  // a stale selection spanning a filter change could otherwise silently
  // include points the admin can no longer see.
  useEffect(() => {
    setPage(1);
    setSelectedIds(new Set());
  }, [buildingId, mapGroupId, mapId, floor, pointType, source, search]);

  const handleSearchSubmit = (e) => {
    e.preventDefault();
    setSearch(searchDraft.trim());
  };

  const clearFilters = () => {
    setCampus(''); setBuildingId(''); setMapGroupId(''); setMapId('');
    setFloor(''); setPointType(''); setSource(''); setSearch(''); setSearchDraft('');
  };

  // ── Add/Edit (unchanged single-point flow, now against the currently
  // filtered map if one is selected) ─────────────────────────────────────
  const openAdd = () => { setForm({ ...EMPTY_ROUTE, map_id: mapId || '' }); setError(''); setView('add'); };
  const openEdit = (rp) => {
    setForm({
      id: rp.id, name: rp.name, point_type: rp.point_type, floor: rp.floor,
      x: rp.x, y: rp.y, is_accessible: rp.is_accessible, map_id: rp.map_id,
    });
    setError('');
    setView('edit');
  };
  const setField = (key, value) => setForm((prev) => ({ ...prev, [key]: value }));

  const handleSave = async () => {
    if (!form.map_id) { setError(t.filters.map + ': ' + t.filters.allMaps); return; }
    try {
      setError('');
      const payload = {
        map_id: form.map_id, name: form.name.trim(), point_type: form.point_type,
        x: Number(form.x), y: Number(form.y), floor: Number(form.floor),
        is_accessible: Boolean(form.is_accessible),
      };
      if (view === 'add') await createRoutePoint(payload);
      else await updateRoutePoint(form.id, payload);
      await loadList();
      setView('list');
    } catch (err) {
      console.error(err);
      setError(resolveApiErrorMessage(err, t));
    }
  };

  const handleDelete = async (id) => {
    try {
      setError('');
      await deleteRoutePoint(id);
      setConfirmId(null);
      await loadList();
    } catch (err) {
      console.error(err);
      setError(resolveApiErrorMessage(err, t));
    }
  };

  // ── Bulk selection ─────────────────────────────────────────────────────
  const toggleSelected = (id) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };

  const selectAllVisible = () => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      items.forEach((p) => next.add(p.id));
      return next;
    });
  };

  const clearSelection = () => setSelectedIds(new Set());

  // "Select all on this map" — never merges in another map's points, even
  // if the current filter view spans multiple maps. Requires a specific
  // map to be selected first (the button is disabled otherwise).
  const selectAllOnMap = async () => {
    if (!mapId) return;
    try {
      setBulkError('');
      const result = await getRoutePointsList({ mapId, page: 1, pageSize: 500 });
      setSelectedIds((prev) => {
        const next = new Set(prev);
        (result.items || []).forEach((p) => next.add(p.id));
        return next;
      });
    } catch (err) {
      setBulkError(resolveApiErrorMessage(err, t));
    }
  };

  const runPreview = async () => {
    if (selectedIds.size === 0) return;
    setPreviewLoading(true);
    setBulkError('');
    try {
      const result = await previewBulkDeleteRoutePoints(Array.from(selectedIds));
      setPreviewResult(result);
      setShowPreviewDialog(true);
    } catch (err) {
      setBulkError(resolveApiErrorMessage(err, t));
    } finally {
      setPreviewLoading(false);
    }
  };

  const runApply = async () => {
    if (!previewResult || !previewResult.can_apply_all) return;
    setApplyLoading(true);
    setBulkError('');
    try {
      const result = await applyBulkDeleteRoutePoints(Array.from(selectedIds));
      setShowPreviewDialog(false);
      setPreviewResult(null);
      setSelectedIds(new Set());
      await loadList();
      // Non-blocking success note — reuses the same error-strip styling
      // (green would need a new class; kept simple/consistent instead).
      setError('');
      window.alert(t.bulk.applySuccess(result.deleted_count));
    } catch (err) {
      // All-or-nothing on the backend: a rejected apply means NOTHING was
      // deleted — the selection is deliberately kept exactly as-is (never
      // cleared, never partially reconciled) so the admin can see what
      // failed and adjust.
      setBulkError(resolveApiErrorMessage(err, { ...t, forbidden: t.bulk.applyFailed }) || t.bulk.applyFailed);
    } finally {
      setApplyLoading(false);
    }
  };

  const reasonLabel = (issue) => {
    switch (issue.reason) {
      case 'not_found': return t.bulk.reasonNotFound;
      case 'out_of_scope': return t.bulk.reasonOutOfScope;
      case 'has_connected_edges': return t.bulk.reasonHasEdges(issue.connected_edge_count ?? 0);
      case 'has_location_code': return t.bulk.reasonHasLocationCode;
      case 'invalid_id': return t.bulk.reasonInvalidId;
      default: return issue.detail || issue.reason;
    }
  };

  return (
    <div className="layout-wrapper">
      <div className="layout-shell adm-shell" dir={isRTL ? 'rtl' : 'ltr'}>
        <div className="adm-inner-header">
          <div className="adm-topbar">
            <button
              className={`adm-back-btn${isRTL ? ' adm-back-btn-rtl' : ''}`}
              onClick={() => (view !== 'list' ? setView('list') : navigate('/screen/05'))}
            >
              {t.back}
            </button>
            <div className="adm-lang-pill" role="group">
              {LANGUAGES.map((language) => (
                <button
                  key={language.code}
                  className={`adm-lang-btn${lang === language.code ? ' active' : ''}`}
                  onClick={() => setLang(language.code)}
                >
                  {language.label}
                </button>
              ))}
            </div>
          </div>
          <div className="adm-inner-heading">
            <h1 className="adm-inner-title">
              {view === 'add' ? t.addTitle : view === 'edit' ? t.editTitle : t.title}
            </h1>
          </div>
        </div>

        <div className="adm-content">
          {error && (
            <div style={{ marginBottom: 16, padding: 12, borderRadius: 12, background: '#ffe9e9', color: '#a92323', fontSize: 14 }}>
              {error}
            </div>
          )}

          {view === 'list' && (
            <>
              {/* ── Filters ─────────────────────────────────────────── */}
              <div className="adm-form-card" style={{ marginBottom: 16 }}>
                <div className="adm-form-card-title">{t.filters.title}</div>
                <div className="adm-form-row" style={{ flexWrap: 'wrap', gap: 10 }}>
                  <div className="adm-form-group" style={{ minWidth: 140 }}>
                    <label className="adm-form-label">{t.filters.campus}</label>
                    <select className="adm-form-input" value={campus} onChange={(e) => { setCampus(e.target.value); setBuildingId(''); }}>
                      <option value="">{t.filters.allCampuses}</option>
                      {campusOptions.map((c) => <option key={c} value={c}>{c}</option>)}
                    </select>
                  </div>
                  <div className="adm-form-group" style={{ minWidth: 140 }}>
                    <label className="adm-form-label">{t.filters.building}</label>
                    <select className="adm-form-input" value={buildingId} onChange={(e) => { setBuildingId(e.target.value); setMapGroupId(''); setMapId(''); }}>
                      <option value="">{t.filters.allBuildings}</option>
                      {buildingsInCampus.map((b) => <option key={b.id} value={b.id}>{b.nameEn || b.name}</option>)}
                    </select>
                  </div>
                  <div className="adm-form-group" style={{ minWidth: 140 }}>
                    <label className="adm-form-label">{t.filters.mapGroup}</label>
                    <select className="adm-form-input" value={mapGroupId} disabled={!buildingId} onChange={(e) => { setMapGroupId(e.target.value); setMapId(''); }}>
                      <option value="">{t.filters.allMapGroups}</option>
                      {mapGroups.map((g) => <option key={g.id} value={g.id}>{g.name || g.code}</option>)}
                    </select>
                  </div>
                  <div className="adm-form-group" style={{ minWidth: 140 }}>
                    <label className="adm-form-label">{t.filters.map}</label>
                    <select className="adm-form-input" value={mapId} disabled={!mapGroupId} onChange={(e) => setMapId(e.target.value)}>
                      <option value="">{t.filters.allMaps}</option>
                      {mapsInSelectedGroup.map((m) => <option key={m.id} value={m.id}>{m.title || m.floorLabel}</option>)}
                    </select>
                  </div>
                  <div className="adm-form-group" style={{ minWidth: 110 }}>
                    <label className="adm-form-label">{t.filters.floor}</label>
                    <input className="adm-form-input" type="number" value={floor} placeholder={t.filters.allFloors}
                      onChange={(e) => setFloor(e.target.value)} />
                  </div>
                  <div className="adm-form-group" style={{ minWidth: 140 }}>
                    <label className="adm-form-label">{t.filters.pointType}</label>
                    <select className="adm-form-input" value={pointType} onChange={(e) => setPointType(e.target.value)}>
                      <option value="">{t.filters.allTypes}</option>
                      {POINT_TYPES.map((pt) => <option key={pt} value={pt}>{pt}</option>)}
                    </select>
                  </div>
                  <div className="adm-form-group" style={{ minWidth: 160 }}>
                    <label className="adm-form-label">{t.filters.source}</label>
                    <select className="adm-form-input" value={source} onChange={(e) => setSource(e.target.value)}>
                      <option value="">{t.filters.allSources}</option>
                      {SOURCES.map((s) => <option key={s} value={s}>{t.sourceLabels[s] || s}</option>)}
                    </select>
                  </div>
                  <form onSubmit={handleSearchSubmit} className="adm-form-group" style={{ minWidth: 180, flex: 1 }}>
                    <label className="adm-form-label">{t.filters.search}</label>
                    <input className="adm-form-input" value={searchDraft} placeholder={t.filters.searchPlaceholder}
                      onChange={(e) => setSearchDraft(e.target.value)} />
                  </form>
                </div>
                <div className="adm-form-actions" style={{ marginTop: 10 }}>
                  <button className="adm-btn adm-btn-cancel" type="button" onClick={clearFilters}>{t.filters.clear}</button>
                  <button className="adm-btn adm-btn-primary" type="button" onClick={() => setSearch(searchDraft.trim())}>{t.filters.search}</button>
                </div>
              </div>

              {/* ── Bulk toolbar ─────────────────────────────────────── */}
              <div className="adm-btn-row" style={{ flexWrap: 'wrap', gap: 8 }}>
                <button className="adm-btn adm-btn-primary" onClick={openAdd}>{t.addBtn}</button>
                <button className="adm-btn adm-btn-cancel" onClick={selectAllVisible} disabled={items.length === 0}>{t.bulk.selectAllVisible}</button>
                <button className="adm-btn adm-btn-cancel" onClick={selectAllOnMap} disabled={!mapId}>{t.bulk.selectAllOnMap}</button>
                <button className="adm-btn adm-btn-cancel" onClick={clearSelection} disabled={selectedIds.size === 0}>{t.bulk.clearSelection}</button>
                <span className="adm-section-count" style={{ alignSelf: 'center' }}>{t.bulk.selectedCount(selectedIds.size)}</span>
                <button className="adm-btn adm-btn-confirm-delete" onClick={runPreview} disabled={selectedIds.size === 0 || previewLoading}>
                  {previewLoading ? '…' : t.bulk.previewDelete}
                </button>
              </div>

              {bulkError && (
                <div style={{ margin: '10px 0', padding: 12, borderRadius: 12, background: '#ffe9e9', color: '#a92323', fontSize: 14 }}>
                  {bulkError}
                </div>
              )}

              {/* ── Pagination summary ───────────────────────────────── */}
              <div className="adm-section-row">
                <span className="adm-section-lbl">{t.pagination.showing(loadedCount, totalCount)}</span>
                <span className="adm-section-count">{t.pagination.page(page, totalPages)}</span>
              </div>

              {/* ── List ─────────────────────────────────────────────── */}
              {loading ? (
                <div className="adm-empty"><div className="adm-empty-txt">{t.loading}</div></div>
              ) : items.length === 0 ? (
                <div className="adm-empty">
                  <div className="adm-empty-txt">{t.empty}</div>
                  <div className="adm-empty-hint">{t.emptyHint}</div>
                </div>
              ) : (
                <div className="adm-list">
                  {items.map((rp) => (
                    <div key={rp.id} className="adm-list-item">
                      <div className="adm-list-item-row">
                        <input
                          type="checkbox"
                          checked={selectedIds.has(rp.id)}
                          onChange={() => toggleSelected(rp.id)}
                          style={{ marginInlineEnd: 10 }}
                          aria-label={rp.name}
                        />
                        <div className="adm-list-item-info">
                          <div className="adm-list-item-name">{rp.name}</div>
                          <div className="adm-list-item-meta">
                            <span className="adm-tag adm-tag-orange">{rp.point_type}</span>
                            <span className="adm-tag-txt">({rp.x}, {rp.y})</span>
                            <span className="adm-tag-txt">{t.fields.floor}: {rp.floor}</span>
                            <span className="adm-tag-txt">{t.sourceLabels[rp.source] || rp.source}</span>
                          </div>
                        </div>
                        <div className="adm-list-item-acts">
                          <button className="adm-icon-btn" onClick={() => navigate(`/admin/map?mapId=${rp.map_id}&editPointId=${rp.id}`)} title={t.openOnMap}>
                            🗺
                          </button>
                          <button className="adm-icon-btn" onClick={() => openEdit(rp)}>✎</button>
                          <button className="adm-icon-btn adm-icon-btn-danger" onClick={() => setConfirmId(confirmId === rp.id ? null : rp.id)}>🗑</button>
                        </div>
                      </div>
                      {confirmId === rp.id && (
                        <div className="adm-delete-strip">
                          <span className="adm-delete-strip-msg">{t.confirmDelete}</span>
                          <div className="adm-delete-strip-acts">
                            <button className="adm-btn adm-btn-cancel" style={{ padding: '5px 12px', fontSize: 12 }} onClick={() => setConfirmId(null)}>{t.cancel}</button>
                            <button className="adm-btn adm-btn-confirm-delete" style={{ padding: '5px 12px', fontSize: 12 }} onClick={() => handleDelete(rp.id)}>{t.yes}</button>
                          </div>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}

              {/* ── Pagination controls ──────────────────────────────── */}
              <div className="adm-btn-row" style={{ justifyContent: 'space-between', marginTop: 12 }}>
                <button className="adm-btn adm-btn-cancel" disabled={page <= 1} onClick={() => setPage((p) => Math.max(1, p - 1))}>
                  {t.pagination.prev}
                </button>
                <select className="adm-form-input" style={{ width: 100 }} value={pageSize} onChange={(e) => { setPageSize(Number(e.target.value)); setPage(1); }}>
                  {PAGE_SIZE_OPTIONS.map((size) => <option key={size} value={size}>{size} / {t.pagination.pageSize}</option>)}
                </select>
                <button className="adm-btn adm-btn-cancel" disabled={page >= totalPages} onClick={() => setPage((p) => Math.min(totalPages, p + 1))}>
                  {t.pagination.next}
                </button>
              </div>
            </>
          )}

          {(view === 'add' || view === 'edit') && (
            <div className="adm-form-card">
              <div className="adm-form-card-title">{view === 'add' ? t.addTitle : t.editTitle}</div>
              <div className="adm-form-group">
                <label className="adm-form-label">{t.fields.name}</label>
                <input className="adm-form-input" value={form.name || ''} onChange={(e) => setField('name', e.target.value)} />
              </div>
              <div className="adm-form-group">
                <label className="adm-form-label">{t.fields.pointType}</label>
                <select className="adm-form-input" value={form.point_type} onChange={(e) => setField('point_type', e.target.value)}>
                  {POINT_TYPES.map((pt) => <option key={pt} value={pt}>{pt}</option>)}
                </select>
              </div>
              <div className="adm-form-row">
                <div className="adm-form-group">
                  <label className="adm-form-label">{t.fields.x}</label>
                  <input className="adm-form-input" type="number" value={form.x ?? 0} onChange={(e) => setField('x', e.target.value)} />
                </div>
                <div className="adm-form-group">
                  <label className="adm-form-label">{t.fields.y}</label>
                  <input className="adm-form-input" type="number" value={form.y ?? 0} onChange={(e) => setField('y', e.target.value)} />
                </div>
              </div>
              <div className="adm-form-group">
                <label className="adm-form-label">{t.fields.floor}</label>
                <input className="adm-form-input" type="number" value={form.floor ?? 0} onChange={(e) => setField('floor', e.target.value)} />
              </div>
              <div className="adm-form-group">
                <label className="adm-form-label" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <input type="checkbox" checked={Boolean(form.is_accessible)} onChange={(e) => setField('is_accessible', e.target.checked)} />
                  {t.fields.accessible}
                </label>
              </div>
              <div className="adm-form-actions">
                <button className="adm-btn adm-btn-cancel" onClick={() => setView('list')}>{t.cancel}</button>
                <button className="adm-btn adm-btn-primary" onClick={handleSave} disabled={!form.name || !form.name.trim()}>{t.save}</button>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* ── Bulk delete preview dialog ─────────────────────────────────── */}
      {showPreviewDialog && previewResult && (
        <div
          role="dialog"
          aria-modal="true"
          style={{
            position: 'fixed', inset: 0, background: 'rgba(20,30,50,0.55)',
            display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100,
          }}
        >
          <div style={{ background: 'white', borderRadius: 16, padding: 20, width: 420, maxHeight: '80vh', overflowY: 'auto' }} dir={isRTL ? 'rtl' : 'ltr'}>
            <h2 style={{ fontSize: 16, marginBottom: 12, color: '#173b70' }}>{t.bulk.previewTitle}</h2>

            <div style={{ fontSize: 13, marginBottom: 10 }}>
              <strong>{t.bulk.deletable}:</strong> {previewResult.deletable_count} / {previewResult.requested_count}
            </div>

            {previewResult.issues && previewResult.issues.length > 0 && (
              <div style={{ marginBottom: 12 }}>
                <div style={{ fontWeight: 700, fontSize: 12.5, color: '#a92323', marginBottom: 4 }}>{t.bulk.blocked}</div>
                {previewResult.issues.map((issue) => (
                  <div key={issue.point_id} style={{ fontSize: 12, color: '#a92323', marginBottom: 2 }}>
                    {issue.point_id.slice(-6)} — {reasonLabel(issue)}
                  </div>
                ))}
              </div>
            )}

            {previewResult.warnings && previewResult.warnings.length > 0 && (
              <div style={{ marginBottom: 12 }}>
                <div style={{ fontWeight: 700, fontSize: 12.5, color: '#8a6d1a', marginBottom: 4 }}>{t.bulk.warnings}</div>
                {previewResult.warnings.map((w) => (
                  <div key={w.point_id} style={{ fontSize: 12, color: '#8a6d1a', marginBottom: 2 }}>
                    {w.point_id.slice(-6)} — {t.bulk.reasonRoomWillDeactivate}
                  </div>
                ))}
              </div>
            )}

            {!previewResult.can_apply_all && (
              <div style={{ fontSize: 12.5, color: '#a92323', marginBottom: 12 }}>{t.bulk.cannotApplyAll}</div>
            )}

            {bulkError && (
              <div style={{ marginBottom: 12, padding: 10, borderRadius: 10, background: '#ffe9e9', color: '#a92323', fontSize: 12.5 }}>
                {bulkError}
              </div>
            )}

            <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
              <button className="adm-btn adm-btn-cancel" onClick={() => { setShowPreviewDialog(false); setPreviewResult(null); }}>
                {t.bulk.close}
              </button>
              {previewResult.can_apply_all && (
                <button
                  className="adm-btn adm-btn-confirm-delete"
                  disabled={applyLoading}
                  onClick={() => {
                    if (window.confirm(t.bulk.confirmApply(previewResult.deletable_count))) runApply();
                  }}
                >
                  {applyLoading ? t.bulk.applying : t.bulk.applyAction}
                </button>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default AdminRoutesScreen;
