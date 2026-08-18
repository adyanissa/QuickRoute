import React from 'react';
import { BrowserRouter, Routes, Route, Navigate, useLocation } from 'react-router-dom';
import { LangProvider } from './context/LangContext';
import { LocationProvider } from './context/LocationContext';
import { AuthProvider } from './context/AuthContext';
import RequireRole from './components/RequireRole';
import RequireGlobalAdmin from './components/RequireGlobalAdmin';
import RequireSuperAdmin from './components/RequireSuperAdmin';

// Import renamed screens
import BarcodeEntryScreen from './screens/BarcodeEntryScreen';
import LoginScreen from './screens/LoginScreen';
import RegisterVerificationScreen from './screens/RegisterVerificationScreen';
import AccountCreationScreen from './screens/AccountCreationScreen';
import AdminDashboardScreen from './screens/AdminDashboardScreen';
import WelcomeScreen from './screens/WelcomeScreen';
import BuildingSelectionScreen from './screens/BuildingSelectionScreen';
import DestinationSelectionScreen from './screens/DestinationSelectionScreen';
import IndoorNavigationScreen from './screens/IndoorNavigationScreen';
import AdminMapScreen from './screens/AdminMapScreen';
import AdminLocationsScreen from './screens/AdminLocationsScreen';
import AdminLocationCodesScreen from './screens/AdminLocationCodesScreen';
import AdminInvitationCodesScreen from './screens/AdminInvitationCodesScreen';
import AdminRoomsScreen from './screens/AdminRoomsScreen';
import AdminRoutesScreen from './screens/AdminRoutesScreen';
import AdminMapAnalysisScreen from './screens/AdminMapAnalysisScreen';
import AdminNavigationCleanupScreen from './screens/AdminNavigationCleanupScreen';
import AdminLayout from './components/dashboard/AdminLayout';
import BuildingWorkspaceScreen from './screens/admin/BuildingWorkspaceScreen';
import FloorWorkspaceScreen from './screens/admin/FloorWorkspaceScreen';
import UsersAccessScreen from './screens/admin/UsersAccessScreen';
import { ADMIN_ROUTES } from './utils/adminNavigation';
import {
  LEGACY_ROUTE_REDIRECTS,
  NOT_FOUND_REDIRECT,
  ROUTES,
} from './config/routes';
import { AdminProvider } from './context/AdminContext';

import './styles/global.css';

// The one redirect component in the app.
//
// `<Navigate to="/start">` with a plain string DROPS the query string and
// hash — which would silently discard the ?locationCode= a scanned QuickRoute
// QR arrives with. Reading them off the current location and passing a Path
// object carries them through:
//
//     /?locationCode=CODE          ->  /start?locationCode=CODE
//     /screen/01?locationCode=CODE ->  /start?locationCode=CODE
//
// `replace` keeps browser Back working: the redirect does not become its own
// history entry, so Back from the destination goes to wherever the user
// really came from rather than bouncing through the redirect again.
//
// This is not a second navigation system — it is the same single redirect the
// root route always had, now also serving the legacy numeric paths.
const PreserveQueryRedirect = ({ to }) => {
  const { search, hash } = useLocation();

  return <Navigate to={{ pathname: to, search, hash }} replace />;
};

function App() {
  return (
    <LocationProvider>
    <LangProvider>
    <AuthProvider>
    <AdminProvider>
    <BrowserRouter>
      <Routes>
        <Route
          path={ROUTES.root}
          element={<PreserveQueryRedirect to={ROUTES.start} />}
        />

        {/* ── Public / end-user flow ─────────────────────────────────────
            Canonical semantic paths. These screens keep their own layout
            and never render the admin shell — a regular_user's navigation
            experience is exactly what it was before, only the URLs changed.

            /screen/18 and /map both rendered IndoorNavigationScreen; they
            are now one route, and both old paths redirect here. */}
        <Route path={ROUTES.start} element={<BarcodeEntryScreen />} />
        <Route path={ROUTES.login} element={<LoginScreen />} />
        <Route path={ROUTES.signup} element={<RegisterVerificationScreen />} />
        <Route path={ROUTES.signupAccount} element={<AccountCreationScreen />} />
        <Route path={ROUTES.welcome} element={<WelcomeScreen />} />
        <Route path={ROUTES.buildings} element={<BuildingSelectionScreen />} />
        <Route path={ROUTES.destinations} element={<DestinationSelectionScreen />} />
        <Route path={ROUTES.navigation} element={<IndoorNavigationScreen />} />

        {/* ── Admin application ─────────────────────────────────────────
            ONE layout route: the guard runs first (so a non-admin never
            renders admin chrome at all), then AdminLayout paints the
            shared shell — white sidebar, branding, language selector and
            the authenticated user's name/role — and every admin page
            below renders into its <Outlet/>. No admin screen paints its
            own page chrome any more.

            Routes that need a STRICTER gate than "any admin" keep their
            own guard inside the layout, exactly as before: Invitation
            Codes stays RequireGlobalAdmin and Navigation Cleanup stays
            RequireSuperAdmin. The layout is presentation; these guards
            and the backend's own authorization remain the boundary. */}
        <Route
          element={
            <RequireRole>
              <AdminLayout />
            </RequireRole>
          }
        >
          <Route path={ADMIN_ROUTES.overview} element={<AdminDashboardScreen />} />

          {/* Canonical Sites & Buildings page (building CRUD + browsing).
              /admin/locations was a second, visually separate interface
              for the same Buildings functionality — it now redirects here
              so old links and bookmarks keep working. */}
          <Route path={ADMIN_ROUTES.sites} element={<AdminLocationsScreen />} />
          <Route
            path="/admin/locations"
            element={<Navigate to={ADMIN_ROUTES.sites} replace />}
          />

          <Route path="/admin/buildings/:buildingId" element={<BuildingWorkspaceScreen />} />
          <Route path="/admin/maps/:mapId" element={<FloorWorkspaceScreen />} />

          <Route path="/admin/map" element={<AdminMapScreen />} />
          <Route path="/admin/location-codes" element={<AdminLocationCodesScreen />} />
          <Route path="/admin/rooms" element={<AdminRoomsScreen />} />
          <Route path="/admin/routes" element={<AdminRoutesScreen />} />
          <Route path="/admin/map-analysis" element={<AdminMapAnalysisScreen />} />

          <Route
            path="/admin/invitation-codes"
            element={
              <RequireGlobalAdmin>
                <AdminInvitationCodesScreen />
              </RequireGlobalAdmin>
            }
          />
          {/* Users & Access — super_admin/global_manager only, the same
              gate the backend applies to /api/admin/users. */}
          <Route
            path={ADMIN_ROUTES.users}
            element={
              <RequireGlobalAdmin>
                <UsersAccessScreen />
              </RequireGlobalAdmin>
            }
          />
          <Route
            path="/admin/navigation-cleanup"
            element={
              <RequireSuperAdmin>
                <AdminNavigationCleanupScreen />
              </RequireSuperAdmin>
            }
          />
        </Route>

        {/* ── Backward compatibility ────────────────────────────────────
            Every old numeric path, plus /map, kept working forever. These
            are declared AFTER the canonical routes and are pure redirects
            — nothing inside the app targets them, so the running app never
            depends on one. They exist for QR labels and bookmarks already
            in the world.

            Each carries ?query and #hash through, which is what keeps a
            printed /screen/01?locationCode=CODE label resolving. */}
        {Object.entries(LEGACY_ROUTE_REDIRECTS).map(([legacyPath, target]) => (
          <Route
            key={legacyPath}
            path={legacyPath}
            element={<PreserveQueryRedirect to={target} />}
          />
        ))}

        {/* Fallback — also preserves the query string and hash, so a
            mistyped or stale deep link carrying ?locationCode= still
            reaches the resolver instead of losing the code. */}
        <Route
          path="*"
          element={<PreserveQueryRedirect to={NOT_FOUND_REDIRECT} />}
        />
      </Routes>
    </BrowserRouter>
    </AdminProvider>
    </AuthProvider>
    </LangProvider>
    </LocationProvider>
  );
}

export default App;
