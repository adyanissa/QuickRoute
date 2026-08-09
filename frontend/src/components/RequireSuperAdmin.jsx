import { Navigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';

// Stricter than RequireGlobalAdmin: only super_admin may pass. Used for the
// multi-Map navigation-data cleanup screen (navigation-data-problem task,
// Part 4), which can Full-Reset every RoutePoint/RouteEdge across several
// Maps at once — matching the backend's require_super_admin gate on every
// /api/navigation-cleanup/* write endpoint exactly (this component is a UI
// convenience only; the backend dependency is the real security boundary).
//
// - Not logged in at all      -> send to the login screen.
// - Logged in but not super_admin -> send to the Admin Dashboard (or the
//   regular end-user flow for a non-admin role), matching RequireGlobalAdmin's
//   own fallback behavior.
// - Logged in as super_admin  -> render the protected screen.
const RequireSuperAdmin = ({ children }) => {
  const { isAuthenticated, isAdmin, user } = useAuth();

  if (!isAuthenticated) {
    return <Navigate to="/screen/02" replace />;
  }

  if (user?.role !== 'super_admin') {
    return <Navigate to={isAdmin ? '/screen/05' : '/screen/15'} replace />;
  }

  return children;
};

export default RequireSuperAdmin;
