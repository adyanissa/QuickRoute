import FloatingToolPanel from './FloatingToolPanel';

// Review and repair panel for legacy invalid connections — walkway edges
// created before the Auto Connect correction that route through ordinary
// destination rooms.
//
// Deliberately small. It shows the counts the admin needs to decide, lists
// the findings with human-facing names, and offers one Repair action. It
// owns no analysis of its own: every classification, and the decision about
// what is safe to repair automatically, comes from
// backend/services/legacy_edge_repair_service.py.
//
// Two kinds of finding are reported but NEVER repaired automatically:
// a room the corridor may be relying on to stay connected, and a
// destination whose every edge is invalid. Both need a human to look at
// the drawing, so they are listed under "needs review" with the reason the
// backend gave, and the Repair button never touches them.

const KIND_STYLES = {
  room_to_room: { color: '#a92323', background: '#ffe9e9' },
  stale_attachment: { color: '#a92323', background: '#ffe9e9' },
  room_used_as_transit_bridge: { color: '#7a5200', background: '#fff6e6' },
  only_invalid_edges: { color: '#7a5200', background: '#fff6e6' },
};

function Row({ label, value, strong }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10 }}>
      <span style={{ color: '#5a7a9f' }}>{label}</span>
      <strong style={{ color: strong ? '#a92323' : '#173b70' }}>{value}</strong>
    </div>
  );
}

export default function LegacyConnectionsPanel({
  preview,
  applyResult,
  loading,
  applying,
  error,
  onScan,
  onRepair,
  onClose,
  strings,
  panelProps,
}) {
  const t = strings || {};
  const findings = preview?.findings || [];
  const repairable = findings.filter((finding) => finding.repairable);
  const review = findings.filter((finding) => !finding.repairable);

  return (
    <FloatingToolPanel
      title={t.legacyRepairTitle || 'Legacy Connections'}
      {...panelProps}
      footer={
        <div className="adm-form-actions" style={{ flexWrap: 'wrap', gap: 8 }}>
          <button
            type="button"
            className="adm-btn adm-btn-secondary"
            onClick={onScan}
            disabled={loading || applying}
            style={{ flex: 1 }}
          >
            {loading ? t.legacyRepairScanning : t.legacyRepairScan}
          </button>

          <button
            type="button"
            className="adm-btn adm-btn-primary"
            onClick={onRepair}
            disabled={loading || applying || repairable.length === 0}
            style={{ flex: 1 }}
          >
            {applying ? t.legacyRepairRepairing : t.legacyRepairRepair}
          </button>

          <button
            type="button"
            className="adm-btn adm-btn-cancel"
            onClick={onClose}
            disabled={applying}
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
          {t.legacyRepairIntro}
        </div>

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

        {preview && (
          <div style={{ lineHeight: 1.9, marginBottom: 12 }}>
            <Row label={t.legacyRepairScanned} value={preview.scanned_edges ?? 0} />
            <Row
              label={t.legacyRepairScannedDestinations}
              value={preview.scanned_destinations ?? 0}
            />
            <Row
              label={t.legacyRepairInvalid}
              value={preview.invalid_edges ?? 0}
              strong={(preview.invalid_edges ?? 0) > 0}
            />
            <Row
              label={t.legacyRepairNeedsReview}
              value={preview.needs_review ?? 0}
            />
          </div>
        )}

        {applyResult && (
          <div
            style={{
              background: '#eafaf0',
              border: '1px solid #bfe6cd',
              borderRadius: 8,
              padding: 8,
              marginBottom: 12,
              color: '#1a7f37',
              lineHeight: 1.9,
            }}
          >
            <Row label={t.legacyRepairRepaired} value={applyResult.repaired ?? 0} />
            <Row
              label={t.legacyRepairReconnected}
              value={applyResult.reconnected ?? 0}
            />
            <Row
              label={t.legacyRepairStillNeedsReview}
              value={applyResult.still_needs_review ?? 0}
            />
          </div>
        )}

        {repairable.length > 0 && (
          <div style={{ marginBottom: 12 }}>
            <div style={{ fontWeight: 700, color: '#a92323', marginBottom: 6 }}>
              {t.legacyRepairInvalidList} ({repairable.length})
            </div>
            {repairable.map((finding) => (
              <div
                key={finding.edge_id}
                style={{
                  ...KIND_STYLES[finding.kind],
                  borderRadius: 8,
                  padding: 8,
                  marginBottom: 6,
                  fontSize: 11.5,
                  lineHeight: 1.6,
                }}
              >
                <strong>
                  {finding.from_name} ↔ {finding.to_name}
                </strong>
                <div>{finding.detail}</div>
              </div>
            ))}
          </div>
        )}

        {review.length > 0 && (
          <div>
            <div style={{ fontWeight: 700, color: '#7a5200', marginBottom: 6 }}>
              {t.legacyRepairReviewList} ({review.length})
            </div>
            {review.map((finding, index) => (
              <div
                key={`${finding.kind}-${finding.point_id || index}`}
                style={{
                  ...KIND_STYLES[finding.kind],
                  borderRadius: 8,
                  padding: 8,
                  marginBottom: 6,
                  fontSize: 11.5,
                  lineHeight: 1.6,
                }}
              >
                <strong>{finding.room_name || finding.from_name}</strong>
                <div>{finding.detail}</div>
              </div>
            ))}
          </div>
        )}

        {preview && findings.length === 0 && (
          <div style={{ color: '#1a7f37', fontWeight: 600 }}>
            {t.legacyRepairNothingFound}
          </div>
        )}
      </div>
    </FloatingToolPanel>
  );
}
