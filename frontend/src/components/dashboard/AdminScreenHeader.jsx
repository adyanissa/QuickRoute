// One-line header for every admin screen inside the shell.
//
// A legacy admin screen used to carry ~35 lines of its own chrome — its own
// navy hero header, its own copy of the language pill, its own back button
// wired to a hand-picked route. All of that collapses to:
//
//     <AdminScreenHeader pageKey="mapManagement" />
//
// This component resolves everything else from shared sources: the title and
// description from the active language's dictionary, the Back target from
// utils/adminNavigation (deterministic, never history.back()), and the
// breadcrumb trail from the current route plus — when the screen was opened
// from a specific floor — that floor's real Site/Building/Floor labels.
//
// The floor context is read from the ALREADY-SCOPED map groups in
// AdminContext, so a map this account may not access simply produces no
// extra crumbs rather than leaking a name.

import { useMemo } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { useLang } from '../../context/LangContext';
import { useAdmin } from '../../context/AdminContext';
import {
  ADMIN_ROUTES,
  buildingRoute,
  floorRoute,
  readMapId,
  resolveBackTarget,
} from '../../utils/adminNavigation';
import {
  buildFloorIndex,
  buildingDisplayName,
  floorDisplayName,
} from '../../utils/dashboardModel';
import dashboardUi from '../../screens/dashboards/dashboardUi';
import AdminPageHeader from './AdminPageHeader';

const AdminScreenHeader = ({
  pageKey,
  title,
  description,
  action,
  backTo,
  onBack,
}) => {
  const { lang } = useLang();
  const location = useLocation();
  const navigate = useNavigate();
  const { buildings, mapGroups } = useAdmin();

  const t = dashboardUi[lang] || dashboardUi.en;
  const isRTL = t.dir === 'rtl';
  const page = (t.pages && t.pages[pageKey]) || {};

  const mapId = readMapId(location.search);

  const floorContext = useMemo(() => {
    if (!mapId) return null;
    return buildFloorIndex(mapGroups).get(String(mapId)) || null;
  }, [mapId, mapGroups]);

  const crumbs = useMemo(() => {
    const items = [
      { label: t.nav.overview, onClick: () => navigate(ADMIN_ROUTES.overview) },
    ];

    if (floorContext) {
      items.push({ label: t.nav.sites, onClick: () => navigate(ADMIN_ROUTES.sites) });

      const building = buildings.find((item) => item.id === floorContext.buildingId);
      if (building) {
        items.push({
          label: buildingDisplayName(building),
          onClick: () => navigate(buildingRoute(building.id)),
        });
      }

      items.push({
        label: floorDisplayName(floorContext.floor, t.labels.floorPrefix),
        onClick: () => navigate(floorRoute(mapId)),
      });
    }

    items.push({ label: title || page.title || '' });
    return items;
  }, [t, navigate, floorContext, buildings, mapId, title, page.title]);

  const resolvedBack = backTo || resolveBackTarget(location.pathname, location.search);

  return (
    <AdminPageHeader
      backTo={onBack ? undefined : resolvedBack}
      onBack={onBack}
      backLabel={t.back}
      crumbs={crumbs}
      title={title || page.title || ''}
      description={description === undefined ? page.desc : description}
      action={action}
      isRTL={isRTL}
    />
  );
};

export default AdminScreenHeader;
