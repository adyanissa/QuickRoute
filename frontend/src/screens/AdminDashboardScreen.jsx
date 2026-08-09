import { useAuth } from '../context/AuthContext';
import SuperAdminDashboard from './dashboards/SuperAdminDashboard';
import GlobalManagerDashboard from './dashboards/GlobalManagerDashboard';
import BuildingManagerDashboard from './dashboards/BuildingManagerDashboard';

// RBAC/dashboard cleanup task (frontend completion), Section 3/6 — this
// screen used to BE the single shared dashboard every admin-tier role
// saw (identical layout, only the Invitation Codes card conditionally
// shown/hidden). It is now a thin role dispatcher: three genuinely
// different components, each with its own data scope, its own controls,
// and its own translations — never a single component branching
// internally on role, which is what made the old dashboard show
// unscoped system-wide totals to every role regardless of what they
// were actually allowed to see.
//
// Still mounted at the same route (/screen/05, wrapped in RequireRole in
// App.jsx) so login redirection (utils/roleRouting.js) and every existing
// "Back" button that navigates('/screen/05') keep working unchanged.
const AdminDashboardScreen = () => {
  const { user } = useAuth();

  if (user?.role === 'super_admin') {
    return <SuperAdminDashboard />;
  }

  if (user?.role === 'global_manager') {
    return <GlobalManagerDashboard />;
  }

  if (user?.role === 'building_manager') {
    return <BuildingManagerDashboard />;
  }

  // RequireRole already blocks any non-admin role from reaching this
  // route at all, so this is unreachable in practice — kept only as a
  // defensive fallback rather than rendering nothing.
  return <SuperAdminDashboard />;
};

export default AdminDashboardScreen;
