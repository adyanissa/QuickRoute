import FloatingToolPanel from './FloatingToolPanel';

// The full-map "Navigation Tools" toolbox.
//
// Replaces the fixed horizontal pill that used to sit across the top of
// the floor plan. That bar grew to eleven buttons, wrapped badly, and
// covered the part of the drawing an admin most needs to look at — the
// middle of the map.
//
// PRESENTATION ONLY. Every tool here is passed in by AdminMapScreen with
// its original onClick and its original active-state expression. This
// component adds no behaviour, owns no mode state, and calls nothing
// itself. Reordering or regrouping the tools cannot change what any of
// them does.
//
// Dragging, collapsing, viewport clamping, keyboard moves and RTL are all
// inherited from FloatingToolPanel, which the map's other panels already
// use — no new dragging code and no new dependency.

export const TOOLBOX_WIDTH = 268;

// Compact line-art glyphs, sized to the text. Deliberately inline rather
// than an icon package: the project has no icon dependency and this UI
// change is not the place to add one.
const ICONS = {
  point: 'M12 21s7-6.1 7-11a7 7 0 1 0-14 0c0 4.9 7 11 7 11z M12 10.5v.01',
  path: 'M4 18h4a4 4 0 0 0 4-4V10a4 4 0 0 1 4-4h4',
  test: 'M5 12h14 M13 6l6 6-6 6',
  connector: 'M12 3v18 M8 7l4-4 4 4 M8 17l4 4 4-4',
  calibrate: 'M3 12h18 M3 9v6 M21 9v6 M12 10v4',
  deleteEdge: 'M5 19L19 5 M8 8l-3 3 M16 16l3-3',
  autoConnect: 'M7 12a3 3 0 1 1-3-3 M17 12a3 3 0 1 0 3 3 M7 12h10',
  destinations: 'M4 6h10 M4 12h16 M4 18h7 M18 4v6 M15 7h6',
  sync: 'M4 12a8 8 0 0 1 13.7-5.7L20 8 M20 12a8 8 0 0 1-13.7 5.7L4 16 M20 4v4h-4 M4 20v-4h4',
  edit: 'M4 20h4L19 9l-4-4L4 16v4z',
  build: 'M12 3l8 4.5v9L12 21l-8-4.5v-9L12 3z M12 12l8-4.5 M12 12v9 M12 12L4 7.5',
};

function ToolIcon({ name }) {
  const path = ICONS[name] || ICONS.point;
  return (
    <svg
      width="15"
      height="15"
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden="true"
      style={{ flexShrink: 0 }}
    >
      {path.split(' M').map((segment, index) => (
        <path
          key={index}
          d={index === 0 ? segment : `M${segment}`}
          stroke="currentColor"
          strokeWidth="1.8"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      ))}
    </svg>
  );
}

function ToolButton({ tool }) {
  const active = Boolean(tool.active);

  return (
    <button
      type="button"
      onClick={tool.onClick}
      title={tool.tooltip || tool.label}
      aria-pressed={active}
      className={`qr-toolbox-button${active ? ' is-active' : ''}`}
    >
      <ToolIcon name={tool.icon} />
      <span className="qr-toolbox-button-label">{tool.label}</span>
    </button>
  );
}

export default function MapToolboxPanel({
  groups,
  position,
  onPositionChange,
  isCollapsed,
  onToggleCollapse,
  onDragStateChange,
  containerRef,
  isRTL = false,
  title = 'Navigation Tools',
  labels = {},
}) {
  return (
    <FloatingToolPanel
      title={title}
      position={position}
      onPositionChange={onPositionChange}
      isCollapsed={isCollapsed}
      onToggleCollapse={onToggleCollapse}
      onDragStateChange={onDragStateChange}
      containerRef={containerRef}
      isRTL={isRTL}
      width={TOOLBOX_WIDTH}
      moveLabel={labels.move}
      minimizeLabel={labels.minimize}
      restoreLabel={labels.restore}
      showSnapControls
      snapLabels={labels.snap}
      className="qr-map-toolbox"
    >
      {groups
        .filter((group) => group.tools.length > 0)
        .map((group) => (
          <div key={group.id} className="qr-toolbox-group">
            <div className="qr-toolbox-group-title">{group.title}</div>
            <div className="qr-toolbox-group-body">
              {group.tools.map((tool) => (
                <ToolButton key={tool.id} tool={tool} />
              ))}
            </div>
          </div>
        ))}
    </FloatingToolPanel>
  );
}
