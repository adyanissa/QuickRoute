// Dependency-free Node tests for adminNavigation.js.
import assert from 'node:assert/strict';
import {
  ADMIN_ROUTES,
  LEGACY_ROUTE_REDIRECTS,
  buildingRoute,
  floorRoute,
  withMapContext,
  resolveSidebarActiveKey,
  resolveBackTarget,
  readMapId,
} from './adminNavigation.js';

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

test('ids are encoded into routes, never interpolated raw', () => {
  assert.equal(buildingRoute('a b/c'), '/admin/buildings/a%20b%2Fc');
  assert.equal(floorRoute('m 1'), '/admin/maps/m%201');
  assert.equal(withMapContext('/admin/rooms', 'm 1'), '/admin/rooms?mapId=m%201');
  assert.equal(withMapContext('/admin/map?x=1', 'm1'), '/admin/map?x=1&mapId=m1');
  assert.equal(withMapContext('/admin/rooms', ''), '/admin/rooms');
});

test('the legacy Locations route redirects to the canonical Sites page', () => {
  assert.equal(LEGACY_ROUTE_REDIRECTS['/admin/locations'], ADMIN_ROUTES.sites);
});

test('sidebar highlighting follows the section, not just the exact page', () => {
  assert.equal(resolveSidebarActiveKey('/screen/05'), 'overview');
  assert.equal(resolveSidebarActiveKey('/admin/sites'), 'sites');
  assert.equal(resolveSidebarActiveKey('/admin/buildings/b1'), 'sites');
  assert.equal(resolveSidebarActiveKey('/admin/maps/m1'), 'sites');
  assert.equal(resolveSidebarActiveKey('/admin/rooms'), 'sites');
  assert.equal(resolveSidebarActiveKey('/admin/map-analysis'), 'sites');
  assert.equal(resolveSidebarActiveKey('/admin/navigation-cleanup'), 'sites');
  assert.equal(resolveSidebarActiveKey('/admin/map'), 'mapManagement');
  assert.equal(resolveSidebarActiveKey('/admin/invitation-codes'), 'invitations');
  assert.equal(resolveSidebarActiveKey('/screen/15'), null);
});

test('/admin/map-analysis is not mistaken for /admin/map', () => {
  // Ordering matters: analysis/rooms/etc. must resolve before the
  // mapManagement prefix could swallow them.
  assert.equal(resolveSidebarActiveKey('/admin/map-analysis'), 'sites');
  assert.notEqual(resolveSidebarActiveKey('/admin/map-analysis'), 'mapManagement');
});

test('Back is deterministic and always lands inside QuickRoute', () => {
  assert.equal(resolveBackTarget('/screen/05'), null);
  assert.equal(resolveBackTarget('/admin/sites'), '/screen/05');
  assert.equal(resolveBackTarget('/admin/buildings/b1'), '/admin/sites');
  assert.equal(resolveBackTarget('/admin/maps/m1'), '/admin/sites');
  assert.equal(resolveBackTarget('/admin/invitation-codes'), '/screen/05');
});

test('a map-scoped tool goes back to its Floor Workspace, else to Overview', () => {
  assert.equal(resolveBackTarget('/admin/rooms', '?mapId=m1'), '/admin/maps/m1');
  assert.equal(resolveBackTarget('/admin/map-analysis', '?mapId=m1&analysisId=a'), '/admin/maps/m1');
  assert.equal(resolveBackTarget('/admin/navigation-cleanup', '?mapId=m1'), '/admin/maps/m1');
  assert.equal(resolveBackTarget('/admin/map', '?mapId=m1'), '/admin/maps/m1');
  assert.equal(resolveBackTarget('/admin/rooms', ''), '/screen/05');
  assert.equal(resolveBackTarget('/admin/map'), '/screen/05');
});

test('mapId is read and decoded out of a raw query string', () => {
  assert.equal(readMapId('?mapId=m%201'), 'm 1');
  assert.equal(readMapId('?a=1&mapId=m2&b=3'), 'm2');
  assert.equal(readMapId('?mapId='), '');
  assert.equal(readMapId(''), '');
  assert.equal(readMapId(undefined), '');
});

console.log(`\n${passed} passed`);
