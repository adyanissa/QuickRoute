// RBAC/dashboard cleanup task (frontend completion) — dependency-free
// Node tests for dashboardHierarchy.js (Super Admin campus grouping).
import assert from 'node:assert/strict';
import { groupBuildingsByCampus, isUnassignedCampus } from './dashboardHierarchy.js';

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

const UNASSIGNED = 'Unassigned location';

test('scenario 9/29: buildings with a real campus group under that campus, never a demo name', () => {
  const buildings = [
    { id: 'b1', campus: 'North Campus' },
    { id: 'b2', campus: 'North Campus' },
    { id: 'b3', campus: 'South Campus' },
  ];
  const groups = groupBuildingsByCampus(buildings, UNASSIGNED);
  assert.equal(groups.size, 2);
  assert.equal(groups.get('North Campus').length, 2);
  assert.equal(groups.get('South Campus').length, 1);
  assert.equal(groups.has('Rabin Medical Center'), false);
});

test('buildings with empty/whitespace-only campus land under the Unassigned label', () => {
  const buildings = [
    { id: 'b1', campus: '' },
    { id: 'b2', campus: '   ' },
    { id: 'b3', campus: null },
    { id: 'b4' }, // campus field entirely absent
  ];
  const groups = groupBuildingsByCampus(buildings, UNASSIGNED);
  assert.equal(groups.size, 1);
  assert.equal(groups.get(UNASSIGNED).length, 4);
});

test('mixed real-campus and unassigned buildings split into separate groups', () => {
  const buildings = [
    { id: 'b1', campus: 'Main' },
    { id: 'b2', campus: '' },
  ];
  const groups = groupBuildingsByCampus(buildings, UNASSIGNED);
  assert.equal(groups.size, 2);
  assert.equal(groups.get('Main').length, 1);
  assert.equal(groups.get(UNASSIGNED).length, 1);
});

test('empty buildings array produces an empty map, not an error', () => {
  assert.equal(groupBuildingsByCampus([], UNASSIGNED).size, 0);
  assert.equal(groupBuildingsByCampus(null, UNASSIGNED).size, 0);
  assert.equal(groupBuildingsByCampus(undefined, UNASSIGNED).size, 0);
});

test('isUnassignedCampus recognizes empty/whitespace/undefined as unassigned', () => {
  assert.equal(isUnassignedCampus(''), true);
  assert.equal(isUnassignedCampus('   '), true);
  assert.equal(isUnassignedCampus(undefined), true);
  assert.equal(isUnassignedCampus(null), true);
  assert.equal(isUnassignedCampus('Main Campus'), false);
});

console.log(`\n${passed} passed`);
