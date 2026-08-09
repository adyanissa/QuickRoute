// RBAC/dashboard cleanup task (frontend completion), Section 3/4 — shared
// building blocks for the three genuinely-distinct admin dashboards
// (Super Admin / Global Manager / Building Manager). Deliberately reuses
// the exact classnames adminScreens.css already defines for the
// pre-existing single dashboard (adm-shell, adm-header, adm-stat,
// adm-nav-card, ...) so the blue-gradient/rounded-card/typography/icon
// design identity carries over unchanged — this file only adds NEW small
// pieces (breadcrumbs, hierarchy list rows, empty/error/loading states)
// that didn't exist before, using the same visual language.

export const ShieldIcon = () => (
  <svg width="13" height="13" viewBox="0 0 24 24" fill="none">
    <path d="M12 2L4 6v6c0 5.25 3.5 10.2 8 11.5C16.5 22.2 20 17.25 20 12V6L12 2z"
      stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/>
    <path d="M9 12l2 2 4-4" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/>
  </svg>
);

export const ChevronIcon = ({ rtl }) => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none">
    {rtl ? (
      <path d="M15 18l-6-6 6-6" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"/>
    ) : (
      <path d="M9 18l6-6-6-6" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"/>
    )}
  </svg>
);

export const MapIcon = () => (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
    <path d="M9 20L3 17V4l6 3M9 20l6-3M9 20V7M15 17l6 3V7l-6-3M15 17V4M9 7l6-3"
      stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/>
  </svg>
);

export const LocationIcon = () => (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
    <path d="M12 2C8.686 2 6 4.686 6 8c0 5.25 6 13 6 13s6-7.75 6-13c0-3.314-2.686-6-6-6z"
      stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/>
    <circle cx="12" cy="8" r="2" stroke="currentColor" strokeWidth="1.8"/>
  </svg>
);

export const RoomIcon = () => (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
    <rect x="3" y="3" width="18" height="18" rx="2" stroke="currentColor" strokeWidth="1.8"/>
    <path d="M9 3v18M3 9h6M3 15h6" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"/>
  </svg>
);

export const RouteIcon = () => (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
    <circle cx="6" cy="6" r="3" stroke="currentColor" strokeWidth="1.8"/>
    <circle cx="18" cy="18" r="3" stroke="currentColor" strokeWidth="1.8"/>
    <path d="M9 6h3a3 3 0 0 1 3 3v6a3 3 0 0 0 3 3" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"/>
  </svg>
);

export const CodeIcon = () => (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
    <rect x="3" y="3" width="7" height="7" rx="1.2" stroke="currentColor" strokeWidth="1.8"/>
    <rect x="14" y="3" width="7" height="7" rx="1.2" stroke="currentColor" strokeWidth="1.8"/>
    <rect x="3" y="14" width="7" height="7" rx="1.2" stroke="currentColor" strokeWidth="1.8"/>
    <path d="M14 14h3v3h-3zM18 18h3v3h-3zM18 14h3M14 18v3" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"/>
  </svg>
);

export const KeyIcon = () => (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
    <circle cx="8" cy="15" r="4" stroke="currentColor" strokeWidth="1.8"/>
    <path d="M11 12l8-8M17 6l2 2M14 9l2 2" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/>
  </svg>
);

export const LogoutIcon = () => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none">
    <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9"
      stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
  </svg>
);

export const PinIcon = () => (
  <svg width="11" height="11" viewBox="0 0 24 24" fill="currentColor">
    <path d="M12 2a7 7 0 0 1 7 7c0 5.25-7 13-7 13S5 14.25 5 9a7 7 0 0 1 7-7z" opacity="0.9"/>
    <circle cx="12" cy="9" r="2.8" fill="white"/>
  </svg>
);

// A single scoped metric — always paired with its own label so a number
// can never be shown without stating exactly what it's scoped to
// (Problem 2.1's "never a bare number" rule, extended to every dashboard
// level).
export const ScopedStat = ({ value, label, color }) => (
  <div className="adm-stat">
    <div className="adm-stat-num" style={{ color: color || '#2a5298' }}>
      {value === null || value === undefined ? '—' : value}
    </div>
    <div className="adm-stat-lbl">{label}</div>
  </div>
);

// Breadcrumb trail for the Super Admin hierarchy (All Locations -> Campus
// -> Building -> Map Group/Floor -> Map Workspace). `items` is
// [{ label, onClick }] — the last item is always the current, non-
// clickable level.
export const Breadcrumbs = ({ items, isRTL }) => (
  <nav
    aria-label="breadcrumb"
    style={{
      display: 'flex',
      flexWrap: 'wrap',
      alignItems: 'center',
      gap: 6,
      padding: '10px 4px',
      fontSize: 12.5,
      color: 'rgba(255,255,255,0.85)',
    }}
  >
    {items.map((item, index) => {
      const isLast = index === items.length - 1;
      return (
        <span key={`${item.label}-${index}`} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          {index > 0 && (
            <span style={{ opacity: 0.6 }}>
              <ChevronIcon rtl={isRTL} />
            </span>
          )}
          {isLast || !item.onClick ? (
            <span style={{ fontWeight: 700, color: 'white' }}>{item.label}</span>
          ) : (
            <button
              type="button"
              onClick={item.onClick}
              style={{
                border: 'none',
                background: 'transparent',
                color: 'rgba(255,255,255,0.85)',
                fontSize: 12.5,
                cursor: 'pointer',
                padding: 0,
                textDecoration: 'underline',
              }}
            >
              {item.label}
            </button>
          )}
        </span>
      );
    })}
  </nav>
);

// A single clickable hierarchy row (Campus / Building / Map Group /
// Map) — reuses adm-nav-card's rounded-card visual language but as a
// plain list row (icon + title + optional subtitle + scoped metric +
// chevron) so a long hierarchy list never turns into a wall of giant
// cards.
export const HierarchyRow = ({ icon, title, subtitle, metricValue, metricLabel, onClick, isRTL }) => (
  <button
    type="button"
    className="adm-nav-card"
    onClick={onClick}
    style={{ textAlign: isRTL ? 'right' : 'left' }}
  >
    <div
      className="adm-nav-card-icon"
      style={{ background: 'linear-gradient(135deg, #1a3a6b, #2a5298)' }}
    >
      {icon}
    </div>
    <div className="adm-nav-card-body">
      <div className="adm-nav-card-title">{title}</div>
      {subtitle && <div className="adm-nav-card-desc">{subtitle}</div>}
    </div>
    <div className="adm-nav-card-right">
      {metricValue !== undefined && metricValue !== null && (
        <div style={{ textAlign: 'center' }}>
          <div className="adm-nav-card-num">{metricValue}</div>
          <div className="adm-nav-card-clbl">{metricLabel}</div>
        </div>
      )}
      <ChevronIcon rtl={isRTL} />
    </div>
  </button>
);

export const DashboardEmptyState = ({ icon, title, hint }) => (
  <div className="adm-empty">
    {icon && <div className="adm-empty-icon">{icon}</div>}
    <div className="adm-empty-txt">{title}</div>
    {hint && <div className="adm-empty-hint">{hint}</div>}
  </div>
);

export const DashboardErrorState = ({ message }) => (
  <div
    style={{
      marginBottom: 16,
      padding: 12,
      borderRadius: 12,
      background: '#ffe9e9',
      color: '#a92323',
      fontSize: 14,
    }}
    role="alert"
  >
    {message}
  </div>
);

export const DashboardLoadingState = ({ message }) => (
  <div className="adm-empty">
    <div className="adm-empty-txt">{message}</div>
  </div>
);

export const LANGUAGES = [
  { code: 'ar', label: 'عربي' },
  { code: 'he', label: 'עברית' },
  { code: 'en', label: 'EN' },
];

export const LangPill = ({ lang, setLang }) => (
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
);
