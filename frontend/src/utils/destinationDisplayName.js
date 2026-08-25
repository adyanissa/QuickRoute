// The name a destination shows on the Destination Selection screen.
//
// WHY THIS EXISTS SEPARATELY FROM utils/localization.js
// -----------------------------------------------------
// The shared getLocalizedText() resolves a missing language through
// FALLBACK_LANGUAGE_ORDER = ['en', 'ar', 'he'] and only reaches its
// `fallback` argument after all three have been tried. That is correct for
// records whose `names` object is the single source of truth.
//
// Real Room records are not always that shape. A room can carry:
//
//     name_en:  "<a real English name>"
//     names.en: null                 <- never populated
//     names.ar: "<a real Arabic name>"
//     names.he: "<a real Hebrew name>"
//
// Asking the shared helper for English there walks past the empty
// names.en, finds names.ar, and returns Arabic — so an English-speaking
// user reads an Arabic room name. The English name was available the
// whole time, one field away, in name_en.
//
// The fix belongs here rather than in the shared helper: getLocalizedText
// is used by the building selector, the admin rooms screen, the
// navigation screen and the map-analysis helpers, and changing its
// fallback order would silently change what all of them display. This
// module is imported by DestinationSelectionScreen and nothing else.
//
// THE RULE
// --------
//   English  ->  names.en          -> name_en -> fallback
//   Arabic   ->  names.ar -> names.en -> name_en -> fallback
//   Hebrew   ->  names.he -> names.en -> name_en -> fallback
//
// English never falls through to Arabic or Hebrew: showing a name in a
// script the reader may not read is worse than showing the legacy English
// one, which is what the room is actually labelled in the building.
//
// A room whose only name is an architectural code is unaffected
// by construction — every branch returns that same string.

// The one language that is a legitimate intermediate fallback, because it
// is the source language every other value was translated from.
const SOURCE_LANGUAGE = 'en';

const clean = (value) =>
  typeof value === 'string' && value.trim() ? value.trim() : '';

/**
 * @param {?object} names    the room's raw translations object
 * @param {string}  lang     the active UI language
 * @param {string}  nameEn   the room's legacy flat English name
 * @param {string}  fallback last-resort value (defaults to '')
 * @returns {string}
 */
export function resolveDestinationName(names, lang, nameEn, fallback = '') {
  const data = names && typeof names === 'object' ? names : {};

  // 1. The requested language, when it actually holds something.
  const requested = clean(data[lang]);
  if (requested) return requested;

  // 2. English as the source language — but only for a NON-English
  //    request. An English request that got here has already found
  //    names.en empty, and must not be answered with another language.
  if (lang !== SOURCE_LANGUAGE) {
    const source = clean(data[SOURCE_LANGUAGE]);
    if (source) return source;
  }

  // 3. The legacy flat English field. This is the step the shared helper
  //    reaches too late, and the whole reason this module exists.
  const legacy = clean(nameEn);
  if (legacy) return legacy;

  // 4. Whatever the caller considers safe last.
  return clean(fallback) || fallback || '';
}

export default resolveDestinationName;
