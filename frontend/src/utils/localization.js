// Shared, single source of truth for resolving a piece of dynamic
// (database-sourced) multilingual content to display in the currently
// selected UI language. Every screen that shows a Destination/Room name,
// a semantic-map-analysis entity name, or a RoutePoint display name must
// go through this helper instead of re-implementing its own fallback
// chain — see the multilingual content spec ("Do not duplicate this
// fallback logic across screens").
//
// Mirrors the exact same fallback order as the backend's
// backend/schemas/localization_schema.get_localized_text(), so a name
// resolves identically whether the server or the client ends up doing
// the resolving.

// The exact, fixed set of supported UI languages — matches
// context/LangContext.jsx's supported `lang` values one-for-one.
export const SUPPORTED_LANGUAGES = ['ar', 'he', 'en'];

// Resolution order once the exact requested language has no usable
// value: English (broadest reach), then Arabic, then Hebrew.
const FALLBACK_LANGUAGE_ORDER = ['en', 'ar', 'he'];

function clean(value) {
  if (typeof value !== 'string') return '';
  const trimmed = value.trim();
  return trimmed || '';
}

/**
 * Resolves the single best string to display for `lang`, given a
 * (possibly undefined/null/partial) translations object plus an
 * optional legacy single-language fallback string.
 *
 * Safely handles every shape the multilingual content spec requires:
 *   - undefined / null translations object -> falls straight to fallback
 *   - a legacy plain string passed in place of an object -> ignored as
 *     "no translations" (never crashes), fallback is still used
 *   - partial translations (only some languages present)
 *   - empty-string / whitespace-only values (never treated as valid)
 *   - an unknown/unsupported `lang` value -> treated as "no exact
 *     match", falls through the same chain, never throws
 *
 * Fallback order (always applied in this exact order):
 *   1. translations[lang], if lang is supported and non-empty
 *   2. translations.en
 *   3. translations.ar
 *   4. translations.he
 *   5. `fallback`
 *   6. "" (empty string)
 */
export function getLocalizedText(translations, lang, fallback = '') {
  const data =
    translations && typeof translations === 'object' ? translations : {};

  if (SUPPORTED_LANGUAGES.includes(lang)) {
    const requested = clean(data[lang]);
    if (requested) return requested;
  }

  for (const fallbackLang of FALLBACK_LANGUAGE_ORDER) {
    const value = clean(data[fallbackLang]);
    if (value) return value;
  }

  return clean(fallback) || fallback || '';
}

/**
 * Normalizes any of {undefined, null, a plain object} into a
 * {ar, he, en} object with every key always present (empty string when
 * a language has no stored value) — handy for controlled <input> fields
 * in an editor UI (e.g. the semantic-analysis review screen's per-
 * language Correct fields) where React inputs must never receive
 * `undefined`/`null` as a value.
 */
export function normalizeLocalizedText(translations) {
  const data =
    translations && typeof translations === 'object' ? translations : {};
  return {
    ar: clean(data.ar),
    he: clean(data.he),
    en: clean(data.en),
  };
}

/**
 * True when `translations` has at least one non-empty language value —
 * useful for deciding whether to show a "no approved translations yet"
 * empty state versus a populated one.
 */
export function hasAnyLocalizedText(translations) {
  const data =
    translations && typeof translations === 'object' ? translations : {};
  return SUPPORTED_LANGUAGES.some((lang) => Boolean(clean(data[lang])));
}

/**
 * Multilingual, case-insensitive "does this record match the search
 * query in ANY stored language" check — used for client-side filtering
 * of an already-loaded list (Section 10: "a destination should be
 * findable using any stored translation"). Also checks the legacy
 * fallback name so records with no `names` object at all keep matching
 * exactly as they did before.
 */
export function matchesLocalizedSearch(translations, legacyName, query) {
  const normalizedQuery = clean(query).toLowerCase();
  if (!normalizedQuery) return true;

  const data =
    translations && typeof translations === 'object' ? translations : {};

  const candidates = [
    data.ar,
    data.he,
    data.en,
    legacyName,
  ];

  return candidates.some((candidate) => {
    const value = clean(candidate).toLowerCase();
    return value.includes(normalizedQuery);
  });
}
