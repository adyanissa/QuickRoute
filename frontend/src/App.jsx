import React from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
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
import { AdminProvider } from './context/AdminContext';

import './styles/global.css';

function App() {
  return (
    <LocationProvider>
    <LangProvider>
    <AuthProvider>
    <AdminProvider>
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Navigate to="/screen/01" replace />} />

        {/* ── Public / end-user flow — unchanged ─────────────────────────
            These screens keep their own layout and never render the admin
            shell. A regular_user's navigation experience is exactly what
            it was before the admin redesign. */}
        <Route path="/screen/01" element={<BarcodeEntryScreen />} />
        <Route path="/screen/02" element={<LoginScreen />} />
        <Route path="/screen/03" element={<RegisterVerificationScreen />} />
        <Route path="/screen/04" element={<AccountCreationScreen />} />
        <Route path="/screen/15" element={<WelcomeScreen />} />
        <Route path="/screen/16" element={<BuildingSelectionScreen />} />
        <Route path="/screen/17" element={<DestinationSelectionScreen />} />
        <Route path="/screen/18" element={<IndoorNavigationScreen />} />
        <Route path="/map"       element={<IndoorNavigationScreen />} />

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
          <Route path="/screen/05" element={<AdminDashboardScreen />} />

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

        {/* Fallback */}
        <Route path="*" element={<Navigate to="/screen/01" replace />} />
      </Routes>
    </BrowserRouter>
    </AdminProvider>
    </AuthProvider>
    </LangProvider>
    </LocationProvider>
  );
}

export default App;
