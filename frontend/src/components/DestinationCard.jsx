import React from 'react';
import '../styles/DestinationCard.css';

// ── Building category icons ──────────────────────────────────────────────────
const CategoryIcon = ({ category, color: c }) => {
  const icons = {
    pediatrics: (
      <>
        <circle cx="12" cy="6" r="3" stroke={c} strokeWidth="1.8"/>
        <path d="M9 11h6l1 9H8l1-9z" stroke={c} strokeWidth="1.8" strokeLinejoin="round" fill="none"/>
        <path d="M10 15h4" stroke={c} strokeWidth="1.8" strokeLinecap="round"/>
      </>
    ),
    cardiology: (
      <path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"
        stroke={c} strokeWidth="1.8" fill="none" strokeLinecap="round" strokeLinejoin="round"/>
    ),
    imaging: (
      <>
        <circle cx="12" cy="12" r="3.5" stroke={c} strokeWidth="1.8"/>
        <circle cx="12" cy="12" r="7" stroke={c} strokeWidth="1.4" strokeDasharray="2.5 2"/>
        <path d="M12 2v2.5M12 19.5V22M2 12h2.5M19.5 12H22" stroke={c} strokeWidth="1.8" strokeLinecap="round"/>
      </>
    ),
    rehabilitation: (
      <>
        <circle cx="12" cy="5" r="2.5" stroke={c} strokeWidth="1.8"/>
        <path d="M7 10.5c0 0 2-1 5-1s5 1 5 1" stroke={c} strokeWidth="1.8" strokeLinecap="round"/>
        <path d="M12 9.5v5M9 21l3-6.5 3 6.5" stroke={c} strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/>
        <path d="M8 12.5l-2 4M16 12.5l2 4" stroke={c} strokeWidth="1.8" strokeLinecap="round"/>
      </>
    ),
    oncology: (
      <>
        <path d="M12 3c-2.2 0-4 1.8-4 4 0 1.8 1 3.5 2.5 5l1.5 2 1.5-2C15 10.5 16 8.8 16 7c0-2.2-1.8-4-4-4z"
          stroke={c} strokeWidth="1.6" fill="none" strokeLinecap="round"/>
        <path d="M9.5 12C8 13.5 5.5 15.5 5.5 18a3 3 0 0 0 6 0c0-1-.5-2-1.5-3"
          stroke={c} strokeWidth="1.6" fill="none" strokeLinecap="round"/>
        <path d="M14.5 12C16 13.5 18.5 15.5 18.5 18a3 3 0 0 1-6 0c0-1 .5-2 1.5-3"
          stroke={c} strokeWidth="1.6" fill="none" strokeLinecap="round"/>
      </>
    ),
    maternity: (
      <>
        <circle cx="12" cy="6" r="2.5" stroke={c} strokeWidth="1.8"/>
        <path d="M8 12c0-2.2 1.8-4 4-4s4 1.8 4 4v2a4 4 0 0 1-8 0v-2z"
          stroke={c} strokeWidth="1.8" fill="none"/>
        <circle cx="12" cy="14" r="1.2" fill={c} opacity="0.5"/>
      </>
    ),
    neurology: (
      <>
        <path d="M9 3a3 3 0 0 1 6 0M3 9a3 3 0 0 1 3-3h12a3 3 0 0 1 3 3M3 15a3 3 0 0 0 3 3h12a3 3 0 0 0 3-3"
          stroke={c} strokeWidth="1.6" fill="none" strokeLinecap="round"/>
        <path d="M9 3v18M15 3v18" stroke={c} strokeWidth="1.6" strokeLinecap="round" strokeDasharray="2 2"/>
        <path d="M3 9h18M3 15h18" stroke={c} strokeWidth="1.6" strokeLinecap="round"/>
      </>
    ),
    general: (
      <>
        <path d="M3 22V10l9-7 9 7v12H3z" stroke={c} strokeWidth="1.8" fill="none" strokeLinejoin="round"/>
        <rect x="9" y="14" width="6" height="8" rx="1" stroke={c} strokeWidth="1.6" fill="none"/>
        <rect x="5" y="12" width="3" height="3" rx="0.5" stroke={c} strokeWidth="1.4" fill="none"/>
        <rect x="16" y="12" width="3" height="3" rx="0.5" stroke={c} strokeWidth="1.4" fill="none"/>
      </>
    ),
    inpatient: (
      <>
        <path d="M3 9h4v8H3M7 9h14" stroke={c} strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/>
        <rect x="7" y="11" width="14" height="6" rx="1.5" stroke={c} strokeWidth="1.8" fill="none"/>
        <path d="M3 20h18M6 17v3M18 17v3" stroke={c} strokeWidth="1.8" strokeLinecap="round"/>
      </>
    ),
    outpatient: (
      <>
        <rect x="3" y="5" width="18" height="16" rx="2" stroke={c} strokeWidth="1.8" fill="none"/>
        <path d="M16 3v4M8 3v4M3 11h18" stroke={c} strokeWidth="1.8" strokeLinecap="round"/>
        <path d="M8 15h.01M12 15h.01M16 15h.01M8 19h.01M12 19h.01" stroke={c} strokeWidth="2" strokeLinecap="round"/>
      </>
    ),
    surgery: (
      <>
        <circle cx="7.5" cy="7.5" r="2.5" stroke={c} strokeWidth="1.8" fill="none"/>
        <circle cx="16.5" cy="16.5" r="2.5" stroke={c} strokeWidth="1.8" fill="none"/>
        <path d="M6 6L18 18M9.5 6.5l9 9" stroke={c} strokeWidth="1.6" strokeLinecap="round"/>
      </>
    ),
    research: (
      <>
        <path d="M9 3h6M9 3v8l-4.5 7a1.5 1.5 0 0 0 1.3 2.3h12.4a1.5 1.5 0 0 0 1.3-2.3L15 11V3"
          stroke={c} strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" fill="none"/>
        <circle cx="10" cy="17" r="0.8" fill={c}/>
        <circle cx="14" cy="15" r="0.8" fill={c}/>
        <circle cx="12" cy="19" r="0.8" fill={c}/>
      </>
    ),
    children: (
      <path d="M12 2l2.5 5.5L20 8.5l-4 4 .9 5.5L12 15.5l-4.9 2.5.9-5.5-4-4 5.5-1L12 2z"
        stroke={c} strokeWidth="1.8" fill="none" strokeLinejoin="round"/>
    ),
    mri: (
      <>
        <path d="M6 5h2a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2z"
          stroke={c} strokeWidth="1.8" fill="none"/>
        <path d="M14 5h4a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-4"
          stroke={c} strokeWidth="1.8" fill="none" strokeLinecap="round"/>
        <path d="M10 9h4M10 12h4M10 15h4" stroke={c} strokeWidth="1.4" strokeLinecap="round" opacity="0.5"/>
        <path d="M2 12h2M20 12h2" stroke={c} strokeWidth="2" strokeLinecap="round"/>
      </>
    ),
    support: (
      <path d="M17 11V7a2 2 0 0 0-2-2 2 2 0 0 0-2 2M13 10V5a2 2 0 0 0-2-2 2 2 0 0 0-2 2v2M9 9V6a2 2 0 0 0-2-2 2 2 0 0 0-2 2v9a5 5 0 0 0 5 5h3a5 5 0 0 0 5-5v-3a2 2 0 0 0-2-2 2 2 0 0 0-2 2"
        stroke={c} strokeWidth="1.7" fill="none" strokeLinecap="round" strokeLinejoin="round"/>
    ),
    logistics: (
      <>
        <rect x="1" y="4" width="14" height="12" rx="1.5" stroke={c} strokeWidth="1.8" fill="none"/>
        <path d="M15 8h4.5l3.5 4v4H15V8z" stroke={c} strokeWidth="1.8" fill="none" strokeLinejoin="round"/>
        <circle cx="5.5" cy="18.5" r="2" stroke={c} strokeWidth="1.8"/>
        <circle cx="18.5" cy="18.5" r="2" stroke={c} strokeWidth="1.8"/>
      </>
    ),
    warehouse: (
      <>
        <path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"
          stroke={c} strokeWidth="1.8" fill="none"/>
        <path d="M3.27 6.96L12 12.01l8.73-5.05M12 22.08V12"
          stroke={c} strokeWidth="1.8" strokeLinecap="round"/>
      </>
    ),
    religious: (
      <>
        <path d="M12 3l3 6H9l3-6z" stroke={c} strokeWidth="1.5" fill="none" strokeLinejoin="round"/>
        <path d="M12 21l-3-6h6l-3 6z" stroke={c} strokeWidth="1.5" fill="none" strokeLinejoin="round"/>
        <path d="M6 9l6 3-6 3M18 9l-6 3 6 3" stroke={c} strokeWidth="1" strokeLinecap="round" opacity="0.4"/>
      </>
    ),
  };
  return (
    <svg width="24" height="24" viewBox="0 0 24 24" fill="none">
      {icons[category] || icons.general}
    </svg>
  );
};

// ── Room type icons ───────────────────────────────────────────────────────────
const TypeIcon = ({ type, color: c }) => {
  const icons = {
    emergency: (
      <path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z"
        fill={c} opacity="0.85"/>
    ),
    room: (
      <>
        <rect x="3" y="3" width="18" height="18" rx="3" stroke={c} strokeWidth="1.8" fill="none"/>
        <path d="M3 9h18M9 9v12" stroke={c} strokeWidth="1.6" strokeLinecap="round"/>
      </>
    ),
    clinic: (
      <>
        <path d="M5 13a7 7 0 1 0 14 0 7 7 0 0 0-14 0z" stroke={c} strokeWidth="1.8" fill="none"/>
        <path d="M12 10v6M9 13h6" stroke={c} strokeWidth="2" strokeLinecap="round"/>
        <path d="M8.5 5.5L7 3M15.5 5.5L17 3" stroke={c} strokeWidth="1.6" strokeLinecap="round"/>
      </>
    ),
    lab: (
      <>
        <path d="M9 3h6M9 3v6l-4 7a1.5 1.5 0 0 0 1.3 2.3h11.4a1.5 1.5 0 0 0 1.3-2.3L15 9V3"
          stroke={c} strokeWidth="1.8" strokeLinecap="round" fill="none"/>
        <circle cx="10" cy="15.5" r="0.7" fill={c}/>
        <circle cx="13.5" cy="13.5" r="0.7" fill={c}/>
      </>
    ),
    office: (
      <>
        <rect x="2" y="7" width="20" height="14" rx="2" stroke={c} strokeWidth="1.8" fill="none"/>
        <path d="M16 7V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v2" stroke={c} strokeWidth="1.8" strokeLinecap="round"/>
        <path d="M2 12h20" stroke={c} strokeWidth="1.6" strokeLinecap="round" opacity="0.5"/>
      </>
    ),
    waiting_area: (
      <>
        <circle cx="12" cy="12" r="9" stroke={c} strokeWidth="1.8" fill="none"/>
        <path d="M12 7v5l3.5 2" stroke={c} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
      </>
    ),
    reception: (
      <>
        <circle cx="9" cy="7" r="3" stroke={c} strokeWidth="1.8" fill="none"/>
        <path d="M3 21v-2a6 6 0 0 1 6-6h6a6 6 0 0 1 6 6v2"
          stroke={c} strokeWidth="1.8" strokeLinecap="round" fill="none"/>
      </>
    ),
    imaging: (
      <>
        <rect x="2" y="6" width="20" height="14" rx="2.5" stroke={c} strokeWidth="1.8" fill="none"/>
        <circle cx="12" cy="13" r="3.5" stroke={c} strokeWidth="1.8" fill="none"/>
        <path d="M6 6V4M18 6V4" stroke={c} strokeWidth="1.6" strokeLinecap="round"/>
        <circle cx="12" cy="13" r="1" fill={c} opacity="0.6"/>
      </>
    ),
    pharmacy: (
      <>
        <rect x="4" y="4" width="16" height="16" rx="3" stroke={c} strokeWidth="1.8" fill="none"/>
        <path d="M12 8v8M8 12h8" stroke={c} strokeWidth="2.2" strokeLinecap="round"/>
      </>
    ),
  };
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
      {icons[type] || icons.room}
    </svg>
  );
};

// ── Helpers ───────────────────────────────────────────────────────────────────
const TYPE_STYLE = {
  emergency:    { color: '#e74c3c', bg: 'rgba(231,76,60,0.12)' },
  room:         { color: '#2a5298', bg: 'rgba(42,82,152,0.12)' },
  clinic:       { color: '#27ae60', bg: 'rgba(39,174,96,0.12)' },
  lab:          { color: '#8e44ad', bg: 'rgba(142,68,173,0.12)' },
  office:       { color: '#7f8c8d', bg: 'rgba(127,140,141,0.12)' },
  waiting_area: { color: '#e67e22', bg: 'rgba(230,126,34,0.12)' },
  reception:    { color: '#4a7ac8', bg: 'rgba(74,122,200,0.12)' },
  imaging:      { color: '#7c5cbf', bg: 'rgba(124,92,191,0.12)' },
  pharmacy:     { color: '#16a085', bg: 'rgba(22,160,133,0.12)' },
};

export const formatFloor = (floor) => {
  if (floor < 0) return `B${Math.abs(floor)}`;
  if (floor === 0) return 'G';
  return `F${floor}`;
};

// ── DestinationCard ───────────────────────────────────────────────────────────
// variant="building" → building list card (Screen 16)
// variant="room"     → room list card    (Screen 17)
// selected           → highlighted state  (Screen 17)
// disabled           → room has no valid graph connection yet (Screen 17) —
//                       the card is shown (never hidden) but not clickable,
//                       with `disabledLabel` shown in place of the chevron
//                       instead of any admin-style "NO GRAPH CONNECTION"
//                       badge (QuickRoute UX Final Cleanup, Part 5).

const DestinationCard = ({ variant = 'building', data, onClick, selected = false, disabled = false, disabledLabel = '' }) => {
  if (variant === 'building') {
    return (
      <button
        className="dcard dcard-building"
        onClick={onClick}
        type="button"
        aria-pressed={false}
      >
        <div className="dcard-icon-box" style={{ background: data.iconBg }}>
          <CategoryIcon category={data.category} color={data.iconColor} />
        </div>

        <div className="dcard-body">
          <span className="dcard-name dcard-name-he">{data.name}</span>
          <span className="dcard-sub">{data.nameEn}</span>
        </div>

        <span
          className="dcard-tag"
          style={{ color: data.iconColor, background: data.iconBg, borderColor: `${data.iconColor}28` }}
        >
          {data.tag}
        </span>

        <span className="dcard-chevron" aria-hidden="true">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
            <path d="M9 18l6-6-6-6" stroke="currentColor" strokeWidth="2.2"
              strokeLinecap="round" strokeLinejoin="round"/>
          </svg>
        </span>
      </button>
    );
  }

  // variant === 'room'
  const ts = TYPE_STYLE[data.type] || TYPE_STYLE.room;

  return (
    <button
      className={`dcard dcard-room${selected ? ' dcard-selected' : ''}${disabled ? ' dcard-disabled' : ''}`}
      onClick={disabled ? undefined : onClick}
      type="button"
      aria-pressed={selected}
      aria-disabled={disabled}
      disabled={disabled}
    >
      <div className="dcard-icon-box dcard-icon-sm" style={{ background: selected ? ts.bg : ts.bg }}>
        <TypeIcon type={data.type} color={ts.color} />
      </div>

      <div className="dcard-body">
        <span className="dcard-name">{data.name}</span>
        {disabled
          ? <span className="dcard-disabled-note">{disabledLabel}</span>
          : (data.description && <span className="dcard-sub">{data.description}</span>)}
      </div>

      <div className="dcard-room-meta">
        <span className="dcard-floor-badge" style={{ color: ts.color, background: ts.bg }}>
          {formatFloor(data.floor)}
        </span>
        {!disabled && (
          <span className="dcard-type-chip" style={{ color: ts.color }}>
            {data.type.replace('_', '\u00A0')}
          </span>
        )}
      </div>

      {!disabled && (
        <span className="dcard-chevron" aria-hidden="true">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
            <path d="M9 18l6-6-6-6" stroke="currentColor" strokeWidth="2.2"
              strokeLinecap="round" strokeLinejoin="round"/>
          </svg>
        </span>
      )}
    </button>
  );
};

export default DestinationCard;
