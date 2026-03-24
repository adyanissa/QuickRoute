import { useNavigate, useLocation } from 'react-router-dom';
import { useLang } from '../context/LangContext';
import { formatFloor } from '../components/DestinationCard';
import hospitalMap from "../assets/bellinson-map.png";
import '../styles/screen18.css';

// ── Translations ──────────────────────────────────────────────────────────────
const UI = {
  en: {
    back:        'Back',
    destination: 'Your Destination',
    routeReady:  'Route ready',
    eta:         '~5 min',
    distance:    '~200 m',
    startNav:    'Start Navigation',
    you:         'You',
  },
  ar: {
    back:        'رجوع',
    destination: 'وجهتك',
    routeReady:  'المسار جاهز',
    eta:         '~٥ دقائق',
    distance:    '~٢٠٠م',
    startNav:    'ابدأ التنقل',
    you:         'أنت',
  },
  he: {
    back:        'חזרה',
    destination: 'היעד שלך',
    routeReady:  'מסלול מוכן',
    eta:         '~5 דקות',
    distance:    '~200מ׳',
    startNav:    'התחל ניווט',
    you:         'אתה',
  },
};

// ── Icons ─────────────────────────────────────────────────────────────────────
const BackArrow = ({ flip }) => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none"
    style={flip ? { transform: 'scaleX(-1)' } : undefined}>
    <path d="M19 12H5M11 18l-6-6 6-6" stroke="currentColor"
      strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"/>
  </svg>
);

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

// ── Fake route SVG overlay ────────────────────────────────────────────────────
// viewBox matches the image's 16∶9 ratio (400×225).
// The path is a plausible campus walk from the entrance (bottom-left)
// to the Schneider / upper-right area — purely decorative.
const RouteOverlay = ({ t }) => (
  <svg
    className="s18-route-svg"
    viewBox="0 0 400 225"
    preserveAspectRatio="xMidYMid meet"
    xmlns="http://www.w3.org/2000/svg"
  >
    {/* ── Shadow / glow under path ── */}
    <path
      d="M 62 198 C 62 178 68 168 85 165 L 158 165
         C 170 165 174 156 174 144 L 174 114
         C 174 102 184 98 198 97 L 252 97
         C 265 97 272 89 280 80 L 298 70"
      stroke="rgba(74,122,200,0.25)"
      strokeWidth="8"
      fill="none"
      strokeLinecap="round"
      strokeLinejoin="round"
    />

    {/* ── Main route path ── */}
    <path
      className="s18-route-path"
      d="M 62 198 C 62 178 68 168 85 165 L 158 165
         C 170 165 174 156 174 144 L 174 114
         C 174 102 184 98 198 97 L 252 97
         C 265 97 272 89 280 80 L 298 70"
      stroke="#4a7ac8"
      strokeWidth="3.5"
      fill="none"
      strokeLinecap="round"
      strokeLinejoin="round"
    />

    {/* ── Waypoint dots along path ── */}
    <circle cx="121" cy="165" r="4" fill="#4a7ac8" opacity="0.55"/>
    <circle cx="174" cy="130" r="4" fill="#4a7ac8" opacity="0.55"/>
    <circle cx="225" cy="97"  r="4" fill="#4a7ac8" opacity="0.55"/>
    <circle cx="265" cy="88"  r="4" fill="#4a7ac8" opacity="0.55"/>

    {/* ── Start: pulsing "You are here" dot ── */}
    <circle className="s18-pulse-ring" cx="62" cy="198" r="14"
      fill="rgba(74,122,200,0.15)" stroke="rgba(74,122,200,0.30)" strokeWidth="1"/>
    <circle cx="62" cy="198" r="7"
      fill="white" stroke="#4a7ac8" strokeWidth="2.5"/>
    <circle cx="62" cy="198" r="3.5" fill="#4a7ac8"/>

    {/* ── Start label ── */}
    <rect x="70" y="190" width="26" height="16" rx="4"
      fill="white" opacity="0.90"/>
    <text x="83" y="201" textAnchor="middle"
      fontSize="7" fontWeight="700" fill="#1a3a6b" fontFamily="sans-serif">
      {t.you}
    </text>

    {/* ── Destination pin ── */}
    {/* Pin shadow */}
    <ellipse cx="298" cy="76" rx="6" ry="2.5"
      fill="rgba(0,0,0,0.18)" transform="translate(0,6)"/>
    {/* Pin body */}
    <path
      d="M 298 43 C 288 43 280 51 280 61 C 280 74 298 88 298 88
         C 298 88 316 74 316 61 C 316 51 308 43 298 43 Z"
      fill="#1a3a6b"
    />
    <path
      d="M 298 43 C 288 43 280 51 280 61 C 280 74 298 88 298 88
         C 298 88 316 74 316 61 C 316 51 308 43 298 43 Z"
      fill="url(#pinGrad)"
    />
    <circle cx="298" cy="61" r="7" fill="white" opacity="0.95"/>
    <circle cx="298" cy="61" r="3.5" fill="#4a7ac8"/>

    {/* Gradient def */}
    <defs>
      <linearGradient id="pinGrad" x1="0" y1="0" x2="1" y2="1">
        <stop offset="0%" stopColor="rgba(255,255,255,0.22)"/>
        <stop offset="100%" stopColor="transparent"/>
      </linearGradient>
    </defs>
  </svg>
);

// ── Screen ────────────────────────────────────────────────────────────────────
const Screen18 = () => {
  const { lang }   = useLang();
  const navigate   = useNavigate();
  const location   = useLocation();

  const isRTL    = lang === 'ar' || lang === 'he';
  const t        = UI[lang];

  const building = location.state?.building ?? null;
  const room     = location.state?.room     ?? null;

  return (
    <div className="layout-wrapper">
      <div className="layout-shell s18-shell" dir={isRTL ? 'rtl' : 'ltr'}>

        {/* ── Compact header ── */}
        <div className="s18-header">
          <button
            className="s18-back-btn"
            onClick={() => navigate('/screen/17', { state: { building } })}
            type="button"
            aria-label={t.back}
          >
            <BackArrow flip={isRTL} />
            <span>{t.back}</span>
          </button>

          {building && room && (
            <div className="s18-header-info">
              <span className="s18-header-building">{building.name}</span>
              <span className="s18-header-sep">·</span>
              <span className="s18-header-room">{room.name}</span>
            </div>
          )}
        </div>

        {/* ── Map container ── */}
        <div className="s18-map-wrap">
          <div className="s18-map-container">
            <img
              src={hospitalMap}
              alt="Hospital campus map"
              className="s18-map-img"
              draggable="false"
            />
            <RouteOverlay t={t} />
          </div>

          {/* Route ready badge */}
          <div className="s18-route-badge">
            <span className="s18-route-dot" />
            <span>{t.routeReady}</span>
          </div>
        </div>

        {/* ── Info card ── */}
        <div className="s18-info-card">

          <p className="s18-dest-label">{t.destination}</p>

          {building && room ? (
            <>
              <h2 className="s18-dest-name">{room.name}</h2>
              <p className="s18-dest-meta">
                <span
                  className="s18-building-chip"
                  style={{ color: building.iconColor, background: building.iconBg }}
                >
                  {building.tag}
                </span>
                <span className="s18-floor-chip">
                  {formatFloor(room.floor)}
                </span>
                <span className="s18-type-chip">
                  {room.type.replace('_', '\u00A0')}
                </span>
              </p>
            </>
          ) : (
            <h2 className="s18-dest-name">—</h2>
          )}

          {/* Stats row */}
          <div className="s18-stats">
            <div className="s18-stat">
              <ClockIcon />
              <span>{t.eta}</span>
            </div>
            <div className="s18-stat-divider" />
            <div className="s18-stat">
              <WalkIcon />
              <span>{t.distance}</span>
            </div>
          </div>

          {/* CTA */}
          <button className="s18-nav-btn" type="button">
            <span>{t.startNav}</span>
            <NavArrow flip={isRTL} />
          </button>

        </div>

      </div>
    </div>
  );
};

export default Screen18;
