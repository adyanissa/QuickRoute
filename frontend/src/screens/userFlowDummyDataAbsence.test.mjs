// Source-text contract tests — QuickRoute User Experience Final Cleanup,
// Part 10 items 7-11: dummy-data absence in the active normal-user
// screens. These assert against the ACTUAL screen source files, not a
// rendered DOM (this repo has no React/DOM test runner installed — see
// the other *.test.mjs files for the same established pattern).
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const screensDir = __dirname;

const readScreen = (name) => fs.readFileSync(path.join(screensDir, name), 'utf8');

const USER_SCREENS = [
  'BarcodeEntryScreen.jsx',
  'WelcomeScreen.jsx',
  'BuildingSelectionScreen.jsx',
  'DestinationSelectionScreen.jsx',
  'IndoorNavigationScreen.jsx',
];

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

// 7. "Rabin Medical Center" does not exist in any active normal-user
//    screen source.
test('Rabin Medical Center does not appear in any normal-user screen', () => {
  USER_SCREENS.forEach((name) => {
    const source = readScreen(name);
    assert.doesNotMatch(source, /Rabin/i, `${name} must not mention "Rabin"`);
  });
});

// 8. No normal-user screen imports the old dummy building dataset.
test('no normal-user screen imports data/hospitalData.js', () => {
  USER_SCREENS.forEach((name) => {
    const source = readScreen(name);
    assert.doesNotMatch(source, /hospitalData/, `${name} must not import hospitalData`);
  });
});

// 9. No normal-user screen imports the old dummy route dataset.
test('no normal-user screen imports data/routeData.js', () => {
  USER_SCREENS.forEach((name) => {
    const source = readScreen(name);
    assert.doesNotMatch(source, /\brouteData\b/, `${name} must not import routeData`);
  });
});

// 10. BuildingSelectionScreen never renders a fake fallback building list
//     on API failure — the error branch only ever sets an empty array +
//     an error string, never a hardcoded array of buildings.
test('BuildingSelectionScreen renders an empty/error state on API failure, never a fake building list', () => {
  const source = readScreen('BuildingSelectionScreen.jsx');
  assert.match(source, /setBuildings\(\[\]\)/);
  assert.doesNotMatch(source, /setBuildings\(\[\s*\{/); // never seeded with a literal object array
});

// 11. DestinationSelectionScreen never renders a fake fallback room list
//     on API failure — same pattern as above, for rooms.
test('DestinationSelectionScreen renders an empty/error state on API failure, never a fake room list', () => {
  const source = readScreen('DestinationSelectionScreen.jsx');
  assert.match(source, /setRooms\(\[\]\)/);
  assert.doesNotMatch(source, /setRooms\(\[\s*\{/);
});

// Extra — the "BUILDINGS" technical section heading is gone (Part 4/17),
// and the old count badge / hardcoded facility badge do not appear.
test('BuildingSelectionScreen has no "BUILDINGS" technical heading or hardcoded facility badge', () => {
  const source = readScreen('BuildingSelectionScreen.jsx');
  assert.doesNotMatch(source, /s16-section-row/);
  assert.doesNotMatch(source, /s16-location-badge/);
  assert.doesNotMatch(source, /Rabin/i);
});

console.log(`\n${passed} test(s) passed.`);
if (process.exitCode) {
  console.error('One or more tests FAILED.');
} else {
  console.log('All tests passed.');
}
