import { useEffect, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { useLang } from '../../context/LangContext';
import { useAdmin } from '../../context/AdminContext';
import { useAuth } from '../../context/AuthContext';
import {
  ShieldIcon,
  MapIcon,
  LocationIcon,
  LogoutIcon,
  HierarchyRow,
  DashboardEmptyState,
  LangPill,
} from '../../components/dashboard/DashboardPrimitives';
import '../../styles/adminScreens.css';

// RBAC/dashboard cleanup task (frontend completion), Section 3 — the
// Building Manager experience: the narrowest of the three. Shows only
// this account's assigned buildings and, within each, only the Maps it
// is actually scoped to (map_ids, if set, is the most restrictive and
// wins; otherwise map_group_ids; otherwise every map in an assigned
// building) — mirrors the exact precedence backend/core/auth_deps.py's
// user_can_access_map already enforces, read here only for DISPLAY
// filtering, never as a substitute for that backend check.
//
// "exactly one Map assigned -> open it directly" is primarily handled by
// the login redirect (utils/roleRouting.js), but this screen re-checks it
// on mount too as a safety net for anyone who lands here directly (e.g.
// browser back button, bookmark) instead of through a fresh login.
const UI = {
  en: {
    badge: 'Building Manager',
    title: 'My Assigned Buildings',
    maps: (n) => `${n} map${n === 1 ? '' : 's'}`,
    loading: 'Loading…',
    empty: 'No buildings are assigned to your account yet',
    emptyHint: 'Contact a Super Admin or Global Manager to be assigned a building',
    noMaps: 'No maps assigned in this building yet',
    logout: 'Logout',
  },
  ar: {
    badge: 'مدير مبنى',
    title: 'مبانيّ المخصصة',
    maps: (n) => `${n} خريطة`,
    loading: 'جارٍ التحميل…',
    empty: 'لا توجد مبانٍ مخصصة لحسابك بعد',
    emptyHint: 'تواصل مع مشرف عام أو مدير عام لتخصيص مبنى لك',
    noMaps: 'لا توجد خرائط مخصصة في هذا المبنى بعد',
    logout: 'تسجيل خروج',
  },
  he: {
    badge: 'מנהל מבנה',
    title: 'המבנים המשויכים לי',
    maps: (n) => `${n} מפות`,
    loading: 'טוען…',
    empty: 'עדיין לא שויך מבנה לחשבון שלך',
    emptyHint: 'פנה למנהל-על או מנהל גלובלי כדי לשייך אליך מבנה',
    noMaps: 'עדיין לא שויכו מפות במבנה זה',
    logout: 'התנתק',
  },
};

const BuildingManagerDashboard = () => {
  const { lang, setLang } = useLang();
  const navigate = useNavigate();
  const { buildings, buildingsLoading, maps, loadMaps } = useAdmin();
  const { logout, user } = useAuth();

  const isRTL = lang === 'ar' || lang === 'he';
  const t = UI[lang] || UI.en;

  useEffect(() => {
    loadMaps();
  }, [loadMaps]);

  // Safety-net redirect (see file header) — replace: true so this never
  // leaves a dead "dashboard" entry in browser history the admin could
  // navigate back into and re-trigger.
  useEffect(() => {
    const mapIds = user?.map_ids || [];
    if (user?.role === 'building_manager' && mapIds.length === 1) {
      navigate(`/admin/map?mapId=${encodeURIComponent(mapIds[0])}`, { replace: true });
    }
  }, [user, navigate]);

  const mapsByBuilding = useMemo(() => {
    const mapIdsScope = user?.map_ids || [];
    const mapGroupIdsScope = user?.map_group_ids || [];
    const grouped = {};
    for (const building of buildings) {
      let buildingMaps = maps.filter((m) => m.buildingId === building.id);
      if (mapIdsScope.length > 0) {
        buildingMaps = buildingMaps.filter((m) => mapIdsScope.includes(m.id));
      } else if (mapGroupIdsScope.length > 0) {
        buildingMaps = buildingMaps.filter((m) => mapGroupIdsScope.includes(m.mapGroupId));
      }
      grouped[building.id] = buildingMaps;
    }
    return grouped;
  }, [buildings, maps, user]);

  const handleLogout = () => {
    logout();
    navigate('/screen/02');
  };

  return (
    <div className="layout-wrapper">
      <div className="layout-shell adm-shell" dir={isRTL ? 'rtl' : 'ltr'}>
        <div className="adm-header">
          <div className="adm-topbar">
            <span className="adm-wordmark">Quick<span>Route</span></span>
            <LangPill lang={lang} setLang={setLang} />
          </div>
          <div className="adm-header-badge"><ShieldIcon /> {t.badge}</div>
          <h1 className="adm-header-title">{t.title}</h1>
        </div>

        <div className="adm-content">
          {buildingsLoading ? (
            <div className="adm-empty"><div className="adm-empty-txt">{t.loading}</div></div>
          ) : buildings.length === 0 ? (
            <DashboardEmptyState icon={<LocationIcon />} title={t.empty} hint={t.emptyHint} />
          ) : (
            buildings.map((building) => {
              const buildingMaps = mapsByBuilding[building.id] || [];
              return (
                <div key={building.id} style={{ marginBottom: 20 }}>
                  <div
                    style={{
                      color: 'white',
                      fontWeight: 700,
                      fontSize: 14,
                      marginBottom: 8,
                      display: 'flex',
                      alignItems: 'center',
                      gap: 8,
                    }}
                  >
                    <LocationIcon /> {building.nameEn || building.name}
                    <span style={{ opacity: 0.75, fontWeight: 500, fontSize: 12 }}>
                      {t.maps(buildingMaps.length)}
                    </span>
                  </div>

                  {buildingMaps.length === 0 ? (
                    <DashboardEmptyState icon={<MapIcon />} title={t.noMaps} />
                  ) : (
                    <div className="adm-nav-cards">
                      {buildingMaps.map((map) => (
                        <HierarchyRow
                          key={map.id}
                          icon={<MapIcon />}
                          title={map.title || map.floorLabel || `Floor ${map.floor ?? ''}`}
                          onClick={() => navigate(`/admin/map?mapId=${map.id}`)}
                          isRTL={isRTL}
                        />
                      ))}
                    </div>
                  )}
                </div>
              );
            })
          )}

          <button className="adm-logout-btn" onClick={handleLogout}>
            <LogoutIcon /> {t.logout}
          </button>
        </div>
      </div>
    </div>
  );
};

export default BuildingManagerDashboard;
