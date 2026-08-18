// Tests for the "Delete Connection" admin mode added to AdminMapScreen.jsx
// — lets an admin delete a single RouteEdge ("Walkable Path" connection)
// without ever deleting either endpoint RoutePoint.
//
// Same plain-node convention as the rest of this repo's *.test.mjs files
// (no jest/testing-library installed — see mapCalibrationUI.test.mjs, this
// feature's closest sibling in both scope and test style). Source-text
// contract tests confirming: the new toolbar mode exists and is mutually
// exclusive with every other mode; edge selection happens via the real
// RouteEdge object (never coordinates/proximity); a plain map click never
// creates a RoutePoint while this mode is active; the confirmation modal
// shows the real endpoint names; confirming calls the existing, already-
// admin-protected DELETE /api/route-edges/{edge_id} endpoint with only the
// selected edge's id; a failed deletion never clears the selection or
// refreshes (so the edge stays visible); vertical connector edges can never
// be selected for deletion here; Draw Walkable Path/Add Point/Test Route/
// Calibrate Scale are untouched and still reachable after leaving this
// mode; and no Dijkstra/graph-generation code was pulled into any of it.

import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

function readScreen(filename) {
  return fs.readFileSync(path.join(__dirname, filename), 'utf8');
}

function readApi(filename) {
  return fs.readFileSync(
    path.join(__dirname, '..', 'api', filename),
    'utf8',
  );
}

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

const ADMIN_MAP_SCREEN = 'AdminMapScreen.jsx';
const source = readScreen(ADMIN_MAP_SCREEN);

// ── 1. Delete Connection button appears in AdminMapScreen ──────────────────

// The mode controls moved out of the old fixed horizontal toolbar into
// the draggable "Navigation Tools" toolbox, which is data-driven: each
// control is an entry in the `mapToolGroups` array rather than an inline
// <button>. The invariant is unchanged — a Delete Connection control
// exists, it is labelled t.deleteConnectionMode, and it enters
// delete-connection mode — so this still slices a tightly bounded region
// (the toolbox config only) rather than matching the whole 500KB file.
function toolboxConfigSlice(src) {
  const start = src.indexOf('const mapToolGroups = [');
  assert.notEqual(start, -1, 'expected the mapToolGroups toolbox config');
  const end = src.indexOf('\n  ];', start);
  assert.notEqual(end, -1, 'expected the mapToolGroups config to terminate');
  return src.slice(start, end);
}

test('AdminMapScreen.jsx: a Delete Connection toolbox entry exists, rendering t.deleteConnectionMode', () => {
  const toolbox = toolboxConfigSlice(source);

  assert.match(toolbox, /setMode\('delete-connection'\)/);
  assert.match(toolbox, /label:\s*t\.deleteConnectionMode/);
  assert.match(
    toolbox,
    /id:\s*'delete-connection'[\s\S]*?label:\s*t\.deleteConnectionMode[\s\S]*?setMode\('delete-connection'\)/,
  );
});

// ── 2. Activating it enters a dedicated delete mode ─────────────────────────

test("AdminMapScreen.jsx: clicking the button sets mode to 'delete-connection', a new value distinct from point/draw/test/connector/calibrate", () => {
  assert.match(source, /const \[mode, setMode\] = useState\('point'\);/);
  assert.match(source, /setMode\('delete-connection'\)/);
  assert.match(source, /mode === 'delete-connection'/);
  // None of the pre-existing modes were removed.
  assert.match(source, /mode === 'draw'/);
  assert.match(source, /mode === 'test'/);
  assert.match(source, /mode === 'connector'/);
  assert.match(source, /mode === 'calibrate'/);
});

test('AdminMapScreen.jsx: entering delete-connection mode resets any in-progress point selection and prior edge selection', () => {
  // Toolbox entries declare their handler as an object property
  // (`onClick: () => {`), not a JSX attribute (`onClick={() => {`).
  const toolButtonMatch = source.match(
    /onClick:\s*\(\) => \{\s*if \(mode !== 'delete-connection'\) \{([\s\S]*?)\}\s*\}/,
  );
  assert.ok(toolButtonMatch, 'expected the delete-connection tool onClick body');
  assert.match(toolButtonMatch[1], /setMode\('delete-connection'\)/);
  assert.match(toolButtonMatch[1], /setSelectedEdgeForDeletion\(null\)/);
  assert.match(toolButtonMatch[1], /setDeleteConnectionVerticalNotice\(false\)/);
});

// ── 3. Clicking an existing edge selects its real RouteEdge ID ─────────────

test('AdminMapScreen.jsx: handleEdgeClickForDeletion selects the real edge object passed in directly, never a coordinate/proximity lookup', () => {
  const fnMatch = source.match(
    /const handleEdgeClickForDeletion = \([\s\S]*?\n  \};/,
  );
  assert.ok(fnMatch, 'expected handleEdgeClickForDeletion');
  const body = fnMatch[0];

  assert.match(body, /\(edge, fromPoint, toPoint, event\) => \{/);
  assert.match(body, /setSelectedEdgeForDeletion\(\{ edge, fromPoint, toPoint \}\)/);
  // Never resolves the edge from x/y coordinates.
  assert.doesNotMatch(body, /findNearestPointWithinThreshold/);
});

test('AdminMapScreen.jsx: the edge overlay passes the real edge from resolvedEdges (the same data used to draw the visible line) into the click handler', () => {
  const overlayMatch = source.match(
    /\{isDeleteConnectionMode && \([\s\S]*?onClick=\{\(event\) =>\s*handleEdgeClickForDeletion\(\s*edge,\s*fromPoint,\s*toPoint,\s*event,\s*\)\s*\}/,
  );
  assert.ok(overlayMatch, 'expected the invisible hit-stroke to pass the real edge/fromPoint/toPoint into the click handler');
});

// ── 4. Edge hit-testing: invisible wider clickable stroke, real geometry,
//       pointerEvents="stroke" ──────────────────────────────────────────────

test('AdminMapScreen.jsx: an invisible, wider clickable line is rendered over each edge only in delete-connection mode, using pointerEvents="stroke" and the exact same coordinates as the visible line', () => {
  const svgSectionMatch = source.match(
    /\{resolvedEdges\.map\([\s\S]*?\{routePoints\.map/,
  );
  assert.ok(svgSectionMatch, 'expected the resolvedEdges rendering block');
  const body = svgSectionMatch[0];

  assert.match(body, /pointerEvents="stroke"/);
  assert.match(body, /stroke="transparent"/);
  // Same coordinates as the real edge (fromPoint/toPoint), not a separate
  // geometry.
  const hitLineMatch = body.match(
    /\{isDeleteConnectionMode && \(\s*<line\s*x1=\{fromPoint\.x\}\s*y1=\{fromPoint\.y\}\s*x2=\{toPoint\.x\}\s*y2=\{toPoint\.y\}/,
  );
  assert.ok(hitLineMatch, 'expected the invisible hit-stroke line to reuse fromPoint/toPoint coordinates directly');
});

test('AdminMapScreen.jsx: the visible edge line geometry (x1/y1/x2/y2) is never altered by delete-connection mode — only its stroke color changes when selected', () => {
  const svgSectionMatch = source.match(
    /\{resolvedEdges\.map\([\s\S]*?\{routePoints\.map/,
  );
  const body = svgSectionMatch[0];
  assert.match(body, /x1=\{fromPoint\.x\}\s*y1=\{fromPoint\.y\}\s*x2=\{toPoint\.x\}\s*y2=\{toPoint\.y\}\s*stroke=\{/);
});

// ── 5 & 13. Clicking a line does not create a RoutePoint; normal map-click
//            point creation is only disabled WHILE this mode is active ─────

test('AdminMapScreen.jsx: handleFullMapClick returns early for delete-connection mode before the normal Add Point fallback runs', () => {
  const handlerMatch = source.match(
    /const handleFullMapClick = \(event\) => \{[\s\S]*?\n  \};/,
  );
  assert.ok(handlerMatch, 'expected to find handleFullMapClick');
  const handlerBody = handlerMatch[0];

  const deleteModeIndex = handlerBody.indexOf("mode === 'delete-connection'");
  const setClickedPointIndex = handlerBody.indexOf('setClickedPoint({ x, y });');

  assert.ok(deleteModeIndex > -1, 'expected a delete-connection mode check inside handleFullMapClick');
  assert.ok(setClickedPointIndex > -1, 'expected the normal Add Point fallback to still exist');
  assert.ok(
    deleteModeIndex < setClickedPointIndex,
    'delete-connection branch must return before the normal Add Point click action runs',
  );
});

// ── 6. The modal displays the correct from/to point names, edge type, and
//       floor/map ──────────────────────────────────────────────────────────

test('AdminMapScreen.jsx: the confirmation modal shows the real fromPoint/toPoint display names, edge_type, and active map/floor', () => {
  const modalMatch = source.match(
    /\{mode === 'delete-connection' && selectedEdgeForDeletion && \([\s\S]*?\n        \)\}/,
  );
  assert.ok(modalMatch, 'expected the delete-connection confirmation modal');
  const body = modalMatch[0];

  assert.match(body, /selectedEdgeForDeletion\.fromPoint\.name/);
  assert.match(body, /selectedEdgeForDeletion\.toPoint\.name/);
  assert.match(body, /selectedEdgeForDeletion\.edge\.edge_type/);
  assert.match(body, /formatFloorDisplay\(activeMap\.floor, activeMap\.floorLabel\)/);
  assert.match(body, /\{t\.deleteConnectionSafetyNote\}/);
});

// ── 7. Confirm calls the correct authenticated edge deletion endpoint,
//        with only the selected edge's id ──────────────────────────────────

test('AdminMapScreen.jsx: handleConfirmDeleteConnection calls deleteRouteEdge with only the selected edge id (no loop/bulk call)', () => {
  const fnMatch = source.match(
    /const handleConfirmDeleteConnection = async \(\) => \{[\s\S]*?\n  \};/,
  );
  assert.ok(fnMatch, 'expected handleConfirmDeleteConnection');
  const body = fnMatch[0];

  assert.match(body, /const edgeId =\s*selectedEdgeForDeletion\.edge\.id \|\| selectedEdgeForDeletion\.edge\._id;/);
  assert.match(body, /await deleteRouteEdge\(edgeId\);/);
  // Never a loop over multiple edges or points.
  assert.doesNotMatch(body, /for \(const/);
  assert.doesNotMatch(body, /\.forEach\(/);
});

test('AdminMapScreen.jsx: imports deleteRouteEdge from the existing routeEdgesApi module (no new API module introduced)', () => {
  assert.match(
    source,
    /import\s*\{[^}]*deleteRouteEdge[^}]*\}\s*from\s*['"]\.\.\/api\/routeEdgesApi['"]/,
  );
});

test('routeEdgesApi.js: deleteRouteEdge sends DELETE to /api/route-edges/{edgeId} (existing, unmodified endpoint contract)', () => {
  const apiSource = readApi('routeEdgesApi.js');
  assert.match(apiSource, /export function deleteRouteEdge\(edgeId\)/);
  assert.match(apiSource, /`\/api\/route-edges\/\$\{edgeId\}`/);
  assert.match(apiSource, /method:\s*['"]DELETE['"]/);
});

// route_edge_routes.py is read once here and reused by both focused checks
// below, instead of one fragile single regex spanning the decorator through
// a Python-brace-matched "end of function" (Python has no explicit block-
// end token, so that only worked by accident, matching the return
// statement's dict literal `}` — and broke outright on CRLF line endings,
// since the previous regex mixed literal `\n` with `\s*` inconsistently).
const backendSource = fs.readFileSync(
  path.join(__dirname, '..', '..', '..', 'backend', 'routes', 'route_edge_routes.py'),
  'utf8',
);

test('route_edge_routes.py: an @router.delete(...) decorator targeting "/{edge_id}" immediately precedes delete_route_edge', () => {
  // Tolerant of: multiline decorators, any order/presence of extra keyword
  // arguments (status_code, response_model, ...), and CRLF vs LF line
  // endings (\r?\n / \s, never a bare \n assumption).
  const decoratorMatch = backendSource.match(
    /@router\.delete\(([\s\S]*?)\)\s*async def delete_route_edge\(/,
  );
  assert.ok(
    decoratorMatch,
    'expected an @router.delete(...) decorator immediately followed by async def delete_route_edge(',
  );
  assert.match(decoratorMatch[1], /["']\/\{edge_id\}["']/);
});

test('route_edge_routes.py: delete_route_edge requires admin authorization, deletes only the RouteEdge, and never references RoutePoint', () => {
  const handlerStart = backendSource.indexOf('async def delete_route_edge(');
  assert.ok(handlerStart > -1, 'expected the delete_route_edge handler');

  // Bounded to the next top-level route (or end of file, since this is
  // currently the last route in the file) — never a Python-brace-matching
  // assumption, which is fragile because Python blocks have no explicit
  // end token (the old regex only worked by coincidentally landing on the
  // return statement's dict literal).
  const nextRouteIndex = backendSource.indexOf('@router.', handlerStart);
  const handlerBody =
    nextRouteIndex === -1
      ? backendSource.slice(handlerStart)
      : backendSource.slice(handlerStart, nextRouteIndex);

  // Admin guard — tolerant of the exact parameter name/whitespace, just
  // requires the real dependency function.
  //
  // This asserted require_global_admin until the RBAC work broadened edge
  // administration to the whole admin tier: delete_route_edge now takes
  // require_any_admin and then calls _require_edge_scope(...), so a
  // building_manager can delete an edge inside their OWN building/map
  // scope and nothing else. That is strictly the same authorization model
  // the sibling create/update edge endpoints already use, and it is a
  // narrowing per-resource check, not a blanket loosening — so the guard
  // asserted here is the admin-tier dependency plus the scope call.
  assert.match(handlerBody, /Depends\(\s*require_any_admin\s*\)/);
  assert.match(handlerBody, /_require_edge_scope\(/);

  // Deletes only the resolved RouteEdge document.
  assert.match(handlerBody, /await edge\.delete\(\)/);

  // Never touches RoutePoint in any way.
  assert.doesNotMatch(handlerBody, /RoutePoint/);
});

// ── 8. Both endpoint RoutePoints remain — no RoutePoint deletion call
//        anywhere in the delete-connection flow ─────────────────────────────

test('AdminMapScreen.jsx: the delete-connection confirm flow never calls deleteRoutePoint', () => {
  const fnMatch = source.match(
    /const handleConfirmDeleteConnection = async \(\) => \{[\s\S]*?\n  \};/,
  );
  assert.doesNotMatch(fnMatch[0], /deleteRoutePoint/);
});

// ── 9. Cancel does not change backend data ──────────────────────────────────

test('AdminMapScreen.jsx: handleCancelDeleteConnectionSelection and handleCancelDeleteConnectionMode never call any API function', () => {
  const selectionCancelMatch = source.match(
    /const handleCancelDeleteConnectionSelection = \(\) => \{[\s\S]*?\n  \};/,
  );
  const modeCancelMatch = source.match(
    /const handleCancelDeleteConnectionMode = \(\) => \{[\s\S]*?\n  \};/,
  );
  assert.ok(selectionCancelMatch, 'expected handleCancelDeleteConnectionSelection');
  assert.ok(modeCancelMatch, 'expected handleCancelDeleteConnectionMode');

  [selectionCancelMatch[0], modeCancelMatch[0]].forEach((body) => {
    assert.doesNotMatch(body, /deleteRouteEdge/);
    assert.doesNotMatch(body, /await /);
    assert.doesNotMatch(body, /createRouteEdge/);
    assert.doesNotMatch(body, /createRoutePoint/);
    assert.doesNotMatch(body, /deleteRoutePoint/);
  });

  // Cancel always restores normal interaction by returning to 'point' mode
  // (same convention as handleCancelDraw / handleCancelCalibration).
  assert.match(modeCancelMatch[0], /setMode\('point'\)/);
});

// ── 10. Failed deletion keeps the edge visible (selection is only cleared
//        and the graph only refreshed on the SUCCESS path) ─────────────────

test('AdminMapScreen.jsx: a failed deleteRouteEdge call never clears the selected edge and never refreshes the graph — only sets an error message', () => {
  const fnMatch = source.match(
    /const handleConfirmDeleteConnection = async \(\) => \{[\s\S]*?\n  \};/,
  );
  const body = fnMatch[0];

  const tryMatch = body.match(/try \{([\s\S]*?)\} catch \(error\) \{([\s\S]*?)\} finally/);
  assert.ok(tryMatch, 'expected a try/catch/finally structure');
  const [, tryBody, catchBody] = tryMatch;

  // Success path clears selection and refreshes.
  assert.match(tryBody, /setSelectedEdgeForDeletion\(null\)/);
  assert.match(tryBody, /await refreshRouteGraph\(/);

  // Failure path only records a safe error message — never clears the
  // selection, never refreshes, never touches routeEdges directly.
  assert.doesNotMatch(catchBody, /setSelectedEdgeForDeletion\(null\)/);
  assert.doesNotMatch(catchBody, /refreshRouteGraph/);
  assert.doesNotMatch(catchBody, /setRouteEdges/);
  assert.match(catchBody, /setDeleteConnectionError\(error\.message \|\| t\.deleteConnectionFailed\)/);
});

// ── 11. Vertical connector edges cannot be deleted through this mode ───────

test('AdminMapScreen.jsx: isVerticalConnectorEdge blocks any edge whose edge_type is not walkway, or that carries a connector_id', () => {
  const fnMatch = source.match(
    /const isVerticalConnectorEdge = \(edge\) =>[\s\S]*?;/,
  );
  assert.ok(fnMatch, 'expected isVerticalConnectorEdge');
  assert.match(fnMatch[0], /edge\.edge_type !== 'walkway'/);
  assert.match(fnMatch[0], /Boolean\(edge\.connector_id\)/);
});

test('AdminMapScreen.jsx: clicking a vertical connector edge never selects it for deletion and shows the "manage from Vertical Connections" message instead', () => {
  const fnMatch = source.match(
    /const handleEdgeClickForDeletion = \([\s\S]*?\n  \};/,
  );
  const body = fnMatch[0];

  const blockedBranch = body.match(
    /if \(isVerticalConnectorEdge\(edge\)\) \{([\s\S]*?)\}/,
  );
  assert.ok(blockedBranch, 'expected a blocked-edge branch');
  assert.match(blockedBranch[1], /setSelectedEdgeForDeletion\(null\)/);
  assert.match(blockedBranch[1], /setDeleteConnectionVerticalNotice\(true\)/);

  // The blocked message is shown via the bottom instruction banner.
  assert.match(source, /deleteConnectionVerticalNotice\s*\?\s*t\.deleteConnectionVerticalBlocked/);
});

// ── 12 & 13. Draw Walkable Path / Add Point still work normally after
//             exiting delete mode ───────────────────────────────────────────

test("AdminMapScreen.jsx: the Draw Walkable Path and Add Point toolbar buttons are unchanged and still set mode to 'draw'/'point' respectively", () => {
  assert.match(source, /setMode\('draw'\);\s*setClickedPoint\(null\);\s*setPointName\(''\);/);
  assert.match(source, /if \(mode !== 'point'\) \{\s*setMode\('point'\);/);
});

test('AdminMapScreen.jsx: Cancel Delete Mode returns to point mode, restoring every other mode-specific click path (draw/connector/calibrate remain reachable via their own buttons)', () => {
  const fnMatch = source.match(
    /const handleCancelDeleteConnectionMode = \(\) => \{[\s\S]*?\n  \};/,
  );
  assert.match(fnMatch[0], /setMode\('point'\)/);
});

// ── 14. Dijkstra/routing/graph-generation code was never touched ───────────

test('AdminMapScreen.jsx: the delete-connection feature code never imports or calls a route-generation/Dijkstra endpoint', () => {
  // Tightly scoped to just the new handler functions block
  // (isVerticalConnectorEdge through handleConfirmDeleteConnection) — from
  // its own start marker to the component's single top-level `return (`,
  // which immediately follows it. Deliberately NOT the wider state-
  // declarations-to-SVG-overlay span, since that span legitimately
  // contains pre-existing Draw Walkable Path / Test Route code that DOES
  // call createRouteEdge/createRoutePoint/calculateRoute — this test must
  // only guard the code THIS feature added.
  const featureSection = source.slice(
    source.indexOf('const isVerticalConnectorEdge = (edge) =>'),
    source.indexOf('\n  return ('),
  );
  assert.ok(featureSection.includes('handleConfirmDeleteConnection'));
  assert.ok(featureSection.includes('handleEdgeClickForDeletion'));
  assert.doesNotMatch(featureSection, /generateMapGraph/);
  assert.doesNotMatch(featureSection, /calculateRoute/);
  assert.doesNotMatch(featureSection, /createRouteEdge/);
  assert.doesNotMatch(featureSection, /createRoutePoint/);
});

// ── 15. Multilingual UI: every required translation key exists in en/ar/he,
//        and matches the exact phrases required by the spec ────────────────

const REQUIRED_KEYS = [
  'deleteConnectionMode',
  'deleteConnectionInstructions',
  'deleteConnectionCancelMode',
  'deleteConnectionConfirmTitle',
  'deleteConnectionFromLabel',
  'deleteConnectionToLabel',
  'deleteConnectionTypeLabel',
  'deleteConnectionFloorLabel',
  'deleteConnectionSafetyNote',
  'deleteConnectionConfirmButton',
  'deleteConnectionDeleting',
  'deleteConnectionSuccess',
  'deleteConnectionFailed',
  'deleteConnectionVerticalBlocked',
];

test('AdminMapScreen.jsx: every required Delete Connection translation key exists in en, ar, and he blocks', () => {
  const enBlock = source.slice(source.indexOf('en: {'), source.indexOf('ar: {'));
  const arBlock = source.slice(source.indexOf('ar: {'), source.indexOf('he: {'));
  const heBlock = source.slice(source.indexOf('he: {'), source.length);

  REQUIRED_KEYS.forEach((key) => {
    assert.match(enBlock, new RegExp(`${key}:`), `missing ${key} in en block`);
    assert.match(arBlock, new RegExp(`${key}:`), `missing ${key} in ar block`);
    assert.match(heBlock, new RegExp(`${key}:`), `missing ${key} in he block`);
  });
});

test('AdminMapScreen.jsx: English mode name and confirmation strings match the spec exactly', () => {
  assert.match(source, /deleteConnectionMode: 'Delete Connection'/);
  assert.match(source, /deleteConnectionInstructions: 'Click an existing connection to select it for deletion\.'/);
  assert.match(source, /deleteConnectionSafetyNote: 'This removes only the connection\. Both points will remain\.'/);
  assert.match(source, /deleteConnectionConfirmButton: 'Delete Connection'/);
  assert.match(source, /deleteConnectionSuccess: 'Connection deleted successfully'/);
  assert.match(source, /deleteConnectionVerticalBlocked: 'Manage this connection from Vertical Connections\.'/);
});

test('AdminMapScreen.jsx: Arabic mode name and confirmation strings match the spec exactly', () => {
  assert.match(source, /deleteConnectionMode: 'حذف ربط'/);
  assert.match(source, /deleteConnectionSafetyNote: 'سيتم حذف الربط فقط، وستبقى النقطتان\.'/);
  assert.match(source, /deleteConnectionConfirmButton: 'حذف الربط'/);
  assert.match(source, /deleteConnectionSuccess: 'تم حذف الربط بنجاح'/);
  assert.match(source, /deleteConnectionVerticalBlocked: 'عدّلي هذا الربط من قسم الربط بين الطوابق\.'/);
});

test('AdminMapScreen.jsx: Hebrew mode name and confirmation strings match the spec exactly', () => {
  assert.match(source, /deleteConnectionMode: 'מחיקת חיבור'/);
  assert.match(source, /deleteConnectionSafetyNote: 'רק החיבור יימחק ושתי הנקודות יישארו\.'/);
  assert.match(source, /deleteConnectionConfirmButton: 'מחיקת חיבור'/);
  assert.match(source, /deleteConnectionSuccess: 'החיבור נמחק בהצלחה'/);
  assert.match(source, /deleteConnectionVerticalBlocked: 'יש לנהל את החיבור הזה דרך חיבורים בין קומות\.'/);
});

test('AdminMapScreen.jsx: the modal Cancel button reuses the existing shared t.cancel translation (Cancel/إلغاء/ביטול), matching the spec exactly', () => {
  assert.match(source, /cancel: 'Cancel'/);
  assert.match(source, /cancel: 'إلغاء'/);
  assert.match(source, /cancel: 'ביטול'/);

  const modalMatch = source.match(
    /\{mode === 'delete-connection' && selectedEdgeForDeletion && \([\s\S]*?\n        \)\}/,
  );
  assert.match(modalMatch[0], /onClick=\{handleCancelDeleteConnectionSelection\}[\s\S]*?\{t\.cancel\}/);
});

console.log(`\n${passed} test(s) passed.`);
if (process.exitCode) {
  console.error('Some tests FAILED.');
} else {
  console.log('All tests passed.');
}
