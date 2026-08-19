// The Destination Selection room-name fallback.
//
// The bug: a room with a real name_en but a null names.en was rendered in
// ARABIC while the UI language was English, because the shared
// getLocalizedText() walks ['en','ar','he'] before it ever looks at the
// legacy name_en it was handed. This pins the corrected order, and pins
// the shared helper as still doing the old thing — because that helper is
// used by four other screens and deliberately was not changed.
//
// Every fixture is synthetic.
//
// Run with: node frontend/src/utils/destinationDisplayName.test.mjs

import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { resolveDestinationName } from './destinationDisplayName.js';
import { getLocalizedText } from './localization.js';

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

// The exact real-data shape that produced the bug: English lives only in
// the legacy flat field, the translations exist.
const AR = 'مكتب X';
const HE = 'משרד X';

const BUGGY_SHAPE = {
  nameEn: 'Office X',
  names: { en: null, ar: AR, he: HE },
};


// ── 1. The reported case ─────────────────────────────────────────────────

test('names.en null + real name_en: EN shows the English name, not Arabic', () => {
  const { names, nameEn } = BUGGY_SHAPE;

  assert.equal(resolveDestinationName(names, 'en', nameEn), 'Office X');
});

test('the same record still shows Arabic in AR and Hebrew in HE', () => {
  const { names, nameEn } = BUGGY_SHAPE;

  assert.equal(resolveDestinationName(names, 'ar', nameEn), AR);
  assert.equal(resolveDestinationName(names, 'he', nameEn), HE);
});

test('this is a real regression — the shared helper still returns Arabic', () => {
  // Not a criticism of getLocalizedText: it is correct for records whose
  // `names` object is the whole truth. This asserts the bug is real, and
  // that the shared helper was left untouched for its other callers.
  const { names, nameEn } = BUGGY_SHAPE;

  assert.equal(getLocalizedText(names, 'en', nameEn), AR);
  assert.notEqual(
    resolveDestinationName(names, 'en', nameEn),
    getLocalizedText(names, 'en', nameEn),
  );
});


// ── 2. English never falls through to another script ─────────────────────

test('English never answers with Arabic or Hebrew', () => {
  const onlyRtl = { en: null, ar: AR, he: HE };

  // No English anywhere: the last resort is the caller's fallback or '',
  // never a script the reader may not read.
  assert.equal(resolveDestinationName(onlyRtl, 'en', ''), '');
  assert.equal(resolveDestinationName(onlyRtl, 'en', '', 'Destination'), 'Destination');
});

test('whitespace-only values count as missing, in every language', () => {
  const blank = { en: '   ', ar: '', he: '\t' };

  assert.equal(resolveDestinationName(blank, 'en', 'Office X'), 'Office X');
  assert.equal(resolveDestinationName(blank, 'ar', 'Office X'), 'Office X');
  assert.equal(resolveDestinationName(blank, 'he', 'Office X'), 'Office X');
});


// ── 3. A populated names.en still wins ───────────────────────────────────

test('names.en populated: EN uses names.en, not the legacy field', () => {
  const names = { en: 'Structured Office X', ar: AR, he: HE };

  assert.equal(
    resolveDestinationName(names, 'en', 'Legacy Office X'),
    'Structured Office X',
  );
});

test('a missing AR/HE falls back to names.en before the legacy field', () => {
  const names = { en: 'Structured Office X', ar: null, he: null };

  assert.equal(resolveDestinationName(names, 'ar', 'Legacy Office X'), 'Structured Office X');
  assert.equal(resolveDestinationName(names, 'he', 'Legacy Office X'), 'Structured Office X');
});

test('the requested language always wins when it has a value', () => {
  const names = { en: 'Structured Office X', ar: AR, he: HE };

  assert.equal(resolveDestinationName(names, 'ar', 'Legacy'), AR);
  assert.equal(resolveDestinationName(names, 'he', 'Legacy'), HE);
});


// ── 4. Code-only labels are unaffected ───────────────────────────────────

test('a preserved code-only label reads identically in all three languages', () => {
  // The translation backfill stores the source label verbatim for codes,
  // so every branch returns the same string.
  const names = { en: 'TEL 312', ar: 'TEL 312', he: 'TEL 312' };

  for (const lang of ['en', 'ar', 'he']) {
    assert.equal(resolveDestinationName(names, lang, 'TEL 312'), 'TEL 312');
  }
});

test('a legacy code-only room with no names object at all still renders', () => {
  for (const lang of ['en', 'ar', 'he']) {
    assert.equal(resolveDestinationName(null, lang, 'ELEC310'), 'ELEC310');
    assert.equal(resolveDestinationName(undefined, lang, 'ELEC310'), 'ELEC310');
    assert.equal(resolveDestinationName({}, lang, 'ELEC310'), 'ELEC310');
  }
});

test('an identifier inside a translated name survives untouched', () => {
  const names = { en: null, ar: 'مكتب 385', he: 'משרד 385' };

  assert.equal(resolveDestinationName(names, 'en', 'OFFICE 385'), 'OFFICE 385');
  assert.match(resolveDestinationName(names, 'ar', 'OFFICE 385'), /385/);
  assert.match(resolveDestinationName(names, 'he', 'OFFICE 385'), /385/);
});


// ── 5. Scope: nothing shared was changed ─────────────────────────────────

const read = (rel) => fs.readFileSync(path.join(__dirname, rel), 'utf8');

test('the shared localization helper keeps its original fallback order', () => {
  const shared = read('./localization.js');

  assert.match(shared, /FALLBACK_LANGUAGE_ORDER = \['en', 'ar', 'he'\]/);
});

test('only Destination Selection uses the new helper', () => {
  const roots = ['../screens', '../components', '../utils', '../context', '../api'];
  const users = [];

  for (const root of roots) {
    const dir = path.join(__dirname, root);
    if (!fs.existsSync(dir)) continue;

    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      if (!entry.isFile()) continue;
      if (!/\.(jsx?|mjs)$/.test(entry.name)) continue;
      if (entry.name.includes('.test.')) continue;
      if (entry.name === 'destinationDisplayName.js') continue;

      const source = fs.readFileSync(path.join(dir, entry.name), 'utf8');
      if (source.includes('destinationDisplayName')) users.push(entry.name);
    }
  }

  assert.deepEqual(users, ['DestinationSelectionScreen.jsx'], users.join(', '));
});

test('the destination list resolves names through the new helper', () => {
  const screen = read('../screens/DestinationSelectionScreen.jsx');

  assert.match(
    screen,
    /rooms\.map\(\(r\) => \(\{ \.\.\.r, name: resolveDestinationName\(r\.names, lang, r\.nameEn\) \}\)\)/,
  );
});

test('no room or floor value is hard-coded by the fix', () => {
  const helper = read('./destinationDisplayName.js');
  const screen = read('../screens/DestinationSelectionScreen.jsx');

  for (const source of [helper, screen]) {
    assert.doesNotMatch(source, /Floor\s*3/);
    assert.doesNotMatch(source, /OFFICE\s*385/);
  }

  // The helper carries no translated text of its own.
  assert.ok(!/[֐-ۿ]/.test(helper), 'the helper hard-codes translated text');
});


console.log(`\n${passed} assertions passed.`);
