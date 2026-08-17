// Dependency-free source-contract tests for the admin shell's LAYOUT and
// the Floor Workspace's Danger Zone — the two things this pass fixed.
// Same style as the repo's other layout tests (floatingToolPanelLayout,
// fullMapWorkspaceLayout): assert the CSS/JSX contracts that the bugs
// violated, so a future edit cannot quietly reintroduce them.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const read = (...parts) => fs.readFileSync(path.join(__dirname, '..', ...parts), 'utf8');

const globalCss = read('styles', 'global.css');
const shellCss = read('styles', 'dashboardShell.css');
const pagesCss = read('styles', 'adminShellPages.css');
const adminLayout = read('components', 'dashboard', 'AdminLayout.jsx');
const floorWorkspace = read('screens', 'admin', 'FloorWorkspaceScreen.jsx');
const app = read('App.jsx');

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

// Strips comments so a rule quoted inside an explanatory comment can never
// satisfy (or trip) an assertion about the real declarations.
const rules = (css) => css.replace(/\/\*[\s\S]*?\*\//g, '');

// ── Scroll model ───────────────────────────────────────────────────────

test('html/body/#root are never pinned to exactly one viewport', () => {
  const css = rules(globalCss);
  // The exact rule that caused the bug: `html, body, #root { height: 100% }`
  // made the shell one viewport tall while its content kept going.
  assert.equal(/html[^{]*,[^{]*#root\s*{[^}]*[^-]height:\s*100%/.test(css), false);
  assert.match(css, /html\s*{[^}]*min-height:\s*100%/);
  assert.match(css, /body,\s*#root\s*{[^}]*min-height:\s*100vh/);
  assert.match(css, /body,\s*#root\s*{[^}]*min-height:\s*100dvh/);
});

test('the root element paints the app background, so no canvas colour shows through', () => {
  // src/index.css declares `color-scheme: light dark` and paints the root
  // element a dark colour, which propagates to the canvas. Both are pinned
  // in global.css (loaded after it) or the dark strip comes back.
  const css = rules(globalCss);
  // Declared on :root, not html — index.css's own `:root` block has higher
  // specificity than a type selector and would otherwise win.
  assert.match(css, /:root\s*{[^}]*background:\s*var\(--bg-primary\)/);
  assert.match(css, /:root\s*{[^}]*color-scheme:\s*light\s*;/);
});

test('the admin shell grows with its content instead of being shrunk back', () => {
  const css = rules(shellCss);
  assert.match(css, /\.qrd-root\s*{[^}]*flex:\s*1\s+0\s+auto/);
  assert.match(css, /\.qrd-root\s*{[^}]*min-height:\s*100vh/);
});

test('nothing in the admin shell creates a second vertical scroll container', () => {
  for (const css of [rules(shellCss), rules(pagesCss)]) {
    assert.equal(/overflow-y:\s*(auto|scroll)/.test(css), false);
    assert.equal(/\.qrd-(root|main|page|pagebody)\s*{[^}]*overflow[^:]*:\s*hidden/.test(css), false);
  }
  // The legacy page body's own scroller is explicitly neutralized so the
  // document stays the single scroll owner.
  assert.match(rules(pagesCss), /\.qrd-page \.adm-content[\s\S]{0,220}overflow:\s*visible/);
});

test('the shell never constrains the content column to a fixed height', () => {
  const css = rules(shellCss);
  assert.equal(/\.qrd-main\s*{[^}]*[^-]height:\s*(100vh|100%)/.test(css), false);
  assert.match(css, /\.qrd-main\s*{[^}]*min-height:\s*100vh/);
});

// ── Shell integrity (must survive the layout fix) ──────────────────────

test('AdminLayout still renders its routed page through an Outlet', () => {
  assert.match(adminLayout, /import\s*{[^}]*Outlet[^}]*}\s*from\s*'react-router-dom'/);
  assert.match(adminLayout, /<Outlet\s*\/>/);
  assert.match(adminLayout, /<DashboardShell/);
});

test('every admin route still renders inside the single shared layout route', () => {
  assert.match(app, /<RequireRole>\s*<AdminLayout \/>\s*<\/RequireRole>/);
  for (const route of ['/screen/05', '/admin/buildings/:buildingId', '/admin/maps/:mapId', '/admin/map', '/admin/invitation-codes']) {
    assert.equal(app.includes(route), true, route);
  }
});

// ── Danger zone ────────────────────────────────────────────────────────

test('the Danger Zone is the FINAL section, after the ordinary tools', () => {
  const toolsIndex = floorWorkspace.indexOf('floorWorkspace.toolsTitle');
  const dangerIndex = floorWorkspace.indexOf('className="qrd-danger"');
  assert.notEqual(toolsIndex, -1);
  assert.notEqual(dangerIndex, -1);
  assert.equal(dangerIndex > toolsIndex, true, 'danger zone must come after the tool grid');
  // ...and nothing else is rendered after it: the danger <section> is the
  // last thing the component returns.
  const tail = floorWorkspace.slice(dangerIndex);
  assert.match(tail, /<\/section>\s*\)\}\s*<\/>\s*\);/);
  assert.equal(tail.includes('<SectionHead'), false);
  assert.equal(tail.includes('<ToolCard'), false);
});

test('the Danger Zone is ONE panel — no ToolCard nested inside it', () => {
  const danger = floorWorkspace.slice(floorWorkspace.indexOf('className="qrd-danger"'));
  assert.equal(danger.includes('<ToolCard'), false);
  assert.equal(danger.includes('qrd-tools'), false);
  assert.match(danger, /className="qrd-danger-btn"/);
});

test('a destructive tool is never rendered as an ordinary tool card', () => {
  // TOOL_ICONS drives the ordinary grid; a `cleanup` entry there would put
  // a destructive action back beside Rooms/Route Points.
  const icons = floorWorkspace.slice(
    floorWorkspace.indexOf('const TOOL_ICONS'),
    floorWorkspace.indexOf('const FloorWorkspaceScreen'),
  );
  assert.equal(/cleanup:\s*</.test(icons), false);
  assert.match(floorWorkspace, /ordinaryTools\s*=\s*tools\.filter\(\(tool\) => !tool\.destructive\)/);
  assert.match(floorWorkspace, /destructiveTools\s*=\s*tools\.filter\(\(tool\) => tool\.destructive\)/);
});

test('the Danger Zone renders only when permission produced a destructive tool', () => {
  // No disabled/locked/"no permission" variant may exist: the whole
  // section is behind a length check on the permission-derived list.
  assert.match(floorWorkspace, /\{destructiveTools\.length > 0 && \(/);
  assert.equal(/disabled/.test(floorWorkspace.slice(floorWorkspace.indexOf('className="qrd-danger"'))), false);
});

test('the Danger Zone navigates to the cleanup screen and never deletes anything itself', () => {
  const danger = floorWorkspace.slice(floorWorkspace.indexOf('className="qrd-danger"'));
  assert.match(danger, /onClick=\{\(\) => navigate\(tool\.route\)\}/);
  // No cleanup/reset API is reachable from this screen at all.
  for (const name of [
    'applyFullMapReset',
    'applyGeneratedGraphCleanup',
    'applyMultiMapFullReset',
    'fetch(',
    'apiRequest',
  ]) {
    assert.equal(floorWorkspace.includes(name), false, name);
  }
});

test('the Danger Zone panel uses logical properties so RTL mirrors with no extra component', () => {
  const css = rules(pagesCss);
  const panel = css.slice(css.indexOf('.qrd-danger {'), css.indexOf('.qrd-danger-btn:hover'));
  assert.equal(/margin-top|margin-left|margin-right|padding-left|padding-right|border-top:/.test(panel), false);
  assert.match(panel, /margin-block-start/);
  assert.equal(/\[dir=['"]rtl['"]\][^{]*\.qrd-danger/.test(css), false);
});

console.log(`\n${passed} passed`);
