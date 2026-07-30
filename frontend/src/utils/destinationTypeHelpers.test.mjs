// Plain-Node tests for the Add/Edit Room Type selector's pure helpers
// (frontend/src/utils/destinationTypeHelpers.js). Run via
// `node destinationTypeHelpers.test.mjs`, matching this repo's other
// *.test.mjs files (no jest/vitest installed).
import assert from 'node:assert/strict';
import {
  resolveDestinationTypeLabel,
  buildDestinationTypeSelectGroups,
  isKnownDestinationType,
} from './destinationTypeHelpers.js';
import { DESTINATION_TYPE_GROUP_KEYS } from '../constants/destinationTypes.js';

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

const LABELS = {
  waiting_area: 'Waiting Area',
  operating_room: 'Operating Room',
  accessible_restroom: 'Accessible Restroom',
  supermarket: 'Supermarket',
  clothing_store: 'Clothing Store',
  information_desk: 'Information Desk',
};

const GROUP_LABELS = {
  general: 'General', medical: 'Medical', retail: 'Retail & Food',
  public: 'Public Facilities', navigation: 'Access & Navigation',
  education: 'Education', legacy: 'Legacy',
};

// ── resolveDestinationTypeLabel — Part 2 requirements 3/4/8 ─────────────

test('resolveDestinationTypeLabel: uses the real translation when one exists', () => {
  assert.equal(resolveDestinationTypeLabel('waiting_area', LABELS), 'Waiting Area');
});

test('resolveDestinationTypeLabel: never exposes a raw snake_case value — falls back to humanized', () => {
  const label = resolveDestinationTypeLabel('convenience_store', {});
  assert.equal(label, 'Convenience Store');
  assert.ok(!label.includes('_'));
});

test('resolveDestinationTypeLabel: empty/null value returns empty string, never crashes', () => {
  assert.equal(resolveDestinationTypeLabel(null, LABELS), '');
  assert.equal(resolveDestinationTypeLabel('', LABELS), '');
});

// ── buildDestinationTypeSelectGroups — Part 2 requirements 1/2/4 ────────

test('includes every canonical group in a stable order', () => {
  const groups = buildDestinationTypeSelectGroups('room', LABELS, GROUP_LABELS);
  assert.deepEqual(groups.map((g) => g.groupKey), DESTINATION_TYPE_GROUP_KEYS);
});

test('an existing canonical value (e.g. from an old Room) loads without a legacy group', () => {
  const groups = buildDestinationTypeSelectGroups('waiting_area', LABELS, GROUP_LABELS);
  assert.ok(!groups.some((g) => g.groupKey === 'legacy'));
  const flatValues = groups.flatMap((g) => g.options.map((o) => o.value));
  assert.ok(flatValues.includes('waiting_area'));
});

test('an unknown legacy value gets its own trailing group, never crashes, never gets reassigned', () => {
  const groups = buildDestinationTypeSelectGroups('some_ancient_value', LABELS, GROUP_LABELS);
  const legacyGroup = groups.find((g) => g.groupKey === 'legacy');
  assert.ok(legacyGroup, 'expected a legacy group to be appended');
  assert.equal(legacyGroup.options.length, 1);
  assert.equal(legacyGroup.options[0].value, 'some_ancient_value');

  // Critically: the legacy value must not have been silently folded into
  // any canonical group's options (no silent conversion — Part 2 rule 4).
  const canonicalGroups = groups.filter((g) => g.groupKey !== 'legacy');
  canonicalGroups.forEach((g) => {
    assert.ok(!g.options.some((o) => o.value === 'some_ancient_value'));
  });
});

test('the "operating" legacy alias also gets its own trailing group (not folded into operating_room)', () => {
  const groups = buildDestinationTypeSelectGroups('operating', LABELS, GROUP_LABELS);
  const legacyGroup = groups.find((g) => g.groupKey === 'legacy');
  assert.ok(legacyGroup);
  assert.equal(legacyGroup.options[0].value, 'operating');

  const medicalGroup = groups.find((g) => g.groupKey === 'medical');
  assert.ok(medicalGroup.options.some((o) => o.value === 'operating_room'));
  assert.ok(!medicalGroup.options.some((o) => o.value === 'operating'));
});

test('a falsy currentValue never appends a legacy group', () => {
  const groups = buildDestinationTypeSelectGroups(null, LABELS, GROUP_LABELS);
  assert.ok(!groups.some((g) => g.groupKey === 'legacy'));
});

test('an "Other" option exists in the general group', () => {
  const groups = buildDestinationTypeSelectGroups('room', LABELS, GROUP_LABELS);
  const generalGroup = groups.find((g) => g.groupKey === 'general');
  assert.ok(generalGroup.options.some((o) => o.value === 'other'));
});

test('every option has a real, non-empty label (never a bare raw value with underscores)', () => {
  const groups = buildDestinationTypeSelectGroups('room', LABELS, GROUP_LABELS);
  groups.forEach((g) => {
    g.options.forEach((opt) => {
      assert.ok(opt.label && opt.label.length > 0);
      assert.ok(!opt.label.includes('_'), `label '${opt.label}' still has an underscore`);
    });
  });
});

// ── isKnownDestinationType ───────────────────────────────────────────────

test('isKnownDestinationType: true for canonical and legacy-alias values', () => {
  assert.equal(isKnownDestinationType('supermarket'), true);
  assert.equal(isKnownDestinationType('operating'), true);
});

test('isKnownDestinationType: false for a genuinely unrecognized value', () => {
  assert.equal(isKnownDestinationType('made_up_value'), false);
});

console.log(`\n${passed} tests passed.`);
