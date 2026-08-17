import { useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { useLang } from '../../context/LangContext';
import { useAdmin } from '../../context/AdminContext';
import { useAuth } from '../../context/AuthContext';
import { canCreateBuildings, canOpenMapWorkspace } from '../../utils/dashboardPermissions';
import { ADMIN_ROUTES, buildingRoute } from '../../utils/adminNavigation';
import { resolveUserDisplayName } from '../../utils/adminIdentity';
import {
  buildSites,
  computeOverviewStats,
  summarizeSite,
  summarizeBuilding,
  resolveSiteAddress,
  buildingDisplayName,
} from '../../utils/dashboardModel';
import {
  DashboardStatCard,
  SectionHead,
  StatePanel,
} from '../../components/dashboard/DashboardCards';
import { MapIcon, LocationIcon, ChevronIcon } from '../../components/dashboard/DashboardPrimitives';
import {
  BuildingIcon,
  SiteIcon,
  LayersIcon,
  FloorsIcon,
  PlusIcon,
} from '../../components/dashboard/DashboardIcons';
import dashboardUi from './dashboardUi';

// Overview — the root of the admin shell.
//
// Refinement pass: the hierarchy used to continue Overview -> Site page ->
// Building page -> Map Group page -> Floors page, which produced a chain of
// near-identical single-row screens. Overview now lists each Site with its
// buildings INLINE, so a building is one click away and the Site level
// never needs a page of its own. Everything below a building lives in the
// Building Workspace.
//
// Every number and name on this screen comes from data the backend already
// narrowed to this account (GET /api/locations/buildings and the admin-only,
// scope-narrowed GET /api/map-groups). There is no system-wide total
// anywhere on this page: a manager scoped to one building sees 1 site, 1
// building and only their own groups/floors, and never learns that other
// institutions exist.

const STAT_TINTS = {
  sites: { bg: '#e8effc', fg: '#2a5298' },
  buildings: { bg: '#e6f4ec', fg: '#2c7a4b' },
  mapGroups: { bg: '#efeafc', fg: '#5b46b5' },
  floors: { bg: '#fdf0e3', fg: '#c06030' },
};

const AdminOverviewDashboard = () => {
  const { lang } = useLang();
  const navigate = useNavigate();
  const { user } = useAuth();
  const { buildings, buildingsLoading, mapGroupsByBuildingId, mapGroupsLoading } = useAdmin();

  const t = dashboardUi[lang] || dashboardUi.en;
  const isRTL = t.dir === 'rtl';

  const sites = useMemo(
    () => buildSites(buildings, t.labels.unassignedSite),
    [buildings, t.labels.unassignedSite],
  );

  const stats = useMemo(
    () => computeOverviewStats(sites, buildings, mapGroupsByBuildingId),
    [sites, buildings, mapGroupsByBuildingId],
  );

  const userName = resolveUserDisplayName(user);

  return (
    <>
      <div className="qrd-intro">
        <h1 className="qrd-intro-title">{t.welcome(userName)}</h1>
        <p className="qrd-intro-sub">{t.welcomeSub}</p>
      </div>

      <div className="qrd-stats">
        <DashboardStatCard
          icon={<SiteIcon />}
          tint={STAT_TINTS.sites}
          value={buildingsLoading ? null : stats.siteCount}
          label={t.stats.sites}
          hint={t.stats.sitesHint}
        />
        <DashboardStatCard
          icon={<BuildingIcon />}
          tint={STAT_TINTS.buildings}
          value={buildingsLoading ? null : stats.buildingCount}
          label={t.stats.buildings}
          hint={t.stats.buildingsHint}
        />
        <DashboardStatCard
          icon={<LayersIcon />}
          tint={STAT_TINTS.mapGroups}
          value={mapGroupsLoading ? null : stats.mapGroupCount}
          label={t.stats.mapGroups}
          hint={t.stats.mapGroupsHint}
        />
        <DashboardStatCard
          icon={<FloorsIcon />}
          tint={STAT_TINTS.floors}
          value={mapGroupsLoading ? null : stats.floorCount}
          label={t.stats.floors}
          hint={t.stats.floorsHint}
        />
      </div>

      <section className="qrd-section">
        <SectionHead
          title={t.sitesTitle}
          subtitle={t.sitesSub}
          action={
            canCreateBuildings(user) ? (
              <button
                type="button"
                className="qrd-btn"
                onClick={() => navigate(ADMIN_ROUTES.sites)}
              >
                <PlusIcon />
                {t.actions.manageBuildings}
              </button>
            ) : null
          }
        />

        {buildingsLoading ? (
          <StatePanel title={t.states.loading} />
        ) : sites.length === 0 ? (
          <StatePanel
            icon={<LocationIcon />}
            title={canCreateBuildings(user) ? t.states.noSites : t.states.noScope}
            hint={canCreateBuildings(user) ? t.states.noSitesHint : t.states.noScopeHint}
            action={
              canOpenMapWorkspace(user) ? (
                <button
                  type="button"
                  className="qrd-btn is-ghost"
                  onClick={() => navigate(ADMIN_ROUTES.mapManagement)}
                >
                  <MapIcon />
                  {t.actions.openMapManagement}
                </button>
              ) : null
            }
          />
        ) : (
          <div className="qrd-list">
            {sites.map((site) => {
              const summary = summarizeSite(site, mapGroupsByBuildingId);
              const address = resolveSiteAddress(site, mapGroupsByBuildingId);
              return (
                <div className="qrd-group" key={site.key}>
                  <div className="qrd-group-head" style={{ cursor: 'default' }}>
                    <span className="qrd-group-icon" aria-hidden="true">
                      <SiteIcon />
                    </span>
                    <span className="qrd-group-body">
                      <span className="qrd-group-name">{site.name}</span>
                      <span className="qrd-group-meta">
                        {address ? `${address} · ` : ''}
                        {summary.buildingCount} {t.labels.buildings} ·{' '}
                        {mapGroupsLoading ? '…' : summary.mapGroupCount} {t.labels.mapGroups} ·{' '}
                        {mapGroupsLoading ? '…' : summary.floorCount} {t.labels.floors}
                      </span>
                    </span>
                    <span className={`qrd-pill${site.isActive ? '' : ' is-muted'}`}>
                      {site.isActive ? t.labels.active : t.labels.inactive}
                    </span>
                  </div>

                  <div className="qrd-floors">
                    {site.buildings.map((building) => {
                      const buildingSummary = summarizeBuilding(building, mapGroupsByBuildingId);
                      return (
                        <button
                          type="button"
                          className="qrd-floor"
                          key={building.id}
                          onClick={() => navigate(buildingRoute(building.id))}
                        >
                          <span className="qrd-floor-icon" aria-hidden="true">
                            <BuildingIcon size={18} />
                          </span>
                          <span className="qrd-floor-name">
                            {buildingDisplayName(building)}
                          </span>
                          <span className="qrd-group-meta" style={{ marginInlineEnd: 10 }}>
                            {mapGroupsLoading ? '…' : buildingSummary.mapGroupCount}{' '}
                            {t.labels.mapGroups} ·{' '}
                            {mapGroupsLoading ? '…' : buildingSummary.floorCount}{' '}
                            {t.labels.floors}
                          </span>
                          <span className="qrd-floor-chev" aria-hidden="true">
                            <ChevronIcon rtl={isRTL} />
                          </span>
                        </button>
                      );
                    })}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </section>
    </>
  );
};

export default AdminOverviewDashboard;
