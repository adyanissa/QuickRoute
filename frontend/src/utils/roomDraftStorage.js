// Preserves an in-progress Add/Edit Room form across a navigation to
// Admin Map Management (Part 4's "Add / Upload New Map" action) and back.
// The serialize/parse functions are pure and DOM-free so the actual
// safety contract (round-trips exactly, never throws on garbage input) is
// directly unit-testable; save/loadAndClear are the only pieces that
// touch sessionStorage, kept intentionally thin.
export const ROOM_DRAFT_STORAGE_KEY = 'quickroute_admin_room_draft_v1';

// Pure — no sessionStorage access, safe to unit test directly.
export function serializeRoomDraft({ buildingId, view, placementMode, form }) {
  return JSON.stringify({
    buildingId: buildingId ?? null,
    view: view || 'add',
    placementMode: placementMode || 'map',
    form: form || {},
    savedAt: Date.now(),
  });
}

// Pure — never throws, even on malformed/garbage JSON; returns null for
// anything that doesn't look like a real draft (missing buildingId/form).
export function parseRoomDraft(raw) {
  if (!raw || typeof raw !== 'string') return null;

  let parsed;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return null;
  }

  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return null;
  if (!parsed.buildingId || !parsed.form || typeof parsed.form !== 'object') return null;

  return parsed;
}

// One-shot save before navigating away to Map Management. Never throws —
// a storage failure (private browsing, quota) must never block the
// navigation itself.
export function saveRoomDraft(draft) {
  try {
    if (typeof sessionStorage === 'undefined') return;
    sessionStorage.setItem(ROOM_DRAFT_STORAGE_KEY, serializeRoomDraft(draft));
  } catch {
    // Ignore — see comment above.
  }
}

// One-shot restore on return — always clears the stored draft immediately
// after reading it (whether or not it parsed successfully) so a stale
// draft can never resurrect itself on some later, unrelated visit to this
// screen.
export function loadAndClearRoomDraft() {
  try {
    if (typeof sessionStorage === 'undefined') return null;
    const raw = sessionStorage.getItem(ROOM_DRAFT_STORAGE_KEY);
    if (raw === null) return null;
    sessionStorage.removeItem(ROOM_DRAFT_STORAGE_KEY);
    return parseRoomDraft(raw);
  } catch {
    return null;
  }
}
