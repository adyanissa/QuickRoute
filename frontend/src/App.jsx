import React from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { LangProvider } from './context/LangContext';
import { LocationProvider } from './context/LocationContext';

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
import AdminRoomsScreen from './screens/AdminRoomsScreen';
import AdminRoutesScreen from './screens/AdminRoutesScreen';
import { AdminProvider } from './context/AdminContext';

import './styles/global.css';

function App() {
  return (
    <LocationProvider>
    <LangProvider>
    <AdminProvider>
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Navigate to="/screen/01" replace />} />

        <Route path="/screen/01" element={<BarcodeEntryScreen />} />
        <Route path="/screen/02" element={<LoginScreen />} />
        <Route path="/screen/03" element={<RegisterVerificationScreen />} />
        <Route path="/screen/04" element={<AccountCreationScreen />} />
        <Route path="/screen/05" element={<AdminDashboardScreen />} />
        <Route path="/screen/15" element={<WelcomeScreen />} />
        <Route path="/screen/16" element={<BuildingSelectionScreen />} />
        <Route path="/screen/17" element={<DestinationSelectionScreen />} />
        <Route path="/screen/18" element={<IndoorNavigationScreen />} />
        <Route path="/map"       element={<IndoorNavigationScreen />} />

        <Route path="/admin/map"       element={<AdminMapScreen />} />
        <Route path="/admin/locations" element={<AdminLocationsScreen />} />
        <Route path="/admin/rooms"     element={<AdminRoomsScreen />} />
        <Route path="/admin/routes"    element={<AdminRoutesScreen />} />

        {/* Fallback */}
        <Route path="*" element={<Navigate to="/screen/01" replace />} />
      </Routes>
    </BrowserRouter>
    </AdminProvider>
    </LangProvider>
    </LocationProvider>
  );
}

export default App;
