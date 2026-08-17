// Dashboard redesign — the small reusable pieces the admin Overview is
// built from. All of them are presentational: they render values the
// caller already derived from real backend responses (see
// utils/dashboardModel.js) and never fetch, compute or default a metric
// themselves. A metric the caller has not loaded yet is passed as null
// and rendered as an em dash, never as 0.

import { ChevronIcon, PinIcon } from './DashboardPrimitives';

export const DashboardStatCard = ({ icon, tint, value, label, hint }) => (
  <div className="qrd-stat">
    <span
      className="qrd-stat-icon"
      style={{ background: tint?.bg || 'var(--bg-secondary)', color: tint?.fg || 'var(--blue-mid)' }}
      aria-hidden="true"
    >
      {icon}
    </span>
    <span className="qrd-stat-body">
      <span className="qrd-stat-num">
        {value === null || value === undefined ? '—' : value}
      </span>
      <span className="qrd-stat-lbl">{label}</span>
      {hint && <span className="qrd-stat-hint">{hint}</span>}
    </span>
  </div>
);

// One clickable row/card for any level of the hierarchy: Site, Building,
// Map Group or Floor. `metrics` is [{ value, label }] — an empty list
// simply renders no metric strip rather than placeholder zeros.
export const EntityCard = ({
  icon,
  softIcon,
  title,
  place,
  metrics = [],
  status,
  isRTL,
  onClick,
}) => (
  <button type="button" className="qrd-entity" onClick={onClick}>
    <span className={`qrd-entity-icon${softIcon ? ' is-soft' : ''}`} aria-hidden="true">
      {icon}
    </span>

    <span className="qrd-entity-body">
      <span className="qrd-entity-title">{title}</span>
      {place && (
        <span className="qrd-entity-place">
          <PinIcon />
          {place}
        </span>
      )}
      {metrics.length > 0 && (
        <span className="qrd-metrics">
          {metrics.map((metric) => (
            <span className="qrd-metric" key={metric.label}>
              <span className="qrd-metric-num">
                {metric.value === null || metric.value === undefined ? '—' : metric.value}
              </span>
              <span className="qrd-metric-lbl">{metric.label}</span>
            </span>
          ))}
        </span>
      )}
    </span>

    {status && (
      <span className={`qrd-pill${status.muted ? ' is-muted' : ''}`}>{status.label}</span>
    )}

    <span className="qrd-entity-chev" aria-hidden="true">
      <ChevronIcon rtl={isRTL} />
    </span>
  </button>
);

export const CategoryTabs = ({ tabs, activeKey, onSelect }) => {
  if (!tabs || tabs.length === 0) return null;

  return (
    <div className="qrd-tabs" role="tablist">
      {tabs.map((tab) => (
        <button
          key={tab.key}
          type="button"
          role="tab"
          aria-selected={tab.key === activeKey}
          className={`qrd-tab${tab.key === activeKey ? ' is-active' : ''}`}
          onClick={() => onSelect(tab.key)}
        >
          {tab.label}
          <span className="qrd-tab-count">{tab.count}</span>
        </button>
      ))}
    </div>
  );
};

export const ToolCard = ({ icon, title, description, destructive, onClick }) => (
  <button
    type="button"
    className={`qrd-tool${destructive ? ' is-destructive' : ''}`}
    onClick={onClick}
  >
    <span className="qrd-tool-icon" aria-hidden="true">{icon}</span>
    <span className="qrd-tool-body">
      <span className="qrd-tool-title">{title}</span>
      {description && <span className="qrd-tool-desc">{description}</span>}
    </span>
  </button>
);

export const SectionHead = ({ title, subtitle, action }) => (
  <div className="qrd-section-head">
    <div>
      <div className="qrd-section-title">{title}</div>
      {subtitle && <div className="qrd-section-sub">{subtitle}</div>}
    </div>
    {action}
  </div>
);

// Breadcrumb trail for the Site -> Building -> Map Group -> Floor
// context. The last entry is always the current, non-clickable level, so
// an admin can always read exactly which map they are about to modify.
export const Crumbs = ({ items, isRTL }) => (
  <nav className="qrd-crumbs" aria-label="Breadcrumb">
    {items.map((item, index) => {
      const isLast = index === items.length - 1;
      return (
        <span className="qrd-crumb" key={`${item.label}-${index}`}>
          {index > 0 && (
            <span className="qrd-crumb-sep" aria-hidden="true">
              <ChevronIcon rtl={isRTL} />
            </span>
          )}
          {isLast || !item.onClick ? (
            <span className="qrd-crumb-current">{item.label}</span>
          ) : (
            <button type="button" className="qrd-crumb-btn" onClick={item.onClick}>
              {item.label}
            </button>
          )}
        </span>
      );
    })}
  </nav>
);

export const StatePanel = ({ icon, title, hint, action }) => (
  <div className="qrd-panel">
    {icon && <div className="qrd-panel-icon">{icon}</div>}
    <div className="qrd-panel-title">{title}</div>
    {hint && <div className="qrd-panel-hint">{hint}</div>}
    {action && <div style={{ marginBlockStart: 16 }}>{action}</div>}
  </div>
);

export const AlertBar = ({ message }) => (
  <div className="qrd-alert" role="alert">{message}</div>
);
