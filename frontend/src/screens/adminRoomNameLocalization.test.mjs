// The Admin "Rooms & Destinations" screen rendered every room-card title
// as `r.name`, which AdminContext's own roomToViewModel fills from
// `name_en` — so the list stayed English even with the UI in Hebrew or
// Arabic, while DestinationSelectionScreen (which resolves through
// utils/localization.js) showed the translated name correctly.
//
// The subtle part is WHY the fix is one expression at the render site and
// not a change to the view model: on this screen `r.name` is not a display
// value at all. openEdit() loads it straight into the "Room Name (EN)"
// input, and AdminContext's roomToApiPayload sends it back as BOTH
// `name_en` and `names.en`. Localizing `r.name` itself would therefore
// write the Hebrew string into the English field on the next save — silent
// data corruption that no visual check would catch until the English name
// was already gone.
//
// So these tests pin down both halves:
//   1. the DISPLAYED title resolves per language, with the project's
//      existing fallback chain intact, and
//   2. the EDIT path still reads and writes the raw English value,
//      untouched by any of this.
//
// Two layers, matching this repo's conventions (no jest/testing-library —
// see screens/multilingualRerender.test.mjs):
//   * real unit tests of the shared helper against real-shaped records
//   * source-text contract tests that the screen is actually wired that
//     way, and that the edit/payload path was not disturbed.
//
// Run with: node frontend/src/screens/adminRoomNameLocalization.test.mjs

import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { getLocalizedText } from '../utils/localization.js';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

const read = (relative) =>
  fs.readFileSync(path.join(__dirname, relative), 'utf8');

// Assertions about the ABSENCE of a token must not be defeated by the word
// appearing in an explanatory comment.
const stripComments = (source) =>
  source
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/\{\/\*[\s\S]*?\*\/\}/g, '')
    .replace(/^\s*\/\/.*$/gm, '');

const adminRoomsSource = read('./AdminRoomsScreen.jsx');
const adminRoomsCode = stripComments(adminRoomsSource);
const adminContextCode = stripComments(read('./../context/AdminContext.jsx'));

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

// The exact shape AdminContext's roomToViewModel produces: `name` is the
// legacy English value, `names` is the raw translations object.
const translatedRoom = {
  id: 'room-adm-1',
  name: 'Office 417',
  names: { en: 'Office 417', ar: 'مكتب 417', he: 'משרד 417' },
  nameAr: 'مكتب 417',
  nameHe: 'משרד 417',
};

const partiallyTranslatedRoom = {
  id: 'room-adm-2',
  name: 'Director Office 422',
  names: { en: 'Director Office 422', ar: null, he: 'משרד מנהל 422' },
  nameAr: '',
  nameHe: 'משרד מנהל 422',
};

// A room that predates the multilingual field entirely.
const legacyRoom = {
  id: 'room-adm-3',
  name: 'Graduate Students Room 450',
  names: null,
  nameAr: '',
  nameHe: '',
};


// ── 1. The displayed title resolves per language ─────────────────────────

test('the card title resolves to the room name in the active UI language', () => {
  assert.equal(getLocalizedText(translatedRoom.names, 'en', translatedRoom.name), 'Office 417');
  assert.equal(getLocalizedText(translatedRoom.names, 'he', translatedRoom.name), 'משרד 417');
  assert.equal(getLocalizedText(translatedRoom.names, 'ar', translatedRoom.name), 'مكتب 417');
});

test('room numbers and identifiers survive the resolution untouched', () => {
  for (const lang of ['en', 'he', 'ar']) {
    const title = getLocalizedText(translatedRoom.names, lang, translatedRoom.name);
    assert.match(title, /417/, `"${title}" lost its room number in ${lang}`);
  }
});


// ── 2. Fallback behavior is preserved exactly ────────────────────────────

test('a language with no stored translation falls back, never renders blank', () => {
  // Arabic is genuinely missing here — the existing chain falls to English.
  assert.equal(
    getLocalizedText(partiallyTranslatedRoom.names, 'ar', partiallyTranslatedRoom.name),
    'Director Office 422',
  );
  // Hebrew exists and wins.
  assert.equal(
    getLocalizedText(partiallyTranslatedRoom.names, 'he', partiallyTranslatedRoom.name),
    'משרד מנהל 422',
  );
});

test('a legacy room with no `names` object at all renders exactly as it does today', () => {
  for (const lang of ['en', 'ar', 'he']) {
    assert.equal(
      getLocalizedText(legacyRoom.names, lang, legacyRoom.name),
      'Graduate Students Room 450',
    );
  }
});

test('an empty-string or whitespace-only translation is never displayed', () => {
  const blank = { en: 'Storage', ar: '', he: '   ' };
  assert.equal(getLocalizedText(blank, 'ar', 'Storage'), 'Storage');
  assert.equal(getLocalizedText(blank, 'he', 'Storage'), 'Storage');
});


// ── 3. The screen is actually wired to the shared helper ─────────────────

test('AdminRoomsScreen imports the shared localization helper', () => {
  assert.match(
    adminRoomsCode,
    /import\s*\{\s*getLocalizedText\s*\}\s*from\s*'\.\.\/utils\/localization'/,
    'the screen must use the project helper, not its own resolver',
  );
});

test('the room-card title is rendered through getLocalizedText', () => {
  const titleBlock = adminRoomsCode.match(
    /className="adm-list-item-name"[^]*?<\/div>/,
  );

  assert.ok(titleBlock, 'the room-card title element was not found');
  assert.match(
    titleBlock[0],
    /getLocalizedText\(\s*r\.names\s*,\s*lang\s*,\s*r\.name\s*\)/,
    'the title must resolve names/lang with the legacy name as fallback',
  );
});

test('the card title is no longer the bare legacy name', () => {
  assert.doesNotMatch(
    adminRoomsCode,
    /className="adm-list-item-name">\{r\.name\}/,
    'the card title still renders the raw English value',
  );
});

test('the screen introduces no translation dictionary of its own', () => {
  // Every Arabic/Hebrew literal in this file belongs to the static UI
  // chrome (the `UI` object's labels), never to a room name. The room
  // names arrive only from the API, via `r.names`.
  assert.doesNotMatch(adminRoomsCode, /Office\s*4\d\d/, 'a room name is hard-coded');
  assert.doesNotMatch(adminRoomsCode, /roomNameTranslations|ROOM_NAME_MAP/);
});


// ── 4. The edit path is untouched ────────────────────────────────────────

test('the "Room Name (EN)" input still binds to the raw English value', () => {
  assert.match(
    adminRoomsCode,
    /value=\{form\.name \|\| ''\}/,
    'the EN input must keep showing the stored English name, not a translation',
  );
  // And it must NOT have been localized — that would make the field
  // display Hebrew and then save Hebrew into name_en.
  assert.doesNotMatch(
    adminRoomsCode,
    /value=\{getLocalizedText/,
    'an edit input was localized — this would corrupt the stored name',
  );
});

test('the AR and HE inputs still bind to their own fields', () => {
  assert.match(adminRoomsCode, /value=\{form\.nameAr \|\| ''\}/);
  assert.match(adminRoomsCode, /value=\{form\.nameHe \|\| ''\}/);
  assert.match(adminRoomsCode, /setField\('nameAr'/);
  assert.match(adminRoomsCode, /setField\('nameHe'/);
});

test('openEdit still loads the untouched view model into the form', () => {
  const openEdit = adminRoomsCode.match(/const openEdit = \(r\) => \{[^]*?\n  \};/);

  assert.ok(openEdit, 'openEdit was not found');
  assert.match(
    openEdit[0],
    /setForm\(\{ \.\.\.EMPTY_ROOM, \.\.\.r \}\)/,
    'the edit form must still receive the raw record',
  );
  assert.doesNotMatch(
    openEdit[0],
    /getLocalizedText/,
    'the edit form must never be populated from a resolved display name',
  );
});


// ── 5. The save payload is untouched ─────────────────────────────────────

test('AdminContext still sends the raw English value as name_en', () => {
  assert.match(
    adminContextCode,
    /name_en:\s*r\.name/,
    'the create/update payload changed — English would no longer round-trip',
  );
});

test('AdminContext still sends all three languages from their own fields', () => {
  assert.match(
    adminContextCode,
    /names:\s*\{\s*en:\s*r\.name \|\| null,\s*ar:\s*r\.nameAr \|\| null,\s*he:\s*r\.nameHe \|\| null\s*\}/,
  );
});

test('AdminContext view model still exposes `name` as the English value', () => {
  const viewModel = adminContextCode.match(
    /const roomToViewModel = \(r\) => \(\{[^]*?\n\}\);/,
  );

  assert.ok(viewModel, 'roomToViewModel was not found');
  assert.match(
    viewModel[0],
    /name:\s*r\.name_en \|\| '',/,
    'the view model must keep `name` as the editable English value',
  );
  assert.match(viewModel[0], /names:\s*r\.names \|\| null,/);
  assert.doesNotMatch(
    viewModel[0],
    /getLocalizedText/,
    'localizing the view model would corrupt the edit/save round trip',
  );
});


console.log(`\n${passed} assertions passed.`);
