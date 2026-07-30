// Regression tests for the "empty Floor dropdown / different-map-floor
// rejection" bug report: Draw Walkable Path's floor <select> rendered only
// a single blank "—" option, and clicking an existing Floor 1 point
// ("Sakara") was rejected as "different map/floor or inactive" even though
// it was clicked directly on its own correctly-rendered marker.
//
// Root cause (confirmed by tracing the real data flow end-to-end —
// backend Map model -> map_to_response() -> MapResponse -> mapsApi.js's
// normalizeMap() -> AdminMapScreen.jsx's activeMap/activeFloor ->
// drawPathHelpers.resolveExistingPointSelection): a legacy/ungrouped Map
// document's own `floor` field can genuinely be null (predates the
// multi-floor Map Group feature — see models/map_model.py's own comment).
// The previous fix's `activeFloor = activeMap?.floor ?? 0` silently
// promoted that null to a fake "0" (Ground Floor), which then poisoned
// TWO independent things at once: (1) the floor dropdown's only option
// showed formatFloorDisplay(null, null) = "—", and (2) the fabricated
// `drawFloor = 0` caused resolveExistingPointSelection's floor check to
// reject a real Floor-1 point (point.floor=1 !== drawFloor=0) even though
// the map-id check already proved it was the right map (RoutePoints are
// always fetched scoped to one exact map_id server-side, so a genuine
// map-id match already implies "same map" — the floor check was
// redundant AND was firing on a fabricated value). The fix has three
// parts: (a) never coerce an unknown floor to 0 anywhere in this chain,
// (b) build floor options from the full loaded Maps list via a
// buildingId-fallback, never a single-Map fallback that can render blank,
// (c) skip the floor comparison entirely when the active map's floor is
// genuinely unknown, trusting the already-scoped map-id match instead.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import {
  normalizeId,
  normalizeFloorNumber,
  buildFloorOptions,
  resolveFloorSwitch,
} from './mapGroupHelpers.js';
import { resolveExistingPointSelection } from './drawPathHelpers.js';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const adminScreenSource = fs.readFileSync(
  path.join(__dirname, '..', 'screens', 'AdminMapScreen.jsx'),
  'utf8',
);
// mapsApi.js imports the browser-only `./api` module (extensionless
// specifier, resolvable under Vite but not plain Node ESM — the same
// reason every other *.test.mjs in this repo avoids importing api/*.js
// directly), so its normalizeMap() is exercised here via a source-text
// contract on the actual wiring instead of a live import. This still
// fails loudly if normalizeMap ever stops calling these exact shared
// primitives with these exact field-name fallbacks.
const mapsApiSource = fs.readFileSync(
  path.join(__dirname, '..', 'api', 'mapsApi.js'),
  'utf8',
);

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

// ── 1. Maps using `_id` instead of `id` ─────────────────────────────────
test('normalizeId (the exact primitive normalizeMap uses for id) resolves a real id from `_id` when `id` is absent', () => {
  const map = { _id: 'mongo-oid-1', title: 'Ground Floor', floor: 0 };
  assert.equal(normalizeId(map.id, map._id, map.map_id, map.mapId), 'mongo-oid-1');
});

// ── 2. Maps using `id` (the normal MapResponse shape) ───────────────────
test('normalizeId resolves a real id from `id` (standard MapResponse shape)', () => {
  const map = { id: 'map-abc', title: 'Floor 1', floor: 1 };
  assert.equal(normalizeId(map.id, map._id, map.map_id, map.mapId), 'map-abc');
});

// ── 3. Maps using `map_id` (defensive, non-standard shape) ──────────────
test('normalizeId resolves a real id from `map_id` when neither id nor _id is present', () => {
  const map = { map_id: 'raw-map-id', title: 'Floor 2', floor: 2 };
  assert.equal(normalizeId(map.id, map._id, map.map_id, map.mapId), 'raw-map-id');
});

// ── 4. floor=0 preserved (never mistaken for "missing") ─────────────────
test('normalizeFloorNumber (the exact primitive normalizeMap uses for floor) preserves floor 0 as a real Ground Floor value, not "missing"', () => {
  assert.equal(normalizeFloorNumber(0), 0);
  assert.notEqual(normalizeFloorNumber(0), null);
  assert.equal(normalizeFloorNumber(undefined, 0), 0);
});

// ── mapsApi.js wiring contract ───────────────────────────────────────────
test('mapsApi.js normalizeMap actually wires id/floor through normalizeId/normalizeFloorNumber with every required field-name fallback', () => {
  assert.match(mapsApiSource, /import \{ normalizeId, normalizeFloorNumber \} from ["']\.\.\/utils\/mapGroupHelpers["']/);
  assert.match(mapsApiSource, /id: normalizeId\(map\.id, map\._id, map\.map_id, map\.mapId\)/);
  assert.match(
    mapsApiSource,
    /floor: normalizeFloorNumber\(map\.floor, map\.floor_number, map\.floorNumber, map\.level\)/,
  );
  assert.match(mapsApiSource, /buildingId: normalizeId\(map\.building_id, map\.buildingId\)/);
  assert.match(
    mapsApiSource,
    /mapGroupId: normalizeId\(map\.map_group_id, map\.mapGroupId, map\.group_id\)/,
  );
  assert.match(mapsApiSource, /isActive: Boolean\(map\.is_active \?\? map\.isActive \?\? true\)/);
});

// ── 5. ObjectId-shaped vs. plain-string id comparison succeeds ──────────
test('normalizeId reconciles an ObjectId-shaped value against an already-stringified id', () => {
  const fakeObjectId = { toString: () => '507f1f77bcf86cd799439011' };
  assert.equal(normalizeId(fakeObjectId), '507f1f77bcf86cd799439011');
  assert.equal(normalizeId(fakeObjectId), normalizeId('507f1f77bcf86cd799439011'));

  // And resolveExistingPointSelection must treat these as the SAME map,
  // not reject as 'wrong-map', when one side arrives ObjectId-shaped.
  const result = resolveExistingPointSelection({
    point: { id: 'p1', map_id: fakeObjectId, floor: 1, is_active: true },
    activeMapId: '507f1f77bcf86cd799439011',
    drawFloor: 1,
    lastDraftPoint: null,
  });
  assert.equal(result.ok, true);
});

// ── 6. Empty/absent Map-Group linkage falls back to buildingId siblings ──
test('buildFloorOptions falls back to buildingId siblings when mapGroupId linkage is empty/missing', () => {
  const groundFloor = { id: 'map-0', title: 'Ground Floor', floor: 0, buildingId: 'bldg-1', mapGroupId: null };
  const floor1 = { id: 'map-1', title: 'Floor 1', floor: 1, buildingId: 'bldg-1', mapGroupId: null };
  const unrelated = { id: 'map-x', title: 'Other Building', floor: 0, buildingId: 'bldg-2', mapGroupId: null };

  const options = buildFloorOptions(floor1, [groundFloor, floor1, unrelated]);
  const ids = options.map((o) => o.mapId).sort();
  assert.deepEqual(ids, ['map-0', 'map-1']);
});

// ── 7. The active rendered Map is always present in the options ─────────
test('buildFloorOptions always includes the active map even when it has no group/building siblings at all', () => {
  const legacyStandalone = { id: 'map-legacy', title: 'Legacy Map', floor: null, buildingId: null, mapGroupId: null };
  const options = buildFloorOptions(legacyStandalone, [legacyStandalone]);
  assert.equal(options.length, 1);
  assert.equal(options[0].mapId, 'map-legacy');
});

// ── 8. Floor 0/1/2 options sort numerically ──────────────────────────────
test('buildFloorOptions sorts Ground Floor / Floor 1 / Floor 2 numerically ascending regardless of input order', () => {
  const floor2 = { id: 'map-2', floor: 2, buildingId: 'b', mapGroupId: 'g' };
  const floor0 = { id: 'map-0', floor: 0, buildingId: 'b', mapGroupId: 'g' };
  const floor1 = { id: 'map-1', floor: 1, buildingId: 'b', mapGroupId: 'g' };

  const options = buildFloorOptions(floor0, [floor2, floor0, floor1]);
  assert.deepEqual(options.map((o) => o.floor), [0, 1, 2]);
  assert.deepEqual(options.map((o) => o.floorLabel), ['Ground Floor', 'Floor 1', 'Floor 2']);
});

// ── 9. AdminMapScreen's <select> value/options use mapId (Section 4) ────
test('AdminMapScreen renders the floor <select> keyed/valued by option.mapId, not option.id', () => {
  assert.match(adminScreenSource, /key=\{floorMap\.mapId\}\s*value=\{floorMap\.mapId\}/);
  assert.match(adminScreenSource, /value=\{selectedMapId\}/);
});

// ── 10. Selecting Floor 1 from the dropdown changes selectedMapId ───────
test('resolveFloorSwitch changes selectedMapId to the target Floor 1 map id when chosen', () => {
  const decision = resolveFloorSwitch({
    targetMapId: 'map-1',
    currentMapId: 'map-0',
    hasDraft: false,
    confirmFn: () => true,
  });
  assert.equal(decision.proceed, true);
  assert.equal(decision.nextMapId, 'map-1');
});

// ── 11. RoutePoints/RouteEdges reload strictly for the new mapId ────────
test('AdminMapScreen reloads route points/edges via refreshRouteGraph(selectedMapId) whenever selectedMapId changes', () => {
  assert.match(adminScreenSource, /refreshRouteGraph\(selectedMapId\)/);
  assert.match(adminScreenSource, /\[selectedMapId, refreshRouteGraph\]/);
});

// ── 12. A current Floor 1 point ("Sakara") is reusable — no false reject ─
test('a Floor 1 point clicked while Floor 1 is active is reusable even when the active map\'s own floor metadata is unknown (null)', () => {
  // This is the exact Sakara scenario: the admin is genuinely on the
  // Floor 1 map (activeMapId correctly matches), but activeMap.floor
  // itself is null (legacy map, floor never set) so drawFloor is null —
  // the floor check must be SKIPPED, not fabricate a Ground-Floor (0)
  // mismatch.
  const sakaraPoint = { id: 'point-sakara', map_id: 'map-floor-1', floor: 1, is_active: true, name: 'Sakara' };

  const result = resolveExistingPointSelection({
    point: sakaraPoint,
    activeMapId: 'map-floor-1',
    drawFloor: null, // activeMap.floor was unknown/null — must not become 0
    lastDraftPoint: null,
  });

  assert.equal(result.ok, true, `Expected Sakara's point to be reusable, got rejection: ${result.reason}`);
  assert.equal(result.draftItem.routePointId, 'point-sakara');
});

// ── 13. A genuinely legacy-map point produces the precise reassignment message ──
test('a point genuinely belonging to a different (legacy) map is rejected as wrong-map, and AdminMapScreen surfaces the precise reassignment message for it', () => {
  const legacyPoint = { id: 'point-old', map_id: 'map-old-legacy', floor: 1, is_active: true };

  const result = resolveExistingPointSelection({
    point: legacyPoint,
    activeMapId: 'map-floor-1-current',
    drawFloor: 1,
    lastDraftPoint: null,
  });

  assert.equal(result.ok, false);
  assert.equal(result.reason, 'wrong-map');

  // AdminMapScreen must branch on this exact reason and use the precise
  // message text required by the spec, not the generic rejection.
  assert.match(adminScreenSource, /result\.reason === 'wrong-map'/);
  assert.match(
    adminScreenSource,
    /This destination point belongs to a different map\. Reassign the destination to the current \$\{floorLabel\} map before connecting it\./,
  );
});

// ── 14. No blank "—" option renders when a real Map exists ──────────────
test('buildFloorOptions never returns a bare "—" floorLabel when a real Map exists, even with null floor and no title', () => {
  const noFloorNoTitle = { id: 'map-mystery', floor: null, floorLabel: null, title: '', buildingId: null, mapGroupId: null };
  const options = buildFloorOptions(noFloorNoTitle, [noFloorNoTitle]);
  assert.equal(options.length, 1);
  assert.notEqual(options[0].floorLabel, '—');
  assert.equal(options[0].floorLabel, 'Map');

  const withTitle = { id: 'map-mystery-2', floor: null, floorLabel: null, title: 'Annex Building', buildingId: null, mapGroupId: null };
  const options2 = buildFloorOptions(withTitle, [withTitle]);
  assert.equal(options2[0].floorLabel, 'Annex Building');
});

// ── 15. A true empty Maps response shows the explicit empty state + Retry ──
test('AdminMapScreen shows "No floor maps were loaded" + a Retry Maps button (never a blank <select>) when floorSelectOptions is empty', () => {
  assert.match(adminScreenSource, /floorSelectOptions\.length === 0/);
  assert.match(adminScreenSource, /t\.noFloorMapsLoaded/);
  assert.match(adminScreenSource, /t\.retryMapsButton/);
  assert.match(adminScreenSource, /onClick=\{\(\) => loadMaps\(selectedMapId\)\}/);
});

console.log(`\n${passed} test(s) passed.`);
if (process.exitCode) {
  console.error('One or more tests FAILED.');
} else {
  console.log('All tests passed.');
}
