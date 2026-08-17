import { useMemo } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useLang } from '../../context/LangContext';
import { useAdmin } from '../../context/AdminContext';
import { useAuth } from '../../context/AuthContext';
import { buildMapContextTools } from '../../utils/dashboardPermissions';
import { ADMIN_ROUTES, buildingRoute } from '../../utils/adminNavigation';
import {
  buildFloorIndex,
  buildingDisplayName,
  floorDisplayName,
  resolveSiteName,
} from '../../utils/dashboardModel';
import AdminPageHeader from '../../components/dashboard/AdminPageHeader';
import { SectionHead, StatePanel, ToolCard } from '../../components/dashboard/DashboardCards';
import {
  MapIcon,
  RoomIcon,
  RouteIcon,
  CodeIcon,
} from '../../components/dashboard/DashboardPrimitives';
import { SparkIcon, AlertIcon } from '../../components/dashboard/DashboardIcons';
import dashboardUi from '../dashboards/dashboardUi';

// Floor (Map) Workspace — the ONE place the map-scoped tools live.
//
// Reaching this page means a specific map has been chosen, so the admin can
// never wonder which map an action will modify: the context strip above the
// tools always spells out Site / Building / Map Group / Floor, and every
// tool link carries this map's id.
//
// The floor index is built from the already-scoped map groups, so a map
// outside this account's scope is simply not in it and this route renders
// the same neutral "not available" state a deleted map would — pasting a
// sibling map's id into the URL reveals nothing, and the backend would
// reject the request anyway.
//
// Destructive tools are not tool cards. They live in a single Danger Zone
// panel that is the LAST section of this page, so an admin only meets a
// destructive action after the whole normal workflow — never beside Rooms
// or Route Points. The panel itself only NAVIGATES to the existing
// Navigation Data Cleanup screen; nothing is deleted or reset from here,
// so every confirmation step, reset behaviour and backend authorization on
// that screen is untouched.
//
// Which destructive tools exist at all is still decided by
// buildMapContextTools(), which mirrors the backend's permissions
// (Navigation Data Cleanup is super_admin-only, per require_super_admin).
// An unauthorized role gets an empty list and therefore NO panel at all —
// never a disabled or locked one.

const TOOL_ICONS = {
  workspace: <MapIcon />,
  rooms: <RoomIcon />,
  routes: <RouteIcon />,
  locationCodes: <CodeIcon />,
  analysis: <SparkIcon />,
  // No entry for `cleanup`: a destructive tool is never rendered as an
  // ordinary tool card — it belongs to the Danger Zone panel below.
};

const FloorWorkspaceScreen = () => {
  const { mapId } = useParams();
  const navigate = useNavigate();
  const { lang } = useLang();
  const { user } = useAuth();
  const { buildings, buildingsLoading, mapGroups, mapGroupsLoading } = useAdmin();

  const t = dashboardUi[lang] || dashboardUi.en;
  const isRTL = t.dir === 'rtl';

  const floorIndex = useMemo(() => buildFloorIndex(mapGroups), [mapGroups]);
  const entry = mapId ? floorIndex.get(String(mapId)) : null;

  const building = useMemo(() => {
    if (!entry?.buildingId) return null;
    return buildings.find((item) => item.id === entry.buildingId) || null;
  }, [buildings, entry]);

  const tools = useMemo(() => buildMapContextTools(user, mapId), [user, mapId]);
  const ordinaryTools = tools.filter((tool) => !tool.destructive);
  const destructiveTools = tools.filter((tool) => tool.destructive);

  const isLoading = buildingsLoading || mapGroupsLoading;

  if (!entry) {
    return (
      <>
        <AdminPageHeader
          backTo={ADMIN_ROUTES.sites}
          backLabel={t.back}
          crumbs={[{ label: t.nav.overview }, { label: t.nav.sites }]}
          title={isLoading ? t.states.loading : t.states.notFound}
          isRTL={isRTL}
        />
        {!isLoading && (
          <StatePanel title={t.states.notFound} hint={t.states.notFoundHint} />
        )}
      </>
    );
  }

  const floorLabel = floorDisplayName(entry.floor, t.labels.floorPrefix);
  const buildingLabel = building ? buildingDisplayName(building) : '';
  const siteLabel = resolveSiteName(building, t.labels.unassignedSite);
  const groupLabel = entry.group?.name || entry.group?.code || '';

  const crumbs = [
    { label: t.nav.overview, onClick: () => navigate(ADMIN_ROUTES.overview) },
    { label: t.nav.sites, onClick: () => navigate(ADMIN_ROUTES.sites) },
  ];
  if (building) {
    crumbs.push({
      label: buildingLabel,
      onClick: () => navigate(buildingRoute(building.id)),
    });
  }
  crumbs.push({ label: floorLabel });

  return (
    <>
      <AdminPageHeader
        backTo={building ? buildingRoute(building.id) : ADMIN_ROUTES.sites}
        backLabel={t.back}
        crumbs={crumbs}
        title={floorLabel}
        description={groupLabel}
        isRTL={isRTL}
      />

      <div className="qrd-context">
        <div className="qrd-context-item">
          <span className="qrd-context-lbl">{t.context.site}</span>
          <span className="qrd-context-val">{siteLabel}</span>
        </div>
        {buildingLabel && (
          <div className="qrd-context-item">
            <span className="qrd-context-lbl">{t.context.building}</span>
            <span className="qrd-context-val">{buildingLabel}</span>
          </div>
        )}
        {groupLabel && (
          <div className="qrd-context-item">
            <span className="qrd-context-lbl">{t.context.mapGroup}</span>
            <span className="qrd-context-val">{groupLabel}</span>
          </div>
        )}
        <div className="qrd-context-item">
          <span className="qrd-context-lbl">{t.context.floor}</span>
          <span className="qrd-context-val">{floorLabel}</span>
        </div>
      </div>

      <section className="qrd-section" style={{ marginBlockStart: 0 }}>
        <SectionHead
          title={t.floorWorkspace.toolsTitle}
          subtitle={t.floorWorkspace.toolsSub}
        />

        {ordinaryTools.length === 0 ? (
          <StatePanel icon={<MapIcon />} title={t.states.forbidden} />
        ) : (
          <div className="qrd-tools">
            {ordinaryTools.map((tool) => (
              <ToolCard
                key={tool.key}
                icon={TOOL_ICONS[tool.key]}
                title={t.tools[tool.key].title}
                description={t.tools[tool.key].desc}
                onClick={() => navigate(tool.route)}
              />
            ))}
          </div>
        )}

      </section>

      {/* FINAL section of the Floor Workspace — after every ordinary tool. */}
      {destructiveTools.length > 0 && (
        <section className="qrd-danger" aria-labelledby="qrd-danger-label">
          <div className="qrd-danger-label" id="qrd-danger-label">
            <AlertIcon />
            {t.floorWorkspace.dangerTitle}
          </div>

          {destructiveTools.map((tool) => (
            <div className="qrd-danger-row" key={tool.key}>
              <div className="qrd-danger-text">
                <div className="qrd-danger-name">{t.tools[tool.key].title}</div>
                <p className="qrd-danger-copy">{t.floorWorkspace.dangerDesc}</p>
              </div>
              <button
                type="button"
                className="qrd-danger-btn"
                onClick={() => navigate(tool.route)}
              >
                {t.floorWorkspace.dangerAction}
              </button>
            </div>
          ))}
        </section>
      )}
    </>
  );
};

export default FloorWorkspaceScreen;
