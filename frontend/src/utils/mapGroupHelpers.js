// Pure helpers for the multi-floor Map Group upload/management UI
// (AdminMapScreen.jsx). Kept dependency-free and side-effect-free so the
// floor-row validation/sorting/grouping logic that prevents "two floors
// with the same number", "empty floor rows submitted", and "Floor 1
// points shown on the Floor 2 image" bugs can be unit-tested without a
// DOM/React harness — see mapGroupHelpers.test.mjs.

// ── Normalization primitives ────────────────────────────────────────────
// The single place that decides "what is this Map's real id/floor",
// shared by mapsApi.js's normalizeMap() and buildFloorOptions() below, so
// both layers can never disagree about what counts as a valid id/floor.
//
// Real stored data is messier than any one assumed shape: some Map
// documents predate the multi-floor feature (map_group_id/floor both
// null), some responses may carry a raw Mongo id under `_id` instead of
// the normalized `id`, and a serialized ObjectId can arrive as a plain
// string, a number-like value, or (rarely, e.g. from a raw Mongo export)
// an object exposing `$oid`. `normalizeId` accepts any number of
// candidate values in priority order and returns the first usable one as
// a plain string, or null when nothing usable was found — it never
// returns the literal "undefined"/"null"/"[object Object]" string.
export function normalizeId(...candidates) {
  for (const raw of candidates) {
    if (raw === null || raw === undefined || raw === '') continue;

    if (typeof raw === 'string') return raw;
    if (typeof raw === 'number' && Number.isFinite(raw)) return String(raw);

    if (typeof raw === 'object') {
      if (typeof raw.$oid === 'string' && raw.$oid) return raw.$oid;
      if (typeof raw.toString === 'function') {
        const asString = raw.toString();
        if (asString && asString !== '[object Object]') return asString;
      }
    }
  }

  return null;
}

// Safely turns a raw floor-like value into a finite number, in priority
// order across every field name a Map document's floor has ever been
// stored/spelled as. Explicitly preserves 0 (Ground Floor) — never masks
// a real floor with `?? 0`, since that is indistinguishable from "this
// map's floor is genuinely unknown" and is exactly what caused floor-0
// points to be treated as reusable/rejectable on the wrong floor. Returns
// null only when none of the candidates is a genuine finite number —
// callers must treat null as "unknown", not as Ground Floor.
export function normalizeFloorNumber(...candidates) {
  for (const raw of candidates) {
    if (raw === null || raw === undefined || raw === '') continue;
    const num = Number(raw);
    if (Number.isFinite(num)) return num;
  }

  return null;
}

// A brand-new, empty floor row for the dynamic "Add Another Floor" list.
// `floor` defaults to one past the highest floor already in the list (or
// 0 for the very first row) — a sensible default the admin can still
// freely overwrite (e.g. for a basement/parking level).
export function createEmptyFloorRow(existingRows = [], idSeed = Date.now()) {
  const usedFloors = existingRows
    .map((row) => Number(row.floor))
    .filter((value) => Number.isFinite(value));

  const nextFloor = usedFloors.length === 0 ? 0 : Math.max(...usedFloors) + 1;

  return {
    rowId: `floor-row-${idSeed}`,
    file: null,
    fileName: '',
    preview: '',
    floor: nextFloor,
    floorLabel: '',
    title: '',
    scale: 1,
    useOpenAI: false,
    autoGenerateGraph: true,
  };
}

// True when two or more rows share the same numeric floor value — the
// hard "must not" rule (two floor maps in the same group can never have
// the same floor number), checked both within a fresh multi-floor upload
// batch and again server-side against the group's already-existing
// floors (see backend routes/map_groups_routes.py).
export function hasDuplicateFloors(rows) {
  const floors = rows.map((row) => Number(row.floor));
  const seen = new Set();

  for (const floor of floors) {
    if (!Number.isFinite(floor)) continue;
    if (seen.has(floor)) return true;
    seen.add(floor);
  }

  return false;
}

// Every reason a floor-row list is not yet ready to submit, keyed by row
// index so the UI can highlight exactly which row(s) need attention.
// Returns an empty object when the whole batch is valid.
export function validateFloorRows(rows, existingFloorNumbers = []) {
  const errors = {};

  if (!Array.isArray(rows) || rows.length === 0) {
    return { _batch: 'At least one floor is required.' };
  }

  const existingSet = new Set(existingFloorNumbers.map(Number));

  // Two-pass so a duplicate floor number is flagged on EVERY row that
  // uses it (not just the second-and-later occurrences) — the admin
  // needs to know exactly which rows to fix, not just which one came
  // second.
  const floorCounts = new Map();
  rows.forEach((row) => {
    const floorNumber = Number(row.floor);
    if (!Number.isFinite(floorNumber)) return;
    floorCounts.set(floorNumber, (floorCounts.get(floorNumber) || 0) + 1);
  });

  rows.forEach((row, index) => {
    const rowErrors = [];

    if (!row.file) {
      rowErrors.push('A map image file is required.');
    }

    if (!row.title || row.title.trim().length < 2) {
      rowErrors.push('Title must be at least 2 characters.');
    }

    const floorNumber = Number(row.floor);
    if (!Number.isFinite(floorNumber) || !Number.isInteger(floorNumber)) {
      rowErrors.push('Floor must be a whole number.');
    } else {
      if ((floorCounts.get(floorNumber) || 0) > 1) {
        rowErrors.push('This floor number is already used by another row.');
      }
      if (existingSet.has(floorNumber)) {
        rowErrors.push('This floor already exists in the map group.');
      }
    }

    if (row.scale !== undefined && row.scale !== null && row.scale !== '') {
      const scaleNumber = Number(row.scale);
      if (!Number.isFinite(scaleNumber) || scaleNumber <= 0) {
        rowErrors.push('Scale must be a positive number.');
      }
    }

    if (rowErrors.length > 0) {
      errors[index] = rowErrors;
    }
  });

  return errors;
}

export function isFloorBatchValid(rows, existingFloorNumbers = []) {
  const errors = validateFloorRows(rows, existingFloorNumbers);
  return Object.keys(errors).length === 0;
}

// Ascending numeric floor order — the required display/storage order for
// every floor list (upload preview, Map Management's expandable list, the
// floor switcher). Never mutates the input array.
export function sortFloorsByNumber(floors) {
  return [...floors].sort((a, b) => {
    const floorA = Number(a.floor);
    const floorB = Number(b.floor);
    if (Number.isFinite(floorA) && Number.isFinite(floorB)) {
      return floorA - floorB;
    }
    if (Number.isFinite(floorA)) return -1;
    if (Number.isFinite(floorB)) return 1;
    return 0;
  });
}

// Groups a FLAT maps array (e.g. from GET /api/maps, which returns every
// map regardless of group) into { groups: [...], ungrouped: [...] } for
// Map Management's "grouped by map group" list. Maps sharing the same
// mapGroupId become one group entry (its own floors sorted ascending);
// maps with no mapGroupId at all are returned separately as ordinary
// single-floor maps, preserving the pre-existing flat list behavior for
// them exactly as it was before this feature.
export function groupMapsByMapGroup(maps) {
  const groupsById = new Map();
  const ungrouped = [];

  for (const map of maps) {
    const groupId = map.mapGroupId ?? map.map_group_id ?? null;

    if (!groupId) {
      ungrouped.push(map);
      continue;
    }

    if (!groupsById.has(groupId)) {
      groupsById.set(groupId, {
        groupId,
        groupCode: map.mapGroupCode ?? map.map_group_code ?? null,
        floors: [],
      });
    }

    groupsById.get(groupId).floors.push(map);
  }

  const groups = Array.from(groupsById.values()).map((group) => ({
    ...group,
    floors: sortFloorsByNumber(group.floors),
  }));

  return { groups, ungrouped };
}

// PHASE "Final Submission" Problem 2 — detects the exact reported bug: a
// Room/Destination or Location Code whose stored map_id no longer appears
// among the CURRENT floor maps available for its building (because the
// map was deleted, the building_id relationship drifted, or — most
// commonly — the map predates a Map Group migration and a newer floor map
// replaced it). Never silently attaches the record to a different map;
// this is purely a detector so the UI can surface an explicit
// "legacy map, needs reassignment" warning instead of a stuck/blank
// picker. Pure — takes plain ids/arrays, no fetch/DOM.
export function resolveMapReferenceStatus(mapId, availableMaps) {
  if (!mapId) {
    return { status: 'none' };
  }

  const maps = Array.isArray(availableMaps) ? availableMaps : [];
  const match = maps.find((m) => String(m.id) === String(mapId));

  if (match) {
    return { status: 'ok', map: match };
  }

  return { status: 'legacy' };
}

// Ready-to-render <option> list for a Building/Room/Location-Code map
// dropdown: floors sorted ascending, each entry carrying exactly the
// fields the requirement calls for (Map Group code + floor label + map
// title), and never a bare "— —" when a title is missing (falls back to
// the floor display alone rather than leaving a trailing separator).
export function buildMapOptionLabel(map) {
  const groupPrefix = map?.mapGroupCode ? `[${map.mapGroupCode}] ` : '';
  const floorPart = formatFloorDisplay(map?.floor, map?.floorLabel);
  const titlePart = map?.title && String(map.title).trim();

  return titlePart
    ? `${groupPrefix}${floorPart} — ${titlePart}`
    : `${groupPrefix}${floorPart}`;
}

// The full-map editor's floor <select> (Add Point / Draw Walkable Path /
// Test Route / Vertical Connections) must only ever offer floors that
// actually have a Map document — there is no such thing as a "floor slot"
// without one (see models/map_group_model.py's own comment: a MapGroup
// never stores per-floor data itself, only real Map documents reference
// it). `mapGroupFloors` is `activeMapGroupFloors` from AdminMapScreen.jsx
// (siblings of the active map within its Map Group, already sorted
// ascending by groupMapsByMapGroup/sortFloorsByNumber). When the active
// map does not belong to any Map Group at all (a legacy single-floor
// map), that list is empty — the dropdown must still show the one real
// floor the admin is actually on, so this falls back to `[activeMap]`
// rather than rendering an empty/locked control.
// DEPRECATED — kept only for its own existing unit tests / backward
// compatibility. Superseded by `buildFloorOptions` below: this function's
// only fallback (`[activeMap]`) produces exactly the reported "single
// blank '—' option" bug whenever a real Map's own `floor` is null and it
// has no Map-Group siblings, which real-world legacy (pre-Map-Group)
// floor maps regularly do. AdminMapScreen.jsx no longer calls this.
export function buildFloorSelectOptions(activeMap, mapGroupFloors) {
  const floors = Array.isArray(mapGroupFloors) ? mapGroupFloors : [];
  if (floors.length > 0) return floors;
  return activeMap ? [activeMap] : [];
}

// Section 3 replacement: builds the full-map editor's floor <select>
// options from the REAL, currently-loaded Maps — never solely from a
// strict Map-Group linkage, which real data frequently lacks (legacy
// single-floor maps predating the Map Group feature have
// `map_group_id: null`). Priority, matching every candidate against the
// active Map's own normalized fields:
//   1. Every loaded Map sharing activeMap's mapGroupId.
//   2. If that yields nothing, every loaded Map sharing activeMap's
//      buildingId (a Map Group is optional; a Building is not).
//   3. Always falls back to at least activeMap itself.
// The currently-rendered activeMap is ALWAYS present in the result even
// if step 1/2 somehow missed it (e.g. a stale `allMaps` snapshot
// mid-reload) — this function must never return an empty array while a
// real Map is on screen. Deduplicated by real mapId, sorted ascending by
// floor (unknown-floor entries sort last). Each option is
// `{ mapId, floor, floorLabel, mapGroupId, buildingId, title }` — never a
// bare "—" label: when the floor genuinely can't be determined, the
// option falls back to the Map's own title instead of a blank symbol.
export function buildFloorOptions(activeMap, allMaps) {
  if (!activeMap) return [];

  const maps = Array.isArray(allMaps) ? allMaps : [];

  const activeId = normalizeId(activeMap.id, activeMap._id, activeMap.map_id, activeMap.mapId);
  const activeGroupId = normalizeId(activeMap.mapGroupId, activeMap.map_group_id);
  const activeBuildingId = normalizeId(activeMap.buildingId, activeMap.building_id);

  let candidates = [];

  if (activeGroupId) {
    candidates = maps.filter(
      (m) => normalizeId(m.mapGroupId, m.map_group_id) === activeGroupId,
    );
  }

  if (candidates.length === 0 && activeBuildingId) {
    candidates = maps.filter(
      (m) => normalizeId(m.buildingId, m.building_id) === activeBuildingId,
    );
  }

  if (candidates.length === 0) {
    candidates = [activeMap];
  }

  const hasActive = candidates.some(
    (m) => normalizeId(m.id, m._id, m.map_id, m.mapId) === activeId,
  );
  if (!hasActive) {
    candidates = [...candidates, activeMap];
  }

  const byId = new Map();

  candidates.forEach((m) => {
    if (!m) return;

    const mapId = normalizeId(m.id, m._id, m.map_id, m.mapId);
    if (!mapId) return;
    if (byId.has(mapId)) return;

    const floor = normalizeFloorNumber(m.floor, m.floor_number, m.floorNumber, m.level);
    let floorLabel = formatFloorDisplay(floor, m.floorLabel ?? m.floor_label);

    // Section 3: "Do not render a blank '—' option when a real Map
    // exists." formatFloorDisplay() returns '—' only when neither an
    // explicit label nor a determinable floor number exists — fall back
    // to the Map's own title (still a real, meaningful label) rather
    // than a bare dash in that case.
    if (floorLabel === '—') {
      floorLabel = (m.title && String(m.title).trim()) || 'Map';
    }

    byId.set(mapId, {
      mapId,
      floor,
      floorLabel,
      mapGroupId: normalizeId(m.mapGroupId, m.map_group_id),
      buildingId: normalizeId(m.buildingId, m.building_id),
      title: m.title || '',
    });
  });

  return Array.from(byId.values()).sort((a, b) => {
    if (a.floor !== null && b.floor !== null) return a.floor - b.floor;
    if (a.floor !== null) return -1;
    if (b.floor !== null) return 1;
    return 0;
  });
}

// Pure decision logic behind AdminMapScreen.jsx's handleFloorSwitch: same
// map id (or no target) is a no-op; an unsaved draft requires an explicit
// confirmation (via the injected confirmFn, so this stays testable
// without window.confirm) before the caller may clear it and switch;
// confirming (or no draft to begin with) allows the switch straight away.
// Never mutates anything itself — the caller applies `nextMapId` /
// `clearDraft` to its own state.
export function resolveFloorSwitch({ targetMapId, currentMapId, hasDraft, confirmFn }) {
  if (!targetMapId || targetMapId === currentMapId) {
    return { proceed: false, reason: 'no-op' };
  }

  if (hasDraft) {
    const confirmed = typeof confirmFn === 'function' ? confirmFn() : false;
    if (!confirmed) {
      return { proceed: false, reason: 'cancelled' };
    }
  }

  return { proceed: true, nextMapId: targetMapId, clearDraft: true };
}

// Human-readable floor display used consistently across the admin UI —
// prefers an explicit floor_label (e.g. "Parking B1"), falling back to a
// numeric convention (B1/G/1/2/...) matching the existing end-user
// DestinationCard.jsx formatFloor() convention, so admin and end-user
// floor displays never disagree for the same map.
export function formatFloorDisplay(floor, floorLabel) {
  if (floorLabel && String(floorLabel).trim()) {
    return String(floorLabel).trim();
  }

  if (floor === null || floor === undefined || floor === '') return '—';

  const floorNumber = Number(floor);
  if (!Number.isFinite(floorNumber)) return '—';
  if (floorNumber < 0) return `B${Math.abs(floorNumber)}`;
  if (floorNumber === 0) return 'Ground Floor';
  return `Floor ${floorNumber}`;
}

// Edit Map Details' Floor <select> options — a genuinely SELECTABLE list
// of floor numbers this Map could be assigned to (distinct from
// buildFloorOptions() above, which lists other MAPS the admin can switch
// the workspace to). Never invents a value from the Map's title — this
// only ever offers plain integers for the admin to explicitly choose.
//
//   - When the Map belongs to a Map Group, offers every floor number
//     already used by a sibling floor in that group (so the admin picks
//     a number consistent with the group's real layout), padded with the
//     common Ground/1/2 default range so a group that currently has only
//     one or two floors still offers the usual next ones. The backend's
//     own sibling-collision check (409) remains the real safety net if
//     the admin picks a number a sibling already uses.
//   - When the Map has no Map Group at all (a legacy standalone map),
//     offers a bounded, safe numeric range instead (B2 through Floor 10)
//     since there's no group layout to read from.
//   - Always includes the Map's own CURRENT floor (even if it's outside
//     either of the above) so an already-set value is never silently
//     dropped from the list.
export function buildFloorEditOptions(activeMap, mapGroupFloors) {
  const siblingFloors = (Array.isArray(mapGroupFloors) ? mapGroupFloors : [])
    .map((m) => normalizeFloorNumber(m.floor))
    .filter((floor) => floor !== null);

  const currentFloor = activeMap ? normalizeFloorNumber(activeMap.floor) : null;

  const candidates = new Set(siblingFloors);

  if (siblingFloors.length > 0) {
    [0, 1, 2].forEach((floor) => candidates.add(floor));
  } else {
    for (let floor = -2; floor <= 10; floor += 1) candidates.add(floor);
  }

  if (currentFloor !== null) candidates.add(currentFloor);

  return Array.from(candidates)
    .sort((a, b) => a - b)
    .map((floor) => ({ floor, label: formatFloorDisplay(floor, null) }));
}
