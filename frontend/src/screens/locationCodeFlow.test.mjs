// Source-text contract tests — QuickRoute User Experience Final Cleanup,
// Part 10 items 12-16 (Location Code flow) and Part 3.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const barcodeSource = fs.readFileSync(path.join(__dirname, 'BarcodeEntryScreen.jsx'), 'utf8');
const destSource = fs.readFileSync(path.join(__dirname, 'DestinationSelectionScreen.jsx'), 'utf8');

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

// 12. A valid Location Code with a building_id navigates straight to
//     Destination Selection (/screen/17) — never to Building Selection.
test('a resolved Location Code navigates directly to /screen/17, never back through Building Selection', () => {
  assert.match(barcodeSource, /navigate\('\/screen\/17'/);
  assert.doesNotMatch(barcodeSource, /navigate\('\/screen\/16'/);
});

// 13. Destination Selection loads rooms scoped to the resolved building
//     only (via the real building_id filter, never every room).
test('DestinationSelectionScreen loads rooms filtered to a single building_id', () => {
  assert.match(destSource, /getRooms\(\{\s*building_id:\s*building\.id\s*\}\)/);
});

// 14. The full resolved Location Code payload — route_point_id, map_id,
//     map_group_id, floor, and label — is preserved, not just a subset.
test('BarcodeEntryScreen persists route_point_id, map_id, map_group_id, floor, and label', () => {
  assert.match(barcodeSource, /routePointId:\s*resolved\.route_point_id/);
  assert.match(barcodeSource, /mapId:\s*resolved\.map_id/);
  assert.match(barcodeSource, /mapGroupId:\s*resolved\.map_group_id/);
  assert.match(barcodeSource, /floor:\s*resolved\.floor/);
  assert.match(barcodeSource, /label:\s*resolved\.label/);
});

// 15. An unlinked Location Code (no building_id) shows the specific
//     honest error state instead of a generic invalid-code message or a
//     frontend-guessed fallback building.
test('a Location Code with no building_id shows the "not linked to a valid building" error', () => {
  assert.match(barcodeSource, /if \(!resolved\?\.building_id\)/);
  assert.match(barcodeSource, /setError\(t\.noBuilding\)/);
  assert.match(barcodeSource, /noBuilding:\s*'This location code is not linked to a valid building\.'/);
});

// 16. Destinations are always requested scoped to the specific building
//     the QR/Location Code resolved — DestinationSelectionScreen never
//     calls getRooms() with no filter (which would return every
//     building's rooms).
test('DestinationSelectionScreen never fetches rooms without a building_id filter', () => {
  assert.doesNotMatch(destSource, /getRooms\(\)/);
  assert.doesNotMatch(destSource, /getRooms\(\{\}\)/);
});

console.log(`\n${passed} test(s) passed.`);
if (process.exitCode) {
  console.error('One or more tests FAILED.');
} else {
  console.log('All tests passed.');
}
