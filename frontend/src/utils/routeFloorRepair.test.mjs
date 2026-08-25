// Regression tests for the RouteEdge floor-mismatch fix (Sakara /
// "Corridor Point 1784655473213-3" on QuickRoute Mall - Floor 1 rejected
// with "Walkway edge must connect points on the same floor").
//
// Backend root cause and fix are covered by
// backend/tests/test_route_edge_floor_consistency.py (10 tests: same-map
// allowed, null-floor derives from Map, stale-floor repair, different
// map_ids rejected, different floors/maps rejected, backfill dry-run is a
// no-op, backfill apply is idempotent, no duplicate points/edges). This
// file covers the two frontend-side requirements from that same fix:
//   - Section 7: Draw Walkable Path's Save Path must send ONLY a reused
//     point's id, never its floor — the backend resolves the real
//     floor/map relationship, so a stale frontend floor value must never
//     even be transmitted for a reused point.
//   - Section 6: the new "Repair RoutePoint Floors from Maps" admin
//     action must call the backfill endpoint with a real dry-run body,
//     and AdminMapScreen.jsx must wire it as dry-run -> show count ->
//     confirm -> apply -> refresh points/edges, never skip straight to
//     applying.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { partitionDraftForSave } from './drawPathHelpers.js';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

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

// ── Section 7: reused points send only their id, never a floor ─────────
test('partitionDraftForSave: a reused ("existing") draft point never carries a floor field into the save payload', () => {
  const draftPoints = [
    {
      tempId: 'existing-sakara-1',
      kind: 'existing',
      routePointId: 'sakara-id',
      x: 100,
      y: 100,
      // Even if a stale/local floor value is present on the draft item
      // itself (e.g. from the marker's last-known client state), the
      // reuse payload partitionDraftForSave builds must never surface it
      // — Save Path only ever sends `routePointId` for a reuse.
      floor: 0,
      name: 'Sakara',
    },
    {
      tempId: 'new-1',
      kind: 'new',
      x: 150,
      y: 150,
      floor: 1,
      name: 'Point 1',
    },
  ];

  const { reuses, creates } = partitionDraftForSave(draftPoints);

  assert.equal(reuses.length, 1);
  assert.deepEqual(Object.keys(reuses[0]).sort(), ['index', 'routePointId'].sort());
  assert.equal('floor' in reuses[0], false);
  assert.equal(reuses[0].routePointId, 'sakara-id');

  // New points are unaffected — they still need a floor to create with
  // (the backend now derives the authoritative value from the Map
  // regardless, but the field is still sent as a hint per the schema).
  assert.equal(creates.length, 1);
  assert.equal(creates[0].floor, 1);
});

test('AdminMapScreen never calls updateRoutePoint (no floor-overwrite path) as part of Draw Walkable Path save', () => {
  const source = fs.readFileSync(
    path.join(__dirname, '..', 'screens', 'AdminMapScreen.jsx'),
    'utf8',
  );
  assert.doesNotMatch(source, /updateRoutePoint\(/);
});

test('RouteEdgeCreate payload sent by AdminMapScreen never includes a floor field', () => {
  const source = fs.readFileSync(
    path.join(__dirname, '..', 'screens', 'AdminMapScreen.jsx'),
    'utf8',
  );
  const edgeCallMatches = source.match(/createRouteEdge\(\{[\s\S]*?\}\)/g) || [];
  assert.ok(edgeCallMatches.length > 0, 'expected at least one createRouteEdge( { ... } ) call');
  edgeCallMatches.forEach((block) => {
    assert.doesNotMatch(block, /floor\s*:/);
  });
});

// ── Section 5/6: backfill endpoint wiring ───────────────────────────────
test('routePointsApi.js exposes backfillRoutePointFloorFromMap posting dry_run to the exact required endpoint', () => {
  const source = fs.readFileSync(
    path.join(__dirname, '..', 'api', 'routePointsApi.js'),
    'utf8',
  );
  assert.match(source, /export function backfillRoutePointFloorFromMap\(dryRun = true\)/);
  assert.match(source, /"\/api\/route-points\/backfill-floor-from-map"/);
  assert.match(source, /method: "POST"/);
  assert.match(source, /dry_run:\s*dryRun/);
});

test('AdminMapScreen wires the repair action as dry-run -> count -> confirm -> apply -> refresh, never applying directly', () => {
  const source = fs.readFileSync(
    path.join(__dirname, '..', 'screens', 'AdminMapScreen.jsx'),
    'utf8',
  );

  assert.match(source, /const handleRepairRoutePointFloors = async \(\) => \{/);

  const handlerMatch = source.match(
    /const handleRepairRoutePointFloors = async \(\) => \{[\s\S]*?\n  \};/,
  );
  assert.ok(handlerMatch, 'expected to find handleRepairRoutePointFloors body');
  const handlerBody = handlerMatch[0];

  // Dry run first — the very first backfill call must request dry_run.
  const firstCallIndex = handlerBody.indexOf('backfillRoutePointFloorFromMap(true)');
  const applyCallIndex = handlerBody.indexOf('backfillRoutePointFloorFromMap(false)');
  const confirmIndex = handlerBody.indexOf('window.confirm(');
  const refreshIndex = handlerBody.indexOf('refreshRouteGraph(');

  assert.ok(firstCallIndex !== -1, 'expected an initial dry_run=true preview call');
  assert.ok(applyCallIndex !== -1, 'expected a dry_run=false apply call');
  assert.ok(confirmIndex !== -1, 'expected an explicit confirmation before applying');
  assert.ok(refreshIndex !== -1, 'expected points/edges to be refreshed after applying');

  // Strict ordering: preview -> confirm -> apply -> refresh.
  assert.ok(firstCallIndex < confirmIndex, 'dry-run preview must happen before confirmation');
  assert.ok(confirmIndex < applyCallIndex, 'confirmation must happen before the real apply call');
  assert.ok(applyCallIndex < refreshIndex, 'refresh must happen after the apply call');

  // The preview path must be able to exit BEFORE any confirmation/apply
  // when nothing needs fixing (points_needing_update === 0) — never
  // silently invoke window.confirm for a no-op.
  assert.match(handlerBody, /points_needing_update === 0/);
});

test('the repair button is disabled while running and reachable regardless of which map is open (global repair, not scoped to activeMap)', () => {
  const source = fs.readFileSync(
    path.join(__dirname, '..', 'screens', 'AdminMapScreen.jsx'),
    'utf8',
  );
  assert.match(source, /onClick=\{handleRepairRoutePointFloors\}/);
  assert.match(source, /disabled=\{isRepairingFloors\}/);
});

console.log(`\n${passed} test(s) passed.`);
if (process.exitCode) {
  console.error('One or more tests FAILED.');
} else {
  console.log('All tests passed.');
}
