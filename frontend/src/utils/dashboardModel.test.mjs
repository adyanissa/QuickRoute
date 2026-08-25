// Dashboard redesign — dependency-free Node tests for dashboardModel.js.
// Every assertion here exists to prove the dashboard's numbers come from
// real backend data and are never invented or placeholder values.
import assert from 'node:assert/strict';
import {
  resolveSiteName,
  buildFloorIndex,
  buildSites,
  countGroupsAndFloors,
  summarizeSite,
  summarizeBuilding,
  computeOverviewStats,
  buildCategoryTabs,
  filterBuildingsByCategory,
  resolveSiteAddress,
  floorDisplayName,
  ALL_CATEGORIES_KEY,
  UNCATEGORIZED_KEY,
} from './dashboardModel.js';

let passed = 0;
function test(name, fn) {
  try {
    fn();
    passed += 1;
    console.log(`PASS: ${name}`);
  } catch (err) {
    console.error(`FAIL: ${name}`);
    console.error(err);
    process.exitCode = 1;
  }
}

const UNASSIGNED = 'Unassigned site';

const buildings = [
  { id: 'b1', nameEn: 'Engineering', campus: 'North Campus', rawCategory: 'Academic', isActive: true },
  { id: 'b2', nameEn: 'Admin Tower', campus: 'North Campus', rawCategory: 'Administration', isActive: true },
  { id: 'b3', nameEn: 'Outpatient', campus: 'City Hospital', rawCategory: '', isActive: false },
  { id: 'b4', nameEn: 'Warehouse', campus: '   ', rawCategory: 'Academic', isActive: true },
];

const groupsByBuildingId = {
  b1: [
    { id: 'g1', buildingId: 'b1', floorCount: 3, floors: [{ id: 'm1' }, { id: 'm2' }, { id: 'm3' }], address: '1 Main St' },
    { id: 'g2', buildingId: 'b1', floorCount: 1, floors: [{ id: 'm4' }], address: '1 Main St' },
  ],
  b2: [{ id: 'g3', buildingId: 'b2', floorCount: 2, floors: [{ id: 'm5' }, { id: 'm6' }], address: '1 Main St' }],
  // no floors[] at all -> the backend's own floor_count is used
  b3: [{ id: 'g4', buildingId: 'b3', floorCount: 5, address: '' }],
};

test('sites come from real Building.campus values, blanks bucket under the caller label', () => {
  const sites = buildSites(buildings, UNASSIGNED);
  assert.deepEqual(sites.map((s) => s.name), ['North Campus', 'City Hospital', UNASSIGNED]);
  assert.equal(sites[0].buildings.length, 2);
  assert.equal(sites[2].isUnassigned, true);
  // no institution name is ever synthesized
  assert.equal(sites.some((s) => /Yezreel|Rabin|Meir/.test(s.name)), false);
});

test('a site is Active when any of its buildings is active', () => {
  const sites = buildSites(buildings, UNASSIGNED);
  assert.equal(sites.find((s) => s.name === 'North Campus').isActive, true);
  assert.equal(sites.find((s) => s.name === 'City Hospital').isActive, false);
});

test('map group and floor counts come from loaded groups, floors[] preferred over floor_count', () => {
  assert.deepEqual(countGroupsAndFloors(['b1'], groupsByBuildingId), { mapGroupCount: 2, floorCount: 4 });
  // no floors[] on the group -> the backend's own floor_count is used
  assert.deepEqual(countGroupsAndFloors(['b3'], groupsByBuildingId), { mapGroupCount: 1, floorCount: 5 });
  // a building with nothing loaded contributes zero, never a guess
  assert.deepEqual(countGroupsAndFloors(['b4'], groupsByBuildingId), { mapGroupCount: 0, floorCount: 0 });
});

test('a floors[] emptied by scope filtering counts as zero, never as floor_count', () => {
  // This is the whole point of preferring floors[]: once out-of-scope
  // floors have been filtered out of a group, the group must report what
  // this admin may actually see, not the backend's unfiltered total.
  const filtered = { bx: [{ id: 'g9', buildingId: 'bx', floorCount: 7, floors: [] }] };
  assert.deepEqual(countGroupsAndFloors(['bx'], filtered), { mapGroupCount: 1, floorCount: 0 });
});

test('scoped-out data is simply absent from every count', () => {
  const scoped = { b1: groupsByBuildingId.b1 };
  const sites = buildSites([buildings[0]], UNASSIGNED);
  assert.deepEqual(summarizeSite(sites[0], scoped), { buildingCount: 1, mapGroupCount: 2, floorCount: 4 });
  assert.deepEqual(computeOverviewStats(sites, [buildings[0]], scoped), {
    siteCount: 1,
    buildingCount: 1,
    mapGroupCount: 2,
    floorCount: 4,
  });
});

test('overview stats aggregate exactly what was handed in', () => {
  const sites = buildSites(buildings, UNASSIGNED);
  assert.deepEqual(computeOverviewStats(sites, buildings, groupsByBuildingId), {
    siteCount: 3,
    buildingCount: 4,
    mapGroupCount: 4,
    floorCount: 11,
  });
});

test('summarizeBuilding is per-building, never per-site', () => {
  assert.deepEqual(summarizeBuilding({ id: 'b2' }, groupsByBuildingId), { mapGroupCount: 1, floorCount: 2 });
});

test('category tabs are built only from persisted Building.category values', () => {
  const tabs = buildCategoryTabs(buildings, 'All', 'Uncategorized');
  assert.deepEqual(tabs.map((t) => t.key), [ALL_CATEGORIES_KEY, 'Academic', 'Administration', UNCATEGORIZED_KEY]);
  assert.equal(tabs[0].count, 4);
  assert.equal(tabs[1].count, 2);
  assert.equal(tabs[3].count, 1);
});

test('no tabs are rendered when no building carries a category', () => {
  assert.deepEqual(buildCategoryTabs([{ id: 'x', rawCategory: '' }], 'All', 'Uncategorized'), []);
  assert.deepEqual(buildCategoryTabs([], 'All', 'Uncategorized'), []);
});

test('category filtering never classifies by building name', () => {
  assert.equal(filterBuildingsByCategory(buildings, ALL_CATEGORIES_KEY).length, 4);
  assert.deepEqual(filterBuildingsByCategory(buildings, 'Academic').map((b) => b.id), ['b1', 'b4']);
  assert.deepEqual(filterBuildingsByCategory(buildings, UNCATEGORIZED_KEY).map((b) => b.id), ['b3']);
  // "Engineering"/"Warehouse" are not treated as category hints
  assert.deepEqual(filterBuildingsByCategory(buildings, 'Engineering'), []);
});

test('a site address is shown only when every loaded map group agrees on one', () => {
  const sites = buildSites(buildings, UNASSIGNED);
  assert.equal(resolveSiteAddress(sites[0], groupsByBuildingId), '1 Main St');
  const mixed = { buildings: [{ id: 'b1' }, { id: 'bx' }] };
  const mixedGroups = {
    b1: [{ address: '1 Main St' }],
    bx: [{ address: '9 Other Rd' }],
  };
  assert.equal(resolveSiteAddress(mixed, mixedGroups), '');
  assert.equal(resolveSiteAddress({ buildings: [{ id: 'b3' }] }, groupsByBuildingId), '');
});

test('floor labels prefer the real label, then the title, and keep floor 0', () => {
  assert.equal(floorDisplayName({ floorLabel: 'Parking B1', floor: -1 }, 'Floor'), 'Parking B1');
  assert.equal(floorDisplayName({ title: 'Ground plan', floor: 0 }, 'Floor'), 'Ground plan');
  assert.equal(floorDisplayName({ floor: 0 }, 'Floor'), 'Floor 0');
  assert.equal(floorDisplayName({}, 'Floor'), 'Floor');
});

test('a site name is the persisted campus, never the building name or code', () => {
  assert.equal(resolveSiteName({ campus: 'Meir Hospital', nameEn: 'Outpatient' }, 'Unspecified site'), 'Meir Hospital');
  // no campus -> neutral label, NOT the building's own name/code
  assert.equal(resolveSiteName({ campus: '', nameEn: 'MA-01234' }, 'Unspecified site'), 'Unspecified site');
  assert.equal(resolveSiteName({ campus: '   ', tag: 'MA-01234' }, 'Unspecified site'), 'Unspecified site');
  assert.equal(resolveSiteName(null, 'Unspecified site'), 'Unspecified site');
});

test('the floor index only ever contains floors the caller may access', () => {
  const scopedGroups = [
    { id: 'g1', buildingId: 'b1', floors: [{ id: 'm2', floor: 2 }] }, // siblings already filtered out
  ];
  const index = buildFloorIndex(scopedGroups);
  assert.equal(index.size, 1);
  assert.equal(index.get('m2').group.id, 'g1');
  assert.equal(index.get('m2').buildingId, 'b1');
  // a sibling floor that was filtered out is absent, not "present but disabled"
  assert.equal(index.has('m1'), false);
  assert.equal(index.has('m3'), false);
  assert.equal(buildFloorIndex([]).size, 0);
  assert.equal(buildFloorIndex(undefined).size, 0);
});

console.log(`\n${passed} passed`);
