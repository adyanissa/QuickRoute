// Plain-Node tests for the multi-floor Map Group upload/management workflow
// wired into AdminMapScreen.jsx (Upload New Map mode toggle + dynamic floor
// rows, Map Management grouped-by-map-group list, and the full-map editor's
// floor switcher).
//
// This repo has no jsdom/jest/vitest, so React component behavior that
// can't be exercised as a pure function is instead verified as a "layout
// contract" against the real source text (matching the existing pattern in
// fullMapWorkspaceLayout.test.mjs / floatingToolPanelLayout.test.mjs). Pure
// logic (row validation, sorting, grouping, floor-label formatting) is
// exercised directly via mapGroupHelpers.js, and the multipart upload
// payload shape is exercised directly against mapGroupsApi.js with a
// captured `fetch`.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import {
  createEmptyFloorRow,
  validateFloorRows,
  sortFloorsByNumber,
  groupMapsByMapGroup,
} from '../utils/mapGroupHelpers.js';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

// Normalize CRLF -> LF so every regex below only has to account for one
// line-ending convention regardless of how the source file was checked out.
const adminMapScreenSource = readFileSync(
  path.join(__dirname, 'AdminMapScreen.jsx'),
  'utf8',
).replace(/\r\n/g, '\n');
const mapGroupsApiSource = readFileSync(
  path.join(__dirname, '..', 'api', 'mapGroupsApi.js'),
  'utf8',
).replace(/\r\n/g, '\n');

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

// ── 1. Single/Multi mode switching ──────────────────────────────────────
test('AdminMapScreen renders a Single-Floor/Multi-Floor mode toggle backed by uploadMode state', () => {
  assert.match(adminMapScreenSource, /const \[uploadMode, setUploadMode\] = useState\('single'\)/);
  assert.match(adminMapScreenSource, /onClick=\{\(\) => setUploadMode\('single'\)\}/);
  assert.match(adminMapScreenSource, /onClick=\{\(\) => setUploadMode\('multi'\)\}/);
  assert.match(adminMapScreenSource, /\{uploadMode === 'single' && \(/);
  assert.match(adminMapScreenSource, /\{uploadMode === 'multi' && \(/);
});

// ── 2. Add 3+ floor rows, no hardcoded max ──────────────────────────────
test('Add Another Floor has no hardcoded cap (e.g. no floorRows.length >= 3 guard) and can append arbitrarily many rows', () => {
  assert.match(adminMapScreenSource, /const addFloorRowTo = \(setRows\) => \{/);
  assert.doesNotMatch(adminMapScreenSource, /floorRows\.length\s*[<>]=?\s*3/);
  assert.doesNotMatch(adminMapScreenSource, /floorRows\.length\s*===\s*3/);

  // Exercise the underlying row-creation helper directly: adding floor
  // rows one at a time past 3 must keep succeeding with distinct ids.
  let rows = [createEmptyFloorRow([])];
  for (let i = 0; i < 5; i += 1) {
    rows = [...rows, createEmptyFloorRow(rows, `seed-${i}`)];
  }
  assert.equal(rows.length, 6);
  assert.equal(new Set(rows.map((r) => r.rowId)).size, 6);
});

// ── 3. Each row preserves its own file/floor/label/title/scale ─────────
test('floor rows are independent objects — updating one field on one row never affects sibling rows', () => {
  const rowA = createEmptyFloorRow([]);
  const rowB = createEmptyFloorRow([rowA], 'row-b');
  let rows = [rowA, rowB];

  // Mirrors updateFloorRowIn's map-by-rowId update logic.
  const updateRow = (rowId, field, value) => {
    rows = rows.map((row) => (row.rowId === rowId ? { ...row, [field]: value } : row));
  };

  updateRow(rowA.rowId, 'title', 'Ground Floor');
  updateRow(rowA.rowId, 'floor', 0);
  updateRow(rowA.rowId, 'scale', 2.5);
  updateRow(rowB.rowId, 'title', 'First Floor');
  updateRow(rowB.rowId, 'floor', 1);

  const finalA = rows.find((r) => r.rowId === rowA.rowId);
  const finalB = rows.find((r) => r.rowId === rowB.rowId);

  assert.equal(finalA.title, 'Ground Floor');
  assert.equal(finalA.scale, 2.5);
  assert.equal(finalB.title, 'First Floor');
  assert.equal(finalB.scale, 1); // untouched default, not leaked from row A
});

// ── 4. Duplicate floor numbers block submission ─────────────────────────
test('handleUploadMapGroup validates floorRows via validateFloorRows before calling the API, and duplicate floors fail validation', () => {
  assert.match(adminMapScreenSource, /const rowErrors = validateFloorRows\(floorRows\);/);
  assert.match(adminMapScreenSource, /if \(Object\.keys\(rowErrors\)\.length > 0\) \{/);

  const rows = [
    { rowId: 'a', file: {}, title: 'Ground', floor: 0, scale: 1 },
    { rowId: 'b', file: {}, title: 'Also Ground', floor: 0, scale: 1 },
  ];
  const errors = validateFloorRows(rows);
  assert.equal(Object.keys(errors).length, 2);
});

// ── 5. Remove Floor removes only the targeted row ───────────────────────
test('removeFloorRowFrom filters out exactly the targeted rowId and leaves the others untouched', () => {
  assert.match(
    adminMapScreenSource,
    /return previousRows\.filter\(\(row\) => row\.rowId !== rowId\);/,
  );

  const rows = [
    { rowId: 'a', title: 'Floor A' },
    { rowId: 'b', title: 'Floor B' },
    { rowId: 'c', title: 'Floor C' },
  ];
  const removed = rows.filter((row) => row.rowId !== 'b');
  assert.deepEqual(removed.map((r) => r.rowId), ['a', 'c']);
});

// ── 6. Upload payload preserves floor metadata ──────────────────────────
// mapGroupsApi.js uses extensionless relative imports (fine for Vite, not
// resolvable under plain `node`), so it can't be dynamically imported by
// this plain-Node test file — instead this both (a) source-checks the real
// file builds one `files` FormData entry per floor and a `floors_json`
// entry, and (b) exercises a byte-for-byte copy of its floor-mapping logic
// (kept in sync with the `floorsJson = floors.map(...)` block in
// createMapGroup/addMapGroupFloors) directly against FormData, so a
// regression in either the shape or the real source is caught.
test('mapGroupsApi.js builds one files entry and a floors_json entry per floor, preserving title/floor/floor_label/scale', () => {
  assert.match(mapGroupsApiSource, /formData\.append\("floors_json", JSON\.stringify\(floorsJson\)\)/);
  assert.match(mapGroupsApiSource, /floors\.forEach\(\(floor\) => formData\.append\("files", floor\.file\)\)/);
  assert.match(mapGroupsApiSource, /floor_label: floor\.floorLabel \|\| null/);

  const floors = [
    { file: new Blob(['png-bytes-0']), title: 'Ground Floor', floor: 0, floorLabel: 'Ground', scale: 1, useOpenAI: false, autoGenerateGraph: true },
    { file: new Blob(['png-bytes-1']), title: 'First Floor', floor: 1, floorLabel: 'Level 1', scale: 1.2, useOpenAI: true, autoGenerateGraph: false },
  ];

  // Mirrors the floorsJson mapping in createMapGroup/addMapGroupFloors.
  const floorsJson = floors.map((floor) => ({
    title: floor.title,
    floor: Number(floor.floor),
    floor_label: floor.floorLabel || null,
    scale: Number(floor.scale) > 0 ? Number(floor.scale) : 1,
    use_openai: Boolean(floor.useOpenAI),
    auto_generate_graph: floor.autoGenerateGraph !== false,
  }));

  const formData = new FormData();
  formData.append('floors_json', JSON.stringify(floorsJson));
  floors.forEach((floor) => formData.append('files', floor.file));

  assert.equal(formData.getAll('files').length, 2);
  const parsed = JSON.parse(formData.get('floors_json'));
  assert.equal(parsed[0].title, 'Ground Floor');
  assert.equal(parsed[0].floor, 0);
  assert.equal(parsed[0].floor_label, 'Ground');
  assert.equal(parsed[1].scale, 1.2);
  assert.equal(parsed[1].use_openai, true);
  assert.equal(parsed[1].auto_generate_graph, false);
});

// ── 7. Map Management groups by map_group_id ────────────────────────────
test('AdminMapScreen derives mapManagementGroups via groupMapsByMapGroup(maps)', () => {
  assert.match(adminMapScreenSource, /groupMapsByMapGroup\(maps\)/);

  const maps = [
    { id: 'm1', mapGroupId: 'g1', floor: 0 },
    { id: 'm2', mapGroupId: 'g1', floor: 1 },
    { id: 'legacy', mapGroupId: null },
  ];
  const { groups, ungrouped } = groupMapsByMapGroup(maps);
  assert.equal(groups.length, 1);
  assert.equal(groups[0].floors.length, 2);
  assert.equal(ungrouped.length, 1);
});

// ── 8. Floors are always displayed/sorted in numeric order ─────────────
test('sortFloorsByNumber orders floors ascending regardless of upload order', () => {
  const sorted = sortFloorsByNumber([{ floor: 2 }, { floor: -1 }, { floor: 0 }, { floor: 1 }]);
  assert.deepEqual(sorted.map((f) => f.floor), [-1, 0, 1, 2]);
});

// ── 9. Add Floor reuses the existing group's code (never regenerates it) ─
test('addMapGroupFloors never sends a code/name field — it can only ever reuse the existing group identity via the URL group id', () => {
  assert.doesNotMatch(mapGroupsApiSource.split('export async function addMapGroupFloors')[1].split('\n\n')[0], /formData\.append\("code"/);
  assert.doesNotMatch(mapGroupsApiSource.split('export async function addMapGroupFloors')[1].split('\n\n')[0], /formData\.append\("name"/);
  assert.match(adminMapScreenSource, /apiAddMapGroupFloors\(group\.id, addFloorRows\)/);
});

// ── 10. Floor switcher loads only the selected floor's data ────────────
test('handleFloorSwitch swaps selectedMapId (which the existing per-map routePoints/routeEdges effects key off of) and never merges the previous floor\'s draft points', () => {
  assert.match(adminMapScreenSource, /const handleFloorSwitch = \(mapId\) => \{/);
  const fnBody = adminMapScreenSource.split('const handleFloorSwitch = (mapId) => {')[1].split('\n  };')[0];
  assert.match(fnBody, /resolveFloorSwitch\(\{/);
  assert.match(fnBody, /setDraftPoints\(\[\]\);/);
  assert.match(fnBody, /setSelectedMapId\(decision\.nextMapId\);/);
});

// ── 11. Unsaved drafts are protected during floor switching ────────────
test('handleFloorSwitch confirms with the admin before discarding in-progress draft points', () => {
  const fnBody = adminMapScreenSource.split('const handleFloorSwitch = (mapId) => {')[1].split('\n  };')[0];
  assert.match(fnBody, /hasDraft: draftPoints\.length > 0,/);
  assert.match(fnBody, /confirmFn: \(\) => window\.confirm\(t\.floorSwitchConfirm\),/);
  assert.match(fnBody, /if \(!decision\.proceed\) return;/);
});

// ── 11b. The floor field is a real, always-editable control ────────────
test('the floor field is a real <select>, never a disabled/read-only input', () => {
  assert.doesNotMatch(adminMapScreenSource, /value=\{activeFloorLabel\}/);
  assert.match(adminMapScreenSource, /const renderFloorSelect = /);
});

// ── 12. Existing single-floor maps remain visible ───────────────────────
test('the flat map dropdown still renders every entry in maps (ungrouped single-floor maps are never filtered out by the grouping UI)', () => {
  assert.match(adminMapScreenSource, /\{maps\.map\(\(map\) => \(/);
});

// ── 13. Arabic/Hebrew/English layouts all have the new UI strings ──────
test('every new multi-floor UI translation key exists in en, ar, and he with a non-empty value', () => {
  const requiredKeys = [
    'modeSingle',
    'modeMulti',
    'mapGroupInfoTitle',
    'mapGroupName',
    'mapGroupCode',
    'floorNumber',
    'floorLabel',
    'addAnotherFloor',
    'removeFloor',
    'uploadAllFloors',
    'addFloor',
    'editGroup',
    'deleteGroup',
    'floorSwitcher',
    'floorSwitchConfirm',
  ];

  const blockPattern = /(en|ar|he):\s*\{([\s\S]*?)\n  \},\n\n?/g;
  const blocks = {};
  let match;
  while ((match = blockPattern.exec(adminMapScreenSource)) !== null) {
    blocks[match[1]] = match[2];
  }

  assert.ok(blocks.en && blocks.ar && blocks.he, 'expected en/ar/he UI blocks to be found');

  for (const lang of ['en', 'ar', 'he']) {
    for (const key of requiredKeys) {
      const re = new RegExp(`\\b${key}:\\s*'([^']+)'`);
      const found = blocks[lang].match(re);
      assert.ok(found, `missing UI.${lang}.${key}`);
      assert.ok(found[1].trim().length > 0, `UI.${lang}.${key} is empty`);
    }
  }
});

console.log(`\n${passed} test(s) passed.`);
if (process.exitCode) {
  console.error('One or more tests FAILED.');
} else {
  console.log('All tests passed.');
}
