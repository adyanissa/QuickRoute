import AdminOverviewDashboard from './dashboards/AdminOverviewDashboard';

// Route element for /screen/05 (Overview).
//
// This used to dispatch to three separate per-role dashboard components,
// then became a role-guarded wrapper. Both jobs now live elsewhere: the
// admin shell and its role-aware navigation are AdminLayout's, and the
// "is this user an admin at all" decision is RequireRole's, which wraps the
// whole admin layout route in App.jsx — a regular_user is redirected to the
// end-user flow before any admin component mounts.
//
// Kept as its own module (rather than pointing the route straight at
// AdminOverviewDashboard) so /screen/05 keeps one obvious entry point for
// login redirection (utils/roleRouting.js) and for every existing "back to
// dashboard" link.
const AdminDashboardScreen = () => <AdminOverviewDashboard />;

export default AdminDashboardScreen;
