import { useState } from 'react';

import FloatingToolPanel from './FloatingToolPanel';

// Read-only control panel for the Automatic Navigation Build preview
// (Phase A). Layer toggles on the left of the map, counts and refusals
// below them.
//
// This lives in its own component rather than inside AdminMapScreen.jsx
// on purpose: that file is already over 500 KB, past the point where
// Babel stops pretty-printing it, and it does not need to carry another
// panel's worth of markup.
//
// Nothing here can write. There is no apply button because there is no
// apply endpoint — the whole point of Phase A is to look at the proposal
// on a real floor plan before anything is persisted.
//
// The panel used to be a fixed box pinned to top-left of the workspace.
// It now renders through the shared FloatingToolPanel, so it can be
// dragged, collapsed and raised like every other map panel. All drag /
// collapse / stacking state stays owned by AdminMapScreen and arrives
// through `panelProps` — this component still owns no position state of
// its own, and its contents are unchanged.

const LAYER_SWATCHES = {
  region: { color: '#1b7f4b', label: 'Building region' },
  rejected: { color: '#b03030', label: 'Rejected areas' },
  graph: { color: '#2d6cdf', label: 'Transit graph' },
  arrivals: { color: '#e08a00', label: 'Room arrival points' },
  attachments: { color: '#7a4bd0', label: 'Room connections' },
  rejectedEdges: { color: '#c0392b', label: 'Rejected edges' },
};

function Row({ label, value }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10 }}>
      <span style={{ color: '#5a7a9f' }}>{label}</span>
      <strong style={{ color: '#173b70' }}>{value}</strong>
    </div>
  );
}

export default function NavigationBuildPreviewPanel({
  result,
  loading,
  error,
  layers,
  onToggleLayer,
  onRun,
  onClose,
  strings,
  // Everything FloatingToolPanel needs (position, collapsed, zIndex,
  // containerRef, labels…), assembled by AdminMapScreen so all the
  // converted map panels are wired identically.
  panelProps,
}) {
  const [showDiagnostics, setShowDiagnostics] = useState(false);

  const t = strings || {};
  const diagnostics = result?.diagnostics || {};
  const rooms = result?.rooms || [];
  const review = diagnostics.rooms_requiring_review || [];

  return (
    <FloatingToolPanel
      title={t.navBuildTitle || 'Automatic Navigation Build'}
      {...panelProps}
      footer={
        <div className="adm-form-actions">
          <button
            type="button"
            className="adm-btn adm-btn-secondary"
            onClick={onClose}
            style={{ flex: 1 }}
          >
            {t.calibrateClose || 'Close'}
          </button>
        </div>
      }
    >
      <div style={{ fontSize: 12.5, color: '#4a6a8f' }}>
      <div
        style={{
          background: '#eaf2fd',
          border: '1px solid #c5daf5',
          borderRadius: 8,
          padding: 8,
          marginBottom: 12,
          color: '#1b4d8f',
        }}
      >
        {t.navBuildReadOnly ||
          'Preview only — nothing is saved. No rooms, points, connections or QR codes are created.'}
      </div>

      <button
        type="button"
        onClick={onRun}
        disabled={loading}
        style={{
          width: '100%',
          border: 'none',
          borderRadius: 8,
          padding: '10px 12px',
          fontSize: 13,
          fontWeight: 700,
          cursor: loading ? 'default' : 'pointer',
          background: loading ? '#c7d6ea' : '#173b70',
          color: 'white',
          marginBottom: 12,
        }}
      >
        {loading
          ? t.navBuildRunning || 'Analyzing the floor plan…'
          : t.navBuildRun || 'Preview Automatic Navigation Build'}
      </button>

      {error && (
        <div
          style={{
            background: '#fdecea',
            border: '1px solid #f5c6c2',
            borderRadius: 8,
            padding: 8,
            marginBottom: 12,
            color: '#8b2a20',
          }}
        >
          {error}
        </div>
      )}

      {result && !result.available && (
        <div
          style={{
            background: '#fff6e6',
            border: '1px solid #f0d9a8',
            borderRadius: 8,
            padding: 8,
            marginBottom: 12,
            color: '#7a5200',
          }}
        >
          <div style={{ fontWeight: 700, marginBottom: 3 }}>
            {t.navBuildRefused || 'Nothing could be generated for this map.'}
          </div>
          <div>{result.reason}</div>
          {result.failed_stage && (
            <div style={{ marginTop: 4, fontSize: 11, color: '#9a7330' }}>
              {(t.navBuildStage || 'Stage')}: {result.failed_stage}
            </div>
          )}
        </div>
      )}

      {result && (
        <>
          <div style={{ marginBottom: 12 }}>
            <div style={{ fontWeight: 700, color: '#173b70', marginBottom: 6 }}>
              {t.navBuildLayers || 'Show on the map'}
            </div>
            {Object.entries(LAYER_SWATCHES).map(([key, swatch]) => (
              <label
                key={key}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 8,
                  padding: '3px 0',
                  cursor: 'pointer',
                }}
              >
                <input
                  type="checkbox"
                  checked={Boolean(layers[key])}
                  onChange={() => onToggleLayer(key)}
                />
                <span
                  style={{
                    width: 12,
                    height: 12,
                    borderRadius: 3,
                    background: swatch.color,
                    display: 'inline-block',
                  }}
                />
                <span>{t[`navBuildLayer_${key}`] || swatch.label}</span>
              </label>
            ))}
          </div>

          <div
            style={{
              borderTop: '1px solid #e3e9f2',
              paddingTop: 10,
              marginBottom: 10,
              lineHeight: 1.9,
            }}
          >
            <Row
              label={t.navBuildTransitNodes || 'Transit nodes proposed'}
              value={diagnostics.proposed_node_count ?? 0}
            />
            <Row
              label={t.navBuildTransitEdges || 'Transit connections proposed'}
              value={diagnostics.proposed_edge_count ?? 0}
            />
            <Row
              label={t.navBuildRoomsPositioned || 'Rooms positioned automatically'}
              value={diagnostics.final_auto_positioned_room_count ?? 0}
            />
            <Row
              label={t.navBuildRoomsConnected || 'Rooms connected to the graph'}
              value={diagnostics.final_auto_connected_room_count ?? 0}
            />
            <Row
              label={t.navBuildAcceptedRooms || 'Accepted rooms scanned'}
              value={diagnostics.accepted_semantic_room_count ?? 0}
            />
            <Row
              label={t.navBuildWouldCreateQr || 'QR codes an apply WOULD create'}
              value={result.location_codes_would_be_created ?? 0}
            />
          </div>

          {review.length > 0 && (
            <div
              style={{
                borderTop: '1px solid #e3e9f2',
                paddingTop: 10,
                marginBottom: 10,
              }}
            >
              <div style={{ fontWeight: 700, color: '#7a5200', marginBottom: 4 }}>
                {t.navBuildNeedsReview || 'Rooms that still need you'}
                {` (${review.length})`}
              </div>
              <ul style={{ margin: 0, paddingInlineStart: 16, lineHeight: 1.7 }}>
                {review.map((entry) => (
                  <li key={entry.semantic_item_id}>
                    <strong>{entry.room_name || entry.semantic_item_id}</strong>
                    {' — '}
                    {entry.reason}
                  </li>
                ))}
              </ul>
            </div>
          )}

          <button
            type="button"
            onClick={() => setShowDiagnostics((previous) => !previous)}
            style={{
              width: '100%',
              border: '1px solid #d5e0ef',
              borderRadius: 8,
              padding: '7px 10px',
              fontSize: 12,
              cursor: 'pointer',
              background: 'white',
              color: '#4a6a8f',
            }}
          >
            {showDiagnostics
              ? t.navBuildHideDiagnostics || 'Hide diagnostics'
              : t.navBuildShowDiagnostics || 'Show diagnostics'}
          </button>

          {showDiagnostics && (
            <pre
              style={{
                marginTop: 8,
                background: '#f6f9fd',
                border: '1px solid #e3e9f2',
                borderRadius: 8,
                padding: 8,
                fontSize: 10.5,
                lineHeight: 1.5,
                whiteSpace: 'pre-wrap',
                wordBreak: 'break-word',
                maxHeight: 260,
                overflowY: 'auto',
                color: '#4a6a8f',
              }}
            >
              {JSON.stringify(diagnostics, null, 2)}
            </pre>
          )}

          {rooms.length > 0 && (
            <div style={{ marginTop: 10, fontSize: 11, color: '#8ba0bd' }}>
              {(t.navBuildLabelSource || 'Labels read from')}
              {': '}
              {diagnostics.label_source}
              {diagnostics.label_source_reason
                ? ` — ${diagnostics.label_source_reason}`
                : ''}
            </div>
          )}
        </>
      )}
      </div>
    </FloatingToolPanel>
  );
}
