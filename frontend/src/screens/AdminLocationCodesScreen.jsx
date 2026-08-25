import { useEffect, useMemo, useState } from 'react';
import AdminScreenHeader from '../components/dashboard/AdminScreenHeader';
import QRCode from 'qrcode';
import { useLang } from '../context/LangContext';
import { useAdmin } from '../context/AdminContext';
import {
  getLocationCodes,
  createLocationCode,
  generateLocationCode,
  updateLocationCode,
  deleteLocationCode,
} from '../api/locationCodesApi';
import {
  buildBuildingOptions,
  buildMapOptions,
  buildRoutePointOptions,
  filterMapsForBuilding,
  filterEntrancePointsForMap,
  hasNoEntranceForSelectedMap,
  filterPointsForMap,
  hasNoPointsForMap,
  resolveMapDerivedInfo,
  buildEditFormFromEntry,
  isEditSaveEnabled,
  buildEditSavePayload,
  resetOnBuildingChange,
  resetOnMapChange,
  isManualSaveEnabled,
  isGenerateEnabled,
  buildManualSavePayload,
  buildGeneratePayload,
  normalizeId,
} from '../utils/locationCodeFormHelpers';
import { formatFloorDisplay } from '../utils/mapGroupHelpers';
import { buildLocationCodeUrl } from '../config/publicUrl';
import '../styles/adminScreens.css';

const LANGUAGES = [
  { code: 'ar', label: 'عربي' },
  { code: 'he', label: 'עברית' },
  { code: 'en', label: 'EN' },
];

const UI = {
  en: {
    title: 'Location Codes',
    back: 'Back',
    section: 'Barcode / QR Codes',
    addBtn: 'Add Code',
    generateBtn: 'Generate Code',
    empty: 'No location codes yet',
    emptyHint: 'Add or generate one to let users start navigation from a scanned code',
    loading: 'Loading location codes...',
    count: (n) => `${n} code${n !== 1 ? 's' : ''}`,
    scopeLabel: 'Showing',
    scopeAllBuildings: 'All buildings',
    scopeAllFloors: 'All floors in this building',
    scopeHint:
      'Codes belong to one specific floor map. Pick a building and floor to see only that floor\u2019s codes.',
    scopeEmptyForFloor: 'No codes on this floor yet',
    fields: {
      building: 'Building', map: 'Map', point: 'Start Point (entrance)',
      code: 'Code (leave blank to auto-generate)', label: 'Label', active: 'Active',
      mapGroup: 'Map Group', floor: 'Floor', pointEdit: 'Route Point',
    },
    save: 'Save', cancel: 'Cancel', delete: 'Delete', deactivate: 'Deactivate', activate: 'Activate',
    edit: 'Edit', editTitle: 'Edit Location Code',
    confirmDelete: 'Delete this location code?',
    yes: 'Yes, Delete',
    saveError: 'Failed to save location code',
    deleteError: 'Failed to delete location code',
    loadError: 'Failed to load location codes',
    showQr: 'Show QR', hideQr: 'Hide QR',
    inactive: 'Inactive',
    selectBuilding: 'Select a building', selectMap: 'Select a map', selectPoint: 'Select a start point',
    noMapsForBuilding: 'This building has no maps yet',
    noEntranceForMap: 'This map has no active entrance point yet — add one in Map Management before creating a code',
    noPointsForMap: 'This map has no active route points yet — add one in Map Management before reassigning this code',
    derivedHint: 'Automatically derived from the selected map',
    codeReadOnly: 'Code (cannot be changed here)',
  },
  ar: {
    title: 'رموز المواقع',
    back: 'رجوع',
    section: 'رموز الباركود / QR',
    addBtn: 'إضافة رمز',
    generateBtn: 'توليد رمز',
    empty: 'لا توجد رموز مواقع بعد',
    emptyHint: 'أضف أو ولّد رمزًا للسماح للمستخدمين ببدء التنقل من رمز ممسوح',
    loading: 'جاري تحميل رموز المواقع...',
    count: (n) => `${n} رمز`,
    scopeLabel: 'عرض',
    scopeAllBuildings: 'كل المباني',
    scopeAllFloors: 'كل الطوابق في هذا المبنى',
    scopeHint:
      'كل رمز يخص خريطة طابق واحدة. اختر المبنى والطابق لعرض رموز ذلك الطابق فقط.',
    scopeEmptyForFloor: 'لا توجد رموز في هذا الطابق بعد',
    fields: {
      building: 'المبنى', map: 'الخريطة', point: 'نقطة البداية (مدخل)',
      code: 'الرمز (اتركه فارغًا للتوليد التلقائي)', label: 'التسمية', active: 'نشط',
      mapGroup: 'مجموعة الخرائط', floor: 'الطابق', pointEdit: 'نقطة المسار',
    },
    save: 'حفظ', cancel: 'إلغاء', delete: 'حذف', deactivate: 'تعطيل', activate: 'تفعيل',
    edit: 'تعديل', editTitle: 'تعديل رمز الموقع',
    confirmDelete: 'حذف رمز الموقع هذا؟',
    yes: 'نعم، احذف',
    saveError: 'فشل حفظ رمز الموقع',
    deleteError: 'فشل حذف رمز الموقع',
    loadError: 'فشل تحميل رموز المواقع',
    showQr: 'عرض QR', hideQr: 'إخفاء QR',
    inactive: 'غير نشط',
    selectBuilding: 'اختر مبنى', selectMap: 'اختر خريطة', selectPoint: 'اختر نقطة بداية',
    noMapsForBuilding: 'لا توجد خرائط لهذا المبنى بعد',
    noEntranceForMap: 'لا توجد نقطة مدخل نشطة لهذه الخريطة بعد — أضف واحدة في إدارة الخريطة قبل إنشاء رمز',
    noPointsForMap: 'لا توجد نقاط مسار نشطة لهذه الخريطة بعد — أضف واحدة في إدارة الخريطة قبل إعادة تعيين هذا الرمز',
    derivedHint: 'مشتق تلقائيًا من الخريطة المختارة',
    codeReadOnly: 'الرمز (لا يمكن تغييره هنا)',
  },
  he: {
    title: 'קודי מיקום',
    back: 'חזרה',
    section: 'קודי ברקוד / QR',
    addBtn: 'הוסף קוד',
    generateBtn: 'צור קוד',
    empty: 'אין עדיין קודי מיקום',
    emptyHint: 'הוסף או צור קוד כדי לאפשר למשתמשים להתחיל ניווט מקוד סרוק',
    loading: 'טוען קודי מיקום...',
    count: (n) => `${n} קודים`,
    scopeLabel: 'מציג',
    scopeAllBuildings: 'כל הבניינים',
    scopeAllFloors: 'כל הקומות בבניין זה',
    scopeHint:
      'כל קוד שייך למפת קומה אחת. בחרו בניין וקומה כדי לראות רק את הקודים של אותה קומה.',
    scopeEmptyForFloor: 'אין עדיין קודים בקומה זו',
    fields: {
      building: 'מבנה', map: 'מפה', point: 'נקודת התחלה (כניסה)',
      code: 'קוד (השאר ריק ליצירה אוטומטית)', label: 'תווית', active: 'פעיל',
      mapGroup: 'קבוצת מפות', floor: 'קומה', pointEdit: 'נקודת מסלול',
    },
    save: 'שמור', cancel: 'ביטול', delete: 'מחק', deactivate: 'בטל הפעלה', activate: 'הפעל',
    edit: 'ערוך', editTitle: 'ערוך קוד מיקום',
    confirmDelete: 'למחוק קוד מיקום זה?',
    yes: 'כן, מחק',
    saveError: 'שמירת קוד המיקום נכשלה',
    deleteError: 'מחיקת קוד המיקום נכשלה',
    loadError: 'טעינת קודי המיקום נכשלה',
    showQr: 'הצג QR', hideQr: 'הסתר QR',
    inactive: 'לא פעיל',
    selectBuilding: 'בחר מבנה', selectMap: 'בחר מפה', selectPoint: 'בחר נקודת התחלה',
    noMapsForBuilding: 'למבנה זה אין עדיין מפות',
    noEntranceForMap: 'למפה זו אין עדיין נקודת כניסה פעילה — הוסף אחת בניהול מפה לפני יצירת קוד',
    noPointsForMap: 'למפה זו אין עדיין נקודות מסלול פעילות — הוסף אחת בניהול מפה לפני שיוך מחדש של קוד זה',
    derivedHint: 'נגזר אוטומטית מהמפה שנבחרה',
    codeReadOnly: 'קוד (לא ניתן לשנות כאן)',
  },
};

const BackArrow = ({ flip }) => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none"
    style={flip ? { transform: 'scaleX(-1)' } : undefined}>
    <path d="M19 12H5M11 18l-6-6 6-6" stroke="currentColor" strokeWidth="2.2"
      strokeLinecap="round" strokeLinejoin="round"/>
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

const CodeIcon = () => (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
    <rect x="3" y="3" width="7" height="7" rx="1.2" stroke="currentColor" strokeWidth="1.8"/>
    <rect x="14" y="3" width="7" height="7" rx="1.2" stroke="currentColor" strokeWidth="1.8"/>
    <rect x="3" y="14" width="7" height="7" rx="1.2" stroke="currentColor" strokeWidth="1.8"/>
    <path d="M14 14h3v3h-3zM18 18h3v3h-3zM18 14h3M14 18v3" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"/>
  </svg>
);

// Renders a code's QR as a data-URL <img>, generated on demand (not
// pre-rendered for every row in the list — most admins won't open every
// code's QR every time the screen loads).
//
// The ENCODED PAYLOAD is the openable QuickRoute URL
// ({PUBLIC_FRONTEND_URL}/?locationCode=CODE), not the bare code — a phone
// camera pointed at a bare code shows inert text and cannot open anything.
// The CAPTION under the image stays the bare LocationCode so it can still be
// read off a printed label and typed by hand on the start screen.
//
// Nothing here writes to the database. QR images have never been persisted —
// each is rendered from `code` at the moment an admin opens this preview —
// so changing the payload changes every QuickRoute QR immediately, with no
// migration, no regenerated records and no duplicate LocationCodes.
const QrPreview = ({ code }) => {
  const [dataUrl, setDataUrl] = useState(null);
  const [error, setError] = useState('');

  const payload = useMemo(() => buildLocationCodeUrl(code), [code]);

  useEffect(() => {
    let cancelled = false;

    if (!payload) return undefined;

    QRCode.toDataURL(payload, { width: 220, margin: 1 })
      .then((url) => {
        if (!cancelled) setDataUrl(url);
      })
      .catch((err) => {
        console.error('Failed to render QR code:', err);
        if (!cancelled) setError('QR render failed');
      });

    return () => {
      cancelled = true;
    };
  }, [payload]);

  // An unbuildable payload (missing/misconfigured public URL) is DERIVED, not
  // stored — writing it from the effect would be a synchronous setState in an
  // effect. It must show the honest failure state rather than silently fall
  // back to encoding the bare code again, which would look like a working QR
  // but open nothing.
  const renderError = payload ? error : 'QR render failed';

  if (renderError) {
    return <div style={{ fontSize: 12, color: '#a92323' }}>{renderError}</div>;
  }

  if (!dataUrl) return null;

  return (
    <div style={{ marginTop: 10, textAlign: 'center' }}>
      <img src={dataUrl} alt={`QR code for ${code}`} style={{ width: 160, height: 160 }} />
      <div style={{ fontSize: 12, fontWeight: 700, marginTop: 4, letterSpacing: 1 }}>{code}</div>
    </div>
  );
};

const AdminLocationCodesScreen = () => {
  const { lang } = useLang();
  const { buildings, maps, routePoints, loadBuildings, loadMaps, loadRoutePoints } = useAdmin();

  const isRTL = lang === 'ar' || lang === 'he';
  const t = UI[lang];

  const [codes, setCodes] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [view, setView] = useState('list'); // 'list' | 'add' | 'edit'
  const [expandedQr, setExpandedQr] = useState(null);
  const [confirmId, setConfirmId] = useState(null);
  const [isSavingEdit, setIsSavingEdit] = useState(false);

  const [form, setForm] = useState({
    buildingId: '', mapId: '', routePointId: '', code: '', label: '',
  });

  // Edit form — kept fully separate from the Add form's `form` state so
  // opening Edit on one entry can never leak into (or be reset by) the
  // Add flow, and vice versa. Nothing here writes to the database on its
  // own — only handleSaveEdit's explicit PUT call does, and only once
  // Save is pressed.
  const [editForm, setEditForm] = useState(null);

  // FLOOR ISOLATION. A LocationCode belongs to exactly one floor map
  // (LocationCode.map_id), but this page used to call getLocationCodes()
  // with no filter at all — so an admin working on the Ground Floor saw
  // every code in the system interleaved, and a floor with many more
  // codes visually swamped the one they were looking at. It reads as
  // "another floor replaced my codes"; nothing was ever replaced.
  //
  // The scope is applied SERVER-side (map_id/building_id query params the
  // endpoint already supports) rather than by filtering a full list in
  // the browser, so the page can never render a code from another floor
  // even for one frame.
  const [scopeBuildingId, setScopeBuildingId] = useState('');
  const [scopeMapId, setScopeMapId] = useState('');

  const loadCodes = async (scope) => {
    setLoading(true);
    setError('');
    try {
      const filters = {};
      const buildingId = scope ? scope.buildingId : scopeBuildingId;
      const mapId = scope ? scope.mapId : scopeMapId;

      // A map_id already implies its building, so the narrower filter
      // wins and the two can never contradict each other.
      if (mapId) filters.map_id = mapId;
      else if (buildingId) filters.building_id = buildingId;

      const data = await getLocationCodes(filters);
      setCodes(Array.isArray(data) ? data : []);
    } catch (err) {
      console.error('Failed to load location codes:', err);
      setError(t.loadError);
    } finally {
      setLoading(false);
    }
  };

  const handleScopeBuildingChange = (buildingId) => {
    setScopeBuildingId(buildingId);
    setScopeMapId('');
    loadCodes({ buildingId, mapId: '' });
  };

  const handleScopeMapChange = (mapId) => {
    setScopeMapId(mapId);
    loadCodes({ buildingId: scopeBuildingId, mapId });
  };

  useEffect(() => {
    // Buildings/Maps/RoutePoints live in AdminContext and are normally
    // loaded once when the app mounts. If an admin (or the "Initialize
    // Project Data" backfill on the Dashboard, in a different tab/session)
    // changed those relationships since this app instance loaded, this
    // screen would otherwise keep showing stale data with no way to
    // refresh it short of a full page reload — so it explicitly re-loads
    // all three every time it's opened, in addition to the location codes
    // themselves.
    loadCodes();
    loadBuildings();
    loadMaps();
    loadRoutePoints();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const buildingById = useMemo(
    () => Object.fromEntries(buildings.map((b) => [normalizeId(b.id), b])),
    [buildings]
  );
  const mapById = useMemo(
    () => Object.fromEntries(maps.map((m) => [normalizeId(m.id), m])),
    [maps]
  );
  const pointById = useMemo(
    () => Object.fromEntries(routePoints.map((p) => [normalizeId(p.id), p])),
    [routePoints]
  );

  const buildingOptions = useMemo(() => buildBuildingOptions(buildings), [buildings]);

  // Floor maps available to the scope filter, for the building it is
  // currently narrowed to. Reuses the same helpers the Add/Edit forms use
  // so the two selectors can never disagree about which maps belong to a
  // building.
  const scopeMapsForBuilding = useMemo(
    () => filterMapsForBuilding(maps, scopeBuildingId),
    [maps, scopeBuildingId]
  );
  const scopeMapOptions = useMemo(
    () => buildMapOptions(scopeMapsForBuilding),
    [scopeMapsForBuilding]
  );

  const mapsForSelectedBuilding = useMemo(
    () => filterMapsForBuilding(maps, form.buildingId),
    [maps, form.buildingId]
  );
  const mapOptions = useMemo(
    () => buildMapOptions(mapsForSelectedBuilding),
    [mapsForSelectedBuilding]
  );

  const pointsForSelectedMap = useMemo(
    () => filterEntrancePointsForMap(routePoints, form.mapId),
    [routePoints, form.mapId]
  );
  const pointOptions = useMemo(
    () => buildRoutePointOptions(pointsForSelectedMap),
    [pointsForSelectedMap]
  );

  const noMapsForBuilding = Boolean(form.buildingId) && mapsForSelectedBuilding.length === 0;
  const noEntranceForMap = hasNoEntranceForSelectedMap(routePoints, form.mapId);

  // ── Edit form — Building/Map/RoutePoint selectors all read the same
  // real backend data (buildings/maps/routePoints from AdminContext) as
  // the Add form above; only the RoutePoint filter differs (every active
  // point on the map, not just entrances — see filterPointsForMap).
  const editMapsForSelectedBuilding = useMemo(
    () => filterMapsForBuilding(maps, editForm?.buildingId),
    [maps, editForm?.buildingId]
  );
  const editMapOptions = useMemo(
    () => buildMapOptions(editMapsForSelectedBuilding),
    [editMapsForSelectedBuilding]
  );

  const editPointsForSelectedMap = useMemo(
    () => filterPointsForMap(routePoints, editForm?.mapId),
    [routePoints, editForm?.mapId]
  );
  const editPointOptions = useMemo(
    () => buildRoutePointOptions(editPointsForSelectedMap),
    [editPointsForSelectedMap]
  );

  // "When a Map is selected: derive its building, map group, and floor
  // automatically" — read straight off the selected Map's own real
  // fields, never re-entered or independently editable.
  const editSelectedMap = editForm?.mapId ? mapById[normalizeId(editForm.mapId)] : null;
  const editDerivedInfo = useMemo(
    () => resolveMapDerivedInfo(editSelectedMap),
    [editSelectedMap]
  );

  const editNoMapsForBuilding = Boolean(editForm?.buildingId) && editMapsForSelectedBuilding.length === 0;
  const editNoPointsForMap = hasNoPointsForMap(routePoints, editForm?.mapId);

  // The entry's current route point may no longer be in the selectable
  // (active) list — surfaced explicitly rather than letting the select
  // silently show a blank/mismatched option, matching the "legacy
  // reference" warning pattern used elsewhere in the admin UI.
  const editCurrentPointMissing = Boolean(
    editForm?.routePointId &&
      editPointOptions.length > 0 &&
      !editPointOptions.some((opt) => opt.value === editForm.routePointId)
  );

  const openAdd = () => {
    setForm({ buildingId: '', mapId: '', routePointId: '', code: '', label: '' });
    setError('');
    setView('add');
  };

  const openEdit = (entry) => {
    setEditForm(buildEditFormFromEntry(entry));
    setError('');
    setView('edit');
  };

  const handleSaveEdit = async () => {
    if (!editForm) return;
    setError('');

    if (!isEditSaveEnabled(editForm)) {
      setError(t.saveError);
      return;
    }

    setIsSavingEdit(true);

    try {
      // Only fires now, on explicit Save — every selector change above
      // only ever updates local editForm state.
      await updateLocationCode(editForm.id, buildEditSavePayload(editForm));
      await loadCodes();
      setEditForm(null);
      setView('list');
    } catch (err) {
      console.error('Failed to save location code:', err);
      setError(err.message || t.saveError);
    } finally {
      setIsSavingEdit(false);
    }
  };

  const handleSave = async (useGenerate) => {
    setError('');

    if (useGenerate) {
      if (!isGenerateEnabled(form)) {
        setError(t.selectPoint);
        return;
      }
    } else if (!isManualSaveEnabled(form)) {
      setError(t.saveError);
      return;
    }

    try {
      if (useGenerate) {
        await generateLocationCode(buildGeneratePayload(form));
      } else {
        // building_id/map_id/route_point_id are read straight from the
        // selected ids (never from display text) and normalized to
        // strings, so the request the backend validates is exactly what
        // the three dropdowns actually selected.
        await createLocationCode(buildManualSavePayload(form));
      }

      await loadCodes();
      setView('list');
    } catch (err) {
      console.error('Failed to save location code:', err);
      setError(err.message || t.saveError);
    }
  };

  const handleToggleActive = async (entry) => {
    try {
      await updateLocationCode(entry.id, { is_active: !entry.is_active });
      await loadCodes();
    } catch (err) {
      console.error('Failed to toggle location code:', err);
      setError(err.message || t.saveError);
    }
  };

  const handleDelete = async (id) => {
    try {
      await deleteLocationCode(id);
      setConfirmId(null);
      await loadCodes();
    } catch (err) {
      console.error('Failed to delete location code:', err);
      setError(err.message || t.deleteError);
      setConfirmId(null);
    }
  };

  return (
    <div className="qrd-page">
      <div className="qrd-pagebody" dir={isRTL ? 'rtl' : 'ltr'}>

        <div className="qrd-headwrap">
          <AdminScreenHeader
            pageKey="locationCodes"
            onBack={view !== 'list' ? () => setView('list') : undefined}
          />
        </div>

        <div className="adm-content">
          {error && (
            <div style={{ marginBottom: 16, padding: 12, borderRadius: 12, background: '#ffe9e9', color: '#a92323', fontSize: 14 }}>
              {error}
            </div>
          )}

          {view === 'list' && (
            <>
              <div className="adm-btn-row">
                <button className="adm-btn adm-btn-primary" onClick={openAdd}>
                  {t.addBtn}
                </button>
              </div>

              {/* Floor scope. Defaults to everything so nothing an admin
                  could previously see disappears without them choosing —
                  but the moment a building/floor is picked, the list is
                  re-fetched narrowed to that exact map, which is what
                  makes "Ground Floor shows Ground Floor codes" true. */}
              <div
                className="adm-form-row"
                style={{ gap: 10, marginBottom: 12, flexWrap: 'wrap' }}
              >
                <div className="adm-form-group" style={{ minWidth: 200, flex: 1 }}>
                  <label className="adm-form-label">{t.scopeLabel}</label>
                  <select
                    className="adm-form-select"
                    value={scopeBuildingId}
                    onChange={(event) => handleScopeBuildingChange(event.target.value)}
                  >
                    <option value="">{t.scopeAllBuildings}</option>
                    {buildingOptions.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                </div>

                <div className="adm-form-group" style={{ minWidth: 200, flex: 1 }}>
                  <label className="adm-form-label">{t.fields.floor}</label>
                  <select
                    className="adm-form-select"
                    value={scopeMapId}
                    disabled={!scopeBuildingId}
                    onChange={(event) => handleScopeMapChange(event.target.value)}
                  >
                    <option value="">{t.scopeAllFloors}</option>
                    {scopeMapOptions.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                </div>
              </div>

              <div style={{ fontSize: 12, color: '#5a7a9f', marginBottom: 12 }}>
                {t.scopeHint}
              </div>

              <div className="adm-section-row">
                <span className="adm-section-lbl">{t.section}</span>
                <span className="adm-section-count">{t.count(codes.length)}</span>
              </div>

              {loading ? (
                <div className="adm-empty"><div className="adm-empty-txt">{t.loading}</div></div>
              ) : codes.length === 0 ? (
                <div className="adm-empty">
                  <div className="adm-empty-icon"><CodeIcon /></div>
                  <div className="adm-empty-txt">
                    {scopeMapId ? t.scopeEmptyForFloor : t.empty}
                  </div>
                  <div className="adm-empty-hint">{t.emptyHint}</div>
                </div>
              ) : (
                <div className="adm-list">
                  {codes.map((entry) => {
                    const building = buildingById[normalizeId(entry.building_id)];
                    const map = mapById[normalizeId(entry.map_id)];
                    const point = pointById[normalizeId(entry.route_point_id)];

                    return (
                      <div key={entry.id} className="adm-list-item">
                        <div className="adm-list-item-row">
                          <div className="adm-list-item-info">
                            <div className="adm-list-item-name">
                              {entry.label || point?.name || entry.code}
                              {!entry.is_active && (
                                <span className="adm-tag" style={{ marginLeft: 8, background: '#f3d9d9', color: '#a92323' }}>
                                  {t.inactive}
                                </span>
                              )}
                            </div>
                            <div className="adm-list-item-meta">
                              <span className="adm-tag adm-tag-blue">{entry.code}</span>
                              <span className="adm-tag-txt">
                                {(building?.nameEn || '—')} · {(map?.title || '—')} · {formatFloorDisplay(entry.floor ?? map?.floor, map?.floor_label)} · {(point?.name || '—')}
                              </span>
                            </div>
                          </div>
                          <div className="adm-list-item-acts">
                            <button className="adm-icon-btn" onClick={() => openEdit(entry)} title={t.edit}>
                              <EditIcon />
                            </button>
                            <button className="adm-icon-btn" onClick={() => setExpandedQr(expandedQr === entry.id ? null : entry.id)} title={t.showQr}>
                              <CodeIcon />
                            </button>
                            <button className="adm-icon-btn" onClick={() => handleToggleActive(entry)} title={entry.is_active ? t.deactivate : t.activate}>
                              {entry.is_active ? '⏸' : '▶'}
                            </button>
                            <button className="adm-icon-btn adm-icon-btn-danger"
                              onClick={() => setConfirmId(confirmId === entry.id ? null : entry.id)} title={t.delete}>
                              ✕
                            </button>
                          </div>
                        </div>

                        {expandedQr === entry.id && <QrPreview code={entry.code} />}

                        {confirmId === entry.id && (
                          <div className="adm-delete-strip">
                            <span className="adm-delete-strip-msg">{t.confirmDelete}</span>
                            <div className="adm-delete-strip-acts">
                              <button className="adm-btn adm-btn-cancel" style={{ padding: '5px 12px', fontSize: 12 }} onClick={() => setConfirmId(null)}>
                                {t.cancel}
                              </button>
                              <button className="adm-btn adm-btn-confirm-delete" style={{ padding: '5px 12px', fontSize: 12 }} onClick={() => handleDelete(entry.id)}>
                                {t.yes}
                              </button>
                            </div>
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </>
          )}

          {view === 'add' && (
            <div className="adm-form-card">
              <div className="adm-form-card-title">{t.addBtn}</div>

              <div className="adm-form-group">
                <label className="adm-form-label">{t.fields.building}</label>
                <select className="adm-form-select" value={form.buildingId}
                  onChange={(e) => setForm((p) => resetOnBuildingChange(p, e.target.value))}>
                  <option value="">{t.selectBuilding}</option>
                  {buildingOptions.map((opt) => (
                    <option key={opt.value} value={opt.value}>{opt.label}</option>
                  ))}
                </select>
              </div>

              <div className="adm-form-group">
                <label className="adm-form-label">{t.fields.map}</label>
                <select className="adm-form-select" value={form.mapId}
                  disabled={!form.buildingId}
                  onChange={(e) => setForm((p) => resetOnMapChange(p, e.target.value))}>
                  <option value="">{t.selectMap}</option>
                  {mapOptions.map((opt) => (
                    <option key={opt.value} value={opt.value}>{opt.label}</option>
                  ))}
                </select>
                {noMapsForBuilding && (
                  <div className="adm-form-hint">{t.noMapsForBuilding}</div>
                )}
              </div>

              <div className="adm-form-group">
                <label className="adm-form-label">{t.fields.point}</label>
                <select className="adm-form-select" value={form.routePointId}
                  disabled={!form.mapId}
                  onChange={(e) => setForm((p) => ({ ...p, routePointId: e.target.value }))}>
                  <option value="">{t.selectPoint}</option>
                  {pointOptions.map((opt) => (
                    <option key={opt.value} value={opt.value}>{opt.label}</option>
                  ))}
                </select>
                {noEntranceForMap && (
                  <div className="adm-form-hint">{t.noEntranceForMap}</div>
                )}
              </div>

              <div className="adm-form-group">
                <label className="adm-form-label">{t.fields.label}</label>
                <input className="adm-form-input" value={form.label}
                  onChange={(e) => setForm((p) => ({ ...p, label: e.target.value }))}
                  placeholder="e.g. Main Entrance Kiosk" />
              </div>

              <div className="adm-form-group">
                <label className="adm-form-label">{t.fields.code}</label>
                <input className="adm-form-input" value={form.code}
                  onChange={(e) => setForm((p) => ({ ...p, code: e.target.value }))}
                  placeholder="QR-KIOSK-01" />
              </div>

              <div className="adm-form-actions">
                <button className="adm-btn adm-btn-cancel" onClick={() => setView('list')}>
                  {t.cancel}
                </button>
                <button className="adm-btn adm-btn-primary" onClick={() => handleSave(true)} disabled={!isGenerateEnabled(form)}>
                  {t.generateBtn}
                </button>
                <button className="adm-btn adm-btn-primary" onClick={() => handleSave(false)} disabled={!isManualSaveEnabled(form)}>
                  {t.save}
                </button>
              </div>
            </div>
          )}

          {view === 'edit' && editForm && (
            <div className="adm-form-card">
              <div className="adm-form-card-title">{t.editTitle}</div>

              <div className="adm-form-group">
                <label className="adm-form-label">{t.codeReadOnly}</label>
                <input className="adm-form-input" value={editForm.code} disabled readOnly />
              </div>

              <div className="adm-form-group">
                <label className="adm-form-label">{t.fields.label}</label>
                <input className="adm-form-input" value={editForm.label}
                  onChange={(e) => setEditForm((p) => ({ ...p, label: e.target.value }))}
                  placeholder="e.g. Main Entrance Kiosk" />
              </div>

              <div className="adm-form-group">
                <label className="adm-form-label">{t.fields.building}</label>
                <select className="adm-form-select" value={editForm.buildingId}
                  onChange={(e) => setEditForm((p) => resetOnBuildingChange(p, e.target.value))}>
                  <option value="">{t.selectBuilding}</option>
                  {buildingOptions.map((opt) => (
                    <option key={opt.value} value={opt.value}>{opt.label}</option>
                  ))}
                </select>
              </div>

              <div className="adm-form-group">
                <label className="adm-form-label">{t.fields.map}</label>
                <select className="adm-form-select" value={editForm.mapId}
                  disabled={!editForm.buildingId}
                  onChange={(e) => setEditForm((p) => resetOnMapChange(p, e.target.value))}>
                  <option value="">{t.selectMap}</option>
                  {editMapOptions.map((opt) => (
                    <option key={opt.value} value={opt.value}>{opt.label}</option>
                  ))}
                </select>
                {editNoMapsForBuilding && (
                  <div className="adm-form-hint">{t.noMapsForBuilding}</div>
                )}
              </div>

              {/* "When a Map is selected: derive its building, map group,
                  and floor automatically" — read-only, always in sync
                  with the Map dropdown above; never independently set. */}
              <div className="adm-form-row">
                <div className="adm-form-group">
                  <label className="adm-form-label">{t.fields.mapGroup}</label>
                  <input className="adm-form-input"
                    value={editDerivedInfo.mapGroupCode || editDerivedInfo.mapGroupId || '—'}
                    disabled readOnly />
                </div>
                <div className="adm-form-group">
                  <label className="adm-form-label">{t.fields.floor}</label>
                  <input className="adm-form-input" value={editDerivedInfo.floorDisplay} disabled readOnly />
                </div>
              </div>
              {editForm.mapId && (
                <div className="adm-form-hint" style={{ marginTop: -8, marginBottom: 12 }}>
                  {t.derivedHint}
                </div>
              )}

              <div className="adm-form-group">
                <label className="adm-form-label">{t.fields.pointEdit}</label>
                <select className="adm-form-select" value={editForm.routePointId}
                  disabled={!editForm.mapId}
                  onChange={(e) => setEditForm((p) => ({ ...p, routePointId: e.target.value }))}>
                  <option value="">{t.selectPoint}</option>
                  {editPointOptions.map((opt) => (
                    <option key={opt.value} value={opt.value}>{opt.label}</option>
                  ))}
                </select>
                {editNoPointsForMap && (
                  <div className="adm-form-hint">{t.noPointsForMap}</div>
                )}
                {editCurrentPointMissing && (
                  <div className="adm-setup-card-error" style={{ marginTop: 6 }}>
                    {t.noPointsForMap}
                  </div>
                )}
              </div>

              <div className="adm-form-group">
                <label className="adm-form-label" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <input type="checkbox" checked={editForm.isActive}
                    onChange={(e) => setEditForm((p) => ({ ...p, isActive: e.target.checked }))} />
                  {t.fields.active}
                </label>
              </div>

              <div className="adm-form-actions">
                <button className="adm-btn adm-btn-cancel"
                  onClick={() => { setEditForm(null); setView('list'); }}>
                  {t.cancel}
                </button>
                <button className="adm-btn adm-btn-primary" onClick={handleSaveEdit}
                  disabled={!isEditSaveEnabled(editForm) || isSavingEdit}>
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

export default AdminLocationCodesScreen;
