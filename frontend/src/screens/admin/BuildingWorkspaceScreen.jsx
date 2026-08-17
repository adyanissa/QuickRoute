import { useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useLang } from '../../context/LangContext';
import { useAdmin } from '../../context/AdminContext';
import { useAuth } from '../../context/AuthContext';
import { canOpenMapWorkspace } from '../../utils/dashboardPermissions';
import { ADMIN_ROUTES, floorRoute } from '../../utils/adminNavigation';
import {
  buildingDisplayName,
  floorDisplayName,
  resolveSiteName,
  summarizeBuilding,
} from '../../utils/dashboardModel';
import AdminPageHeader from '../../components/dashboard/AdminPageHeader';
import { SectionHead, StatePanel } from '../../components/dashboard/DashboardCards';
import { MapIcon, ChevronIcon } from '../../components/dashboard/DashboardPrimitives';
import { LayersIcon } from '../../components/dashboard/DashboardIcons';
import dashboardUi from '../dashboards/dashboardUi';

// Building Workspace — the page that replaced THREE separate screens.
//
// Before this pass the admin walked Site page -> Building page -> Map Group
// page -> Floors page, each of which rendered a single row and no unique
// functionality (that is the "MA-01234 -> MA-01234 -> MA-01234 -> Floors"
// chain). The backend hierarchy is unchanged; only the frontend collapsed.
// One page now shows the building's identity, its real Site and category,
// and every authorized map group with its floors listed inline. Selecting a
// floor goes straight to that floor's workspace.
//
// The building and its groups/floors come from data the backend already
// scoped to this account, so a building outside scope simply is not in the
// list and this page renders the neutral "not available" state for it —
// the same state a deleted building produces, so a scoped manager cannot
// use this route to discover that another institution's building exists.

const BuildingWorkspaceScreen = () => {
  const { buildingId } = useParams();
  const navigate = useNavigate();
  const { lang } = useLang();
  const { user } = useAuth();
  const { buildings, buildingsLoading, mapGroupsByBuildingId, mapGroupsLoading } = useAdmin();

  const t = dashboardUi[lang] || dashboardUi.en;
  const isRTL = t.dir === 'rtl';

  const building = useMemo(
    () => buildings.find((item) => item.id === buildingId) || null,
    [buildings, buildingId],
  );

  const groups = useMemo(
    () => mapGroupsByBuildingId[buildingId] || [],
    [mapGroupsByBuildingId, buildingId],
  );

  // Every group starts expanded: with the usual one-or-two groups per
  // building, collapsing by default would just reintroduce an extra click.
  const [collapsedIds, setCollapsedIds] = useState(() => new Set());

  const toggleGroup = (groupId) => {
    setCollapsedIds((previous) => {
      const next = new Set(previous);
      if (next.has(groupId)) next.delete(groupId);
      else next.add(groupId);
      return next;
    });
  };

  const isLoading = buildingsLoading || mapGroupsLoading;

  if (!building) {
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

  const siteName = resolveSiteName(building, t.labels.unassignedSite);
  const summary = summarizeBuilding(building, mapGroupsByBuildingId);
  const category = (building.rawCategory || '').trim();

  return (
    <>
      <AdminPageHeader
        backTo={ADMIN_ROUTES.sites}
        backLabel={t.back}
        crumbs={[
          { label: t.nav.overview, onClick: () => navigate(ADMIN_ROUTES.overview) },
          { label: t.nav.sites, onClick: () => navigate(ADMIN_ROUTES.sites) },
          { label: buildingDisplayName(building) },
        ]}
        title={buildingDisplayName(building)}
        description={building.subtitle || ''}
        isRTL={isRTL}
      />

      {/* Real hierarchy values only: Site is Building.campus, Category is
          Building.category. Neither is ever derived from a name or code. */}
      <div className="qrd-context">
        <div className="qrd-context-item">
          <span className="qrd-context-lbl">{t.context.site}</span>
          <span className="qrd-context-val">{siteName}</span>
        </div>
        <div className="qrd-context-item">
          <span className="qrd-context-lbl">{t.context.building}</span>
          <span className="qrd-context-val">{buildingDisplayName(building)}</span>
        </div>
        {category && (
          <div className="qrd-context-item">
            <span className="qrd-context-lbl">{t.context.category}</span>
            <span className="qrd-context-val">{category}</span>
          </div>
        )}
        <div className="qrd-context-item">
          <span className="qrd-context-lbl">{t.labels.mapGroups}</span>
          <span className="qrd-context-val">
            {mapGroupsLoading ? '—' : summary.mapGroupCount}
          </span>
        </div>
        <div className="qrd-context-item">
          <span className="qrd-context-lbl">{t.labels.floors}</span>
          <span className="qrd-context-val">
            {mapGroupsLoading ? '—' : summary.floorCount}
          </span>
        </div>
      </div>

      <section className="qrd-section" style={{ marginBlockStart: 0 }}>
        <SectionHead
          title={t.buildingWorkspace.groups}
          subtitle={t.buildingWorkspace.groupsSub}
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

        {mapGroupsLoading ? (
          <StatePanel title={t.states.loading} />
        ) : groups.length === 0 ? (
          <StatePanel
            icon={<LayersIcon />}
            title={t.states.noMapGroups}
            hint={canOpenMapWorkspace(user) ? t.states.noMapGroupsHint : undefined}
            action={
              canOpenMapWorkspace(user) ? (
                <button
                  type="button"
                  className="qrd-btn"
                  onClick={() => navigate(ADMIN_ROUTES.mapManagement)}
                >
                  <MapIcon />
                  {t.actions.uploadMap}
                </button>
              ) : null
            }
          />
        ) : (
          groups.map((group) => {
            const floors = group.floors || [];
            const isOpen = !collapsedIds.has(group.id);
            return (
              <div className="qrd-group" key={group.id}>
                <button
                  type="button"
                  className="qrd-group-head"
                  onClick={() => toggleGroup(group.id)}
                  aria-expanded={isOpen}
                >
                  <span className="qrd-group-icon" aria-hidden="true">
                    <LayersIcon size={22} />
                  </span>
                  <span className="qrd-group-body">
                    <span className="qrd-group-name">{group.name || group.code}</span>
                    <span className="qrd-group-meta">
                      {group.code ? `${group.code} · ` : ''}
                      {t.labels.floorCount(floors.length)}
                      {group.address ? ` · ${group.address}` : ''}
                    </span>
                  </span>
                  <span
                    className={`qrd-group-toggle${isOpen ? ' is-open' : ''}`}
                    aria-hidden="true"
                  >
                    <ChevronIcon rtl={isRTL} />
                  </span>
                </button>

                {isOpen && (
                  <div className="qrd-floors">
                    {floors.length === 0 ? (
                      <div className="qrd-group-meta" style={{ padding: '10px 12px' }}>
                        {t.states.noFloors}
                      </div>
                    ) : (
                      floors.map((floor) => (
                        <button
                          type="button"
                          className="qrd-floor"
                          key={floor.id}
                          onClick={() => navigate(floorRoute(floor.id))}
                        >
                          <span className="qrd-floor-icon" aria-hidden="true">
                            <MapIcon />
                          </span>
                          <span className="qrd-floor-name">
                            {floorDisplayName(floor, t.labels.floorPrefix)}
                          </span>
                          <span className="qrd-floor-chev" aria-hidden="true">
                            <ChevronIcon rtl={isRTL} />
                          </span>
                        </button>
                      ))
                    )}
                  </div>
                )}
              </div>
            );
          })
        )}
      </section>
    </>
  );
};

export default BuildingWorkspaceScreen;
