import { Navigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';

// Stricter than RequireRole: only super_admin/global_manager may pass.
// Used for the Invitation Codes management screen specifically —
// building_manager is an admin-tier role (so RequireRole alone would let
// it through) but must NOT reach invitation-code administration by
// default, matching the same rule the backend enforces on every
// /api/invitation-codes write endpoint (require_global_admin).
//
// - Not logged in at all                -> send to the login screen.
// - Logged in but not super_admin/global_manager -> send to the Admin
//   Dashboard (a building_manager still has a real admin home to land
//   on, unlike a regular_user who has none).
// - Logged in as super_admin/global_manager -> render the protected screen.
const GLOBAL_ADMIN_ROLES = ['super_admin', 'global_manager'];

const RequireGlobalAdmin = ({ children }) => {
  const { isAuthenticated, isAdmin, user } = useAuth();

  if (!isAuthenticated) {
    return <Navigate to="/screen/02" replace />;
  }

  if (!GLOBAL_ADMIN_ROLES.includes(user?.role)) {
    // A building_manager still has a real admin home to land on; anyone
    // else (shouldn't normally reach an /admin/* route at all) goes to
    // the regular end-user flow, matching RequireRole's own fallback.
    return <Navigate to={isAdmin ? '/screen/05' : '/screen/15'} replace />;
  }

  return children;
};

export default RequireGlobalAdmin;
