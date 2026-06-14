import { useState } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { useLang } from '../context/LangContext';
import { formatFloor } from '../components/DestinationCard';
import RouteSteps from '../components/RouteSteps';
import BackButton from '../components/BackButton';
import hospitalMap from "../assets/bellinson-map.png";
import {
  getRouteSVGPath,
  getWaypoints,
  getEstimatedDistance,
  getEstimatedTime,
  getDestinationPosition,
  getStartPosition,
  getFullRoute,
  formatDistance,
  formatTime,
} from '../utils/routeHelpers';
import '../styles/IndoorNavigationScreen.css';

// ── Translations ──────────────────────────────────────────────────────────────
const UI = {
  en: {
    back:        'Back',
    destination: 'Your Destination',
    routeReady:  'Route ready',
    navigating:  'Navigating',
    arrived:     'Arrived',
    startNav:    'Start Navigation',
    cancelNav:   'Cancel navigation',
    done:        'Done',
    you:         'You',
    directions:  'Directions',
    navHint:     'Tap ✓ on each step when completed',
    arrivedTitle:'You have arrived!',
    arrivedSub:  'Destination reached',
  },
  ar: {
    back:        'رجوع',
    destination: 'وجهتك',
    routeReady:  'المسار جاهز',
    navigating:  'جارٍ التنقل',
    arrived:     'وصلت',
    startNav:    'ابدأ التنقل',
    cancelNav:   'إلغاء التنقل',
    done:        'تم',
    you:         'أنت',
    directions:  'التعليمات',
    navHint:     'اضغط ✓ بعد إتمام كل خطوة',
    arrivedTitle:'لقد وصلت!',
    arrivedSub:  'تم الوصول إلى الوجهة',
  },
  he: {
    back:        'חזרה',
    destination: 'היעד שלך',
    routeReady:  'מסלול מוכן',
    navigating:  'מנווט',
    arrived:     'הגעת',
    startNav:    'התחל ניווט',
    cancelNav:   'בטל ניווט',
    done:        'סיום',
    you:         'אתה',
    directions:  'הוראות',
    navHint:     'הקש ✓ בכל שלב שהשלמת',
    arrivedTitle:'הגעת ליעד!',
    arrivedSub:  'הגעת ליעדך',
  },
};

// ── Icons ─────────────────────────────────────────────────────────────────────

const ClockIcon = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
    <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="1.8"/>
    <path d="M12 7v5l3 2" stroke="currentColor" strokeWidth="1.8"
      strokeLinecap="round" strokeLinejoin="round"/>
  </svg>
);

const WalkIcon = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
    <circle cx="12" cy="4" r="2" stroke="currentColor" strokeWidth="1.8"/>
    <path d="M9 20l1.5-5L9 12l3 2 2.5-4" stroke="currentColor"
      strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/>
    <path d="M7 8.5L9 12M15 8l-1.5 3.5" stroke="currentColor"
      strokeWidth="1.8" strokeLinecap="round"/>
  </svg>
);

const NavArrow = ({ flip }) => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none"
    style={flip ? { transform: 'scaleX(-1)' } : undefined}>
    <path d="M5 12h14M13 6l6 6-6 6" stroke="currentColor"
      strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"/>
  </svg>
);

const BigCheckIcon = () => (
  <svg width="28" height="28" viewBox="0 0 24 24" fill="none">
    <circle cx="12" cy="12" r="11" fill="rgba(39,174,96,0.15)" stroke="#27ae60" strokeWidth="1.5"/>
    <path d="M7 12l4 4 6-7" stroke="#27ae60" strokeWidth="2.2"
      strokeLinecap="round" strokeLinejoin="round"/>
  </svg>
);

// ── Dynamic SVG route overlay ─────────────────────────────────────────────────
const RouteOverlay = ({ buildingId, t, hasArrived }) => {
  const pathD  = getRouteSVGPath(buildingId);
  const waypts = getWaypoints(buildingId);
  const start  = getStartPosition();
  const dest   = getDestinationPosition(buildingId);

  if (!pathD) return null;

  const routeColor = hasArrived ? '#27ae60' : '#4a7ac8';

  return (
    <svg
      className="s18-route-svg"
      viewBox="0 0 400 225"
      preserveAspectRatio="xMidYMid slice"
      xmlns="http://www.w3.org/2000/svg"
    >
      {/* Glow under path */}
      <path d={pathD}
        stroke={hasArrived ? 'rgba(39,174,96,0.22)' : 'rgba(74,122,200,0.22)'}
        strokeWidth="8" fill="none" strokeLinecap="round" strokeLinejoin="round"/>

      {/* Animated route path */}
      <path className="s18-route-path" d={pathD}
        stroke={routeColor} strokeWidth="3.5" fill="none"
        strokeLinecap="round" strokeLinejoin="round"/>

      {/* Waypoint dots */}
      {waypts.map((p, i) => (
        <circle key={i} cx={p.x} cy={p.y} r="4" fill={routeColor} opacity="0.55"/>
      ))}

      {/* Start: pulsing dot */}
      <circle className="s18-pulse-ring"
        cx={start.x} cy={start.y} r="14"
        fill={`rgba(${hasArrived ? '39,174,96' : '74,122,200'},0.15)`}
        stroke={`rgba(${hasArrived ? '39,174,96' : '74,122,200'},0.30)`}
        strokeWidth="1"/>
      <circle cx={start.x} cy={start.y} r="7"
        fill="white" stroke={routeColor} strokeWidth="2.5"/>
      <circle cx={start.x} cy={start.y} r="3.5" fill={routeColor}/>

      {/* Start label */}
      <rect x={start.x + 8} y={start.y - 8} width="26" height="16" rx="4"
        fill="white" opacity="0.90"/>
      <text x={start.x + 21} y={start.y + 3} textAnchor="middle"
        fontSize="7" fontWeight="700" fill="#1a3a6b" fontFamily="sans-serif">
        {t.you}
      </text>

      {/* Destination pin */}
      <ellipse cx={dest.x} cy={dest.y + 6} rx="6" ry="2.5" fill="rgba(0,0,0,0.18)"/>
      <path
        d={`M ${dest.x} ${dest.y - 18}
            C ${dest.x - 10} ${dest.y - 18} ${dest.x - 18} ${dest.y - 10}
              ${dest.x - 18} ${dest.y}
            C ${dest.x - 18} ${dest.y + 13} ${dest.x} ${dest.y + 27}
              ${dest.x} ${dest.y + 27}
            C ${dest.x} ${dest.y + 27} ${dest.x + 18} ${dest.y + 13}
              ${dest.x + 18} ${dest.y}
            C ${dest.x + 18} ${dest.y - 10} ${dest.x + 10} ${dest.y - 18}
              ${dest.x} ${dest.y - 18} Z`}
        fill={hasArrived ? '#27ae60' : '#1a3a6b'}
      />
      <path
        d={`M ${dest.x} ${dest.y - 18}
            C ${dest.x - 10} ${dest.y - 18} ${dest.x - 18} ${dest.y - 10}
              ${dest.x - 18} ${dest.y}
            C ${dest.x - 18} ${dest.y + 13} ${dest.x} ${dest.y + 27}
              ${dest.x} ${dest.y + 27}
            C ${dest.x} ${dest.y + 27} ${dest.x + 18} ${dest.y + 13}
              ${dest.x + 18} ${dest.y}
            C ${dest.x + 18} ${dest.y - 10} ${dest.x + 10} ${dest.y - 18}
              ${dest.x} ${dest.y - 18} Z`}
        fill="url(#pinGrad)"
      />
      <circle cx={dest.x} cy={dest.y} r="7" fill="white" opacity="0.95"/>
      <circle cx={dest.x} cy={dest.y} r="3.5" fill={routeColor}/>

      <defs>
        <linearGradient id="pinGrad" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%"   stopColor="rgba(255,255,255,0.22)"/>
          <stop offset="100%" stopColor="transparent"/>
        </linearGradient>
      </defs>
    </svg>
  );
};

// ── Screen ────────────────────────────────────────────────────────────────────
const IndoorNavigationScreen = () => {
  const { lang }  = useLang();
  const navigate  = useNavigate();
  const location  = useLocation();

  // Navigation state
  const [isNavigating, setIsNavigating]   = useState(false);
  const [completedSteps, setCompletedSteps] = useState(new Set());

  const isRTL = lang === 'ar' || lang === 'he';
  const t     = UI[lang];

  const building   = location.state?.building    ?? null;
  const room       = location.state?.destination ?? location.state?.room ?? null;
  const buildingId = building?.id ?? 'schneider';

  const distanceM = getEstimatedDistance(buildingId);
  const timeMin   = getEstimatedTime(buildingId);
  const { outdoor, indoor } = getFullRoute(buildingId, room, lang, building?.name ?? '');

  // Flat step list for index tracking
  const allSteps  = [...outdoor, ...indoor];
  const activeStep = allSteps.findIndex((_, i) => !completedSteps.has(i));
  const hasArrived = isNavigating && allSteps.length > 0 && completedSteps.size === allSteps.length;

  const handleStepToggle = (index) => {
    setCompletedSteps(prev => {
      const next = new Set(prev);
      if (next.has(index)) next.delete(index);
      else next.add(index);
      return next;
    });
  };

  const handleStartNav = () => {
    setIsNavigating(true);
    setCompletedSteps(new Set());
  };

  const handleCancelNav = () => {
    setIsNavigating(false);
    setCompletedSteps(new Set());
  };

  // Badge config
  const badgeClass = hasArrived
    ? 's18-route-badge s18-route-badge--arrived'
    : isNavigating
      ? 's18-route-badge s18-route-badge--nav'
      : 's18-route-badge';
  const badgeText = hasArrived ? t.arrived : isNavigating ? t.navigating : t.routeReady;

  return (
    <div className="layout-wrapper">
      <div className="layout-shell s18-shell" dir={isRTL ? 'rtl' : 'ltr'}>

        {/* ── Header ── */}
        <div className="s18-header">
          <BackButton
            onClick={() => navigate('/screen/17', { state: { building } })}
            label={t.back}
            isRTL={isRTL}
            spacing="compact"
          />

          {building && (
            <div className="s18-header-info">
              <span className="s18-header-building">{building.name}</span>
              {room && (
                <>
                  <span className="s18-header-sep">·</span>
                  <span className="s18-header-room">{room.name}</span>
                </>
              )}
            </div>
          )}
        </div>

        {/* ── Map ── */}
        <div className="s18-map-wrap">
          <div className={`s18-map-container${isNavigating ? ' s18-map-container--nav' : ''}`}>
            <img
              src={hospitalMap}
              alt="Hospital campus map"
              className="s18-map-img"
              draggable="false"
            />
            <RouteOverlay buildingId={buildingId} t={t} hasArrived={hasArrived} />
          </div>
          <div className={badgeClass}>
            <span className="s18-route-dot" />
            <span>{badgeText}</span>
          </div>
        </div>

        {/* ── Scrollable bottom ── */}
        <div className="s18-bottom">

          {/* Arrival banner */}
          {hasArrived && (
            <div className="s18-arrival">
              <BigCheckIcon />
              <div className="s18-arrival-text">
                <p className="s18-arrival-title">{t.arrivedTitle}</p>
                <p className="s18-arrival-sub">{t.arrivedSub}</p>
              </div>
            </div>
          )}

          {/* Info card */}
          <div className={`s18-info-card${hasArrived ? ' s18-info-card--arrived' : ''}`}>
            <p className="s18-dest-label">{t.destination}</p>

            {building ? (
              <>
                <h2 className="s18-dest-name">{room ? room.name : building.name}</h2>
                <p className="s18-dest-meta">
                  <span
                    className="s18-building-chip"
                    style={{ color: building.iconColor, background: building.iconBg }}
                  >
                    {building.tag}
                  </span>
                  {room && (
                    <>
                      <span className="s18-floor-chip">{formatFloor(room.floor)}</span>
                      <span className="s18-type-chip">{room.type.replace('_', '\u00A0')}</span>
                    </>
                  )}
                </p>
              </>
            ) : (
              <h2 className="s18-dest-name">—</h2>
            )}

            <div className="s18-stats">
              <div className="s18-stat">
                <ClockIcon />
                <span>{formatTime(timeMin)}</span>
              </div>
              <div className="s18-stat-divider" />
              <div className="s18-stat">
                <WalkIcon />
                <span>{formatDistance(distanceM)}</span>
              </div>
            </div>
          </div>

          {/* Directions section */}
          {allSteps.length > 0 && (
            <div className="s18-directions">
              <div className="s18-directions-header">
                <p className="s18-directions-label">{t.directions}</p>
                {isNavigating && !hasArrived && (
                  <p className="s18-nav-hint">{t.navHint}</p>
                )}
              </div>
              <RouteSteps
                outdoorSteps={outdoor}
                indoorSteps={indoor}
                lang={lang}
                isNavigating={isNavigating}
                completedSteps={completedSteps}
                activeStep={activeStep}
                onStepToggle={handleStepToggle}
              />
            </div>
          )}

          {/* Bottom action */}
          {hasArrived ? (
            <button className="s18-done-btn" type="button" onClick={handleCancelNav}>
              <span>{t.done}</span>
            </button>
          ) : isNavigating ? (
            <button className="s18-cancel-btn" type="button" onClick={handleCancelNav}>
              {t.cancelNav}
            </button>
          ) : (
            <button className="s18-nav-btn" type="button" onClick={handleStartNav}>
              <span>{t.startNav}</span>
              <NavArrow flip={isRTL} />
            </button>
          )}

        </div>
      </div>
    </div>
  );
};

export default IndoorNavigationScreen;
