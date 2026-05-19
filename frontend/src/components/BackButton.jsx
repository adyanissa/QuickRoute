import '../styles/BackButton.css';

const BackArrow = ({ isRTL }) => (
  <svg
    width="15" height="15" viewBox="0 0 24 24" fill="none" aria-hidden="true"
    style={isRTL ? { transform: 'scaleX(-1)' } : undefined}
  >
    <path
      d="M19 12H5M11 18l-6-6 6-6"
      stroke="currentColor" strokeWidth="2.2"
      strokeLinecap="round" strokeLinejoin="round"
    />
  </svg>
);

/**
 * Shared back button used across all screens.
 *
 * Props:
 *   onClick  – navigation handler
 *   label    – already-translated button text
 *   isRTL    – true when lang is 'ar' or 'he'
 *   spacing  – 'default' (gap below) | 'compact' (less gap below)
 */
const BackButton = ({ onClick, label, isRTL, spacing = 'default' }) => (
  <div className={`back-btn-row back-btn-row--${spacing}`}>
    <button
      type="button"
      className="back-btn"
      onClick={onClick}
      aria-label={label}
    >
      <BackArrow isRTL={isRTL} />
      <span>{label}</span>
    </button>
  </div>
);

export default BackButton;
