// Tests for utils/localization.js — the single shared fallback chain for
// resolving dynamic (database-sourced) multilingual content, mirroring
// backend/schemas/localization_schema.get_localized_text() exactly so a
// name resolves identically no matter which side does the resolving.
//
// Same plain-node convention as the rest of this repo's utils/*.test.mjs
// (no jest/testing-library installed) — see utils/mapAnalysisHelpers.test.mjs.

import assert from 'node:assert/strict';
import {
  SUPPORTED_LANGUAGES,
  getLocalizedText,
  normalizeLocalizedText,
  hasAnyLocalizedText,
  matchesLocalizedSearch,
} from './localization.js';

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

// ── 1. exact requested language wins when present ──────────────────────

test('getLocalizedText: returns the exact requested language when present', () => {
  const names = { ar: 'صيدلية الشفاء', he: 'בית מרקחת אלשפאא', en: 'Al Shifaa Pharmacy' };
  assert.equal(getLocalizedText(names, 'ar'), 'صيدلية الشفاء');
  assert.equal(getLocalizedText(names, 'he'), 'בית מרקחת אלשפאא');
  assert.equal(getLocalizedText(names, 'en'), 'Al Shifaa Pharmacy');
});

// ── 2. exact fallback order: requested -> en -> ar -> he -> fallback -> '' ──

test('getLocalizedText: falls through en -> ar -> he -> fallback -> "" in order', () => {
  assert.equal(getLocalizedText({ en: 'English Name' }, 'ar'), 'English Name');
  assert.equal(getLocalizedText({ ar: 'Arabic Only' }, 'he'), 'Arabic Only');
  assert.equal(getLocalizedText({ he: 'Hebrew Only' }, 'ar'), 'Hebrew Only');
  assert.equal(getLocalizedText({}, 'ar', 'Legacy Name'), 'Legacy Name');
  assert.equal(getLocalizedText({}, 'ar'), '');
});

// ── 3. undefined/null translations object -> falls straight to fallback ──

test('getLocalizedText: undefined/null translations object falls straight to fallback', () => {
  assert.equal(getLocalizedText(undefined, 'en', 'Legacy'), 'Legacy');
  assert.equal(getLocalizedText(null, 'ar', 'Legacy'), 'Legacy');
  assert.equal(getLocalizedText(undefined, 'en'), '');
});

// ── 4. a legacy plain string passed in place of an object never crashes ──

test('getLocalizedText: a legacy plain string in place of an object is ignored, never crashes', () => {
  // Some legacy call sites may still pass a bare string where an object
  // is expected — this must be treated as "no translations" rather than
  // throwing (e.g. 'x'[lang] would silently return undefined, not throw,
  // but this proves the function never assumes an object shape).
  assert.equal(getLocalizedText('Just A String', 'en', 'Fallback'), 'Fallback');
  assert.equal(getLocalizedText(42, 'en', 'Fallback'), 'Fallback');
});

// ── 5. partial translations (only some languages present) ──────────────

test('getLocalizedText: partial translations resolve correctly for every requested language', () => {
  const partial = { en: 'English Only' };
  assert.equal(getLocalizedText(partial, 'en'), 'English Only');
  assert.equal(getLocalizedText(partial, 'ar'), 'English Only'); // falls to en
  assert.equal(getLocalizedText(partial, 'he'), 'English Only'); // falls to en
});

// ── 6. empty-string/whitespace-only values are never treated as valid ──

test('getLocalizedText: empty-string and whitespace-only values are never valid', () => {
  assert.equal(getLocalizedText({ ar: '', en: 'Real Name' }, 'ar'), 'Real Name');
  assert.equal(getLocalizedText({ ar: '   ', en: 'Real Name' }, 'ar'), 'Real Name');
  assert.equal(getLocalizedText({ ar: '   ' }, 'ar', 'Legacy'), 'Legacy');
});

// ── 7. an unknown/unsupported `lang` value never throws ────────────────

test('getLocalizedText: an unknown/unsupported lang value falls through safely, never throws', () => {
  const names = { en: 'English Name' };
  assert.equal(getLocalizedText(names, 'fr'), 'English Name');
  assert.equal(getLocalizedText(names, ''), 'English Name');
  assert.equal(getLocalizedText(names, null), 'English Name');
  assert.equal(getLocalizedText(names, undefined), 'English Name');
  assert.doesNotThrow(() => getLocalizedText(names, '__proto__'));
});

// ── 8. normalizeLocalizedText: always {ar,he,en}, safe for <input> values ──

test('normalizeLocalizedText: always returns all three keys, "" for anything missing', () => {
  assert.deepEqual(normalizeLocalizedText(undefined), { ar: '', he: '', en: '' });
  assert.deepEqual(normalizeLocalizedText({ en: 'Only English' }), {
    ar: '',
    he: '',
    en: 'Only English',
  });
  // Never returns null/undefined for a React controlled <input> value.
  const normalized = normalizeLocalizedText(null);
  Object.values(normalized).forEach((v) => assert.equal(typeof v, 'string'));
});

// ── 9. hasAnyLocalizedText ───────────────────────────────────────────────

test('hasAnyLocalizedText: true iff at least one language has a real value', () => {
  assert.equal(hasAnyLocalizedText(null), false);
  assert.equal(hasAnyLocalizedText({}), false);
  assert.equal(hasAnyLocalizedText({ ar: '   ' }), false);
  assert.equal(hasAnyLocalizedText({ he: 'בית מרקחת' }), true);
});

// ── 10. matchesLocalizedSearch: findable by ANY stored language ────────

test('matchesLocalizedSearch: a record is findable by any stored translation, case-insensitively', () => {
  const names = { ar: 'صيدلية الشفاء', he: 'בית מרקחת אלשפאא', en: 'Al Shifaa Pharmacy' };
  assert.equal(matchesLocalizedSearch(names, null, 'شفاء'), true);
  assert.equal(matchesLocalizedSearch(names, null, 'shifaa'), true);
  assert.equal(matchesLocalizedSearch(names, null, 'SHIFAA'), true);
  assert.equal(matchesLocalizedSearch(names, null, 'unrelated query'), false);
  // Legacy records with no `names` object at all still match on the
  // legacy fallback name, exactly as they did before.
  assert.equal(matchesLocalizedSearch(null, 'Legacy Pharmacy', 'legacy'), true);
  // An empty query always matches everything (never filters out
  // everything just because search hasn't been typed yet).
  assert.equal(matchesLocalizedSearch(names, null, ''), true);
  assert.equal(matchesLocalizedSearch(names, null, '   '), true);
});

test('SUPPORTED_LANGUAGES matches the exact three-language contract', () => {
  assert.deepEqual([...SUPPORTED_LANGUAGES].sort(), ['ar', 'en', 'he']);
});

console.log(`\n${passed} test(s) passed.`);
if (process.exitCode) {
  console.error('Some tests FAILED.');
} else {
  console.log('All tests passed.');
}
