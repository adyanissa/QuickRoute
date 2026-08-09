import { useEffect, useMemo, useState, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { useLang } from '../../context/LangContext';
import { useAdmin } from '../../context/AdminContext';
import { useAuth } from '../../context/AuthContext';
import { getRoutePointCount } from '../../api/routePointsApi';
import { getMapGroups } from '../../api/mapGroupsApi';
import { isForbiddenError, resolveApiErrorMessage } from '../../utils/apiErrors';
import { groupBuildingsByCampus } from '../../utils/dashboardHierarchy';
import {
  ShieldIcon,
  MapIcon,
  LocationIcon,
  RoomIcon,
  RouteIcon,
  CodeIcon,
  KeyIcon,
  LogoutIcon,
  PinIcon,
  ScopedStat,
  Breadcrumbs,
  HierarchyRow,
  DashboardEmptyState,
  DashboardErrorState,
  DashboardLoadingState,
  LangPill,
} from '../../components/dashboard/DashboardPrimitives';
import '../../styles/adminScreens.css';

// RBAC/dashboard cleanup task (frontend completion), Section 3/4/10 — the
// Super Admin experience: a real hierarchy browser (All Locations ->
// Campus -> Building -> Map Group/Floor -> Map Workspace) with breadcrumbs
// and level-scoped metrics, replacing the old single flat dashboard's
// "everything unscoped in one screen" layout. Preserves the pre-existing
// blue-gradient/rounded-card/typography/icon identity (adm-* classes,
// unchanged) — only the content structure is new.
//
// "Unassigned location" (exact strings from the task spec) is used for
// every Building whose `campus` field is empty/whitespace-only — grouping
// is always derived from real Building.campus values, never a
// hardcoded/demo name (e.g. the old "Rabin Medical Center" placeholder
// this task explicitly forbids reintroducing).
const UI = {
  en: {
    badge: 'Super Admin',
    title: 'All Locations',
    rooms: 'rooms',
    allLocations: 'All Locations',
    unassigned: 'Unassigned location',
    campusLevel: 'Campus',
    buildingLevel: 'Building',
    mapGroupLevel: 'Map Group',
    buildings: 'Buildings',
    floors: 'Floors',
    nodesGlobal: (n) => `All locations: ${n} nodes`,
    nodesScoped: (n) => `${n} nodes`,
    loading: 'Loading…',
    loadError: 'Failed to load dashboard data',
    forbidden: 'You do not have permission to view this.',
    emptyLocations: 'No buildings yet',
    emptyLocationsHint: 'Create a building to get started',
    emptyMapGroups: 'No map groups in this building yet',
    emptyMaps: 'No floors in this map group yet',
    section: 'Management',
    map: { title: 'Map Management', desc: 'Upload, edit and manage every map' },
    loc: { title: 'Locations', desc: 'Create and manage all buildings & centers' },
    room: { title: 'Rooms & Destinations', desc: 'Manage clinics, wards, labs and offices' },
    route: { title: 'Route Points', desc: 'Manage navigation nodes and path data' },
    codes: { title: 'Location Codes', desc: 'Barcode/QR codes for user start points' },
    invites: { title: 'Invitation Codes', desc: 'Create signup codes, assign roles and building scope' },
    cleanup: { title: 'Navigation Data Cleanup', desc: 'Remove generated data or fully reset navigation on one or more maps' },
    logout: 'Logout',
    back: 'Back',
  },
  ar: {
    badge: 'مشرف عام',
    title: 'كل المواقع',
    rooms: 'غرف',
    allLocations: 'كل المواقع',
    unassigned: 'موقع غير معيّن',
    campusLevel: 'الحرم',
    buildingLevel: 'المبنى',
    mapGroupLevel: 'مجموعة الخرائط',
    buildings: 'مبانٍ',
    floors: 'طوابق',
    nodesGlobal: (n) => `كل المواقع: ${n} عقدة`,
    nodesScoped: (n) => `${n} عقدة`,
    loading: 'جارٍ التحميل…',
    loadError: 'فشل تحميل بيانات اللوحة',
    forbidden: 'ليست لديك صلاحية لعرض هذا.',
    emptyLocations: 'لا توجد مبانٍ بعد',
    emptyLocationsHint: 'أنشئ مبنى للبدء',
    emptyMapGroups: 'لا توجد مجموعات خرائط في هذا المبنى بعد',
    emptyMaps: 'لا توجد طوابق في مجموعة الخرائط هذه بعد',
    section: 'الإدارة',
    map: { title: 'إدارة الخريطة', desc: 'تحميل وتعديل وإدارة كل الخرائط' },
    loc: { title: 'المواقع', desc: 'إنشاء وإدارة كل المباني والمراكز' },
    room: { title: 'الغرف والوجهات', desc: 'إدارة العيادات والأجنحة والمختبرات' },
    route: { title: 'نقاط المسار', desc: 'إدارة عقد التنقل والمسارات' },
    codes: { title: 'رموز المواقع', desc: 'رموز باركود/QR لنقاط بدء المستخدم' },
    invites: { title: 'رموز الدعوة', desc: 'إنشاء رموز تسجيل وتحديد الأدوار ونطاق المباني' },
    cleanup: { title: 'تنظيف بيانات المسارات', desc: 'حذف البيانات المولّدة أو إعادة ضبط بيانات المسارات بالكامل في خريطة أو أكثر' },
    logout: 'تسجيل خروج',
    back: 'رجوع',
  },
  he: {
    badge: 'מנהל-על',
    title: 'כל המיקומים',
    rooms: 'חדרים',
    allLocations: 'כל המיקומים',
    unassigned: 'מיקום לא משויך',
    campusLevel: 'קמפוס',
    buildingLevel: 'מבנה',
    mapGroupLevel: 'קבוצת מפות',
    buildings: 'מבנים',
    floors: 'קומות',
    nodesGlobal: (n) => `כל המיקומים: ${n} צמתים`,
    nodesScoped: (n) => `${n} צמתים`,
    loading: 'טוען…',
    loadError: 'טעינת נתוני הלוח נכשלה',
    forbidden: 'אין לך הרשאה לצפות בזה.',
    emptyLocations: 'אין עדיין מבנים',
    emptyLocationsHint: 'צור מבנה כדי להתחיל',
    emptyMapGroups: 'אין עדיין קבוצות מפות במבנה זה',
    emptyMaps: 'אין עדיין קומות בקבוצת המפות הזו',
    section: 'ניהול',
    map: { title: 'ניהול מפה', desc: 'העלאה, עריכה וניהול של כל המפות' },
    loc: { title: 'מיקומים', desc: 'יצירה וניהול של כל המבנים והמרכזים' },
    room: { title: 'חדרים ויעדים', desc: 'ניהול מרפאות, אגפים ומעבדות' },
    route: { title: 'נקודות מסלול', desc: 'ניהול צמתי ניווט ומסלולים' },
    codes: { title: 'קודי מיקום', desc: 'קודי ברקוד/QR לנקודות התחלה' },
    invites: { title: 'קודי הזמנה', desc: 'צור קודי הרשמה, הקצה תפקידים והיקף מבנים' },
    cleanup: { title: 'ניקוי נתוני ניווט', desc: 'הסרת נתונים שנוצרו אוטומטית או איפוס מלא של נתוני הניווט במפה אחת או יותר' },
    logout: 'התנתק',
    back: 'חזרה',
  },
};

const SuperAdminDashboard = () => {
  const { lang, setLang } = useLang();
  const navigate = useNavigate();
  const { buildings, buildingsLoading, rooms, routePoints, loadBuildings } = useAdmin();
  const { logout } = useAuth();

  const isRTL = lang === 'ar' || lang === 'he';
  const t = UI[lang] || UI.en;

  const [selectedCampus, setSelectedCampus] = useState(null);
  const [selectedBuildingId, setSelectedBuildingId] = useState(null);
  const [selectedMapGroupId, setSelectedMapGroupId] = useState(null);

  const [globalNodeCount, setGlobalNodeCount] = useState(null);
  const [campusNodeCounts, setCampusNodeCounts] = useState({});
  const [buildingNodeCounts, setBuildingNodeCounts] = useState({});
  const [mapNodeCounts, setMapNodeCounts] = useState({});
  const [mapGroupsForBuilding, setMapGroupsForBuilding] = useState([]);
  const [mapGroupsLoading, setMapGroupsLoading] = useState(false);
  const [error, setError] = useState('');

  const campusGroups = useMemo(
    () => groupBuildingsByCampus(buildings, t.unassigned),
    [buildings, t.unassigned],
  );

  // Global "All locations" count — the one figure that IS allowed to be
  // system-wide, and is always explicitly labeled as such (never shown
  // next to a scoped count without the label).
  useEffect(() => {
    let cancelled = false;
    getRoutePointCount({})
      .then((res) => { if (!cancelled) setGlobalNodeCount(res.count); })
      .catch((err) => {
        if (!cancelled && !isForbiddenError(err)) setGlobalNodeCount(null);
      });
    return () => { cancelled = true; };
  }, []);

  // Campus-level metrics: sum of each member building's own scoped count
  // (RoutePointCountResponse has no native "campus" filter — campus is a
  // display grouping, not a security/query boundary — so this is the
  // honest way to aggregate it without ever inventing a fake endpoint).
  useEffect(() => {
    let cancelled = false;
    const loadCampusCounts = async () => {
      const entries = await Promise.all(
        Array.from(campusGroups.entries()).map(async ([campusKey, campusBuildings]) => {
          const counts = await Promise.all(
            campusBuildings.map((b) =>
              getRoutePointCount({ building_id: b.id }).then((r) => r.count).catch(() => 0),
            ),
          );
          return [campusKey, counts.reduce((sum, n) => sum + n, 0)];
        }),
      );
      if (!cancelled) setCampusNodeCounts(Object.fromEntries(entries));
    };
    if (campusGroups.size > 0) loadCampusCounts();
    return () => { cancelled = true; };
  }, [campusGroups]);

  // Building-level metrics — loaded lazily, only for buildings actually
  // visible at the currently selected campus level (never all buildings
  // system-wide up front).
  useEffect(() => {
    if (!selectedCampus) return undefined;
    let cancelled = false;
    const campusBuildings = campusGroups.get(selectedCampus) || [];
    Promise.all(
      campusBuildings.map((b) =>
        getRoutePointCount({ building_id: b.id }).then((r) => [b.id, r.count]).catch(() => [b.id, null]),
      ),
    ).then((entries) => {
      if (!cancelled) setBuildingNodeCounts((prev) => ({ ...prev, ...Object.fromEntries(entries) }));
    });
    return () => { cancelled = true; };
  }, [selectedCampus, campusGroups]);

  // Map Groups for the selected building.
  useEffect(() => {
    if (!selectedBuildingId) {
      setMapGroupsForBuilding([]);
      return undefined;
    }
    let cancelled = false;
    setMapGroupsLoading(true);
    setError('');
    getMapGroups(selectedBuildingId)
      .then((groups) => { if (!cancelled) setMapGroupsForBuilding(groups); })
      .catch((err) => {
        if (!cancelled) {
          setMapGroupsForBuilding([]);
          setError(resolveApiErrorMessage(err, t));
        }
      })
      .finally(() => { if (!cancelled) setMapGroupsLoading(false); });
    return () => { cancelled = true; };
  }, [selectedBuildingId, t]);

  // Per-floor (Map) node counts for the selected Map Group.
  useEffect(() => {
    if (!selectedMapGroupId) return undefined;
    const group = mapGroupsForBuilding.find((g) => g.id === selectedMapGroupId);
    if (!group) return undefined;
    let cancelled = false;
    Promise.all(
      (group.floors || []).map((floor) =>
        getRoutePointCount({ map_id: floor.id }).then((r) => [floor.id, r.count]).catch(() => [floor.id, null]),
      ),
    ).then((entries) => {
      if (!cancelled) setMapNodeCounts((prev) => ({ ...prev, ...Object.fromEntries(entries) }));
    });
    return () => { cancelled = true; };
  }, [selectedMapGroupId, mapGroupsForBuilding]);

  const goToAllLocations = useCallback(() => {
    setSelectedCampus(null);
    setSelectedBuildingId(null);
    setSelectedMapGroupId(null);
  }, []);

  const goToCampus = useCallback((campusKey) => {
    setSelectedCampus(campusKey);
    setSelectedBuildingId(null);
    setSelectedMapGroupId(null);
  }, []);

  const goToBuilding = useCallback((buildingId) => {
    setSelectedBuildingId(buildingId);
    setSelectedMapGroupId(null);
  }, []);

  const handleLogout = () => {
    logout();
    navigate('/screen/02');
  };

  const selectedBuilding = buildings.find((b) => b.id === selectedBuildingId) || null;
  const selectedMapGroup = mapGroupsForBuilding.find((g) => g.id === selectedMapGroupId) || null;

  const breadcrumbItems = [{ label: t.allLocations, onClick: goToAllLocations }];
  if (selectedCampus) breadcrumbItems.push({ label: selectedCampus, onClick: () => goToCampus(selectedCampus) });
  if (selectedBuilding) {
    breadcrumbItems.push({
      label: selectedBuilding.nameEn || selectedBuilding.name,
      onClick: () => goToBuilding(selectedBuilding.id),
    });
  }
  if (selectedMapGroup) breadcrumbItems.push({ label: selectedMapGroup.name || t.mapGroupLevel });

  return (
    <div className="layout-wrapper">
      <div className="layout-shell adm-shell" dir={isRTL ? 'rtl' : 'ltr'}>
        <div className="adm-header">
          <div className="adm-topbar">
            <div className="adm-logo-row">
              <span className="adm-wordmark">Quick<span>Route</span></span>
            </div>
            <LangPill lang={lang} setLang={setLang} />
          </div>

          <div className="adm-header-badge"><ShieldIcon /> {t.badge}</div>
          <h1 className="adm-header-title">{t.title}</h1>

          <Breadcrumbs items={breadcrumbItems} isRTL={isRTL} />

          <div className="adm-stats-row">
            <ScopedStat
              value={globalNodeCount === null ? '—' : globalNodeCount}
              label={t.nodesGlobal(globalNodeCount ?? 0)}
              color="#c06030"
            />
            <ScopedStat value={buildings.length} label={t.buildings} color="#2a5298" />
          </div>
        </div>

        <div className="adm-content">
          {error && <DashboardErrorState message={error} />}

          {buildingsLoading && <DashboardLoadingState message={t.loading} />}

          {!buildingsLoading && !selectedCampus && (
            buildings.length === 0 ? (
              <DashboardEmptyState
                icon={<LocationIcon />}
                title={t.emptyLocations}
                hint={t.emptyLocationsHint}
              />
            ) : (
              <div className="adm-nav-cards">
                {Array.from(campusGroups.entries()).map(([campusKey, campusBuildings]) => (
                  <HierarchyRow
                    key={campusKey}
                    icon={<PinIcon />}
                    title={campusKey}
                    subtitle={`${campusBuildings.length} ${t.buildings.toLowerCase()}`}
                    metricValue={campusNodeCounts[campusKey] ?? '…'}
                    metricLabel={t.nodesScoped(campusNodeCounts[campusKey] ?? 0)}
                    onClick={() => goToCampus(campusKey)}
                    isRTL={isRTL}
                  />
                ))}
              </div>
            )
          )}

          {!buildingsLoading && selectedCampus && !selectedBuildingId && (
            <div className="adm-nav-cards">
              {(campusGroups.get(selectedCampus) || []).map((building) => (
                <HierarchyRow
                  key={building.id}
                  icon={<LocationIcon />}
                  title={building.nameEn || building.name}
                  subtitle={`${(rooms[building.id] || []).length} ${t.rooms}`}
                  metricValue={buildingNodeCounts[building.id] ?? '…'}
                  metricLabel={t.nodesScoped(buildingNodeCounts[building.id] ?? 0)}
                  onClick={() => goToBuilding(building.id)}
                  isRTL={isRTL}
                />
              ))}
            </div>
          )}

          {selectedBuildingId && !selectedMapGroupId && (
            mapGroupsLoading ? (
              <DashboardLoadingState message={t.loading} />
            ) : mapGroupsForBuilding.length === 0 ? (
              <DashboardEmptyState icon={<MapIcon />} title={t.emptyMapGroups} />
            ) : (
              <div className="adm-nav-cards">
                {mapGroupsForBuilding.map((group) => (
                  <HierarchyRow
                    key={group.id}
                    icon={<MapIcon />}
                    title={group.name || group.code || t.mapGroupLevel}
                    subtitle={`${group.floorCount || (group.floors || []).length} ${t.floors.toLowerCase()}`}
                    metricValue={group.floorCount || (group.floors || []).length}
                    metricLabel={t.floors}
                    onClick={() => setSelectedMapGroupId(group.id)}
                    isRTL={isRTL}
                  />
                ))}
              </div>
            )
          )}

          {selectedMapGroupId && selectedMapGroup && (
            (selectedMapGroup.floors || []).length === 0 ? (
              <DashboardEmptyState icon={<MapIcon />} title={t.emptyMaps} />
            ) : (
              <div className="adm-nav-cards">
                {(selectedMapGroup.floors || []).map((floor) => (
                  <HierarchyRow
                    key={floor.id}
                    icon={<MapIcon />}
                    title={floor.title || floor.floorLabel || `Floor ${floor.floor}`}
                    metricValue={mapNodeCounts[floor.id] ?? '…'}
                    metricLabel={t.nodesScoped(mapNodeCounts[floor.id] ?? 0)}
                    onClick={() => navigate(`/admin/map?mapId=${floor.id}`)}
                    isRTL={isRTL}
                  />
                ))}
              </div>
            )
          )}

          <div className="adm-section-row" style={{ marginTop: 24 }}>
            <span className="adm-section-lbl">{t.section}</span>
          </div>

          <div className="adm-nav-cards">
            <HierarchyRow icon={<MapIcon />} title={t.map.title} subtitle={t.map.desc}
              onClick={() => navigate('/admin/map')} isRTL={isRTL} />
            <HierarchyRow icon={<LocationIcon />} title={t.loc.title} subtitle={t.loc.desc}
              onClick={() => navigate('/admin/locations')} isRTL={isRTL} />
            <HierarchyRow icon={<RoomIcon />} title={t.room.title} subtitle={t.room.desc}
              onClick={() => navigate('/admin/rooms')} isRTL={isRTL} />
            <HierarchyRow icon={<RouteIcon />} title={t.route.title} subtitle={t.route.desc}
              onClick={() => navigate('/admin/routes')} isRTL={isRTL} />
            <HierarchyRow icon={<CodeIcon />} title={t.codes.title} subtitle={t.codes.desc}
              onClick={() => navigate('/admin/location-codes')} isRTL={isRTL} />
            <HierarchyRow icon={<KeyIcon />} title={t.invites.title} subtitle={t.invites.desc}
              onClick={() => navigate('/admin/invitation-codes')} isRTL={isRTL} />
            <HierarchyRow icon={<RouteIcon />} title={t.cleanup.title} subtitle={t.cleanup.desc}
              onClick={() => navigate('/admin/navigation-cleanup')} isRTL={isRTL} />
          </div>

          <button className="adm-logout-btn" onClick={handleLogout}>
            <LogoutIcon /> {t.logout}
          </button>
        </div>
      </div>
    </div>
  );
};

export default SuperAdminDashboard;
