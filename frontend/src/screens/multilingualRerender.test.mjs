// Tests for "language changes must immediately rerender dynamic content
// with NO duplicate records, NO MongoDB edits, NO Claude re-run, and NO
// manual browser refresh" (multilingual content spec, Section 9).
//
// Two layers, matching this repo's existing conventions (no jest/
// testing-library installed — see screens/destinationNavigability.test.mjs):
//   1. Real unit tests proving utils/viewModels.js resolves a DIFFERENT
//      `.name` for the SAME already-fetched raw record purely as a
//      function of `lang` — this is exactly the property that makes a
//      `useMemo(() => ..., [rooms, lang])` recomputation correct and
//      refetch-free (no new network/DB call is needed to change the
//      displayed language).
//   2. Source-text contract tests confirming each screen actually wires
//      this up (useMemo keyed on `lang`, getLocalizedText imported and
//      used, RTL direction still driven by `lang`), and never displays a
//      raw technical id (routePointId/semanticEntityExternalId) as a name.

import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { roomToViewModel, buildingToViewModel } from '../utils/viewModels.js';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

function readScreen(filename) {
  return fs.readFileSync(path.join(__dirname, filename), 'utf8');
}

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

const rawRoom = {
  id: 'room-ml-1',
  name_en: 'Al Shifaa Pharmacy',
  names: { ar: 'صيدلية الشفاء', he: 'בית מרקחת אלשפאא', en: 'Al Shifaa Pharmacy' },
  room_type: 'pharmacy',
  is_active: true,
  is_navigable: true,
};

const rawBuilding = {
  id: 'bld-ml-1',
  name_en: 'Main Tower',
  name_local: 'Legacy Local Name',
  names: { ar: 'البرج الرئيسي', he: 'המגדל הראשי', en: 'Main Tower' },
  is_active: true,
};

// ── 1. roomToViewModel resolves a different .name purely from `lang` ──

test('roomToViewModel: the SAME raw record resolves a different .name purely as a function of lang', () => {
  const en = roomToViewModel(rawRoom, 'en');
  const ar = roomToViewModel(rawRoom, 'ar');
  const he = roomToViewModel(rawRoom, 'he');

  assert.equal(en.name, 'Al Shifaa Pharmacy');
  assert.equal(ar.name, 'صيدلية الشفاء');
  assert.equal(he.name, 'בית מרקחת אלשפאא');

  // No fetch/DB call happened here at all — this proves a component can
  // switch languages with a pure in-memory recomputation over data it
  // already has, exactly what a `useMemo(..., [rooms, lang])` does.
  assert.deepEqual(en.names, rawRoom.names);
  assert.deepEqual(ar.names, rawRoom.names);
});

// ── 2. buildingToViewModel: same property for buildings ────────────────

test('buildingToViewModel: the SAME raw record resolves a different .name purely as a function of lang', () => {
  const en = buildingToViewModel(rawBuilding, 'en');
  const ar = buildingToViewModel(rawBuilding, 'ar');
  const he = buildingToViewModel(rawBuilding, 'he');

  assert.equal(en.name, 'Main Tower');
  assert.equal(ar.name, 'البرج الرئيسي');
  assert.equal(he.name, 'המגדל הראשי');
});

// ── 3. a legacy record with no `names` at all keeps working unchanged ──

test('roomToViewModel/buildingToViewModel: a legacy record with no `names` falls back correctly for every lang', () => {
  const legacyRoom = { id: 'r2', name_en: 'Legacy Room', names: null, is_active: true };
  ['en', 'ar', 'he'].forEach((lang) => {
    assert.equal(roomToViewModel(legacyRoom, lang).name, 'Legacy Room');
  });

  const legacyBuilding = { id: 'b2', name_en: 'Legacy Bldg', name_local: 'Local Bldg', is_active: true };
  // No `names` field at all on this raw record (pre-migration shape).
  assert.equal(buildingToViewModel(legacyBuilding, 'ar').name, 'Local Bldg');
  assert.equal(buildingToViewModel(legacyBuilding, 'en').name, 'Local Bldg');
});

// ── 4. a technical id is never used as a displayed name ────────────────

test('roomToViewModel: never resolves the displayed name to a raw technical id', () => {
  const roomWithNoTranslationsAtAll = {
    id: 'room-technical',
    name_en: '',
    names: null,
    route_point_id: 'rp-abc123',
    semantic_entity_external_id: 'place_007',
    is_active: true,
  };
  const vm = roomToViewModel(roomWithNoTranslationsAtAll, 'ar');
  assert.notEqual(vm.name, 'rp-abc123');
  assert.notEqual(vm.name, 'place_007');
  // The technical ids are still exposed as their OWN separate fields for
  // internal use (e.g. navigation lookups) — just never surfaced as the
  // display name.
  assert.equal(vm.routePointId, 'rp-abc123');
  assert.equal(vm.semanticEntityExternalId, 'place_007');
});

// ── 5/6/7 — source-text contract: each screen wires up instant,
//            refetch-free rerendering on language change ──────────────

const SCREENS_WITH_LOCALIZED_LISTS = [
  'DestinationSelectionScreen.jsx',
  'BuildingSelectionScreen.jsx',
];

SCREENS_WITH_LOCALIZED_LISTS.forEach((filename) => {
  test(`${filename}: recomputes localized names via useMemo keyed on lang (no refetch)`, () => {
    const source = readScreen(filename);
    assert.match(source, /import\s*\{[^}]*getLocalizedText[^}]*\}\s*from\s*['"]\.\.\/utils\/localization['"]/);
    // The useMemo that resolves display names must depend on `lang` so a
    // language switch alone triggers recomputation.
    assert.match(source, /useMemo\(\s*\(\)\s*=>\s*[\s\S]*?\.map\(/);
    assert.match(source, /\[\s*\w+,\s*lang\s*\]\s*,?\s*\)/);
  });
});

test('IndoorNavigationScreen.jsx: room/building display names are memoized on [room/building, lang], not refetched', () => {
  const source = readScreen('IndoorNavigationScreen.jsx');
  assert.match(source, /import\s*\{\s*getLocalizedText\s*\}\s*from\s*['"]\.\.\/utils\/localization['"]/);
  assert.match(source, /roomDisplayName\s*=\s*useMemo\(/);
  assert.match(source, /buildingDisplayName\s*=\s*useMemo\(/);
  // The render must actually use the memoized display names, not the
  // raw (potentially stale-language) room.name/building.name directly.
  assert.match(source, /\{roomDisplayName\}/);
  assert.match(source, /\{buildingDisplayName\}/);
});

// ── 8. RTL direction is still correctly driven by `lang` on every
//       screen that got new localization wiring (regression guard) ────

['DestinationSelectionScreen.jsx', 'BuildingSelectionScreen.jsx', 'IndoorNavigationScreen.jsx'].forEach(
  (filename) => {
    test(`${filename}: RTL direction is still computed from lang === 'ar' || lang === 'he'`, () => {
      const source = readScreen(filename);
      assert.match(source, /isRTL\s*=\s*lang\s*===\s*'ar'\s*\|\|\s*lang\s*===\s*'he'/);
      assert.match(source, /dir=\{isRTL\s*\?\s*'rtl'\s*:\s*'ltr'\}/);
    });
  },
);

// ── 9. multilingual search never becomes a second competing search
//       system — every screen with search reuses matchesLocalizedSearch ──

test('DestinationSelectionScreen.jsx and BuildingSelectionScreen.jsx reuse the one shared matchesLocalizedSearch helper', () => {
  ['DestinationSelectionScreen.jsx', 'BuildingSelectionScreen.jsx'].forEach((filename) => {
    const source = readScreen(filename);
    assert.match(
      source,
      /import\s*\{[^}]*matchesLocalizedSearch[^}]*\}\s*from\s*['"]\.\.\/utils\/localization['"]/,
    );
    assert.match(source, /matchesLocalizedSearch\(/);
  });
});

console.log(`\n${passed} test(s) passed.`);
if (process.exitCode) {
  console.error('Some tests FAILED.');
} else {
  console.log('All tests passed.');
}
