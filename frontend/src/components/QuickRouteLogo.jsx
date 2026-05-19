import React from 'react';

const QuickRouteLogo = ({ size = 42 }) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 100 100"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
  >
    {/* Map grid lines */}
    <rect x="10" y="10" width="80" height="80" rx="8" stroke="rgba(255,255,255,0.35)" strokeWidth="2" fill="none"/>
    {/* Horizontal roads */}
    <rect x="10" y="30" width="30" height="6" rx="2" fill="rgba(255,255,255,0.55)"/>
    <rect x="60" y="30" width="30" height="6" rx="2" fill="rgba(255,255,255,0.55)"/>
    <rect x="10" y="64" width="80" height="6" rx="2" fill="rgba(255,255,255,0.40)"/>
    {/* Vertical road */}
    <rect x="44" y="10" width="6" height="28" rx="2" fill="rgba(255,255,255,0.55)"/>
    <rect x="44" y="64" width="6" height="26" rx="2" fill="rgba(255,255,255,0.40)"/>
    {/* Route path */}
    <path
      d="M25 67 Q25 47 47 47 Q65 47 65 33"
      stroke="rgba(255,255,255,0.9)"
      strokeWidth="3.5"
      strokeLinecap="round"
      fill="none"
      strokeDasharray="0"
    />
    {/* Location pin */}
    <circle cx="65" cy="27" r="9" fill="white" opacity="0.95"/>
    <circle cx="65" cy="26" r="4" fill="#4a7ac8"/>
    <path d="M65 33 L62 38 Q65 40 68 38 Z" fill="white" opacity="0.95"/>
    {/* Start dot */}
    <circle cx="25" cy="67" r="4.5" fill="rgba(255,255,255,0.8)"/>
    <circle cx="25" cy="67" r="2" fill="white"/>
  </svg>
);

export default QuickRouteLogo;
