import { Navigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { ROUTES } from '../config/routes';

// Route guard used around admin screens.
//
// - Not logged in at all               -> send to the login screen.
// - Logged in but role isn't an admin role -> send to the end-user home
//   screen (regular users must never see admin pages, even by typing the
//   URL directly).
// - Logged in with an admin role        -> render the protected screen.
//
// Auth state is read from AuthContext, which itself is backed by
// localStorage, so a browser refresh keeps the user logged in exactly like
// before this guard existed.
const RequireRole = ({ children }) => {
  const { isAuthenticated, isAdmin } = useAuth();

  if (!isAuthenticated) {
    return <Navigate to={ROUTES.login} replace />;
  }

  if (!isAdmin) {
    return <Navigate to={ROUTES.welcome} replace />;
  }

  return children;
};

export default RequireRole;
