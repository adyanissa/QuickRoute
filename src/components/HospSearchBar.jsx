import React from 'react';
import '../styles/HospSearchBar.css';

const SearchIcon = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
    <circle cx="11" cy="11" r="7.5" stroke="currentColor" strokeWidth="2" strokeLinecap="round"/>
    <path d="M20.5 20.5l-4.35-4.35" stroke="currentColor" strokeWidth="2" strokeLinecap="round"/>
  </svg>
);

const ClearIcon = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden="true">
    <path d="M18 6L6 18M6 6l12 12" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round"/>
  </svg>
);

// isRTL is passed explicitly; the input's dir is set accordingly so the
// browser renders placeholder & typed text in the correct direction.
const HospSearchBar = ({ value, onChange, placeholder, isRTL = false }) => (
  <div className="hsb-wrap">
    <span className="hsb-icon" aria-hidden="true">
      <SearchIcon />
    </span>
    <input
      className="hsb-input"
      type="text"
      dir={isRTL ? 'rtl' : 'ltr'}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder || 'Search...'}
      autoComplete="off"
      spellCheck="false"
    />
    {value && (
      <button
        className="hsb-clear"
        onClick={() => onChange('')}
        aria-label="Clear search"
        type="button"
      >
        <ClearIcon />
      </button>
    )}
  </div>
);

export default HospSearchBar;
