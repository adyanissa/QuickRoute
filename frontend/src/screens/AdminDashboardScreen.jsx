import { useNavigate } from 'react-router-dom';
import QuickRouteLogo from '../components/QuickRouteLogo';
import { useLang } from '../context/LangContext';
import { useAdmin } from '../context/AdminContext';
import { useAuth } from '../context/AuthContext';
import '../styles/adminScreens.css';

// ── Translations ──────────────────────────────────────────────────────────────
const LANGUAGES = [
  { code: 'ar', label: 'عربي' },
  { code: 'he', label: 'עברית' },
  { code: 'en', label: 'EN' },
];

const UI = {
  en: {
    badge: 'Admin Portal',
    title: 'Admin\nDashboard',
    campus: 'Rabin Medical Center',
    wordmark: ['Quick', 'Route'],
    stats: { buildings: 'Buildings', rooms: 'Rooms', routes: 'Nodes' },
    map: { title: 'Map Management', desc: 'Upload, edit and manage the campus map' },
    loc: { title: 'Locations', desc: 'Add and manage buildings & centers' },
    room: { title: 'Rooms & Destinations', desc: 'Manage clinics, wards, labs and offices' },
    route: { title: 'Route Points', desc: 'Manage navigation nodes and path data' },
    section: 'Management',
    mapStatus: { active: 'Map uploaded', none: 'No map uploaded', hint: 'Tap Map Management to upload a floor plan' },
    logout: 'Logout',
  },
  ar: {
    badge: 'بوابة المشرف',
    title: 'لوحة\nالإدارة',
    campus: 'مركز رابين الطبي',
    wordmark: ['Quick', 'Route'],
    stats: { buildings: 'مبانٍ', rooms: 'غرف', routes: 'نقاط' },
    map: { title: 'إدارة الخريطة', desc: 'تحميل وتعديل خريطة الحرم' },
    loc: { title: 'المواقع', desc: 'إضافة وإدارة المباني والمراكز' },
    room: { title: 'الغرف والوجهات', desc: 'إدارة العيادات والأجنحة والمختبرات' },
    route: { title: 'نقاط المسار', desc: 'إدارة عقد التنقل والمسارات' },
    section: 'الإدارة',
    mapStatus: { active: 'الخريطة محملة', none: 'لا توجد خريطة', hint: 'انقر إدارة الخريطة لتحميل مخطط' },
    logout: 'تسجيل خروج',
  },
  he: {
    badge: 'פורטל מנהל',
    title: 'לוח\nהניהול',
    campus: 'מרכז רבין הרפואי',
    wordmark: ['Quick', 'Route'],
    stats: { buildings: 'מבנים', rooms: 'חדרים', routes: 'נקודות' },
    map: { title: 'ניהול מפה', desc: 'העלאה ועריכה של מפת הקמפוס' },
    loc: { title: 'מיקומים', desc: 'הוספה וניהול מבנים ומרכזים' },
    room: { title: 'חדרים ויעדים', desc: 'ניהול מרפאות, אגפים ומעבדות' },
    route: { title: 'נקודות מסלול', desc: 'ניהול צמתי ניווט ומסלולים' },
    section: 'ניהול',
    mapStatus: { active: 'מפה הועלתה', none: 'אין מפה', hint: 'לחץ ניהול מפה להעלאת תוכנית קומה' },
    logout: 'התנתק',
  },
};

// ── Icons ─────────────────────────────────────────────────────────────────────
const PinIcon = () => (
  <svg width="11" height="11" viewBox="0 0 24 24" fill="currentColor">
    <path d="M12 2a7 7 0 0 1 7 7c0 5.25-7 13-7 13S5 14.25 5 9a7 7 0 0 1 7-7z" opacity="0.9"/>
    <circle cx="12" cy="9" r="2.8" fill="white"/>
  </svg>
);

const ShieldIcon = () => (
  <svg width="13" height="13" viewBox="0 0 24 24" fill="none">
    <path d="M12 2L4 6v6c0 5.25 3.5 10.2 8 11.5C16.5 22.2 20 17.25 20 12V6L12 2z"
      stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/>
    <path d="M9 12l2 2 4-4" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/>
  </svg>
);

const ChevronIcon = () => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none">
    <path d="M9 18l6-6-6-6" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"/>
  </svg>
);

const ChevronIconRTL = () => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none">
    <path d="M15 18l-6-6 6-6" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"/>
  </svg>
);

const MapIcon = () => (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
    <path d="M9 20L3 17V4l6 3M9 20l6-3M9 20V7M15 17l6 3V7l-6-3M15 17V4M9 7l6-3"
      stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/>
  </svg>
);

const LocationIcon = () => (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
    <path d="M12 2C8.686 2 6 4.686 6 8c0 5.25 6 13 6 13s6-7.75 6-13c0-3.314-2.686-6-6-6z"
      stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/>
    <circle cx="12" cy="8" r="2" stroke="currentColor" strokeWidth="1.8"/>
  </svg>
);

const RoomIcon = () => (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
    <rect x="3" y="3" width="18" height="18" rx="2" stroke="currentColor" strokeWidth="1.8"/>
    <path d="M9 3v18M3 9h6M3 15h6" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"/>
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

const LogoutIcon = () => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none">
    <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9"
      stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
  </svg>
);

// ── NavCard ───────────────────────────────────────────────────────────────────
const NavCard = ({ icon, title, desc, count, countLabel, gradient, onClick, isRTL }) => (
  <button className="adm-nav-card" onClick={onClick}>
    <div className="adm-nav-card-icon" style={{ background: gradient }}>{icon}</div>
    <div className="adm-nav-card-body">
      <div className="adm-nav-card-title">{title}</div>
      <div className="adm-nav-card-desc">{desc}</div>
    </div>
    <div className="adm-nav-card-right">
      {count !== undefined && (
        <div style={{ textAlign: 'center' }}>
          <div className="adm-nav-card-num">{count}</div>
          <div className="adm-nav-card-clbl">{countLabel}</div>
        </div>
      )}
      {isRTL ? <ChevronIconRTL /> : <ChevronIcon />}
    </div>
  </button>
);

// ── Screen05 ──────────────────────────────────────────────────────────────────
const Screen05 = () => {
  const { lang, setLang } = useLang();
  const navigate          = useNavigate();
  const { buildings, rooms, routePoints, mapData } = useAdmin();
  const { logout } = useAuth();

  const handleLogout = () => {
    logout();
    navigate('/screen/02');
  };

  const isRTL = lang === 'ar' || lang === 'he';
  const t     = UI[lang];

  const totalRooms = Object.values(rooms).reduce((sum, arr) => sum + arr.length, 0);

  return (
    <div className="layout-wrapper">
      <div className="layout-shell adm-shell" dir={isRTL ? 'rtl' : 'ltr'}>

        {/* ── Header ──────────────────────────────────────────────────── */}
        <div className="adm-header">

          {/* Top bar: logo + language switcher */}
          <div className="adm-topbar">
            <div className="adm-logo-row">
              <div className="adm-logo-card">
                <QuickRouteLogo size={26} />
              </div>
              <span className="adm-wordmark">
                {t.wordmark[0]}<span>{t.wordmark[1]}</span>
              </span>
            </div>
            <div className="adm-lang-pill" role="group" aria-label="Language selector">
              {LANGUAGES.map((l) => (
                <button
                  key={l.code}
                  className={`adm-lang-btn${lang === l.code ? ' active' : ''}`}
                  onClick={() => setLang(l.code)}
                  aria-pressed={lang === l.code}
                >
                  {l.label}
                </button>
              ))}
            </div>
          </div>

          {/* Admin badge */}
          <div className="adm-header-badge">
            <ShieldIcon /> {t.badge}
          </div>

          {/* Page title */}
          <h1 className="adm-header-title">
            {t.title.split('\n').map((line, i) => (
              <span key={i}>{line}{i === 0 && <br />}</span>
            ))}
          </h1>

          {/* Campus pill */}
          <div className="adm-campus-badge">
            <PinIcon />
            <span>{t.campus}</span>
          </div>

        </div>

        {/* ── Scrollable content ───────────────────────────────────────── */}
        <div className="adm-content">

          {/* Stats row */}
          <div className="adm-stats-row">
            <div className="adm-stat">
              <div className="adm-stat-num" style={{ color: '#2a5298' }}>{buildings.length}</div>
              <div className="adm-stat-lbl">{t.stats.buildings}</div>
            </div>
            <div className="adm-stat">
              <div className="adm-stat-num" style={{ color: '#2aaa8a' }}>{totalRooms}</div>
              <div className="adm-stat-lbl">{t.stats.rooms}</div>
            </div>
            <div className="adm-stat">
              <div className="adm-stat-num" style={{ color: '#c06030' }}>{routePoints.length}</div>
              <div className="adm-stat-lbl">{t.stats.routes}</div>
            </div>
          </div>

          {/* Map status */}
          {mapData.hasImage ? (
            <div className="adm-map-card adm-map-card-active">
              <div className="adm-map-card-icon"><MapIcon /></div>
              <div className="adm-map-card-info">
                <div className="adm-map-card-name">{mapData.title}</div>
                <div className="adm-map-card-meta">{mapData.campus}</div>
              </div>
              <span className="adm-map-status-badge">{t.mapStatus.active}</span>
            </div>
          ) : (
            <div className="adm-map-card adm-map-card-empty">
              <div className="adm-map-card-empty-icon">
                <MapIcon />
              </div>
              <div className="adm-map-card-empty-txt">{t.mapStatus.none}</div>
              <div className="adm-map-card-empty-hint">{t.mapStatus.hint}</div>
            </div>
          )}

          {/* Section label */}
          <div className="adm-section-row">
            <span className="adm-section-lbl">{t.section}</span>
          </div>

          {/* Navigation cards */}
          <div className="adm-nav-cards">
            <NavCard
              icon={<MapIcon />}
              title={t.map.title}
              desc={t.map.desc}
              gradient="linear-gradient(135deg, #1a3a6b, #2a5298)"
              onClick={() => navigate('/admin/map')}
              isRTL={isRTL}
            />
            <NavCard
              icon={<LocationIcon />}
              title={t.loc.title}
              desc={t.loc.desc}
              count={buildings.length}
              countLabel={t.stats.buildings}
              gradient="linear-gradient(135deg, #1d7a6a, #2aaa8a)"
              onClick={() => navigate('/admin/locations')}
              isRTL={isRTL}
            />
            <NavCard
              icon={<RoomIcon />}
              title={t.room.title}
              desc={t.room.desc}
              count={totalRooms}
              countLabel={t.stats.rooms}
              gradient="linear-gradient(135deg, #5c3d9b, #7c5cbf)"
              onClick={() => navigate('/admin/rooms')}
              isRTL={isRTL}
            />
            <NavCard
              icon={<RouteIcon />}
              title={t.route.title}
              desc={t.route.desc}
              count={routePoints.length}
              countLabel={t.stats.routes}
              gradient="linear-gradient(135deg, #9a4020, #c06030)"
              onClick={() => navigate('/admin/routes')}
              isRTL={isRTL}
            />
          </div>

          {/* Logout */}
          <button className="adm-logout-btn" onClick={handleLogout}>
            <LogoutIcon /> {t.logout}
          </button>

        </div>

      </div>
    </div>
  );
};

export default Screen05;
