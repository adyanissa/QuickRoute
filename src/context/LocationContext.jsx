import { createContext, useContext, useState } from 'react';

const LocationContext = createContext(null);

// Default starting location — main entrance / Davidoff Cancer Center
export const DEFAULT_LOCATION = {
  id: 'entrance',
  name: 'כניסה ראשית',
  nameEn: 'Main Entrance',
};

export const LocationProvider = ({ children }) => {
  const [currentLocation, setCurrentLocation] = useState(DEFAULT_LOCATION);

  return (
    <LocationContext.Provider value={{ currentLocation, setCurrentLocation }}>
      {children}
    </LocationContext.Provider>
  );
};

export const useLocation2 = () => {
  const ctx = useContext(LocationContext);
  if (!ctx) throw new Error('useLocation2 must be used inside LocationProvider');
  return ctx;
};
