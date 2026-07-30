// Plain-Node tests for Room draft preservation across the "Add / Upload
// New Map" navigation (frontend/src/utils/roomDraftStorage.js). Run via
// `node roomDraftStorage.test.mjs`, matching this repo's other
// *.test.mjs files (no jest/vitest installed).
//
// sessionStorage doesn't exist in plain Node, so a tiny in-memory
// polyfill is installed on `globalThis` before importing the module
// under test (save/loadAndClear read `sessionStorage` lazily inside each
// call, so this works regardless of import order).
import assert from 'node:assert/strict';

class FakeStorage {
  constructor() { this._data = new Map(); }
  getItem(key) { return this._data.has(key) ? this._data.get(key) : null; }
  setItem(key, value) { this._data.set(key, String(value)); }
  removeItem(key) { this._data.delete(key); }
  clear() { this._data.clear(); }
}

globalThis.sessionStorage = new FakeStorage();

const {
  ROOM_DRAFT_STORAGE_KEY,
  serializeRoomDraft,
  parseRoomDraft,
  saveRoomDraft,
  loadAndClearRoomDraft,
} = await import('./roomDraftStorage.js');

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

// ── serializeRoomDraft / parseRoomDraft (pure) ──────────────────────────

test('serializeRoomDraft + parseRoomDraft round-trips the draft exactly', () => {
  const draft = {
    buildingId: 'bld-1',
    view: 'add',
    placementMode: 'map',
    form: { name: 'New Kiosk', type: 'kiosk', floor: 1 },
  };
  const parsed = parseRoomDraft(serializeRoomDraft(draft));
  assert.equal(parsed.buildingId, 'bld-1');
  assert.equal(parsed.view, 'add');
  assert.equal(parsed.placementMode, 'map');
  assert.deepEqual(parsed.form, draft.form);
  assert.ok(typeof parsed.savedAt === 'number');
});

test('serializeRoomDraft: defaults view/placementMode when omitted', () => {
  const parsed = parseRoomDraft(serializeRoomDraft({ buildingId: 'bld-1', form: {} }));
  assert.equal(parsed.view, 'add');
  assert.equal(parsed.placementMode, 'map');
});

test('parseRoomDraft: returns null for garbage/malformed JSON, never throws', () => {
  assert.equal(parseRoomDraft('not json at all {{{'), null);
  assert.equal(parseRoomDraft(''), null);
  assert.equal(parseRoomDraft(null), null);
  assert.equal(parseRoomDraft(undefined), null);
  assert.equal(parseRoomDraft(42), null);
});

test('parseRoomDraft: rejects a parsed value missing buildingId or form', () => {
  assert.equal(parseRoomDraft(JSON.stringify({ view: 'add' })), null);
  assert.equal(parseRoomDraft(JSON.stringify({ buildingId: 'x' })), null);
  assert.equal(parseRoomDraft(JSON.stringify([1, 2, 3])), null);
  assert.equal(parseRoomDraft(JSON.stringify('a string')), null);
});

// ── saveRoomDraft / loadAndClearRoomDraft (sessionStorage side effects) ─

test('saveRoomDraft + loadAndClearRoomDraft: round-trips through real storage', () => {
  globalThis.sessionStorage.clear();
  const draft = { buildingId: 'bld-9', view: 'edit', placementMode: 'manual', form: { name: 'X' } };
  saveRoomDraft(draft);

  const restored = loadAndClearRoomDraft();
  assert.equal(restored.buildingId, 'bld-9');
  assert.equal(restored.view, 'edit');
  assert.deepEqual(restored.form, { name: 'X' });
});

test('loadAndClearRoomDraft: is one-shot — a second call returns null', () => {
  globalThis.sessionStorage.clear();
  saveRoomDraft({ buildingId: 'bld-1', form: {} });

  const first = loadAndClearRoomDraft();
  const second = loadAndClearRoomDraft();
  assert.ok(first !== null);
  assert.equal(second, null);
});

test('loadAndClearRoomDraft: returns null when nothing was ever saved', () => {
  globalThis.sessionStorage.clear();
  assert.equal(loadAndClearRoomDraft(), null);
});

test('saveRoomDraft: never throws even if sessionStorage.setItem throws (private browsing/quota)', () => {
  const original = globalThis.sessionStorage;
  globalThis.sessionStorage = {
    setItem() { throw new Error('QuotaExceededError'); },
  };
  assert.doesNotThrow(() => saveRoomDraft({ buildingId: 'x', form: {} }));
  globalThis.sessionStorage = original;
});

test('loadAndClearRoomDraft: never throws even if sessionStorage.getItem throws', () => {
  const original = globalThis.sessionStorage;
  globalThis.sessionStorage = {
    getItem() { throw new Error('SecurityError'); },
  };
  let result;
  assert.doesNotThrow(() => { result = loadAndClearRoomDraft(); });
  assert.equal(result, null);
  globalThis.sessionStorage = original;
});

test('the storage key is a stable, namespaced constant', () => {
  assert.equal(ROOM_DRAFT_STORAGE_KEY, 'quickroute_admin_room_draft_v1');
});

console.log(`\n${passed} tests passed.`);
