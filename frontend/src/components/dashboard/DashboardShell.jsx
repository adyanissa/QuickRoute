// Dashboard redesign — the shared shell every admin-tier role sees:
// slim white sidebar (logo + permitted global navigation + logout) and a
// main column whose upper area keeps QuickRoute's navy/blue gradient and
// whose lower area keeps the existing soft light-blue content background.
//
// The shell is PRESENTATIONAL. It renders whatever navigation items it is
// handed; deciding which items exist is
// utils/dashboardPermissions.buildSidebarItems(), which mirrors the
// backend dependencies. A hidden item is never a security boundary — the
// backend gate on each route is unchanged and remains authoritative.
//
// The same shell serves LTR (en) and RTL (ar/he): `dir` is set once here
// and dashboardShell.css uses logical properties throughout.

import { LangPill } from './DashboardPrimitives';
import '../../styles/adminScreens.css';
import '../../styles/dashboardShell.css';
import '../../styles/adminShellPages.css';

const BrandMark = () => (
  <span className="qrd-brand-mark" aria-hidden="true">
    <svg width="34" height="34" viewBox="0 0 40 40" fill="none">
      <rect width="40" height="40" rx="12" fill="url(#qrdBrand)" />
      <path
        d="M20 10c-3.6 0-6.5 2.9-6.5 6.5 0 4.9 6.5 13.5 6.5 13.5s6.5-8.6 6.5-13.5c0-3.6-2.9-6.5-6.5-6.5z"
        fill="#fff"
      />
      <circle cx="20" cy="16.5" r="2.6" fill="#1a3a6b" />
      <defs>
        <linearGradient id="qrdBrand" x1="0" y1="0" x2="40" y2="40">
          <stop stopColor="#1a3a6b" />
          <stop offset="1" stopColor="#2a5298" />
        </linearGradient>
      </defs>
    </svg>
  </span>
);

export const SidebarItem = ({ icon, label, isActive, onClick }) => (
  <button
    type="button"
    className={`qrd-nav-item${isActive ? ' is-active' : ''}`}
    onClick={onClick}
    aria-current={isActive ? 'page' : undefined}
  >
    <span className="qrd-nav-icon">{icon}</span>
    <span>{label}</span>
  </button>
);

// `initial` is derived from the user's real full_name by the caller; the
// role line under the name is the user's real backend role, translated.
export const DashboardHeader = ({ lang, setLang, userName, roleLabel, initial }) => (
  <div className="qrd-topbar">
    <LangPill lang={lang} setLang={setLang} />
    <span className="qrd-topbar-divider" aria-hidden="true" />
    <div className="qrd-user">
      <span className="qrd-avatar" aria-hidden="true">{initial}</span>
      <span className="qrd-user-meta">
        <span className="qrd-user-name">{userName}</span>
        <span className="qrd-user-role">{roleLabel}</span>
      </span>
    </div>
  </div>
);

export const DashboardShell = ({
  isRTL,
  compact,
  navItems,
  logoutLabel,
  logoutIcon,
  onLogout,
  header,
  children,
}) => (
  <div className="qrd-root" dir={isRTL ? 'rtl' : 'ltr'}>
    <aside className="qrd-sidebar">
      <div className="qrd-brand">
        <BrandMark />
        <span className="qrd-brand-text">Quick<span>Route</span></span>
      </div>

      <nav className="qrd-nav" aria-label="Main">
        {navItems.map((item) => (
          <SidebarItem
            key={item.key}
            icon={item.icon}
            label={item.label}
            isActive={item.isActive}
            onClick={item.onClick}
          />
        ))}
      </nav>

      <div className="qrd-sidebar-foot">
        <button type="button" className="qrd-logout" onClick={onLogout}>
          <span className="qrd-nav-icon">{logoutIcon}</span>
          <span>{logoutLabel}</span>
        </button>
      </div>
    </aside>

    <main className={`qrd-main${compact ? ' is-compact' : ''}`}>
      {header}
      {children}
    </main>
  </div>
);

export default DashboardShell;
