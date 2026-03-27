import React from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { LangProvider } from './context/LangContext';
import { LocationProvider } from './context/LocationContext';

// Import all 30 screens
import Screen01 from './screens/Screen01';
import Screen02 from './screens/Screen02';
import Screen03 from './screens/Screen03';
import Screen04 from './screens/Screen04';
import Screen05 from './screens/Screen05';
import Screen06 from './screens/Screen06';
import Screen07 from './screens/Screen07';
import Screen08 from './screens/Screen08';
import Screen09 from './screens/Screen09';
import Screen10 from './screens/Screen10';
import Screen11 from './screens/Screen11';
import Screen12 from './screens/Screen12';
import Screen13 from './screens/Screen13';
import Screen14 from './screens/Screen14';
import Screen15 from './screens/Screen15';
import Screen16 from './screens/Screen16';
import Screen17 from './screens/Screen17';
import Screen18 from './screens/Screen18';
import Screen19 from './screens/Screen19';
import Screen20 from './screens/Screen20';
import Screen21 from './screens/Screen21';
import Screen22 from './screens/Screen22';
import Screen23 from './screens/Screen23';
import Screen24 from './screens/Screen24';
import Screen25 from './screens/Screen25';
import Screen26 from './screens/Screen26';
import Screen27 from './screens/Screen27';
import Screen28 from './screens/Screen28';
import Screen29 from './screens/Screen29';
import Screen30 from './screens/Screen30';

import './styles/global.css';

function App() {
  return (
    <LocationProvider>
    <LangProvider>
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Navigate to="/screen/01" replace />} />

        <Route path="/screen/01" element={<Screen01 />} />
        <Route path="/screen/02" element={<Screen02 />} />
        <Route path="/screen/03" element={<Screen03 />} />
        <Route path="/screen/04" element={<Screen04 />} />
        <Route path="/screen/05" element={<Screen05 />} />
        <Route path="/screen/06" element={<Screen06 />} />
        <Route path="/screen/07" element={<Screen07 />} />
        <Route path="/screen/08" element={<Screen08 />} />
        <Route path="/screen/09" element={<Screen09 />} />
        <Route path="/screen/10" element={<Screen10 />} />
        <Route path="/screen/11" element={<Screen11 />} />
        <Route path="/screen/12" element={<Screen12 />} />
        <Route path="/screen/13" element={<Screen13 />} />
        <Route path="/screen/14" element={<Screen14 />} />
        <Route path="/screen/15" element={<Screen15 />} />
        <Route path="/screen/16" element={<Screen16 />} />
        <Route path="/screen/17" element={<Screen17 />} />
        <Route path="/screen/18" element={<Screen18 />} />
        <Route path="/map"       element={<Screen18 />} />
        <Route path="/screen/19" element={<Screen19 />} />
        <Route path="/screen/20" element={<Screen20 />} />
        <Route path="/screen/21" element={<Screen21 />} />
        <Route path="/screen/22" element={<Screen22 />} />
        <Route path="/screen/23" element={<Screen23 />} />
        <Route path="/screen/24" element={<Screen24 />} />
        <Route path="/screen/25" element={<Screen25 />} />
        <Route path="/screen/26" element={<Screen26 />} />
        <Route path="/screen/27" element={<Screen27 />} />
        <Route path="/screen/28" element={<Screen28 />} />
        <Route path="/screen/29" element={<Screen29 />} />
        <Route path="/screen/30" element={<Screen30 />} />

        {/* Fallback */}
        <Route path="*" element={<Navigate to="/screen/01" replace />} />
      </Routes>
    </BrowserRouter>
    </LangProvider>
    </LocationProvider>
  );
}

export default App;
