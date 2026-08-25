import { createContext, useContext, useCallback, useState } from 'react';

// Single canonical localStorage key for the authenticated user. The old
// LoginScreen used to write both `quickroute_user` and `quickroute_admin` —
// nothing else in the app ever read `quickroute_admin`, so it has been
// dropped in favor of one consistent key.
const STORAGE_KEY = 'quickroute_user';

// Same key api.js reads from to attach the Authorization header to every
// request. Kept as a plain localStorage key (not React state) so non-React
// code (api.js) can read it without needing a context import.
const TOKEN_STORAGE_KEY = 'quickroute_token';

// Roles that are allowed into any /admin/* route or the admin dashboard.
export const ADMIN_ROLES = [
  'super_admin',
  'global_manager',
  'building_manager',
];

function readStoredUser() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

const AuthContext = createContext(null);

export const AuthProvider = ({ children }) => {
  const [user, setUser] = useState(readStoredUser);

  const login = useCallback((userData, accessToken) => {
    setUser(userData);

    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(userData));

      if (accessToken) {
        localStorage.setItem(TOKEN_STORAGE_KEY, accessToken);
      }
    } catch {
      // localStorage may be unavailable (private mode, quota, etc). The
      // in-memory state still lets the current session work.
    }
  }, []);

  const logout = useCallback(() => {
    setUser(null);

    try {
      localStorage.removeItem(STORAGE_KEY);
      localStorage.removeItem(TOKEN_STORAGE_KEY);
    } catch {
      // Ignore storage errors on logout too.
    }
  }, []);

  const isAdmin = Boolean(user && ADMIN_ROLES.includes(user.role));

  return (
    <AuthContext.Provider
      value={{
        user,
        isAuthenticated: Boolean(user),
        isAdmin,
        login,
        logout,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = () => {
  const ctx = useContext(AuthContext);

  if (!ctx) {
    throw new Error('useAuth must be used inside <AuthProvider>');
  }

  return ctx;
};
