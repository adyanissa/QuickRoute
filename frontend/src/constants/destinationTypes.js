// Canonical Room/Destination type list — mirrors
// backend/constants/destination_types.py key-for-key (the two files must
// never drift; a value here that isn't accepted there would 400 on save,
// and vice versa a backend-accepted value missing here just wouldn't be
// offered as a fresh selection).
//
// QuickRoute is not hospital-only: this list spans shopping malls,
// hospitals, universities, office buildings, and general public
// buildings, replacing the old 10-value hospital-oriented list.
//
// Architecture decision — elevators/stairs/escalators/ramps are
// DELIBERATELY NOT included. This codebase already models vertical
// transitions as VerticalConnector documents (their own CRUD, their own
// per-floor "stop" RoutePoints, their own transition-edge graph logic —
// see components/VerticalConnectionsPanel.jsx). Adding "elevator" as a
// Room type would create a second, disconnected representation of the
// same physical thing — exactly the "duplicate connector record" this
// change must avoid. See the backend module's docstring for the full
// reasoning.
export const DESTINATION_TYPE_GROUPS = {
  general: ['room', 'office', 'reception', 'waiting_area', 'information_desk', 'service', 'other'],
  medical: [
    'emergency', 'clinic', 'lab', 'imaging', 'pharmacy',
    'operating_room', 'treatment_room', 'examination_room', 'nurses_station',
  ],
  retail: [
    'store', 'supermarket', 'convenience_store', 'clothing_store', 'electronics_store',
    'bookstore', 'restaurant', 'cafe', 'bakery', 'food_court', 'kiosk', 'bank', 'atm',
  ],
  public: [
    'restroom', 'accessible_restroom', 'prayer_room', 'childcare',
    'security', 'customer_service', 'ticket_office',
  ],
  // entrance/exit/parking/pickup_point are genuine standalone
  // destinations — elevator/stairs/escalator/ramp are intentionally
  // excluded (see module comment above).
  navigation: ['entrance', 'exit', 'parking', 'pickup_point'],
  education: ['classroom', 'lecture_hall', 'library', 'computer_lab', 'administration'],
};

export const DESTINATION_TYPE_GROUP_KEYS = Object.keys(DESTINATION_TYPE_GROUPS);

export const CANONICAL_DESTINATION_TYPES = DESTINATION_TYPE_GROUP_KEYS.flatMap(
  (groupKey) => DESTINATION_TYPE_GROUPS[groupKey],
);

// Old stored values that must keep working (never crash the edit form,
// never be silently rewritten to another type) but are no longer offered
// as a fresh selection — see the backend module docstring for why
// "operating" specifically needs this (every other old value already has
// an identical-spelling canonical replacement above).
export const LEGACY_ALIAS_DESTINATION_TYPES = ['operating'];

export const ALL_KNOWN_DESTINATION_TYPES = new Set([
  ...CANONICAL_DESTINATION_TYPES,
  ...LEGACY_ALIAS_DESTINATION_TYPES,
]);

// Safety-net label for a value with no translation entry at all (a
// genuinely unknown legacy value not even in LEGACY_ALIAS_DESTINATION_TYPES)
// — "Part 2 requirement 3": user-facing labels must never expose a raw
// snake_case value like `convenience_store` or `waiting_area`. Never used
// for a canonical/legacy-alias value that already has a real translation.
export function humanizeDestinationType(value) {
  if (!value) return '';
  return String(value)
    .split('_')
    .filter(Boolean)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ');
}
