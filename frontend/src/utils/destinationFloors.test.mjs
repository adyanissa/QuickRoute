// The floor/map filter on the user Destination Selection screen.
//
// The whole point of this helper is that the options are DERIVED, never
// declared. A hard-coded ["G","1","2","3"] would look right against the
// one building this project is currently deployed against and be wrong
// for every other one — so these tests feed it buildings that look
// nothing like ours (one floor, seven floors, custom labels, unrelated
// map groups) and assert the options match the data it was given.
//
// Two layers, matching this repo's conventions (no jest/testing-library —
// see screens/multilingualRerender.test.mjs):
//   * real unit tests of utils/destinationFloors.js against synthetic
//     room fixtures, and
//   * source-text contract tests that the screen is wired to them, that
//     Back targets the location-code route, and that no building, room,
//     floor name or floor count is written into the frontend.
//
// Every fixture below is invented. Nothing here reads production data.
//
// Run with: node frontend/src/utils/destinationFloors.test.mjs

import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import {
  ALL_FLOORS,
  filterRoomsByFloor,
  isInRelatedScope,
  reconcileFloorSelection,
  resolveFloorOptions,
  shouldShowFloorFilter,
} from './destinationFloors.js';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

const read = (relative) =>
  fs.readFileSync(path.join(__dirname, relative), 'utf8');

const stripComments = (source) =>
  source
    .replace(/\{\/\*[\s\S]*?\*\/\}/g, '')
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/^\s*\/\/.*$/gm, '');

const screenSource = read('../screens/DestinationSelectionScreen.jsx');
const screenCode = stripComments(screenSource);
const helperCode = stripComments(read('./destinationFloors.js'));

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

// ── Synthetic fixtures ───────────────────────────────────────────────────
// Deliberately unlike this project's real deployment: invented ids,
// invented names, invented floor numbering.

const room = ({ id, mapId, mapGroupId = 'grp-alpha', floor = 0, name = 'Somewhere', type = 'room' }) => ({
  id,
  mapId,
  mapGroupId,
  floor,
  name,
  nameEn: name,
  names: { en: name },
  type,
  description: '',
  isNavigable: true,
  isActive: true,
});

// A two-floor site.
const TWO_FLOOR_ROOMS = [
  room({ id: 'r1', mapId: 'map-g', floor: 0, name: 'Welcome Desk' }),
  room({ id: 'r2', mapId: 'map-g', floor: 0, name: 'Parcel Locker' }),
  room({ id: 'r3', mapId: 'map-1', floor: 1, name: 'Seminar Hall' }),
];

// A seven-floor tower, including basements.
const SEVEN_FLOOR_ROOMS = [-2, -1, 0, 1, 2, 3, 4].map((floor, index) =>
  room({
    id: `t${index}`,
    mapId: `tower-map-${index}`,
    mapGroupId: 'grp-tower',
    floor,
    name: `Space ${index}`,
  }),
);

const START_ALPHA = { mapId: 'map-g', mapGroupId: 'grp-alpha' };


// ── 1. Options are derived from the data, not declared ───────────────────

test('2 real floors produce exactly 2 floor options', () => {
  const options = resolveFloorOptions(TWO_FLOOR_ROOMS, START_ALPHA);

  assert.equal(options.length, 2);
  assert.deepEqual(options.map((o) => o.mapId), ['map-g', 'map-1']);
});

test('7 real floors all appear, ordered by real floor number', () => {
  const options = resolveFloorOptions(SEVEN_FLOOR_ROOMS, {
    mapId: 'tower-map-2',
    mapGroupId: 'grp-tower',
  });

  assert.equal(options.length, 7);
  assert.deepEqual(options.map((o) => o.floor), [-2, -1, 0, 1, 2, 3, 4]);
});

test('1 real floor produces exactly 1 option — no invented neighbours', () => {
  const options = resolveFloorOptions(
    [room({ id: 'a', mapId: 'only-map', floor: 0 })],
    { mapId: 'only-map', mapGroupId: 'grp-alpha' },
  );

  assert.equal(options.length, 1);
  // ...and the filter hides itself, because it would filter nothing.
  assert.equal(shouldShowFloorFilter(options), false);
});

test('the filter appears only once there is a real choice', () => {
  assert.equal(shouldShowFloorFilter([]), false);
  assert.equal(shouldShowFloorFilter(resolveFloorOptions(TWO_FLOOR_ROOMS, START_ALPHA)), true);
});

test('no destinations at all produces no options and no crash', () => {
  assert.deepEqual(resolveFloorOptions([], START_ALPHA), []);
  assert.deepEqual(resolveFloorOptions(null, null), []);
  assert.deepEqual(resolveFloorOptions(undefined), []);
});


// ── 2. Map-group membership is what limits the options ───────────────────

test('maps from an unrelated group never become options', () => {
  const mixed = [
    ...TWO_FLOOR_ROOMS,
    room({ id: 'x1', mapId: 'annex-map', mapGroupId: 'grp-annex', floor: 0 }),
    room({ id: 'x2', mapId: 'annex-map-2', mapGroupId: 'grp-annex', floor: 1 }),
  ];

  const options = resolveFloorOptions(mixed, START_ALPHA);

  assert.deepEqual(options.map((o) => o.mapId), ['map-g', 'map-1']);
  assert.ok(!options.some((o) => o.mapId.startsWith('annex')));
});

test('every map in the relevant group is included', () => {
  const options = resolveFloorOptions(TWO_FLOOR_ROOMS, START_ALPHA);
  assert.deepEqual(new Set(options.map((o) => o.mapId)), new Set(['map-g', 'map-1']));
});

test('an ungrouped start map relates only to itself', () => {
  const rooms = [
    room({ id: 'a', mapId: 'lone-map', mapGroupId: null, floor: 0 }),
    room({ id: 'b', mapId: 'other-map', mapGroupId: null, floor: 3 }),
  ];

  const options = resolveFloorOptions(rooms, { mapId: 'lone-map', mapGroupId: null });

  assert.equal(options.length, 1);
  assert.equal(options[0].mapId, 'lone-map');
});

test('with no resolved start, nothing is narrowed away', () => {
  const options = resolveFloorOptions(TWO_FLOOR_ROOMS, null);
  assert.equal(options.length, 2);

  assert.equal(isInRelatedScope(TWO_FLOOR_ROOMS[0], null), true);
  assert.equal(isInRelatedScope(TWO_FLOOR_ROOMS[0], {}), true);
});

test('a destination with no map placement contributes no floor option', () => {
  const rooms = [
    ...TWO_FLOOR_ROOMS,
    room({ id: 'manual', mapId: null, mapGroupId: null, floor: null }),
  ];

  assert.equal(resolveFloorOptions(rooms, START_ALPHA).length, 2);
  // ...but it is still listed under All.
  assert.equal(filterRoomsByFloor(rooms, ALL_FLOORS).length, 4);
});


// ── 3. Real labels, not a normalized G/1/2/3 ─────────────────────────────

test('labels come from the real floor value via the shared helper', () => {
  const options = resolveFloorOptions(SEVEN_FLOOR_ROOMS, { mapGroupId: 'grp-tower' });

  assert.deepEqual(options.map((o) => o.label), [
    'B2',
    'B1',
    'Ground Floor',
    'Floor 1',
    'Floor 2',
    'Floor 3',
    'Floor 4',
  ]);
});

test('a custom floor label is preserved verbatim, not renumbered', () => {
  const rooms = [
    { ...room({ id: 'm', mapId: 'mez-map', floor: 1 }), floorLabel: 'Mezzanine' },
    { ...room({ id: 'l', mapId: 'lob-map', floor: 0 }), floorLabel: 'Lobby Level' },
  ];

  const options = resolveFloorOptions(rooms, { mapGroupId: 'grp-alpha' });

  assert.deepEqual(options.map((o) => o.label), ['Lobby Level', 'Mezzanine']);
});

test('the floor the user is standing on is marked, not preselected', () => {
  const options = resolveFloorOptions(TWO_FLOOR_ROOMS, START_ALPHA);

  assert.deepEqual(options.map((o) => o.isCurrent), [true, false]);
  // The default selection is still All — no destination is hidden on
  // arrival just because it is on another floor.
  assert.equal(ALL_FLOORS, null);
});


// ── 4. Filtering, and filtering together with search ─────────────────────

test('All shows every destination; a floor shows only that map', () => {
  assert.equal(filterRoomsByFloor(TWO_FLOOR_ROOMS, ALL_FLOORS).length, 3);
  assert.deepEqual(
    filterRoomsByFloor(TWO_FLOOR_ROOMS, 'map-g').map((r) => r.id),
    ['r1', 'r2'],
  );
  assert.deepEqual(
    filterRoomsByFloor(TWO_FLOOR_ROOMS, 'map-1').map((r) => r.id),
    ['r3'],
  );
});

test('floor filter and search compose', () => {
  const rooms = [
    room({ id: 'a', mapId: 'map-g', floor: 0, name: 'Testing Lab' }),
    room({ id: 'b', mapId: 'map-g', floor: 0, name: 'Cloakroom' }),
    room({ id: 'c', mapId: 'map-1', floor: 1, name: 'Testing Lab' }),
  ];

  const onFloor = filterRoomsByFloor(rooms, 'map-1');
  const searched = onFloor.filter((r) =>
    r.name.toLowerCase().includes('lab'),
  );

  assert.deepEqual(searched.map((r) => r.id), ['c']);
});

test('filtering never mutates or copies the room objects', () => {
  const rooms = [...TWO_FLOOR_ROOMS];
  const before = JSON.stringify(rooms);

  const result = filterRoomsByFloor(rooms, 'map-g');

  assert.equal(JSON.stringify(rooms), before);
  assert.equal(result[0], rooms[0], 'the same object identity is returned');
});

test('a selection that no longer exists falls back to All', () => {
  const options = resolveFloorOptions(TWO_FLOOR_ROOMS, START_ALPHA);

  assert.equal(reconcileFloorSelection('map-1', options), 'map-1');
  assert.equal(reconcileFloorSelection('map-that-went-away', options), ALL_FLOORS);
  assert.equal(reconcileFloorSelection(ALL_FLOORS, options), ALL_FLOORS);
});


// ── 5. Nothing about any specific building is written down ───────────────

test('no floor list, floor count or building name is hard-coded', () => {
  for (const source of [helperCode, screenCode]) {
    // A literal floor-option array.
    assert.doesNotMatch(source, /\[\s*['"]G['"]\s*,/);
    assert.doesNotMatch(source, /['"]Ground Floor['"]/);
    assert.doesNotMatch(source, /['"]Floor\s*\d['"]/);
    assert.doesNotMatch(source, /FLOOR_OPTIONS|DEFAULT_FLOORS|FLOOR_LABELS/);
  }
});

test('the screen names no building, campus or room', () => {
  assert.doesNotMatch(screenCode, /מכללה/);
  assert.doesNotMatch(screenCode, /Control Room/i);
  assert.doesNotMatch(screenCode, /DEFAULT_BUILDING|SAMPLE_ROOMS|MOCK_/);

  // The only Hebrew/Arabic literals in the screen are the UI dictionary
  // and the language selector's own endonyms. Anything else would be a
  // building, floor or destination name written into the frontend.
  const uiBlock = screenCode.slice(
    screenCode.indexOf('const UI = {'),
    screenCode.indexOf('// ── Screen'),
  );
  const languagesBlock = screenCode.slice(
    screenCode.indexOf('const LANGUAGES = ['),
    screenCode.indexOf('];', screenCode.indexOf('const LANGUAGES = [')),
  );

  const outside = screenCode.replace(uiBlock, '').replace(languagesBlock, '');

  assert.ok(!/[֐-ۿ]/.test(outside), 'translated text outside the UI dictionary');
});

test('the screen derives its options from the helper, not from a constant', () => {
  assert.match(screenCode, /resolveFloorOptions\(\s*localizedRooms\s*,\s*startContext\s*\)/);
  assert.match(screenCode, /filterRoomsByFloor\(\s*localizedRooms\s*,\s*activeFloorMapId\s*\)/);
  assert.match(screenCode, /shouldShowFloorFilter\(floorOptions\)/);
});

test('the map-group relationship comes from the resolved start location', () => {
  assert.match(screenCode, /persistedStart\?\.mapGroupId/);
  assert.match(screenCode, /persistedStart\?\.mapId/);
  // The helper scopes on the stored ids, and derives no relationship of
  // its own from coordinates, names or floor numbers.
  assert.match(helperCode, /startContext\?\.mapGroupId/);
  assert.match(helperCode, /startContext\?\.mapId/);
});


// ── 6. Back, and the removed building step ───────────────────────────────

test('Back navigates to the location-code entry route', () => {
  assert.match(screenCode, /navigate\(ROUTES\.start\)/);
});

test('Back never targets the building picker or browser history', () => {
  assert.doesNotMatch(screenCode, /ROUTES\.buildings/);
  assert.doesNotMatch(screenCode, /history\.back|navigate\(\s*-1\s*\)/);
});

test('the Back control shows only the plain back label', () => {
  const backBlock = screenCode.slice(
    screenCode.indexOf('<BackButton'),
    screenCode.indexOf('/>', screenCode.indexOf('<BackButton')) + 2,
  );

  assert.match(backBlock, /label=\{t\.back\}/);
  // No second line, subtitle or composed sentence.
  assert.doesNotMatch(backBlock, /subtitle|hint|חזרה לעמוד/);
  for (const dict of ['en', 'ar', 'he']) {
    assert.ok(dict);
  }
  assert.doesNotMatch(screenCode, /חזרה לעמוד הסריקה/);
});


// ── 7. Direction, one search container, one language state ───────────────

test('RTL is still driven by the shared lang value', () => {
  assert.match(screenCode, /const isRTL\s*=\s*lang === 'ar' \|\| lang === 'he'/);
  assert.match(screenCode, /dir=\{isRTL \? 'rtl' : 'ltr'\}/);
  assert.match(screenCode, /isRTL=\{isRTL\}/);
});

test('the language selector reuses LangContext and adds no second state', () => {
  assert.match(screenCode, /const \{ lang, setLang \}\s*=\s*useLang\(\)/);
  assert.match(screenCode, /setLang\(l\.code\)/);
  // No local language state of its own.
  assert.doesNotMatch(screenCode, /useState\([^)]*lang/i);

  for (const code of ['en', 'he', 'ar']) {
    assert.match(screenCode, new RegExp(`code: '${code}'`));
  }
});

test('the search bar has exactly one container', () => {
  assert.doesNotMatch(screenCode, /s17-search-wrap/);
  assert.match(screenCode, /className="s17-searchbar"/);

  const css = read('../styles/DestinationSelectionScreen.css');
  assert.ok(!css.includes('s17-search-wrap'), 'the outer search wrapper CSS survived');
  // The one remaining wrapper is layout-only: no border, no background of
  // its own, so nothing paints a second rectangle around the input.
  const block = css.slice(css.indexOf('.s17-searchbar {'), css.indexOf('}', css.indexOf('.s17-searchbar {')));
  assert.doesNotMatch(block, /border:|background:/);
});

test('the empty square is gone and a real location icon took its place', () => {
  assert.doesNotMatch(screenCode, /s17-building-icon|s17-building-tag|building\.tag/);
  assert.match(screenCode, /s17-identity-icon/);
  assert.match(screenCode, /<PinIcon/);
});

test('the duplicated building subtitle is gone', () => {
  assert.doesNotMatch(screenCode, /s17-building-en|building\.nameEn\}/);
  // The building name is rendered exactly once.
  assert.equal((screenCode.match(/\{buildingName\}/g) || []).length, 1);
});

test('the building name is resolved dynamically for the active language', () => {
  assert.match(
    screenCode,
    /getLocalizedText\(building\.names, lang, building\.name \|\| building\.nameEn\)/,
  );
});


// ── 8. The destination click flow is untouched ───────────────────────────

test('choosing a destination still hands off to navigation unchanged', () => {
  assert.match(
    screenCode,
    /navigate\(ROUTES\.navigation, \{ state: \{ building, destination: room, lang \} \}\)/,
  );
  assert.match(screenCode, /if \(!room\.isNavigable\) return;/);
});

test('the rooms request is still coalesced and abortable', () => {
  assert.match(screenCode, /roomsRequestRef/);
  assert.match(screenCode, /new AbortController\(\)/);
  assert.match(screenCode, /getRooms\(/);

  // No new endpoint was introduced for maps or map groups.
  assert.doesNotMatch(screenCode, /getMapGroups|getMaps\(/);
});

test('the helper performs no I/O of any kind', () => {
  assert.doesNotMatch(helperCode, /fetch\(|apiRequest|axios|localStorage|import\s+.*Api/);
});


console.log(`\n${passed} assertions passed.`);
