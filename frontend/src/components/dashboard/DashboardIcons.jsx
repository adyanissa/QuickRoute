// Dashboard redesign — the few icons the new admin shell needs that
// DashboardPrimitives.jsx did not already provide. Same drawing
// convention as the existing set (24x24 viewBox, currentColor, 1.8
// stroke) so the sidebar, stat cards and entity cards all read as one
// consistent icon family rather than a mix of styles. No icon library is
// added — this project has never had one and this redesign does not
// introduce a dependency for six glyphs.

export const HomeIcon = ({ size = 18 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true">
    <path d="M3 10.2 12 3l9 7.2V20a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z"
      stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

export const BuildingIcon = ({ size = 20 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true">
    <path d="M4 21V6a1 1 0 0 1 1-1h7a1 1 0 0 1 1 1v15M13 21V10h6a1 1 0 0 1 1 1v10M3 21h18"
      stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
    <path d="M7 9h2M7 13h2M7 17h2M16 14h1M16 17h1"
      stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
  </svg>
);

export const SiteIcon = ({ size = 22 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true">
    <path d="M3 21V8l5-3 5 3v13M13 21V11l4-2.5 4 2.5v10M2 21h20"
      stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
    <path d="M6 12h2M6 16h2M16 15h2" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
  </svg>
);

export const LayersIcon = ({ size = 20 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true">
    <path d="m12 3 9 5-9 5-9-5 9-5zM3 13l9 5 9-5"
      stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

export const FloorsIcon = ({ size = 20 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true">
    <rect x="3" y="4" width="18" height="5" rx="1.4" stroke="currentColor" strokeWidth="1.8" />
    <rect x="3" y="11.5" width="18" height="5" rx="1.4" stroke="currentColor" strokeWidth="1.8" />
    <path d="M5 20h14" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
  </svg>
);

export const SparkIcon = ({ size = 20 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true">
    <path d="M12 3.5 13.7 9l5.5 1.7-5.5 1.7L12 18l-1.7-5.6L4.8 10.7 10.3 9z"
      stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
    <path d="M18.5 16.5 19.3 19l2.5.8-2.5.8-.8 2.4-.8-2.4L15.2 20l2.5-.9z"
      stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" />
  </svg>
);

export const BroomIcon = ({ size = 20 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true">
    <path d="M3 6h18M8 6v13a2 2 0 0 0 2 2h4a2 2 0 0 0 2-2V6M10 6V4a1 1 0 0 1 1-1h2a1 1 0 0 1 1 1v2"
      stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
    <path d="M11 11v6M14 11v6" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
  </svg>
);

export const AlertIcon = ({ size = 15 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true">
    <path d="M12 4.5 21 20H3z" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" />
    <path d="M12 10v4" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" />
    <circle cx="12" cy="17.2" r="0.95" fill="currentColor" />
  </svg>
);

export const PlusIcon = ({ size = 16 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true">
    <path d="M12 5v14M5 12h14" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" />
  </svg>
);
