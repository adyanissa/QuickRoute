// The ONE content header every admin page below Overview uses: Back +
// breadcrumb + title + optional description + optional primary action.
//
// Before this component each admin screen painted its own full-width navy
// hero header (`.adm-inner-header`), which is why opening Map Management
// or Invitation Codes felt like leaving the product. The navy identity now
// belongs to the shared shell (see AdminLayout/DashboardShell); this header
// only supplies the page's own content on top of it.
//
// Back is deterministic — the caller passes an explicit route (resolved by
// utils/adminNavigation.js), never history.back(), so a page opened from a
// pasted URL, a redirect or a fresh session still lands somewhere inside
// QuickRoute. The arrow mirrors in RTL via the shared BackArrow below.

import { Link } from 'react-router-dom';
import { Crumbs } from './DashboardCards';

export const BackArrow = ({ isRTL }) => (
  <svg
    width="15"
    height="15"
    viewBox="0 0 24 24"
    fill="none"
    aria-hidden="true"
    style={isRTL ? { transform: 'scaleX(-1)' } : undefined}
  >
    <path
      d="M19 12H5M11 18l-6-6 6-6"
      stroke="currentColor"
      strokeWidth="2.2"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);

const AdminPageHeader = ({
  backTo,
  onBack,
  backLabel,
  crumbs,
  title,
  description,
  action,
  isRTL,
}) => (
  <header className="qrd-pagehead">
    {/* `onBack` exists for the few screens whose Back is an in-page step
        (an open add/edit form returning to its own list) rather than a
        route change. Everything else uses a real <Link> to a deterministic
        route, so Back is a normal, middle-clickable link. */}
    {onBack ? (
      <button type="button" className="qrd-back" onClick={onBack}>
        <BackArrow isRTL={isRTL} />
        <span>{backLabel}</span>
      </button>
    ) : (
      backTo && (
        <Link className="qrd-back" to={backTo}>
          <BackArrow isRTL={isRTL} />
          <span>{backLabel}</span>
        </Link>
      )
    )}

    {crumbs && crumbs.length > 0 && <Crumbs items={crumbs} isRTL={isRTL} />}

    <div className="qrd-pagehead-row">
      <div className="qrd-pagehead-main">
        <h1 className="qrd-pagehead-title">{title}</h1>
        {description && <p className="qrd-pagehead-desc">{description}</p>}
      </div>
      {action && <div className="qrd-pagehead-action">{action}</div>}
    </div>
  </header>
);

export default AdminPageHeader;
