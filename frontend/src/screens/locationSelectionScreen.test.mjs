// Source-text contract tests — QuickRoute User Experience Final Cleanup,
// Part 10 items 17-21 (redesigned Location Selection screen, Part 4).
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const source = fs.readFileSync(path.join(__dirname, 'BuildingSelectionScreen.jsx'), 'utf8');

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

// 17. No "BUILDINGS" technical heading is rendered.
test('no "BUILDINGS" technical section heading exists', () => {
  assert.doesNotMatch(source, /section:\s*'Buildings'/);
  assert.doesNotMatch(source, /s16-section-label/);
  assert.doesNotMatch(source, /s16-section-row/);
});

// 18. Real API buildings render as professional cards, in a grid list —
//     via the shared DestinationCard component, not a plain database row.
test('buildings render via DestinationCard in a grid-capable list', () => {
  assert.match(source, /<DestinationCard/);
  assert.match(source, /variant="building"/);
  assert.match(source, /className="s16-list"/);
});

// 19. An empty API response renders the honest empty state — never
//     synthesized placeholder cards.
test('an empty buildings list renders the "no locations available yet" empty state, not fake cards', () => {
  assert.match(source, /noDataTitle:\s*'No locations are available yet'/);
  assert.match(source, /noDataDesc:\s*'Ask an administrator to configure a building and its destinations\.'/);
  assert.match(source, /buildings\.length === 0/);
});

// 20. Search filters the real loaded records (findable by any stored
//     translation via the shared matchesLocalizedSearch helper, plus tag
//     and campus when available) — never a separate hardcoded list, and
//     never a second competing search implementation (multilingual
//     content spec, Section 10).
test('search filters the real loaded buildings array, including by campus', () => {
  assert.match(source, /localizedBuildings\.filter\(/);
  assert.match(source, /matchesLocalizedSearch\(/);
  assert.match(source, /b\.campus/);
});

// 21. Loading renders a distinct skeleton state — never simultaneously
//     shown alongside the old list or the empty placeholder.
test('loading renders skeleton cards, mutually exclusive with the empty/list branches', () => {
  assert.match(source, /s16-skeleton-list/);
  assert.match(source, /loading \? \(/);
});

// Inactive buildings (is_active === false) are filtered out client-side,
// since the backend does not filter them server-side (Part 3 rule 4's
// "never display inactive" spirit extended to buildings).
test('inactive buildings are filtered out after fetch', () => {
  assert.match(source, /filter\(\(b\) => b\.isActive !== false\)/);
});

console.log(`\n${passed} test(s) passed.`);
if (process.exitCode) {
  console.error('One or more tests FAILED.');
} else {
  console.log('All tests passed.');
}
