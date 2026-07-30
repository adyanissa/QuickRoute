import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import QuickRouteLogo from '../components/QuickRouteLogo';
import { useLang } from '../context/LangContext';
import { useAdmin } from '../context/AdminContext';
import { useAuth } from '../context/AuthContext';
import { runBackfillBuildings } from '../api/maintenanceApi';
import { classifyInitializeError, summarizeInitializeResult } from '../utils/maintenanceHelpers';
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
    codes: { title: 'Location Codes', desc: 'Barcode/QR codes for user start points' },
    invites: { title: 'Invitation Codes', desc: 'Create one-time signup codes and assign admin roles and building responsibilities' },
    section: 'Management',
    mapStatus: { active: 'Map uploaded', none: 'No map uploaded', hint: 'Tap Map Management to upload a floor plan' },
    init: {
      title: 'Initialize Project Data',
      desc: 'Creates or reuses buildings and links existing maps and route points that are missing a building.',
      action: 'Initialize Project Data',
      running: 'Running...',
      confirmMessage:
        'This will create or reuse buildings for any map missing one, and link existing maps and route points to them.\n\n' +
        'Existing valid data will not be deleted or changed.\n' +
        'Missing building relationships will be added.\n' +
        'This operation is safe to run more than once.\n\n' +
        'Continue?',
      sessionExpired: 'Your session has expired. Please log in again.',
      forbidden: 'Only super admins and global managers can run this operation.',
      failed: 'Failed to initialize project data',
      resultMapsUpdated: 'Maps updated',
      resultPointsUpdated: 'Route points updated',
      resultBuildings: 'Buildings created / reused',
      resultRoomsWarning: (n) => `${n} room(s) still missing a valid building — review manually.`,
      resultCodesWarning: (n) => `${n} location code(s) have inconsistent building references — review manually.`,
    },
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
    codes: { title: 'رموز المواقع', desc: 'رموز باركود/QR لنقاط بدء المستخدم' },
    invites: { title: 'رموز الدعوة', desc: 'إنشاء رموز تسجيل لمرة واحدة وتحديد أدوار الإدارة ومسؤوليات المباني' },
    section: 'الإدارة',
    mapStatus: { active: 'الخريطة محملة', none: 'لا توجد خريطة', hint: 'انقر إدارة الخريطة لتحميل مخطط' },
    init: {
      title: 'تهيئة بيانات المشروع',
      desc: 'إنشاء أو إعادة استخدام المباني وربط الخرائط ونقاط المسار الحالية التي تفتقر إلى مبنى.',
      action: 'تهيئة بيانات المشروع',
      running: 'جارٍ التنفيذ...',
      confirmMessage:
        'سيؤدي هذا إلى إنشاء أو إعادة استخدام المباني لأي خريطة تفتقر إلى مبنى، وربط الخرائط ونقاط المسار الحالية بها.\n\n' +
        'لن يتم حذف أو تغيير أي بيانات صالحة موجودة.\n' +
        'سيتم إضافة علاقات المباني المفقودة فقط.\n' +
        'هذه العملية آمنة ويمكن تشغيلها أكثر من مرة.\n\n' +
        'هل تريد المتابعة؟',
      sessionExpired: 'انتهت صلاحية جلستك. يرجى تسجيل الدخول مرة أخرى.',
      forbidden: 'فقط المشرف العام أو مدير النظام يمكنه تنفيذ هذه العملية.',
      failed: 'فشلت تهيئة بيانات المشروع',
      resultMapsUpdated: 'الخرائط المحدثة',
      resultPointsUpdated: 'نقاط المسار المحدثة',
      resultBuildings: 'المباني التي تم إنشاؤها/إعادة استخدامها',
      resultRoomsWarning: (n) => `${n} غرفة/غرف ما زالت بدون مبنى صالح — يلزم المراجعة اليدوية.`,
      resultCodesWarning: (n) => `${n} رمز/رموز مواقع بها تعارض في بيانات المبنى — يلزم المراجعة اليدوية.`,
    },
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
    codes: { title: 'קודי מיקום', desc: 'קודי ברקוד/QR לנקודות התחלה' },
    invites: { title: 'קודי הזמנה', desc: 'צור קודי הרשמה חד-פעמיים והקצה תפקידי ניהול ואחריות מבנים' },
    section: 'ניהול',
    mapStatus: { active: 'מפה הועלתה', none: 'אין מפה', hint: 'לחץ ניהול מפה להעלאת תוכנית קומה' },
    init: {
      title: 'אתחול נתוני הפרויקט',
      desc: 'יוצר או משתמש מחדש במבנים ומקשר מפות ונקודות מסלול קיימות שחסר להן מבנה.',
      action: 'אתחל נתוני פרויקט',
      running: 'מתבצע...',
      confirmMessage:
        'פעולה זו תיצור או תשתמש מחדש במבנים עבור כל מפה שחסר לה מבנה, ותקשר אליהם מפות ונקודות מסלול קיימות.\n\n' +
        'נתונים תקפים קיימים לא יימחקו או ישתנו.\n' +
        'קשרי מבנה חסרים יתווספו.\n' +
        'הפעולה בטוחה להרצה יותר מפעם אחת.\n\n' +
        'להמשיך?',
      sessionExpired: 'תוקף ההתחברות שלך פג. יש להתחבר מחדש.',
      forbidden: 'רק מנהל-על או מנהל גלובלי יכולים להריץ פעולה זו.',
      failed: 'אתחול נתוני הפרויקט נכשל',
      resultMapsUpdated: 'מפות שעודכנו',
      resultPointsUpdated: 'נקודות מסלול שעודכנו',
      resultBuildings: 'מבנים שנוצרו / נעשה בהם שימוש חוזר',
      resultRoomsWarning: (n) => `${n} חדרים עדיין ללא מבנה תקין — נדרשת בדיקה ידנית.`,
      resultCodesWarning: (n) => `${n} קודי מיקום עם התייחסות מבנה לא עקבית — נדרשת בדיקה ידנית.`,
    },
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

const CodeIcon = () => (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
    <rect x="3" y="3" width="7" height="7" rx="1.2" stroke="currentColor" strokeWidth="1.8"/>
    <rect x="14" y="3" width="7" height="7" rx="1.2" stroke="currentColor" strokeWidth="1.8"/>
    <rect x="3" y="14" width="7" height="7" rx="1.2" stroke="currentColor" strokeWidth="1.8"/>
    <path d="M14 14h3v3h-3zM18 18h3v3h-3zM18 14h3M14 18v3" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"/>
  </svg>
);

const KeyIcon = () => (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
    <circle cx="8" cy="15" r="4" stroke="currentColor" strokeWidth="1.8"/>
    <path d="M11 12l8-8M17 6l2 2M14 9l2 2" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/>
  </svg>
);

const SetupIcon = () => (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
    <path d="M14.7 6.3a4 4 0 0 1-5.4 5.4L4 17l3 3 5.3-5.3a4 4 0 0 1 5.4-5.4l-2.3 2.3-2-2 2.3-2.3z"
      stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/>
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
  const {
    buildings, rooms, routePoints, mapData,
    loadMaps, loadBuildings, loadRooms, loadRoutePoints,
  } = useAdmin();
  const { logout, user } = useAuth();
  const canManageInvitationCodes = user?.role === 'super_admin' || user?.role === 'global_manager';

  const [isInitializing, setIsInitializing] = useState(false);
  const [initResult, setInitResult] = useState(null);
  const [initError, setInitError] = useState('');

  const handleLogout = () => {
    logout();
    navigate('/screen/02');
  };

  const isRTL = lang === 'ar' || lang === 'he';
  const t     = UI[lang];

  const totalRooms = Object.values(rooms).reduce((sum, arr) => sum + arr.length, 0);

  const resultSummary = initResult ? summarizeInitializeResult(initResult) : null;

  const handleInitializeProjectData = async () => {
    // Belt-and-suspenders against double-clicks: the button is already
    // disabled while running, but guard the handler itself too in case
    // it fires again before the re-render lands.
    if (isInitializing) return;

    const confirmed = window.confirm(t.init.confirmMessage);
    if (!confirmed) return;

    setIsInitializing(true);
    setInitError('');
    setInitResult(null);

    try {
      const result = await runBackfillBuildings();
      setInitResult(result);

      // Refresh everything the dashboard (and screens it links to) shows
      // counts/data for, so the admin sees the effect immediately without
      // a full page reload.
      await Promise.all([
        loadMaps(),
        loadBuildings(),
        loadRooms(),
        loadRoutePoints(),
      ]);
    } catch (error) {
      const classified = classifyInitializeError(error, t.init);
      setInitError(classified.message);

      if (classified.kind === 'sessionExpired') {
        // Token was already cleared by apiRequest(); also clear the
        // in-memory auth state and send the admin back to login instead of
        // leaving a stale "logged in" UI around a dead session.
        logout();
        navigate('/screen/02');
      }
    } finally {
      setIsInitializing(false);
    }
  };

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

          {/* Initialize Project Data */}
          <div className="adm-setup-card">
            <div className="adm-setup-card-top">
              <div className="adm-setup-card-icon"><SetupIcon /></div>
              <div className="adm-setup-card-body">
                <div className="adm-setup-card-title">{t.init.title}</div>
                <div className="adm-setup-card-desc">{t.init.desc}</div>
              </div>
            </div>

            <button
              className="adm-btn adm-btn-primary adm-setup-card-btn"
              onClick={handleInitializeProjectData}
              disabled={isInitializing}
            >
              {isInitializing ? t.init.running : t.init.action}
            </button>

            {initError && (
              <div className="adm-setup-card-error">{initError}</div>
            )}

            {resultSummary && (
              <div className="adm-setup-card-result">
                <div className="adm-setup-card-result-row">
                  <span>{t.init.resultMapsUpdated}</span>
                  <strong>{resultSummary.mapsUpdated}</strong>
                </div>
                <div className="adm-setup-card-result-row">
                  <span>{t.init.resultPointsUpdated}</span>
                  <strong>{resultSummary.pointsUpdated}</strong>
                </div>
                <div className="adm-setup-card-result-row">
                  <span>{t.init.resultBuildings}</span>
                  <strong>{resultSummary.buildingsTouchedCount}</strong>
                </div>
                {resultSummary.buildingsTouchedNames.length > 0 && (
                  <div className="adm-setup-card-result-names">
                    {resultSummary.buildingsTouchedNames.join(', ')}
                  </div>
                )}
                {resultSummary.roomsWithMissingBuilding > 0 && (
                  <div className="adm-setup-card-result-warn">
                    {t.init.resultRoomsWarning(resultSummary.roomsWithMissingBuilding)}
                  </div>
                )}
                {resultSummary.locationCodesInconsistent > 0 && (
                  <div className="adm-setup-card-result-warn">
                    {t.init.resultCodesWarning(resultSummary.locationCodesInconsistent)}
                  </div>
                )}
              </div>
            )}
          </div>

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
            <NavCard
              icon={<CodeIcon />}
              title={t.codes.title}
              desc={t.codes.desc}
              gradient="linear-gradient(135deg, #1f6f6f, #2a9d9d)"
              onClick={() => navigate('/admin/location-codes')}
              isRTL={isRTL}
            />
            {canManageInvitationCodes && (
              <NavCard
                icon={<KeyIcon />}
                title={t.invites.title}
                desc={t.invites.desc}
                gradient="linear-gradient(135deg, #6b3f1a, #c08030)"
                onClick={() => navigate('/admin/invitation-codes')}
                isRTL={isRTL}
              />
            )}
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
