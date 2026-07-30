// Pure helpers for the Add/Edit Room "Type" selector — kept
// dependency-free (no React) so the "never crash on an unknown legacy
// value, never silently convert it" contract is directly unit-testable.
// See constants/destinationTypes.js for the canonical value list itself.
import {
  DESTINATION_TYPE_GROUPS,
  DESTINATION_TYPE_GROUP_KEYS,
  ALL_KNOWN_DESTINATION_TYPES,
  humanizeDestinationType,
} from '../constants/destinationTypes.js';

// Resolves a single value's display label: a real translation when one
// exists, otherwise a humanized fallback (never a raw snake_case string
// reaches the UI) — Part 2 requirements 3/4/8.
export function resolveDestinationTypeLabel(value, typeLabels = {}) {
  if (!value) return '';
  return typeLabels[value] || humanizeDestinationType(value);
}

// Builds the full <optgroup>-ready structure for the Type <select>:
//   [{ groupKey, groupLabel, options: [{ value, label }] }, ...]
// Always includes every canonical group in a stable order. When
// `currentValue` is a real value that ISN'T among the canonical options
// (a legacy alias like "operating", or a genuinely unrecognized old
// value), an extra trailing group is appended containing ONLY that one
// value — so the select can render it as a real, selected option without
// crashing and, critically, WITHOUT silently reassigning the room to a
// different (canonical-looking) type just because it rendered in the
// same list (Part 2 requirement 4).
export function buildDestinationTypeSelectGroups(currentValue, typeLabels = {}, groupLabels = {}) {
  const groups = DESTINATION_TYPE_GROUP_KEYS.map((groupKey) => ({
    groupKey,
    groupLabel: groupLabels[groupKey] || groupKey,
    options: DESTINATION_TYPE_GROUPS[groupKey].map((value) => ({
      value,
      label: resolveDestinationTypeLabel(value, typeLabels),
    })),
  }));

  if (currentValue && !isCanonicalDestinationType(currentValue)) {
    groups.push({
      groupKey: 'legacy',
      groupLabel: groupLabels.legacy || 'Legacy',
      options: [
        {
          value: currentValue,
          label: resolveDestinationTypeLabel(currentValue, typeLabels),
        },
      ],
    });
  }

  return groups;
}

function isCanonicalDestinationType(value) {
  return DESTINATION_TYPE_GROUP_KEYS.some((groupKey) =>
    DESTINATION_TYPE_GROUPS[groupKey].includes(value),
  );
}

// True for any value the app has ever seen before (canonical OR legacy
// alias) — used only for diagnostics/tests, not for gating the select
// (buildDestinationTypeSelectGroups already handles the genuinely-unknown
// case safely on its own).
export function isKnownDestinationType(value) {
  return ALL_KNOWN_DESTINATION_TYPES.has(value);
}
