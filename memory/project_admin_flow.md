---
name: QuickRoute Admin Flow Architecture
description: Admin portal screens, routing, and context - how the admin section is structured
type: project
---

The admin area is a mobile-first, phone-style portal integrated into the main QuickRoute React app.

**Flow:**
Screen02 (login) → Sign In button → Screen05 (Admin Dashboard) → management screens

**Routes:**
- `/screen/05` → Screen05 (Admin Dashboard home, dark gradient header, stats, nav cards)
- `/admin/map` → AdminMapScreen (map upload/edit/delete)
- `/admin/locations` → AdminLocationsScreen (BUILDINGS data management)
- `/admin/rooms` → AdminRoomsScreen (ROOMS data management, building tab selector)
- `/admin/routes` → AdminRoutesScreen (route points management)

**State:** Shared via `src/context/AdminContext.jsx` (AdminProvider wraps entire app in App.jsx).
Data: `buildings` (from BUILDINGS), `rooms` (from ROOMS per building), `routePoints` (dummy), `mapData`.
CRUD: addBuilding/updateBuilding/deleteBuilding, addRoom/updateRoom/deleteRoom, addRoute/updateRoute/deleteRoute, updateMap.

**Design pattern:** All admin screens follow Screen16 layout exactly:
- `.adm-shell` = `max-width: 390px; height: 100vh; overflow: hidden; flex-direction: column`
- `.adm-header` / `.adm-inner-header` = dark gradient (158deg, #0d2244 → #1a3a6b → #2a5298 → #4474be)
- `.adm-content` = `flex:1; overflow-y:auto; padding:18px`
- Language switcher (same as s16-lang-pill) in every screen header
- Back button on inner screens navigates back to Screen05 (or list view within screen)

**Shared CSS:** `src/styles/adminScreens.css` has all admin styles.

**Data source:** Uses real `BUILDINGS` and `ROOMS` from `src/data/hospitalData.js` (same as Screen16/17/18).

**Why:** Mobile-first admin portal that feels like part of the QuickRoute app, not a separate dashboard.
**How to apply:** When adding new admin screens, follow the same `.adm-shell + .adm-inner-header + .adm-content` pattern and import from AdminContext for data.
