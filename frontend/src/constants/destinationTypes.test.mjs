// Plain-Node tests for the canonical destination-type constants
// (frontend/src/constants/destinationTypes.js). Run via
// `node destinationTypes.test.mjs`, matching this repo's other *.test.mjs
// files (no jest/vitest installed).
import assert from 'node:assert/strict';
import {
  DESTINATION_TYPE_GROUPS,
  DESTINATION_TYPE_GROUP_KEYS,
  CANONICAL_DESTINATION_TYPES,
  LEGACY_ALIAS_DESTINATION_TYPES,
  ALL_KNOWN_DESTINATION_TYPES,
  humanizeDestinationType,
} from './destinationTypes.js';

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

// ── Part 1 — canonical list shape ───────────────────────────────────────

test('every group key has at least one value', () => {
  DESTINATION_TYPE_GROUP_KEYS.forEach((key) => {
    assert.ok(Array.isArray(DESTINATION_TYPE_GROUPS[key]));
    assert.ok(DESTINATION_TYPE_GROUPS[key].length > 0);
  });
});

test('no value appears in more than one group', () => {
  const seen = new Set();
  DESTINATION_TYPE_GROUP_KEYS.forEach((key) => {
    DESTINATION_TYPE_GROUPS[key].forEach((value) => {
      assert.ok(!seen.has(value), `'${value}' duplicated across groups`);
      seen.add(value);
    });
  });
});

test('CANONICAL_DESTINATION_TYPES is the flattened union of every group', () => {
  const expectedCount = DESTINATION_TYPE_GROUP_KEYS.reduce(
    (sum, key) => sum + DESTINATION_TYPE_GROUPS[key].length,
    0,
  );
  assert.equal(CANONICAL_DESTINATION_TYPES.length, expectedCount);
});

test('elevator/stairs/escalator/ramp are never Room types (VerticalConnector territory)', () => {
  ['elevator', 'stairs', 'escalator', 'ramp'].forEach((excluded) => {
    assert.ok(!CANONICAL_DESTINATION_TYPES.includes(excluded));
    assert.ok(!LEGACY_ALIAS_DESTINATION_TYPES.includes(excluded));
  });
});

test('the old hospital-oriented list round-trips onto identically-spelled canonical values', () => {
  const oldList = [
    'emergency', 'room', 'clinic', 'office', 'lab',
    'waiting_area', 'reception', 'imaging', 'pharmacy',
  ];
  oldList.forEach((value) => {
    assert.ok(CANONICAL_DESTINATION_TYPES.includes(value), `missing old value '${value}'`);
  });
});

test('"operating" (no identical-spelling replacement) is a legacy alias, not canonical', () => {
  assert.ok(LEGACY_ALIAS_DESTINATION_TYPES.includes('operating'));
  assert.ok(!CANONICAL_DESTINATION_TYPES.includes('operating'));
  assert.ok(ALL_KNOWN_DESTINATION_TYPES.has('operating'));
});

test('every new commercial/public/education value from the spec is present', () => {
  const mustHave = [
    'store', 'supermarket', 'convenience_store', 'clothing_store', 'electronics_store',
    'bookstore', 'restaurant', 'cafe', 'bakery', 'food_court', 'kiosk', 'bank', 'atm',
    'restroom', 'accessible_restroom', 'prayer_room', 'childcare', 'security',
    'customer_service', 'ticket_office',
    'entrance', 'exit', 'parking', 'pickup_point',
    'classroom', 'lecture_hall', 'library', 'computer_lab', 'administration',
    'information_desk', 'service', 'other',
  ];
  mustHave.forEach((value) => {
    assert.ok(CANONICAL_DESTINATION_TYPES.includes(value), `missing '${value}'`);
  });
});

// ── humanizeDestinationType ──────────────────────────────────────────────

test('humanizeDestinationType: converts snake_case to Title Case', () => {
  assert.equal(humanizeDestinationType('convenience_store'), 'Convenience Store');
  assert.equal(humanizeDestinationType('waiting_area'), 'Waiting Area');
});

test('humanizeDestinationType: single word', () => {
  assert.equal(humanizeDestinationType('room'), 'Room');
});

test('humanizeDestinationType: never exposes a raw snake_case value or crashes on empty input', () => {
  assert.equal(humanizeDestinationType(''), '');
  assert.equal(humanizeDestinationType(null), '');
  assert.equal(humanizeDestinationType(undefined), '');
  assert.ok(!humanizeDestinationType('convenience_store').includes('_'));
});

console.log(`\n${passed} tests passed.`);
