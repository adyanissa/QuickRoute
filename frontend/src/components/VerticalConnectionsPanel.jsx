import { useCallback, useEffect, useState } from 'react';
import FloatingToolPanel from './FloatingToolPanel';
import {
  getVerticalConnectors,
  createVerticalConnector,
  updateVerticalConnector,
  deleteVerticalConnector,
  addConnectorStop,
  removeConnectorStop,
  validateMapGroupNavigation,
} from '../api/verticalConnectorsApi';
const CONNECTOR_TYPES = ['elevator', 'stairs', 'escalator', 'ramp'];

const badgeStyle = (bg, color) => ({
  display: 'inline-block',
  padding: '2px 8px',
  borderRadius: 999,
  fontSize: 10.5,
  fontWeight: 700,
  background: bg,
  color,
  marginInlineEnd: 6,
});

// Admin "Vertical Connections" panel (PHASE 4/5/15): create/manage
// elevators/stairs/escalators/ramps for the current Map Group, place a
// stop on each floor by clicking that floor's own map image (never
// inferred from another floor's coordinates), and run the "Validate
// Multi-Floor Navigation" report before trusting the group for real
// navigation.
//
// Deliberately a standalone component (rather than more inline state in
// the already-very-large AdminMapScreen.jsx) — AdminMapScreen only needs
// to: (1) add a 'connector' mode button, (2) forward map clicks in that
// mode as `pendingClick`, (3) refresh its own route points/edges via
// `onStopsChanged` after a stop is placed/removed so the new marker shows
// up immediately.
const VerticalConnectionsPanel = ({
  t,
  activeMap,
  mapGroup,
  // Floor control — same real, always-editable <select> the other tool
  // panels use, sourced from AdminMapScreen's own floorSelectOptions /
  // selectedMapId / handleFloorSwitch (never independent state here, so
  // the selected floor and selected map can never disagree — see
  // AdminMapScreen.jsx's `floorSelectOptions` comment).
  floorOptions,
  selectedMapId,
  onFloorChange,
  floorLabel,
  pendingClick,
  onClickConsumed,
  onStopsChanged,
  position,
  onPositionChange,
  isCollapsed,
  onToggleCollapse,
  onDragStateChange,
  containerRef,
  isRTL,
  snapTopOffset,
}) => {
  const [connectors, setConnectors] = useState([]);
  const [isLoading, setIsLoading] = useState(false);
  const [loadError, setLoadError] = useState('');

  const [showCreateForm, setShowCreateForm] = useState(false);
  const [createForm, setCreateForm] = useState({
    connectorType: 'elevator',
    name: '',
    code: '',
    isBidirectional: true,
    isAccessible: true,
    waitTimeSeconds: 30,
    secondsPerFloor: 6,
    distancePerFloorMeters: 4,
  });
  const [createError, setCreateError] = useState('');
  const [isCreating, setIsCreating] = useState(false);

  const [selectedConnectorId, setSelectedConnectorId] = useState('');
  const [placementError, setPlacementError] = useState('');
  const [isPlacing, setIsPlacing] = useState(false);

  const [validation, setValidation] = useState(null);
  const [isValidating, setIsValidating] = useState(false);
  const [validationError, setValidationError] = useState('');

  const mapGroupId = activeMap?.mapGroupId || null;

  const loadConnectors = useCallback(async () => {
    if (!mapGroupId) {
      setConnectors([]);
      return;
    }
    setIsLoading(true);
    setLoadError('');
    try {
      const list = await getVerticalConnectors({ mapGroupId });
      setConnectors(list);
    } catch (error) {
      setLoadError(error.message || 'Failed to load vertical connectors');
    } finally {
      setIsLoading(false);
    }
  }, [mapGroupId]);

  useEffect(() => {
    loadConnectors();
  }, [loadConnectors]);

  // A pending click only ever arrives while this panel's own 'connector'
  // mode is active (AdminMapScreen guarantees that), so any click here is
  // a real admin click on the CURRENT floor's own map image.
  useEffect(() => {
    if (!pendingClick || !selectedConnectorId || !activeMap?.id) {
      return;
    }

    let cancelled = false;

    (async () => {
      setIsPlacing(true);
      setPlacementError('');
      try {
        await addConnectorStop(selectedConnectorId, {
          mapId: activeMap.id,
          x: pendingClick.x,
          y: pendingClick.y,
          autoConnect: 'nearest',
        });
        if (!cancelled) {
          await loadConnectors();
          onStopsChanged?.();
        }
      } catch (error) {
        if (!cancelled) {
          setPlacementError(error.message || 'Failed to place connector stop');
        }
      } finally {
        if (!cancelled) {
          setIsPlacing(false);
          onClickConsumed?.();
        }
      }
    })();

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pendingClick]);

  const setCreateField = (field, value) =>
    setCreateForm((previous) => ({ ...previous, [field]: value }));

  const handleCreateConnector = async () => {
    setCreateError('');

    if (!activeMap?.buildingId || !mapGroupId) {
      setCreateError(
        'This floor is not part of a Map Group yet — vertical connectors require a multi-floor Map Group.',
      );
      return;
    }
    if (!createForm.name.trim()) {
      setCreateError('Connector name is required.');
      return;
    }

    setIsCreating(true);
    try {
      await createVerticalConnector({
        buildingId: activeMap.buildingId,
        mapGroupId,
        name: createForm.name.trim(),
        connectorCode: createForm.code.trim() || undefined,
        connectorType: createForm.connectorType,
        isBidirectional: createForm.isBidirectional,
        isAccessible: createForm.isAccessible,
        waitTimeSeconds: Number(createForm.waitTimeSeconds) || 0,
        secondsPerFloor: Number(createForm.secondsPerFloor) || 0,
        distancePerFloorMeters: Number(createForm.distancePerFloorMeters) || 0,
      });
      setCreateForm({
        connectorType: 'elevator',
        name: '',
        code: '',
        isBidirectional: true,
        isAccessible: true,
        waitTimeSeconds: 30,
        secondsPerFloor: 6,
        distancePerFloorMeters: 4,
      });
      setShowCreateForm(false);
      await loadConnectors();
    } catch (error) {
      setCreateError(error.message || 'Failed to create connector');
    } finally {
      setIsCreating(false);
    }
  };

  const handleToggleActive = async (connector) => {
    try {
      await updateVerticalConnector(connector.id, { isActive: !connector.isActive });
      await loadConnectors();
    } catch (error) {
      setLoadError(error.message || 'Failed to update connector');
    }
  };

  const handleDeleteConnector = async (connector) => {
    if (!window.confirm(`Delete ${connector.name}? Its transition edges will be removed; the stop points on each floor stay in place as ordinary corridor points.`)) {
      return;
    }
    try {
      await deleteVerticalConnector(connector.id);
      if (selectedConnectorId === connector.id) setSelectedConnectorId('');
      await loadConnectors();
      onStopsChanged?.();
    } catch (error) {
      setLoadError(error.message || 'Failed to delete connector');
    }
  };

  const handleRemoveStop = async (connector, stop) => {
    try {
      await removeConnectorStop(connector.id, stop.routePointId || stop.route_point_id);
      await loadConnectors();
      onStopsChanged?.();
    } catch (error) {
      setLoadError(error.message || 'Failed to remove stop');
    }
  };

  const handleValidate = async () => {
    if (!mapGroupId) return;
    setIsValidating(true);
    setValidationError('');
    setValidation(null);
    try {
      const result = await validateMapGroupNavigation(mapGroupId);
      setValidation(result);
    } catch (error) {
      setValidationError(error.message || 'Validation failed');
    } finally {
      setIsValidating(false);
    }
  };

  if (!position) return null;

  return (
    <FloatingToolPanel
      title={t?.verticalConnectionsTitle || 'Vertical Connections'}
      position={position}
      onPositionChange={onPositionChange}
      isCollapsed={isCollapsed}
      onToggleCollapse={onToggleCollapse}
      onDragStateChange={onDragStateChange}
      containerRef={containerRef}
      snapTopOffset={snapTopOffset}
      isRTL={isRTL}
      showSnapControls
      width={340}
      footer={
        <div className="adm-form-actions" style={{ flexWrap: 'wrap', gap: 8 }}>
          <button
            type="button"
            className="adm-btn adm-btn-cancel"
            onClick={() => setShowCreateForm((prev) => !prev)}
          >
            {showCreateForm ? 'Cancel' : '+ Add Connector'}
          </button>
          <button
            type="button"
            className="adm-btn adm-btn-primary"
            disabled={!mapGroupId || isValidating}
            onClick={handleValidate}
          >
            {isValidating ? 'Validating…' : 'Validate Multi-Floor Navigation'}
          </button>
        </div>
      }
    >
      {Array.isArray(floorOptions) && floorOptions.length > 0 && (
        <div className="adm-form-group">
          <label className="adm-form-label" htmlFor="floor-select-connector">
            {floorLabel || 'Floor'}
          </label>
          <select
            id="floor-select-connector"
            className="adm-form-input"
            value={selectedMapId || ''}
            onChange={(event) => onFloorChange?.(event.target.value)}
          >
            {floorOptions.map((floorMap) => (
              <option key={floorMap.mapId} value={floorMap.mapId}>
                {floorMap.floorLabel}
              </option>
            ))}
          </select>
        </div>
      )}

      {!mapGroupId && (
        <div style={{ padding: 8, fontSize: 12.5, color: '#b42318', fontWeight: 600 }}>
          This floor map does not belong to a Map Group. Vertical connectors
          (elevators/stairs/escalators/ramps) only make sense between floors
          of the same multi-floor Map Group.
        </div>
      )}

      {mapGroupId && (
        <>
          {loadError && (
            <div style={{ marginBottom: 8, padding: 8, borderRadius: 8, background: '#fff0f0', color: '#b42318', fontSize: 12, fontWeight: 600 }}>
              {loadError}
            </div>
          )}

          {showCreateForm && (
            <div style={{ marginBottom: 12, padding: 10, borderRadius: 10, background: '#f4f7fb' }}>
              <div className="adm-form-group">
                <label className="adm-form-label">Type</label>
                <select
                  className="adm-form-input"
                  value={createForm.connectorType}
                  onChange={(e) => setCreateField('connectorType', e.target.value)}
                >
                  {CONNECTOR_TYPES.map((ct) => (
                    <option key={ct} value={ct}>
                      {ct.charAt(0).toUpperCase() + ct.slice(1)}
                    </option>
                  ))}
                </select>
              </div>
              <div className="adm-form-group">
                <label className="adm-form-label">Name</label>
                <input
                  className="adm-form-input"
                  value={createForm.name}
                  onChange={(e) => setCreateField('name', e.target.value)}
                  placeholder="Elevator A"
                />
              </div>
              <div className="adm-form-group">
                <label className="adm-form-label">Code (optional)</label>
                <input
                  className="adm-form-input"
                  value={createForm.code}
                  onChange={(e) => setCreateField('code', e.target.value)}
                  placeholder="ELEVATOR-A"
                />
              </div>
              <div style={{ display: 'flex', gap: 12, marginBottom: 8 }}>
                <label style={{ fontSize: 12, display: 'flex', alignItems: 'center', gap: 4 }}>
                  <input
                    type="checkbox"
                    checked={createForm.isBidirectional}
                    onChange={(e) => setCreateField('isBidirectional', e.target.checked)}
                  />
                  Bidirectional
                </label>
                <label style={{ fontSize: 12, display: 'flex', alignItems: 'center', gap: 4 }}>
                  <input
                    type="checkbox"
                    checked={createForm.isAccessible}
                    onChange={(e) => setCreateField('isAccessible', e.target.checked)}
                  />
                  Accessible
                </label>
              </div>
              <div style={{ display: 'flex', gap: 8, marginBottom: 8 }}>
                <div className="adm-form-group" style={{ flex: 1 }}>
                  <label className="adm-form-label">Wait (s)</label>
                  <input
                    type="number"
                    min="0"
                    className="adm-form-input"
                    value={createForm.waitTimeSeconds}
                    onChange={(e) => setCreateField('waitTimeSeconds', e.target.value)}
                  />
                </div>
                <div className="adm-form-group" style={{ flex: 1 }}>
                  <label className="adm-form-label">Sec/floor</label>
                  <input
                    type="number"
                    min="0"
                    className="adm-form-input"
                    value={createForm.secondsPerFloor}
                    onChange={(e) => setCreateField('secondsPerFloor', e.target.value)}
                  />
                </div>
                <div className="adm-form-group" style={{ flex: 1 }}>
                  <label className="adm-form-label">m/floor</label>
                  <input
                    type="number"
                    min="0"
                    className="adm-form-input"
                    value={createForm.distancePerFloorMeters}
                    onChange={(e) => setCreateField('distancePerFloorMeters', e.target.value)}
                  />
                </div>
              </div>
              {createError && (
                <div style={{ marginBottom: 8, fontSize: 12, color: '#b42318', fontWeight: 600 }}>
                  {createError}
                </div>
              )}
              <button
                type="button"
                className="adm-btn adm-btn-primary"
                disabled={isCreating}
                onClick={handleCreateConnector}
                style={{ width: '100%' }}
              >
                {isCreating ? 'Creating…' : 'Create Connector'}
              </button>
            </div>
          )}

          {isLoading && <div style={{ fontSize: 12.5, color: '#666' }}>Loading connectors…</div>}

          {!isLoading && connectors.length === 0 && (
            <div style={{ fontSize: 12.5, color: '#666' }}>
              No vertical connectors yet in this Map Group.
            </div>
          )}

          {connectors.map((connector) => (
            <div
              key={connector.id}
              style={{
                marginBottom: 10,
                padding: 10,
                borderRadius: 10,
                border:
                  selectedConnectorId === connector.id
                    ? '2px solid #4a7ac8'
                    : '1px solid #e2e8f0',
                background: 'white',
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                <div>
                  <div style={{ fontWeight: 700, fontSize: 13.5, color: '#173b70' }}>
                    {connector.name}
                  </div>
                  <div style={{ fontSize: 11, color: '#8291a8' }}>{connector.connectorCode}</div>
                </div>
                <div>
                  <span style={badgeStyle(connector.isActive ? '#eafaf0' : '#fff0f0', connector.isActive ? '#1a7f37' : '#b42318')}>
                    {connector.isActive ? 'Active' : 'Inactive'}
                  </span>
                </div>
              </div>

              <div style={{ margin: '6px 0' }}>
                <span style={badgeStyle('#eef2ff', '#3b4ca0')}>{connector.connectorType}</span>
                {connector.isAccessible && <span style={badgeStyle('#eafaf0', '#1a7f37')}>Accessible</span>}
                {connector.isBidirectional && <span style={badgeStyle('#f4f7fb', '#4a5568')}>Bidirectional</span>}
                <span style={badgeStyle(connector.isFullyConnected ? '#eafaf0' : '#fff8e6', connector.isFullyConnected ? '#1a7f37' : '#9a6700')}>
                  {connector.isFullyConnected ? 'Connected' : 'Not fully connected'}
                </span>
              </div>

              <div style={{ fontSize: 11.5, color: '#4a5568', marginBottom: 6 }}>
                Serves Floors: {connector.stops.length
                  ? connector.stops.map((s) => (s.floor ?? '?')).join(', ')
                  : 'none yet'}
              </div>

              {connector.stops.map((stop) => (
                <div
                  key={stop.routePointId}
                  style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    fontSize: 11.5,
                    padding: '3px 0',
                  }}
                >
                  <span>
                    Floor {stop.floor}: {stop.connectedToFloorGraph ? '✅ connected to floor graph' : '⚠️ not connected to floor graph'}
                  </span>
                  <button
                    type="button"
                    onClick={() => handleRemoveStop(connector, stop)}
                    style={{ border: 'none', background: 'none', color: '#b42318', cursor: 'pointer', fontSize: 11, fontWeight: 700 }}
                  >
                    Remove
                  </button>
                </div>
              ))}

              <div style={{ display: 'flex', gap: 6, marginTop: 8, flexWrap: 'wrap' }}>
                <button
                  type="button"
                  className="adm-btn adm-btn-cancel"
                  style={{ fontSize: 11, padding: '5px 10px' }}
                  onClick={() =>
                    setSelectedConnectorId((prev) => (prev === connector.id ? '' : connector.id))
                  }
                >
                  {selectedConnectorId === connector.id
                    ? 'Stop placing'
                    : `Place stop on Floor ${activeMap?.floor ?? '?'}`}
                </button>
                <button
                  type="button"
                  className="adm-btn adm-btn-cancel"
                  style={{ fontSize: 11, padding: '5px 10px' }}
                  onClick={() => handleToggleActive(connector)}
                >
                  {connector.isActive ? 'Deactivate' : 'Activate'}
                </button>
                <button
                  type="button"
                  style={{ border: 'none', background: 'none', color: '#b42318', cursor: 'pointer', fontSize: 11, fontWeight: 700 }}
                  onClick={() => handleDeleteConnector(connector)}
                >
                  Delete
                </button>
              </div>
            </div>
          ))}

          {selectedConnectorId && (
            <div style={{ marginTop: 4, padding: 8, borderRadius: 8, background: '#eef4ff', fontSize: 11.5, color: '#173b70', fontWeight: 600 }}>
              {isPlacing
                ? 'Placing stop…'
                : `Click the real location of this connector on Floor ${activeMap?.floor ?? '?'}'s map.`}
            </div>
          )}
          {placementError && (
            <div style={{ marginTop: 6, fontSize: 11.5, color: '#b42318', fontWeight: 600 }}>
              {placementError}
            </div>
          )}

          {validationError && (
            <div style={{ marginTop: 10, padding: 8, borderRadius: 8, background: '#fff0f0', color: '#b42318', fontSize: 12, fontWeight: 600 }}>
              {validationError}
            </div>
          )}

          {validation && (
            <div
              style={{
                marginTop: 10,
                padding: 10,
                borderRadius: 10,
                background: validation.ready ? '#eafaf0' : '#fff8e6',
              }}
            >
              <div style={{ fontWeight: 700, fontSize: 13, color: validation.ready ? '#1a7f37' : '#9a6700', marginBottom: 6 }}>
                {validation.ready
                  ? 'Ready for navigation'
                  : `${validation.issue_count} issue(s) found`}
              </div>
              {!validation.ready && (
                <ul style={{ margin: 0, paddingInlineStart: 18, fontSize: 11.5, color: '#4a5568' }}>
                  {validation.issues.map((issue, index) => (
                    <li key={index} style={{ marginBottom: 4 }}>
                      {issue.message}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </>
      )}
    </FloatingToolPanel>
  );
};

export default VerticalConnectionsPanel;
