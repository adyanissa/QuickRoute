import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useLang } from '../../context/LangContext';
import { useAdmin } from '../../context/AdminContext';
import { useAuth } from '../../context/AuthContext';
import { getRoutePointCount } from '../../api/routePointsApi';
import {
  ShieldIcon,
  MapIcon,
  LocationIcon,
  RoomIcon,
  RouteIcon,
  CodeIcon,
  KeyIcon,
  LogoutIcon,
  ScopedStat,
  HierarchyRow,
  DashboardEmptyState,
  LangPill,
} from '../../components/dashboard/DashboardPrimitives';
import '../../styles/adminScreens.css';

// RBAC/dashboard cleanup task (frontend completion), Section 3 — the
// Global Manager experience: scoped strictly to the buildings this
// account is actually assigned (user.building_ids, or every building only
// if all_buildings===true). Never shows system-wide totals, never shows
// campuses/buildings outside scope, never shows Super Admin-only
// management (no hierarchy browser, no global user/role controls). The
// backend already narrows GET /api/locations/buildings and GET
// /api/rooms to this account's scope (RBAC/dashboard cleanup task,
// Phase 9) — this screen simply renders exactly what those calls return,
// it never re-implements the filtering itself.
const UI = {
  en: {
    badge: 'Global Manager',
    title: 'My Buildings',
    buildings: 'Assigned buildings',
    rooms: 'Rooms',
    nodes: (n) => `${n} nodes`,
    loading: 'Loading…',
    empty: 'No buildings are assigned to your account yet',
    emptyHint: 'Contact a Super Admin to be assigned to one or more buildings',
    section: 'Management',
    map: { title: 'Map Management', desc: 'Upload, edit and manage your maps' },
    room: { title: 'Rooms & Destinations', desc: 'Manage clinics, wards, labs and offices' },
    route: { title: 'Route Points', desc: 'Manage navigation nodes and path data' },
    codes: { title: 'Location Codes', desc: 'Barcode/QR codes for user start points' },
    invites: { title: 'Invitation Codes', desc: 'Create signup codes within your scope' },
    logout: 'Logout',
  },
  ar: {
    badge: 'مدير عام',
    title: 'مبانيّ',
    buildings: 'المباني المخصصة',
    rooms: 'غرف',
    nodes: (n) => `${n} عقدة`,
    loading: 'جارٍ التحميل…',
    empty: 'لا توجد مبانٍ مخصصة لحسابك بعد',
    emptyHint: 'تواصل مع مشرف عام ليتم تخصيص مبنى أو أكثر لك',
    section: 'الإدارة',
    map: { title: 'إدارة الخريطة', desc: 'تحميل وتعديل وإدارة خرائطك' },
    room: { title: 'الغرف والوجهات', desc: 'إدارة العيادات والأجنحة والمختبرات' },
    route: { title: 'نقاط المسار', desc: 'إدارة عقد التنقل والمسارات' },
    codes: { title: 'رموز المواقع', desc: 'رموز باركود/QR لنقاط بدء المستخدم' },
    invites: { title: 'رموز الدعوة', desc: 'إنشاء رموز تسجيل ضمن نطاقك' },
    logout: 'تسجيل خروج',
  },
  he: {
    badge: 'מנהל גלובלי',
    title: 'המבנים שלי',
    buildings: 'מבנים משויכים',
    rooms: 'חדרים',
    nodes: (n) => `${n} צמתים`,
    loading: 'טוען…',
    empty: 'עדיין לא שויכו מבנים לחשבון שלך',
    emptyHint: 'פנה למנהל-על כדי לשייך אותך למבנה אחד או יותר',
    section: 'ניהול',
    map: { title: 'ניהול מפה', desc: 'העלאה, עריכה וניהול של המפות שלך' },
    room: { title: 'חדרים ויעדים', desc: 'ניהול מרפאות, אגפים ומעבדות' },
    route: { title: 'נקודות מסלול', desc: 'ניהול צמתי ניווט ומסלולים' },
    codes: { title: 'קודי מיקום', desc: 'קודי ברקוד/QR לנקודות התחלה' },
    invites: { title: 'קודי הזמנה', desc: 'צור קודי הרשמה בתוך ההיקף שלך' },
    logout: 'התנתק',
  },
};

const GlobalManagerDashboard = () => {
  const { lang, setLang } = useLang();
  const navigate = useNavigate();
  const { buildings, buildingsLoading, rooms } = useAdmin();
  const { logout } = useAuth();

  const isRTL = lang === 'ar' || lang === 'he';
  const t = UI[lang] || UI.en;

  const [buildingNodeCounts, setBuildingNodeCounts] = useState({});

  // Buildings here are ALREADY scoped by the backend (GET
  // /api/locations/buildings narrows to this account's building_ids
  // unless all_buildings===true) — no client-side re-filtering needed or
  // performed.
  useEffect(() => {
    let cancelled = false;
    Promise.all(
      buildings.map((b) =>
        getRoutePointCount({ building_id: b.id }).then((r) => [b.id, r.count]).catch(() => [b.id, null]),
      ),
    ).then((entries) => {
      if (!cancelled) setBuildingNodeCounts(Object.fromEntries(entries));
    });
    return () => { cancelled = true; };
  }, [buildings]);

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

          <div className="adm-stats-row">
            <ScopedStat value={buildings.length} label={t.buildings} color="#2a5298" />
          </div>
        </div>

        <div className="adm-content">
          {buildingsLoading ? (
            <div className="adm-empty"><div className="adm-empty-txt">{t.loading}</div></div>
          ) : buildings.length === 0 ? (
            <DashboardEmptyState icon={<LocationIcon />} title={t.empty} hint={t.emptyHint} />
          ) : (
            <div className="adm-nav-cards">
              {buildings.map((building) => (
                <HierarchyRow
                  key={building.id}
                  icon={<LocationIcon />}
                  title={building.nameEn || building.name}
                  subtitle={`${(rooms[building.id] || []).length} ${t.rooms.toLowerCase()}`}
                  metricValue={buildingNodeCounts[building.id] ?? '…'}
                  metricLabel={t.nodes(buildingNodeCounts[building.id] ?? 0)}
                  onClick={() => navigate('/admin/map')}
                  isRTL={isRTL}
                />
              ))}
            </div>
          )}

          <div className="adm-section-row" style={{ marginTop: 24 }}>
            <span className="adm-section-lbl">{t.section}</span>
          </div>

          <div className="adm-nav-cards">
            <HierarchyRow icon={<MapIcon />} title={t.map.title} subtitle={t.map.desc}
              onClick={() => navigate('/admin/map')} isRTL={isRTL} />
            <HierarchyRow icon={<RoomIcon />} title={t.room.title} subtitle={t.room.desc}
              onClick={() => navigate('/admin/rooms')} isRTL={isRTL} />
            <HierarchyRow icon={<RouteIcon />} title={t.route.title} subtitle={t.route.desc}
              onClick={() => navigate('/admin/routes')} isRTL={isRTL} />
            <HierarchyRow icon={<CodeIcon />} title={t.codes.title} subtitle={t.codes.desc}
              onClick={() => navigate('/admin/location-codes')} isRTL={isRTL} />
            <HierarchyRow icon={<KeyIcon />} title={t.invites.title} subtitle={t.invites.desc}
              onClick={() => navigate('/admin/invitation-codes')} isRTL={isRTL} />
          </div>

          <button className="adm-logout-btn" onClick={handleLogout}>
            <LogoutIcon /> {t.logout}
          </button>
        </div>
      </div>
    </div>
  );
};

export default GlobalManagerDashboard;
