// The single admin application shell. Mounted as a React Router LAYOUT
// route, so the white sidebar, the QuickRoute branding and the
// language/identity header are rendered ONCE and stay mounted while the
// admin moves between Overview, Sites & Buildings, a Building Workspace, a
// Floor Workspace, Map Management, Invitation Codes and every map tool.
// Nothing below it paints its own page chrome any more.
//
// This is presentation only. Which sidebar entries exist comes from
// utils/dashboardPermissions.buildSidebarItems(), which mirrors the backend
// dependencies; which DATA each page shows is decided by the backend's own
// scoping. A hidden sidebar entry is not a security boundary — every route
// underneath is still wrapped in its own RequireRole/RequireGlobalAdmin/
// RequireSuperAdmin guard in App.jsx, and every endpoint still enforces its
// own authorization.
//
// The end-user (regular_user) flow never renders this shell: RequireRole
// bounces a non-admin to the end-user home before this component mounts,
// and the
// public screens have their own unchanged layout.

import { useCallback, useMemo } from 'react';
import { Outlet, useLocation, useNavigate } from 'react-router-dom';
import { useLang } from '../../context/LangContext';
import { useAuth } from '../../context/AuthContext';
import { ROUTES } from '../../config/routes';
import { buildSidebarItems } from '../../utils/dashboardPermissions';
import {
  ADMIN_ROUTES,
  resolveSidebarActiveKey,
} from '../../utils/adminNavigation';
import {
  resolveUserDisplayName,
  resolveUserInitial,
  resolveRoleLabel,
} from '../../utils/adminIdentity';
import { DashboardShell, DashboardHeader } from './DashboardShell';
import { KeyIcon, LogoutIcon, MapIcon } from './DashboardPrimitives';
import { HomeIcon, SiteIcon } from './DashboardIcons';
import dashboardUi from '../../screens/dashboards/dashboardUi';

const NAV_ICONS = {
  overview: <HomeIcon />,
  sites: <SiteIcon size={18} />,
  mapManagement: <MapIcon />,
  invitations: <KeyIcon />,
};

const AdminLayout = () => {
  const { lang, setLang } = useLang();
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  const t = dashboardUi[lang] || dashboardUi.en;
  const isRTL = t.dir === 'rtl';

  const activeKey = resolveSidebarActiveKey(location.pathname);

  const navItems = useMemo(
    () =>
      buildSidebarItems(user).map((item) => ({
        key: item.key,
        icon: NAV_ICONS[item.key],
        label: t.nav[item.key],
        isActive: item.key === activeKey,
        onClick: () => navigate(item.route),
      })),
    [user, t.nav, activeKey, navigate],
  );

  const handleLogout = useCallback(() => {
    logout();
    navigate(ROUTES.login);
  }, [logout, navigate]);

  // Identity is always derived from the authenticated user object — there
  // is no default/placeholder person anywhere in this shell.
  const header = (
    <DashboardHeader
      lang={lang}
      setLang={setLang}
      userName={resolveUserDisplayName(user)}
      roleLabel={resolveRoleLabel(user, t.roles)}
      initial={resolveUserInitial(user)}
    />
  );

  return (
    <DashboardShell
      isRTL={isRTL}
      compact={location.pathname !== ADMIN_ROUTES.overview}
      navItems={navItems}
      logoutLabel={t.nav.logout}
      logoutIcon={<LogoutIcon />}
      onLogout={handleLogout}
      header={header}
    >
      <Outlet />
    </DashboardShell>
  );
};

export default AdminLayout;
