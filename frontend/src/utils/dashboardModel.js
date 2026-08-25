// Dashboard redesign — pure, React-free derivation of everything the
// admin Overview renders, so the numbers on screen can be unit-tested
// without a browser and can never be "decorative".
//
// Hard rules enforced here:
//   * every value is derived from data the backend actually returned
//     (Building.campus, Building.category, MapGroup.floor_count/floors);
//   * nothing is ever synthesized, guessed from a name, or defaulted to a
//     placeholder institution;
//   * a building/map group/floor the caller filtered out for scope
//     reasons is simply absent — it is never counted.
//
// "Site" is Building.campus. It is a real persisted field (see
// backend/models/building_model.py) and is the only grouping level above
// Building that exists in the current data model — QuickRoute stays fully
// generic (campus, hospital, mall, office: whatever the admin typed).

import { groupBuildingsByCampus } from './dashboardHierarchy.js';

// buildings: the AdminContext view-model shape ({ id, nameEn, name,
// campus, rawCategory, isActive, ... }).
export function buildSites(buildings, unassignedLabel) {
  const grouped = groupBuildingsByCampus(buildings, unassignedLabel);

  return Array.from(grouped.entries()).map(([name, siteBuildings]) => ({
    key: name,
    name,
    isUnassigned: name === unassignedLabel,
    buildings: siteBuildings,
    isActive: siteBuildings.some((b) => b.isActive !== false),
  }));
}

// groupsByBuildingId: { [buildingId]: MapGroup[] }, already narrowed to
// what this user may access. Each group is the mapGroupsApi view-model
// ({ id, buildingId, floorCount, floors: [...] }).
export function countGroupsAndFloors(buildingIds, groupsByBuildingId) {
  let mapGroupCount = 0;
  let floorCount = 0;

  for (const buildingId of buildingIds) {
    const groups = groupsByBuildingId?.[buildingId] || [];
    mapGroupCount += groups.length;
    for (const group of groups) {
      floorCount += Array.isArray(group.floors)
        ? group.floors.length
        : Number(group.floorCount || 0);
    }
  }

  return { mapGroupCount, floorCount };
}

export function summarizeSite(site, groupsByBuildingId) {
  const buildingIds = (site.buildings || []).map((b) => b.id);
  const { mapGroupCount, floorCount } = countGroupsAndFloors(buildingIds, groupsByBuildingId);

  return {
    buildingCount: buildingIds.length,
    mapGroupCount,
    floorCount,
  };
}

export function summarizeBuilding(building, groupsByBuildingId) {
  const { mapGroupCount, floorCount } = countGroupsAndFloors(
    [building.id],
    groupsByBuildingId,
  );
  return { mapGroupCount, floorCount };
}

// The four Overview metrics. `null` for a metric whose source data has
// not loaded yet is the caller's business — this returns real counts of
// whatever it was handed.
export function computeOverviewStats(sites, buildings, groupsByBuildingId) {
  const { mapGroupCount, floorCount } = countGroupsAndFloors(
    (buildings || []).map((b) => b.id),
    groupsByBuildingId,
  );

  return {
    siteCount: (sites || []).length,
    buildingCount: (buildings || []).length,
    mapGroupCount,
    floorCount,
  };
}

// ── Categories ─────────────────────────────────────────────────────────
// Building.category is a REAL persisted field (backend/models/
// building_model.py + BuildingCreate/Update/Response). Tabs are built
// only from values that actually exist on the buildings in front of the
// admin — a category is never inferred from a building's name, and an
// empty category is grouped under the caller-supplied label rather than
// being invented.

export const ALL_CATEGORIES_KEY = '__all__';
export const UNCATEGORIZED_KEY = '__uncategorized__';

export function buildCategoryTabs(buildings, allLabel, uncategorizedLabel) {
  const counts = new Map();
  let uncategorized = 0;

  for (const building of buildings || []) {
    const category = (building.rawCategory || '').trim();
    if (!category) {
      uncategorized += 1;
      continue;
    }
    counts.set(category, (counts.get(category) || 0) + 1);
  }

  const tabs = [
    { key: ALL_CATEGORIES_KEY, label: allLabel, count: (buildings || []).length },
  ];

  for (const [category, count] of Array.from(counts.entries()).sort((a, b) =>
    a[0].localeCompare(b[0]),
  )) {
    tabs.push({ key: category, label: category, count });
  }

  if (uncategorized > 0 && counts.size > 0) {
    tabs.push({ key: UNCATEGORIZED_KEY, label: uncategorizedLabel, count: uncategorized });
  }

  // A single "All" tab carries no information — the caller renders
  // nothing when only one tab comes back.
  return tabs.length > 1 ? tabs : [];
}

export function filterBuildingsByCategory(buildings, categoryKey) {
  if (!categoryKey || categoryKey === ALL_CATEGORIES_KEY) return buildings || [];
  if (categoryKey === UNCATEGORIZED_KEY) {
    return (buildings || []).filter((b) => !(b.rawCategory || '').trim());
  }
  return (buildings || []).filter((b) => (b.rawCategory || '').trim() === categoryKey);
}

// ── Display helpers ────────────────────────────────────────────────────

// A site's secondary line. MapGroup.address is a real persisted field;
// it is only shown when every map group in the site agrees on one
// non-empty address, so an admin never sees one building's address
// presented as if it were the whole site's.
export function resolveSiteAddress(site, groupsByBuildingId) {
  const addresses = new Set();

  for (const building of site.buildings || []) {
    for (const group of groupsByBuildingId?.[building.id] || []) {
      const address = (group.address || '').trim();
      if (address) addresses.add(address);
    }
  }

  return addresses.size === 1 ? Array.from(addresses)[0] : '';
}

// The Site a building belongs to. Building.campus is the ONLY persisted
// site-level field in the current data model, so it is used verbatim when
// it holds a value and replaced by a neutral localized label when it does
// not. A building's own name/code is NEVER promoted to a site name — that
// is what made Site, Building and Map Group all read "MA-01234" — and a
// site is never inferred from any name.
export function resolveSiteName(building, unassignedLabel) {
  const campus = String(building?.campus || '').trim();
  return campus || unassignedLabel;
}

// mapId -> { floor, group, buildingId }. Built from the already-scoped map
// groups, so a lookup can only ever resolve a map this account may access:
// a floor outside scope is simply absent from the index, and every consumer
// treats "absent" as "not available" rather than rendering a disabled row.
export function buildFloorIndex(mapGroups) {
  const index = new Map();
  for (const group of mapGroups || []) {
    for (const floor of group.floors || []) {
      if (!floor?.id) continue;
      index.set(String(floor.id), {
        floor,
        group,
        buildingId: floor.buildingId || group.buildingId || null,
      });
    }
  }
  return index;
}

export function buildingDisplayName(building) {
  if (!building) return '';
  return building.nameEn || building.name || '';
}

export function floorDisplayName(floor, fallbackPrefix) {
  if (!floor) return '';
  if (floor.floorLabel) return floor.floorLabel;
  if (floor.floor_label) return floor.floor_label;
  if (floor.title) return floor.title;
  if (floor.floor !== null && floor.floor !== undefined) {
    return `${fallbackPrefix} ${floor.floor}`;
  }
  return fallbackPrefix;
}
