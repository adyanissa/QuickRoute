import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import { useNavigate, useLocation, useSearchParams } from 'react-router-dom';
import { useLang } from '../context/LangContext';
import {
  getMaps,
  updateMap as apiUpdateMap,
  deleteMap as apiDeleteMap,
  uploadMap as apiUploadMap,
  getMapProcessingStatus,
  normalizeMap,
  previewMapGraph,
  generateMapGraph,
  clearGeneratedMapGraph,
  calibrateMapScale,
  previewGeneratedGraphCleanup,
  applyGeneratedGraphCleanup,
  previewFullMapReset,
  applyFullMapReset,
} from '../api/mapsApi';
import {
  getRoutePoints,
  createRoutePoint,
  updateRoutePoint,
  deleteRoutePoint,
  backfillRoutePointFloorFromMap,
} from '../api/routePointsApi';
import {
  getRouteEdges,
  createRouteEdge,
  deleteRouteEdge,
  previewAutoConnectDestinations,
  applyAutoConnectDestinations,
} from '../api/routeEdgesApi';
import { getBuildings } from '../api/buildingsApi';
import { getRooms, getRoomById, syncRoomsFromRoutePoints } from '../api/roomsApi';
import { getVerticalConnectorById } from '../api/verticalConnectorsApi';
import { calculateRoute } from '../api/navigationApi';
import {
  previewSemanticDestinations,
  previewDestinationAutoPlacement,
  applySemanticDestinations,
} from '../api/mapAnalysisApi';
import {
  getMapGroups,
  createMapGroup as apiCreateMapGroup,
  addMapGroupFloors as apiAddMapGroupFloors,
  deleteMapGroupFloor as apiDeleteMapGroupFloor,
  deleteMapGroup as apiDeleteMapGroup,
} from '../api/mapGroupsApi';
import VerticalConnectionsPanel from '../components/VerticalConnectionsPanel';
import SemanticAnalysisStatusCard from '../components/SemanticAnalysisStatusCard';
import SemanticNameSelector from '../components/SemanticNameSelector';
import {
  createEmptyFloorRow,
  validateFloorRows,
  sortFloorsByNumber,
  groupMapsByMapGroup,
  formatFloorDisplay,
  buildFloorOptions,
  buildFloorEditOptions,
  resolveFloorSwitch,
  resolveMapReferenceStatus,
} from '../utils/mapGroupHelpers';
import {
  findNearestPointWithinThreshold,
  resolveSnapThresholdPx,
} from '../utils/geometry';
import {
  resolveExistingPointSelection,
  partitionDraftForSave,
  buildEdgeKeySet,
  buildEdgePlan,
  computeNearbyMergePreview,
  generateDefaultDraftPointName,
  validateDraftPointName,
  isDraftNamingValid as computeIsDraftNamingValid,
  updateDraftPointName,
} from '../utils/drawPathHelpers';
import {
  clampPanelPosition,
  computeDefaultPanelPosition,
  computeSnapPosition,
} from '../utils/floatingPanelHelpers';
import {
  MAP_PANEL_IDS,
  createInitialMapPanelState,
  getMapPanelWidth,
  raiseMapPanel,
  writeStoredMapPanelState,
} from '../utils/mapPanelLayout';
import { computeOriginalImageCoords } from '../utils/destinationPlacement';
import {
  buildBatchQueueItemIds,
  initialBatchStatuses,
  findNextActiveIndex,
  computeBatchProgress,
  isBatchReadyToSave,
  buildBatchAcceptedPayload,
  buildBatchDraftStorageKey,
  serializeBatchDraft,
  deserializeBatchDraft,
  indexAutoPlacementSuggestions,
  applyAutoPlacementSuggestions,
  buildAutoPlacementReviewList,
} from '../utils/batchDestinationPlacement';
import FloatingToolPanel from '../components/FloatingToolPanel';
import NavigationBuildPreviewPanel from '../components/NavigationBuildPreviewPanel';
import MapToolboxPanel, { TOOLBOX_WIDTH } from '../components/MapToolboxPanel';
import { previewNavigationBuild } from '../api/navigationBuildApi';
import { useAuth } from '../context/AuthContext';
import '../styles/adminScreens.css';

// Snap target for Draw Walkable Path, in on-screen pixels — this is what
// actually needs to feel "clickable" to an admin, regardless of the map's
// native resolution or current zoom level. It is converted to
// original-image pixels at click time via resolveSnapThresholdPx() using
// the live render scale, with a small native-pixel floor so extremely
// zoomed-out views still have a sane minimum hit area.
// Backend reason codes from services/room_location_code_service.
// ensure_room_location_codes -> the translation key that explains them.
// Any unrecognised reason falls back to showing the raw code rather than
// silently hiding a room from the admin.
const SEMANTIC_DEST_REVIEW_REASONS = {
  no_arrival_point: 'semanticDestReasonNoArrivalPoint',
  arrival_point_missing_or_inactive: 'semanticDestReasonInactivePoint',
  not_connected_to_graph: 'semanticDestReasonNotConnected',
  arrival_point_has_no_building: 'semanticDestReasonNoBuilding',
};

const SNAP_SCREEN_PX = 14;
const SNAP_MIN_NATIVE_PX = 10;

const LANGUAGES = [
  { code: 'ar', label: 'عربي' },
  { code: 'he', label: 'עברית' },
  { code: 'en', label: 'EN' },
];

const UI = {
  en: {
    title: 'Map Management',
    back: 'Back',
    // Part 4 — return navigation when arriving here from the Add/Edit Room
    // screen's "Add / Upload New Map" action (see ?returnTo= param).
    backToRoom: 'Back to Room (draft preserved)',
    roomDraftBanner: 'Your Room draft is saved. Upload a map here, then you’ll return to it automatically.',
    selectMap: 'Select Map',
    uploadNewMap: 'Upload New Map',
    editDetails: 'Edit Details',
    deleteMap: 'Delete Map',
    selectedMap: 'Selected Map',
    current: 'Current',
    noMap: 'No map uploaded yet',
    noMapHint: 'Upload a map image or PDF to get started',
    openFullMap: 'Click map to open full view',
    savedPoints: 'Saved points',
    noPoints: 'No route points saved for this map yet',
    savedEdges: 'Saved edges',
    noEdges: 'No route edges saved for this map yet',
    loadingMaps: 'Loading maps...',
    loadingPoints: 'Loading route points...',
    loadingEdges: 'Loading route edges...',
    mapsError: 'Failed to load maps',
    pointsError: 'Failed to load route points',
    edgesError: 'Failed to load route edges',
    edgeDataWarning:
      'route edge(s) reference a route point that is missing from this map and were not drawn',
    addPointMode: 'Add Point',
    drawMode: 'Draw Walkable Path',
    drawHint: 'Click the map to add corridor points. Click near an existing point to reuse it.',
    drawFloor: 'Floor',
    noMapForFloor: 'No map is configured for this floor.',
    noFloorMapsLoaded: 'No floor maps were loaded for this Map Group.',
    retryMapsButton: 'Retry Maps',
    analyzeFloorMap: 'Analyze Floor Map (AI suggestions)',
    repairFloorsButton: 'Repair RoutePoint Floors from Maps',
    repairFloorsRunning: 'Checking…',
    repairFloorsNoneNeeded: 'No RoutePoint floors need repair — every point already matches its Map.',
    repairFloorsConfirm: (count) =>
      `${count} point${count === 1 ? '' : 's'} will have its floor corrected to match its Map. Apply this repair now?`,
    repairFloorsDone: (count) =>
      `Repaired ${count} point${count === 1 ? '' : 's'}. Points and edges have been refreshed.`,
    repairFloorsFailed: 'Failed to repair RoutePoint floors.',
    drawUndo: 'Undo',
    drawClear: 'Clear',
    drawCancel: 'Cancel',
    drawSave: 'Save Path',
    drawSaving: 'Saving...',
    drawNeedTwo: 'Add at least 2 points before saving',
    drawInvalidNames: 'Enter a valid name for every new point before saving',
    drawPointListTitle: 'Draft points',
    drawStatusNew: 'New',
    drawStatusExisting: 'Existing',
    drawStatusMergeHint: 'may auto-merge nearby',
    drawNamePlaceholder: 'Point name',
    drawNameEmpty: 'Name is required',
    drawNameTooShort: 'Name is too short',
    drawNameTooLong: 'Name is too long',
    drawRemovePoint: 'Remove',
    drawSaveSuccess: (points, edges, reused = 0, skippedEdges = 0, mergedEdges = 0) => {
      let message = `Saved ${points} new point${points === 1 ? '' : 's'} and ${edges} edge${edges === 1 ? '' : 's'}`;
      if (reused > 0) {
        message += `, reused ${reused} existing point${reused === 1 ? '' : 's'}`;
      }
      if (skippedEdges > 0) {
        message += ` (${skippedEdges} duplicate edge${skippedEdges === 1 ? '' : 's'} skipped)`;
      }
      if (mergedEdges > 0) {
        message += `, ${mergedEdges} automatic nearby merge edge${mergedEdges === 1 ? '' : 's'} added`;
      }
      return message;
    },
    drawSaveFailed: 'Could not save the path. Any newly created points and edges were rolled back.',
    drawWrongPointReject: "That point can't be reused here (different map/floor or inactive) — click again to place a new point instead.",
    drawWrongMapReject: (floorLabel) =>
      `This destination point belongs to a different map. Reassign the destination to the current ${floorLabel} map before connecting it.`,
    drawPointCount: (n) => `${n} point${n === 1 ? '' : 's'} in draft`,
    drawReusedPoint: 'existing point reused',
    drawMergeModeLabel: 'Automatic graph merging',
    drawMergeModeOff: 'Off',
    drawMergeModeReuseOnly: 'Reuse selected existing points only',
    drawMergeModeNearby: 'Merge with safe nearby graph points',
    drawSummaryTitle: 'Before you save',
    drawSummaryNewPoints: (n) => `New points: ${n}`,
    drawSummaryReusedPoints: (n) => `Existing points reused: ${n}`,
    drawSummaryPlannedEdges: (n) => `Planned new edges: ${n}`,
    drawSummarySkippedEdges: (n) => `Existing edges reused/skipped: ${n}`,
    panelMove: 'Move panel',
    panelMinimize: 'Minimize panel',
    panelRestore: 'Restore panel',
    panelDockLeft: 'Dock left',
    panelDockRight: 'Dock right',
    panelDockBottom: 'Dock bottom',
    building: 'Building',
    room: 'Room',
    selectBuilding: 'Select a building',
    selectRoom: 'Select a room',
    connectNearest: 'Connect to nearest corridor point',
    roomAlreadyLinked: (name) => `This room is already linked to "${name}"`,
    // Destination data flow — a "room"/"store" point now automatically
    // gets a linked Room, so the admin never has to separately open Add
    // Room and re-type the same name.
    pointWillBecomeDestination: 'This point will appear as a destination',
    syncRoomsAction: 'Sync Rooms from Route Points',
    syncRoomsSuccess: 'Rooms synchronised successfully',
    syncRoomsConfirmTitle: 'Sync Rooms from Route Points?',
    syncRoomsConfirmBody:
      'This creates or updates destination Rooms for existing room/store route points in this building so they appear in the user destination list. It does not change the walkable graph or routing in any way.',
    syncRoomsConfirmButton: 'Sync Now',
    syncRoomsRunning: 'Syncing...',
    syncRoomsNoScope: 'Select a map to sync its building’s rooms.',
    syncRoomsSummary: ({ scanned, created, updated, skipped, failed }) =>
      `Scanned ${scanned} · Created ${created} · Updated ${updated} · Skipped ${skipped} · Failed ${failed}`,
    syncRoomsFailed: 'Failed to sync rooms from route points',
    // ── Delete Connection mode (delete a RouteEdge without touching either
    // endpoint RoutePoint) ──────────────────────────────────────────────────
    // ── Edit Route Points mode (RBAC/dashboard cleanup task, Phase 13) ──
    editPointsMode: 'Edit Route Points',
    editPointsInstructions: 'Click an existing point on the map to edit it.',
    editPointsPanelTitle: 'Edit Route Point',
    editPointsNameLabel: 'Name',
    editPointsTypeLabel: 'Point Type',
    editPointsMovePoint: 'Move Point',
    editPointsMovingActive: 'Click new location…',
    editPointsOutOfBounds: 'That location is outside the map image.',
    editPointsSaveError: 'Failed to save changes.',
    editPointsNameTooShort: 'Name is too short.',
    editPointsDeleteError: 'Failed to delete point.',
    editPointsConnectedEdges: 'Connected edges',
    editPointsNone: 'None',
    editPointsInaccessible: 'not accessible',
    editPointsLinkedRoom: 'Linked room',
    editPointsLinkedConnector: 'Linked vertical connector',
    editPointsDeleteAction: 'Delete this point',
    editPointsConfirmDelete: 'Delete this route point? This cannot be undone.',
    deleteConnectionMode: 'Delete Connection',
    deleteConnectionInstructions: 'Click an existing connection to select it for deletion.',
    deleteConnectionCancelMode: 'Cancel Delete Mode',
    deleteConnectionConfirmTitle: 'Delete this connection?',
    deleteConnectionFromLabel: 'From',
    deleteConnectionToLabel: 'To',
    deleteConnectionTypeLabel: 'Edge type',
    deleteConnectionFloorLabel: 'Floor / Map',
    deleteConnectionSafetyNote: 'This removes only the connection. Both points will remain.',
    deleteConnectionConfirmButton: 'Delete Connection',
    deleteConnectionDeleting: 'Deleting...',
    deleteConnectionSuccess: 'Connection deleted successfully',
    deleteConnectionFailed: 'Failed to delete connection',
    deleteConnectionVerticalBlocked: 'Manage this connection from Vertical Connections.',
    // ── Auto Connect Destinations to Corridors ──────────────────────────────
    autoConnectMode: 'Auto Connect Destinations',
    autoConnectScanning: 'Scanning for unconnected destinations...',
    autoConnectPreviewTitle: 'Preview Connections',
    autoConnectScopeMap: 'Current map',
    autoConnectScopeMapGroup: 'All maps in Map Group',
    autoConnectManualPickInstructions: 'Click a corridor point on the map.',
    autoConnectAcceptAllHighConfidence: 'Accept all high-confidence proposals',
    autoConnectRejectAllLowConfidence: 'Reject all low-confidence proposals',
    autoConnectNothingToReview: 'No unconnected Room/Store destinations were found on this map.',
    autoConnectNoCorridorPointFound: 'No corridor point found',
    // Distinct per-reason labels (corridor point_type filtering fix) —
    // shown instead of the generic autoConnectNoCorridorPointFound line
    // whenever the backend returns a specific `reason` code, so an admin
    // can tell "no hallway/junction points exist" apart from "they exist
    // but aren't wired together" apart from "too far away".
    autoConnectReasonNoTransitPoints: 'No hallway/junction points exist on this map/floor',
    autoConnectReasonTransitNotConnected: 'Hallway/junction points exist but are not connected to each other by any walkway connection',
    autoConnectReasonTooFar: 'No hallway/junction point close enough to connect to',
    autoConnectReasonNestedParentNotReady: 'The approved parent room is not ready to receive connections yet',
    autoConnectReasonBlockedByWall:
      'A corridor point is close by, but a wall blocks the connection',
    autoConnectReasonCorridorIsolated:
      'A corridor point is nearby but is not connected to the walkable graph',
    autoConnectReasonNestedParentNotPassThrough:
      'The parent room is not approved for pass-through — approve it to connect this room',
    autoConnectReasonNestedParentNoPoint: 'The approved parent room has no map location yet',
    autoConnectTargetCorridorEdge: 'Attaches partway along a corridor (a junction will be added)',
    autoConnectDiagnosticsClearLine: 'Clear line',
    autoConnectDiagnosticsGraphConnected: 'On the walkable graph',
    autoConnectDiagnosticsBlockedCount: 'Candidates rejected by a wall',
    autoConnectDiagnosticsIsolatedCount: 'Candidates off the walkable graph',
    autoConnectDiagnosticsParentPassThrough: 'Parent allows pass-through',
    autoConnectDiagnosticsNearest: 'Nearest corridor found',
    autoConnectNeedsReviewBadge: 'Needs review',
    autoConnectTargetTypeLabel: 'Connection type',
    autoConnectNestedParentLabel: 'Parent room',
    autoConnectJunctionsCreated: 'Corridor junctions added',
    autoConnectUncalibrated: 'uncalibrated',
    autoConnectConfidenceHigh: 'High confidence',
    autoConnectConfidenceMedium: 'Medium confidence',
    autoConnectConfidenceLow: 'Low confidence',
    autoConnectNeedsReview: 'Needs review',
    autoConnectAlreadyConnected: 'Already connected',
    autoConnectNestedAccessBadge: 'Nested access — connects to the approved parent room',
    autoConnectInvalidEdgesWarning:
      'This destination has existing connections that are not valid corridor links. They will not be removed automatically.',
    autoConnectAccept: 'Accept',
    autoConnectReject: 'Reject',
    autoConnectPickManually: 'Pick different point on map',
    autoConnectReviewComplete: 'Review complete',
    autoConnectConfirmTitle: 'Create accepted connections?',
    autoConnectConfirmBody:
      'Only the accepted destination-to-corridor connections will be created. Existing points and connections will not be changed.',
    autoConnectBackToPreview: 'Back to Preview',
    autoConnectApplying: 'Creating connections...',
    autoConnectCreateAccepted: 'Create Accepted Connections',
    autoConnectResultTitle: 'Connections created successfully',
    autoConnectNoAccepted: 'Accept at least one proposal before creating connections.',
    autoConnectPreviewFailed: 'Failed to preview connections',
    autoConnectApplyFailed: 'Failed to create connections',
    autoConnectScannedCount: (n) => `Scanned: ${n}`,
    autoConnectProposedCount: (n) => `Proposed: ${n}`,
    autoConnectAcceptedCount: (n) => `Accepted: ${n}`,
    autoConnectRejectedCount: (n) => `Rejected: ${n}`,
    autoConnectSummaryLine: (s) =>
      `Scanned ${s.scanned} · Already connected ${s.already_connected} · Proposed ${s.proposed} · Needs review ${s.needs_review} · No candidate ${s.no_candidate}`,
    autoConnectProposedCorridorLine: (name, distanceText) =>
      `Proposed: ${name}${distanceText ? ` — ${distanceText}` : ''}`,
    autoConnectResultLine: (r) =>
      `Requested ${r.requested} · Created ${r.created} · Skipped (already connected) ${r.skipped_existing} · Rejected invalid ${r.rejected_invalid} · Failed ${r.failed}`,
    // ── Create Destinations from Approved Analysis ──────────────────────────
    semanticDestMode: 'Create Destinations from Approved Analysis',
    semanticDestScanning: 'Scanning approved semantic analysis...',
    semanticDestPreviewTitle: 'Preview Destinations',
    semanticDestScannedCount: (n) => `Scanned: ${n}`,
    semanticDestNewCount: (n) => `New destinations: ${n}`,
    semanticDestNeedsLocationCount: (n) => `Needs location review: ${n}`,
    semanticDestNestedCount: (n) => `Nested relationships: ${n}`,
    semanticDestManualPlaceInstructions: 'Click the correct location on the map for this destination.',
    semanticDestNothingToReview: 'No approved destinations were found to create.',
    semanticDestExcluded: 'Excluded from destination creation',
    semanticDestNeedsLocationReview:
      'Needs location review — no existing point found. Click "Pick Location" to place it.',
    semanticDestExistingLocation: 'Location found from existing route point',
    semanticDestNestedTitle: 'Possible nested destination',
    semanticDestNestedLine: (name) => `This destination may be inside ${name}.`,
    semanticDestConfirmNested: 'Confirm nested relationship',
    semanticDestAllowTransit: 'Allow users to pass through this room to reach other destinations',
    semanticDestPickLocation: 'Pick Location',
    semanticDestConfirmTitle: 'Create accepted destinations?',
    semanticDestConfirmBody:
      'Only the accepted destinations will be created as Rooms and Route Points. Existing points and connections will not be changed.',
    semanticDestNestedConfirmBody:
      'Users will be allowed to pass through the outer room to reach the inner destination.',
    semanticDestCreateAccepted: 'Create Accepted Destinations',
    semanticDestResultTitle: 'Destinations created successfully',
    semanticDestResultRoomsLine: (r) => `Rooms created: ${r.rooms_created}`,
    semanticDestResultPointsLine: (r) => `Route points created: ${r.route_points_created}`,
    // "Every accepted navigable room gets its own QR" — reported by the
    // same apply response, so no extra request is needed here.
    semanticDestResultQrLine: (r) =>
      `Room QR codes: ${r.qr_codes_created ?? 0} created, ${r.qr_codes_reused ?? 0} already existed`,
    semanticDestResultNotNavigableLine: (r) =>
      `Not navigable yet: ${(r.rooms_unconnected ?? 0) + (r.rooms_unplaced ?? 0)} room(s) — no QR issued`,
    semanticDestNotNavigableHint:
      'A room only gets a QR once it has a location on the map AND a connection to the corridor graph. Place any unplaced rooms, then run Auto Connect Destinations — the codes are issued automatically.',
    semanticDestReasonNoArrivalPoint: 'not placed on the map yet',
    semanticDestReasonInactivePoint: 'its map point is missing or inactive',
    semanticDestReasonNotConnected: 'not connected to the corridor graph',
    semanticDestReasonNoBuilding: 'its map has no building assigned',
    semanticDestResultUpdatedLine: (r) => `Existing destinations updated: ${r.rooms_updated}`,
    semanticDestResultNestedLine: (r) => `Nested destinations created: ${r.nested_relationships_created}`,
    semanticDestResultNeedsReviewLine: (r) => `Items needing review: ${r.skipped + r.ambiguous}`,
    semanticDestResultFailedLine: (r) => `Failed items: ${r.failed}`,
    semanticDestPreviewFailed: 'Failed to preview destinations',
    semanticDestNoAccepted: 'Accept at least one proposal before creating destinations.',
    semanticDestApplyFailed: 'Failed to create destinations',

    // ── Fast Batch Destination Placement ("Place All Destinations") ─────────
    semanticBatchPlaceAll: 'Place All Destinations',
    // ── Automatic Navigation Build (Phase A preview) ───────────────────────
    navBuildMode: 'Automatic Navigation Build',
    // ── Floating map toolbox (presentation only) ──────────────────────────
    toolboxTitle: 'Navigation Tools',
    toolboxMove: 'Move the tools panel',
    toolboxMinimize: 'Collapse the tools panel',
    toolboxRestore: 'Expand the tools panel',
    toolboxGroupDraw: 'Draw',
    toolboxGroupRouting: 'Routing',
    toolboxGroupDestinations: 'Destinations',
    toolboxGroupEditing: 'Map & graph editing',
    toolboxGroupAutomation: 'Automation',
    // Shortened button labels. The full wording stays in each button's
    // tooltip; the action behind it is unchanged.
    semanticDestModeShort: 'Create from Analysis',
    syncRoomsActionShort: 'Sync Rooms',
    navBuildModeShort: 'Automatic Build',
    navBuildTitle: 'Automatic Navigation Build',
    navBuildReadOnly:
      'Preview only — nothing is saved. No rooms, points, connections or QR codes are created.',
    navBuildRun: 'Preview Automatic Navigation Build',
    navBuildRunning: 'Analyzing the floor plan…',
    navBuildFailed: 'Automatic navigation build preview failed',
    navBuildRefused: 'Nothing could be generated for this map.',
    navBuildStage: 'Stage',
    navBuildLayers: 'Show on the map',
    navBuildLayer_region: 'Building region',
    navBuildLayer_rejected: 'Rejected areas',
    navBuildLayer_graph: 'Transit graph',
    navBuildLayer_arrivals: 'Room arrival points',
    navBuildLayer_attachments: 'Room connections',
    navBuildLayer_rejectedEdges: 'Rejected edges',
    navBuildTransitNodes: 'Transit nodes proposed',
    navBuildTransitEdges: 'Transit connections proposed',
    navBuildRoomsPositioned: 'Rooms positioned automatically',
    navBuildRoomsConnected: 'Rooms connected to the graph',
    navBuildAcceptedRooms: 'Accepted rooms scanned',
    navBuildWouldCreateQr: 'QR codes an apply WOULD create',
    navBuildNeedsReview: 'Rooms that still need you',
    navBuildShowDiagnostics: 'Show diagnostics',
    navBuildHideDiagnostics: 'Hide diagnostics',
    navBuildLabelSource: 'Labels read from',
    // ── Automatic placement from the map's own printed labels ──────────────
    // Deliberate wording: "from the map label". This is never described as
    // door detection — no door, opening or room outline is detected
    // anywhere in this feature.
    semanticAutoPlacedBadge: 'Positioned from map label',
    semanticAutoPlacedDetail: (label) => `Matched the label "${label}" printed on this map.`,
    semanticAutoPlacedConnects: (name) => `Reaches ${name} with a clear line.`,
    semanticAutoPlacedCheckHint: 'Check it, move it, or reject it like any other destination.',
    semanticAutoPlacedSummary: (placed, total) =>
      `${placed} of ${total} destinations were positioned from labels printed on this map.`,
    semanticAutoPlacedNeedsClick: 'These still need a location:',
    semanticAutoPlaceReasonNoLabelMatch: 'no matching label on the map',
    semanticAutoPlaceReasonAmbiguous: 'more than one label matches',
    semanticAutoPlaceReasonNoConnection: 'no clear path to a corridor point',
    semanticAutoPlaceReasonNeedsConfirmation: 'needs a location you confirm',
    semanticBatchPanelTitle: 'Batch Placement',
    semanticBatchDestinationOf: (i, n) => `Destination ${i} of ${n}`,
    semanticBatchClickInstructions: 'Click the door location on the map.',
    semanticBatchLocationRecorded: 'Location recorded for this destination.',
    semanticBatchLocationSelected: (name) => `Location selected for ${name}`,
    semanticBatchProgressPlaced: (placed, total) => `Placed ${placed} of ${total}`,
    semanticBatchProgressRemaining: (remaining) => `Remaining ${remaining}`,
    semanticBatchProgressRejected: (rejected) => `Rejected ${rejected}`,
    semanticBatchEnterHint: 'Press Enter to move to the next destination.',
    semanticBatchAllResolved: 'Every destination has been placed, skipped, or rejected. Open the review to save.',
    semanticBatchPrevious: 'Previous',
    semanticBatchSkip: 'Skip for now',
    semanticBatchReject: 'Reject destination',
    semanticBatchUndo: 'Undo last placement',
    semanticBatchChangeLocation: 'Change location',
    semanticBatchExit: 'Exit placement mode',
    semanticBatchReviewTitle: 'Review Destinations',
    semanticBatchBackToPlacement: 'Back to placement',
    semanticBatchSaveAll: 'Save All Destinations',
    semanticBatchSaveConfirmTitle: 'Save all destinations?',
    semanticBatchSaveConfirmBody: (count) =>
      `This will create or reuse ${count} destination(s) in one final save. Nothing is written until you confirm.`,
    semanticBatchSaveFailedWithErrors: 'Some destinations failed validation — nothing was saved. Fix the items below and try again.',
    semanticBatchExitWarningTitle: 'Exit placement mode?',
    semanticBatchExitWarningBody: 'You have unsaved placement progress. It stays saved locally in this browser, but nothing is written to the database until you Save All Destinations.',
    semanticBatchResumeDraftTitle: 'Resume previous placement?',
    semanticBatchResumeDraftBody: 'We found unsaved batch placement progress for this map. Would you like to resume where you left off, or start over?',
    semanticBatchResumeDraft: 'Resume placement',
    semanticBatchDiscardDraft: 'Discard draft',
    semanticBatchFloorLabel: (floor) => `Floor ${floor}`,
    semanticBatchNoLocationYet: 'No location yet',
    semanticBatchStatusReady: 'Ready',
    semanticBatchStatusRejected: 'Rejected',
    semanticBatchStatusMissing: 'Missing location',

    testMode: 'Test Route',
    testStart: 'Start point',
    testEnd: 'Destination point',
    testSelectStart: 'Select a start point',
    testSelectEnd: 'Select a destination',
    testFind: 'Find Route',
    testClear: 'Clear Test',
    testChangeStart: 'Change Start',
    testChangeEnd: 'Change Destination',
    testCalculating: 'Calculating route...',
    testNoRoute: 'No route found between these points',
    testDistance: (meters) => `Total distance: ${meters.toFixed(1)} m`,
    testStepCount: (n) => `${n} point${n === 1 ? '' : 's'} on this route`,
    processing: 'Processing map',
    processingFailed: 'Map processing failed',
    confirmDelete: 'Delete the selected map?',
    yesDelete: 'Yes, Delete',
    cancel: 'Cancel',
    addPoint: 'Add Route Point',
    savePoint: 'Save Route Point',
    savedPoint: 'Route point saved',
    selectPoint: 'Click on the map to select a route point',
    pointName: 'Point Name',
    pointType: 'Point Type',
    floor: 'Floor',
    noSelectedMap: 'No map selected',
    uploadTitle: 'Upload a New Map',
    chooseFile: 'Choose map file',
    selectedFile: 'Selected file',
    mapTitle: 'Map Title',
    campus: 'Campus / Location',
    address: 'Address',
    description: 'Description',
    scale: 'Map Scale',
    useOpenAI: 'Use OpenAI processing',
    uploadBuilding: 'Building',
    uploadBuildingAuto: 'Auto-create/reuse from campus name',
    uploadFloor: 'Floor',
    uploadAutoGenerateGraph: 'Auto-generate walkable graph after processing',
    regenerateGraph: 'Generate Route Graph (Experimental)',
    graphGenerationExperimentalNote:
      'Optional, experimental automatic generation from the map image. Manually adding route points is the recommended, supported workflow — review the proposed graph carefully before confirming.',
    graphGenerating: 'Generating...',
    clearGeneratedGraph: 'Clear Generated Graph',
    graphGenerationDone: 'Walkable graph generation finished.',
    graphGenerationFailed: 'Failed to generate walkable graph',
    graphClearedSummary: (points, edges) =>
      `Cleared ${points} auto-generated point(s) and ${edges} auto-generated edge(s).`,

    // Navigation-data-problem task, Part 3A/3B/6/7 — generated-only
    // cleanup + full navigation reset for the active map.
    removeGeneratedNavData: 'Remove Generated Navigation Data',
    resetAllNavData: 'Reset All Navigation Data on This Map',
    cleanupPreviewLoading: 'Loading preview…',
    cleanupPreviewFailed: 'Failed to load the generated-data cleanup preview',
    cleanupApplyFailed: 'Failed to remove generated navigation data',
    cleanupApplySummary: (points, edges) =>
      `Removed ${points} generated route point(s) and ${edges} generated connection(s).`,
    cleanupPreviewTitle: 'Remove Generated Navigation Data — Preview',
    cleanupGeneratedPoints: 'Generated route points (will be deleted)',
    cleanupGeneratedEdges: 'Generated connections (will be deleted)',
    cleanupManualPoints: 'Manual route points (kept)',
    cleanupManualEdges: 'Manual connections (kept)',
    cleanupUnknownLegacy: 'Unknown/legacy points (kept — not proven generated)',
    cleanupUnknownLegacyNote: 'Not proven generated, so never deleted by this action.',
    cleanupLinkedRooms: 'Rooms linked to generated points',
    cleanupLinkedConnectors: 'Vertical connectors linked to generated points',
    cleanupDependentEdges: 'Manual connections that will also be removed (touch a generated point)',
    cleanupNoneToDelete: 'Nothing proven generated was found on this map — there is nothing to remove.',
    cleanupConfirmButton: 'Delete Generated Data',
    cleanupApplying: 'Deleting…',

    resetPreviewFailed: 'Failed to load the full navigation reset preview',
    resetApplyFailed: 'Failed to reset navigation data for this map',
    resetApplySummary: (points, edges) =>
      `Deleted ${points} route point(s) and ${edges} connection(s) from this map.`,
    resetPreviewTitle: 'Reset All Navigation Data on This Map — Preview',
    resetWarning:
      'This deletes ALL route points and connections on this map, including any manually added ones. Public navigation on this map will be unavailable until an admin manually adds new route points. This cannot be undone.',
    resetTotalPoints: 'Total route points on this map',
    resetTotalEdges: 'Total connections on this map',
    resetBreakdownManual: 'Manual',
    resetBreakdownGenerated: 'Generated',
    resetBreakdownSemantic: 'Semantic destinations',
    resetBreakdownConnector: 'Vertical connector stops',
    resetBreakdownUnknown: 'Unknown/legacy',
    resetLinkedRooms: 'Rooms linked (link will be cleared, room kept)',
    resetLinkedConnectors: 'Vertical connectors affected (metadata kept)',
    resetLinkedLocationCodes: 'QR/location codes linked (will be deactivated)',
    resetNoneToDelete: 'This map has no route points or connections — nothing to reset.',
    resetConfirmInstructions: (mapName) =>
      `Type this map's name ("${mapName}") or the phrase "RESET NAVIGATION DATA" to confirm.`,
    resetConfirmPlaceholder: 'Type the map name or RESET NAVIGATION DATA',
    resetConfirmButton: 'Permanently Delete All Navigation Data',
    resetApplying: 'Resetting…',
    upload: 'Upload Map',
    uploading: 'Uploading...',
    uploadSuccess:
      'Map uploaded successfully. Processing started automatically.',
    uploadError: 'Failed to upload map',
    requiredUploadFields: 'Map title and file are required',
    editTitle: 'Edit Map Details',
    editFloorLabel: 'Floor',
    floorNotConfigured: 'Floor is not configured',
    saveChanges: 'Save Changes',
    details: {
      title: 'Title',
      campus: 'Campus',
      address: 'Address',
      description: 'Description',
      status: 'Status',
      mapId: 'Map ID',
    },
    modeSingle: 'Single-Floor Map',
    modeMulti: 'Multi-Floor Map',
    modeSingleHint: 'Upload one image as one map.',
    modeMultiHint: 'Upload several floors of the same building as one map group.',
    mapGroupInfoTitle: 'Map Group Information',
    mapGroupName: 'Map Group Name',
    mapGroupCode: 'Shared Map Group Code',
    mapGroupCodeHint: 'Optional — leave blank to auto-generate. Letters, numbers, and hyphens only.',
    mapGroupNameRequired: 'Map group name is required (at least 2 characters).',
    floorRowsInvalid: 'Fix the highlighted floor rows before uploading.',
    mapGroupUploadSuccess: 'Map group uploaded successfully. Processing started for each floor.',
    mapGroupUploadError: 'Failed to upload map group',
    floorMapsListTitle: 'Floor Maps',
    floorNumber: 'Floor Number',
    floorLabel: 'Floor Label',
    floorTitle: 'Floor Title',
    floorScale: 'Map Scale',
    floorFile: 'Floor map file',
    addAnotherFloor: 'Add Another Floor',
    removeFloor: 'Remove Floor',
    uploadAllFloors: 'Upload All Floors',
    uploadingFloors: 'Uploading floors...',
    groupFloorCount: (n) => `${n} floor${n === 1 ? '' : 's'}`,
    expandGroup: 'Show floors',
    collapseGroup: 'Hide floors',
    addFloor: 'Add Floor',
    editGroup: 'Edit Group',
    deleteGroup: 'Delete Group',
    viewAllFloors: 'View All Floors',
    confirmDeleteFloor: (title) => `Delete the floor map "${title}"? This does not delete the map group.`,
    confirmDeleteGroup: (name) => `Delete the map group "${name}" and all of its floors?`,
    floorSwitcher: 'Floor',
    ungroupedMapsTitle: 'Single-Floor Maps',
    addFloorTitle: 'Add a Floor',
    saveFloor: 'Add Floor',
    floorSwitchConfirm: 'Switch floor? Unsaved draft points on this floor will be lost.',
    calibrateMode: 'Calibrate Scale',
    calibrateInstructions: 'Choose two points on the map',
    calibratePointA: 'Point A',
    calibratePointB: 'Point B',
    calibrateDistanceTitle: 'Known real distance in meters',
    calibrateDistancePlaceholder: 'e.g. 5.5',
    calibrateDistanceInvalid: 'Enter a distance greater than 0',
    calibrateNeedTwoPoints: 'Click two points on the map first',
    calibrateSubmit: 'Save Calibration',
    calibrateSaving: 'Saving calibration...',
    calibrateSuccess: 'Calibration saved successfully',
    calibrateScaleResult: (metersPerPixel) => `Scale: ${metersPerPixel.toFixed(4)} m/px`,
    calibrateEdgesRecalculated: (n) => `${n} walkway edge${n === 1 ? '' : 's'} recalculated`,
    calibrateEdgesSkipped: (n) => `${n} edge${n === 1 ? '' : 's'} skipped`,
    calibrateError: 'Failed to save calibration',
    calibrateCancel: 'Cancel Calibration',
    calibrateReset: 'Reset Selected Points',
    calibrateClose: 'OK',
  },

  ar: {
    title: 'إدارة الخريطة',
    back: 'رجوع',
    backToRoom: 'العودة إلى الغرفة (تم حفظ المسودة)',
    roomDraftBanner: 'تم حفظ مسودة الغرفة. ارفع خريطة هنا وستعود إليها تلقائيًا.',
    selectMap: 'اختيار الخريطة',
    uploadNewMap: 'رفع خارطة جديدة',
    editDetails: 'تعديل التفاصيل',
    deleteMap: 'حذف الخريطة',
    selectedMap: 'الخريطة المختارة',
    current: 'الحالية',
    noMap: 'لا توجد خريطة مرفوعة',
    noMapHint: 'ارفعي صورة خارطة أو ملف PDF للبدء',
    openFullMap: 'اضغطي على الخريطة لفتحها كاملة',
    savedPoints: 'النقاط المحفوظة',
    noPoints: 'لا توجد نقاط محفوظة لهذه الخريطة بعد',
    savedEdges: 'الحواف المحفوظة',
    noEdges: 'لا توجد حواف مسار محفوظة لهذه الخريطة بعد',
    loadingMaps: 'جاري تحميل الخرائط...',
    loadingPoints: 'جاري تحميل نقاط المسار...',
    loadingEdges: 'جاري تحميل حواف المسار...',
    mapsError: 'فشل تحميل الخرائط',
    pointsError: 'فشل تحميل نقاط المسار',
    edgesError: 'فشل تحميل حواف المسار',
    edgeDataWarning: 'حافة/حواف مسار تشير إلى نقطة غير موجودة في هذه الخريطة ولم تُرسم',
    addPointMode: 'إضافة نقطة',
    drawMode: 'رسم مسار للمشي',
    drawHint: 'اضغطي على الخريطة لإضافة نقاط الممر. اضغطي بالقرب من نقطة موجودة لإعادة استخدامها.',
    drawFloor: 'الطابق',
    noMapForFloor: 'لا توجد خريطة مُعدة لهذا الطابق.',
    noFloorMapsLoaded: 'لم يتم تحميل أي خرائط طوابق لمجموعة الخرائط هذه.',
    retryMapsButton: 'إعادة محاولة تحميل الخرائط',
    analyzeFloorMap: 'تحليل خريطة الطابق (اقتراحات الذكاء الاصطناعي)',
    repairFloorsButton: 'إصلاح طوابق نقاط المسار من الخرائط',
    repairFloorsRunning: 'جارٍ الفحص…',
    repairFloorsNoneNeeded: 'لا توجد نقاط مسار بحاجة إلى إصلاح — كل نقطة تطابق طابق خريطتها بالفعل.',
    repairFloorsConfirm: (count) =>
      `سيتم تصحيح طابق ${count} نقطة لتطابق خريطتها. هل تريدين تطبيق هذا الإصلاح الآن؟`,
    repairFloorsDone: (count) =>
      `تم إصلاح ${count} نقطة. تم تحديث النقاط والمسارات.`,
    repairFloorsFailed: 'فشل إصلاح طوابق نقاط المسار.',
    drawUndo: 'تراجع',
    drawClear: 'مسح',
    drawCancel: 'إلغاء',
    drawSave: 'حفظ المسار',
    drawSaving: 'جاري الحفظ...',
    drawNeedTwo: 'أضيفي نقطتين على الأقل قبل الحفظ',
    drawInvalidNames: 'أدخلي اسمًا صالحًا لكل نقطة جديدة قبل الحفظ',
    drawPointListTitle: 'نقاط المسودة',
    drawStatusNew: 'جديدة',
    drawStatusExisting: 'موجودة',
    drawStatusMergeHint: 'قد تندمج تلقائيًا مع نقطة قريبة',
    drawNamePlaceholder: 'اسم النقطة',
    drawNameEmpty: 'الاسم مطلوب',
    drawNameTooShort: 'الاسم قصير جدًا',
    drawNameTooLong: 'الاسم طويل جدًا',
    drawRemovePoint: 'إزالة',
    drawSaveSuccess: (points, edges, reused = 0, skippedEdges = 0, mergedEdges = 0) => {
      let message = `تم حفظ ${points} نقطة جديدة و ${edges} حافة`;
      if (reused > 0) {
        message += `، وإعادة استخدام ${reused} نقطة موجودة`;
      }
      if (skippedEdges > 0) {
        message += ` (تم تخطي ${skippedEdges} حافة مكررة)`;
      }
      if (mergedEdges > 0) {
        message += `، وإضافة ${mergedEdges} حافة دمج تلقائي مع نقاط قريبة`;
      }
      return message;
    },
    drawSaveFailed: 'تعذر حفظ المسار. تم التراجع عن أي نقاط وحواف تم إنشاؤها حديثًا.',
    drawWrongPointReject: 'لا يمكن إعادة استخدام هذه النقطة هنا (خريطة/طابق مختلف أو غير نشطة) — اضغطي مرة أخرى لوضع نقطة جديدة بدلاً من ذلك.',
    drawWrongMapReject: (floorLabel) =>
      `تنتمي نقطة الوجهة هذه إلى خريطة مختلفة. يرجى إعادة تعيين الوجهة إلى خريطة ${floorLabel} الحالية قبل ربطها.`,
    drawPointCount: (n) => `${n} نقطة في المسودة`,
    drawReusedPoint: 'إعادة استخدام نقطة موجودة',
    drawMergeModeLabel: 'الدمج التلقائي للرسم البياني',
    drawMergeModeOff: 'إيقاف',
    drawMergeModeReuseOnly: 'إعادة استخدام النقاط الموجودة المحددة فقط',
    drawMergeModeNearby: 'الدمج مع نقاط الرسم البياني القريبة الآمنة',
    drawSummaryTitle: 'قبل الحفظ',
    drawSummaryNewPoints: (n) => `نقاط جديدة: ${n}`,
    drawSummaryReusedPoints: (n) => `نقاط موجودة معاد استخدامها: ${n}`,
    drawSummaryPlannedEdges: (n) => `حواف جديدة مخططة: ${n}`,
    drawSummarySkippedEdges: (n) => `حواف موجودة معاد استخدامها/تم تخطيها: ${n}`,
    panelMove: 'تحريك اللوحة',
    panelMinimize: 'تصغير اللوحة',
    panelRestore: 'استعادة اللوحة',
    panelDockLeft: 'إرساء لليسار',
    panelDockRight: 'إرساء لليمين',
    panelDockBottom: 'إرساء للأسفل',
    building: 'المبنى',
    room: 'الغرفة',
    selectBuilding: 'اختر مبنى',
    selectRoom: 'اختر غرفة',
    connectNearest: 'الاتصال بأقرب نقطة ممر',
    roomAlreadyLinked: (name) => `هذه الغرفة مرتبطة بالفعل بـ "${name}"`,
    pointWillBecomeDestination: 'ستظهر هذه النقطة كوجهة للمستخدم',
    syncRoomsAction: 'مزامنة الغرف من نقاط المسار',
    syncRoomsSuccess: 'تمت مزامنة الغرف بنجاح',
    syncRoomsConfirmTitle: 'مزامنة الغرف من نقاط المسار؟',
    syncRoomsConfirmBody:
      'سيؤدي هذا إلى إنشاء أو تحديث غرف الوجهات لنقاط المسار الحالية من نوع غرفة/متجر في هذا المبنى لتظهر في قائمة وجهات المستخدم. لن يغيّر هذا الرسم البياني القابل للسير أو التوجيه بأي شكل.',
    syncRoomsConfirmButton: 'مزامنة الآن',
    syncRoomsRunning: 'جارٍ المزامنة...',
    syncRoomsNoScope: 'اختر خريطة لمزامنة غرف مبناها.',
    syncRoomsSummary: ({ scanned, created, updated, skipped, failed }) =>
      `تم فحص ${scanned} · تم إنشاء ${created} · تم تحديث ${updated} · تم تخطي ${skipped} · فشل ${failed}`,
    syncRoomsFailed: 'فشلت مزامنة الغرف من نقاط المسار',
    editPointsMode: 'تعديل نقاط المسار',
    editPointsInstructions: 'انقر على نقطة موجودة في الخريطة لتعديلها.',
    editPointsPanelTitle: 'تعديل نقطة المسار',
    editPointsNameLabel: 'الاسم',
    editPointsTypeLabel: 'نوع النقطة',
    editPointsMovePoint: 'نقل النقطة',
    editPointsMovingActive: 'انقر على الموقع الجديد…',
    editPointsOutOfBounds: 'هذا الموقع خارج صورة الخريطة.',
    editPointsSaveError: 'فشل حفظ التغييرات.',
    editPointsNameTooShort: 'الاسم قصير جدًا.',
    editPointsDeleteError: 'فشل حذف النقطة.',
    editPointsConnectedEdges: 'الروابط المتصلة',
    editPointsNone: 'لا يوجد',
    editPointsInaccessible: 'غير متاحة',
    editPointsLinkedRoom: 'الغرفة المرتبطة',
    editPointsLinkedConnector: 'الموصل الرأسي المرتبط',
    editPointsDeleteAction: 'حذف هذه النقطة',
    editPointsConfirmDelete: 'حذف نقطة المسار هذه؟ لا يمكن التراجع عن هذا.',
    deleteConnectionMode: 'حذف ربط',
    deleteConnectionInstructions: 'اضغطي على ربط موجود لتحديده للحذف.',
    deleteConnectionCancelMode: 'إلغاء وضع الحذف',
    deleteConnectionConfirmTitle: 'هل تريدين حذف هذا الربط؟',
    deleteConnectionFromLabel: 'من',
    deleteConnectionToLabel: 'إلى',
    deleteConnectionTypeLabel: 'نوع الربط',
    deleteConnectionFloorLabel: 'الطابق / الخريطة',
    deleteConnectionSafetyNote: 'سيتم حذف الربط فقط، وستبقى النقطتان.',
    deleteConnectionConfirmButton: 'حذف الربط',
    deleteConnectionDeleting: 'جارٍ الحذف...',
    deleteConnectionSuccess: 'تم حذف الربط بنجاح',
    deleteConnectionFailed: 'فشل حذف الربط',
    deleteConnectionVerticalBlocked: 'عدّلي هذا الربط من قسم الربط بين الطوابق.',
    autoConnectMode: 'ربط الوجهات تلقائيًا',
    autoConnectScanning: 'جارٍ البحث عن الوجهات غير المربوطة...',
    autoConnectPreviewTitle: 'معاينة الروابط',
    autoConnectScopeMap: 'الخريطة الحالية',
    autoConnectScopeMapGroup: 'كل خرائط مجموعة الخرائط',
    autoConnectManualPickInstructions: 'اضغطي على نقطة ممر على الخريطة.',
    autoConnectAcceptAllHighConfidence: 'قبول جميع الاقتراحات عالية الثقة',
    autoConnectRejectAllLowConfidence: 'رفض جميع الاقتراحات منخفضة الثقة',
    autoConnectNothingToReview: 'لم يتم العثور على وجهات غرفة/متجر غير مربوطة في هذه الخريطة.',
    autoConnectNoCorridorPointFound: 'لم يتم العثور على نقطة ممر',
    autoConnectReasonNoTransitPoints: 'لا توجد نقاط ممر/تقاطع في هذه الخريطة/الطابق',
    autoConnectReasonTransitNotConnected: 'توجد نقاط ممر/تقاطع لكنها غير مرتبطة ببعضها بأي رابط مسار',
    autoConnectReasonTooFar: 'لا توجد نقطة ممر/تقاطع قريبة بما يكفي للربط',
    autoConnectReasonNestedParentNotReady: 'الغرفة الأصل المعتمدة غير جاهزة بعد لاستقبال الروابط',
    autoConnectReasonBlockedByWall: 'توجد نقطة ممر قريبة لكن يوجد جدار يمنع الربط',
    autoConnectReasonCorridorIsolated: 'توجد نقطة ممر قريبة لكنها غير متصلة بشبكة المسارات',
    autoConnectReasonNestedParentNotPassThrough:
      'الغرفة الأصل غير معتمدة للمرور من خلالها — اعتمدها لربط هذه الغرفة',
    autoConnectReasonNestedParentNoPoint: 'الغرفة الأصل المعتمدة ليس لها موقع على الخريطة بعد',
    autoConnectTargetCorridorEdge: 'يرتبط بمنتصف الممر (ستتم إضافة تقاطع)',
    autoConnectDiagnosticsClearLine: 'خط واضح',
    autoConnectDiagnosticsGraphConnected: 'ضمن شبكة المسارات',
    autoConnectDiagnosticsBlockedCount: 'مرشحون مرفوضون بسبب جدار',
    autoConnectDiagnosticsIsolatedCount: 'مرشحون خارج شبكة المسارات',
    autoConnectDiagnosticsParentPassThrough: 'الغرفة الأصل تسمح بالمرور',
    autoConnectDiagnosticsNearest: 'أقرب ممر تم العثور عليه',
    autoConnectNeedsReviewBadge: 'يحتاج مراجعة',
    autoConnectTargetTypeLabel: 'نوع الربط',
    autoConnectNestedParentLabel: 'الغرفة الأصل',
    autoConnectJunctionsCreated: 'تقاطعات ممر تمت إضافتها',
    autoConnectUncalibrated: 'غير معايَر',
    autoConnectConfidenceHigh: 'ثقة عالية',
    autoConnectConfidenceMedium: 'ثقة متوسطة',
    autoConnectConfidenceLow: 'ثقة منخفضة',
    autoConnectNeedsReview: 'يحتاج إلى مراجعة',
    autoConnectAlreadyConnected: 'مربوط مسبقًا',
    autoConnectNestedAccessBadge: 'وصول متداخل — يربط بالغرفة الأصل المعتمدة',
    autoConnectInvalidEdgesWarning:
      'لهذه الوجهة روابط حالية ليست روابط ممر صالحة. لن يتم حذفها تلقائيًا.',
    autoConnectAccept: 'قبول',
    autoConnectReject: 'رفض',
    autoConnectPickManually: 'اختيار نقطة مختلفة من الخريطة',
    autoConnectReviewComplete: 'اكتملت المراجعة',
    autoConnectConfirmTitle: 'هل تريدين إنشاء الروابط المقبولة؟',
    autoConnectConfirmBody:
      'سيتم إنشاء روابط الوجهات المقبولة مع الممر فقط. لن يتم تغيير النقاط أو الروابط الموجودة.',
    autoConnectBackToPreview: 'العودة إلى المعاينة',
    autoConnectApplying: 'جارٍ إنشاء الروابط...',
    autoConnectCreateAccepted: 'إنشاء الروابط المقبولة',
    autoConnectResultTitle: 'تم إنشاء الروابط بنجاح',
    autoConnectNoAccepted: 'يجب قبول اقتراح واحد على الأقل قبل إنشاء الروابط.',
    autoConnectPreviewFailed: 'فشلت معاينة الروابط',
    autoConnectApplyFailed: 'فشل إنشاء الروابط',
    autoConnectScannedCount: (n) => `تم الفحص: ${n}`,
    autoConnectProposedCount: (n) => `مقترح: ${n}`,
    autoConnectAcceptedCount: (n) => `المقبول: ${n}`,
    autoConnectRejectedCount: (n) => `المرفوض: ${n}`,
    autoConnectSummaryLine: (s) =>
      `تم فحص ${s.scanned} · مربوط مسبقًا ${s.already_connected} · مقترح ${s.proposed} · يحتاج إلى مراجعة ${s.needs_review} · بدون مرشح ${s.no_candidate}`,
    autoConnectProposedCorridorLine: (name, distanceText) =>
      `المقترح: ${name}${distanceText ? ` — ${distanceText}` : ''}`,
    autoConnectResultLine: (r) =>
      `مطلوب ${r.requested} · تم الإنشاء ${r.created} · تم التخطي (مربوط مسبقًا) ${r.skipped_existing} · مرفوض غير صالح ${r.rejected_invalid} · فشل ${r.failed}`,
    // ── Create Destinations from Approved Analysis ──────────────────────────
    semanticDestMode: 'إنشاء الوجهات من التحليل المعتمد',
    semanticDestScanning: 'جارٍ فحص التحليل الدلالي المعتمد...',
    semanticDestPreviewTitle: 'معاينة الوجهات',
    semanticDestScannedCount: (n) => `تم الفحص: ${n}`,
    semanticDestNewCount: (n) => `وجهات جديدة: ${n}`,
    semanticDestNeedsLocationCount: (n) => `يحتاج إلى مراجعة الموقع: ${n}`,
    semanticDestNestedCount: (n) => `علاقات متداخلة: ${n}`,
    semanticDestManualPlaceInstructions: 'اضغطي على الموقع الصحيح على الخريطة لهذه الوجهة.',
    semanticDestNothingToReview: 'لم يتم العثور على وجهات معتمدة لإنشائها.',
    semanticDestExcluded: 'مستبعدة من إنشاء الوجهات',
    semanticDestNeedsLocationReview:
      'يحتاج إلى مراجعة الموقع — لم يتم العثور على نقطة موجودة. اضغطي على "اختيار الموقع" لتحديده.',
    semanticDestExistingLocation: 'تم تحديد الموقع من نقطة مسار موجودة',
    semanticDestNestedTitle: 'وجهة داخل مكان آخر محتملة',
    semanticDestNestedLine: (name) => `قد تكون هذه الوجهة داخل ${name}.`,
    semanticDestConfirmNested: 'تأكيد العلاقة المتداخلة',
    semanticDestAllowTransit: 'السماح للمستخدمين بالمرور عبر هذه الغرفة للوصول إلى وجهات أخرى',
    semanticDestPickLocation: 'اختيار الموقع',
    semanticDestConfirmTitle: 'هل تريدين إنشاء الوجهات المقبولة؟',
    semanticDestConfirmBody:
      'سيتم إنشاء الوجهات المقبولة فقط كغرف ونقاط مسار. لن يتم تغيير النقاط أو الروابط الموجودة.',
    semanticDestNestedConfirmBody:
      'سيُسمح للمستخدم بالمرور عبر الغرفة الخارجية للوصول إلى الوجهة الداخلية.',
    semanticDestCreateAccepted: 'إنشاء الوجهات المقبولة',
    semanticDestResultTitle: 'تم إنشاء الوجهات بنجاح',
    semanticDestResultRoomsLine: (r) => `الغرف التي تم إنشاؤها: ${r.rooms_created}`,
    semanticDestResultPointsLine: (r) => `نقاط المسار التي تم إنشاؤها: ${r.route_points_created}`,
    semanticDestResultQrLine: (r) =>
      `رموز QR للغرف: ${r.qr_codes_created ?? 0} تم إنشاؤها، ${r.qr_codes_reused ?? 0} موجودة مسبقًا`,
    semanticDestResultNotNavigableLine: (r) =>
      `غير قابلة للملاحة بعد: ${(r.rooms_unconnected ?? 0) + (r.rooms_unplaced ?? 0)} غرفة — لم يتم إصدار رمز`,
    semanticDestNotNavigableHint:
      'تحصل الغرفة على رمز QR فقط بعد تحديد موقعها على الخريطة وربطها بشبكة الممرات. حدد مواقع الغرف غير المحددة ثم شغّل الربط التلقائي للوجهات — تُصدر الرموز تلقائيًا.',
    semanticDestReasonNoArrivalPoint: 'لم يتم تحديد موقعها على الخريطة',
    semanticDestReasonInactivePoint: 'نقطة الخريطة مفقودة أو غير مفعلة',
    semanticDestReasonNotConnected: 'غير مرتبطة بشبكة الممرات',
    semanticDestReasonNoBuilding: 'لا يوجد مبنى مرتبط بخريطتها',
    semanticDestResultUpdatedLine: (r) => `الوجهات الحالية التي تم تحديثها: ${r.rooms_updated}`,
    semanticDestResultNestedLine: (r) => `الوجهات المتداخلة التي تم إنشاؤها: ${r.nested_relationships_created}`,
    semanticDestResultNeedsReviewLine: (r) => `عناصر تحتاج إلى مراجعة: ${r.skipped + r.ambiguous}`,
    semanticDestResultFailedLine: (r) => `العناصر الفاشلة: ${r.failed}`,
    semanticDestPreviewFailed: 'فشلت معاينة الوجهات',
    semanticDestNoAccepted: 'يجب قبول اقتراح واحد على الأقل قبل إنشاء الوجهات.',
    semanticDestApplyFailed: 'فشل إنشاء الوجهات',

    // ── Fast Batch Destination Placement ("Place All Destinations") ─────────
    semanticBatchPlaceAll: 'تحديد مواقع جميع الوجهات',
    navBuildMode: 'بناء التنقل التلقائي',
    toolboxTitle: 'أدوات التنقل',
    toolboxMove: 'تحريك لوحة الأدوات',
    toolboxMinimize: 'طي لوحة الأدوات',
    toolboxRestore: 'توسيع لوحة الأدوات',
    toolboxGroupDraw: 'الرسم',
    toolboxGroupRouting: 'المسارات',
    toolboxGroupDestinations: 'الوجهات',
    toolboxGroupEditing: 'تحرير الخريطة والشبكة',
    toolboxGroupAutomation: 'الأتمتة',
    semanticDestModeShort: 'إنشاء من التحليل',
    syncRoomsActionShort: 'مزامنة الغرف',
    navBuildModeShort: 'بناء تلقائي',
    navBuildTitle: 'بناء التنقل التلقائي',
    navBuildReadOnly:
      'معاينة فقط — لا يتم حفظ أي شيء. لا يتم إنشاء غرف أو نقاط أو وصلات أو رموز QR.',
    navBuildRun: 'معاينة بناء التنقل التلقائي',
    navBuildRunning: 'جارٍ تحليل مخطط الطابق…',
    navBuildFailed: 'فشلت معاينة بناء التنقل التلقائي',
    navBuildRefused: 'تعذّر إنشاء أي شيء لهذه الخريطة.',
    navBuildStage: 'المرحلة',
    navBuildLayers: 'إظهار على الخريطة',
    navBuildLayer_region: 'منطقة المبنى',
    navBuildLayer_rejected: 'المناطق المرفوضة',
    navBuildLayer_graph: 'شبكة الممرات',
    navBuildLayer_arrivals: 'نقاط الوصول للغرف',
    navBuildLayer_attachments: 'وصلات الغرف',
    navBuildLayer_rejectedEdges: 'الوصلات المرفوضة',
    navBuildTransitNodes: 'نقاط الممرات المقترحة',
    navBuildTransitEdges: 'وصلات الممرات المقترحة',
    navBuildRoomsPositioned: 'غرف تم تحديد موقعها تلقائيًا',
    navBuildRoomsConnected: 'غرف متصلة بالشبكة',
    navBuildAcceptedRooms: 'الغرف المقبولة التي تم فحصها',
    navBuildWouldCreateQr: 'رموز QR التي سيتم إنشاؤها عند التطبيق',
    navBuildNeedsReview: 'غرف ما زالت بحاجة إليك',
    navBuildShowDiagnostics: 'إظهار التشخيصات',
    navBuildHideDiagnostics: 'إخفاء التشخيصات',
    navBuildLabelSource: 'مصدر النصوص',
    semanticAutoPlacedBadge: 'تم تحديد الموقع من نص الخريطة',
    semanticAutoPlacedDetail: (label) => `تمت مطابقة النص "${label}" المطبوع على هذه الخريطة.`,
    semanticAutoPlacedConnects: (name) => `يصل إلى ${name} بخط واضح.`,
    semanticAutoPlacedCheckHint: 'يمكنك مراجعته أو نقله أو رفضه مثل أي وجهة أخرى.',
    semanticAutoPlacedSummary: (placed, total) =>
      `تم تحديد موقع ${placed} من ${total} وجهة من النصوص المطبوعة على هذه الخريطة.`,
    semanticAutoPlacedNeedsClick: 'ما زالت هذه الوجهات بحاجة إلى موقع:',
    semanticAutoPlaceReasonNoLabelMatch: 'لا يوجد نص مطابق على الخريطة',
    semanticAutoPlaceReasonAmbiguous: 'أكثر من نص واحد مطابق',
    semanticAutoPlaceReasonNoConnection: 'لا يوجد مسار واضح إلى نقطة ممر',
    semanticAutoPlaceReasonNeedsConfirmation: 'بحاجة إلى موقع تؤكده بنفسك',
    semanticBatchPanelTitle: 'التحديد الجماعي للمواقع',
    semanticBatchDestinationOf: (i, n) => `الوجهة ${i} من ${n}`,
    semanticBatchClickInstructions: 'اضغطي على موقع الباب على الخريطة.',
    semanticBatchLocationRecorded: 'تم تسجيل الموقع لهذه الوجهة.',
    semanticBatchLocationSelected: (name) => `تم تحديد الموقع لـ ${name}`,
    semanticBatchProgressPlaced: (placed, total) => `تم تحديد ${placed} من ${total}`,
    semanticBatchProgressRemaining: (remaining) => `المتبقي ${remaining}`,
    semanticBatchProgressRejected: (rejected) => `المرفوض ${rejected}`,
    semanticBatchEnterHint: 'اضغطي Enter للانتقال إلى الوجهة التالية.',
    semanticBatchAllResolved: 'تم تحديد موقع أو تخطي أو رفض كل الوجهات. افتحي المراجعة للحفظ.',
    semanticBatchPrevious: 'السابق',
    semanticBatchSkip: 'تخطي الآن',
    semanticBatchReject: 'رفض الوجهة',
    semanticBatchUndo: 'التراجع عن آخر تحديد موقع',
    semanticBatchChangeLocation: 'تغيير الموقع',
    semanticBatchExit: 'إنهاء وضع التحديد',
    semanticBatchReviewTitle: 'مراجعة الوجهات',
    semanticBatchBackToPlacement: 'العودة إلى التحديد',
    semanticBatchSaveAll: 'حفظ جميع الوجهات',
    semanticBatchSaveConfirmTitle: 'حفظ جميع الوجهات؟',
    semanticBatchSaveConfirmBody: (count) =>
      `سيؤدي هذا إلى إنشاء أو إعادة استخدام ${count} وجهة/وجهات في حفظ نهائي واحد. لن يتم حفظ أي شيء حتى تؤكدي.`,
    semanticBatchSaveFailedWithErrors: 'فشلت بعض الوجهات في التحقق — لم يتم حفظ أي شيء. أصلحي العناصر أدناه وحاولي مرة أخرى.',
    semanticBatchExitWarningTitle: 'إنهاء وضع التحديد؟',
    semanticBatchExitWarningBody: 'لديك تقدم غير محفوظ في التحديد. يبقى محفوظًا محليًا في هذا المتصفح، لكن لن يتم حفظ أي شيء في قاعدة البيانات حتى تضغطي حفظ جميع الوجهات.',
    semanticBatchResumeDraftTitle: 'استئناف التحديد السابق؟',
    semanticBatchResumeDraftBody: 'وجدنا تقدمًا غير محفوظ للتحديد الجماعي لهذه الخريطة. هل تريدين الاستئناف من حيث توقفت، أم البدء من جديد؟',
    semanticBatchResumeDraft: 'استئناف التحديد',
    semanticBatchDiscardDraft: 'تجاهل المسودة',
    semanticBatchFloorLabel: (floor) => `الطابق ${floor}`,
    semanticBatchNoLocationYet: 'لا يوجد موقع بعد',
    semanticBatchStatusReady: 'جاهز',
    semanticBatchStatusRejected: 'مرفوض',
    semanticBatchStatusMissing: 'الموقع مفقود',

    testMode: 'اختبار المسار',
    testStart: 'نقطة البداية',
    testEnd: 'نقطة الوجهة',
    testSelectStart: 'اختر نقطة البداية',
    testSelectEnd: 'اختر الوجهة',
    testFind: 'ابحث عن مسار',
    testClear: 'مسح الاختبار',
    testChangeStart: 'تغيير البداية',
    testChangeEnd: 'تغيير الوجهة',
    testCalculating: 'جاري حساب المسار...',
    testNoRoute: 'لم يتم العثور على مسار بين هاتين النقطتين',
    testDistance: (meters) => `المسافة الإجمالية: ${meters.toFixed(1)} م`,
    testStepCount: (n) => `${n} نقطة على هذا المسار`,
    processing: 'جاري تجهيز الخريطة',
    processingFailed: 'فشلت معالجة الخريطة',
    confirmDelete: 'حذف الخريطة المختارة؟',
    yesDelete: 'نعم، احذف',
    cancel: 'إلغاء',
    addPoint: 'إضافة نقطة مسار',
    savePoint: 'حفظ نقطة المسار',
    savedPoint: 'تم حفظ نقطة المسار',
    selectPoint: 'اضغطي على الخريطة لاختيار نقطة مسار',
    pointName: 'اسم النقطة',
    pointType: 'نوع النقطة',
    floor: 'الطابق',
    noSelectedMap: 'لا توجد خريطة مختارة',
    uploadTitle: 'رفع خارطة جديدة',
    chooseFile: 'اختيار ملف الخريطة',
    selectedFile: 'الملف المختار',
    mapTitle: 'اسم الخريطة',
    campus: 'الحرم / الموقع',
    address: 'العنوان',
    description: 'الوصف',
    scale: 'مقياس الخريطة',
    useOpenAI: 'استخدام OpenAI لمعالجة الصورة',
    uploadBuilding: 'المبنى',
    uploadBuildingAuto: 'إنشاء/إعادة استخدام تلقائي من اسم الحرم',
    uploadFloor: 'الطابق',
    uploadAutoGenerateGraph: 'توليد شبكة المسارات تلقائيًا بعد المعالجة',
    regenerateGraph: 'توليد شبكة المسارات (تجريبي)',
    graphGenerationExperimentalNote:
      'ميزة اختيارية وتجريبية للتوليد التلقائي من صورة الخريطة. الإضافة اليدوية لنقاط المسار هي أسلوب العمل الموصى به والمدعوم — راجع الشبكة المقترحة بعناية قبل التأكيد.',
    graphGenerating: 'جارٍ التوليد...',
    clearGeneratedGraph: 'مسح الشبكة المولدة تلقائيًا',
    graphGenerationDone: 'انتهى توليد شبكة المسارات القابلة للمشي.',
    graphGenerationFailed: 'فشل توليد شبكة المسارات',
    graphClearedSummary: (points, edges) =>
      `تم مسح ${points} نقطة و ${edges} حافة تم توليدها تلقائيًا.`,

    removeGeneratedNavData: 'حذف بيانات المسارات المولّدة',
    resetAllNavData: 'مسح جميع بيانات المسارات من هذه الخريطة',
    cleanupPreviewLoading: 'جارٍ تحميل المعاينة…',
    cleanupPreviewFailed: 'فشل تحميل معاينة حذف البيانات المولّدة',
    cleanupApplyFailed: 'فشل حذف بيانات المسارات المولّدة',
    cleanupApplySummary: (points, edges) =>
      `تم حذف ${points} نقطة مسار و ${edges} اتصال تم توليدهما تلقائيًا.`,
    cleanupPreviewTitle: 'حذف بيانات المسارات المولّدة — معاينة',
    cleanupGeneratedPoints: 'نقاط مسار مولّدة (سيتم حذفها)',
    cleanupGeneratedEdges: 'اتصالات مولّدة (سيتم حذفها)',
    cleanupManualPoints: 'نقاط مسار يدوية (ستبقى)',
    cleanupManualEdges: 'اتصالات يدوية (ستبقى)',
    cleanupUnknownLegacy: 'نقاط غير مؤكدة/قديمة (ستبقى — لم يثبت أنها مولّدة)',
    cleanupUnknownLegacyNote: 'لم يثبت أنها مولّدة، لذلك لن تُحذف بهذا الإجراء أبدًا.',
    cleanupLinkedRooms: 'غرف مرتبطة بنقاط مولّدة',
    cleanupLinkedConnectors: 'وصلات رأسية مرتبطة بنقاط مولّدة',
    cleanupDependentEdges: 'اتصالات يدوية ستُحذف أيضًا (متصلة بنقطة مولّدة)',
    cleanupNoneToDelete: 'لم يتم العثور على أي بيانات مؤكدة أنها مولّدة في هذه الخريطة — لا يوجد ما يُحذف.',
    cleanupConfirmButton: 'حذف البيانات المولّدة',
    cleanupApplying: 'جارٍ الحذف…',

    resetPreviewFailed: 'فشل تحميل معاينة إعادة ضبط بيانات المسارات',
    resetApplyFailed: 'فشل إعادة ضبط بيانات المسارات لهذه الخريطة',
    resetApplySummary: (points, edges) =>
      `تم حذف ${points} نقطة مسار و ${edges} اتصال من هذه الخريطة.`,
    resetPreviewTitle: 'مسح جميع بيانات المسارات من هذه الخريطة — معاينة',
    resetWarning:
      'سيؤدي هذا إلى حذف جميع نقاط واتصالات المسارات في هذه الخريطة، بما في ذلك ما تمت إضافته يدويًا. سيتعطل التنقل العام في هذه الخريطة حتى يضيف المسؤول نقاط مسار جديدة يدويًا. لا يمكن التراجع عن هذا الإجراء.',
    resetTotalPoints: 'إجمالي نقاط المسار في هذه الخريطة',
    resetTotalEdges: 'إجمالي الاتصالات في هذه الخريطة',
    resetBreakdownManual: 'يدوية',
    resetBreakdownGenerated: 'مولّدة',
    resetBreakdownSemantic: 'وجهات دلالية',
    resetBreakdownConnector: 'محطات وصلات رأسية',
    resetBreakdownUnknown: 'غير مؤكدة/قديمة',
    resetLinkedRooms: 'غرف مرتبطة (سيُزال الرابط، وتبقى الغرفة)',
    resetLinkedConnectors: 'وصلات رأسية متأثرة (تبقى بياناتها)',
    resetLinkedLocationCodes: 'رموز QR/مواقع مرتبطة (سيتم تعطيلها)',
    resetNoneToDelete: 'لا توجد نقاط مسار أو اتصالات في هذه الخريطة — لا يوجد ما يُعاد ضبطه.',
    resetConfirmInstructions: (mapName) =>
      `اكتب اسم هذه الخريطة ("${mapName}") أو العبارة "RESET NAVIGATION DATA" للتأكيد.`,
    resetConfirmPlaceholder: 'اكتب اسم الخريطة أو RESET NAVIGATION DATA',
    resetConfirmButton: 'حذف جميع بيانات المسارات نهائيًا',
    resetApplying: 'جارٍ إعادة الضبط…',

    upload: 'رفع الخريطة',
    uploading: 'جاري الرفع...',
    uploadSuccess: 'تم رفع الخريطة وبدأ تجهيزها تلقائيًا.',
    uploadError: 'فشل رفع الخريطة',
    requiredUploadFields: 'اسم الخريطة والملف مطلوبان',
    editTitle: 'تعديل تفاصيل الخريطة',
    editFloorLabel: 'الطابق',
    floorNotConfigured: 'الطابق غير محدد',
    saveChanges: 'حفظ التغييرات',
    details: {
      title: 'الاسم',
      campus: 'الحرم',
      address: 'العنوان',
      description: 'الوصف',
      status: 'الحالة',
      mapId: 'رقم الخريطة',
    },
    modeSingle: 'خريطة طابق واحد',
    modeMulti: 'خريطة متعددة الطوابق',
    modeSingleHint: 'ارفعي صورة واحدة كخريطة واحدة.',
    modeMultiHint: 'ارفعي عدة طوابق لنفس المبنى كمجموعة خرائط واحدة.',
    mapGroupInfoTitle: 'معلومات مجموعة الخريطة',
    mapGroupName: 'اسم مجموعة الخريطة',
    mapGroupCode: 'رمز مجموعة الخريطة المشترك',
    mapGroupCodeHint: 'اختياري — اتركه فارغًا للتوليد التلقائي. أحرف وأرقام وشرطات فقط.',
    mapGroupNameRequired: 'اسم مجموعة الخريطة مطلوب (حرفان على الأقل).',
    floorRowsInvalid: 'صححي صفوف الطوابق المميزة قبل الرفع.',
    mapGroupUploadSuccess: 'تم رفع مجموعة الخريطة بنجاح. بدأت معالجة كل طابق.',
    mapGroupUploadError: 'فشل رفع مجموعة الخريطة',
    floorMapsListTitle: 'خرائط الطوابق',
    floorNumber: 'رقم الطابق',
    floorLabel: 'تسمية الطابق',
    floorTitle: 'عنوان الطابق',
    floorScale: 'مقياس الخريطة',
    floorFile: 'ملف خريطة الطابق',
    addAnotherFloor: 'إضافة طابق آخر',
    removeFloor: 'إزالة الطابق',
    uploadAllFloors: 'رفع جميع الطوابق',
    uploadingFloors: 'جاري رفع الطوابق...',
    groupFloorCount: (n) => `${n} طابق`,
    expandGroup: 'إظهار الطوابق',
    collapseGroup: 'إخفاء الطوابق',
    addFloor: 'إضافة طابق',
    editGroup: 'تعديل المجموعة',
    deleteGroup: 'حذف المجموعة',
    viewAllFloors: 'عرض جميع الطوابق',
    confirmDeleteFloor: (title) => `حذف خريطة الطابق "${title}"؟ لن يتم حذف مجموعة الخريطة.`,
    confirmDeleteGroup: (name) => `حذف مجموعة الخريطة "${name}" وجميع طوابقها؟`,
    floorSwitcher: 'الطابق',
    ungroupedMapsTitle: 'خرائط الطابق الواحد',
    addFloorTitle: 'إضافة طابق',
    saveFloor: 'إضافة الطابق',
    floorSwitchConfirm: 'تبديل الطابق؟ ستفقد نقاط المسودة غير المحفوظة في هذا الطابق.',
    calibrateMode: 'معايرة مقياس الخريطة',
    calibrateInstructions: 'اختاري نقطتين على الخريطة',
    calibratePointA: 'النقطة أ',
    calibratePointB: 'النقطة ب',
    calibrateDistanceTitle: 'المسافة الحقيقية بالمتر',
    calibrateDistancePlaceholder: 'مثال: 5.5',
    calibrateDistanceInvalid: 'أدخلي مسافة أكبر من 0',
    calibrateNeedTwoPoints: 'اضغطي على نقطتين على الخريطة أولاً',
    calibrateSubmit: 'حفظ المعايرة',
    calibrateSaving: 'جاري حفظ المعايرة...',
    calibrateSuccess: 'تم حفظ المعايرة بنجاح',
    calibrateScaleResult: (metersPerPixel) => `المقياس: ${metersPerPixel.toFixed(4)} م/بكسل`,
    calibrateEdgesRecalculated: (n) => `تم إعادة حساب ${n} حافة مسار`,
    calibrateEdgesSkipped: (n) => `تم تخطي ${n} حافة`,
    calibrateError: 'فشل حفظ المعايرة',
    calibrateCancel: 'إلغاء المعايرة',
    calibrateReset: 'إعادة اختيار النقاط',
    calibrateClose: 'حسناً',
  },

  he: {
    title: 'ניהול מפה',
    back: 'חזרה',
    backToRoom: 'חזרה לחדר (הטיוטה נשמרה)',
    roomDraftBanner: 'טיוטת החדר נשמרה. העלה כאן מפה ותחזור אליה אוטומטית.',
    selectMap: 'בחירת מפה',
    uploadNewMap: 'העלאת מפה חדשה',
    editDetails: 'ערוך פרטים',
    deleteMap: 'מחק מפה',
    selectedMap: 'מפה נבחרת',
    current: 'נוכחית',
    noMap: 'לא הועלתה מפה',
    noMapHint: 'העלי תמונת מפה או PDF כדי להתחיל',
    openFullMap: 'לחצי על המפה כדי לפתוח תצוגה מלאה',
    savedPoints: 'נקודות שמורות',
    noPoints: 'עדיין אין נקודות שמורות למפה זו',
    savedEdges: 'קשתות שמורות',
    noEdges: 'עדיין אין קשתות מסלול שמורות למפה זו',
    loadingMaps: 'טוען מפות...',
    loadingPoints: 'טוען נקודות מסלול...',
    loadingEdges: 'טוען קשתות מסלול...',
    mapsError: 'טעינת המפות נכשלה',
    pointsError: 'טעינת נקודות המסלול נכשלה',
    edgesError: 'טעינת קשתות המסלול נכשלה',
    edgeDataWarning: 'קשת/קשתות מסלול מצביעות על נקודה שלא נמצאה במפה זו ולא צוירו',
    addPointMode: 'הוסף נקודה',
    drawMode: 'צייר מסלול הליכה',
    drawHint: 'לחצי על המפה כדי להוסיף נקודות מסדרון. לחצי ליד נקודה קיימת כדי לעשות בה שימוש חוזר.',
    drawFloor: 'קומה',
    noMapForFloor: 'לא הוגדרה מפה עבור קומה זו.',
    noFloorMapsLoaded: 'לא נטענו מפות קומה עבור קבוצת מפות זו.',
    retryMapsButton: 'נסה שוב לטעון מפות',
    analyzeFloorMap: 'נתח מפת קומה (הצעות בינה מלאכותית)',
    repairFloorsButton: 'תקן קומות של נקודות מסלול מהמפות',
    repairFloorsRunning: 'בודק…',
    repairFloorsNoneNeeded: 'אין נקודות מסלול הדורשות תיקון — כל נקודה כבר תואמת את קומת המפה שלה.',
    repairFloorsConfirm: (count) =>
      `הקומה של ${count} נקודות תתוקן כך שתתאים למפה שלהן. להחיל את התיקון עכשיו?`,
    repairFloorsDone: (count) =>
      `תוקנו ${count} נקודות. הנקודות והמסלולים עודכנו.`,
    repairFloorsFailed: 'תיקון קומות נקודות המסלול נכשל.',
    drawUndo: 'בטל',
    drawClear: 'נקה',
    drawCancel: 'ביטול',
    drawSave: 'שמור מסלול',
    drawSaving: 'שומר...',
    drawNeedTwo: 'הוסף לפחות 2 נקודות לפני השמירה',
    drawInvalidNames: 'הזן שם תקין לכל נקודה חדשה לפני השמירה',
    drawPointListTitle: 'נקודות הטיוטה',
    drawStatusNew: 'חדשה',
    drawStatusExisting: 'קיימת',
    drawStatusMergeHint: 'ייתכן מיזוג אוטומטי עם נקודה קרובה',
    drawNamePlaceholder: 'שם הנקודה',
    drawNameEmpty: 'נדרש שם',
    drawNameTooShort: 'השם קצר מדי',
    drawNameTooLong: 'השם ארוך מדי',
    drawRemovePoint: 'הסר',
    drawSaveSuccess: (points, edges, reused = 0, skippedEdges = 0, mergedEdges = 0) => {
      let message = `נשמרו ${points} נקודות חדשות ו-${edges} קשתות`;
      if (reused > 0) {
        message += `, נעשה שימוש חוזר ב-${reused} נקודות קיימות`;
      }
      if (skippedEdges > 0) {
        message += ` (${skippedEdges} קשתות כפולות דולגו)`;
      }
      if (mergedEdges > 0) {
        message += `, נוספו ${mergedEdges} קשתות מיזוג אוטומטי לנקודות קרובות`;
      }
      return message;
    },
    drawSaveFailed: 'לא ניתן היה לשמור את המסלול. נקודות וקשתות שנוצרו לאחרונה בוטלו.',
    drawWrongPointReject: 'לא ניתן לעשות שימוש חוזר בנקודה זו כאן (מפה/קומה שונה או לא פעילה) — לחצי שוב כדי למקם נקודה חדשה במקום זאת.',
    drawWrongMapReject: (floorLabel) =>
      `נקודת יעד זו שייכת למפה אחרת. יש לשייך מחדש את היעד למפת ${floorLabel} הנוכחית לפני החיבור.`,
    drawPointCount: (n) => `${n} נקודות בטיוטה`,
    drawReusedPoint: 'שימוש חוזר בנקודה קיימת',
    drawMergeModeLabel: 'מיזוג גרף אוטומטי',
    drawMergeModeOff: 'כבוי',
    drawMergeModeReuseOnly: 'שימוש חוזר בנקודות קיימות שנבחרו בלבד',
    drawMergeModeNearby: 'מיזוג עם נקודות גרף קרובות בטוחות',
    drawSummaryTitle: 'לפני השמירה',
    drawSummaryNewPoints: (n) => `נקודות חדשות: ${n}`,
    drawSummaryReusedPoints: (n) => `נקודות קיימות בשימוש חוזר: ${n}`,
    drawSummaryPlannedEdges: (n) => `קשתות חדשות מתוכננות: ${n}`,
    drawSummarySkippedEdges: (n) => `קשתות קיימות בשימוש חוזר/דולגו: ${n}`,
    panelMove: 'הזז את הפאנל',
    panelMinimize: 'מזער את הפאנל',
    panelRestore: 'שחזר את הפאנל',
    panelDockLeft: 'עגן משמאל',
    panelDockRight: 'עגן מימין',
    panelDockBottom: 'עגן למטה',
    building: 'מבנה',
    room: 'חדר',
    selectBuilding: 'בחר מבנה',
    selectRoom: 'בחר חדר',
    connectNearest: 'חבר לנקודת המסדרון הקרובה ביותר',
    roomAlreadyLinked: (name) => `החדר הזה כבר מקושר ל-"${name}"`,
    pointWillBecomeDestination: 'נקודה זו תופיע כיעד למשתמש',
    syncRoomsAction: 'סנכרון חדרים מנקודות מסלול',
    syncRoomsSuccess: 'החדרים סונכרנו בהצלחה',
    syncRoomsConfirmTitle: 'לסנכרן חדרים מנקודות מסלול?',
    syncRoomsConfirmBody:
      'פעולה זו יוצרת או מעדכנת חדרי יעד עבור נקודות מסלול קיימות מסוג חדר/חנות בבניין זה כדי שיופיעו ברשימת היעדים של המשתמש. היא לא משנה את גרף ההליכה או הניווט בשום צורה.',
    syncRoomsConfirmButton: 'סנכרן עכשיו',
    syncRoomsRunning: 'מסנכרן...',
    syncRoomsNoScope: 'בחר מפה כדי לסנכרן את חדרי הבניין שלה.',
    syncRoomsSummary: ({ scanned, created, updated, skipped, failed }) =>
      `נסרקו ${scanned} · נוצרו ${created} · עודכנו ${updated} · דולגו ${skipped} · נכשלו ${failed}`,
    syncRoomsFailed: 'סנכרון החדרים מנקודות המסלול נכשל',
    editPointsMode: 'עריכת נקודות מסלול',
    editPointsInstructions: 'לחץ על נקודה קיימת במפה כדי לערוך אותה.',
    editPointsPanelTitle: 'עריכת נקודת מסלול',
    editPointsNameLabel: 'שם',
    editPointsTypeLabel: 'סוג נקודה',
    editPointsMovePoint: 'הזז נקודה',
    editPointsMovingActive: 'לחץ על המיקום החדש…',
    editPointsOutOfBounds: 'המיקום הזה מחוץ לתמונת המפה.',
    editPointsSaveError: 'שמירת השינויים נכשלה.',
    editPointsNameTooShort: 'השם קצר מדי.',
    editPointsDeleteError: 'מחיקת הנקודה נכשלה.',
    editPointsConnectedEdges: 'קשרים מחוברים',
    editPointsNone: 'אין',
    editPointsInaccessible: 'לא נגיש',
    editPointsLinkedRoom: 'חדר מקושר',
    editPointsLinkedConnector: 'מחבר אנכי מקושר',
    editPointsDeleteAction: 'מחק נקודה זו',
    editPointsConfirmDelete: 'למחוק נקודת מסלול זו? לא ניתן לבטל פעולה זו.',
    deleteConnectionMode: 'מחיקת חיבור',
    deleteConnectionInstructions: 'לחץ על חיבור קיים כדי לבחור אותו למחיקה.',
    deleteConnectionCancelMode: 'ביטול מצב מחיקה',
    deleteConnectionConfirmTitle: 'למחוק את החיבור הזה?',
    deleteConnectionFromLabel: 'מ',
    deleteConnectionToLabel: 'אל',
    deleteConnectionTypeLabel: 'סוג החיבור',
    deleteConnectionFloorLabel: 'קומה / מפה',
    deleteConnectionSafetyNote: 'רק החיבור יימחק ושתי הנקודות יישארו.',
    deleteConnectionConfirmButton: 'מחיקת חיבור',
    deleteConnectionDeleting: 'מוחק...',
    deleteConnectionSuccess: 'החיבור נמחק בהצלחה',
    deleteConnectionFailed: 'מחיקת החיבור נכשלה',
    deleteConnectionVerticalBlocked: 'יש לנהל את החיבור הזה דרך חיבורים בין קומות.',
    autoConnectMode: 'חיבור יעדים אוטומטי',
    autoConnectScanning: 'סורק יעדים לא מחוברים...',
    autoConnectPreviewTitle: 'תצוגה מקדימה של חיבורים',
    autoConnectScopeMap: 'המפה הנוכחית',
    autoConnectScopeMapGroup: 'כל המפות בקבוצת המפות',
    autoConnectManualPickInstructions: 'לחץ על נקודת מסדרון במפה.',
    autoConnectAcceptAllHighConfidence: 'אישור כל ההצעות בביטחון גבוה',
    autoConnectRejectAllLowConfidence: 'דחיית כל ההצעות בביטחון נמוך',
    autoConnectNothingToReview: 'לא נמצאו יעדי חדר/חנות לא מחוברים במפה זו.',
    autoConnectNoCorridorPointFound: 'לא נמצאה נקודת מסדרון',
    autoConnectReasonNoTransitPoints: 'אין נקודות מסדרון/צומת במפה/בקומה זו',
    autoConnectReasonTransitNotConnected: 'קיימות נקודות מסדרון/צומת אך הן אינן מחוברות זו לזו בשום חיבור מסלול',
    autoConnectReasonTooFar: 'אין נקודת מסדרון/צומת קרובה מספיק לחיבור',
    autoConnectReasonNestedParentNotReady: 'חדר האב המאושר עדיין אינו מוכן לקבל חיבורים',
    autoConnectReasonBlockedByWall: 'קיימת נקודת מסדרון קרובה אך קיר חוסם את החיבור',
    autoConnectReasonCorridorIsolated: 'קיימת נקודת מסדרון קרובה אך היא אינה מחוברת לגרף ההליכה',
    autoConnectReasonNestedParentNotPassThrough: 'חדר האב אינו מאושר למעבר — אשרו אותו כדי לחבר חדר זה',
    autoConnectReasonNestedParentNoPoint: 'לחדר האב המאושר אין עדיין מיקום במפה',
    autoConnectTargetCorridorEdge: 'מתחבר באמצע המסדרון (תתווסף צומת)',
    autoConnectDiagnosticsClearLine: 'קו פנוי',
    autoConnectDiagnosticsGraphConnected: 'על גרף ההליכה',
    autoConnectDiagnosticsBlockedCount: 'מועמדים שנדחו בגלל קיר',
    autoConnectDiagnosticsIsolatedCount: 'מועמדים מחוץ לגרף ההליכה',
    autoConnectDiagnosticsParentPassThrough: 'חדר האב מאפשר מעבר',
    autoConnectDiagnosticsNearest: 'המסדרון הקרוב ביותר שנמצא',
    autoConnectNeedsReviewBadge: 'דורש בדיקה',
    autoConnectTargetTypeLabel: 'סוג החיבור',
    autoConnectNestedParentLabel: 'חדר האב',
    autoConnectJunctionsCreated: 'צמתי מסדרון שנוספו',
    autoConnectUncalibrated: 'לא מכויל',
    autoConnectConfidenceHigh: 'ביטחון גבוה',
    autoConnectConfidenceMedium: 'ביטחון בינוני',
    autoConnectConfidenceLow: 'ביטחון נמוך',
    autoConnectNeedsReview: 'דורש בדיקה',
    autoConnectAlreadyConnected: 'מחובר כבר',
    autoConnectNestedAccessBadge: 'גישה מקוננת — מתחבר לחדר האב שאושר',
    autoConnectInvalidEdgesWarning:
      'ליעד זה יש חיבורים קיימים שאינם חיבורי מסדרון תקינים. הם לא יימחקו אוטומטית.',
    autoConnectAccept: 'אישור',
    autoConnectReject: 'דחייה',
    autoConnectPickManually: 'בחירת נקודה אחרת במפה',
    autoConnectReviewComplete: 'הבדיקה הושלמה',
    autoConnectConfirmTitle: 'ליצור את החיבורים שאושרו?',
    autoConnectConfirmBody:
      'רק חיבורי היעדים שאושרו אל המסדרון ייווצרו. נקודות וחיבורים קיימים לא ישתנו.',
    autoConnectBackToPreview: 'חזרה לתצוגה המקדימה',
    autoConnectApplying: 'יוצר חיבורים...',
    autoConnectCreateAccepted: 'יצירת החיבורים שאושרו',
    autoConnectResultTitle: 'החיבורים נוצרו בהצלחה',
    autoConnectNoAccepted: 'יש לאשר הצעה אחת לפחות לפני יצירת חיבורים.',
    autoConnectPreviewFailed: 'תצוגת החיבורים המקדימה נכשלה',
    autoConnectApplyFailed: 'יצירת החיבורים נכשלה',
    autoConnectScannedCount: (n) => `נסרקו: ${n}`,
    autoConnectProposedCount: (n) => `הוצעו: ${n}`,
    autoConnectAcceptedCount: (n) => `אושרו: ${n}`,
    autoConnectRejectedCount: (n) => `נדחו: ${n}`,
    autoConnectSummaryLine: (s) =>
      `נסרקו ${s.scanned} · מחובר כבר ${s.already_connected} · הוצע ${s.proposed} · דורש בדיקה ${s.needs_review} · אין מועמד ${s.no_candidate}`,
    autoConnectProposedCorridorLine: (name, distanceText) =>
      `מוצע: ${name}${distanceText ? ` — ${distanceText}` : ''}`,
    autoConnectResultLine: (r) =>
      `התבקשו ${r.requested} · נוצרו ${r.created} · דולגו (מחובר כבר) ${r.skipped_existing} · נדחו לא תקינים ${r.rejected_invalid} · נכשלו ${r.failed}`,
    // ── Create Destinations from Approved Analysis ──────────────────────────
    semanticDestMode: 'יצירת יעדים מהניתוח שאושר',
    semanticDestScanning: 'סורק ניתוח סמנטי שאושר...',
    semanticDestPreviewTitle: 'תצוגה מקדימה של יעדים',
    semanticDestScannedCount: (n) => `נסרקו: ${n}`,
    semanticDestNewCount: (n) => `יעדים חדשים: ${n}`,
    semanticDestNeedsLocationCount: (n) => `דורש בדיקת מיקום: ${n}`,
    semanticDestNestedCount: (n) => `קשרים מקוננים: ${n}`,
    semanticDestManualPlaceInstructions: 'לחץ על המיקום הנכון במפה עבור יעד זה.',
    semanticDestNothingToReview: 'לא נמצאו יעדים מאושרים ליצירה.',
    semanticDestExcluded: 'הוחרג מיצירת יעדים',
    semanticDestNeedsLocationReview:
      'דורש בדיקת מיקום — לא נמצאה נקודה קיימת. לחץ על "בחירת מיקום" כדי למקם אותו.',
    semanticDestExistingLocation: 'המיקום נמצא מנקודת מסלול קיימת',
    semanticDestNestedTitle: 'ייתכן שהיעד נמצא בתוך יעד אחר',
    semanticDestNestedLine: (name) => `ייתכן שיעד זה נמצא בתוך ${name}.`,
    semanticDestConfirmNested: 'אישור הקשר המקונן',
    semanticDestAllowTransit: 'לאפשר למשתמשים לעבור דרך חדר זה כדי להגיע ליעדים אחרים',
    semanticDestPickLocation: 'בחירת מיקום',
    semanticDestConfirmTitle: 'ליצור את היעדים שאושרו?',
    semanticDestConfirmBody:
      'רק היעדים שאושרו ייווצרו כחדרים ונקודות מסלול. נקודות וחיבורים קיימים לא ישתנו.',
    semanticDestNestedConfirmBody:
      'המשתמשים יורשו לעבור דרך החדר החיצוני כדי להגיע ליעד הפנימי.',
    semanticDestCreateAccepted: 'יצירת היעדים שאושרו',
    semanticDestResultTitle: 'היעדים נוצרו בהצלחה',
    semanticDestResultRoomsLine: (r) => `חדרים שנוצרו: ${r.rooms_created}`,
    semanticDestResultPointsLine: (r) => `נקודות מסלול שנוצרו: ${r.route_points_created}`,
    semanticDestResultQrLine: (r) =>
      `קודי QR לחדרים: ${r.qr_codes_created ?? 0} נוצרו, ${r.qr_codes_reused ?? 0} כבר היו קיימים`,
    semanticDestResultNotNavigableLine: (r) =>
      `עדיין לא ניתנות לניווט: ${(r.rooms_unconnected ?? 0) + (r.rooms_unplaced ?? 0)} חדרים — לא הונפק קוד`,
    semanticDestNotNavigableHint:
      'חדר מקבל קוד QR רק לאחר שמוקם על המפה וחובר לרשת המסדרונות. מקם את החדרים החסרים ואז הפעל חיבור אוטומטי של יעדים — הקודים מונפקים אוטומטית.',
    semanticDestReasonNoArrivalPoint: 'טרם מוקם על המפה',
    semanticDestReasonInactivePoint: 'נקודת המפה חסרה או לא פעילה',
    semanticDestReasonNotConnected: 'לא מחובר לרשת המסדרונות',
    semanticDestReasonNoBuilding: 'למפה שלו לא משויך בניין',
    semanticDestResultUpdatedLine: (r) => `יעדים קיימים שעודכנו: ${r.rooms_updated}`,
    semanticDestResultNestedLine: (r) => `יעדים מקוננים שנוצרו: ${r.nested_relationships_created}`,
    semanticDestResultNeedsReviewLine: (r) => `פריטים הדורשים בדיקה: ${r.skipped + r.ambiguous}`,
    semanticDestResultFailedLine: (r) => `פריטים שנכשלו: ${r.failed}`,
    semanticDestPreviewFailed: 'תצוגת היעדים המקדימה נכשלה',
    semanticDestNoAccepted: 'יש לאשר הצעה אחת לפחות לפני יצירת יעדים.',
    semanticDestApplyFailed: 'יצירת היעדים נכשלה',

    // ── Fast Batch Destination Placement ("Place All Destinations") ─────────
    semanticBatchPlaceAll: 'מיקום כל היעדים',
    navBuildMode: 'בניית ניווט אוטומטית',
    toolboxTitle: 'כלי ניווט',
    toolboxMove: 'הזזת חלונית הכלים',
    toolboxMinimize: 'כיווץ חלונית הכלים',
    toolboxRestore: 'הרחבת חלונית הכלים',
    toolboxGroupDraw: 'שרטוט',
    toolboxGroupRouting: 'ניתוב',
    toolboxGroupDestinations: 'יעדים',
    toolboxGroupEditing: 'עריכת מפה ורשת',
    toolboxGroupAutomation: 'אוטומציה',
    semanticDestModeShort: 'יצירה מהניתוח',
    syncRoomsActionShort: 'סנכרון חדרים',
    navBuildModeShort: 'בנייה אוטומטית',
    navBuildTitle: 'בניית ניווט אוטומטית',
    navBuildReadOnly:
      'תצוגה מקדימה בלבד — שום דבר לא נשמר. לא נוצרים חדרים, נקודות, חיבורים או קודי QR.',
    navBuildRun: 'הצג בניית ניווט אוטומטית',
    navBuildRunning: 'מנתח את תוכנית הקומה…',
    navBuildFailed: 'התצוגה המקדימה של בניית הניווט נכשלה',
    navBuildRefused: 'לא ניתן היה ליצור דבר עבור מפה זו.',
    navBuildStage: 'שלב',
    navBuildLayers: 'הצג על המפה',
    navBuildLayer_region: 'אזור המבנה',
    navBuildLayer_rejected: 'אזורים שנדחו',
    navBuildLayer_graph: 'רשת המסדרונות',
    navBuildLayer_arrivals: 'נקודות הגעה לחדרים',
    navBuildLayer_attachments: 'חיבורי חדרים',
    navBuildLayer_rejectedEdges: 'חיבורים שנדחו',
    navBuildTransitNodes: 'צמתי מסדרון מוצעים',
    navBuildTransitEdges: 'חיבורי מסדרון מוצעים',
    navBuildRoomsPositioned: 'חדרים שמוקמו אוטומטית',
    navBuildRoomsConnected: 'חדרים המחוברים לרשת',
    navBuildAcceptedRooms: 'חדרים מאושרים שנסרקו',
    navBuildWouldCreateQr: 'קודי QR שייווצרו בעת החלה',
    navBuildNeedsReview: 'חדרים שעדיין זקוקים לך',
    navBuildShowDiagnostics: 'הצג אבחון',
    navBuildHideDiagnostics: 'הסתר אבחון',
    navBuildLabelSource: 'מקור הכיתובים',
    semanticAutoPlacedBadge: 'מוקם לפי הכיתוב במפה',
    semanticAutoPlacedDetail: (label) => `הותאם לכיתוב "${label}" המודפס במפה זו.`,
    semanticAutoPlacedConnects: (name) => `מגיע אל ${name} בקו פנוי.`,
    semanticAutoPlacedCheckHint: 'אפשר לבדוק, להזיז או לדחות אותו כמו כל יעד אחר.',
    semanticAutoPlacedSummary: (placed, total) =>
      `${placed} מתוך ${total} יעדים מוקמו לפי כיתובים המודפסים במפה זו.`,
    semanticAutoPlacedNeedsClick: 'היעדים האלה עדיין זקוקים למיקום:',
    semanticAutoPlaceReasonNoLabelMatch: 'אין כיתוב תואם במפה',
    semanticAutoPlaceReasonAmbiguous: 'יותר מכיתוב אחד תואם',
    semanticAutoPlaceReasonNoConnection: 'אין מסלול פנוי לנקודת מסדרון',
    semanticAutoPlaceReasonNeedsConfirmation: 'זקוק למיקום שתאשר',
    semanticBatchPanelTitle: 'מיקום קבוצתי',
    semanticBatchDestinationOf: (i, n) => `יעד ${i} מתוך ${n}`,
    semanticBatchClickInstructions: 'לחץ על מיקום הדלת במפה.',
    semanticBatchLocationRecorded: 'המיקום נרשם עבור יעד זה.',
    semanticBatchLocationSelected: (name) => `המיקום נבחר עבור ${name}`,
    semanticBatchProgressPlaced: (placed, total) => `מוקמו ${placed} מתוך ${total}`,
    semanticBatchProgressRemaining: (remaining) => `נותרו ${remaining}`,
    semanticBatchProgressRejected: (rejected) => `נדחו ${rejected}`,
    semanticBatchEnterHint: 'לחץ Enter כדי לעבור ליעד הבא.',
    semanticBatchAllResolved: 'כל היעדים מוקמו, דולגו או נדחו. פתח את הסקירה כדי לשמור.',
    semanticBatchPrevious: 'הקודם',
    semanticBatchSkip: 'דלג לעת עתה',
    semanticBatchReject: 'דחה יעד',
    semanticBatchUndo: 'בטל את המיקום האחרון',
    semanticBatchChangeLocation: 'שנה מיקום',
    semanticBatchExit: 'צא ממצב מיקום',
    semanticBatchReviewTitle: 'סקירת יעדים',
    semanticBatchBackToPlacement: 'חזרה למיקום',
    semanticBatchSaveAll: 'שמירת כל היעדים',
    semanticBatchSaveConfirmTitle: 'לשמור את כל היעדים?',
    semanticBatchSaveConfirmBody: (count) =>
      `פעולה זו תיצור או תשתמש מחדש ב-${count} יעד/ים בשמירה סופית אחת. שום דבר לא נשמר עד לאישור.`,
    semanticBatchSaveFailedWithErrors: 'חלק מהיעדים נכשלו באימות — שום דבר לא נשמר. תקן את הפריטים למטה ונסה שוב.',
    semanticBatchExitWarningTitle: 'לצאת ממצב מיקום?',
    semanticBatchExitWarningBody: 'יש לך התקדמות מיקום שלא נשמרה. היא נשמרת מקומית בדפדפן זה, אך שום דבר לא נכתב למסד הנתונים עד שתלחץ על שמירת כל היעדים.',
    semanticBatchResumeDraftTitle: 'להמשיך מיקום קודם?',
    semanticBatchResumeDraftBody: 'מצאנו התקדמות מיקום קבוצתי שלא נשמרה עבור מפה זו. האם ברצונך להמשיך מהנקודה שבה הפסקת, או להתחיל מחדש?',
    semanticBatchResumeDraft: 'המשך מיקום',
    semanticBatchDiscardDraft: 'מחק טיוטה',
    semanticBatchFloorLabel: (floor) => `קומה ${floor}`,
    semanticBatchNoLocationYet: 'עדיין אין מיקום',
    semanticBatchStatusReady: 'מוכן',
    semanticBatchStatusRejected: 'נדחה',
    semanticBatchStatusMissing: 'חסר מיקום',

    testMode: 'בדיקת מסלול',
    testStart: 'נקודת התחלה',
    testEnd: 'נקודת יעד',
    testSelectStart: 'בחר נקודת התחלה',
    testSelectEnd: 'בחר יעד',
    testFind: 'מצא מסלול',
    testClear: 'נקה בדיקה',
    testChangeStart: 'שנה התחלה',
    testChangeEnd: 'שנה יעד',
    testCalculating: 'מחשב מסלול...',
    testNoRoute: 'לא נמצא מסלול בין הנקודות הללו',
    testDistance: (meters) => `מרחק כולל: ${meters.toFixed(1)} מ'`,
    testStepCount: (n) => `${n} נקודות במסלול זה`,
    processing: 'מעבד את המפה',
    processingFailed: 'עיבוד המפה נכשל',
    confirmDelete: 'למחוק את המפה שנבחרה?',
    yesDelete: 'כן, מחק',
    cancel: 'ביטול',
    addPoint: 'הוסף נקודת מסלול',
    savePoint: 'שמור נקודת מסלול',
    savedPoint: 'נקודת המסלול נשמרה',
    selectPoint: 'לחצי על המפה כדי לבחור נקודת מסלול',
    pointName: 'שם הנקודה',
    pointType: 'סוג הנקודה',
    floor: 'קומה',
    noSelectedMap: 'לא נבחרה מפה',
    uploadTitle: 'העלאת מפה חדשה',
    chooseFile: 'בחירת קובץ מפה',
    selectedFile: 'הקובץ שנבחר',
    mapTitle: 'שם המפה',
    campus: 'קמפוס / מיקום',
    address: 'כתובת',
    description: 'תיאור',
    scale: 'קנה מידה',
    useOpenAI: 'השתמש ב-OpenAI לעיבוד התמונה',
    uploadBuilding: 'מבנה',
    uploadBuildingAuto: 'יצירה/שימוש חוזר אוטומטי משם הקמפוס',
    uploadFloor: 'קומה',
    uploadAutoGenerateGraph: 'צור אוטומטית גרף מסלולים לאחר העיבוד',
    regenerateGraph: 'יצירת גרף מסלולים (ניסיוני)',
    graphGenerationExperimentalNote:
      'תכונה אופציונלית וניסיונית ליצירה אוטומטית מתמונת המפה. הוספת נקודות מסלול ידנית היא שיטת העבודה המומלצת והנתמכת — בדקו בעיון את הגרף המוצע לפני האישור.',
    graphGenerating: 'מייצר...',
    clearGeneratedGraph: 'נקה גרף שנוצר אוטומטית',
    graphGenerationDone: 'יצירת גרף המסלולים הסתיימה.',
    graphGenerationFailed: 'יצירת גרף המסלולים נכשלה',
    graphClearedSummary: (points, edges) =>
      `נוקו ${points} נקודות ו-${edges} קשתות שנוצרו אוטומטית.`,

    removeGeneratedNavData: 'מחיקת נתוני ניווט שנוצרו אוטומטית',
    resetAllNavData: 'איפוס כל נתוני הניווט במפה זו',
    cleanupPreviewLoading: 'טוען תצוגה מקדימה…',
    cleanupPreviewFailed: 'טעינת תצוגת המחיקה של הנתונים שנוצרו נכשלה',
    cleanupApplyFailed: 'מחיקת נתוני הניווט שנוצרו אוטומטית נכשלה',
    cleanupApplySummary: (points, edges) =>
      `נמחקו ${points} נקודות מסלול ו-${edges} חיבורים שנוצרו אוטומטית.`,
    cleanupPreviewTitle: 'מחיקת נתוני ניווט שנוצרו אוטומטית — תצוגה מקדימה',
    cleanupGeneratedPoints: 'נקודות מסלול שנוצרו אוטומטית (יימחקו)',
    cleanupGeneratedEdges: 'חיבורים שנוצרו אוטומטית (יימחקו)',
    cleanupManualPoints: 'נקודות מסלול ידניות (יישארו)',
    cleanupManualEdges: 'חיבורים ידניים (יישארו)',
    cleanupUnknownLegacy: 'נקודות לא ודאיות/ישנות (יישארו — לא הוכח שנוצרו אוטומטית)',
    cleanupUnknownLegacyNote: 'לא הוכח שנוצרו אוטומטית, ולכן לעולם לא יימחקו בפעולה זו.',
    cleanupLinkedRooms: 'חדרים המקושרים לנקודות שנוצרו אוטומטית',
    cleanupLinkedConnectors: 'חיבורים אנכיים המקושרים לנקודות שנוצרו אוטומטית',
    cleanupDependentEdges: 'חיבורים ידניים שגם יוסרו (נוגעים בנקודה שנוצרה אוטומטית)',
    cleanupNoneToDelete: 'לא נמצאו נתונים שהוכח שנוצרו אוטומטית במפה זו — אין מה למחוק.',
    cleanupConfirmButton: 'מחק נתונים שנוצרו אוטומטית',
    cleanupApplying: 'מוחק…',

    resetPreviewFailed: 'טעינת תצוגת האיפוס המלא נכשלה',
    resetApplyFailed: 'איפוס נתוני הניווט למפה זו נכשל',
    resetApplySummary: (points, edges) =>
      `נמחקו ${points} נקודות מסלול ו-${edges} חיבורים ממפה זו.`,
    resetPreviewTitle: 'איפוס כל נתוני הניווט במפה זו — תצוגה מקדימה',
    resetWarning:
      'פעולה זו תמחק את כל נקודות המסלול והחיבורים במפה זו, כולל כאלה שנוספו ידנית. הניווט הציבורי במפה זו לא יהיה זמין עד שמנהל יוסיף נקודות מסלול חדשות ידנית. לא ניתן לבטל פעולה זו.',
    resetTotalPoints: 'סך כל נקודות המסלול במפה זו',
    resetTotalEdges: 'סך כל החיבורים במפה זו',
    resetBreakdownManual: 'ידניות',
    resetBreakdownGenerated: 'שנוצרו אוטומטית',
    resetBreakdownSemantic: 'יעדים סמנטיים',
    resetBreakdownConnector: 'תחנות חיבור אנכי',
    resetBreakdownUnknown: 'לא ודאיות/ישנות',
    resetLinkedRooms: 'חדרים מקושרים (הקישור יוסר, החדר יישאר)',
    resetLinkedConnectors: 'חיבורים אנכיים מושפעים (הנתונים יישארו)',
    resetLinkedLocationCodes: 'קודי QR/מיקום מקושרים (יושבתו)',
    resetNoneToDelete: 'למפה זו אין נקודות מסלול או חיבורים — אין מה לאפס.',
    resetConfirmInstructions: (mapName) =>
      `הקלד/י את שם המפה ("${mapName}") או את הביטוי "RESET NAVIGATION DATA" לאישור.`,
    resetConfirmPlaceholder: 'הקלד/י את שם המפה או RESET NAVIGATION DATA',
    resetConfirmButton: 'מחק לצמיתות את כל נתוני הניווט',
    resetApplying: 'מאפס…',

    upload: 'העלה מפה',
    uploading: 'מעלה...',
    uploadSuccess: 'המפה הועלתה והעיבוד התחיל אוטומטית.',
    uploadError: 'העלאת המפה נכשלה',
    requiredUploadFields: 'שם המפה והקובץ הם שדות חובה',
    editTitle: 'עריכת פרטי מפה',
    editFloorLabel: 'קומה',
    floorNotConfigured: 'הקומה אינה מוגדרת',
    saveChanges: 'שמור שינויים',
    details: {
      title: 'שם',
      campus: 'קמפוס',
      address: 'כתובת',
      description: 'תיאור',
      status: 'סטטוס',
      mapId: 'מזהה מפה',
    },
    modeSingle: 'מפת קומה בודדת',
    modeMulti: 'מפה רב-קומתית',
    modeSingleHint: 'העלי תמונה אחת כמפה אחת.',
    modeMultiHint: 'העלי כמה קומות של אותו מבנה כקבוצת מפות אחת.',
    mapGroupInfoTitle: 'פרטי קבוצת המפה',
    mapGroupName: 'שם קבוצת המפה',
    mapGroupCode: 'קוד קבוצת מפה משותף',
    mapGroupCodeHint: 'אופציונלי — השאירי ריק ליצירה אוטומטית. אותיות, ספרות ומקפים בלבד.',
    mapGroupNameRequired: 'שם קבוצת המפה נדרש (לפחות 2 תווים).',
    floorRowsInvalid: 'תקני את שורות הקומות המסומנות לפני ההעלאה.',
    mapGroupUploadSuccess: 'קבוצת המפה הועלתה בהצלחה. העיבוד התחיל לכל קומה.',
    mapGroupUploadError: 'העלאת קבוצת המפה נכשלה',
    floorMapsListTitle: 'מפות קומות',
    floorNumber: 'מספר קומה',
    floorLabel: 'תווית קומה',
    floorTitle: 'כותרת הקומה',
    floorScale: 'קנה מידה',
    floorFile: 'קובץ מפת הקומה',
    addAnotherFloor: 'הוסף קומה נוספת',
    removeFloor: 'הסר קומה',
    uploadAllFloors: 'העלה את כל הקומות',
    uploadingFloors: 'מעלה קומות...',
    groupFloorCount: (n) => `${n} קומות`,
    expandGroup: 'הצג קומות',
    collapseGroup: 'הסתר קומות',
    addFloor: 'הוסף קומה',
    editGroup: 'ערוך קבוצה',
    deleteGroup: 'מחק קבוצה',
    viewAllFloors: 'הצג את כל הקומות',
    confirmDeleteFloor: (title) => `למחוק את מפת הקומה "${title}"? קבוצת המפה לא תימחק.`,
    confirmDeleteGroup: (name) => `למחוק את קבוצת המפה "${name}" ואת כל קומותיה?`,
    floorSwitcher: 'קומה',
    ungroupedMapsTitle: 'מפות קומה בודדת',
    addFloorTitle: 'הוספת קומה',
    saveFloor: 'הוסף קומה',
    floorSwitchConfirm: 'להחליף קומה? נקודות טיוטה שלא נשמרו בקומה זו יאבדו.',
    calibrateMode: 'כיול קנה מידה',
    calibrateInstructions: 'בחר שתי נקודות במפה',
    calibratePointA: 'נקודה A',
    calibratePointB: 'נקודה B',
    calibrateDistanceTitle: 'מרחק אמיתי במטרים',
    calibrateDistancePlaceholder: 'לדוגמה: 5.5',
    calibrateDistanceInvalid: 'הזן מרחק גדול מ-0',
    calibrateNeedTwoPoints: 'לחץ תחילה על שתי נקודות במפה',
    calibrateSubmit: 'שמור כיול',
    calibrateSaving: 'שומר כיול...',
    calibrateSuccess: 'הכיול נשמר בהצלחה',
    calibrateScaleResult: (metersPerPixel) => `קנה מידה: ${metersPerPixel.toFixed(4)} מ׳/פיקסל`,
    calibrateEdgesRecalculated: (n) => `${n} קטעי מסלול חושבו מחדש`,
    calibrateEdgesSkipped: (n) => `${n} קטעים דולגו`,
    calibrateError: 'שמירת הכיול נכשלה',
    calibrateCancel: 'ביטול כיול',
    calibrateReset: 'איפוס נקודות',
    calibrateClose: 'אישור',
  },
};

const INITIAL_UPLOAD_FORM = {
  title: '',
  campus: '',
  address: '',
  description: '',
  scale: 1,
  useOpenAI: false,
  // '' = auto-create/reuse a building from campus/title (Priority 1).
  // Set to an existing building's id to attach this map to it instead.
  buildingId: '',
  floor: 0,
  // Default changed to false (navigation-data cleanup task, Section 1.3):
  // graph generation is no longer applied automatically on upload under
  // any circumstance — this flag is sent for backward API compatibility
  // but the backend now ignores it. Use the explicit "Generate Route
  // Graph" preview/confirm action after upload instead.
  autoGenerateGraph: false,
};

const INITIAL_MAP_GROUP_FORM = {
  name: '',
  code: '',
  buildingId: '',
  campus: '',
  address: '',
  description: '',
};

const BackArrow = ({ flip }) => (
  <svg
    width="15"
    height="15"
    viewBox="0 0 24 24"
    fill="none"
    style={flip ? { transform: 'scaleX(-1)' } : undefined}
  >
    <path
      d="M19 12H5M11 18l-6-6 6-6"
      stroke="currentColor"
      strokeWidth="2.2"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);

const MapIcon = () => (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
    <path
      d="M9 20L3 17V4l6 3M9 20l6-3M9 20V7M15 17l6 3V7l-6-3M15 17V4M9 7l6-3"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);

const UploadIcon = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
    <path
      d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M17 8l-5-5-5 5M12 3v12"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);

const EditIcon = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
    <path
      d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    />

    <path
      d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);

const DeleteIcon = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
    <polyline
      points="3 6 5 6 21 6"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
    />

    <path
      d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6M10 11v6M14 11v6M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);

// Where the floating map toolbox remembers its position and collapsed
// state. UI preference only — frontend storage, no backend field and no
// endpoint. Every read and write is guarded, because a browser with
// storage disabled must still get a perfectly usable toolbox.
const TOOLBOX_STORAGE_KEY = 'quickroute:mapToolbox:v1';

function readStoredToolboxState() {
  try {
    const raw = window.localStorage.getItem(TOOLBOX_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== 'object') return null;
    return parsed;
  } catch {
    return null;
  }
}

const AdminMapScreen = () => {
  const { lang, setLang } = useLang();
  const { user } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  // Part 4 — arrival from the Add/Edit Room screen's "Add / Upload New
  // Map" action: ?openUpload=1&buildingId=<id>&returnTo=/admin/rooms.
  // Recomputed from the current URL on every render (cheap parsing, no
  // extra state) so it can never go stale relative to the address bar.
  const roomReturnParams = new URLSearchParams(location.search);
  const returnToRoomPath = roomReturnParams.get('returnTo') || '';
  const openUploadRequested = roomReturnParams.get('openUpload') === '1';
  const requestedBuildingId = roomReturnParams.get('buildingId') || '';

  const isRTL =
    lang === 'ar' ||
    lang === 'he';

  const t = UI[lang] || UI.en;

  const [view, setView] = useState('detail');

  const [maps, setMaps] = useState([]);
  const [selectedMapId, setSelectedMapId] = useState('');
  const [isMapsLoading, setIsMapsLoading] = useState(false);
  const [mapsError, setMapsError] = useState('');

  const [routePoints, setRoutePoints] = useState([]);
  const [isPointsLoading, setIsPointsLoading] = useState(false);
  const [pointsError, setPointsError] = useState('');

  // RBAC/dashboard cleanup task, Phase 13 — "Edit Route Points" mode
  // state. Deliberately separate from the pre-existing 'point' (Add
  // Point) mode's clickedPoint/pointName state above: this mode never
  // creates a point from a plain click (see the mode==='edit-points'
  // branch in the canvas click handler), it only selects/edits/moves an
  // EXISTING one, so it must never share state with the create-flow.
  const [searchParams] = useSearchParams();
  const [editPointTarget, setEditPointTarget] = useState(null); // the RoutePoint currently open in the edit panel
  const [editPointMoving, setEditPointMoving] = useState(false); // true while the next map click repositions editPointTarget
  const [editPointDraftName, setEditPointDraftName] = useState('');
  const [editPointDraftType, setEditPointDraftType] = useState('');
  const [editPointSaving, setEditPointSaving] = useState(false);
  const [editPointError, setEditPointError] = useState('');
  const [editPointConfirmDelete, setEditPointConfirmDelete] = useState(false);
  const [editPointEdges, setEditPointEdges] = useState([]);
  const [editPointEdgesLoading, setEditPointEdgesLoading] = useState(false);
  const [editPointRoom, setEditPointRoom] = useState(null);
  const [editPointConnector, setEditPointConnector] = useState(null);
  // Guards against re-opening the same ?editPointId= deep link over and
  // over every time routePoints reloads (e.g. after the move/save itself
  // triggers a refresh) — only the FIRST successful open per navigation
  // acts on the URL param.
  const editPointDeepLinkHandledRef = useRef(false);

  const [routeEdges, setRouteEdges] = useState([]);
  const [isEdgesLoading, setIsEdgesLoading] = useState(false);
  const [edgesError, setEdgesError] = useState('');

  const [form, setForm] = useState({});

  const [isUploadOpen, setIsUploadOpen] = useState(false);
  const [uploadForm, setUploadForm] = useState(
    INITIAL_UPLOAD_FORM,
  );
  const [uploadFile, setUploadFile] = useState(null);
  const [uploadPreview, setUploadPreview] = useState('');
  const [uploadError, setUploadError] = useState('');
  const [isUploading, setIsUploading] = useState(false);
  const [pollingMapId, setPollingMapId] = useState('');

  // ── Multi-floor Map Groups ──────────────────────────────────────────────
  // 'single' preserves the original Upload New Map workflow above
  // completely unchanged; 'multi' shows the Map Group Information +
  // dynamic floor-row fields below it instead.
  const [uploadMode, setUploadMode] = useState('single');
  const [mapGroupForm, setMapGroupForm] = useState(INITIAL_MAP_GROUP_FORM);
  const [floorRows, setFloorRows] = useState(() => [
    createEmptyFloorRow([]),
  ]);
  const [isUploadingGroup, setIsUploadingGroup] = useState(false);
  const [groupUploadError, setGroupUploadError] = useState('');

  // Every existing map group, each carrying its own ordered floor list —
  // loaded alongside `maps` (see loadMaps below) and used both by the Map
  // Management screen's grouped list and by the full-map editor's floor
  // switcher (via the activeMap.mapGroupId match in the full-map modal).
  const [mapGroups, setMapGroups] = useState([]);
  const [isMapGroupsLoading, setIsMapGroupsLoading] = useState(false);
  const [expandedGroupIds, setExpandedGroupIds] = useState(() => new Set());
  // Which group's "Add Floor" mini-form is currently open (one at a time),
  // and that mini-form's own state — kept separate from floorRows/
  // mapGroupForm above (the initial multi-floor upload form) so opening
  // "Add Floor" on an existing group never disturbs an in-progress new
  // upload, and vice versa.
  const [addFloorGroupId, setAddFloorGroupId] = useState('');
  const [addFloorRows, setAddFloorRows] = useState([]);
  const [isAddingFloor, setIsAddingFloor] = useState(false);
  const [addFloorError, setAddFloorError] = useState('');

  const [isMapOpen, setIsMapOpen] = useState(false);
  const [fullMapMetrics, setFullMapMetrics] = useState(null);
  const [clickedPoint, setClickedPoint] = useState(null);

  // ── Floating tool panel (Add Point / Draw Walkable Path / Test Route) ──
  // A single shared position/collapsed state — only one of the three mode
  // panels is ever mounted at a time, so this naturally persists the
  // panel's position and collapsed state across mode switches within the
  // same full-map session, and resets to a fresh default each time the
  // full-map view is reopened (see the isMapOpen effect below).
  const [panelPosition, setPanelPosition] = useState(null);

  // The floating "Navigation Tools" toolbox that replaced the fixed
  // horizontal mode bar. Deliberately its OWN position/collapsed state
  // rather than sharing `panelPosition` with the Add Point / Draw / Test
  // Route panels: those are mutually exclusive and only one is mounted at
  // a time, whereas the toolbox is always on screen alongside whichever
  // of them is open, so a shared position would make the two stack.
  const [toolboxPosition, setToolboxPosition] = useState(null);
  const [toolboxCollapsed, setToolboxCollapsed] = useState(false);
  // Position / collapsed / stacking for the map panels that were
  // converted from fixed boxes into FloatingToolPanel instances. Keyed by
  // MAP_PANEL_IDS; one entry per panel, created the first time that panel
  // becomes visible. Deliberately SEPARATE from the shared
  // `panelPosition` / `isPanelCollapsed` pair below, which the five
  // already-draggable panels keep using exactly as before.
  const [mapPanels, setMapPanels] = useState({});
  const [isPanelCollapsed, setIsPanelCollapsed] = useState(false);
  const isPanelDraggingRef = useRef(false);
  // The floating panel's drag/dock/clamp boundary — the FULL editor
  // workspace (toolbar + map stage + panel + close button), not just the
  // map image. Kept entirely separate from fullMapContainerRef (the map
  // stage/image wrapper below) so widening this boundary can never affect
  // a single click-to-map-coordinate calculation, which is based solely on
  // the map image element itself.
  const fullMapWorkspaceRef = useRef(null);
  // The map stage: wraps ONLY the map image + its SVG marker/edge overlay.
  // This is the sole source of truth for RoutePoint coordinates — never
  // widen its role beyond that; see fullMapWorkspaceRef above for panel
  // positioning bounds instead.
  const fullMapContainerRef = useRef(null);
  const [pointName, setPointName] = useState('');
  const [pointType, setPointType] = useState('hallway');
  // PHASE "Final Submission" — floor is no longer independent editable
  // state. It is DERIVED from the active Map (single source of truth),
  // so a click on Floor 1's tab can never leave Add Point silently
  // pointed at floor 0. See `floor`/`drawFloor` below (both derived the
  // same way) and the reproduced-bug regression tests in
  // activeFloorSync.test.mjs.

  // ── Connect Place: link a room/store point to a building + room ───────────
  const [buildingsList, setBuildingsList] = useState([]);
  const [roomsList, setRoomsList] = useState([]);
  const [isRoomsLoading, setIsRoomsLoading] = useState(false);
  const [selectedBuildingId, setSelectedBuildingId] = useState('');
  const [selectedRoomId, setSelectedRoomId] = useState('');
  const [connectToNearest, setConnectToNearest] = useState(true);

  const isPlaceType = pointType === 'room' || pointType === 'store';

  // ── Test Route mode ─────────────────────────────────────────────────────────
  const [testStartId, setTestStartId] = useState('');
  const [testEndId, setTestEndId] = useState('');
  const [testResult, setTestResult] = useState(null);
  const [isTestLoading, setIsTestLoading] = useState(false);
  const [testError, setTestError] = useState('');

  // ── Admin map editing modes ─────────────────────────────────────────────────
  // 'point' is the original click-to-add-a-single-point behavior.
  // 'draw'  is the Draw Walkable Path workflow — nothing touches the backend
  //         until Save is pressed.
  // 'test'  is Test Route — pick two existing points and run the real
  //         Dijkstra endpoint; purely read-only, nothing is ever saved.
  const [mode, setMode] = useState('point');
  // 'connector' mode (PHASE 4/5): click the real location of a vertical
  // connector (elevator/stairs/escalator/ramp) on THIS floor's own map
  // image. VerticalConnectionsPanel owns all connector state; this screen
  // only forwards the click coordinates (never inferred/copied from
  // another floor) and refreshes its own route point/edge markers once a
  // stop is placed or removed.
  const [connectorPendingClick, setConnectorPendingClick] = useState(null);
  const [draftPoints, setDraftPoints] = useState([]);
  const [isSavingDraft, setIsSavingDraft] = useState(false);
  const [draftError, setDraftError] = useState('');
  // Draw Walkable Path's "Automatic graph merging" option:
  //   'off'        — bypass server-side dedup entirely (force_create) for
  //                  every new point; only explicitly-selected existing
  //                  markers ever get reused. Most conservative.
  //   'reuseOnly'  — (default, matches the previous/existing behavior)
  //                  server-side dedup still guards against re-creating a
  //                  point at essentially the same spot, but no automatic
  //                  connection to nearby unrelated points ever happens.
  //   'nearby'     — additionally asks the backend to auto-connect each
  //                  newly created point to safe nearby graph neighbors
  //                  (wall-aware, distance-capped) via auto_connect=nearest.
  const [mergeMode, setMergeMode] = useState('reuseOnly');

  // ── Calibrate Scale mode ─────────────────────────────────────────────────
  // 'calibrate' mode (added alongside point/draw/test/connector): the admin
  // clicks exactly two points on the CURRENT map's own image whose real
  // distance apart they know, then submits that distance to the existing
  // POST /api/maps/{id}/calibrate-scale endpoint. Both points are stored as
  // original-image pixel coordinates via computeOriginalImageCoords — the
  // same helper AdminRoomsScreen.jsx already reuses for destination
  // placement — never a second, duplicated coordinate transform. Nothing
  // here ever touches Dijkstra/RoutePoints/RouteEdges directly; the backend
  // endpoint (already implemented) does the scale math and the safe
  // walkway-edge distance recalculation.
  const [calibrationPointA, setCalibrationPointA] = useState(null);
  const [calibrationPointB, setCalibrationPointB] = useState(null);
  const [isCalibrationDistanceOpen, setIsCalibrationDistanceOpen] = useState(false);
  const [calibrationDistanceInput, setCalibrationDistanceInput] = useState('');
  const [isCalibrationSaving, setIsCalibrationSaving] = useState(false);
  const [calibrationError, setCalibrationError] = useState('');
  const [calibrationResult, setCalibrationResult] = useState(null);

  // ── Sync Rooms from Route Points (destination data flow, Section 4) ──────
  // Admin-only bulk repair for existing "room"/"store" RoutePoints that
  // predate automatic Room creation. Scoped to the currently active map's
  // building — never touches the walkable graph/routing.
  const [showSyncRoomsConfirm, setShowSyncRoomsConfirm] = useState(false);
  const [isSyncingRooms, setIsSyncingRooms] = useState(false);
  const [syncRoomsError, setSyncRoomsError] = useState('');

  // ── Delete Connection mode ──────────────────────────────────────────────
  // 'delete-connection' mode (added alongside point/draw/test/connector/
  // calibrate): the admin clicks an existing ORDINARY walkway RouteEdge —
  // never a RoutePoint — to select it, confirms in a modal, and only that
  // single RouteEdge document is deleted via the existing, already-admin-
  // protected DELETE /api/route-edges/{edge_id} endpoint (see
  // routeEdgesApi.js's deleteRouteEdge, already imported/used above for
  // Draw Walkable Path's own rollback). Both endpoint RoutePoints are never
  // touched — that endpoint only ever calls edge.delete() on the RouteEdge
  // document itself. Any edge whose edge_type isn't 'walkway', or that
  // carries a connector_id (a VerticalConnector-generated cross-floor
  // transition edge), is never selectable here — see
  // isVerticalConnectorEdge below and Vertical Connections' own management
  // UI for those instead.
  const [selectedEdgeForDeletion, setSelectedEdgeForDeletion] = useState(null); // { edge, fromPoint, toPoint }
  const [deleteConnectionVerticalNotice, setDeleteConnectionVerticalNotice] = useState(false);
  const [isDeletingConnection, setIsDeletingConnection] = useState(false);
  const [deleteConnectionError, setDeleteConnectionError] = useState('');

  // ── Auto Connect Destinations to Corridors ──────────────────────────────
  // 'auto-connect' mode: a dedicated preview-and-confirm workflow that
  // proposes (never silently creates) one same-floor walkway RouteEdge per
  // currently-unconnected Room/Store RoutePoint on the active map, using
  // the real POST /api/route-edges/auto-connect-destinations/preview and
  // .../apply endpoints. Nothing here ever calls createRouteEdge/
  // deleteRouteEdge/deleteRoutePoint directly — only the two dedicated API
  // functions below, and apply is only ever called once, with exactly the
  // admin-accepted pairs, from the confirmation step.
  const [autoConnectPhase, setAutoConnectPhase] = useState('idle'); // 'idle' | 'scanning' | 'preview' | 'confirming' | 'applying' | 'result'
  const [autoConnectScope, setAutoConnectScope] = useState('map'); // 'map' | 'map_group'
  const [autoConnectSummary, setAutoConnectSummary] = useState(null);
  // Each entry is the preview proposal plus purely local/frontend review
  // state (localStatus, selectedCandidateKey) — the backend is never asked
  // to remember review state between preview and apply.
  const [autoConnectProposals, setAutoConnectProposals] = useState([]);
  const [autoConnectError, setAutoConnectError] = useState('');
  // Destination point id currently awaiting a manually-clicked corridor
  // point on the map (Section 8: "click a different corridor point
  // manually"), or null when not in that sub-interaction.
  const [autoConnectManualPickTargetId, setAutoConnectManualPickTargetId] = useState(null);
  const [autoConnectApplyResult, setAutoConnectApplyResult] = useState(null);

  // "Create Destinations from Approved Analysis" — Stage 1 of the
  // Approved Semantic Analysis -> Automatic Destinations workflow. Same
  // preview/review/confirm/result phase pattern as Auto Connect
  // Destinations above (Section 6/18 of that spec explicitly reuses this
  // screen's established conventions).
  const [semanticDestPhase, setSemanticDestPhase] = useState('idle'); // 'idle' | 'scanning' | 'preview' | 'confirming' | 'applying' | 'result'
  const [semanticDestSummary, setSemanticDestSummary] = useState(null);
  const [semanticDestPublicationId, setSemanticDestPublicationId] = useState(null);
  // Each entry is the preview proposal plus purely local review state
  // (localStatus, x, y, confirmNested, allowTransitThrough) — nothing is
  // ever written to MongoDB until Apply.
  const [semanticDestProposals, setSemanticDestProposals] = useState([]);
  const [semanticDestError, setSemanticDestError] = useState('');
  // semantic_item_id currently awaiting a manually-clicked map location
  // for its new destination point (Section 5: no AI door/centroid data
  // exists — a genuinely new point can only ever be manually placed).
  const [semanticDestManualPlaceTargetId, setSemanticDestManualPlaceTargetId] = useState(null);
  const [semanticDestApplyResult, setSemanticDestApplyResult] = useState(null);

  // Automatic Navigation Build (Phase A) — a READ-ONLY proposal for the
  // whole floor: the detected building region, a hidden transit graph
  // derived from the drawing, room arrival points, and which rooms could
  // not be resolved. Nothing here is ever saved; there is no apply
  // endpoint yet by design.
  const [navBuildResult, setNavBuildResult] = useState(null);
  const [navBuildLoading, setNavBuildLoading] = useState(false);
  const [navBuildError, setNavBuildError] = useState('');
  const [navBuildOpen, setNavBuildOpen] = useState(false);
  const [navBuildLayers, setNavBuildLayers] = useState({
    region: true,
    rejected: false,
    graph: true,
    arrivals: true,
    attachments: true,
    rejectedEdges: false,
  });

  // The server's automatic-placement preview for the SAME publication —
  // a location suggested for each accepted room from the labels PRINTED
  // on this map, already checked against the wall mask and line of sight
  // (backend/services/destination_auto_placement_service.py). Read-only
  // on the server side; here it only ever pre-fills the batch queue, and
  // every suggestion stays movable and rejectable like any manual one.
  // Null means the preview was never run or could not be reached — in
  // which case the batch queue behaves exactly as it did before this
  // feature existed.
  const [semanticAutoPlacement, setSemanticAutoPlacement] = useState(null);

  // Fast batch destination placement ("Place All Destinations") — a
  // DISTINCT sub-workflow layered on top of the proposals array above.
  // Entering batch mode treats every needs-manual-placement proposal as
  // an ordered queue walked one item at a time, advancing automatically
  // after each map click, with exactly one final "Save All Destinations"
  // confirmation — never a per-item Accept/OK click. The existing
  // per-card preview panel above is left fully intact (still reachable,
  // still works exactly as before) for an admin who prefers it.
  const [semanticBatchActive, setSemanticBatchActive] = useState(false);
  const [semanticBatchQueue, setSemanticBatchQueue] = useState([]); // ordered semantic_item_id[]
  const [semanticBatchIndex, setSemanticBatchIndex] = useState(0);
  const [semanticBatchStatuses, setSemanticBatchStatuses] = useState({}); // id -> 'pending'|'skipped'|'placed'|'rejected'
  // Undo stack: each entry restores exactly one prior PLACEMENT (never
  // skip/reject — matches the "Undo last placement" control's own name).
  const [semanticBatchHistory, setSemanticBatchHistory] = useState([]);
  const [semanticBatchFeedback, setSemanticBatchFeedback] = useState('');
  // True only right after the admin explicitly clicks "Change location"
  // for the active item — otherwise a map click while revisiting an
  // already-'placed' item (e.g. after Previous) is ignored rather than
  // silently overwriting it.
  const [semanticBatchAwaitingReplace, setSemanticBatchAwaitingReplace] = useState(false);
  const [semanticBatchReviewOpen, setSemanticBatchReviewOpen] = useState(false);
  const [semanticBatchConfirmOpen, setSemanticBatchConfirmOpen] = useState(false);
  const [semanticBatchExitWarningOpen, setSemanticBatchExitWarningOpen] = useState(false);
  const [semanticBatchSaving, setSemanticBatchSaving] = useState(false);
  const [semanticBatchSaveError, setSemanticBatchSaveError] = useState('');
  const [semanticBatchItemErrors, setSemanticBatchItemErrors] = useState({});
  // Draft-recovery prompt (Section 9): non-null only when a previously
  // saved, unfinished batch draft was found in localStorage for this
  // exact map + publication + admin combination.
  const [semanticBatchDraftPrompt, setSemanticBatchDraftPrompt] = useState(null);

  const fullMapImageRef = useRef(null);

  const activeMap = useMemo(
    () =>
      maps.find(
        (map) => map.id === selectedMapId,
      ) || null,
    [maps, selectedMapId],
  );

  // ── Canonical active-floor context ──────────────────────────────────────
  // Single source of truth for "which floor is the admin currently working
  // on", derived entirely from the selected Map (never independent state).
  // A previous fix made this read-only, driven only by a floor-tab strip
  // elsewhere on the screen — that regressed in real use because the tab
  // strip is not reliably visible from inside the tool panels (floating
  // panel overlap / no tabs for a legacy standalone map), leaving the
  // admin stuck with no way to reach Floor 1. The floor is a real,
  // always-editable <select> now (see `floorSelectOptions` /
  // `renderFloorSelect` below and `handleFloorSwitch` above) — choosing an
  // option is the ONLY thing that changes `selectedMapId`, which is what
  // `activeMap`/`activeFloor` derive from, so the selected floor and
  // selected map can never disagree, and every tool (Add Point, Draw
  // Walkable Path, Test Route, Vertical Connections) reads the exact same
  // value. See utils/mapGroupHelpers.js's `buildFloorOptions` /
  // `resolveFloorSwitch` and utils/activeFloorSync.test.mjs for the
  // pure-function regression tests.
  // NEVER `?? 0` here — activeMap.floor is already a proper number-or-null
  // (mapsApi.js's normalizeMap explicitly preserves floor 0 vs. genuinely
  // unknown). Coercing a genuinely-unknown floor to 0 was the actual root
  // cause of the "existing Floor 1 point rejected" bug: it silently made
  // every legacy/ungrouped Map look like Ground Floor, so any real Floor 1
  // point failed the floor-match check below even though it was clicked
  // directly on its own correct map. `resolveExistingPointSelection` (and
  // findNearestPointWithinThreshold) already treat a null floor as "skip
  // the floor check, trust the map id instead" — see drawPathHelpers.js.
  const activeFloor = activeMap ? activeMap.floor : null;
  const activeMapGroupId = activeMap?.mapGroupId ?? null;
  const activeBuildingId = activeMap?.buildingId ?? null;

  // `floor` (Add Point) and `drawFloor` (Draw Walkable Path) are plain
  // derived aliases of activeFloor — never independent state — so there is
  // no way for either to disagree with the floor the admin has selected in
  // the dropdown.
  const floor = activeFloor;
  const drawFloor = activeFloor;

  const adminMapImageUrl =
    activeMap?.sourceImageUrl ||
    activeMap?.imageUrl ||
    activeMap?.displayImageUrl;

  const isProcessing = [
    'pending',
    'processing',
  ].includes(activeMap?.processingStatus);

  const loadMaps = useCallback(
    async (preferredMapId = '') => {
      setIsMapsLoading(true);
      setMapsError('');

      try {
        const normalizedMaps = await getMaps();

        setMaps(normalizedMaps);

        setSelectedMapId((previousId) => {
          if (
            preferredMapId &&
            normalizedMaps.some(
              (map) => map.id === preferredMapId,
            )
          ) {
            return preferredMapId;
          }

          if (
            previousId &&
            normalizedMaps.some(
              (map) => map.id === previousId,
            )
          ) {
            return previousId;
          }

          const currentMap = normalizedMaps.find(
            (map) => map.isCurrent,
          );

          return (
            currentMap?.id ||
            normalizedMaps[0]?.id ||
            ''
          );
        });
      } catch (error) {
        console.error(
          'Failed to load maps:',
          error,
        );

        setMapsError(t.mapsError);
      } finally {
        setIsMapsLoading(false);
      }
    },
    [t.mapsError],
  );

  const loadMapGroups = useCallback(async () => {
    setIsMapGroupsLoading(true);

    try {
      const groups = await getMapGroups();
      setMapGroups(groups);
    } catch (error) {
      console.error('Failed to load map groups:', error);
    } finally {
      setIsMapGroupsLoading(false);
    }
  }, []);

  useEffect(() => {
    // RBAC/dashboard cleanup task, Phase 5/13 — role-aware login redirect
    // (building_manager with exactly one assigned map) and "Open on Map"
    // deep links (Section 7 / Section 6's per-point "Open on Map" action)
    // both land here as ?mapId=<id>. loadMaps() already prefers an
    // explicit preferredMapId over its own is_current/first-map fallback,
    // so passing it through is enough to make the deep link work with no
    // change to the fallback logic itself.
    loadMaps(searchParams.get('mapId') || '');
    loadMapGroups();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loadMaps, loadMapGroups]);

  // Buildings list for the room/store connect-place picker. Loaded once —
  // buildings don't change often enough to warrant reloading per map.
  useEffect(() => {
    const loadBuildingsList = async () => {
      try {
        const data = await getBuildings();
        setBuildingsList(Array.isArray(data) ? data : []);
      } catch (error) {
        console.error('Failed to load buildings for Connect Place:', error);
        setBuildingsList([]);
      }
    };

    loadBuildingsList();
  }, []);

  // Rooms for whichever building is currently selected in the Add Point
  // form's room/store fields.
  useEffect(() => {
    if (!selectedBuildingId) {
      setRoomsList([]);
      return undefined;
    }

    let cancelled = false;

    const loadRoomsForBuilding = async () => {
      setIsRoomsLoading(true);

      try {
        const data = await getRooms({ building_id: selectedBuildingId });
        if (!cancelled) {
          setRoomsList(Array.isArray(data) ? data : []);
        }
      } catch (error) {
        console.error('Failed to load rooms for Connect Place:', error);
        if (!cancelled) setRoomsList([]);
      } finally {
        if (!cancelled) setIsRoomsLoading(false);
      }
    };

    loadRoomsForBuilding();

    return () => {
      cancelled = true;
    };
  }, [selectedBuildingId]);

  // Reusable loader for a single map's RoutePoints + RouteEdges. Used both
  // by the "selected map changed" effect below and after a successful
  // Draw Walkable Path save (to pull in the freshly created graph data).
  const refreshRouteGraph = useCallback(
    async (mapId) => {
      if (!mapId) {
        setRoutePoints([]);
        setRouteEdges([]);
        return;
      }

      setIsPointsLoading(true);
      setIsEdgesLoading(true);
      setPointsError('');
      setEdgesError('');

      const [pointsResult, edgesResult] = await Promise.allSettled([
        getRoutePoints({ map_id: mapId }),
        getRouteEdges({ map_id: mapId }),
      ]);

      if (pointsResult.status === 'fulfilled') {
        setRoutePoints(
          Array.isArray(pointsResult.value) ? pointsResult.value : [],
        );
      } else {
        console.error(
          'Failed to load route points:',
          pointsResult.reason,
        );

        setRoutePoints([]);
        setPointsError(t.pointsError);
      }

      if (edgesResult.status === 'fulfilled') {
        setRouteEdges(
          Array.isArray(edgesResult.value) ? edgesResult.value : [],
        );
      } else {
        console.error(
          'Failed to load route edges:',
          edgesResult.reason,
        );

        setRouteEdges([]);
        setEdgesError(t.edgesError);
      }

      setIsPointsLoading(false);
      setIsEdgesLoading(false);
    },
    [t.pointsError, t.edgesError],
  );

  // ── Edit Route Points mode handlers (RBAC/dashboard cleanup task, Phase
  // 13) ────────────────────────────────────────────────────────────────
  // Opens the detail panel for an EXISTING point — never creates one.
  // Also fires the "inspect connected edges / linked Room / linked
  // vertical connector" lookups so the panel has real data as soon as it
  // opens rather than a second explicit step.
  const openEditPointPanel = useCallback((point) => {
    if (!point) return;

    setEditPointTarget(point);
    setEditPointDraftName(point.name || '');
    setEditPointDraftType(point.point_type || '');
    setEditPointMoving(false);
    setEditPointError('');
    setEditPointConfirmDelete(false);
    setEditPointRoom(null);
    setEditPointConnector(null);
    setEditPointEdges([]);

    const pointId = point.id;

    setEditPointEdgesLoading(true);
    getRouteEdges({ map_id: point.map_id })
      .then((edges) => {
        const connected = (Array.isArray(edges) ? edges : []).filter(
          (edge) =>
            edge.from_point_id === pointId || edge.to_point_id === pointId,
        );
        setEditPointEdges(connected);
      })
      .catch((error) => {
        console.error('Failed to load connected edges for edit panel:', error);
        setEditPointEdges([]);
      })
      .finally(() => setEditPointEdgesLoading(false));

    if (point.room_id) {
      getRoomById(point.room_id)
        .then((room) => setEditPointRoom(room))
        .catch((error) => {
          console.error('Failed to load linked room for edit panel:', error);
          setEditPointRoom(null);
        });
    }

    if (point.connector_id) {
      getVerticalConnectorById(point.connector_id)
        .then((connector) => setEditPointConnector(connector))
        .catch((error) => {
          console.error(
            'Failed to load linked vertical connector for edit panel:',
            error,
          );
          setEditPointConnector(null);
        });
    }
  }, []);

  const closeEditPointPanel = useCallback(() => {
    setEditPointTarget(null);
    setEditPointMoving(false);
    setEditPointError('');
    setEditPointConfirmDelete(false);
    setEditPointEdges([]);
    setEditPointRoom(null);
    setEditPointConnector(null);
  }, []);

  // Selecting an existing marker while 'edit-points' mode is active — the
  // ONLY way this mode ever targets a point; a plain background click
  // (handled in the main canvas click handler) is always a no-op here so
  // normal map clicks can never accidentally create or move anything.
  const selectPointForEditing = useCallback(
    (point, event) => {
      if (event) event.stopPropagation();
      openEditPointPanel(point);
    },
    [openEditPointPanel],
  );

  // Persists a Move Point repositioning — called only from the main
  // canvas click handler's mode==='edit-points' branch, and only while
  // editPointMoving is true (an explicit toggle the admin must turn on
  // first). Bounds are validated against the map's own natural image
  // size before ever calling the backend, so a mis-click just outside the
  // rendered image can never silently save an out-of-bounds coordinate.
  const handleEditPointMoveTo = useCallback(
    async (x, y) => {
      if (!editPointTarget) return;

      const naturalWidth = fullMapMetrics?.naturalWidth;
      const naturalHeight = fullMapMetrics?.naturalHeight;

      if (
        Number.isFinite(naturalWidth) &&
        Number.isFinite(naturalHeight) &&
        (x < 0 || y < 0 || x > naturalWidth || y > naturalHeight)
      ) {
        setEditPointError(t.editPointsOutOfBounds || 'Point is outside the map image.');
        return;
      }

      setEditPointSaving(true);
      setEditPointError('');

      try {
        const updated = await updateRoutePoint(editPointTarget.id, { x, y });
        setEditPointTarget(updated);
        setEditPointMoving(false);
        await refreshRouteGraph(selectedMapId);
      } catch (error) {
        console.error('Failed to move route point:', error);
        setEditPointError(error?.message || t.editPointsSaveError || 'Failed to move point.');
      } finally {
        setEditPointSaving(false);
      }
    },
    [editPointTarget, fullMapMetrics, refreshRouteGraph, selectedMapId, t],
  );

  const handleEditPointSaveDetails = useCallback(async () => {
    if (!editPointTarget) return;

    const trimmedName = (editPointDraftName || '').trim();
    if (trimmedName.length < 2) {
      setEditPointError(t.editPointsNameTooShort || 'Name is too short.');
      return;
    }

    setEditPointSaving(true);
    setEditPointError('');

    try {
      const updated = await updateRoutePoint(editPointTarget.id, {
        name: trimmedName,
        point_type: editPointDraftType || null,
      });
      setEditPointTarget(updated);
      await refreshRouteGraph(selectedMapId);
    } catch (error) {
      console.error('Failed to save route point details:', error);
      setEditPointError(error?.message || t.editPointsSaveError || 'Failed to save changes.');
    } finally {
      setEditPointSaving(false);
    }
  }, [editPointTarget, editPointDraftName, editPointDraftType, refreshRouteGraph, selectedMapId, t]);

  const handleEditPointDelete = useCallback(async () => {
    if (!editPointTarget) return;

    setEditPointSaving(true);
    setEditPointError('');

    try {
      await deleteRoutePoint(editPointTarget.id);
      closeEditPointPanel();
      await refreshRouteGraph(selectedMapId);
    } catch (error) {
      console.error('Failed to delete route point:', error);
      // The backend already blocks deletion with a clear 409 when this
      // point still has connected edges or a linked location code — that
      // message is surfaced verbatim rather than a generic fallback, and
      // the panel/selection is deliberately kept open (never silently
      // closed) so the admin can act on it (e.g. delete the edges first).
      setEditPointError(error?.message || t.editPointsDeleteError || 'Failed to delete point.');
      setEditPointConfirmDelete(false);
    } finally {
      setEditPointSaving(false);
    }
  }, [editPointTarget, closeEditPointPanel, refreshRouteGraph, selectedMapId, t]);

  useEffect(() => {
    let cancelled = false;

    // Switching maps must never leave the previous map's graph on screen,
    // even for a moment — clear points, edges, and any in-progress overlay
    // state before fetching the newly selected map's data. This includes
    // any Draw Walkable Path draft: it is never carried over to another
    // map, and switching away discards it with zero API calls.
    setClickedPoint(null);
    setPointName('');
    setPointType('hallway');
    // `floor`/`drawFloor` are derived from activeMap now — no reset needed.
    setFullMapMetrics(null);
    setMode('point');
    setDraftPoints([]);
    setDraftError('');
    setIsSavingDraft(false);
    setSelectedBuildingId('');
    setSelectedRoomId('');
    setTestStartId('');
    setTestEndId('');
    setTestResult(null);
    setTestError('');
    setIsTestLoading(false);

    if (!cancelled) {
      refreshRouteGraph(selectedMapId);
    }

    return () => {
      cancelled = true;
    };
  }, [selectedMapId, refreshRouteGraph]);

  // RBAC/dashboard cleanup task, Phase 13 — "Open on Map" deep link:
  // ?editPointId=<id> (paired with ?mapId=<id> above so the right map is
  // already selected). Runs after routePoints for the selected map have
  // actually loaded, and deliberately AFTER the map-switch effect above
  // (which resets mode to 'point' on every selectedMapId change) — this
  // is what lets it win instead of being immediately reset back to
  // 'point'. Fires at most once per page load (editPointDeepLinkHandledRef)
  // so it never re-triggers itself from the routePoints refresh a
  // save/move/delete inside the panel itself causes.
  useEffect(() => {
    if (editPointDeepLinkHandledRef.current) return;
    const targetId = searchParams.get('editPointId');
    if (!targetId) return;
    if (!Array.isArray(routePoints) || routePoints.length === 0) return;

    const target = routePoints.find((p) => p.id === targetId);
    if (!target) return;

    editPointDeepLinkHandledRef.current = true;
    setMode('edit-points');
    openEditPointPanel(target);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [routePoints, searchParams]);

  useEffect(() => {
    if (!pollingMapId) return undefined;

    let cancelled = false;
    let timerId;

    const checkStatus = async () => {
      try {
        const statusData = await getMapProcessingStatus(pollingMapId);

        if (cancelled) return;

        setMaps((previousMaps) =>
          previousMaps.map((map) =>
            map.id === pollingMapId
              ? normalizeMap({
                  ...map,
                  processing_status:
                    statusData.processing_status,
                  processing_progress:
                    statusData.processing_progress,
                  processing_error:
                    statusData.processing_error,
                  generation_method:
                    statusData.generation_method,
                  source_image_url:
                    statusData.source_image_url ??
                    map.sourceImageUrl,
                  display_image_url:
                    statusData.display_image_url ??
                    map.displayImageUrl,
                })
              : map,
          ),
        );

        if (
          statusData.processing_status ===
          'completed'
        ) {
          await loadMaps(pollingMapId);
          setPollingMapId('');
          return;
        }

        if (
          statusData.processing_status ===
          'failed'
        ) {
          setPollingMapId('');
          return;
        }

        timerId = window.setTimeout(
          checkStatus,
          1200,
        );
      } catch (error) {
        console.error(
          'Failed to check map processing status:',
          error,
        );

        timerId = window.setTimeout(
          checkStatus,
          2000,
        );
      }
    };

    checkStatus();

    return () => {
      cancelled = true;

      if (timerId) {
        window.clearTimeout(timerId);
      }
    };
  }, [
    loadMaps,
    pollingMapId,
  ]);

  useEffect(() => {
    return () => {
      if (uploadPreview) {
        URL.revokeObjectURL(uploadPreview);
      }
    };
  }, [uploadPreview]);

  const syncFullMapMetrics = () => {
    const image = fullMapImageRef.current;

    if (
      !image?.naturalWidth ||
      !image?.naturalHeight
    ) {
      return;
    }

    const rect = image.getBoundingClientRect();

    setFullMapMetrics({
      displayWidth: rect.width,
      displayHeight: rect.height,
      naturalWidth: image.naturalWidth,
      naturalHeight: image.naturalHeight,
    });

    // First time the container becomes measurable in this full-map
    // session, give the tool panel a sensible starting position (near the
    // top, on the leading side for the current language direction) —
    // requirement 8: reset to a default position each time the full-map
    // view is opened. Only runs once per open because panelPosition is
    // non-null after this; it is reset back to null when the modal closes
    // (see the isMapOpen effect below). Never overrides a position the
    // admin has already dragged the panel to.
    setPanelPosition((previous) => {
      if (previous) return previous;

      // Default position is computed against the WORKSPACE, not the map
      // stage — on a portrait map this is what places the panel in the
      // real, usable gutter beside the image instead of on top of it.
      const workspaceRect =
        fullMapWorkspaceRef.current?.getBoundingClientRect() || rect;

      return computeDefaultPanelPosition({
        containerWidth: workspaceRect.width,
        containerHeight: workspaceRect.height,
        panelWidth: 300,
        panelHeight: 320,
        isRTL,
      });
    });

    // The toolbox docks to the far side by default, so the top-left of
    // the map stays clear for the floor selector and the plan itself is
    // the dominant thing on screen. A position the admin has dragged to
    // (restored from localStorage below) always wins.
    setToolboxPosition((previous) => {
      if (previous) return previous;

      const workspaceRect =
        fullMapWorkspaceRef.current?.getBoundingClientRect() || rect;

      const stored = readStoredToolboxState();

      if (stored && stored.position) {
        return clampPanelPosition({
          x: stored.position.x,
          y: stored.position.y,
          panelWidth: TOOLBOX_WIDTH,
          panelHeight: 360,
          containerWidth: workspaceRect.width,
          containerHeight: workspaceRect.height,
        });
      }

      return computeSnapPosition({
        side: isRTL ? 'left' : 'right',
        panelWidth: TOOLBOX_WIDTH,
        panelHeight: 360,
        containerWidth: workspaceRect.width,
        containerHeight: workspaceRect.height,
      });
    });
  };

  useEffect(() => {
    if (!isMapOpen) return undefined;

    const handleResize = () => {
      syncFullMapMetrics();
    };

    window.addEventListener(
      'resize',
      handleResize,
    );

    return () => {
      window.removeEventListener(
        'resize',
        handleResize,
      );
    };
  }, [isMapOpen]);

  // Reset the panel back to a fresh default position/collapsed state each
  // time the full-map view is closed, so reopening it later doesn't start
  // from wherever it happened to be left last time (requirement 8).
  useEffect(() => {
    if (!isMapOpen) {
      setPanelPosition(null);
      setIsPanelCollapsed(false);
      isPanelDraggingRef.current = false;
    }
  }, [isMapOpen]);

  const setFormField = (key, value) => {
    setForm((previousForm) => ({
      ...previousForm,
      [key]: value,
    }));
  };

  const setUploadField = (key, value) => {
    setUploadForm((previousForm) => ({
      ...previousForm,
      [key]: value,
    }));
  };

  const handleMapSelection = async (mapId) => {
    setSelectedMapId(mapId);
    setView('detail');
    setIsMapOpen(false);

    if (!mapId) return;

    try {
      const selectedMap = await apiUpdateMap(mapId, {
        is_current: true,
      });

      setMaps((previousMaps) =>
        previousMaps.map((map) =>
          map.id === selectedMap.id
            ? selectedMap
            : {
                ...map,
                isCurrent: false,
              },
        ),
      );
    } catch (error) {
      console.error(
        'Failed to make map current:',
        error,
      );
    }
  };

  // Floor switcher (full-map editor, multi-floor groups only). Deliberately
  // does NOT reuse handleMapSelection above: that function calls
  // apiUpdateMap(..., { is_current: true }), which flips the LEGACY
  // collection-wide `is_current` singleton flag and would incorrectly
  // clear it on every other map in the system (including unrelated
  // buildings) on every floor switch. Floor maps use `is_current_for_floor`
  // instead, which the backend already sets correctly at creation time —
  // switching floors here never needs to touch either flag. Also, unlike
  // handleMapSelection, this must keep the full-map modal OPEN and must
  // never merge/carry over the previous floor's draft points onto the new
  // floor's image.
  const handleFloorSwitch = (mapId) => {
    const decision = resolveFloorSwitch({
      targetMapId: mapId,
      currentMapId: selectedMapId,
      hasDraft: draftPoints.length > 0,
      confirmFn: () => window.confirm(t.floorSwitchConfirm),
    });

    if (!decision.proceed) return;

    if (decision.clearDraft) {
      setDraftPoints([]);
      setDraftError('');
    }
    setClickedPoint(null);
    setTestStartId('');
    setTestEndId('');
    setTestResult(null);
    setTestError('');
    setSelectedMapId(decision.nextMapId);
  };

  const openEdit = () => {
    if (!activeMap) return;

    setForm({
      title: activeMap.title || '',
      campus: activeMap.campus || '',
      address: activeMap.address || '',
      description: activeMap.description || '',
      // The real backend Map.floor — a number (0 preserved as a real
      // Ground Floor value, never coerced) or null when genuinely
      // unconfigured. Never derived from the title; the admin sees and
      // edits the actual stored value.
      floor: activeMap.floor,
    });

    setView('edit');
  };

  const saveMapDetails = async () => {
    if (!activeMap?.id) return;

    const payload = {
      title: String(form.title || '').trim(),
      campus:
        String(form.campus || '').trim() ||
        null,
      address:
        String(form.address || '').trim() ||
        null,
      description:
        String(form.description || '').trim() ||
        null,
      // Always sent explicitly (including null) — the Floor field is a
      // real, always-visible control now, so whatever it currently shows
      // is exactly what gets persisted, never silently skipped. The
      // backend (routes/map_routes.py's update_map) is the source of
      // truth for validation (sibling-floor collisions, cascading the
      // new floor onto this map's own RoutePoints/Rooms) and for
      // preserving 0 correctly.
      floor: form.floor === '' ? null : form.floor,
    };

    try {
      const updatedMap = await apiUpdateMap(activeMap.id, payload);

      // "reload the updated Map / refresh map options and activeMap" —
      // apiUpdateMap's response IS the freshly persisted Map (the backend
      // returns map_to_response(map_item) right after .save()), so
      // patching it into `maps` here already reloads everything that
      // derives from it: `activeMap` (useMemo on maps/selectedMapId),
      // `floorSelectOptions`/`activeMapGroupFloors` (useMemo on
      // activeMap/maps), and `editFloorOptions` below — no separate
      // re-fetch needed. This never touches the map image, RoutePoints,
      // RouteEdges, Rooms, or connectors — only the Map document's own
      // fields.
      setMaps((previousMaps) =>
        previousMaps.map((map) =>
          map.id === updatedMap.id
            ? updatedMap
            : map,
        ),
      );

      setView('detail');
    } catch (error) {
      console.error(
        'Failed to update map:',
        error,
      );

      alert(error.message || 'Failed to update map');
    }
  };

  const deleteMap = async () => {
    if (!activeMap?.id) return;

    try {
      await apiDeleteMap(activeMap.id);

      setRoutePoints([]);
      setRouteEdges([]);
      setClickedPoint(null);
      setIsMapOpen(false);
      setView('detail');
      setSelectedMapId('');

      await loadMaps();
    } catch (error) {
      console.error(
        'Failed to delete map:',
        error,
      );

      alert('Failed to delete map');
    }
  };

  const [isGeneratingGraph, setIsGeneratingGraph] = useState(false);

  // "Generate Route Graph" is now an explicit preview -> confirm -> apply
  // workflow (navigation-data cleanup task, Section 1.3): nothing is
  // written until the admin has seen the proposed node/edge counts and
  // explicitly confirmed. Preview never touches MongoDB.
  const handleGenerateGraph = async () => {
    if (!activeMap?.id) return;

    setIsGeneratingGraph(true);

    try {
      const preview = await previewMapGraph(activeMap.id);

      if (!preview.meets_confidence_threshold) {
        alert(
          preview.note ||
            t.graphGenerationLowConfidence ||
            t.graphGenerationFailed,
        );
        return;
      }

      const confirmed = window.confirm(
        (t.graphGenerationConfirmPrompt
          ? t.graphGenerationConfirmPrompt(
              preview.nodes.length,
              preview.edges.length,
            )
          : `Generate ${preview.nodes.length} point(s) and ${preview.edges.length} connection(s) for this map? Review carefully before confirming — nothing is saved until you confirm.`),
      );

      if (!confirmed) return;

      const updatedMap = await generateMapGraph(activeMap.id, { confirm: true });
      await Promise.all([loadMaps(), refreshRouteGraph(activeMap.id)]);
      alert(
        updatedMap.graphGenerationNote ||
          t.graphGenerationDone,
      );
    } catch (error) {
      console.error('Failed to generate walkable graph:', error);
      alert(error.message || t.graphGenerationFailed);
    } finally {
      setIsGeneratingGraph(false);
    }
  };

  const handleClearGeneratedGraph = async () => {
    if (!activeMap?.id) return;

    try {
      const summary = await clearGeneratedMapGraph(activeMap.id);
      await Promise.all([loadMaps(), refreshRouteGraph(activeMap.id)]);
      alert(
        t.graphClearedSummary(
          summary.points_cleared,
          summary.edges_cleared,
        ),
      );
    } catch (error) {
      console.error('Failed to clear generated graph:', error);
      alert(error.message || t.graphGenerationFailed);
    }
  };

  // ── Navigation-data-problem task, Part 3A/3B — Generated-only cleanup
  //    + Full Navigation Reset for the active map. Both are strictly
  //    preview -> explicit confirm -> apply; neither ever runs from a
  //    plain click. ──────────────────────────────────────────────────────

  const [cleanupPreview, setCleanupPreview] = useState(null);
  const [isCleanupPreviewLoading, setIsCleanupPreviewLoading] = useState(false);
  const [isCleanupApplying, setIsCleanupApplying] = useState(false);
  const [cleanupError, setCleanupError] = useState('');

  const handleOpenGeneratedCleanup = async () => {
    if (!activeMap?.id) return;
    setIsCleanupPreviewLoading(true);
    setCleanupError('');
    try {
      const preview = await previewGeneratedGraphCleanup(activeMap.id);
      setCleanupPreview(preview);
    } catch (error) {
      console.error('Failed to preview generated navigation cleanup:', error);
      alert(error.message || t.cleanupPreviewFailed);
    } finally {
      setIsCleanupPreviewLoading(false);
    }
  };

  const handleCloseGeneratedCleanup = () => {
    setCleanupPreview(null);
    setCleanupError('');
  };

  const handleApplyGeneratedCleanup = async () => {
    if (!activeMap?.id) return;
    setIsCleanupApplying(true);
    setCleanupError('');
    try {
      const result = await applyGeneratedGraphCleanup(activeMap.id, { confirm: true });
      await Promise.all([loadMaps(), refreshRouteGraph(activeMap.id)]);
      setCleanupPreview(null);
      alert(t.cleanupApplySummary(result.points_deleted, result.edges_deleted));
    } catch (error) {
      console.error('Failed to apply generated navigation cleanup:', error);
      setCleanupError(error.message || t.cleanupApplyFailed);
    } finally {
      setIsCleanupApplying(false);
    }
  };

  const [resetPreview, setResetPreview] = useState(null);
  const [isResetPreviewLoading, setIsResetPreviewLoading] = useState(false);
  const [isResetApplying, setIsResetApplying] = useState(false);
  const [resetConfirmText, setResetConfirmText] = useState('');
  const [resetError, setResetError] = useState('');

  const handleOpenFullReset = async () => {
    if (!activeMap?.id) return;
    setIsResetPreviewLoading(true);
    setResetError('');
    try {
      const preview = await previewFullMapReset(activeMap.id);
      setResetPreview(preview);
      setResetConfirmText('');
    } catch (error) {
      console.error('Failed to preview full navigation reset:', error);
      alert(error.message || t.resetPreviewFailed);
    } finally {
      setIsResetPreviewLoading(false);
    }
  };

  const handleCloseFullReset = () => {
    setResetPreview(null);
    setResetConfirmText('');
    setResetError('');
  };

  const handleApplyFullReset = async () => {
    if (!activeMap?.id || !resetPreview) return;
    setIsResetApplying(true);
    setResetError('');
    try {
      const result = await applyFullMapReset(activeMap.id, {
        confirm: true,
        confirmationText: resetConfirmText,
      });
      await Promise.all([loadMaps(), refreshRouteGraph(activeMap.id)]);
      setResetPreview(null);
      setResetConfirmText('');
      alert(t.resetApplySummary(result.points_deleted, result.edges_deleted));
    } catch (error) {
      console.error('Failed to apply full navigation reset:', error);
      setResetError(error.message || t.resetApplyFailed);
    } finally {
      setIsResetApplying(false);
    }
  };

  const [isRepairingFloors, setIsRepairingFloors] = useState(false);

  // Admin UI action for POST /api/route-points/backfill-floor-from-map —
  // the RouteEdge "different floor" rejection reported for Sakara /
  // legacy corridor points is a data-consistency problem (some
  // RoutePoints still carry a null/stale `floor` that disagrees with
  // their own Map), not a drawing bug, so this is a global, map-agnostic
  // repair across every RoutePoint, not scoped to `activeMap`. Always
  // dry-runs first (never writes on the first call), shows the admin
  // exactly how many points would change, requires an explicit
  // confirmation, only then applies, and refreshes the currently open
  // map's points/edges afterward so any newly-fixed point becomes
  // immediately reusable without a manual page reload.
  const handleRepairRoutePointFloors = async () => {
    setIsRepairingFloors(true);

    try {
      const preview = await backfillRoutePointFloorFromMap(true);

      if (preview.points_needing_update === 0) {
        alert(t.repairFloorsNoneNeeded);
        return;
      }

      const confirmed = window.confirm(
        t.repairFloorsConfirm(preview.points_needing_update),
      );

      if (!confirmed) return;

      const applied = await backfillRoutePointFloorFromMap(false);

      alert(t.repairFloorsDone(applied.points_updated));

      await Promise.all([
        loadMaps(),
        selectedMapId
          ? refreshRouteGraph(selectedMapId)
          : Promise.resolve(),
      ]);
    } catch (error) {
      console.error('Failed to repair RoutePoint floors from Maps:', error);
      alert(error.message || t.repairFloorsFailed);
    } finally {
      setIsRepairingFloors(false);
    }
  };

  // Part 4 — one-shot guard so the ?openUpload=1 arrival only ever
  // auto-opens the modal once, not on every re-render (e.g. after the
  // admin explicitly closes it).
  const autoOpenUploadRef = useRef(false);

  const openUploadModal = () => {
    if (uploadPreview) {
      URL.revokeObjectURL(uploadPreview);
    }

    setUploadForm(INITIAL_UPLOAD_FORM);
    setUploadFile(null);
    setUploadPreview('');
    setUploadError('');
    setUploadMode('single');
    setMapGroupForm(INITIAL_MAP_GROUP_FORM);
    revokeFloorRowPreviews(floorRows);
    setFloorRows([createEmptyFloorRow([])]);
    setGroupUploadError('');
    setIsUploadOpen(true);
  };

  // Part 4 — auto-open the upload modal, pre-filled with the Building
  // context carried over from the Add/Edit Room screen, exactly once per
  // arrival. Runs after `maps`/buildings are already loading via the
  // mount effect above, so it never races the rest of the screen's setup.
  useEffect(() => {
    if (!openUploadRequested || autoOpenUploadRef.current) return;
    autoOpenUploadRef.current = true;

    openUploadModal();
    if (requestedBuildingId) {
      setUploadForm((prev) => ({ ...prev, buildingId: requestedBuildingId }));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [openUploadRequested, requestedBuildingId]);

  const closeUploadModal = () => {
    if (isUploading || isUploadingGroup) return;

    if (uploadPreview) {
      URL.revokeObjectURL(uploadPreview);
    }

    setUploadFile(null);
    setUploadPreview('');
    setUploadError('');
    revokeFloorRowPreviews(floorRows);
    setGroupUploadError('');
    setIsUploadOpen(false);
  };

  const handleUploadFileChange = (event) => {
    const file =
      event.target.files?.[0] ||
      null;

    if (uploadPreview) {
      URL.revokeObjectURL(uploadPreview);
    }

    setUploadFile(file);
    setUploadError('');

    if (!file) {
      setUploadPreview('');
      return;
    }

    setUploadPreview(
      file.type.startsWith('image/')
        ? URL.createObjectURL(file)
        : '',
    );

    if (!uploadForm.title.trim()) {
      setUploadField(
        'title',
        file.name
          .replace(/\.[^.]+$/, '')
          .replace(/[_-]+/g, ' '),
      );
    }
  };

  const uploadMap = async () => {
    const cleanedTitle =
      uploadForm.title.trim();

    if (
      !uploadFile ||
      cleanedTitle.length < 2
    ) {
      setUploadError(
        t.requiredUploadFields,
      );

      return;
    }

    const scaleNumber = Number(
      uploadForm.scale,
    );

    const safeScale =
      Number.isFinite(scaleNumber) &&
      scaleNumber > 0
        ? scaleNumber
        : 1;

    const formData = new FormData();

    formData.append(
      'file',
      uploadFile,
    );

    formData.append(
      'title',
      cleanedTitle,
    );

    formData.append(
      'scale',
      String(safeScale),
    );

    formData.append(
      'use_openai',
      String(
        Boolean(uploadForm.useOpenAI),
      ),
    );

    formData.append(
      'auto_generate_graph',
      String(Boolean(uploadForm.autoGenerateGraph)),
    );

    if (uploadForm.buildingId) {
      formData.append('building_id', uploadForm.buildingId);
    }

    if (
      uploadForm.floor !== '' &&
      uploadForm.floor !== null &&
      uploadForm.floor !== undefined
    ) {
      formData.append('floor', String(Number(uploadForm.floor)));
    }

    if (uploadForm.campus.trim()) {
      formData.append(
        'campus',
        uploadForm.campus.trim(),
      );
    }

    if (uploadForm.address.trim()) {
      formData.append(
        'address',
        uploadForm.address.trim(),
      );
    }

    if (
      uploadForm.description.trim()
    ) {
      formData.append(
        'description',
        uploadForm.description.trim(),
      );
    }

    setIsUploading(true);
    setUploadError('');

    try {
      const newMap = await apiUploadMap(formData);

      setMaps((previousMaps) => [
        newMap,
        ...previousMaps
          .filter(
            (map) => map.id !== newMap.id,
          )
          .map((map) => ({
            ...map,
            isCurrent: false,
          })),
      ]);

      setSelectedMapId(newMap.id);
      setRoutePoints([]);
      setRouteEdges([]);
      setPollingMapId(newMap.id);
      setIsUploadOpen(false);

      if (uploadPreview) {
        URL.revokeObjectURL(
          uploadPreview,
        );
      }

      setUploadFile(null);
      setUploadPreview('');

      // Part 4 — arrived from the Add/Edit Room screen: return there with
      // ?newMapId=<id> so it can refetch Maps and auto-select the map
      // that was just created, instead of leaving the admin stranded on
      // Map Management after finishing the upload they came here to do.
      if (returnToRoomPath) {
        navigate(`${returnToRoomPath}?newMapId=${encodeURIComponent(newMap.id)}`);
      } else {
        alert(t.uploadSuccess);
      }
    } catch (error) {
      console.error(
        'Failed to upload map:',
        error,
      );

      setUploadError(
        error.message ||
          t.uploadError,
      );
    } finally {
      setIsUploading(false);
    }
  };

  // ── Multi-floor Map Group upload/management helpers ─────────────────────

  const revokeFloorRowPreviews = (rows) => {
    rows.forEach((row) => {
      if (row.preview) {
        URL.revokeObjectURL(row.preview);
      }
    });
  };

  // Generic row-list mutators, parameterized by which state setter to
  // operate on — reused as-is for both the initial multi-floor upload
  // form (floorRows) and the "Add Floor" mini-form on an existing group
  // (addFloorRows), so the two forms can never accidentally leak state
  // into each other while still sharing one implementation.
  const addFloorRowTo = (setRows) => {
    setRows((previousRows) => [
      ...previousRows,
      createEmptyFloorRow(previousRows, `${Date.now()}-${previousRows.length}`),
    ]);
  };

  const removeFloorRowFrom = (setRows) => (rowId) => {
    setRows((previousRows) => {
      const target = previousRows.find((row) => row.rowId === rowId);
      if (target?.preview) {
        URL.revokeObjectURL(target.preview);
      }
      return previousRows.filter((row) => row.rowId !== rowId);
    });
  };

  const updateFloorRowIn = (setRows) => (rowId, field, value) => {
    setRows((previousRows) =>
      previousRows.map((row) =>
        row.rowId === rowId ? { ...row, [field]: value } : row,
      ),
    );
  };

  const handleFloorFileChangeIn = (setRows) => (rowId, file) => {
    setRows((previousRows) =>
      previousRows.map((row) => {
        if (row.rowId !== rowId) return row;

        if (row.preview) {
          URL.revokeObjectURL(row.preview);
        }

        return {
          ...row,
          file,
          fileName: file?.name || '',
          preview: file ? URL.createObjectURL(file) : '',
          title:
            row.title ||
            (file
              ? file.name.replace(/\.[^.]+$/, '').replace(/[_-]+/g, ' ')
              : row.title),
        };
      }),
    );
  };

  const addFloorRow = () => addFloorRowTo(setFloorRows);
  const removeFloorRow = removeFloorRowFrom(setFloorRows);
  const updateFloorRow = updateFloorRowIn(setFloorRows);
  const handleFloorFileChange = handleFloorFileChangeIn(setFloorRows);

  const setMapGroupField = (field, value) =>
    setMapGroupForm((previous) => ({ ...previous, [field]: value }));

  const handleUploadMapGroup = async () => {
    const cleanedName = mapGroupForm.name.trim();

    if (cleanedName.length < 2) {
      setGroupUploadError(t.mapGroupNameRequired);
      return;
    }

    const rowErrors = validateFloorRows(floorRows);
    if (Object.keys(rowErrors).length > 0) {
      setGroupUploadError(t.floorRowsInvalid);
      return;
    }

    setIsUploadingGroup(true);
    setGroupUploadError('');

    try {
      const group = await apiCreateMapGroup(
        {
          name: cleanedName,
          code: mapGroupForm.code.trim() || undefined,
          buildingId: mapGroupForm.buildingId || undefined,
          campus: mapGroupForm.campus.trim() || undefined,
          address: mapGroupForm.address.trim() || undefined,
          description: mapGroupForm.description.trim() || undefined,
        },
        floorRows,
      );

      await Promise.all([loadMaps(), loadMapGroups()]);

      revokeFloorRowPreviews(floorRows);
      setFloorRows([createEmptyFloorRow([])]);
      setMapGroupForm(INITIAL_MAP_GROUP_FORM);
      setIsUploadOpen(false);

      if (group?.floors?.[0]?.id) {
        setSelectedMapId(group.floors[0].id);
      }

      alert(t.mapGroupUploadSuccess);
    } catch (error) {
      console.error('Failed to upload map group:', error);
      setGroupUploadError(error.message || t.mapGroupUploadError);
    } finally {
      setIsUploadingGroup(false);
    }
  };

  // ── Map Management: grouped list expand/collapse + Add Floor ───────────

  const toggleGroupExpanded = (groupId) => {
    setExpandedGroupIds((previous) => {
      const next = new Set(previous);
      if (next.has(groupId)) {
        next.delete(groupId);
      } else {
        next.add(groupId);
      }
      return next;
    });
  };

  const openAddFloorForm = (group) => {
    setAddFloorGroupId(group.id);
    setAddFloorRows([
      createEmptyFloorRow(group.floors || []),
    ]);
    setAddFloorError('');
  };

  const closeAddFloorForm = () => {
    if (isAddingFloor) return;
    revokeFloorRowPreviews(addFloorRows);
    setAddFloorGroupId('');
    setAddFloorRows([]);
    setAddFloorError('');
  };

  const addAddFloorRow = () => addFloorRowTo(setAddFloorRows);
  const removeAddFloorRow = removeFloorRowFrom(setAddFloorRows);
  const updateAddFloorRow = updateFloorRowIn(setAddFloorRows);
  const handleAddFloorFileChange = handleFloorFileChangeIn(setAddFloorRows);

  const handleSubmitAddFloor = async () => {
    const group = mapGroups.find((g) => g.id === addFloorGroupId);
    if (!group) return;

    const existingFloorNumbers = (group.floors || []).map((f) => f.floor);
    const rowErrors = validateFloorRows(addFloorRows, existingFloorNumbers);

    if (Object.keys(rowErrors).length > 0) {
      setAddFloorError(t.floorRowsInvalid);
      return;
    }

    setIsAddingFloor(true);
    setAddFloorError('');

    try {
      await apiAddMapGroupFloors(group.id, addFloorRows);
      await Promise.all([loadMaps(), loadMapGroups()]);
      revokeFloorRowPreviews(addFloorRows);
      setAddFloorGroupId('');
      setAddFloorRows([]);
    } catch (error) {
      console.error('Failed to add floor(s):', error);
      setAddFloorError(error.message || t.mapGroupUploadError);
    } finally {
      setIsAddingFloor(false);
    }
  };

  const handleDeleteMapGroupFloor = async (group, floorMap) => {
    if (!window.confirm(t.confirmDeleteFloor(floorMap.title))) return;

    try {
      await apiDeleteMapGroupFloor(group.id, floorMap.id);
      await Promise.all([loadMaps(), loadMapGroups()]);
      if (selectedMapId === floorMap.id) {
        setSelectedMapId('');
      }
    } catch (error) {
      console.error('Failed to delete floor:', error);
      alert(error.message || t.mapGroupUploadError);
    }
  };

  const handleDeleteMapGroup = async (group) => {
    if (!window.confirm(t.confirmDeleteGroup(group.name))) return;

    try {
      await apiDeleteMapGroup(group.id);
      await Promise.all([loadMaps(), loadMapGroups()]);
      if ((group.floors || []).some((f) => f.id === selectedMapId)) {
        setSelectedMapId('');
      }
    } catch (error) {
      console.error('Failed to delete map group:', error);
      alert(error.message || t.mapGroupUploadError);
    }
  };

  // Groups derived straight from `maps` (flat, always up to date via the
  // normal loadMaps() refresh cycle) rather than solely trusting the
  // separately-fetched `mapGroups` list, so the grouped Map Management
  // view can never show stale floor data for a group whose floors list
  // this component already knows is fresher.
  const { groups: groupedMapEntries, ungrouped: ungroupedMaps } = useMemo(
    () => groupMapsByMapGroup(maps),
    [maps],
  );

  // Enriches the derived groups above with each MapGroup's own metadata
  // (name/code/building/campus/address) from the separately-loaded
  // mapGroups list — falls back to just the id/code when that hasn't
  // loaded yet, so the list still renders (with a plain code fallback)
  // instead of blocking on a second request.
  const mapManagementGroups = useMemo(
    () =>
      groupedMapEntries.map((entry) => {
        const groupMeta = mapGroups.find((g) => g.id === entry.groupId);
        return {
          id: entry.groupId,
          code: groupMeta?.code || entry.groupCode || '',
          name: groupMeta?.name || entry.floors[0]?.title || '',
          buildingId: groupMeta?.buildingId || entry.floors[0]?.buildingId || '',
          floors: entry.floors,
        };
      }),
    [groupedMapEntries, mapGroups],
  );

  // Sibling floors of the currently active map (used by the full-map
  // editor's floor switcher) — derived the same way, so it reflects the
  // very latest floor list without a separate fetch every time the full
  // map view opens.
  const activeMapGroupFloors = useMemo(() => {
    if (!activeMap?.mapGroupId) return [];
    const group = groupedMapEntries.find(
      (entry) => entry.groupId === activeMap.mapGroupId,
    );
    return group ? group.floors : [];
  }, [activeMap, groupedMapEntries]);

  // Edit Map Details' Floor <select> options — which floor NUMBERS this
  // Map itself can be assigned to (distinct from floorSelectOptions
  // above, which lists other MAPS the workspace can switch to). See
  // utils/mapGroupHelpers.js's buildFloorEditOptions for the full
  // group-vs-legacy-standalone contract.
  const editFloorOptions = useMemo(
    () => buildFloorEditOptions(activeMap, activeMapGroupFloors),
    [activeMap, activeMapGroupFloors],
  );

  // The real, always-editable floor control every tool (Add Point, Draw
  // Walkable Path, Test Route, Vertical Connections) renders — never a
  // locked/read-only field. Built from the FULL loaded `maps` array via
  // buildFloorOptions()'s 3-tier priority (mapGroupId siblings, then
  // buildingId siblings, then always activeMap itself) rather than
  // solely `activeMapGroupFloors`, which is empty for any legacy map with
  // no Map Group linkage and was the actual source of the reported
  // "single blank '—' option" bug. Its value is always exactly
  // `selectedMapId` so the selected floor and selected map can never
  // disagree (picking an option calls handleFloorSwitch, which is the
  // ONLY place selectedMapId changes for a floor switch). See
  // utils/mapGroupHelpers.js's buildFloorOptions for the full contract.
  const floorSelectOptions = useMemo(
    () => buildFloorOptions(activeMap, maps),
    [activeMap, maps],
  );

  // Shared floor <select> markup for every tool panel (Add Point, Draw
  // Walkable Path, Test Route) — a real dropdown, never a free numeric
  // input and never disabled/read-only (per the reported regression: a
  // locked "Floor 0" field made an existing Floor 1 point permanently
  // unreusable). `idSuffix` only keeps each panel's <label>/<select> pair
  // uniquely keyed; the value/onChange logic is identical everywhere.
  // Section 6 defensive state: floorSelectOptions can only be empty when
  // there is truly no activeMap at all (buildFloorOptions() always
  // includes activeMap itself otherwise) — in that case, never render an
  // empty/blank <select>; show an explicit message + a Retry Maps button
  // that re-runs loadMaps() instead.
  const renderFloorSelect = (labelText, idSuffix) => {
    if (floorSelectOptions.length === 0) {
      return (
        <div className="adm-form-group">
          <label className="adm-form-label">{labelText}</label>
          <div
            style={{
              fontSize: 12.5,
              color: '#b42318',
              fontWeight: 600,
              marginBottom: 6,
            }}
          >
            {t.noFloorMapsLoaded}
          </div>
          <button
            type="button"
            className="adm-btn adm-btn-cancel"
            onClick={() => loadMaps(selectedMapId)}
            disabled={isMapsLoading}
          >
            {isMapsLoading ? t.loadingMaps : t.retryMapsButton}
          </button>
        </div>
      );
    }

    return (
    <div className="adm-form-group">
      <label className="adm-form-label" htmlFor={`floor-select-${idSuffix}`}>
        {labelText}
      </label>
      <select
        id={`floor-select-${idSuffix}`}
        className="adm-form-input"
        value={selectedMapId}
        onChange={(event) => handleFloorSwitch(event.target.value)}
      >
        {floorSelectOptions.map((floorMap) => (
          <option key={floorMap.mapId} value={floorMap.mapId}>
            {floorMap.floorLabel}
          </option>
        ))}
      </select>
    </div>
    );
  };

  const handleFullMapClick = (event) => {
    // Dragging the floating tool panel must never place/select a point on
    // the map underneath it, even if the pointer briefly passes over the
    // map image during the drag or the drag ends there.
    if (isPanelDraggingRef.current) {
      return;
    }

    const image = event.currentTarget;

    // Defense-in-depth: this handler must only ever act on a real click on
    // the map stage's own image element — never on the surrounding
    // workspace (the gutters beside a portrait map, now a much larger
    // clickable-looking area than before). Wired as `onClick` directly on
    // `<img ref={fullMapImageRef}>`, so `event.currentTarget` is always
    // that image already; this check just makes the contract explicit and
    // fails safe if that wiring is ever changed.
    if (!image || image !== fullMapImageRef.current) {
      return;
    }

    const rect =
      image.getBoundingClientRect();

    const displayX =
      event.clientX -
      rect.left;

    const displayY =
      event.clientY -
      rect.top;

    const scaleX = image.naturalWidth / rect.width;
    const scaleY = image.naturalHeight / rect.height;

    const x = Math.round(displayX * scaleX);
    const y = Math.round(displayY * scaleY);

    setFullMapMetrics({
      displayWidth: rect.width,
      displayHeight: rect.height,
      naturalWidth: image.naturalWidth,
      naturalHeight: image.naturalHeight,
    });

    // Draw Walkable Path has its own click handling and must never also
    // trigger the normal single-point Add Point form. The current render
    // scale is passed through so the snap threshold can be sized in real
    // screen pixels instead of a fixed (and often far-too-small) number of
    // native map pixels — see resolveSnapThresholdPx() in utils/geometry.js.
    if (mode === 'draw') {
      handleDrawClick(x, y, (scaleX + scaleY) / 2);
      return;
    }

    if (mode === 'connector') {
      setConnectorPendingClick({ x, y });
      return;
    }

    // Calibrate Scale: reuses the exact same original-image pixel
    // coordinate system as Add Point / Draw Walkable Path above (the
    // (x, y) already computed at the top of this handler), via the shared
    // computeOriginalImageCoords helper so this never duplicates a second
    // coordinate transform. The first click sets Point A, the second sets
    // Point B and opens the "known real distance" prompt; further clicks
    // are ignored until the admin resets or cancels — this also means
    // normal Add Point / Draw Path placement never fires while calibrating.
    if (mode === 'calibrate') {
      const coords = computeOriginalImageCoords({
        clientX: event.clientX,
        clientY: event.clientY,
        rectLeft: rect.left,
        rectTop: rect.top,
        rectWidth: rect.width,
        rectHeight: rect.height,
        naturalWidth: image.naturalWidth,
        naturalHeight: image.naturalHeight,
      });

      if (!coords) {
        return;
      }

      if (!calibrationPointA) {
        setCalibrationPointA(coords);
      } else if (!calibrationPointB) {
        setCalibrationPointB(coords);
        setIsCalibrationDistanceOpen(true);
      }

      return;
    }

    // Edit Route Points mode (RBAC/dashboard cleanup task, Phase 13):
    // selecting an existing point is handled entirely through each
    // marker's own onClick (selectPointForEditing, wired on the route-
    // point layer below) — a plain click on the map background/image
    // must NEVER create or move a point while this mode is merely active.
    // The one exception is the explicit "Move Point" sub-state: only
    // once the admin has pressed Move Point in the detail panel does the
    // NEXT background click actually reposition editPointTarget (still
    // never creating a new point) — this two-step requirement is exactly
    // what "explicit editing mode so normal Map clicks cannot
    // accidentally create/move points" means in practice.
    if (mode === 'edit-points') {
      if (editPointMoving && editPointTarget) {
        handleEditPointMoveTo(x, y);
      }
      return;
    }

    // Delete Connection mode: edge selection happens exclusively through
    // each edge's own invisible hit-stroke (handleEdgeClickForDeletion,
    // wired directly on the edge overlay below) — a plain click on the map
    // background/image itself must never create a RoutePoint, or select
    // anything, while this mode is active.
    if (mode === 'delete-connection') {
      return;
    }

    // Auto Connect Destinations preview mode: a plain click on the map
    // background/image must never create a RoutePoint either. Picking a
    // manual corridor point is handled entirely through each RoutePoint
    // marker's own onClick (selectManualCorridorPoint below), never
    // through this generic background click handler.
    if (mode === 'auto-connect') {
      return;
    }

    // Create Destinations from Approved Analysis: a plain map click never
    // creates an ordinary RoutePoint here. When a proposal's manual
    // placement is pending (Section 5 — no AI door/centroid coordinate
    // exists), this click IS the admin-reviewed location for that one
    // proposal; otherwise the click is simply ignored, exactly like
    // Auto Connect / Delete Connection above.
    if (mode === 'semantic-destinations') {
      // Fast batch placement (Section 3): while active, THIS click always
      // targets the current batch queue item — takes priority over the
      // older single-target "Pick Location" flow below. This is also the
      // actual fix for that flow's map-click bug: the batch panel is a
      // draggable/collapsible FloatingToolPanel instead of a fixed
      // full-height sidebar, so it never permanently covers the room the
      // admin needs to click.
      if (semanticBatchActive) {
        handleBatchDestinationMapClick(x, y);
        return;
      }
      if (semanticDestManualPlaceTargetId) {
        setSemanticDestProposals((previous) =>
          previous.map((proposal) =>
            proposal.semantic_item_id === semanticDestManualPlaceTargetId
              ? { ...proposal, x, y, localStatus: 'accepted' }
              : proposal,
          ),
        );
        setSemanticDestManualPlaceTargetId(null);
      }
      return;
    }

    setClickedPoint({ x, y });
    setPointName(`Point ${x},${y}`);
  };

  // ── Draw Walkable Path handlers ────────────────────────────────────────────

  // Direct, deterministic selection: called by a saved RoutePoint marker's
  // own onClick when Draw Walkable Path is active. The marker already IS
  // the RoutePoint object — no coordinate math, no proximity threshold, no
  // re-derivation of which point was clicked. This is the primary way an
  // existing point gets reused; proximity snapping in handleDrawClick below
  // is only a fallback for clicks that land near-but-not-exactly-on a
  // marker (the SVG's route-point layer sits under `pointerEvents: none`
  // everywhere except the markers themselves, so a direct hit here means
  // the admin's cursor was genuinely over that marker's rendered shape).
  const selectExistingPointForDraft = (point, event) => {
    if (mode !== 'draw') {
      return;
    }

    if (isPanelDraggingRef.current) {
      return;
    }

    if (event) {
      event.stopPropagation();
    }

    setDraftError('');

    const lastDraftPoint = draftPoints[draftPoints.length - 1];

    const result = resolveExistingPointSelection({
      point,
      activeMapId: activeMap?.id,
      drawFloor,
      lastDraftPoint,
    });

    if (!result.ok) {
      // duplicate-consecutive and a plain re-click are silent no-ops (the
      // same way the proximity path already treats them); anything else
      // (wrong map/floor, inactive point) is worth surfacing so the admin
      // understands why the click didn't do anything.
      if (result.reason === 'wrong-map') {
        // Section 5: a point whose real map_id doesn't match the current
        // active map (e.g. it still references a legacy/pre-migration
        // Map document) must never be silently treated as reusable, and
        // must never be masked by the generic message — the admin needs
        // to know exactly what to do about it. Report the real ids
        // internally (dev console only, never surfaced to the admin) so
        // this is diagnosable without exposing anything sensitive.
        if (import.meta.env?.DEV) {
          console.warn(
            '[Draw Walkable Path] Rejected point reuse: point belongs to a different map.',
            {
              pointId: point?.id ?? point?._id,
              pointMapId: point?.map_id ?? point?.mapId,
              activeMapId: activeMap?.id,
              activeMapGroupId: activeMap?.mapGroupId,
            },
          );
        }
        setDraftError(t.drawWrongMapReject(formatFloorDisplay(activeMap?.floor, activeMap?.floorLabel)));
      } else if (result.reason !== 'duplicate-consecutive') {
        setDraftError(t.drawWrongPointReject);
      }
      return;
    }

    setDraftPoints((previous) => [...previous, result.draftItem]);
  };

  const handleDrawClick = (x, y, renderScale = 1) => {
    setDraftError('');

    // Convert the fixed "comfortable to click" screen-pixel target into
    // this map's current native-pixel space. renderScale is
    // naturalWidth/renderedWidth at the moment of this exact click, so the
    // effective on-screen hit target stays a consistent size no matter how
    // large the uploaded map's source resolution is or how zoomed in the
    // admin currently is. This whole function only runs for clicks that did
    // NOT land directly on a marker (those are caught by
    // selectExistingPointForDraft via the marker's own onClick first), so
    // this is intentionally a fallback, not the primary reuse mechanism.
    const snapThresholdPx = resolveSnapThresholdPx(
      SNAP_SCREEN_PX,
      renderScale,
      SNAP_MIN_NATIVE_PX,
    );

    // Ignore a click that lands on (or right next to) the last draft point
    // — this is almost always an accidental double-click and would create
    // a zero-length duplicate segment.
    const lastDraftPoint = draftPoints[draftPoints.length - 1];

    if (
      lastDraftPoint &&
      Math.sqrt(
        (x - lastDraftPoint.x) ** 2 + (y - lastDraftPoint.y) ** 2,
      ) <= snapThresholdPx
    ) {
      return;
    }

    const nearestExisting = findNearestPointWithinThreshold(
      routePoints,
      x,
      y,
      snapThresholdPx,
      drawFloor,
    );

    if (nearestExisting) {
      const result = resolveExistingPointSelection({
        point: nearestExisting,
        activeMapId: activeMap?.id,
        drawFloor,
        lastDraftPoint,
      });

      if (result.ok) {
        setDraftPoints((previous) => [...previous, result.draftItem]);
        return;
      }

      if (result.reason === 'duplicate-consecutive') {
        return;
      }

      if (result.reason === 'wrong-map') {
        // Section 5 / "Do not create duplicate points as a workaround":
        // the nearest existing point genuinely belongs to a different Map
        // document (e.g. a legacy pre-migration map). Silently falling
        // through to create a brand new point here would leave the admin
        // with two coincident points on the same spot and no indication
        // anything was wrong — surface the precise reassignment message
        // instead and stop, exactly like the direct marker-click path.
        if (import.meta.env?.DEV) {
          console.warn(
            '[Draw Walkable Path] Nearest point rejected: belongs to a different map.',
            {
              pointId: nearestExisting?.id ?? nearestExisting?._id,
              pointMapId: nearestExisting?.map_id ?? nearestExisting?.mapId,
              activeMapId: activeMap?.id,
              activeMapGroupId: activeMap?.mapGroupId,
            },
          );
        }
        setDraftError(t.drawWrongMapReject(formatFloorDisplay(activeMap?.floor, activeMap?.floorLabel)));
        return;
      }
      // Any other rejection (wrong floor, inactive) falls through to
      // creating a new point below — proximity match found *something*
      // nearby, but it wasn't a valid reuse target, so treat this click as
      // a genuinely new point instead of silently dropping it.
    }

    setDraftPoints((previous) => [
      ...previous,
      {
        tempId: `new-${Date.now()}-${previous.length}`,
        kind: 'new',
        x,
        y,
        floor: drawFloor,
        // Short, sequential, human-meaningful default (e.g. "Point 2") —
        // never a timestamp. The admin can edit this in the draft-point
        // list before Save Path; if left as-is it's still a perfectly
        // valid name, just a generic one.
        name: generateDefaultDraftPointName(previous),
      },
    ]);
  };

  const handleUndoDraft = () => {
    setDraftError('');
    // Removing only the LAST draft item (never an arbitrary middle one)
    // keeps this safe/compatible with the rest of the draft: every other
    // item's index, resolved reuse, and any already-typed name is left
    // completely untouched, so nothing needs re-validating.
    setDraftPoints((previous) => previous.slice(0, -1));
  };

  // Updates the editable name of a single "new" draft point in place —
  // used by the draft-point list's per-row name input. Only ever touches
  // draftPoints[index].name; every other field (kind, x, y, floor, or a
  // reused point's routePointId/name) is left exactly as-is. Typed names
  // are ordinary React state, so they naturally survive Undo (which only
  // ever drops the last item), panel drag, and panel collapse/restore —
  // none of those touch draftPoints at all.
  const handleDraftPointNameChange = (index, value) => {
    setDraftPoints((previous) => updateDraftPointName(previous, index, value));
  };

  const handleClearDraft = () => {
    setDraftError('');
    setDraftPoints([]);
  };

  const handleCancelDraw = () => {
    setMode('point');
    setDraftPoints([]);
    setDraftError('');
  };

  const handleSaveDraft = async () => {
    if (draftPoints.length < 2) {
      setDraftError(t.drawNeedTwo);
      return;
    }

    if (!activeMap?.id) {
      setDraftError(t.noSelectedMap);
      return;
    }

    // Defense in depth beyond the Save Path button's own disabled state —
    // never send an invalid name to createRoutePoint.
    if (!computeIsDraftNamingValid(draftPoints)) {
      setDraftError(t.drawInvalidNames);
      return;
    }

    setIsSavingDraft(true);
    setDraftError('');

    // Tracks only what THIS save created, so a failure can be rolled back
    // without ever touching pre-existing reused points.
    const createdPointIds = [];
    const createdEdgeIds = [];
    let reusedPointCount = 0;
    let skippedDuplicateEdgeCount = 0;
    let mergedNearbyEdgeCount = 0;

    // resolvedIds[i] is the real backend RoutePoint id for draftPoints[i],
    // whether that point was freshly created or an existing point reused
    // via a direct marker click or proximity snapping.
    const resolvedIds = new Array(draftPoints.length).fill(null);

    // Pure partition: which draft indices already have a real id (never
    // call createRoutePoint for these — that is the exact bug this task
    // fixes) versus which indices still need a fresh RoutePoint.
    const { reuses, creates } = partitionDraftForSave(draftPoints);

    // Translate the panel's "Automatic graph merging" selection into what
    // createRoutePoint actually needs to send. 'off' bypasses server-side
    // dedup entirely (force_create) — only explicit marker-click reuse ever
    // connects to anything. 'reuseOnly' (default) keeps the previous
    // behavior: dedup active, no automatic nearby connection. 'nearby' asks
    // the backend to also auto-connect each new point to safe neighbors.
    const forceCreate = mergeMode === 'off';
    const autoConnect = mergeMode === 'nearby' ? 'nearest' : 'off';

    try {
      reuses.forEach(({ index, routePointId }) => {
        resolvedIds[index] = routePointId;
      });
      reusedPointCount = reuses.length;

      for (const { index, x, y, floor, name } of creates) {
        // Already validated above (and by the disabled Save Path button),
        // but re-derive the trimmed value here too rather than trusting
        // the raw typed string — trims accidental leading/trailing
        // whitespace out of what actually gets sent to the backend.
        const trimmedName = validateDraftPointName(name).trimmed;

        const created = await createRoutePoint(
          {
            map_id: activeMap.id,
            name: trimmedName,
            point_type: 'hallway',
            x,
            y,
            // Never `?? 0` — a genuinely unknown floor (legacy/ungrouped
            // map) must stay null rather than being silently recorded as
            // Ground Floor. RoutePointCreate.floor is Optional[int], so
            // the backend accepts null here.
            floor: (() => {
              const resolvedFloor = floor ?? drawFloor;
              return resolvedFloor === null || resolvedFloor === undefined
                ? null
                : Number(resolvedFloor);
            })(),
            building_id: null,
            room_id: null,
            is_accessible: true,
            force_create: forceCreate,
          },
          { autoConnect },
        );

        const newId = created.id || created._id;
        resolvedIds[index] = newId;
        createdPointIds.push(newId);

        // Any edges the backend created automatically (auto_connect=
        // nearest) are a side effect of THIS save too — track them for
        // both the summary count and rollback, since deleting the point
        // alone would otherwise be rejected while these edges still
        // reference it.
        if (Array.isArray(created.auto_connected_edge_ids)) {
          created.auto_connected_edge_ids.forEach((edgeId) => {
            createdEdgeIds.push(edgeId);
            mergedNearbyEdgeCount += 1;
          });
        }
      }

      // Build the set of already-existing edges (in either direction) so a
      // re-drawn segment over an already-connected pair doesn't create a
      // duplicate edge, then the ordered list of pairs Save Path still
      // needs to create.
      const existingEdgeKeys = buildEdgeKeySet(routeEdges);
      const edgePlan = buildEdgePlan(resolvedIds, existingEdgeKeys);
      skippedDuplicateEdgeCount = edgePlan.skippedCount;

      for (const { fromId, toId } of edgePlan.toCreate) {
        try {
          const createdEdge = await createRouteEdge({
            map_id: activeMap.id,
            from_point_id: fromId,
            to_point_id: toId,
            edge_type: 'walkway',
            is_bidirectional: true,
            is_accessible: true,
          });

          createdEdgeIds.push(createdEdge.id || createdEdge._id);
        } catch (edgeError) {
          // The backend independently rejects an edge that already exists
          // between these two points (defense in depth beyond the
          // existingEdgeKeys check above, e.g. if routeEdges was stale).
          // That is an expected, recoverable "already connected" outcome —
          // count it and keep saving the rest of the path instead of
          // rolling back everything already created in this save.
          const message = String(edgeError?.message || '').toLowerCase();

          if (message.includes('already exists')) {
            skippedDuplicateEdgeCount += 1;
            continue;
          }

          throw edgeError;
        }
      }

      const summary = t.drawSaveSuccess(
        createdPointIds.length,
        createdEdgeIds.length - mergedNearbyEdgeCount,
        reusedPointCount,
        skippedDuplicateEdgeCount,
        mergedNearbyEdgeCount,
      );

      // The draw toolbar unmounts the instant we switch back to 'point'
      // mode, so an inline success message would never actually be seen —
      // use the same alert() pattern the rest of this screen already uses
      // for save confirmations.
      setMode('point');
      setDraftPoints([]);

      await refreshRouteGraph(activeMap.id);

      alert(summary);
    } catch (error) {
      console.error('Failed to save walkable path, rolling back:', error);

      // Roll back edges first (they reference points), then points. Only
      // ever delete what THIS save created — reused existing points are
      // never touched.
      for (const edgeId of createdEdgeIds.reverse()) {
        try {
          await deleteRouteEdge(edgeId);
        } catch (rollbackError) {
          console.error('Rollback: failed to delete edge', edgeId, rollbackError);
        }
      }

      for (const pointId of createdPointIds.reverse()) {
        try {
          await deleteRoutePoint(pointId);
        } catch (rollbackError) {
          console.error('Rollback: failed to delete point', pointId, rollbackError);
        }
      }

      setDraftError(t.drawSaveFailed);

      // Refresh so the overlay reflects the post-rollback truth rather than
      // any partially-created state that briefly existed on the backend.
      await refreshRouteGraph(activeMap.id);
    } finally {
      setIsSavingDraft(false);
    }
  };

  const saveRoutePoint = async () => {
    if (
      !clickedPoint ||
      !pointName.trim()
    ) {
      return;
    }

    if (!activeMap?.id) {
      alert(t.noSelectedMap);
      return;
    }

    const payload = {
      map_id: activeMap.id,
      name: pointName.trim(),
      point_type: pointType,
      x: clickedPoint.x,
      y: clickedPoint.y,
      floor: Number(floor),
      building_id: isPlaceType ? selectedBuildingId || null : null,
      room_id: isPlaceType ? selectedRoomId || null : null,
      is_accessible: true,
    };

    try {
      const savedPoint = await createRoutePoint(payload);

      setRoutePoints(
        (previousPoints) => [
          ...previousPoints,
          savedPoint,
        ],
      );

      // Connect Place: optionally wire this new point into the graph by
      // creating a walkway edge to the nearest existing point on the same
      // floor. Never crosses floors (that would be an invalid walkway) and
      // never crosses maps (routePoints here is already scoped to the
      // active map).
      if (connectToNearest) {
        const nearest = findNearestPointWithinThreshold(
          routePoints,
          savedPoint.x,
          savedPoint.y,
          Infinity,
          savedPoint.floor,
        );

        if (nearest) {
          const nearestId = nearest.id || nearest._id;
          const newId = savedPoint.id || savedPoint._id;

          try {
            const newEdge = await createRouteEdge({
              map_id: activeMap.id,
              from_point_id: newId,
              to_point_id: nearestId,
              edge_type: 'walkway',
              is_bidirectional: true,
              is_accessible: true,
            });

            setRouteEdges((previousEdges) => [...previousEdges, newEdge]);
          } catch (connectError) {
            // The point itself was saved successfully — a failed connecting
            // edge shouldn't be reported as a failed point save. Log it and
            // let the admin connect it manually via Draw Walkable Path.
            console.error(
              'Route point saved, but connecting edge failed:',
              connectError,
            );
          }
        }
      }

      setClickedPoint(null);
      setPointName('');
      setPointType('hallway');
      setSelectedBuildingId('');
      setSelectedRoomId('');

      alert(t.savedPoint);
    } catch (error) {
      console.error(
        'Failed to save route point:',
        error,
      );

      alert(
        'Failed to save route point',
      );
    }
  };

  // ── Test Route mode handlers ────────────────────────────────────────────────
  // Read-only: calls the real Dijkstra endpoint and renders the response.
  // Nothing here is ever written back to MongoDB.

  const handleFindRoute = async () => {
    if (!activeMap?.id || !testStartId || !testEndId) {
      return;
    }

    setIsTestLoading(true);
    setTestError('');
    setTestResult(null);

    try {
      const result = await calculateRoute({
        mapId: activeMap.id,
        startPointId: testStartId,
        endPointId: testEndId,
      });

      setTestResult(result);
    } catch (error) {
      console.error('Failed to calculate test route:', error);
      setTestError(error.message || t.testNoRoute);
    } finally {
      setIsTestLoading(false);
    }
  };

  const handleClearTest = () => {
    setTestResult(null);
    setTestError('');
  };

  const handleChangeTestStart = () => {
    setTestStartId('');
    setTestResult(null);
    setTestError('');
  };

  const handleChangeTestEnd = () => {
    setTestEndId('');
    setTestResult(null);
    setTestError('');
  };

  // ── Calibrate Scale mode handlers ───────────────────────────────────────────
  // Only ever calls the already-existing calibrateMapScale() (POST
  // /api/maps/{id}/calibrate-scale) — no new backend wiring, no touching
  // Dijkstra/RoutePoints/RouteEdges/graph topology directly. The backend
  // endpoint itself owns the scale formula and the safe walkway-edge
  // recalculation; this screen only collects the two clicked points + the
  // known distance and displays what comes back.

  const resetCalibrationPoints = () => {
    setCalibrationPointA(null);
    setCalibrationPointB(null);
    setIsCalibrationDistanceOpen(false);
    setCalibrationDistanceInput('');
    setCalibrationError('');
  };

  const handleCancelCalibration = () => {
    // Leaving calibrate mode must restore normal map interactions exactly —
    // 'point' is the screen's original default mode, and clearing the
    // draft Add Point state mirrors what every other mode switch already
    // does above, so Add Point behaves identically to before calibration
    // mode was ever entered.
    setMode('point');
    resetCalibrationPoints();
    setCalibrationResult(null);
    setClickedPoint(null);
    setPointName('');
  };

  const parsedCalibrationDistance = Number(calibrationDistanceInput);
  const isCalibrationDistanceValid =
    calibrationDistanceInput.trim() !== '' &&
    Number.isFinite(parsedCalibrationDistance) &&
    parsedCalibrationDistance > 0;

  const canSubmitCalibration = Boolean(
    activeMap?.id &&
      calibrationPointA &&
      calibrationPointB &&
      isCalibrationDistanceValid &&
      !isCalibrationSaving,
  );

  const handleSubmitCalibration = async () => {
    if (!canSubmitCalibration) {
      return;
    }

    setIsCalibrationSaving(true);
    setCalibrationError('');

    try {
      const updatedMap = await calibrateMapScale(activeMap.id, {
        pointA: calibrationPointA,
        pointB: calibrationPointB,
        realDistanceMeters: parsedCalibrationDistance,
      });

      setCalibrationResult({
        scale: updatedMap.scale,
        edgesRecalculated: updatedMap.edgesRecalculated ?? 0,
        edgesRecalculationSkipped: updatedMap.edgesRecalculationSkipped ?? 0,
      });

      resetCalibrationPoints();

      // Refresh the current map data (scale/isCalibrated) purely by
      // reusing the already-existing loadMaps() — no new refresh/sync
      // logic. activeMap re-derives automatically once `maps` updates.
      await loadMaps(activeMap.id);

      // Refresh the Route Test distance display too, but only if a test
      // route is already selected — reuses the existing handleFindRoute()
      // rather than duplicating route-recalculation logic here.
      if (testStartId && testEndId) {
        handleFindRoute();
      }
    } catch (error) {
      console.error('Failed to save calibration:', error);
      setCalibrationError(error.message || t.calibrateError);
    } finally {
      setIsCalibrationSaving(false);
    }
  };

  // ── Sync Rooms from Route Points (Section 4) ──────────────────────────────
  // Scoped to the currently active map's building — mirrors "operate on
  // the currently selected building or Map Group". Never touches
  // Dijkstra/routing/graph topology; only creates/updates Room documents.
  const handleConfirmSyncRooms = async () => {
    if (!activeMap?.buildingId) {
      setSyncRoomsError(t.syncRoomsNoScope);
      return;
    }

    setIsSyncingRooms(true);
    setSyncRoomsError('');

    try {
      const result = await syncRoomsFromRoutePoints({
        building_id: activeMap.buildingId,
      });

      setShowSyncRoomsConfirm(false);

      // Refresh whatever destination data this screen currently has
      // loaded — the Connect Place room picker's list for the building
      // that was just synced (reuses the same getRooms() the picker's own
      // effect already calls; no new fetch logic invented).
      if (selectedBuildingId === activeMap.buildingId) {
        try {
          const refreshed = await getRooms({ building_id: selectedBuildingId });
          setRoomsList(Array.isArray(refreshed) ? refreshed : []);
        } catch (refreshError) {
          console.error('Failed to refresh rooms after sync:', refreshError);
        }
      }

      alert(`${t.syncRoomsSuccess} — ${t.syncRoomsSummary(result)}`);
    } catch (error) {
      console.error('Failed to sync rooms from route points:', error);
      setSyncRoomsError(error.message || t.syncRoomsFailed);
    } finally {
      setIsSyncingRooms(false);
    }
  };

  // ── SVG overlay: point/edge lookups and color coding ──────────────────────
  // The overlay uses a single SVG whose viewBox equals the original image's
  // natural pixel dimensions, so route point x/y and edge geometry can be
  // rendered directly without any manual display-scaling math.

  const pointsById = useMemo(() => {
    const lookup = new Map();

    routePoints.forEach((point) => {
      const id = point.id || point._id;
      if (id) lookup.set(id, point);
    });

    return lookup;
  }, [routePoints]);

  const { resolvedEdges, missingEdgeCount } = useMemo(() => {
    const resolved = [];
    let missingCount = 0;

    routeEdges.forEach((edge) => {
      const fromPoint = pointsById.get(edge.from_point_id);
      const toPoint = pointsById.get(edge.to_point_id);

      if (!fromPoint || !toPoint) {
        missingCount += 1;
        return;
      }

      resolved.push({ edge, fromPoint, toPoint });
    });

    if (missingCount > 0) {
      console.warn(
        `AdminMapScreen: ${missingCount} route edge(s) for map ${selectedMapId} ` +
          'reference a from_point_id/to_point_id that was not found among the ' +
          'loaded route points for this map. These edges were skipped instead ' +
          'of rendered.',
        routeEdges.filter(
          (edge) =>
            !pointsById.has(edge.from_point_id) ||
            !pointsById.has(edge.to_point_id),
        ),
      );
    }

    return { resolvedEdges: resolved, missingEdgeCount: missingCount };
  }, [routeEdges, pointsById, selectedMapId]);

  // STEP 8 visual feedback: while "Merge with safe nearby graph points" is
  // selected, a dashed preview line hints which existing point each new
  // draft point would likely auto-connect to on save. This is only a
  // client-side hint (nearest active point within a smaller-than-backend
  // radius) — the backend remains the real authority and additionally
  // checks walls/existing connections, so the actual saved result can
  // legitimately differ.
  const nearbyMergePreview = useMemo(() => {
    if (mode !== 'draw' || mergeMode !== 'nearby') return [];

    return computeNearbyMergePreview({
      draftPoints,
      routePoints,
      activeMapId: activeMap?.id,
      drawFloor,
    });
  }, [mode, mergeMode, draftPoints, routePoints, activeMap, drawFloor]);

  // STEP 8 pre-save draft summary: New points / Existing points reused /
  // Planned new edges / Existing edges reused-skipped, computed live from
  // the same pure helpers Save Path itself uses, so the preview can never
  // drift out of sync with what Save Path will actually do. Placeholder
  // ids stand in for not-yet-created points — buildEdgePlan only treats
  // two ids as an existing duplicate when both are real saved ids, so this
  // never over- or under-counts skipped edges.
  const draftSummary = useMemo(() => {
    if (draftPoints.length < 2) return null;

    const { reuses, creates } = partitionDraftForSave(draftPoints);
    const previewIds = draftPoints.map((point, index) =>
      point.kind === 'existing' ? point.routePointId : `__draft_new_${index}__`,
    );
    const edgePlan = buildEdgePlan(previewIds, buildEdgeKeySet(routeEdges));

    return {
      newPoints: creates.length,
      reusedPoints: reuses.length,
      plannedEdges: edgePlan.toCreate.length,
      skippedEdges: edgePlan.skippedCount,
    };
  }, [draftPoints, routeEdges]);

  // Save Path must be disabled while any new draft point's name is
  // invalid (empty/whitespace-only, or outside the backend's length
  // bounds) — checked live so the button state and the per-point
  // validation message next to the offending field never disagree.
  const isDraftNamingValid = useMemo(
    () => computeIsDraftNamingValid(draftPoints),
    [draftPoints],
  );

  const POINT_TYPE_COLORS = {
    hallway: '#2f7edb',
    junction: '#8e44ad',
    entrance: '#e6820e',
    room: '#e6820e',
    store: '#e6820e',
    stairs: '#c0392b',
    elevator: '#c0392b',
  };

  const LABELED_POINT_TYPES = new Set(['entrance', 'room', 'store']);
  const VERTICAL_TRANSIT_TYPES = new Set(['stairs', 'elevator']);

  const getPointColor = (pointType) =>
    POINT_TYPE_COLORS[pointType] || '#5f7fa6';

  const getEdgeStyle = (edgeType) => {
    if (VERTICAL_TRANSIT_TYPES.has(edgeType)) {
      return { stroke: '#c0392b', dash: '7 5' };
    }

    return { stroke: '#a9c3e3', dash: undefined };
  };

  // Delete Connection mode must only ever offer an ORDINARY walkway edge
  // for deletion — never a stairs/elevator/escalator/ramp edge and never a
  // VerticalConnector-generated cross-floor transition edge (identified by
  // a non-null connector_id, regardless of edge_type). Those must be
  // managed exclusively from Vertical Connections (Section 7 of this
  // feature's spec) so this mode can never silently break a floor
  // transition. edge_type !== 'walkway' alone already covers every legacy
  // manually-created stairs/elevator edge too, not just connector-owned
  // ones.
  const isVerticalConnectorEdge = (edge) =>
    Boolean(edge) && (edge.edge_type !== 'walkway' || Boolean(edge.connector_id));

  // Real-edge-identity click handler for the invisible wide hit-stroke
  // rendered over every edge while in 'delete-connection' mode (see the SVG
  // overlay below). Never resolves "which edge" from coordinates/proximity
  // — the real RouteEdge object is passed in directly from resolvedEdges,
  // the exact same data already used to draw the visible line.
  const handleEdgeClickForDeletion = (edge, fromPoint, toPoint, event) => {
    if (mode !== 'delete-connection') {
      return;
    }

    if (event) {
      event.stopPropagation();
    }

    if (isPanelDraggingRef.current) {
      return;
    }

    if (isVerticalConnectorEdge(edge)) {
      setSelectedEdgeForDeletion(null);
      setDeleteConnectionVerticalNotice(true);
      return;
    }

    setDeleteConnectionVerticalNotice(false);
    setDeleteConnectionError('');
    setSelectedEdgeForDeletion({ edge, fromPoint, toPoint });
  };

  const handleCancelDeleteConnectionSelection = () => {
    if (isDeletingConnection) {
      return;
    }

    setSelectedEdgeForDeletion(null);
    setDeleteConnectionError('');
  };

  // Fully exits delete-connection mode, exactly like handleCancelDraw does
  // for Draw Walkable Path — switching back to 'point' mode restores every
  // normal map interaction (Add Point, marker clicks, etc.) with no
  // separate "restore" step needed, since every other mode's own toolbar
  // handler already resets its own state when (re)entering it.
  const handleCancelDeleteConnectionMode = () => {
    setMode('point');
    setSelectedEdgeForDeletion(null);
    setDeleteConnectionVerticalNotice(false);
    setDeleteConnectionError('');
  };

  // On confirmation: calls the existing, already-admin-protected RouteEdge
  // delete endpoint with the real selected edge's id, waits for success,
  // then refreshes this map's edges (never optimistic-removes the line) so
  // the rendered graph always reflects the backend's real, current state.
  // Both RoutePoints are never referenced here at all — only the RouteEdge
  // id is ever sent.
  const handleConfirmDeleteConnection = async () => {
    if (!selectedEdgeForDeletion?.edge) {
      return;
    }

    const edgeId =
      selectedEdgeForDeletion.edge.id || selectedEdgeForDeletion.edge._id;

    if (!edgeId) {
      setDeleteConnectionError(t.deleteConnectionFailed);
      return;
    }

    setIsDeletingConnection(true);
    setDeleteConnectionError('');

    try {
      await deleteRouteEdge(edgeId);

      setSelectedEdgeForDeletion(null);
      setDeleteConnectionVerticalNotice(false);
      setMode('point');

      // Refresh from the backend rather than locally filtering routeEdges —
      // this is the same "never optimistically mutate, always reload the
      // real graph" pattern Draw Walkable Path's own save already uses.
      await refreshRouteGraph(activeMap?.id);

      alert(t.deleteConnectionSuccess);
    } catch (error) {
      console.error('Failed to delete route edge:', error);
      // error.message is always either the backend's own safe HTTPException
      // detail string (e.g. "Route edge not found") or a generic fetch
      // failure message from apiRequest() — never a raw exception/traceback
      // — so it is safe to surface directly, with a translated fallback.
      setDeleteConnectionError(error.message || t.deleteConnectionFailed);
    } finally {
      setIsDeletingConnection(false);
    }
  };

  // ── Auto Connect Destinations to Corridors handlers ─────────────────────

  const AUTO_CONNECT_TRANSIT_TYPES = new Set(['hallway', 'junction']);

  // Corridor point_type filtering fix: maps each distinct backend
  // `reason` code to its own translated label, instead of always showing
  // the generic "No corridor point found" line regardless of why. Falls
  // back to the generic label for reason values this build doesn't
  // recognize (e.g. an older/newer backend), never to a blank string.
  const getAutoConnectReasonLabel = (reason) => {
    switch (reason) {
      case 'no_transit_points_on_map':
        return t.autoConnectReasonNoTransitPoints;
      case 'transit_points_not_connected_by_edges':
        return t.autoConnectReasonTransitNotConnected;
      case 'no_transit_point_within_range':
        return t.autoConnectReasonTooFar;
      case 'blocked_by_wall':
        return t.autoConnectReasonBlockedByWall;
      case 'corridor_candidate_isolated':
        return t.autoConnectReasonCorridorIsolated;
      case 'nested_parent_not_pass_through':
        return t.autoConnectReasonNestedParentNotPassThrough;
      case 'nested_parent_no_point':
        return t.autoConnectReasonNestedParentNoPoint;
      // Kept for proposals produced by an older backend build.
      case 'nested_parent_not_ready':
        return t.autoConnectReasonNestedParentNotReady;
      default:
        return t.autoConnectNoCorridorPointFound;
    }
  };

  // A candidate's stable identity. Corridor NODES are identified by their
  // RoutePoint id; a corridor EDGE attachment has no point yet (applying
  // it is what creates the junction), so the backend supplies
  // "edge:<edge_id>" instead. Falls back to point_id so a response from an
  // older backend, which had no candidate_key at all, still selects.
  const autoConnectCandidateKey = (candidate) =>
    candidate?.candidate_key || candidate?.point_id || null;

  // Per-room diagnostics for the review panel: exactly what happened to
  // this destination, so a failure is diagnosable without reading server
  // logs. Only rows the backend actually reported are rendered — an older
  // backend that sends none of these simply shows nothing extra.
  const renderAutoConnectDiagnostics = (proposal) => {
    const rows = [];

    if (proposal.target_type) {
      rows.push([t.autoConnectTargetTypeLabel, proposal.connection_type || proposal.target_type]);
    }
    if (proposal.clear_line != null) {
      rows.push([t.autoConnectDiagnosticsClearLine, proposal.clear_line ? '\u2713' : '\u2717']);
    }
    if (proposal.graph_connected != null) {
      rows.push([
        t.autoConnectDiagnosticsGraphConnected,
        proposal.graph_connected ? '\u2713' : '\u2717',
      ]);
    }
    if (proposal.nearest_distance_px != null) {
      rows.push([t.autoConnectDiagnosticsNearest, `${proposal.nearest_distance_px}px`]);
    }
    if (proposal.blocked_candidate_count) {
      rows.push([
        t.autoConnectDiagnosticsBlockedCount,
        String(proposal.blocked_candidate_count),
      ]);
    }
    if (proposal.isolated_candidate_count) {
      rows.push([
        t.autoConnectDiagnosticsIsolatedCount,
        String(proposal.isolated_candidate_count),
      ]);
    }
    if (proposal.is_nested_access) {
      if (proposal.nested_parent_room_name) {
        rows.push([t.autoConnectNestedParentLabel, proposal.nested_parent_room_name]);
      }
      if (proposal.parent_pass_through != null) {
        rows.push([
          t.autoConnectDiagnosticsParentPassThrough,
          proposal.parent_pass_through ? '\u2713' : '\u2717',
        ]);
      }
    }

    if (rows.length === 0) return null;

    return (
      <div
        style={{
          marginTop: 6,
          padding: '6px 8px',
          borderRadius: 8,
          background: '#f4f7fc',
          fontSize: 10.5,
          color: '#4a6a8f',
          lineHeight: 1.7,
        }}
      >
        {rows.map(([label, value]) => (
          <div
            key={label}
            style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}
          >
            <span>{label}</span>
            <strong style={{ color: '#173b70' }}>{value}</strong>
          </div>
        ))}
      </div>
    );
  };

  const runAutoConnectPreview = async (scopeOverride) => {
    if (!activeMap?.id) {
      setAutoConnectError(t.noSelectedMap);
      return;
    }

    setAutoConnectPhase('scanning');
    setAutoConnectError('');

    try {
      const response = await previewAutoConnectDestinations({
        map_id: activeMap.id,
        scope: scopeOverride || autoConnectScope,
        lang,
      });

      const proposals = (response.proposals || []).map((proposal) => ({
        ...proposal,
        // Nothing is ever pre-accepted — even a high-confidence proposal
        // requires an explicit admin action (single Accept, or "Accept
        // all high-confidence proposals").
        localStatus: proposal.status === 'proposed' ? 'pending' : 'skipped',
        selectedCandidateKey:
          proposal.proposed_candidate_key || proposal.proposed_candidate_id || null,
      }));

      setAutoConnectSummary(response.summary || null);
      setAutoConnectProposals(proposals);
      setAutoConnectPhase('preview');
    } catch (error) {
      console.error('Auto Connect Destinations preview failed:', error);
      setAutoConnectError(error.message || t.autoConnectPreviewFailed);
      setAutoConnectPhase('preview');
    }
  };

  const handleStartAutoConnect = () => {
    if (mode !== 'auto-connect') {
      setMode('auto-connect');
    }
    setClickedPoint(null);
    setPointName('');
    setAutoConnectError('');
    setAutoConnectApplyResult(null);
    setAutoConnectManualPickTargetId(null);
    runAutoConnectPreview();
  };

  const handleAcceptProposal = (destinationId) => {
    setAutoConnectProposals((previous) =>
      previous.map((proposal) =>
        proposal.destination_point_id === destinationId
          ? { ...proposal, localStatus: 'accepted' }
          : proposal,
      ),
    );
  };

  const handleRejectProposal = (destinationId) => {
    setAutoConnectProposals((previous) =>
      previous.map((proposal) =>
        proposal.destination_point_id === destinationId
          ? { ...proposal, localStatus: 'rejected' }
          : proposal,
      ),
    );
  };

  const handleSelectAlternativeCandidate = (destinationId, candidateKey) => {
    setAutoConnectProposals((previous) =>
      previous.map((proposal) =>
        proposal.destination_point_id === destinationId
          ? { ...proposal, selectedCandidateKey: candidateKey }
          : proposal,
      ),
    );
  };

  const handleAcceptAllHighConfidence = () => {
    setAutoConnectProposals((previous) =>
      previous.map((proposal) =>
        proposal.status === 'proposed' && proposal.confidence === 'high'
          ? { ...proposal, localStatus: 'accepted' }
          : proposal,
      ),
    );
  };

  const handleRejectAllLowConfidence = () => {
    setAutoConnectProposals((previous) =>
      previous.map((proposal) =>
        proposal.status === 'proposed' &&
        (proposal.confidence === 'low' || proposal.confidence === 'needs_review')
          ? { ...proposal, localStatus: 'rejected' }
          : proposal,
      ),
    );
  };

  const handleStartManualCorridorPick = (destinationId) => {
    setAutoConnectManualPickTargetId(destinationId);
  };

  const handleCancelManualCorridorPick = () => {
    setAutoConnectManualPickTargetId(null);
  };

  // Called directly from a RoutePoint marker's own onClick while a manual
  // pick is pending (see the routePoints.map() marker render below) — the
  // real clicked RoutePoint object is passed in, never re-derived from
  // coordinates. Silently ignores a click on anything that isn't a valid
  // transit-type point, exactly like the backend's own apply-time
  // revalidation would reject it anyway.
  const selectManualCorridorPoint = (point) => {
    if (!autoConnectManualPickTargetId) {
      return;
    }

    if (!AUTO_CONNECT_TRANSIT_TYPES.has(point.point_type)) {
      return;
    }

    const pointId = point.id || point._id;

    setAutoConnectProposals((previous) =>
      previous.map((proposal) =>
        proposal.destination_point_id === autoConnectManualPickTargetId
          ? {
              ...proposal,
              // A manually picked corridor point is always an existing
              // RoutePoint, so its id doubles as its candidate key.
              selectedCandidateKey: pointId,
              manualCandidateName: point.name,
              localStatus: 'accepted',
            }
          : proposal,
      ),
    );

    setAutoConnectManualPickTargetId(null);
  };

  const handleCancelAutoConnect = () => {
    setMode('point');
    setAutoConnectPhase('idle');
    setAutoConnectProposals([]);
    setAutoConnectSummary(null);
    setAutoConnectError('');
    setAutoConnectManualPickTargetId(null);
    setAutoConnectApplyResult(null);
  };

  const handleOpenAutoConnectConfirm = () => {
    setAutoConnectError('');
    setAutoConnectPhase('confirming');
  };

  const handleBackToAutoConnectPreview = () => {
    setAutoConnectPhase('preview');
  };

  // On confirmation: sends ONLY the explicitly accepted pairs to the apply
  // endpoint, which independently revalidates every one of them from a
  // fresh database read (never trusts this preview state as-is).
  const handleConfirmAutoConnectApply = async () => {
    const accepted = autoConnectProposals
      .filter(
        (proposal) =>
          proposal.localStatus === 'accepted' && proposal.selectedCandidateKey,
      )
      .map((proposal) => {
        const candidate = (proposal.candidates || []).find(
          (entry) => autoConnectCandidateKey(entry) === proposal.selectedCandidateKey,
        );

        // Attaching partway along a corridor edge: the backend creates the
        // junction at these coordinates, splits the edge through it, and
        // connects the destination to it. Everything else — including a
        // manually picked corridor point, which is never in `candidates` —
        // is an ordinary existing-point pair.
        if (candidate?.target_type === 'corridor_edge' && candidate.corridor_edge_id) {
          return {
            destination_point_id: proposal.destination_point_id,
            corridor_edge_id: candidate.corridor_edge_id,
            attachment_x: candidate.attachment_x,
            attachment_y: candidate.attachment_y,
          };
        }

        return {
          destination_point_id: proposal.destination_point_id,
          corridor_point_id: candidate?.point_id || proposal.selectedCandidateKey,
        };
      })
      .filter(
        (pair) => Boolean(pair.corridor_point_id) || Boolean(pair.corridor_edge_id),
      );

    if (accepted.length === 0) {
      setAutoConnectError(t.autoConnectNoAccepted);
      return;
    }

    setAutoConnectPhase('applying');
    setAutoConnectError('');

    try {
      const result = await applyAutoConnectDestinations({
        map_id: activeMap.id,
        accepted,
      });

      setAutoConnectApplyResult(result);

      // Refresh RouteEdges (and RoutePoints, via the same reusable loader
      // every other feature on this screen already uses) so the newly
      // created connections appear immediately — every existing
      // RoutePoint is kept exactly as-is, only routeEdges gains the new
      // entries the backend actually created.
      await refreshRouteGraph(activeMap.id);

      setAutoConnectPhase('result');
      setMode('point');
    } catch (error) {
      console.error('Auto Connect Destinations apply failed:', error);
      setAutoConnectError(error.message || t.autoConnectApplyFailed);
      setAutoConnectPhase('confirming');
    }
  };

  const handleCloseAutoConnectResult = () => {
    setAutoConnectPhase('idle');
    setAutoConnectProposals([]);
    setAutoConnectSummary(null);
    setAutoConnectApplyResult(null);
  };

  // ── Create Destinations from Approved Analysis handlers ─────────────────
  // (Approved Semantic Analysis -> Automatic Destinations and Nested-Room
  // Navigation spec.) Same preview/review/confirm/result pattern already
  // established above for Auto Connect Destinations.

  const runSemanticDestPreview = async () => {
    if (!activeMap?.id) {
      setSemanticDestError(t.noSelectedMap);
      return;
    }

    setSemanticDestPhase('scanning');
    setSemanticDestError('');

    try {
      const response = await previewSemanticDestinations(activeMap.id, { lang });

      const proposals = (response.proposals || []).map((proposal) => ({
        ...proposal,
        // Nothing is ever pre-accepted, exactly like Auto Connect
        // Destinations — even an exact existing-point reuse still
        // requires an explicit admin Accept.
        localStatus: proposal.excluded ? 'excluded' : 'pending',
        x: proposal.proposed_x ?? null,
        y: proposal.proposed_y ?? null,
        // Nested confirmation always starts unchecked (Section 10: "Do
        // not enable pass-through without explicit admin confirmation").
        confirmNested: false,
        allowTransitThrough: false,
      }));

      setSemanticDestSummary(response.summary || null);
      setSemanticDestPublicationId(response.publication_id || null);
      setSemanticDestProposals(proposals);
      setSemanticDestPhase('preview');

      // Ask, separately and non-fatally, whether the map's own printed
      // labels can supply the locations these proposals are missing. A
      // failure here must never break the preview the admin just asked
      // for — it only means every destination is placed by hand, which
      // is exactly the behavior that existed before this feature.
      try {
        const autoPlacement = await previewDestinationAutoPlacement(activeMap.id, { lang });
        setSemanticAutoPlacement(autoPlacement || null);
      } catch (autoPlacementError) {
        console.error('Automatic destination placement preview failed:', autoPlacementError);
        setSemanticAutoPlacement(null);
      }
    } catch (error) {
      console.error('Create Destinations from Approved Analysis preview failed:', error);
      setSemanticDestError(error.message || t.semanticDestPreviewFailed);
      setSemanticDestPhase('preview');
    }
  };

  const handleStartSemanticDestinations = () => {
    if (mode !== 'semantic-destinations') {
      setMode('semantic-destinations');
    }
    setClickedPoint(null);
    setPointName('');
    setSemanticDestError('');
    setSemanticDestApplyResult(null);
    setSemanticDestManualPlaceTargetId(null);
    runSemanticDestPreview();
  };

  const handleAcceptSemanticProposal = (itemId) => {
    setSemanticDestProposals((previous) =>
      previous.map((proposal) =>
        proposal.semantic_item_id === itemId
          ? { ...proposal, localStatus: 'accepted' }
          : proposal,
      ),
    );
  };

  const handleRejectSemanticProposal = (itemId) => {
    setSemanticDestProposals((previous) =>
      previous.map((proposal) =>
        proposal.semantic_item_id === itemId
          ? { ...proposal, localStatus: 'rejected' }
          : proposal,
      ),
    );
  };

  const handleStartManualSemanticPlacement = (itemId) => {
    setSemanticDestManualPlaceTargetId(itemId);
  };

  const handleCancelManualSemanticPlacement = () => {
    setSemanticDestManualPlaceTargetId(null);
  };

  const handleToggleSemanticNested = (itemId, confirmed) => {
    setSemanticDestProposals((previous) =>
      previous.map((proposal) =>
        proposal.semantic_item_id === itemId
          ? { ...proposal, confirmNested: confirmed }
          : proposal,
      ),
    );
  };

  const handleToggleSemanticAllowTransit = (itemId, allowed) => {
    setSemanticDestProposals((previous) =>
      previous.map((proposal) =>
        proposal.semantic_item_id === itemId
          ? { ...proposal, allowTransitThrough: allowed }
          : proposal,
      ),
    );
  };

  const handleCancelSemanticDestinations = () => {
    setMode('point');
    setSemanticDestPhase('idle');
    setSemanticDestProposals([]);
    setSemanticDestSummary(null);
    setSemanticDestError('');
    setSemanticDestManualPlaceTargetId(null);
    setSemanticDestApplyResult(null);
  };

  const handleOpenSemanticDestConfirm = () => {
    setSemanticDestError('');
    setSemanticDestPhase('confirming');
  };

  const handleBackToSemanticDestPreview = () => {
    setSemanticDestPhase('preview');
  };

  // On confirmation: sends ONLY the explicitly accepted items, each with
  // its admin-reviewed coordinates and explicit nested/pass-through
  // confirmations — the apply endpoint independently revalidates every
  // one of them from a fresh database read (never trusts this preview
  // state as-is).
  const handleConfirmSemanticDestApply = async () => {
    const accepted = semanticDestProposals
      .filter((proposal) => proposal.localStatus === 'accepted')
      .map((proposal) => ({
        semantic_item_id: proposal.semantic_item_id,
        entity_kind: proposal.entity_kind,
        x: proposal.x,
        y: proposal.y,
        parent_semantic_item_id:
          proposal.confirmNested && proposal.nested_parent_candidate
            ? proposal.nested_parent_candidate.semantic_item_id
            : null,
        allow_transit_through: Boolean(proposal.allowTransitThrough),
      }));

    if (accepted.length === 0) {
      setSemanticDestError(t.semanticDestNoAccepted);
      return;
    }

    setSemanticDestPhase('applying');
    setSemanticDestError('');

    try {
      const result = await applySemanticDestinations(activeMap.id, {
        publicationId: semanticDestPublicationId,
        accepted,
      });

      setSemanticDestApplyResult(result);

      // Refresh Rooms/RoutePoints/RouteEdges (Section 19: "Refresh Rooms,
      // RoutePoints and RouteEdges after success") via the same reusable
      // loader every other feature on this screen already uses.
      await refreshRouteGraph(activeMap.id);

      setSemanticDestPhase('result');
      setMode('point');
    } catch (error) {
      console.error('Create Destinations from Approved Analysis apply failed:', error);
      setSemanticDestError(error.message || t.semanticDestApplyFailed);
      setSemanticDestPhase('confirming');
    }
  };

  const handleCloseSemanticDestResult = () => {
    setSemanticDestPhase('idle');
    setSemanticDestProposals([]);
    setSemanticDestSummary(null);
    setSemanticDestApplyResult(null);
    setSemanticAutoPlacement(null);
  };

  // ── Fast batch destination placement ("Place All Destinations") ────────

  // ── Floating "Navigation Tools" toolbox ───────────────────────────────
  // UI preference only. The storage key and reader live at MODULE scope
  // (above this component) rather than in the component body: they hold
  // no state, and syncFullMapMetrics — defined far earlier — calls the
  // reader. Keeping them out here means that call can never depend on how
  // far through the component body evaluation has got.

  useEffect(() => {
    const stored = readStoredToolboxState();
    if (stored && typeof stored.collapsed === 'boolean') {
      setToolboxCollapsed(stored.collapsed);
    }
  }, []);

  useEffect(() => {
    if (!isMapOpen || !toolboxPosition) return;

    try {
      window.localStorage.setItem(
        TOOLBOX_STORAGE_KEY,
        JSON.stringify({
          position: toolboxPosition,
          collapsed: toolboxCollapsed,
        }),
      );
    } catch {
      // Storage unavailable (private mode, quota, disabled). The toolbox
      // simply starts from its default next time.
    }
  }, [isMapOpen, toolboxPosition, toolboxCollapsed]);

  // ── Converted floating map panels ─────────────────────────────────────
  //
  // Everything below drives ONLY the five panels that used to be fixed
  // absolutely-positioned boxes: Preview Destinations, the Auto Connect
  // preview, the fast-batch review screen, the Automatic Navigation Build
  // preview, and the Edit Route Point detail panel.
  //
  // Add Point, Draw Walkable Path, Vertical Connections, Test Route and
  // the fast-batch sequential placement panel are NOT touched by any of
  // it — they keep sharing `panelPosition` / `isPanelCollapsed` and never
  // get an entry in `mapPanels`.

  const visibleMapPanelIds = useMemo(() => {
    const ids = [];

    if (mode === 'auto-connect' && autoConnectPhase === 'preview') {
      ids.push(MAP_PANEL_IDS.autoConnectPreview);
    }
    if (mode === 'semantic-destinations' && semanticDestPhase === 'preview') {
      ids.push(MAP_PANEL_IDS.semanticDestPreview);
    }
    if (
      mode === 'semantic-destinations' &&
      semanticBatchActive &&
      semanticBatchReviewOpen
    ) {
      ids.push(MAP_PANEL_IDS.semanticBatchReview);
    }
    if (navBuildOpen) {
      ids.push(MAP_PANEL_IDS.navBuild);
    }
    if (mode === 'edit-points' && editPointTarget) {
      ids.push(MAP_PANEL_IDS.editPoint);
    }

    return ids;
  }, [
    mode,
    autoConnectPhase,
    semanticDestPhase,
    semanticBatchActive,
    semanticBatchReviewOpen,
    navBuildOpen,
    editPointTarget,
  ]);

  // Give each panel its starting position the first time it becomes
  // visible in this full-map session — restored from its own localStorage
  // key when one exists, otherwise from the default-position table. The
  // panel renders only once its entry exists (one frame later), which is
  // the same `panelPosition &&` gate the pre-existing panels already use.
  useEffect(() => {
    if (!isMapOpen || visibleMapPanelIds.length === 0) return;

    const workspace = fullMapWorkspaceRef.current;
    if (!workspace) return;

    const rect = workspace.getBoundingClientRect();
    if (!rect.width || !rect.height) return;

    setMapPanels((previous) => {
      let next = previous;

      visibleMapPanelIds.forEach((panelId) => {
        if (next[panelId]) return;
        if (next === previous) next = { ...previous };

        next[panelId] = createInitialMapPanelState({
          panelId,
          containerWidth: rect.width,
          containerHeight: rect.height,
          isRTL,
        });
      });

      return next;
    });
  }, [isMapOpen, visibleMapPanelIds, isRTL, fullMapMetrics]);

  // Persist each panel's own position/collapsed state under its own key.
  useEffect(() => {
    if (!isMapOpen) return;

    Object.keys(mapPanels).forEach((panelId) => {
      const entry = mapPanels[panelId];
      if (!entry?.position) return;

      writeStoredMapPanelState(panelId, {
        position: entry.position,
        collapsed: entry.collapsed === true,
      });
    });
  }, [isMapOpen, mapPanels]);

  // Closing the full-map view clears the in-memory entries so the next
  // open re-reads localStorage and re-clamps against the (possibly
  // resized) workspace. Saved positions themselves are not cleared.
  useEffect(() => {
    if (!isMapOpen) setMapPanels({});
  }, [isMapOpen]);

  const handleMapPanelPositionChange = useCallback((panelId, position) => {
    setMapPanels((previous) => {
      const entry = previous[panelId];
      if (!entry) return previous;
      if (
        entry.position?.x === position?.x &&
        entry.position?.y === position?.y
      ) {
        return previous;
      }
      return { ...previous, [panelId]: { ...entry, position } };
    });
  }, []);

  const handleMapPanelToggleCollapse = useCallback((panelId) => {
    setMapPanels((previous) => {
      const entry = previous[panelId];
      if (!entry) return previous;
      return {
        ...previous,
        [panelId]: { ...entry, collapsed: !entry.collapsed },
      };
    });
  }, []);

  const handleMapPanelFocus = useCallback((panelId) => {
    // raiseMapPanel returns the same object when the panel is already
    // frontmost, so this is a no-op re-render-wise for the common case of
    // clicking around inside the panel you are already using.
    setMapPanels((previous) => raiseMapPanel(previous, panelId));
  }, []);

  // Every converted panel takes the same set of FloatingToolPanel props.
  // Building them in one place keeps the five call sites identical and
  // makes it impossible to wire one of them up inconsistently. Returns
  // null until the panel's entry exists, which is what gates its render.
  const buildMapPanelProps = useCallback(
    (panelId) => {
      const entry = mapPanels[panelId];
      if (!entry?.position) return null;

      return {
        position: entry.position,
        onPositionChange: (position) =>
          handleMapPanelPositionChange(panelId, position),
        isCollapsed: entry.collapsed === true,
        onToggleCollapse: () => handleMapPanelToggleCollapse(panelId),
        onFocusRequest: () => handleMapPanelFocus(panelId),
        // Same drag guard the pre-existing panels use, so a drag that
        // ends over the map never also registers as a map click.
        onDragStateChange: (dragging) => {
          isPanelDraggingRef.current = dragging;
        },
        zIndex: entry.zIndex,
        width: getMapPanelWidth(panelId),
        containerRef: fullMapWorkspaceRef,
        snapTopOffset: 76,
        isRTL,
        showSnapControls: true,
        moveLabel: t.panelMove,
        minimizeLabel: t.panelMinimize,
        restoreLabel: t.panelRestore,
        snapLabels: {
          left: t.panelDockLeft,
          right: t.panelDockRight,
          bottom: t.panelDockBottom,
        },
      };
    },
    [
      mapPanels,
      handleMapPanelPositionChange,
      handleMapPanelToggleCollapse,
      handleMapPanelFocus,
      isRTL,
      t,
    ],
  );


  // ── Automatic Navigation Build (Phase A, read-only) ───────────────────

  const handleToggleNavBuildLayer = (key) => {
    setNavBuildLayers((previous) => ({ ...previous, [key]: !previous[key] }));
  };

  const handleRunNavBuildPreview = async () => {
    if (!activeMap?.id) {
      setNavBuildError(t.noSelectedMap);
      return;
    }

    setNavBuildLoading(true);
    setNavBuildError('');

    try {
      const response = await previewNavigationBuild(activeMap.id, { lang });
      setNavBuildResult(response);
    } catch (error) {
      console.error('Automatic navigation build preview failed:', error);
      setNavBuildError(error.message || t.navBuildFailed);
      setNavBuildResult(null);
    } finally {
      setNavBuildLoading(false);
    }
  };

  const handleOpenNavBuild = () => {
    setNavBuildOpen(true);
    setNavBuildError('');
  };

  const handleCloseNavBuild = () => {
    setNavBuildOpen(false);
    setNavBuildResult(null);
    setNavBuildError('');
  };

  // Declared HERE, after every handler it references, and not earlier.
  // This array is built during render, so a `const` arrow handler defined
  // further down the component body is still in its temporal dead zone at
  // that moment — reading it throws "Cannot access ... before
  // initialization" and the whole Admin Map renders blank. Of the five
  // handlers used below (closeEditPointPanel, resetCalibrationPoints,
  // handleStartAutoConnect, handleStartSemanticDestinations,
  // handleOpenNavBuild), handleOpenNavBuild was the one declared after
  // the old position. Keeping the array below all of them makes the
  // ordering safe rather than coincidental.
  // The tools themselves. Each entry carries the EXACT onClick and the
  // EXACT active-state expression the old horizontal bar used, so this is
  // a pure regrouping — no handler is rewritten, wrapped or conditioned
  // differently. `tooltip` keeps the full original wording for the few
  // labels shortened to fit a 268px panel.
  const mapToolGroups = [
    {
      id: 'draw',
      title: t.toolboxGroupDraw,
      tools: [
        {
          id: 'point',
          icon: 'point',
          label: t.addPointMode,
          active: mode === 'point',
          onClick: () => {
            if (mode !== 'point') {
              setMode('point');
              setDraftPoints([]);
              setDraftError('');
            }
          },
        },
        {
          id: 'draw',
          icon: 'path',
          label: t.drawMode,
          active: mode === 'draw',
          onClick: () => {
            if (mode !== 'draw') {
              setMode('draw');
              setClickedPoint(null);
              setPointName('');
            }
          },
        },
      ],
    },
    {
      id: 'routing',
      title: t.toolboxGroupRouting,
      tools: [
        {
          id: 'test',
          icon: 'test',
          label: t.testMode,
          active: mode === 'test',
          onClick: () => {
            if (mode !== 'test') {
              setMode('test');
              setClickedPoint(null);
              setPointName('');
            }
          },
        },
        {
          id: 'connector',
          icon: 'connector',
          label: t.connectorMode || 'Vertical Connections',
          active: mode === 'connector',
          onClick: () => {
            if (mode !== 'connector') {
              setMode('connector');
              setClickedPoint(null);
              setPointName('');
              setConnectorPendingClick(null);
            }
          },
        },
        {
          id: 'auto-connect',
          icon: 'autoConnect',
          label: t.autoConnectMode,
          active: mode === 'auto-connect',
          onClick: () => {
            if (mode !== 'auto-connect') {
              handleStartAutoConnect();
            }
          },
        },
      ],
    },
    {
      id: 'destinations',
      title: t.toolboxGroupDestinations,
      tools: [
        {
          id: 'semantic-destinations',
          icon: 'destinations',
          label: t.semanticDestModeShort || t.semanticDestMode,
          tooltip: t.semanticDestMode,
          active: mode === 'semantic-destinations',
          onClick: () => {
            if (mode !== 'semantic-destinations') {
              handleStartSemanticDestinations();
            }
          },
        },
        {
          id: 'sync-rooms',
          icon: 'sync',
          label: t.syncRoomsActionShort || t.syncRoomsAction,
          tooltip: t.syncRoomsAction,
          active: false,
          onClick: () => {
            setSyncRoomsError('');
            setShowSyncRoomsConfirm(true);
          },
        },
      ],
    },
    {
      id: 'editing',
      title: t.toolboxGroupEditing,
      tools: [
        {
          id: 'edit-points',
          icon: 'edit',
          label: t.editPointsMode,
          active: mode === 'edit-points',
          onClick: () => {
            if (mode !== 'edit-points') {
              setMode('edit-points');
              setClickedPoint(null);
              setPointName('');
              closeEditPointPanel();
            }
          },
        },
        {
          id: 'delete-connection',
          icon: 'deleteEdge',
          label: t.deleteConnectionMode,
          active: mode === 'delete-connection',
          onClick: () => {
            if (mode !== 'delete-connection') {
              setMode('delete-connection');
              setClickedPoint(null);
              setPointName('');
              setSelectedEdgeForDeletion(null);
              setDeleteConnectionVerticalNotice(false);
              setDeleteConnectionError('');
            }
          },
        },
        {
          id: 'calibrate',
          icon: 'calibrate',
          label: t.calibrateMode,
          active: mode === 'calibrate',
          onClick: () => {
            if (mode !== 'calibrate') {
              setMode('calibrate');
              setClickedPoint(null);
              setPointName('');
              resetCalibrationPoints();
              setCalibrationResult(null);
            }
          },
        },
      ],
    },
    {
      id: 'automation',
      title: t.toolboxGroupAutomation,
      tools: [
        {
          id: 'nav-build',
          icon: 'build',
          label: t.navBuildModeShort || t.navBuildMode,
          tooltip: t.navBuildMode,
          active: navBuildOpen,
          onClick: handleOpenNavBuild,
        },
      ],
    },
  ];

  // Why the map's own labels could not answer for one room. Kept as
  // plain, non-technical reasons: the admin's next action is the same in
  // every case (click the right spot), so the wording only has to explain
  // why they are being asked.
  const describeAutoPlacementStatus = (status) => {
    if (status === 'no_label_match') return t.semanticAutoPlaceReasonNoLabelMatch;
    if (status === 'ambiguous_label') return t.semanticAutoPlaceReasonAmbiguous;
    if (status === 'no_safe_graph_connection') return t.semanticAutoPlaceReasonNoConnection;
    return t.semanticAutoPlaceReasonNeedsConfirmation;
  };

  const getSemanticBatchDraftKey = () =>
    buildBatchDraftStorageKey({
      mapId: activeMap?.id,
      publicationId: semanticDestPublicationId,
      adminId: user?.id || user?.email,
    });

  const handleBeginFreshSemanticBatch = () => {
    const queueItemIds = buildBatchQueueItemIds(semanticDestProposals);

    // Locations the map's own labels already justify (see
    // semanticAutoPlacement above). These items still enter the queue and
    // still show their marker — they just start already placed, so the
    // admin walks only the rooms the drawing could not answer for.
    const autoPlacementSuggestions = indexAutoPlacementSuggestions(
      semanticAutoPlacement?.proposals,
    );

    // Existing-linked-point proposals (Section 8: "do not require a new
    // location unless the admin explicitly chooses to replace it") are
    // auto-included in the final save without ever entering the queue.
    setSemanticDestProposals((previous) =>
      applyAutoPlacementSuggestions(
        previous.map((proposal) =>
          proposal.placement_source !== 'needs_manual_placement' &&
          proposal.localStatus !== 'rejected' &&
          proposal.localStatus !== 'excluded'
            ? { ...proposal, localStatus: 'accepted' }
            : proposal,
        ),
        autoPlacementSuggestions,
      ),
    );

    const statuses = initialBatchStatuses(
      queueItemIds,
      queueItemIds.filter((id) => autoPlacementSuggestions[id]),
    );
    // Start on the first item that still needs a click, not blindly on
    // item 0 — which may well already be placed from its label.
    const firstUnresolved = findNextActiveIndex(queueItemIds, statuses, -1);

    setSemanticBatchQueue(queueItemIds);
    setSemanticBatchStatuses(statuses);
    setSemanticBatchIndex(firstUnresolved === -1 ? 0 : firstUnresolved);
    setSemanticBatchHistory([]);
    setSemanticBatchFeedback('');
    setSemanticBatchAwaitingReplace(false);
    setSemanticBatchReviewOpen(queueItemIds.length > 0 && firstUnresolved === -1);
    setSemanticBatchItemErrors({});
    setSemanticBatchSaveError('');
    setSemanticBatchDraftPrompt(null);
    setSemanticBatchActive(true);
  };

  // Entry point for the "Place All Destinations" action (Section 1).
  // Checks for a resumable local draft (Section 9) before starting fresh.
  const handleStartSemanticBatchPlacement = () => {
    let existingDraft = null;
    try {
      existingDraft = deserializeBatchDraft(
        window.localStorage.getItem(getSemanticBatchDraftKey()),
      );
    } catch {
      existingDraft = null;
    }

    if (existingDraft && existingDraft.queueItemIds?.length) {
      setSemanticBatchDraftPrompt(existingDraft);
      return;
    }

    handleBeginFreshSemanticBatch();
  };

  const handleResumeSemanticBatchDraft = () => {
    const draft = semanticBatchDraftPrompt;
    if (!draft) return;

    // Re-applies the draft's remembered coordinates/status onto the
    // CURRENT (freshly re-fetched) proposals — never trusts stale
    // proposal data from before the page reload, only the x/y + status
    // the admin actually chose.
    setSemanticDestProposals((previous) =>
      previous.map((proposal) => {
        const placement = draft.placements?.[proposal.semantic_item_id];
        const status = draft.statuses?.[proposal.semantic_item_id];
        if (!placement && !status) return proposal;
        return {
          ...proposal,
          ...(placement ? { x: placement.x, y: placement.y } : {}),
          ...(status === 'placed' ? { localStatus: 'accepted' } : {}),
          ...(status === 'rejected' ? { localStatus: 'rejected' } : {}),
        };
      }),
    );

    const statuses = draft.statuses || initialBatchStatuses(draft.queueItemIds);
    setSemanticBatchQueue(draft.queueItemIds);
    setSemanticBatchStatuses(statuses);
    const resumeIndex = findNextActiveIndex(draft.queueItemIds, statuses, -1);
    setSemanticBatchIndex(resumeIndex === -1 ? 0 : resumeIndex);
    setSemanticBatchHistory([]);
    setSemanticBatchFeedback('');
    setSemanticBatchAwaitingReplace(false);
    setSemanticBatchReviewOpen(resumeIndex === -1);
    setSemanticBatchItemErrors({});
    setSemanticBatchSaveError('');
    setSemanticBatchDraftPrompt(null);
    setSemanticBatchActive(true);
  };

  const handleDiscardSemanticBatchDraft = () => {
    try {
      window.localStorage.removeItem(getSemanticBatchDraftKey());
    } catch {
      // Discarding is still effectively true in-memory even if the
      // underlying storage write fails — semanticBatchDraftPrompt is
      // cleared by handleBeginFreshSemanticBatch below either way.
    }
    handleBeginFreshSemanticBatch();
  };

  // The core placement interaction (Section 2/3): a valid map click
  // while batch mode is active assigns x/y to the CURRENT active queue
  // item and auto-advances — no separate Accept/OK/Next click required.
  const handleBatchDestinationMapClick = (x, y) => {
    const activeItemId = semanticBatchQueue[semanticBatchIndex];
    if (!activeItemId) return;

    const currentStatus = semanticBatchStatuses[activeItemId];
    // Revisiting an already-placed item (e.g. via Previous) never
    // silently overwrites it — only explicit "Change location" arms this.
    if (currentStatus === 'placed' && !semanticBatchAwaitingReplace) {
      return;
    }

    const proposal = semanticDestProposals.find(
      (candidate) => candidate.semantic_item_id === activeItemId,
    );

    setSemanticBatchHistory((previous) => [
      ...previous,
      {
        itemId: activeItemId,
        prevStatus: currentStatus,
        prevX: proposal?.x ?? null,
        prevY: proposal?.y ?? null,
      },
    ]);

    setSemanticDestProposals((previous) =>
      previous.map((candidate) =>
        candidate.semantic_item_id === activeItemId
          ? { ...candidate, x, y, localStatus: 'accepted' }
          : candidate,
      ),
    );

    const nextStatuses = { ...semanticBatchStatuses, [activeItemId]: 'placed' };
    setSemanticBatchStatuses(nextStatuses);
    setSemanticBatchAwaitingReplace(false);
    setSemanticBatchFeedback(
      t.semanticBatchLocationSelected(
        proposal?.name_en || proposal?.name_original || activeItemId,
      ),
    );

    const nextIndex = findNextActiveIndex(semanticBatchQueue, nextStatuses, semanticBatchIndex);
    if (nextIndex === -1) {
      setSemanticBatchReviewOpen(true);
    } else {
      setSemanticBatchIndex(nextIndex);
    }
  };

  const handleBatchSkip = () => {
    const activeItemId = semanticBatchQueue[semanticBatchIndex];
    if (!activeItemId) return;
    const nextStatuses = { ...semanticBatchStatuses, [activeItemId]: 'skipped' };
    setSemanticBatchStatuses(nextStatuses);
    setSemanticBatchFeedback('');
    const nextIndex = findNextActiveIndex(semanticBatchQueue, nextStatuses, semanticBatchIndex);
    if (nextIndex === -1) {
      setSemanticBatchReviewOpen(true);
    } else {
      setSemanticBatchIndex(nextIndex);
    }
  };

  const handleBatchReject = () => {
    const activeItemId = semanticBatchQueue[semanticBatchIndex];
    if (!activeItemId) return;
    setSemanticDestProposals((previous) =>
      previous.map((candidate) =>
        candidate.semantic_item_id === activeItemId
          ? { ...candidate, localStatus: 'rejected' }
          : candidate,
      ),
    );
    const nextStatuses = { ...semanticBatchStatuses, [activeItemId]: 'rejected' };
    setSemanticBatchStatuses(nextStatuses);
    setSemanticBatchFeedback('');
    const nextIndex = findNextActiveIndex(semanticBatchQueue, nextStatuses, semanticBatchIndex);
    if (nextIndex === -1) {
      setSemanticBatchReviewOpen(true);
    } else {
      setSemanticBatchIndex(nextIndex);
    }
  };

  const handleBatchPrevious = () => {
    setSemanticBatchAwaitingReplace(false);
    setSemanticBatchIndex((previous) => Math.max(0, previous - 1));
  };

  const handleBatchChangeLocation = () => {
    setSemanticBatchAwaitingReplace(true);
  };

  const handleBatchUndo = () => {
    if (semanticBatchHistory.length === 0) return;
    const last = semanticBatchHistory[semanticBatchHistory.length - 1];

    setSemanticDestProposals((previous) =>
      previous.map((candidate) =>
        candidate.semantic_item_id === last.itemId
          ? {
              ...candidate,
              x: last.prevX,
              y: last.prevY,
              localStatus:
                last.prevStatus === 'placed' ? 'accepted' : candidate.localStatus,
            }
          : candidate,
      ),
    );
    setSemanticBatchStatuses((previous) => ({
      ...previous,
      [last.itemId]: last.prevStatus,
    }));
    setSemanticBatchHistory((previous) => previous.slice(0, -1));
    setSemanticBatchReviewOpen(false);
    setSemanticBatchAwaitingReplace(false);

    const undoneIndex = semanticBatchQueue.indexOf(last.itemId);
    setSemanticBatchIndex(undoneIndex === -1 ? 0 : undoneIndex);
  };

  const handleRequestExitSemanticBatch = () => {
    const progress = computeBatchProgress(semanticBatchQueue, semanticBatchStatuses);
    if (progress.placed > 0 || progress.rejected > 0 || progress.skipped > 0) {
      setSemanticBatchExitWarningOpen(true);
    } else {
      setSemanticBatchActive(false);
    }
  };

  const handleConfirmExitSemanticBatch = () => {
    setSemanticBatchExitWarningOpen(false);
    setSemanticBatchActive(false);
    setSemanticBatchReviewOpen(false);
  };

  const handleCancelExitSemanticBatch = () => {
    setSemanticBatchExitWarningOpen(false);
  };

  const handleSelectSemanticBatchReviewItem = (itemId) => {
    const index = semanticBatchQueue.indexOf(itemId);
    if (index === -1) return;
    setSemanticBatchIndex(index);
    setSemanticBatchAwaitingReplace(true);
    setSemanticBatchReviewOpen(false);
  };

  const handleOpenSemanticBatchSaveConfirm = () => {
    setSemanticBatchSaveError('');
    setSemanticBatchItemErrors({});
    setSemanticBatchConfirmOpen(true);
  };

  const handleCancelSemanticBatchSaveConfirm = () => {
    setSemanticBatchConfirmOpen(false);
  };

  // The ONE final write for the whole batch (Section 6/7) — reuses the
  // existing apply endpoint with all_or_nothing=true rather than a new
  // endpoint (see services/semantic_destination_service.py). Every
  // non-rejected proposal with a usable location (freshly placed OR an
  // existing linked point) is sent in a single request; the backend
  // validates the entire batch before writing anything.
  const handleSaveAllSemanticBatchDestinations = async () => {
    const accepted = buildBatchAcceptedPayload(semanticDestProposals);

    if (accepted.length === 0) {
      setSemanticBatchSaveError(t.semanticDestNoAccepted);
      return;
    }

    setSemanticBatchSaving(true);
    setSemanticBatchSaveError('');
    setSemanticBatchItemErrors({});

    try {
      const result = await applySemanticDestinations(activeMap.id, {
        publicationId: semanticDestPublicationId,
        accepted,
        allOrNothing: true,
      });

      if (result.item_errors && Object.keys(result.item_errors).length > 0) {
        setSemanticBatchItemErrors(result.item_errors);
        setSemanticBatchSaveError(t.semanticBatchSaveFailedWithErrors);
        setSemanticBatchConfirmOpen(false);
        setSemanticBatchReviewOpen(true);
        return;
      }

      setSemanticDestApplyResult(result);

      // Refresh Rooms/RoutePoints/RouteEdges, exactly like the existing
      // per-card apply flow.
      await refreshRouteGraph(activeMap.id);

      // Clear the local draft — a successful save is one of only two
      // times this is allowed to happen (Section 9); the other is an
      // explicit discard.
      try {
        window.localStorage.removeItem(getSemanticBatchDraftKey());
      } catch {
        // Nothing else to do if storage is unavailable — the batch
        // itself still saved successfully server-side.
      }

      setSemanticBatchActive(false);
      setSemanticBatchReviewOpen(false);
      setSemanticBatchConfirmOpen(false);
      setSemanticDestPhase('result');
      setMode('point');
    } catch (error) {
      console.error('Save All Destinations failed:', error);
      setSemanticBatchSaveError(error.message || t.semanticDestApplyFailed);
      setSemanticBatchConfirmOpen(false);
    } finally {
      setSemanticBatchSaving(false);
    }
  };

  // Section 9: persists the in-progress batch (queue order, every item's
  // status, and every remembered x/y) to localStorage on every change
  // while batch mode is active — never written to real Room/RoutePoint
  // collections, purely a browser-local resume aid.
  useEffect(() => {
    if (!semanticBatchActive || !activeMap?.id) return undefined;

    const placements = {};
    semanticDestProposals.forEach((proposal) => {
      if (proposal.x != null && proposal.y != null) {
        placements[proposal.semantic_item_id] = { x: proposal.x, y: proposal.y };
      }
    });

    try {
      window.localStorage.setItem(
        getSemanticBatchDraftKey(),
        serializeBatchDraft({
          queueItemIds: semanticBatchQueue,
          statuses: semanticBatchStatuses,
          placements,
        }),
      );
    } catch {
      // localStorage may be unavailable/full — batch placement still
      // works for the current session even if the draft can't persist.
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    semanticBatchActive,
    semanticBatchQueue,
    semanticBatchStatuses,
    semanticDestProposals,
    activeMap?.id,
    semanticDestPublicationId,
  ]);

  // Section 4: keyboard shortcuts are an ADDITIONAL way to drive the
  // workflow, never the only way — every action they trigger also has a
  // corresponding on-screen button (Previous/Skip/Reject/Undo/Change
  // location/Exit above, or the map click itself).
  useEffect(() => {
    if (!semanticBatchActive) return undefined;

    const handleBatchKeyDown = (event) => {
      const tag = event.target?.tagName;
      if (tag === 'INPUT' || tag === 'TEXTAREA') return;

      if (event.key === 'Enter') {
        const activeItemId = semanticBatchQueue[semanticBatchIndex];
        const status = activeItemId ? semanticBatchStatuses[activeItemId] : null;
        // "move to next only when current item is valid" (Section 4).
        if (status === 'placed' || status === 'rejected') {
          event.preventDefault();
          const nextIndex = findNextActiveIndex(
            semanticBatchQueue,
            semanticBatchStatuses,
            semanticBatchIndex,
          );
          if (nextIndex === -1) {
            setSemanticBatchReviewOpen(true);
          } else {
            setSemanticBatchIndex(nextIndex);
          }
        }
      } else if (event.key === 'Backspace' || (event.ctrlKey && event.key.toLowerCase() === 'z')) {
        event.preventDefault();
        handleBatchUndo();
      } else if (event.key === 'Escape') {
        event.preventDefault();
        handleRequestExitSemanticBatch();
      }
    };

    window.addEventListener('keydown', handleBatchKeyDown);
    return () => window.removeEventListener('keydown', handleBatchKeyDown);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    semanticBatchActive,
    semanticBatchQueue,
    semanticBatchIndex,
    semanticBatchStatuses,
    semanticBatchHistory,
  ]);

  return (
    <div className="layout-wrapper">
      <div
        className="layout-shell adm-shell"
        dir={isRTL ? 'rtl' : 'ltr'}
      >
        <div className="adm-inner-header">
          <div className="adm-topbar">
            <button
              className={`adm-back-btn${
                isRTL
                  ? ' adm-back-btn-rtl'
                  : ''
              }`}
              onClick={() =>
                navigate('/screen/05')
              }
            >
              <BackArrow flip={isRTL} />
              {t.back}
            </button>

            <div
              className="adm-lang-pill"
              role="group"
            >
              {LANGUAGES.map(
                (language) => (
                  <button
                    key={language.code}
                    className={`adm-lang-btn${
                      lang === language.code
                        ? ' active'
                        : ''
                    }`}
                    onClick={() =>
                      setLang(
                        language.code,
                      )
                    }
                  >
                    {language.label}
                  </button>
                ),
              )}
            </div>
          </div>

          <div className="adm-inner-heading">
            <div className="adm-inner-icon">
              <MapIcon />
            </div>

            <h1 className="adm-inner-title">
              {t.title}
            </h1>
          </div>

          {/* Part 4 — arrived from the Add/Edit Room screen's "Add /
              Upload New Map" action. The Room draft is already saved
              (sessionStorage) at this point, so this is purely an
              explicit, always-available way back — never required, since
              a successful upload above already navigates back on its own. */}
          {returnToRoomPath && (
            <div
              className="adm-form-hint"
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                gap: 12,
                marginTop: 10,
              }}
            >
              <span>{t.roomDraftBanner}</span>
              <button
                type="button"
                className="adm-btn adm-btn-secondary"
                onClick={() => navigate(returnToRoomPath)}
              >
                {t.backToRoom}
              </button>
            </div>
          )}
        </div>

        <div className="adm-content">
          {view === 'detail' && (
            <>
              {mapManagementGroups.length > 0 && (
                <div className="adm-form-card" style={{ marginBottom: 16 }}>
                  {mapManagementGroups.map((group) => {
                    const isExpanded = expandedGroupIds.has(group.id);
                    return (
                      <div
                        key={group.id}
                        style={{
                          border: '1px solid #dde8f5',
                          borderRadius: 12,
                          padding: 12,
                          marginBottom: 10,
                          background: '#fbfdff',
                        }}
                      >
                        <div
                          style={{
                            display: 'flex',
                            justifyContent: 'space-between',
                            alignItems: 'center',
                            gap: 10,
                            cursor: 'pointer',
                          }}
                          onClick={() => toggleGroupExpanded(group.id)}
                        >
                          <div>
                            <div style={{ fontWeight: 800, color: '#173b70', fontSize: 14 }}>
                              {group.name || group.code}
                            </div>
                            <div style={{ fontSize: 12, color: '#7891ac', marginTop: 2 }}>
                              {group.code} · {t.groupFloorCount(group.floors.length)}
                            </div>
                          </div>
                          <button type="button" className="adm-btn adm-btn-secondary" style={{ padding: '5px 12px', fontSize: 12 }}>
                            {isExpanded ? t.collapseGroup : t.expandGroup}
                          </button>
                        </div>

                        {isExpanded && (
                          <div style={{ marginTop: 10 }}>
                            {group.floors.map((floorMap) => (
                              <div
                                key={floorMap.id}
                                style={{
                                  display: 'flex',
                                  justifyContent: 'space-between',
                                  alignItems: 'center',
                                  padding: '8px 10px',
                                  borderRadius: 8,
                                  marginBottom: 6,
                                  background:
                                    floorMap.id === selectedMapId ? '#e5eef9' : '#ffffff',
                                  border: '1px solid #e7eff9',
                                }}
                              >
                                <div>
                                  <div style={{ fontSize: 13, fontWeight: 700, color: '#1f5fae' }}>
                                    {formatFloorDisplay(floorMap.floor, floorMap.floorLabel)}
                                    {' — '}
                                    {floorMap.title}
                                  </div>
                                  <div style={{ fontSize: 11, color: '#7891ac' }}>
                                    {floorMap.processingStatus}
                                  </div>
                                </div>
                                <div style={{ display: 'flex', gap: 6 }}>
                                  <button
                                    type="button"
                                    className="adm-btn adm-btn-secondary"
                                    style={{ padding: '4px 10px', fontSize: 11.5 }}
                                    onClick={() => handleMapSelection(floorMap.id)}
                                  >
                                    {t.editDetails}
                                  </button>
                                  <button
                                    type="button"
                                    className="adm-btn adm-btn-cancel"
                                    style={{ padding: '4px 10px', fontSize: 11.5 }}
                                    onClick={() => handleDeleteMapGroupFloor(group, floorMap)}
                                  >
                                    {t.deleteMap}
                                  </button>
                                </div>
                              </div>
                            ))}

                            <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
                              <button
                                type="button"
                                className="adm-btn"
                                style={{ padding: '5px 12px', fontSize: 12 }}
                                onClick={() => openAddFloorForm(group)}
                              >
                                {t.addFloor}
                              </button>
                              <button
                                type="button"
                                className="adm-btn adm-btn-cancel"
                                style={{ padding: '5px 12px', fontSize: 12 }}
                                onClick={() => handleDeleteMapGroup(group)}
                              >
                                {t.deleteGroup}
                              </button>
                            </div>

                            {addFloorGroupId === group.id && (
                              <div
                                style={{
                                  marginTop: 12,
                                  padding: 10,
                                  borderRadius: 10,
                                  border: '1px dashed #9db8dd',
                                }}
                              >
                                <div style={{ fontWeight: 800, fontSize: 13, marginBottom: 8, color: '#173b70' }}>
                                  {t.addFloorTitle}
                                </div>

                                {addFloorRows.map((row) => (
                                  <div key={row.rowId} style={{ marginBottom: 10 }}>
                                    <input
                                      className="adm-form-input"
                                      type="file"
                                      style={{ marginBottom: 6 }}
                                      accept="image/png,image/jpeg,image/jpg,image/webp,application/pdf,.pdf"
                                      onChange={(event) =>
                                        handleAddFloorFileChange(row.rowId, event.target.files?.[0] || null)
                                      }
                                    />
                                    <input
                                      className="adm-form-input"
                                      placeholder={t.floorTitle}
                                      style={{ marginBottom: 6 }}
                                      value={row.title}
                                      onChange={(event) => updateAddFloorRow(row.rowId, 'title', event.target.value)}
                                    />
                                    <div style={{ display: 'flex', gap: 8 }}>
                                      <input
                                        className="adm-form-input"
                                        type="number"
                                        step="1"
                                        placeholder={t.floorNumber}
                                        value={row.floor}
                                        onChange={(event) => updateAddFloorRow(row.rowId, 'floor', event.target.value)}
                                      />
                                      <input
                                        className="adm-form-input"
                                        placeholder={t.floorLabel}
                                        value={row.floorLabel}
                                        onChange={(event) => updateAddFloorRow(row.rowId, 'floorLabel', event.target.value)}
                                      />
                                    </div>
                                    {addFloorRows.length > 1 && (
                                      <button
                                        type="button"
                                        className="adm-btn adm-btn-cancel"
                                        style={{ padding: '3px 9px', fontSize: 11, marginTop: 6 }}
                                        onClick={() => removeAddFloorRow(row.rowId)}
                                      >
                                        {t.removeFloor}
                                      </button>
                                    )}
                                  </div>
                                ))}

                                <button
                                  type="button"
                                  className="adm-btn"
                                  style={{ fontSize: 12, marginBottom: 8 }}
                                  onClick={addAddFloorRow}
                                >
                                  {t.addAnotherFloor}
                                </button>

                                {addFloorError && (
                                  <div style={{ color: '#b42318', fontSize: 12, fontWeight: 700, marginBottom: 8 }}>
                                    {addFloorError}
                                  </div>
                                )}

                                <div style={{ display: 'flex', gap: 8 }}>
                                  <button
                                    type="button"
                                    className="adm-btn adm-btn-cancel"
                                    style={{ fontSize: 12 }}
                                    onClick={closeAddFloorForm}
                                    disabled={isAddingFloor}
                                  >
                                    {t.cancel}
                                  </button>
                                  <button
                                    type="button"
                                    className="adm-btn adm-btn-primary"
                                    style={{ fontSize: 12 }}
                                    onClick={handleSubmitAddFloor}
                                    disabled={isAddingFloor}
                                  >
                                    {isAddingFloor ? t.uploadingFloors : t.saveFloor}
                                  </button>
                                </div>
                              </div>
                            )}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}

              <div
                className="adm-form-card"
                style={{
                  marginBottom: 16,
                }}
              >
                <div
                  className="adm-form-group"
                  style={{
                    marginBottom: 0,
                  }}
                >
                  <label className="adm-form-label">
                    {t.selectMap}
                  </label>

                  <select
                    className="adm-form-input"
                    value={selectedMapId}
                    disabled={
                      isMapsLoading ||
                      maps.length === 0
                    }
                    onChange={(event) =>
                      handleMapSelection(
                        event.target.value,
                      )
                    }
                  >
                    {maps.length === 0 && (
                      <option value="">
                        {t.noSelectedMap}
                      </option>
                    )}

                    {maps.map((map) => (
                      <option
                        key={map.id}
                        value={map.id}
                      >
                        {map.mapGroupCode
                          ? `[${map.mapGroupCode}] ${formatFloorDisplay(map.floor, map.floorLabel)} — `
                          : ''}
                        {map.title || map.id}

                        {map.isCurrent
                          ? ` — ${t.current}`
                          : ''}
                      </option>
                    ))}
                  </select>
                </div>

                <div
                  style={{
                    marginTop: 10,
                    fontSize: 12.5,
                    color: mapsError
                      ? '#c0392b'
                      : '#5f7fa6',
                  }}
                >
                  {isMapsLoading
                    ? t.loadingMaps
                    : mapsError ||
                      `${t.savedPoints}: ${routePoints.length}`}
                </div>

                {isPointsLoading && (
                  <div
                    style={{
                      marginTop: 6,
                      fontSize: 12.5,
                      color: '#5f7fa6',
                    }}
                  >
                    {t.loadingPoints}
                  </div>
                )}

                {!isPointsLoading &&
                  pointsError && (
                    <div
                      style={{
                        marginTop: 6,
                        fontSize: 12.5,
                        color: '#c0392b',
                      }}
                    >
                      {pointsError}
                    </div>
                  )}

                {!isPointsLoading &&
                  !pointsError &&
                  selectedMapId &&
                  routePoints.length ===
                    0 && (
                    <div
                      style={{
                        marginTop: 6,
                        fontSize: 12.5,
                        color: '#7a9abf',
                      }}
                    >
                      {t.noPoints}
                    </div>
                  )}

                {isEdgesLoading && (
                  <div
                    style={{
                      marginTop: 6,
                      fontSize: 12.5,
                      color: '#5f7fa6',
                    }}
                  >
                    {t.loadingEdges}
                  </div>
                )}

                {!isEdgesLoading &&
                  edgesError && (
                    <div
                      style={{
                        marginTop: 6,
                        fontSize: 12.5,
                        color: '#c0392b',
                      }}
                    >
                      {edgesError}
                    </div>
                  )}

                {!isEdgesLoading &&
                  !edgesError &&
                  selectedMapId && (
                    <div
                      style={{
                        marginTop: 6,
                        fontSize: 12.5,
                        color:
                          routeEdges.length === 0
                            ? '#7a9abf'
                            : '#5f7fa6',
                      }}
                    >
                      {routeEdges.length === 0
                        ? t.noEdges
                        : `${t.savedEdges}: ${routeEdges.length}`}
                    </div>
                  )}

                {missingEdgeCount > 0 && (
                  <div
                    style={{
                      marginTop: 6,
                      fontSize: 12.5,
                      color: '#c0392b',
                    }}
                  >
                    {missingEdgeCount} {t.edgeDataWarning}
                  </div>
                )}
              </div>

              {isProcessing && (
                <div
                  className="adm-form-card"
                  style={{
                    marginBottom: 16,
                  }}
                >
                  <div
                    style={{
                      fontWeight: 800,
                      color: '#173b70',
                      marginBottom: 8,
                    }}
                  >
                    {t.processing}:{' '}
                    {activeMap?.processingProgress ||
                      0}
                    %
                  </div>

                  <div
                    style={{
                      width: '100%',
                      height: 10,
                      background: '#e5eef9',
                      borderRadius: 999,
                      overflow: 'hidden',
                    }}
                  >
                    <div
                      style={{
                        width: `${Math.max(
                          3,
                          Math.min(
                            100,
                            activeMap?.processingProgress ||
                              0,
                          ),
                        )}%`,
                        height: '100%',
                        background: '#376fbd',
                        transition:
                          'width 0.3s ease',
                      }}
                    />
                  </div>
                </div>
              )}

              {activeMap?.processingStatus ===
                'failed' && (
                <div
                  className="adm-form-card"
                  style={{
                    marginBottom: 16,
                    color: '#c0392b',
                  }}
                >
                  <div
                    style={{
                      fontWeight: 800,
                    }}
                  >
                    {t.processingFailed}
                  </div>

                  {activeMap.processingError && (
                    <div
                      style={{
                        marginTop: 6,
                        fontSize: 12,
                      }}
                    >
                      {
                        activeMap.processingError
                      }
                    </div>
                  )}
                </div>
              )}

              <div className="adm-map-img-placeholder">
                {activeMap?.hasImage &&
                adminMapImageUrl ? (
                  <>
                    <img
                      src={adminMapImageUrl}
                      alt={
                        activeMap.title ||
                        'Selected map'
                      }
                      onClick={() =>
                        setIsMapOpen(true)
                      }
                      style={{
                        display: 'block',
                        width: '100%',
                        maxHeight: '520px',
                        objectFit: 'contain',
                        borderRadius: '18px',
                        cursor: 'zoom-in',
                      }}
                    />

                    <div
                      style={{
                        marginTop: 10,
                        fontSize: 12,
                        fontWeight: 700,
                        color: '#4c7bb5',
                      }}
                    >
                      {t.openFullMap}
                    </div>
                  </>
                ) : (
                  <>
                    <MapIcon />

                    <div className="adm-map-img-label">
                      {isProcessing
                        ? t.processing
                        : t.noMap}
                    </div>

                    <div
                      style={{
                        marginTop: 6,
                        fontSize: 12,
                        color: '#7a9abf',
                      }}
                    >
                      {isProcessing
                        ? `${
                            activeMap?.processingProgress ||
                            0
                          }%`
                        : t.noMapHint}
                    </div>
                  </>
                )}
              </div>

              <button
                className="adm-upload-btn"
                onClick={openUploadModal}
              >
                <UploadIcon />
                {t.uploadNewMap}
              </button>

              {/* Navigation-data-problem task, Part 2: this optional,
                  experimental automatic-generation workflow is hidden
                  from the normal building_manager workflow entirely —
                  manual RoutePoint creation is the only supported path
                  for that role. super_admin/global_manager can still
                  reach it, but only behind an explicit preview+confirm
                  (handleGenerateGraph above never writes without both). */}
              {activeMap?.processingStatus === 'completed' &&
                user?.role !== 'building_manager' && (
                <div className="adm-btn-row" style={{ flexDirection: 'column', alignItems: 'stretch' }}>
                  <div style={{ display: 'flex', gap: 8 }}>
                    <button
                      className="adm-btn adm-btn-secondary"
                      onClick={handleGenerateGraph}
                      disabled={isGeneratingGraph}
                      title={t.graphGenerationExperimentalNote}
                    >
                      {isGeneratingGraph
                        ? t.graphGenerating
                        : t.regenerateGraph}
                    </button>

                    <button
                      className="adm-btn adm-btn-secondary"
                      onClick={handleClearGeneratedGraph}
                    >
                      {t.clearGeneratedGraph}
                    </button>
                  </div>
                  <div
                    style={{
                      fontSize: 11,
                      color: '#8a9bb5',
                      marginTop: 4,
                      lineHeight: 1.4,
                    }}
                  >
                    {t.graphGenerationExperimentalNote}
                  </div>
                </div>
              )}

              {/* Navigation-data-problem task, Part 3A/3B — safe cleanup
                  for maps that already have hundreds of stored generated
                  RoutePoints/RouteEdges (never touched by an ordinary
                  upload/analysis/publish/sync anymore, but pre-existing
                  data isn't removed by that fix alone). Both actions are
                  strictly preview -> explicit confirm -> apply. Full Reset
                  is Super Admin only, matching the backend's
                  require_super_admin gate exactly (this is a UI
                  convenience, not the real security boundary). */}
              {activeMap?.id && (
                <div className="adm-btn-row" style={{ flexDirection: 'column', alignItems: 'stretch', gap: 8 }}>
                  <button
                    type="button"
                    className="adm-btn adm-btn-secondary"
                    onClick={handleOpenGeneratedCleanup}
                    disabled={isCleanupPreviewLoading}
                  >
                    {isCleanupPreviewLoading
                      ? t.cleanupPreviewLoading
                      : t.removeGeneratedNavData}
                  </button>

                  {user?.role === 'super_admin' && (
                    <button
                      type="button"
                      className="adm-btn adm-btn-danger"
                      onClick={handleOpenFullReset}
                      disabled={isResetPreviewLoading}
                    >
                      {isResetPreviewLoading
                        ? t.cleanupPreviewLoading
                        : t.resetAllNavData}
                    </button>
                  )}
                </div>
              )}

              {activeMap?.graphGenerationNote && (
                <div
                  style={{
                    fontSize: 11.5,
                    color: '#5f7fa6',
                    marginBottom: 10,
                    lineHeight: 1.4,
                  }}
                >
                  {activeMap.graphGenerationNote}
                </div>
              )}

              <div className="adm-btn-row">
                <button
                  className="adm-btn adm-btn-secondary"
                  onClick={openEdit}
                  disabled={!activeMap?.id}
                >
                  <EditIcon />
                  {t.editDetails}
                </button>

                <button
                  className="adm-btn adm-btn-danger"
                  onClick={() =>
                    setView(
                      'confirm-delete',
                    )
                  }
                  disabled={!activeMap?.id}
                >
                  <DeleteIcon />
                  {t.deleteMap}
                </button>
              </div>

              {/* Automatic semantic map analysis (real backend — see
                  backend/routes/semantic_analysis_routes.py). Fires
                  automatically after a successful upload when
                  AUTO_ANALYZE_MAPS=true; this button/status card lets an
                  admin also start/retry/review it manually. Manual
                  Add Point / Draw Path / Vertical Connections above
                  remain the primary, unchanged workflow either way — AI
                  semantic analysis never creates RoutePoints/RouteEdges
                  itself. */}
              <div className="adm-btn-row">
                <button
                  type="button"
                  className="adm-btn adm-btn-secondary"
                  onClick={() => navigate(`/admin/map-analysis?mapId=${activeMap.id}`)}
                  disabled={!activeMap?.id}
                >
                  {t.analyzeFloorMap}
                </button>
              </div>
              {activeMap?.id && (
                <SemanticAnalysisStatusCard mapId={activeMap.id} lang={lang} />
              )}

              {/* Data-consistency repair for the "Walkway edge must
                  connect points on the same floor" rejection: some
                  legacy RoutePoints still carry a null/stale floor that
                  disagrees with their own Map. This is a global repair
                  across every RoutePoint (not scoped to activeMap), so
                  it's always enabled. Always dry-runs first — see
                  handleRepairRoutePointFloors. */}
              <div className="adm-btn-row">
                <button
                  type="button"
                  className="adm-btn adm-btn-secondary"
                  onClick={handleRepairRoutePointFloors}
                  disabled={isRepairingFloors}
                >
                  {isRepairingFloors
                    ? t.repairFloorsRunning
                    : t.repairFloorsButton}
                </button>
              </div>

              <div className="adm-section-row">
                <span className="adm-section-lbl">
                  {t.selectedMap}
                </span>
              </div>

              <div className="adm-form-card">
                <div className="adm-detail-list">
                  <div className="adm-detail-row">
                    <span className="adm-detail-key">
                      {t.details.title}
                    </span>

                    <span className="adm-detail-val">
                      {activeMap?.title ||
                        '—'}
                    </span>
                  </div>

                  <div className="adm-detail-row">
                    <span className="adm-detail-key">
                      {t.details.campus}
                    </span>

                    <span className="adm-detail-val">
                      {activeMap?.campus ||
                        '—'}
                    </span>
                  </div>

                  <div className="adm-detail-row">
                    <span className="adm-detail-key">
                      {t.details.address}
                    </span>

                    <span className="adm-detail-val">
                      {activeMap?.address ||
                        '—'}
                    </span>
                  </div>

                  <div className="adm-detail-row">
                    <span className="adm-detail-key">
                      {
                        t.details
                          .description
                      }
                    </span>

                    <span className="adm-detail-val">
                      {activeMap?.description ||
                        '—'}
                    </span>
                  </div>

                  <div className="adm-detail-row">
                    <span className="adm-detail-key">
                      {t.details.status}
                    </span>

                    <span className="adm-detail-val">
                      {activeMap?.processingStatus ||
                        '—'}
                    </span>
                  </div>

                  <div className="adm-detail-row">
                    <span className="adm-detail-key">
                      {t.details.mapId}
                    </span>

                    <span
                      className="adm-detail-val"
                      style={{
                        wordBreak: 'break-all',
                        fontSize: 11.5,
                      }}
                    >
                      {activeMap?.id || '—'}
                    </span>
                  </div>
                </div>
              </div>
            </>
          )}

          {view === 'edit' && (
            <div className="adm-form-card">
              <div className="adm-form-card-title">
                {t.editTitle}
              </div>

              <div className="adm-form-group">
                <label className="adm-form-label">
                  {t.mapTitle}
                </label>

                <input
                  className="adm-form-input"
                  value={form.title || ''}
                  onChange={(event) =>
                    setFormField(
                      'title',
                      event.target.value,
                    )
                  }
                />
              </div>

              <div className="adm-form-group">
                <label className="adm-form-label">
                  {t.campus}
                </label>

                <input
                  className="adm-form-input"
                  value={form.campus || ''}
                  onChange={(event) =>
                    setFormField(
                      'campus',
                      event.target.value,
                    )
                  }
                />
              </div>

              <div className="adm-form-group">
                <label className="adm-form-label">
                  {t.address}
                </label>

                <input
                  className="adm-form-input"
                  value={form.address || ''}
                  onChange={(event) =>
                    setFormField(
                      'address',
                      event.target.value,
                    )
                  }
                />
              </div>

              <div className="adm-form-group">
                <label className="adm-form-label">
                  {t.description}
                </label>

                <textarea
                  className="adm-form-textarea"
                  value={
                    form.description || ''
                  }
                  onChange={(event) =>
                    setFormField(
                      'description',
                      event.target.value,
                    )
                  }
                />
              </div>

              <div className="adm-form-group">
                <label className="adm-form-label">
                  {t.editFloorLabel}
                </label>

                <select
                  className="adm-form-input"
                  value={
                    form.floor === null || form.floor === undefined
                      ? ''
                      : String(form.floor)
                  }
                  onChange={(event) =>
                    setFormField(
                      'floor',
                      event.target.value === ''
                        ? null
                        : Number(event.target.value),
                    )
                  }
                >
                  <option value="">
                    {t.floorNotConfigured}
                  </option>
                  {editFloorOptions.map((option) => (
                    <option key={option.floor} value={option.floor}>
                      {option.label}
                    </option>
                  ))}
                </select>

                {(form.floor === null || form.floor === undefined) && (
                  <div
                    style={{
                      fontSize: 11.5,
                      color: '#b42318',
                      fontWeight: 600,
                      marginTop: 4,
                    }}
                  >
                    {t.floorNotConfigured}
                  </div>
                )}
              </div>

              <div className="adm-form-actions">
                <button
                  className="adm-btn adm-btn-cancel"
                  onClick={() =>
                    setView('detail')
                  }
                >
                  {t.cancel}
                </button>

                <button
                  className="adm-btn adm-btn-primary"
                  onClick={saveMapDetails}
                >
                  {t.saveChanges}
                </button>
              </div>
            </div>
          )}

          {view ===
            'confirm-delete' && (
            <div
              className="adm-form-card"
              style={{
                textAlign: 'center',
                padding: '28px 20px',
              }}
            >
              <div
                style={{
                  color: '#c0392b',
                  marginBottom: 12,
                }}
              >
                <DeleteIcon />
              </div>

              <div
                style={{
                  fontFamily:
                    'var(--font-brand)',
                  fontSize: 16,
                  fontWeight: 700,
                  color: '#1a3a6b',
                  marginBottom: 8,
                }}
              >
                {t.confirmDelete}
              </div>

              <div
                style={{
                  fontSize: 12.5,
                  color: '#7a9abf',
                  marginBottom: 20,
                }}
              >
                {activeMap?.title}
              </div>

              <div
                className="adm-form-actions"
                style={{
                  justifyContent: 'center',
                }}
              >
                <button
                  className="adm-btn adm-btn-cancel"
                  onClick={() =>
                    setView('detail')
                  }
                >
                  {t.cancel}
                </button>

                <button
                  className="adm-btn adm-btn-confirm-delete"
                  onClick={deleteMap}
                >
                  {t.yesDelete}
                </button>
              </div>
            </div>
          )}
        </div>

        {isUploadOpen && (
          <div
            onClick={closeUploadModal}
            style={{
              position: 'fixed',
              inset: 0,
              zIndex: 10020,
              background:
                'rgba(9, 26, 53, 0.78)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              padding: 20,
              overflowY: 'auto',
            }}
          >
            <div
              className="adm-form-card"
              onClick={(event) =>
                event.stopPropagation()
              }
              style={{
                width:
                  'min(560px, 96vw)',
                maxHeight: '92vh',
                overflowY: 'auto',
                padding: 24,
              }}
            >
              <div className="adm-form-card-title">
                {t.uploadTitle}
              </div>

              <div
                role="tablist"
                style={{
                  display: 'flex',
                  gap: 8,
                  marginBottom: 18,
                  background: '#eef4fb',
                  padding: 4,
                  borderRadius: 12,
                }}
              >
                <button
                  type="button"
                  role="tab"
                  aria-selected={uploadMode === 'single'}
                  onClick={() => setUploadMode('single')}
                  className="adm-btn"
                  style={{
                    flex: 1,
                    background: uploadMode === 'single' ? '#1f5fae' : 'transparent',
                    color: uploadMode === 'single' ? '#fff' : '#315b8f',
                    boxShadow: 'none',
                  }}
                >
                  {t.modeSingle}
                </button>
                <button
                  type="button"
                  role="tab"
                  aria-selected={uploadMode === 'multi'}
                  onClick={() => setUploadMode('multi')}
                  className="adm-btn"
                  style={{
                    flex: 1,
                    background: uploadMode === 'multi' ? '#1f5fae' : 'transparent',
                    color: uploadMode === 'multi' ? '#fff' : '#315b8f',
                    boxShadow: 'none',
                  }}
                >
                  {t.modeMulti}
                </button>
              </div>

              <div
                style={{
                  marginBottom: 16,
                  fontSize: 12.5,
                  color: '#5c7ca3',
                }}
              >
                {uploadMode === 'single' ? t.modeSingleHint : t.modeMultiHint}
              </div>

              {uploadMode === 'single' && (
              <>
              <div className="adm-form-group">
                <label className="adm-form-label">
                  {t.chooseFile}
                </label>

                <input
                  className="adm-form-input"
                  type="file"
                  accept="image/png,image/jpeg,image/jpg,image/webp,application/pdf,.pdf"
                  onChange={
                    handleUploadFileChange
                  }
                />
              </div>

              {uploadFile && (
                <div
                  style={{
                    marginBottom: 14,
                    padding: 12,
                    borderRadius: 12,
                    background: '#f1f6fc',
                    color: '#315b8f',
                    fontSize: 12.5,
                    wordBreak: 'break-word',
                  }}
                >
                  <strong>
                    {t.selectedFile}:
                  </strong>{' '}
                  {uploadFile.name}
                </div>
              )}

              {uploadPreview && (
                <img
                  src={uploadPreview}
                  alt="Map preview"
                  style={{
                    display: 'block',
                    width: '100%',
                    maxHeight: 230,
                    objectFit: 'contain',
                    borderRadius: 14,
                    background: '#eef4fb',
                    marginBottom: 16,
                  }}
                />
              )}

              <div className="adm-form-group">
                <label className="adm-form-label">
                  {t.mapTitle}
                </label>

                <input
                  className="adm-form-input"
                  value={uploadForm.title}
                  onChange={(event) =>
                    setUploadField(
                      'title',
                      event.target.value,
                    )
                  }
                />
              </div>

              <div className="adm-form-group">
                <label className="adm-form-label">
                  {t.campus}
                </label>

                <input
                  className="adm-form-input"
                  value={uploadForm.campus}
                  onChange={(event) =>
                    setUploadField(
                      'campus',
                      event.target.value,
                    )
                  }
                />
              </div>

              <div className="adm-form-group">
                <label className="adm-form-label">
                  {t.address}
                </label>

                <input
                  className="adm-form-input"
                  value={uploadForm.address}
                  onChange={(event) =>
                    setUploadField(
                      'address',
                      event.target.value,
                    )
                  }
                />
              </div>

              <div className="adm-form-group">
                <label className="adm-form-label">
                  {t.description}
                </label>

                <textarea
                  className="adm-form-textarea"
                  value={
                    uploadForm.description
                  }
                  onChange={(event) =>
                    setUploadField(
                      'description',
                      event.target.value,
                    )
                  }
                />
              </div>

              <div className="adm-form-group">
                <label className="adm-form-label">
                  {t.scale}
                </label>

                <input
                  className="adm-form-input"
                  type="number"
                  min="0.0001"
                  step="0.01"
                  value={uploadForm.scale}
                  onChange={(event) =>
                    setUploadField(
                      'scale',
                      event.target.value,
                    )
                  }
                />
              </div>

              <div className="adm-form-group">
                <label className="adm-form-label">
                  {t.uploadBuilding}
                </label>

                <select
                  className="adm-form-select"
                  value={uploadForm.buildingId}
                  onChange={(event) =>
                    setUploadField('buildingId', event.target.value)
                  }
                >
                  <option value="">{t.uploadBuildingAuto}</option>
                  {buildingsList.map((b) => (
                    <option key={b.id} value={b.id}>
                      {b.name_en}
                    </option>
                  ))}
                </select>
              </div>

              <div className="adm-form-group">
                <label className="adm-form-label">
                  {t.uploadFloor}
                </label>

                <input
                  className="adm-form-input"
                  type="number"
                  step="1"
                  value={uploadForm.floor}
                  onChange={(event) =>
                    setUploadField('floor', event.target.value)
                  }
                />
              </div>

              <label
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 9,
                  marginBottom: 12,
                  color: '#315b8f',
                  fontSize: 13,
                  fontWeight: 700,
                  cursor: 'pointer',
                }}
              >
                <input
                  type="checkbox"
                  checked={
                    uploadForm.useOpenAI
                  }
                  onChange={(event) =>
                    setUploadField(
                      'useOpenAI',
                      event.target.checked,
                    )
                  }
                />

                {t.useOpenAI}
              </label>

              {/* Navigation-data-problem task, Part 2: the "auto-generate
                  walkable graph after upload" checkbox has been removed
                  from the normal upload workflow — RoutePoints/RouteEdges
                  must only ever be created manually or via the separate,
                  explicit preview -> confirm "Generate Route Graph"
                  action below (never automatically on upload). The
                  underlying autoGenerateGraph form field is left at its
                  default (false) and is now inert on the backend even if
                  ever sent as true. */}

              {uploadError && (
                <div
                  style={{
                    marginBottom: 14,
                    padding: 11,
                    borderRadius: 10,
                    background: '#fff0f0',
                    color: '#b42318',
                    fontSize: 12.5,
                    fontWeight: 700,
                  }}
                >
                  {uploadError}
                </div>
              )}
              </>
              )}

              {uploadMode === 'multi' && (
              <>
                <div className="adm-form-card-title" style={{ fontSize: 15, marginTop: 4 }}>
                  {t.mapGroupInfoTitle}
                </div>

                <div className="adm-form-group">
                  <label className="adm-form-label">{t.uploadBuilding}</label>
                  <select
                    className="adm-form-select"
                    value={mapGroupForm.buildingId}
                    onChange={(event) => setMapGroupField('buildingId', event.target.value)}
                  >
                    <option value="">{t.uploadBuildingAuto}</option>
                    {buildingsList.map((b) => (
                      <option key={b.id} value={b.id}>
                        {b.name_en}
                      </option>
                    ))}
                  </select>
                </div>

                <div className="adm-form-group">
                  <label className="adm-form-label">{t.mapGroupName}</label>
                  <input
                    className="adm-form-input"
                    value={mapGroupForm.name}
                    onChange={(event) => setMapGroupField('name', event.target.value)}
                  />
                </div>

                <div className="adm-form-group">
                  <label className="adm-form-label">{t.mapGroupCode}</label>
                  <input
                    className="adm-form-input"
                    value={mapGroupForm.code}
                    placeholder="QRMALL-001"
                    onChange={(event) => setMapGroupField('code', event.target.value)}
                  />
                  <div style={{ fontSize: 11.5, color: '#7891ac', marginTop: 4 }}>
                    {t.mapGroupCodeHint}
                  </div>
                </div>

                <div className="adm-form-group">
                  <label className="adm-form-label">{t.campus}</label>
                  <input
                    className="adm-form-input"
                    value={mapGroupForm.campus}
                    onChange={(event) => setMapGroupField('campus', event.target.value)}
                  />
                </div>

                <div className="adm-form-group">
                  <label className="adm-form-label">{t.address}</label>
                  <input
                    className="adm-form-input"
                    value={mapGroupForm.address}
                    onChange={(event) => setMapGroupField('address', event.target.value)}
                  />
                </div>

                <div className="adm-form-group">
                  <label className="adm-form-label">{t.description}</label>
                  <textarea
                    className="adm-form-textarea"
                    value={mapGroupForm.description}
                    onChange={(event) => setMapGroupField('description', event.target.value)}
                  />
                </div>

                <div className="adm-form-card-title" style={{ fontSize: 15, marginTop: 10 }}>
                  {t.floorMapsListTitle}
                </div>

                {floorRows.map((row, index) => {
                  const rowErrors = groupUploadError ? validateFloorRows(floorRows)[index] : null;
                  return (
                    <div
                      key={row.rowId}
                      style={{
                        border: '1px solid #dde8f5',
                        borderRadius: 12,
                        padding: 14,
                        marginBottom: 14,
                        background: '#fbfdff',
                      }}
                    >
                      <div
                        style={{
                          display: 'flex',
                          justifyContent: 'space-between',
                          alignItems: 'center',
                          marginBottom: 10,
                        }}
                      >
                        <strong style={{ fontSize: 13, color: '#1f5fae' }}>
                          {formatFloorDisplay(row.floor, row.floorLabel)}
                        </strong>
                        {floorRows.length > 1 && (
                          <button
                            type="button"
                            className="adm-btn adm-btn-cancel"
                            style={{ padding: '4px 10px', fontSize: 12 }}
                            onClick={() => removeFloorRow(row.rowId)}
                          >
                            {t.removeFloor}
                          </button>
                        )}
                      </div>

                      <div className="adm-form-group">
                        <label className="adm-form-label">{t.floorFile}</label>
                        <input
                          className="adm-form-input"
                          type="file"
                          accept="image/png,image/jpeg,image/jpg,image/webp,application/pdf,.pdf"
                          onChange={(event) =>
                            handleFloorFileChange(row.rowId, event.target.files?.[0] || null)
                          }
                        />
                        {row.fileName && (
                          <div style={{ fontSize: 12, color: '#5c7ca3', marginTop: 4 }}>
                            {row.fileName}
                          </div>
                        )}
                        {row.preview && (
                          <img
                            src={row.preview}
                            alt="Floor preview"
                            style={{
                              display: 'block',
                              width: '100%',
                              maxHeight: 140,
                              objectFit: 'contain',
                              borderRadius: 10,
                              background: '#eef4fb',
                              marginTop: 8,
                            }}
                          />
                        )}
                      </div>

                      <div className="adm-form-group">
                        <label className="adm-form-label">{t.floorTitle}</label>
                        <input
                          className="adm-form-input"
                          value={row.title}
                          onChange={(event) => updateFloorRow(row.rowId, 'title', event.target.value)}
                        />
                      </div>

                      <div style={{ display: 'flex', gap: 10 }}>
                        <div className="adm-form-group" style={{ flex: 1 }}>
                          <label className="adm-form-label">{t.floorNumber}</label>
                          <input
                            className="adm-form-input"
                            type="number"
                            step="1"
                            value={row.floor}
                            onChange={(event) => updateFloorRow(row.rowId, 'floor', event.target.value)}
                          />
                        </div>
                        <div className="adm-form-group" style={{ flex: 1 }}>
                          <label className="adm-form-label">{t.floorLabel}</label>
                          <input
                            className="adm-form-input"
                            placeholder="e.g. Parking B1"
                            value={row.floorLabel}
                            onChange={(event) => updateFloorRow(row.rowId, 'floorLabel', event.target.value)}
                          />
                        </div>
                      </div>

                      <div className="adm-form-group">
                        <label className="adm-form-label">{t.floorScale}</label>
                        <input
                          className="adm-form-input"
                          type="number"
                          min="0.0001"
                          step="0.01"
                          value={row.scale}
                          onChange={(event) => updateFloorRow(row.rowId, 'scale', event.target.value)}
                        />
                      </div>

                      <label
                        style={{
                          display: 'flex',
                          alignItems: 'center',
                          gap: 9,
                          marginBottom: 6,
                          color: '#315b8f',
                          fontSize: 13,
                          fontWeight: 700,
                          cursor: 'pointer',
                        }}
                      >
                        <input
                          type="checkbox"
                          checked={row.useOpenAI}
                          onChange={(event) => updateFloorRow(row.rowId, 'useOpenAI', event.target.checked)}
                        />
                        {t.useOpenAI}
                      </label>

                      {/* Navigation-data-problem task, Part 2: same
                          removal as the single-map upload form above —
                          no per-floor "auto-generate graph" control in
                          the normal batch upload workflow either. */}

                      {rowErrors && rowErrors.length > 0 && (
                        <div style={{ marginTop: 8, fontSize: 12, color: '#b42318', fontWeight: 700 }}>
                          {rowErrors.join(' ')}
                        </div>
                      )}
                    </div>
                  );
                })}

                <button
                  type="button"
                  className="adm-btn"
                  style={{ width: '100%', marginBottom: 14 }}
                  onClick={addFloorRow}
                >
                  {t.addAnotherFloor}
                </button>

                {groupUploadError && (
                  <div
                    style={{
                      marginBottom: 14,
                      padding: 11,
                      borderRadius: 10,
                      background: '#fff0f0',
                      color: '#b42318',
                      fontSize: 12.5,
                      fontWeight: 700,
                    }}
                  >
                    {groupUploadError}
                  </div>
                )}
              </>
              )}

              <div className="adm-form-actions">
                <button
                  className="adm-btn adm-btn-cancel"
                  onClick={closeUploadModal}
                  disabled={isUploading || isUploadingGroup}
                >
                  {t.cancel}
                </button>

                {uploadMode === 'single' ? (
                  <button
                    className="adm-btn adm-btn-primary"
                    onClick={uploadMap}
                    disabled={isUploading}
                  >
                    {isUploading ? t.uploading : t.upload}
                  </button>
                ) : (
                  <button
                    className="adm-btn adm-btn-primary"
                    onClick={handleUploadMapGroup}
                    disabled={isUploadingGroup}
                  >
                    {isUploadingGroup ? t.uploadingFloors : t.uploadAllFloors}
                  </button>
                )}
              </div>
            </div>
          </div>
        )}

        {/* Calibrate Scale: "known real distance in meters" prompt — opens
            automatically once both Point A and Point B are selected.
            Cancelling here cancels the whole calibration flow (there is no
            partial "just hide, keep points but no way back" state). */}
        {mode === 'calibrate' && isCalibrationDistanceOpen && (
          <div
            onClick={handleCancelCalibration}
            style={{
              position: 'fixed',
              inset: 0,
              zIndex: 10020,
              background: 'rgba(9, 26, 53, 0.78)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              padding: 20,
            }}
          >
            <div
              className="adm-form-card"
              onClick={(event) => event.stopPropagation()}
              style={{ width: 'min(420px, 96vw)', padding: 24 }}
            >
              <div className="adm-form-card-title">{t.calibrateMode}</div>

              <div className="adm-form-group">
                <label
                  className="adm-form-label"
                  htmlFor="calibration-distance-input"
                >
                  {t.calibrateDistanceTitle}
                </label>
                <input
                  id="calibration-distance-input"
                  className="adm-form-input"
                  type="number"
                  min="0"
                  step="0.01"
                  placeholder={t.calibrateDistancePlaceholder}
                  value={calibrationDistanceInput}
                  onChange={(event) =>
                    setCalibrationDistanceInput(event.target.value)
                  }
                  autoFocus
                />
                {calibrationDistanceInput.trim() !== '' &&
                  !isCalibrationDistanceValid && (
                    <div
                      style={{
                        fontSize: 12,
                        color: '#b42318',
                        marginTop: 6,
                        fontWeight: 600,
                      }}
                    >
                      {t.calibrateDistanceInvalid}
                    </div>
                  )}
              </div>

              {calibrationError && (
                <div
                  style={{
                    fontSize: 12.5,
                    color: '#b42318',
                    marginBottom: 12,
                    fontWeight: 600,
                  }}
                >
                  {calibrationError}
                </div>
              )}

              <div
                className="adm-form-actions"
                style={{ justifyContent: 'center' }}
              >
                <button
                  type="button"
                  className="adm-btn adm-btn-cancel"
                  onClick={handleCancelCalibration}
                  disabled={isCalibrationSaving}
                >
                  {t.calibrateCancel}
                </button>

                <button
                  type="button"
                  className="adm-btn adm-btn-primary"
                  onClick={handleSubmitCalibration}
                  disabled={!canSubmitCalibration}
                >
                  {isCalibrationSaving ? t.calibrateSaving : t.calibrateSubmit}
                </button>
              </div>
            </div>
          </div>
        )}

        {/* Calibrate Scale: success summary shown after a successful save —
            calculated scale, recalculated walkway edge count, and the
            skipped count only when it's greater than zero. */}
        {calibrationResult && (
          <div
            onClick={() => setCalibrationResult(null)}
            style={{
              position: 'fixed',
              inset: 0,
              zIndex: 10020,
              background: 'rgba(9, 26, 53, 0.78)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              padding: 20,
            }}
          >
            <div
              className="adm-form-card"
              onClick={(event) => event.stopPropagation()}
              style={{
                width: 'min(420px, 96vw)',
                padding: 24,
                textAlign: 'center',
              }}
            >
              <div className="adm-form-card-title">{t.calibrateSuccess}</div>

              <div
                style={{
                  fontSize: 13.5,
                  color: '#1a3a6b',
                  marginBottom: 8,
                  fontWeight: 700,
                }}
              >
                {t.calibrateScaleResult(calibrationResult.scale)}
              </div>

              <div
                style={{
                  fontSize: 12.5,
                  color: '#4a6a8f',
                  marginBottom:
                    calibrationResult.edgesRecalculationSkipped > 0 ? 4 : 18,
                }}
              >
                {t.calibrateEdgesRecalculated(calibrationResult.edgesRecalculated)}
              </div>

              {calibrationResult.edgesRecalculationSkipped > 0 && (
                <div
                  style={{
                    fontSize: 12.5,
                    color: '#b45309',
                    marginBottom: 18,
                    fontWeight: 600,
                  }}
                >
                  {t.calibrateEdgesSkipped(
                    calibrationResult.edgesRecalculationSkipped,
                  )}
                </div>
              )}

              <div
                className="adm-form-actions"
                style={{ justifyContent: 'center' }}
              >
                <button
                  type="button"
                  className="adm-btn adm-btn-primary"
                  onClick={() => setCalibrationResult(null)}
                >
                  {t.calibrateClose}
                </button>
              </div>
            </div>
          </div>
        )}

        {/* Sync Rooms from Route Points — confirmation modal (Section 4).
            Explicitly explains this never touches the walkable graph or
            routing before the admin confirms. */}
        {showSyncRoomsConfirm && (
          <div
            onClick={() =>
              !isSyncingRooms && setShowSyncRoomsConfirm(false)
            }
            style={{
              position: 'fixed',
              inset: 0,
              zIndex: 10020,
              background: 'rgba(9, 26, 53, 0.78)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              padding: 20,
            }}
          >
            <div
              className="adm-form-card"
              onClick={(event) => event.stopPropagation()}
              style={{
                width: 'min(440px, 96vw)',
                padding: 24,
                textAlign: 'center',
              }}
            >
              <div className="adm-form-card-title">
                {t.syncRoomsConfirmTitle}
              </div>

              <div
                style={{
                  fontSize: 13,
                  color: '#4a6a8f',
                  marginBottom: 18,
                  lineHeight: 1.5,
                }}
              >
                {t.syncRoomsConfirmBody}
              </div>

              {syncRoomsError && (
                <div
                  style={{
                    fontSize: 12.5,
                    color: '#c0392b',
                    marginBottom: 14,
                    fontWeight: 600,
                  }}
                >
                  {syncRoomsError}
                </div>
              )}

              <div
                className="adm-form-actions"
                style={{ justifyContent: 'center' }}
              >
                <button
                  type="button"
                  className="adm-btn adm-btn-secondary"
                  onClick={() => setShowSyncRoomsConfirm(false)}
                  disabled={isSyncingRooms}
                >
                  {t.cancel}
                </button>

                <button
                  type="button"
                  className="adm-btn adm-btn-primary"
                  onClick={handleConfirmSyncRooms}
                  disabled={isSyncingRooms}
                >
                  {isSyncingRooms ? t.syncRoomsRunning : t.syncRoomsConfirmButton}
                </button>
              </div>
            </div>
          </div>
        )}

        {/* Delete Connection confirmation modal — only ever shown once a
            real, non-vertical-connector RouteEdge has been selected via
            handleEdgeClickForDeletion. Shows the two real endpoint
            RoutePoints' own display names (never ids), the edge_type, and
            the active map/floor. Confirming calls the existing RouteEdge
            delete endpoint; a failure keeps the edge selected/visible and
            surfaces a safe error message instead of removing anything. */}
        {mode === 'delete-connection' && selectedEdgeForDeletion && (
          <div
            onClick={handleCancelDeleteConnectionSelection}
            style={{
              position: 'fixed',
              inset: 0,
              zIndex: 10020,
              background: 'rgba(9, 26, 53, 0.78)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              padding: 20,
            }}
          >
            <div
              className="adm-form-card"
              onClick={(event) => event.stopPropagation()}
              style={{
                width: 'min(440px, 96vw)',
                padding: 24,
                textAlign: 'center',
              }}
            >
              <div className="adm-form-card-title">
                {t.deleteConnectionConfirmTitle}
              </div>

              <div
                style={{
                  fontSize: 13,
                  color: '#4a6a8f',
                  marginBottom: 14,
                  lineHeight: 1.8,
                  textAlign: isRTL ? 'right' : 'left',
                }}
              >
                <div>
                  <strong>{t.deleteConnectionFromLabel}:</strong>{' '}
                  {selectedEdgeForDeletion.fromPoint.name ||
                    selectedEdgeForDeletion.edge.from_point_id}
                </div>
                <div>
                  <strong>{t.deleteConnectionToLabel}:</strong>{' '}
                  {selectedEdgeForDeletion.toPoint.name ||
                    selectedEdgeForDeletion.edge.to_point_id}
                </div>
                <div>
                  <strong>{t.deleteConnectionTypeLabel}:</strong>{' '}
                  {selectedEdgeForDeletion.edge.edge_type}
                </div>
                {activeMap && (
                  <div>
                    <strong>{t.deleteConnectionFloorLabel}:</strong>{' '}
                    {activeMap.title ? `${activeMap.title} — ` : ''}
                    {formatFloorDisplay(activeMap.floor, activeMap.floorLabel)}
                  </div>
                )}
              </div>

              <div
                style={{
                  fontSize: 13,
                  color: '#173b70',
                  fontWeight: 600,
                  marginBottom: 18,
                }}
              >
                {t.deleteConnectionSafetyNote}
              </div>

              {deleteConnectionError && (
                <div
                  style={{
                    fontSize: 12.5,
                    color: '#c0392b',
                    marginBottom: 14,
                    fontWeight: 600,
                  }}
                >
                  {deleteConnectionError}
                </div>
              )}

              <div
                className="adm-form-actions"
                style={{ justifyContent: 'center' }}
              >
                <button
                  type="button"
                  className="adm-btn adm-btn-secondary"
                  onClick={handleCancelDeleteConnectionSelection}
                  disabled={isDeletingConnection}
                >
                  {t.cancel}
                </button>

                <button
                  type="button"
                  className="adm-btn adm-btn-danger"
                  onClick={handleConfirmDeleteConnection}
                  disabled={isDeletingConnection}
                >
                  {isDeletingConnection
                    ? t.deleteConnectionDeleting
                    : t.deleteConnectionConfirmButton}
                </button>
              </div>
            </div>
          </div>
        )}

        {/* Navigation-data-problem task, Part 3A — Generated-Only Cleanup
            preview/confirm modal. Read-only preview loaded by
            handleOpenGeneratedCleanup; apply only ever runs from the
            explicit confirm button below, never automatically. */}
        {cleanupPreview && (
          <div
            onClick={handleCloseGeneratedCleanup}
            style={{
              position: 'fixed',
              inset: 0,
              zIndex: 10030,
              background: 'rgba(9, 26, 53, 0.78)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              padding: 20,
            }}
          >
            <div
              className="adm-form-card"
              onClick={(event) => event.stopPropagation()}
              style={{
                width: 'min(520px, 96vw)',
                padding: 24,
                maxHeight: '90vh',
                overflowY: 'auto',
              }}
            >
              <div className="adm-form-card-title">{t.cleanupPreviewTitle}</div>

              <div
                style={{
                  fontSize: 13,
                  color: '#4a6a8f',
                  marginBottom: 14,
                  lineHeight: 1.9,
                  textAlign: isRTL ? 'right' : 'left',
                }}
              >
                <div>
                  <strong>{activeMap?.title}</strong>
                  {activeMap && ` — ${formatFloorDisplay(activeMap.floor, activeMap.floorLabel)}`}
                </div>
                <div>
                  <strong>{t.cleanupGeneratedPoints}:</strong>{' '}
                  {cleanupPreview.generated_point_count}
                </div>
                <div>
                  <strong>{t.cleanupGeneratedEdges}:</strong>{' '}
                  {cleanupPreview.generated_edge_count}
                </div>
                <div>
                  <strong>{t.cleanupManualPoints}:</strong>{' '}
                  {cleanupPreview.manual_point_count}
                </div>
                <div>
                  <strong>{t.cleanupManualEdges}:</strong>{' '}
                  {cleanupPreview.manual_edge_count}
                </div>
                <div>
                  <strong>{t.cleanupUnknownLegacy}:</strong>{' '}
                  {cleanupPreview.unknown_legacy_point_count}
                </div>
                <div>
                  <strong>{t.cleanupLinkedRooms}:</strong>{' '}
                  {cleanupPreview.rooms_linked_to_generated_points}
                </div>
                <div>
                  <strong>{t.cleanupLinkedConnectors}:</strong>{' '}
                  {cleanupPreview.vertical_connectors_linked_to_generated_points}
                </div>
                {cleanupPreview.dependent_manual_edge_count > 0 && (
                  <div>
                    <strong>{t.cleanupDependentEdges}:</strong>{' '}
                    {cleanupPreview.dependent_manual_edge_count}
                  </div>
                )}
              </div>

              {cleanupPreview.unknown_legacy_point_count > 0 && (
                <div
                  style={{
                    fontSize: 12,
                    color: '#8a6d16',
                    background: '#fff8e6',
                    borderRadius: 8,
                    padding: 10,
                    marginBottom: 14,
                  }}
                >
                  {t.cleanupUnknownLegacyNote}
                </div>
              )}

              {cleanupPreview.generated_point_count === 0 &&
                cleanupPreview.generated_edge_count === 0 && (
                <div
                  style={{
                    fontSize: 13,
                    color: '#315b8f',
                    marginBottom: 14,
                    fontWeight: 600,
                  }}
                >
                  {t.cleanupNoneToDelete}
                </div>
              )}

              {cleanupError && (
                <div
                  style={{
                    fontSize: 12.5,
                    color: '#c0392b',
                    marginBottom: 14,
                    fontWeight: 600,
                  }}
                >
                  {cleanupError}
                </div>
              )}

              <div className="adm-form-actions" style={{ justifyContent: 'center' }}>
                <button
                  type="button"
                  className="adm-btn adm-btn-secondary"
                  onClick={handleCloseGeneratedCleanup}
                  disabled={isCleanupApplying}
                >
                  {t.cancel}
                </button>

                <button
                  type="button"
                  className="adm-btn adm-btn-danger"
                  onClick={handleApplyGeneratedCleanup}
                  disabled={
                    isCleanupApplying ||
                    (cleanupPreview.generated_point_count === 0 &&
                      cleanupPreview.generated_edge_count === 0)
                  }
                >
                  {isCleanupApplying ? t.cleanupApplying : t.cleanupConfirmButton}
                </button>
              </div>
            </div>
          </div>
        )}

        {/* Navigation-data-problem task, Part 3B — Full Navigation Reset
            preview/confirm modal. Strictly separate from the
            generated-only cleanup modal above — deletes EVERY route
            point/connection on this map, including manual ones, and
            requires the admin to type the map's name or the fixed
            confirmation phrase before the confirm button is even
            enabled. */}
        {resetPreview && (
          <div
            onClick={handleCloseFullReset}
            style={{
              position: 'fixed',
              inset: 0,
              zIndex: 10030,
              background: 'rgba(9, 26, 53, 0.78)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              padding: 20,
            }}
          >
            <div
              className="adm-form-card"
              onClick={(event) => event.stopPropagation()}
              style={{
                width: 'min(540px, 96vw)',
                padding: 24,
                maxHeight: '90vh',
                overflowY: 'auto',
              }}
            >
              <div className="adm-form-card-title">{t.resetPreviewTitle}</div>

              <div
                style={{
                  fontSize: 12.5,
                  color: '#8a1f1f',
                  background: '#fdecec',
                  borderRadius: 8,
                  padding: 12,
                  marginBottom: 16,
                  fontWeight: 600,
                  lineHeight: 1.6,
                  textAlign: isRTL ? 'right' : 'left',
                }}
              >
                {t.resetWarning}
              </div>

              <div
                style={{
                  fontSize: 13,
                  color: '#4a6a8f',
                  marginBottom: 14,
                  lineHeight: 1.9,
                  textAlign: isRTL ? 'right' : 'left',
                }}
              >
                <div>
                  <strong>{resetPreview.map_name}</strong>
                  {resetPreview.floor !== null &&
                    resetPreview.floor !== undefined &&
                    ` — ${formatFloorDisplay(resetPreview.floor)}`}
                </div>
                <div>
                  <strong>{t.resetTotalPoints}:</strong>{' '}
                  {resetPreview.total_point_count}
                </div>
                <div>
                  <strong>{t.resetTotalEdges}:</strong>{' '}
                  {resetPreview.total_edge_count}
                </div>
                <div>
                  {t.resetBreakdownManual}: {resetPreview.point_source_breakdown?.manual ?? 0}
                  {' · '}
                  {t.resetBreakdownGenerated}: {resetPreview.point_source_breakdown?.generated ?? 0}
                  {' · '}
                  {t.resetBreakdownSemantic}: {resetPreview.point_source_breakdown?.semantic_destination ?? 0}
                  {' · '}
                  {t.resetBreakdownConnector}: {resetPreview.point_source_breakdown?.vertical_connector ?? 0}
                  {' · '}
                  {t.resetBreakdownUnknown}: {resetPreview.point_source_breakdown?.unknown_legacy ?? 0}
                </div>
                <div>
                  <strong>{t.resetLinkedRooms}:</strong>{' '}
                  {resetPreview.rooms_linked_count}
                </div>
                <div>
                  <strong>{t.resetLinkedConnectors}:</strong>{' '}
                  {resetPreview.vertical_connectors_linked_count}
                </div>
                <div>
                  <strong>{t.resetLinkedLocationCodes}:</strong>{' '}
                  {resetPreview.location_code_count}
                </div>
              </div>

              {resetPreview.total_point_count === 0 &&
                resetPreview.total_edge_count === 0 ? (
                <div
                  style={{
                    fontSize: 13,
                    color: '#315b8f',
                    marginBottom: 14,
                    fontWeight: 600,
                  }}
                >
                  {t.resetNoneToDelete}
                </div>
              ) : (
                <>
                  <div
                    style={{
                      fontSize: 12.5,
                      color: '#173b70',
                      fontWeight: 600,
                      marginBottom: 8,
                      textAlign: isRTL ? 'right' : 'left',
                    }}
                  >
                    {t.resetConfirmInstructions(resetPreview.map_name)}
                  </div>
                  <input
                    type="text"
                    className="adm-input"
                    value={resetConfirmText}
                    onChange={(event) => setResetConfirmText(event.target.value)}
                    placeholder={t.resetConfirmPlaceholder}
                    style={{ width: '100%', marginBottom: 14, boxSizing: 'border-box' }}
                  />
                </>
              )}

              {resetError && (
                <div
                  style={{
                    fontSize: 12.5,
                    color: '#c0392b',
                    marginBottom: 14,
                    fontWeight: 600,
                  }}
                >
                  {resetError}
                </div>
              )}

              <div className="adm-form-actions" style={{ justifyContent: 'center' }}>
                <button
                  type="button"
                  className="adm-btn adm-btn-secondary"
                  onClick={handleCloseFullReset}
                  disabled={isResetApplying}
                >
                  {t.cancel}
                </button>

                <button
                  type="button"
                  className="adm-btn adm-btn-danger"
                  onClick={handleApplyFullReset}
                  disabled={
                    isResetApplying ||
                    (resetPreview.total_point_count === 0 &&
                      resetPreview.total_edge_count === 0) ||
                    (resetConfirmText.trim() !== (resetPreview.map_name || '') &&
                      resetConfirmText.trim() !== 'RESET NAVIGATION DATA')
                  }
                >
                  {isResetApplying ? t.resetApplying : t.resetConfirmButton}
                </button>
              </div>
            </div>
          </div>
        )}

        {isMapOpen &&
          adminMapImageUrl && (
            <div
              onClick={() =>
                setIsMapOpen(false)
              }
              style={{
                position: 'fixed',
                inset: 0,
                background:
                  'rgba(0, 0, 0, 0.82)',
                zIndex: 9999,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                padding: 24,
              }}
            >
              {/* Editor workspace: the FULL usable modal area (toolbar +
                  map stage + floating panel + close button) — this, not the
                  narrow map stage below, is the FloatingToolPanel's
                  drag/dock/clamp boundary. On a portrait/vertical map the
                  map stage renders far narrower than this workspace, so the
                  leftover horizontal space becomes real, usable panel
                  gutters instead of dead space the panel could never
                  actually reach. Stops click propagation so an empty-gutter
                  click (grabbing/dropping the panel, or a stray misclick
                  near it) never closes the modal via the backdrop's own
                  onClick above; it never creates a RoutePoint either, since
                  RoutePoint creation is wired only to the map image itself
                  (see the map stage below and handleFullMapClick). */}
              <div
                ref={fullMapWorkspaceRef}
                onClick={(event) => event.stopPropagation()}
                style={{
                  position: 'relative',
                  width: '100%',
                  height: '100%',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                }}
              >
                {/* Map stage: the map image + its SVG marker/edge overlay
                    ONLY. This — and only this — is what every click-to-map-
                    coordinate calculation (handleFullMapClick,
                    syncFullMapMetrics) is based on. Sized/centered
                    independently of the workspace above (preserving the
                    map's own aspect ratio) so resizing or docking the panel
                    within the workspace can never change a single
                    RoutePoint's computed coordinates. */}
                <div
                  ref={fullMapContainerRef}
                  onClick={(event) =>
                    event.stopPropagation()
                  }
                  style={{
                    position: 'relative',
                    maxWidth: '96vw',
                    maxHeight: '90vh',
                  }}
                >
                <img
                  ref={fullMapImageRef}
                  src={adminMapImageUrl}
                  alt={
                    activeMap?.title ||
                    'Full map'
                  }
                  onLoad={
                    syncFullMapMetrics
                  }
                  onClick={
                    handleFullMapClick
                  }
                  style={{
                    display: 'block',
                    maxWidth: '96vw',
                    maxHeight: '90vh',
                    objectFit: 'contain',
                    borderRadius: 14,
                    background: 'white',
                    cursor: 'crosshair',
                  }}
                />

                {fullMapMetrics &&
                  (() => {
                    const radius = Math.max(
                      8,
                      fullMapMetrics.naturalWidth * 0.006,
                    );

                    // Native-pixel radius for the direct marker hit target
                    // below, sized the same "comfortable on screen"
                    // way as the click-fallback threshold so the clickable
                    // area always at least covers the visible marker.
                    const snapHitRadius = resolveSnapThresholdPx(
                      SNAP_SCREEN_PX,
                      fullMapMetrics.naturalWidth /
                        (fullMapMetrics.displayWidth || fullMapMetrics.naturalWidth),
                      SNAP_MIN_NATIVE_PX,
                    );

                    return (
                      <svg
                        viewBox={`0 0 ${fullMapMetrics.naturalWidth} ${fullMapMetrics.naturalHeight}`}
                        preserveAspectRatio="xMidYMid meet"
                        style={{
                          position: 'absolute',
                          inset: 0,
                          width: '100%',
                          height: '100%',
                          pointerEvents: 'none',
                        }}
                      >
                        {/* Route edges — drawn first so points sit on top */}
                        {resolvedEdges.map(
                          ({ edge, fromPoint, toPoint }) => {
                            const style = getEdgeStyle(
                              edge.edge_type,
                            );

                            const edgeId = edge.id || edge._id;

                            const isDeleteConnectionMode =
                              mode === 'delete-connection';

                            const selectedEdgeId =
                              selectedEdgeForDeletion?.edge &&
                              (selectedEdgeForDeletion.edge.id ||
                                selectedEdgeForDeletion.edge._id);

                            const isSelectedForDeletion =
                              isDeleteConnectionMode &&
                              selectedEdgeId != null &&
                              selectedEdgeId === edgeId;

                            // The visible line's own geometry is never
                            // touched by delete-connection mode — same
                            // x1/y1/x2/y2/strokeDasharray/strokeLinecap as
                            // always. Its stroke color only changes to
                            // highlight the exact edge currently selected
                            // for deletion (Section 5's "visually highlight
                            // that exact edge" requirement) — every other
                            // edge, in every other mode, renders exactly as
                            // before.
                            return (
                              <g key={edgeId}>
                                <line
                                  x1={fromPoint.x}
                                  y1={fromPoint.y}
                                  x2={toPoint.x}
                                  y2={toPoint.y}
                                  stroke={
                                    isSelectedForDeletion
                                      ? '#e63946'
                                      : style.stroke
                                  }
                                  strokeWidth={
                                    isSelectedForDeletion
                                      ? Math.max(
                                          4,
                                          fullMapMetrics.naturalWidth * 0.003,
                                        )
                                      : Math.max(
                                          2,
                                          fullMapMetrics.naturalWidth * 0.0015,
                                        )
                                  }
                                  strokeDasharray={style.dash}
                                  strokeLinecap="round"
                                />

                                {/* Invisible, wider clickable overlay — only
                                    rendered while Delete Connection mode is
                                    active. Follows the exact same x1/y1/x2/y2
                                    coordinates as the visible line above (no
                                    separate geometry), uses
                                    pointerEvents="stroke" so only its own
                                    stroke area (not its transparent fill/
                                    bounding box) is clickable, and carries
                                    the real edge/fromPoint/toPoint objects
                                    straight into the click handler — never a
                                    proximity/coordinate-based lookup. */}
                                {isDeleteConnectionMode && (
                                  <line
                                    x1={fromPoint.x}
                                    y1={fromPoint.y}
                                    x2={toPoint.x}
                                    y2={toPoint.y}
                                    stroke="transparent"
                                    strokeWidth={Math.max(
                                      20,
                                      fullMapMetrics.naturalWidth * 0.012,
                                    )}
                                    strokeLinecap="round"
                                    pointerEvents="stroke"
                                    style={{
                                      pointerEvents: 'stroke',
                                      cursor: 'pointer',
                                    }}
                                    onClick={(event) =>
                                      handleEdgeClickForDeletion(
                                        edge,
                                        fromPoint,
                                        toPoint,
                                        event,
                                      )
                                    }
                                  />
                                )}
                              </g>
                            );
                          },
                        )}

                        {/* Auto Connect Destinations to Corridors — proposed
                            connections as TEMPORARY dashed overlay lines
                            only (Section 8: "Show proposed edges as
                            temporary overlays only... must not create
                            RouteEdges in MongoDB"). Resolved entirely from
                            data already in state (pointsById), never from
                            a separate coordinate fetch. Only proposals for
                            THIS map are drawn — a map_group-scope proposal
                            belonging to a different floor's map has no
                            line here, but still appears in the review
                            panel/list. */}
                        {mode === 'auto-connect' &&
                          autoConnectProposals
                            .filter((proposal) => proposal.status === 'proposed')
                            .map((proposal) => {
                              const fromPoint = pointsById.get(
                                proposal.destination_point_id,
                              );

                              // The selected candidate is either an
                              // existing corridor point or a projected
                              // attachment partway along a corridor edge —
                              // the latter has no RoutePoint to look up
                              // until the proposal is applied, so the line
                              // is drawn to its projected coordinates.
                              const selected = (proposal.candidates || []).find(
                                (candidate) =>
                                  autoConnectCandidateKey(candidate) ===
                                  proposal.selectedCandidateKey,
                              );

                              const toPoint =
                                pointsById.get(
                                  selected?.point_id || proposal.selectedCandidateKey,
                                ) ||
                                (selected?.attachment_x != null &&
                                selected?.attachment_y != null
                                  ? { x: selected.attachment_x, y: selected.attachment_y }
                                  : null);

                              if (!fromPoint || !toPoint) {
                                return null;
                              }

                              let stroke = '#8e44ad';
                              let opacity = 0.85;

                              if (proposal.localStatus === 'accepted') {
                                stroke = '#27ae60';
                                opacity = 0.95;
                              } else if (proposal.localStatus === 'rejected') {
                                stroke = '#95a5a6';
                                opacity = 0.4;
                              } else if (proposal.confidence === 'high') {
                                stroke = '#2ecc71';
                              } else if (proposal.confidence === 'medium') {
                                stroke = '#f39c12';
                              } else if (proposal.confidence === 'low') {
                                stroke = '#e67e22';
                              } else if (proposal.confidence === 'needs_review') {
                                stroke = '#8e44ad';
                              }

                              return (
                                <line
                                  key={`auto-connect-preview-${proposal.destination_point_id}`}
                                  x1={fromPoint.x}
                                  y1={fromPoint.y}
                                  x2={toPoint.x}
                                  y2={toPoint.y}
                                  stroke={stroke}
                                  strokeWidth={Math.max(
                                    2,
                                    fullMapMetrics.naturalWidth * 0.002,
                                  )}
                                  strokeDasharray="6 6"
                                  strokeLinecap="round"
                                  opacity={opacity}
                                />
                              );
                            })}

                        {/* Create Destinations from Approved Analysis —
                            proposed destination points as TEMPORARY
                            markers only (Section 6: "Show temporary point
                            overlays on the current map... No Room,
                            RoutePoint or RouteEdge may be created during
                            preview"). Only proposals with a real x/y
                            (either an existing linked point, or a
                            location the admin just clicked) are drawn. */}
                        {mode === 'semantic-destinations' &&
                          semanticDestProposals
                            .filter(
                              (proposal) =>
                                proposal.localStatus !== 'rejected' &&
                                proposal.localStatus !== 'excluded' &&
                                proposal.x != null &&
                                proposal.y != null,
                            )
                            .map((proposal) => (
                              <circle
                                key={`semantic-dest-preview-${proposal.semantic_item_id}`}
                                cx={proposal.x}
                                cy={proposal.y}
                                r={Math.max(8, fullMapMetrics.naturalWidth * 0.006)}
                                fill={
                                  proposal.localStatus === 'accepted'
                                    ? '#27ae60'
                                    : '#f39c12'
                                }
                                stroke="white"
                                strokeWidth={2}
                                strokeDasharray="3 3"
                                opacity={0.9}
                              />
                            ))}

                        {/* Fast batch destination placement — a distinct
                            pulsing highlight ring around the CURRENTLY
                            ACTIVE queue item's temporary marker (or around
                            where it will appear once placed), clearly
                            distinguishable from both the plain proposal
                            dots above and every real saved RoutePoint
                            below (Section 3: "Temporary markers must be
                            visually distinguishable from existing saved
                            RoutePoints"). */}
                        {mode === 'semantic-destinations' &&
                          semanticBatchActive &&
                          (() => {
                            const activeItemId = semanticBatchQueue[semanticBatchIndex];
                            const activeProposal = semanticDestProposals.find(
                              (proposal) => proposal.semantic_item_id === activeItemId,
                            );
                            if (!activeProposal || activeProposal.x == null || activeProposal.y == null) {
                              return null;
                            }
                            return (
                              <circle
                                key={`semantic-batch-active-${activeItemId}`}
                                cx={activeProposal.x}
                                cy={activeProposal.y}
                                r={Math.max(16, fullMapMetrics.naturalWidth * 0.012)}
                                fill="none"
                                stroke="#2d6cdf"
                                strokeWidth={3}
                                opacity={0.85}
                              />
                            );
                          })()}

                        {/* ── Automatic Navigation Build preview overlay ──
                            READ-ONLY. Every shape here is a PROPOSAL held
                            in memory on the client; none of it exists in
                            the database. Styles are deliberately distinct
                            from saved RoutePoints and RouteEdges below so
                            a proposal can never be mistaken for something
                            that was actually created. */}
                        {navBuildOpen && navBuildResult && (
                          <g>
                            {navBuildLayers.region &&
                              (navBuildResult.region_polygons || [])
                                .filter((polygon) => polygon.decision === 'interior')
                                .map((polygon, index) => (
                                  <polygon
                                    key={`nb-region-${index}`}
                                    points={polygon.points
                                      .map((point) => `${point[0]},${point[1]}`)
                                      .join(' ')}
                                    fill="#1b7f4b"
                                    fillOpacity={0.10}
                                    stroke="#1b7f4b"
                                    strokeWidth={3}
                                    strokeOpacity={0.85}
                                  />
                                ))}

                            {navBuildLayers.rejected &&
                              (navBuildResult.region_polygons || [])
                                .filter((polygon) => polygon.decision === 'rejected')
                                .map((polygon, index) => (
                                  <polygon
                                    key={`nb-rejected-${index}`}
                                    points={polygon.points
                                      .map((point) => `${point[0]},${point[1]}`)
                                      .join(' ')}
                                    fill="#b03030"
                                    fillOpacity={0.06}
                                    stroke="#b03030"
                                    strokeWidth={2}
                                    strokeDasharray="10 6"
                                    strokeOpacity={0.8}
                                  />
                                ))}

                            {navBuildLayers.rejectedEdges &&
                              (navBuildResult.rejected_edges || []).map((edge, index) => (
                                <line
                                  key={`nb-rejedge-${index}`}
                                  x1={edge.from_point[0]}
                                  y1={edge.from_point[1]}
                                  x2={edge.to_point[0]}
                                  y2={edge.to_point[1]}
                                  stroke="#c0392b"
                                  strokeWidth={2}
                                  strokeDasharray="4 5"
                                  opacity={0.7}
                                />
                              ))}

                            {navBuildLayers.graph && (() => {
                              const nodeByIndex = {};
                              (navBuildResult.graph_nodes || []).forEach((node) => {
                                nodeByIndex[node.index] = node;
                              });

                              return (
                                <>
                                  {(navBuildResult.graph_edges || []).map((edge, index) => {
                                    const from = nodeByIndex[edge.from_index];
                                    const to = nodeByIndex[edge.to_index];
                                    if (!from || !to) return null;
                                    return (
                                      <line
                                        key={`nb-edge-${index}`}
                                        x1={from.x}
                                        y1={from.y}
                                        x2={to.x}
                                        y2={to.y}
                                        stroke="#2d6cdf"
                                        strokeWidth={4}
                                        strokeLinecap="round"
                                        opacity={0.85}
                                      />
                                    );
                                  })}
                                  {(navBuildResult.graph_nodes || []).map((node) => (
                                    <circle
                                      key={`nb-node-${node.index}`}
                                      cx={node.x}
                                      cy={node.y}
                                      r={Math.max(5, fullMapMetrics.naturalWidth * 0.0035)}
                                      fill="#2d6cdf"
                                      stroke="white"
                                      strokeWidth={2}
                                      opacity={0.95}
                                    />
                                  ))}
                                </>
                              );
                            })()}

                            {navBuildLayers.attachments &&
                              (navBuildResult.rooms || []).map((room) => {
                                if (!room.arrival_point || !room.attachment) return null;
                                if (room.attachment.node_x == null) return null;
                                return (
                                  <line
                                    key={`nb-attach-${room.semantic_item_id}`}
                                    x1={room.arrival_point.x}
                                    y1={room.arrival_point.y}
                                    x2={room.attachment.node_x}
                                    y2={room.attachment.node_y}
                                    stroke="#7a4bd0"
                                    strokeWidth={3}
                                    strokeDasharray="8 5"
                                    opacity={0.9}
                                  />
                                );
                              })}

                            {navBuildLayers.arrivals &&
                              (navBuildResult.rooms || []).map((room) => {
                                if (!room.arrival_point) return null;
                                return (
                                  <circle
                                    key={`nb-arrival-${room.semantic_item_id}`}
                                    cx={room.arrival_point.x}
                                    cy={room.arrival_point.y}
                                    r={Math.max(7, fullMapMetrics.naturalWidth * 0.005)}
                                    fill="#e08a00"
                                    stroke="white"
                                    strokeWidth={2}
                                    opacity={0.95}
                                  />
                                );
                              })}
                          </g>
                        )}

                        {/* Existing saved route points */}
                        {routePoints.map((point) => {
                          const pointX = Number(point.x);
                          const pointY = Number(point.y);

                          if (
                            !Number.isFinite(pointX) ||
                            !Number.isFinite(pointY)
                          ) {
                            return null;
                          }

                          const isVertical = VERTICAL_TRANSIT_TYPES.has(
                            point.point_type,
                          );

                          const color = getPointColor(
                            point.point_type,
                          );

                          const key =
                            point.id ||
                            point._id ||
                            `${point.x}-${point.y}-${point.name}`;

                          // Direct, deterministic reuse target: only live
                          // while Draw Walkable Path is active. The parent
                          // <svg> is pointerEvents: none (so it never
                          // blocks the underlying map click for placing new
                          // points or other modes), but this single hit
                          // target opts back into pointer events so a click
                          // that lands on it is resolved by identity via
                          // selectExistingPointForDraft — never by
                          // recomputing "which point is this" from
                          // coordinates.
                          const isDrawTarget = mode === 'draw';

                          // Edit Route Points mode (Phase 13): every
                          // marker becomes a selectable hit target while
                          // this mode is active — selecting it opens the
                          // detail panel via selectPointForEditing.
                          const isEditPointsTarget = mode === 'edit-points';
                          const isBeingEdited =
                            isEditPointsTarget &&
                            editPointTarget &&
                            editPointTarget.id === point.id;

                          // Auto Connect Destinations manual-pick sub-
                          // interaction: only while a manual pick is
                          // pending (Section 8: "click a different
                          // corridor point manually"), and only for a
                          // real, valid transit-type point — never for a
                          // Room/Store/entrance/stairs/elevator marker,
                          // which the backend's own apply-time
                          // revalidation would reject anyway.
                          const isAutoConnectPickTarget =
                            mode === 'auto-connect' &&
                            Boolean(autoConnectManualPickTargetId) &&
                            AUTO_CONNECT_TRANSIT_TYPES.has(point.point_type);

                          return (
                            <g key={key}>
                              {isDrawTarget && (
                                <circle
                                  cx={pointX}
                                  cy={pointY}
                                  r={Math.max(radius * 1.8, snapHitRadius)}
                                  fill="transparent"
                                  style={{
                                    pointerEvents: 'auto',
                                    cursor: 'pointer',
                                  }}
                                  onClick={(event) =>
                                    selectExistingPointForDraft(point, event)
                                  }
                                />
                              )}

                              {isEditPointsTarget && (
                                <circle
                                  cx={pointX}
                                  cy={pointY}
                                  r={Math.max(radius * 1.8, snapHitRadius)}
                                  fill="transparent"
                                  style={{
                                    pointerEvents: 'auto',
                                    cursor: 'pointer',
                                  }}
                                  onClick={(event) =>
                                    selectPointForEditing(point, event)
                                  }
                                />
                              )}

                              {isBeingEdited && (
                                <circle
                                  cx={pointX}
                                  cy={pointY}
                                  r={radius * 2.6}
                                  fill="none"
                                  stroke="#ffb020"
                                  strokeWidth={radius * 0.35}
                                  style={{ pointerEvents: 'none' }}
                                >
                                  <animate
                                    attributeName="opacity"
                                    values="1;0.35;1"
                                    dur="1.2s"
                                    repeatCount="indefinite"
                                  />
                                </circle>
                              )}

                              {isAutoConnectPickTarget && (
                                <circle
                                  cx={pointX}
                                  cy={pointY}
                                  r={Math.max(radius * 1.8, snapHitRadius)}
                                  fill="transparent"
                                  style={{
                                    pointerEvents: 'auto',
                                    cursor: 'pointer',
                                  }}
                                  onClick={(event) => {
                                    event.stopPropagation();
                                    selectManualCorridorPoint(point);
                                  }}
                                />
                              )}

                              {isVertical ? (
                                <rect
                                  x={pointX - radius}
                                  y={pointY - radius}
                                  width={radius * 2}
                                  height={radius * 2}
                                  fill={color}
                                  stroke="white"
                                  strokeWidth={radius * 0.25}
                                  style={
                                    isDrawTarget
                                      ? { pointerEvents: 'none' }
                                      : undefined
                                  }
                                  transform={`rotate(45 ${pointX} ${pointY})`}
                                />
                              ) : (
                                <circle
                                  cx={pointX}
                                  cy={pointY}
                                  r={radius}
                                  fill={color}
                                  stroke="white"
                                  strokeWidth={radius * 0.25}
                                  style={
                                    isDrawTarget
                                      ? { pointerEvents: 'none' }
                                      : undefined
                                  }
                                />
                              )}

                              {LABELED_POINT_TYPES.has(
                                point.point_type,
                              ) &&
                                point.name && (
                                  <text
                                    x={pointX}
                                    y={pointY - radius - 6}
                                    textAnchor="middle"
                                    fontSize={
                                      fullMapMetrics.naturalWidth * 0.012
                                    }
                                    fontWeight="700"
                                    fill="#173b70"
                                    stroke="white"
                                    strokeWidth={2}
                                    paintOrder="stroke"
                                    style={
                                      isDrawTarget
                                        ? { pointerEvents: 'none' }
                                        : undefined
                                    }
                                  >
                                    {point.name}
                                  </text>
                                )}
                            </g>
                          );
                        })}

                        {/* Test Route result — visually distinct from normal graph edges:
                            solid, thick, bright green vs. the light blue/red dashed
                            edges used for the real graph. */}
                        {mode === 'test' &&
                          testResult &&
                          (() => {
                            const testPathPoints = (
                              testResult.path_point_ids || []
                            )
                              .map((id) => pointsById.get(id))
                              .filter(Boolean);

                            if (testPathPoints.length < 2) return null;

                            return (
                              <>
                                <polyline
                                  points={testPathPoints
                                    .map((p) => `${p.x},${p.y}`)
                                    .join(' ')}
                                  fill="none"
                                  stroke="#16a34a"
                                  strokeWidth={Math.max(
                                    3,
                                    fullMapMetrics.naturalWidth * 0.0025,
                                  )}
                                  strokeLinecap="round"
                                  strokeLinejoin="round"
                                />
                                {testPathPoints.map((p, index) => (
                                  <circle
                                    key={`test-${p.id || p._id || index}`}
                                    cx={p.x}
                                    cy={p.y}
                                    r={radius * 0.7}
                                    fill="#16a34a"
                                    stroke="white"
                                    strokeWidth={radius * 0.2}
                                  />
                                ))}
                              </>
                            );
                          })()}

                        {/* In-progress clicked point (not yet saved) — Add Point mode only */}
                        {mode === 'point' &&
                          clickedPoint &&
                          Number.isFinite(Number(clickedPoint.x)) &&
                          Number.isFinite(Number(clickedPoint.y)) && (
                            <circle
                              cx={clickedPoint.x}
                              cy={clickedPoint.y}
                              r={radius * 1.15}
                              fill="red"
                              stroke="white"
                              strokeWidth={radius * 0.3}
                            />
                          )}

                        {/* Calibrate Scale: clear markers for the two clicked
                            calibration points, in the map's real image
                            coordinate system (same viewBox as everything
                            else here), with their coordinates shown as text
                            per the calibration flow requirements. */}
                        {mode === 'calibrate' &&
                          calibrationPointA &&
                          calibrationPointB && (
                            <line
                              x1={calibrationPointA.x}
                              y1={calibrationPointA.y}
                              x2={calibrationPointB.x}
                              y2={calibrationPointB.y}
                              stroke="#ff8c00"
                              strokeWidth={Math.max(
                                2,
                                fullMapMetrics.naturalWidth * 0.0015,
                              )}
                              strokeDasharray="6 5"
                              strokeLinecap="round"
                            />
                          )}

                        {mode === 'calibrate' && calibrationPointA && (
                          <g>
                            <circle
                              cx={calibrationPointA.x}
                              cy={calibrationPointA.y}
                              r={radius * 1.15}
                              fill="#ff8c00"
                              stroke="white"
                              strokeWidth={radius * 0.3}
                            />
                            <text
                              x={calibrationPointA.x}
                              y={calibrationPointA.y - radius * 1.8}
                              textAnchor="middle"
                              fontSize={fullMapMetrics.naturalWidth * 0.013}
                              fontWeight="700"
                              fill="#173b70"
                              stroke="white"
                              strokeWidth={2}
                              paintOrder="stroke"
                            >
                              {`${t.calibratePointA} (${calibrationPointA.x}, ${calibrationPointA.y})`}
                            </text>
                          </g>
                        )}

                        {mode === 'calibrate' && calibrationPointB && (
                          <g>
                            <circle
                              cx={calibrationPointB.x}
                              cy={calibrationPointB.y}
                              r={radius * 1.15}
                              fill="#0ea5a5"
                              stroke="white"
                              strokeWidth={radius * 0.3}
                            />
                            <text
                              x={calibrationPointB.x}
                              y={calibrationPointB.y - radius * 1.8}
                              textAnchor="middle"
                              fontSize={fullMapMetrics.naturalWidth * 0.013}
                              fontWeight="700"
                              fill="#173b70"
                              stroke="white"
                              strokeWidth={2}
                              paintOrder="stroke"
                            >
                              {`${t.calibratePointB} (${calibrationPointB.x}, ${calibrationPointB.y})`}
                            </text>
                          </g>
                        )}

                        {/* Preview-only dashed lines to the nearest existing
                            point each new draft point might auto-merge with
                            (only shown for the "nearby" merge mode) — a
                            visual hint, not a guarantee of what the backend
                            will actually connect on save. */}
                        {mode === 'draw' &&
                          mergeMode === 'nearby' &&
                          nearbyMergePreview.map((preview) => (
                            <line
                              key={`merge-preview-${preview.draftIndex}-${preview.toPointId}`}
                              x1={preview.fromX}
                              y1={preview.fromY}
                              x2={preview.toX}
                              y2={preview.toY}
                              stroke="#8e44ad"
                              strokeWidth={Math.max(
                                1.5,
                                fullMapMetrics.naturalWidth * 0.001,
                              )}
                              strokeDasharray="4 5"
                              strokeLinecap="round"
                              opacity={0.75}
                            />
                          ))}

                        {/* Draw Walkable Path draft — live polyline + draft points */}
                        {mode === 'draw' && draftPoints.length > 1 && (
                          <polyline
                            points={draftPoints
                              .map((point) => `${point.x},${point.y}`)
                              .join(' ')}
                            fill="none"
                            stroke="#f2b705"
                            strokeWidth={Math.max(
                              2,
                              fullMapMetrics.naturalWidth * 0.0018,
                            )}
                            strokeDasharray="10 6"
                            strokeLinecap="round"
                            strokeLinejoin="round"
                          />
                        )}

                        {mode === 'draw' &&
                          draftPoints.map((point, index) => (
                            <g key={point.tempId}>
                              {point.kind === 'existing' && (
                                <circle
                                  cx={point.x}
                                  cy={point.y}
                                  r={radius * 1.6}
                                  fill="none"
                                  stroke="#2ecc71"
                                  strokeWidth={radius * 0.35}
                                />
                              )}
                              <circle
                                cx={point.x}
                                cy={point.y}
                                r={radius * 0.85}
                                fill={
                                  point.kind === 'existing'
                                    ? '#2ecc71'
                                    : '#f2b705'
                                }
                                stroke="white"
                                strokeWidth={radius * 0.22}
                              />
                              <text
                                x={point.x}
                                y={point.y - radius * 1.9}
                                textAnchor="middle"
                                fontSize={fullMapMetrics.naturalWidth * 0.011}
                                fontWeight="700"
                                fill="#173b70"
                                stroke="white"
                                strokeWidth={2}
                                paintOrder="stroke"
                              >
                                {index + 1}
                              </text>
                            </g>
                          ))}
                      </svg>
                    );
                  })()}

                {/* ── Floating "Navigation Tools" toolbox ──
                    Replaces the fixed horizontal pill that used to run
                    across the top of the plan. Same eleven tools, same
                    handlers, same active states — regrouped into a
                    draggable, collapsible panel so the floor plan is no
                    longer covered by its own controls. */}
                {toolboxPosition && (
                  <MapToolboxPanel
                    groups={mapToolGroups}
                    position={toolboxPosition}
                    onPositionChange={setToolboxPosition}
                    isCollapsed={toolboxCollapsed}
                    onToggleCollapse={() =>
                      setToolboxCollapsed((previous) => !previous)
                    }
                    containerRef={fullMapWorkspaceRef}
                    isRTL={isRTL}
                    title={t.toolboxTitle}
                    labels={{
                      move: t.toolboxMove,
                      minimize: t.toolboxMinimize,
                      restore: t.toolboxRestore,
                    }}
                  />
                )}

                {mode === 'connector' && (
                  <div
                    style={{
                      position: 'absolute',
                      left: '50%',
                      bottom: 18,
                      transform: 'translateX(-50%)',
                      background: 'rgba(20, 55, 105, 0.92)',
                      color: 'white',
                      padding: '10px 16px',
                      borderRadius: 999,
                      fontSize: 13,
                      fontWeight: 700,
                      pointerEvents: 'none',
                      whiteSpace: 'nowrap',
                    }}
                  >
                    {activeMap?.mapGroupId
                      ? 'Select a connector, then click its real location on this floor'
                      : 'This floor has no Map Group — add it via Map Groups to use vertical connectors'}
                  </div>
                )}

                {mode === 'point' && (
                  <div
                    style={{
                      position: 'absolute',
                      left: '50%',
                      bottom: 18,
                      transform:
                        'translateX(-50%)',
                      background:
                        'rgba(20, 55, 105, 0.92)',
                      color: 'white',
                      padding: '10px 16px',
                      borderRadius: 999,
                      fontSize: 13,
                      fontWeight: 700,
                      pointerEvents: 'none',
                      whiteSpace: 'nowrap',
                    }}
                  >
                    {t.selectPoint}
                  </div>
                )}

                {mode === 'calibrate' && (
                  <div
                    style={{
                      position: 'absolute',
                      left: '50%',
                      bottom: 18,
                      transform: 'translateX(-50%)',
                      background: 'rgba(20, 55, 105, 0.92)',
                      color: 'white',
                      padding: '10px 16px',
                      borderRadius: 16,
                      fontSize: 13,
                      fontWeight: 700,
                      whiteSpace: 'nowrap',
                      display: 'flex',
                      flexDirection: 'column',
                      alignItems: 'center',
                      gap: 8,
                    }}
                  >
                    <div style={{ pointerEvents: 'none' }}>
                      {!calibrationPointA &&
                        t.calibrateInstructions}
                      {calibrationPointA &&
                        !calibrationPointB &&
                        `${t.calibratePointA}: (${calibrationPointA.x}, ${calibrationPointA.y}) — ${t.calibrateInstructions}`}
                      {calibrationPointA &&
                        calibrationPointB &&
                        `${t.calibratePointA}: (${calibrationPointA.x}, ${calibrationPointA.y})   ${t.calibratePointB}: (${calibrationPointB.x}, ${calibrationPointB.y})`}
                    </div>

                    <div style={{ display: 'flex', gap: 8 }}>
                      <button
                        type="button"
                        onClick={resetCalibrationPoints}
                        disabled={!calibrationPointA && !calibrationPointB}
                        style={{
                          border: '1px solid rgba(255,255,255,0.6)',
                          borderRadius: 999,
                          padding: '6px 12px',
                          fontSize: 12,
                          fontWeight: 700,
                          cursor:
                            !calibrationPointA && !calibrationPointB
                              ? 'default'
                              : 'pointer',
                          background: 'transparent',
                          color: 'white',
                          opacity:
                            !calibrationPointA && !calibrationPointB ? 0.5 : 1,
                        }}
                      >
                        {t.calibrateReset}
                      </button>

                      <button
                        type="button"
                        onClick={handleCancelCalibration}
                        style={{
                          border: 'none',
                          borderRadius: 999,
                          padding: '6px 12px',
                          fontSize: 12,
                          fontWeight: 700,
                          cursor: 'pointer',
                          background: 'white',
                          color: '#173b70',
                        }}
                      >
                        {t.calibrateCancel}
                      </button>
                    </div>
                  </div>
                )}

                {mode === 'delete-connection' && !selectedEdgeForDeletion && (
                  <div
                    style={{
                      position: 'absolute',
                      left: '50%',
                      bottom: 18,
                      transform: 'translateX(-50%)',
                      background: 'rgba(20, 55, 105, 0.92)',
                      color: 'white',
                      padding: '10px 16px',
                      borderRadius: 16,
                      fontSize: 13,
                      fontWeight: 700,
                      whiteSpace: 'nowrap',
                      display: 'flex',
                      flexDirection: 'column',
                      alignItems: 'center',
                      gap: 8,
                    }}
                  >
                    <div style={{ pointerEvents: 'none' }}>
                      {deleteConnectionVerticalNotice
                        ? t.deleteConnectionVerticalBlocked
                        : t.deleteConnectionInstructions}
                    </div>

                    <button
                      type="button"
                      onClick={handleCancelDeleteConnectionMode}
                      style={{
                        border: 'none',
                        borderRadius: 999,
                        padding: '6px 12px',
                        fontSize: 12,
                        fontWeight: 700,
                        cursor: 'pointer',
                        background: 'white',
                        color: '#173b70',
                      }}
                    >
                      {t.deleteConnectionCancelMode}
                    </button>
                  </div>
                )}
                </div>
                {/* ↑ map stage (fullMapContainerRef) closes here — every
                    element below is a workspace-level sibling, positioned
                    and clamped against the workspace, never the map stage. */}

                {/* Edit Route Points mode — instructions bubble, shown
                    whenever the mode is active but nothing is selected
                    yet (mirrors the delete-connection instructions bubble
                    above). */}
                {mode === 'edit-points' && !editPointTarget && (
                  <div
                    style={{
                      position: 'absolute',
                      left: '50%',
                      bottom: 18,
                      transform: 'translateX(-50%)',
                      background: 'rgba(20, 55, 105, 0.92)',
                      color: 'white',
                      padding: '10px 16px',
                      borderRadius: 16,
                      fontSize: 13,
                      fontWeight: 700,
                      whiteSpace: 'nowrap',
                      pointerEvents: 'none',
                    }}
                  >
                    {t.editPointsInstructions}
                  </div>
                )}

                {/* Edit Route Points mode — detail panel for the
                    currently-selected existing point. Now a real
                    FloatingToolPanel like every other map-workspace
                    panel: draggable, collapsible, and raised to the
                    front on click. Its own position lives under its own
                    localStorage key (MAP_PANEL_IDS.editPoint) — it does
                    NOT share the `panelPosition` state the Add Point /
                    Draw / Test Route panels use. Every action it offered
                    before (Move Point, Edit Name, Edit Point Type,
                    inspect connected edges / linked Room / linked
                    vertical connector, Delete with confirmation) is
                    unchanged; the old × close button is now the footer's
                    Close. */}
                {mode === 'edit-points' &&
                  editPointTarget &&
                  mapPanels[MAP_PANEL_IDS.editPoint]?.position && (
                  <FloatingToolPanel
                    title={t.editPointsPanelTitle}
                    {...buildMapPanelProps(MAP_PANEL_IDS.editPoint)}
                    footer={
                      <div className="adm-form-actions">
                        <button
                          type="button"
                          className="adm-btn adm-btn-secondary"
                          onClick={closeEditPointPanel}
                          style={{ flex: 1 }}
                        >
                          {t.cancel || 'Close'}
                        </button>
                      </div>
                    }
                  >
                    <div style={{ color: '#173b70', fontSize: 13 }}>

                    {editPointError && (
                      <div
                        style={{
                          background: '#ffe9e9',
                          color: '#a92323',
                          borderRadius: 10,
                          padding: 8,
                          marginBottom: 10,
                          fontSize: 12,
                        }}
                      >
                        {editPointError}
                      </div>
                    )}

                    <label style={{ display: 'block', fontSize: 11.5, fontWeight: 700, marginBottom: 4 }}>
                      {t.editPointsNameLabel}
                    </label>
                    <input
                      value={editPointDraftName}
                      onChange={(e) => setEditPointDraftName(e.target.value)}
                      style={{
                        width: '100%',
                        padding: '7px 10px',
                        borderRadius: 10,
                        border: '1px solid #d6dee9',
                        marginBottom: 10,
                        fontSize: 13,
                        boxSizing: 'border-box',
                      }}
                    />

                    <label style={{ display: 'block', fontSize: 11.5, fontWeight: 700, marginBottom: 4 }}>
                      {t.editPointsTypeLabel}
                    </label>
                    <select
                      value={editPointDraftType}
                      onChange={(e) => setEditPointDraftType(e.target.value)}
                      style={{
                        width: '100%',
                        padding: '7px 10px',
                        borderRadius: 10,
                        border: '1px solid #d6dee9',
                        marginBottom: 10,
                        fontSize: 13,
                        boxSizing: 'border-box',
                      }}
                    >
                      {['entrance', 'hallway', 'stairs', 'elevator', 'room', 'store', 'junction'].map(
                        (option) => (
                          <option key={option} value={option}>
                            {option}
                          </option>
                        ),
                      )}
                    </select>

                    <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
                      <button
                        type="button"
                        onClick={handleEditPointSaveDetails}
                        disabled={editPointSaving}
                        style={{
                          flex: 1,
                          border: 'none',
                          borderRadius: 10,
                          padding: '8px 10px',
                          fontSize: 12.5,
                          fontWeight: 700,
                          cursor: editPointSaving ? 'default' : 'pointer',
                          background: '#173b70',
                          color: 'white',
                          opacity: editPointSaving ? 0.6 : 1,
                        }}
                      >
                        {t.save || 'Save'}
                      </button>

                      <button
                        type="button"
                        onClick={() => setEditPointMoving((v) => !v)}
                        disabled={editPointSaving}
                        style={{
                          flex: 1,
                          border: '1px solid #173b70',
                          borderRadius: 10,
                          padding: '8px 10px',
                          fontSize: 12.5,
                          fontWeight: 700,
                          cursor: editPointSaving ? 'default' : 'pointer',
                          background: editPointMoving ? '#173b70' : 'white',
                          color: editPointMoving ? 'white' : '#173b70',
                        }}
                      >
                        {editPointMoving ? t.editPointsMovingActive : t.editPointsMovePoint}
                      </button>
                    </div>

                    <div style={{ borderTop: '1px solid #eef1f6', paddingTop: 10, marginBottom: 10 }}>
                      <div style={{ fontWeight: 700, fontSize: 11.5, marginBottom: 4 }}>
                        {t.editPointsConnectedEdges} (
                        {editPointEdgesLoading ? '…' : editPointEdges.length})
                      </div>
                      {!editPointEdgesLoading && editPointEdges.length === 0 && (
                        <div style={{ color: '#8b97a8', fontSize: 12 }}>{t.editPointsNone}</div>
                      )}
                      {editPointEdges.map((edge) => (
                        <div key={edge.id} style={{ fontSize: 12, color: '#3a4a63', marginBottom: 2 }}>
                          {edge.edge_type || '—'}
                          {edge.is_accessible === false ? ` · ${t.editPointsInaccessible}` : ''}
                        </div>
                      ))}
                    </div>

                    {editPointTarget.room_id && (
                      <div style={{ borderTop: '1px solid #eef1f6', paddingTop: 10, marginBottom: 10 }}>
                        <div style={{ fontWeight: 700, fontSize: 11.5, marginBottom: 4 }}>
                          {t.editPointsLinkedRoom}
                        </div>
                        <div style={{ fontSize: 12, color: '#3a4a63' }}>
                          {editPointRoom?.name_en || editPointRoom?.name || editPointTarget.room_id}
                        </div>
                      </div>
                    )}

                    {editPointTarget.connector_id && (
                      <div style={{ borderTop: '1px solid #eef1f6', paddingTop: 10, marginBottom: 10 }}>
                        <div style={{ fontWeight: 700, fontSize: 11.5, marginBottom: 4 }}>
                          {t.editPointsLinkedConnector}
                        </div>
                        <div style={{ fontSize: 12, color: '#3a4a63' }}>
                          {editPointConnector?.name || editPointTarget.connector_id}
                        </div>
                      </div>
                    )}

                    <div style={{ borderTop: '1px solid #eef1f6', paddingTop: 10 }}>
                      {!editPointConfirmDelete ? (
                        <button
                          type="button"
                          onClick={() => setEditPointConfirmDelete(true)}
                          disabled={editPointSaving}
                          style={{
                            width: '100%',
                            border: 'none',
                            borderRadius: 10,
                            padding: '8px 10px',
                            fontSize: 12.5,
                            fontWeight: 700,
                            cursor: 'pointer',
                            background: '#ffe9e9',
                            color: '#a92323',
                          }}
                        >
                          {t.editPointsDeleteAction}
                        </button>
                      ) : (
                        <div>
                          <div style={{ fontSize: 12, marginBottom: 8, color: '#a92323' }}>
                            {t.editPointsConfirmDelete}
                          </div>
                          <div style={{ display: 'flex', gap: 8 }}>
                            <button
                              type="button"
                              onClick={() => setEditPointConfirmDelete(false)}
                              style={{
                                flex: 1,
                                border: '1px solid #d6dee9',
                                borderRadius: 10,
                                padding: '8px 10px',
                                fontSize: 12.5,
                                fontWeight: 700,
                                cursor: 'pointer',
                                background: 'white',
                                color: '#173b70',
                              }}
                            >
                              {t.cancel || 'Cancel'}
                            </button>
                            <button
                              type="button"
                              onClick={handleEditPointDelete}
                              disabled={editPointSaving}
                              style={{
                                flex: 1,
                                border: 'none',
                                borderRadius: 10,
                                padding: '8px 10px',
                                fontSize: 12.5,
                                fontWeight: 700,
                                cursor: 'pointer',
                                background: '#a92323',
                                color: 'white',
                              }}
                            >
                              {t.yes || 'Yes, Delete'}
                            </button>
                          </div>
                        </div>
                      )}
                    </div>
                    </div>
                  </FloatingToolPanel>
                )}

                {/* Auto Connect Destinations to Corridors — scanning
                    banner, shown only while the preview request is
                    in-flight. */}
                {mode === 'auto-connect' && autoConnectPhase === 'scanning' && (
                  <div
                    style={{
                      position: 'absolute',
                      left: '50%',
                      bottom: 18,
                      transform: 'translateX(-50%)',
                      background: 'rgba(20, 55, 105, 0.92)',
                      color: 'white',
                      padding: '10px 16px',
                      borderRadius: 999,
                      fontSize: 13,
                      fontWeight: 700,
                      pointerEvents: 'none',
                      whiteSpace: 'nowrap',
                    }}
                  >
                    {t.autoConnectScanning}
                  </div>
                )}

                {/* Auto Connect Destinations to Corridors — preview review
                    panel (Section 8). A draggable FloatingToolPanel, not
                    a blocking modal, so the map + temporary overlay lines
                    above stay visible while reviewing — and now movable,
                    so it never has to sit on top of the destinations it
                    is describing. Only rendered during 'preview' (the
                    'confirming'/'result' modals below take over from
                    there, and those stay modal). */}
                {mode === 'auto-connect' &&
                  autoConnectPhase === 'preview' &&
                  mapPanels[MAP_PANEL_IDS.autoConnectPreview]?.position && (
                  <FloatingToolPanel
                    title={t.autoConnectPreviewTitle}
                    {...buildMapPanelProps(MAP_PANEL_IDS.autoConnectPreview)}
                    footer={
                      <div className="adm-form-actions">
                        <button
                          type="button"
                          className="adm-btn adm-btn-secondary"
                          onClick={handleCancelAutoConnect}
                          style={{ flex: 1 }}
                        >
                          {t.cancel}
                        </button>
                        <button
                          type="button"
                          className="adm-btn adm-btn-primary"
                          onClick={handleOpenAutoConnectConfirm}
                          style={{ flex: 1 }}
                        >
                          {t.autoConnectReviewComplete}
                        </button>
                      </div>
                    }
                  >
                    <div className="qr-map-panel-summary">
                      {activeMap?.mapGroupId && (
                        <div style={{ display: 'flex', gap: 6, marginBottom: 8 }}>
                          <button
                            type="button"
                            onClick={() => {
                              setAutoConnectScope('map');
                              runAutoConnectPreview('map');
                            }}
                            style={{
                              flex: 1,
                              border: '1px solid rgba(255,255,255,0.6)',
                              borderRadius: 999,
                              padding: '5px 8px',
                              fontSize: 11.5,
                              fontWeight: 700,
                              cursor: 'pointer',
                              background: autoConnectScope === 'map' ? 'white' : 'transparent',
                              color: autoConnectScope === 'map' ? '#173b70' : 'white',
                            }}
                          >
                            {t.autoConnectScopeMap}
                          </button>
                          <button
                            type="button"
                            onClick={() => {
                              setAutoConnectScope('map_group');
                              runAutoConnectPreview('map_group');
                            }}
                            style={{
                              flex: 1,
                              border: '1px solid rgba(255,255,255,0.6)',
                              borderRadius: 999,
                              padding: '5px 8px',
                              fontSize: 11.5,
                              fontWeight: 700,
                              cursor: 'pointer',
                              background: autoConnectScope === 'map_group' ? 'white' : 'transparent',
                              color: autoConnectScope === 'map_group' ? '#173b70' : 'white',
                            }}
                          >
                            {t.autoConnectScopeMapGroup}
                          </button>
                        </div>
                      )}

                      {autoConnectSummary && (
                        <div style={{ fontSize: 11.5, lineHeight: 1.6, opacity: 0.92 }}>
                          <div>{t.autoConnectScannedCount(autoConnectSummary.scanned)}</div>
                          <div>
                            {t.autoConnectAlreadyConnected}: {autoConnectSummary.already_connected}
                          </div>
                          <div>{t.autoConnectProposedCount(autoConnectSummary.proposed)}</div>
                          <div>
                            {t.autoConnectNeedsReview}: {autoConnectSummary.needs_review}
                          </div>
                          <div>
                            {t.autoConnectNoCorridorPointFound}: {autoConnectSummary.no_candidate}
                          </div>
                        </div>
                      )}

                      {autoConnectManualPickTargetId && (
                        <div
                          style={{
                            marginTop: 8,
                            fontSize: 11.5,
                            background: 'rgba(255,255,255,0.15)',
                            borderRadius: 8,
                            padding: '6px 8px',
                          }}
                        >
                          {t.autoConnectManualPickInstructions}
                          <button
                            type="button"
                            onClick={handleCancelManualCorridorPick}
                            style={{
                              marginInlineStart: 8,
                              border: 'none',
                              background: 'transparent',
                              color: 'white',
                              textDecoration: 'underline',
                              cursor: 'pointer',
                              fontSize: 11.5,
                            }}
                          >
                            {t.cancel}
                          </button>
                        </div>
                      )}
                    </div>

                    <div
                      style={{
                        display: 'flex',
                        gap: 8,
                        padding: '10px 18px',
                        borderBottom: '1px solid #e3e9f2',
                      }}
                    >
                      <button
                        type="button"
                        onClick={handleAcceptAllHighConfidence}
                        style={{
                          flex: 1,
                          border: '1px solid #2ecc71',
                          borderRadius: 8,
                          padding: '6px 8px',
                          fontSize: 11.5,
                          fontWeight: 700,
                          cursor: 'pointer',
                          background: 'white',
                          color: '#218c4a',
                        }}
                      >
                        {t.autoConnectAcceptAllHighConfidence}
                      </button>
                      <button
                        type="button"
                        onClick={handleRejectAllLowConfidence}
                        style={{
                          flex: 1,
                          border: '1px solid #c0392b',
                          borderRadius: 8,
                          padding: '6px 8px',
                          fontSize: 11.5,
                          fontWeight: 700,
                          cursor: 'pointer',
                          background: 'white',
                          color: '#c0392b',
                        }}
                      >
                        {t.autoConnectRejectAllLowConfidence}
                      </button>
                    </div>

                    {autoConnectError && (
                      <div
                        style={{
                          padding: '8px 18px',
                          fontSize: 12,
                          color: '#c0392b',
                          fontWeight: 600,
                        }}
                      >
                        {autoConnectError}
                      </div>
                    )}

                    <div>
                      {autoConnectProposals.length === 0 && (
                        <div style={{ fontSize: 12.5, color: '#4a6a8f', padding: '12px 4px' }}>
                          {t.autoConnectNothingToReview}
                        </div>
                      )}

                      {autoConnectProposals.map((proposal) => {
                        const selectedCandidate = proposal.candidates?.find(
                          (candidate) =>
                            autoConnectCandidateKey(candidate) ===
                            proposal.selectedCandidateKey,
                        );

                        return (
                          <div
                            key={proposal.destination_point_id}
                            style={{
                              border: '1px solid #e3e9f2',
                              borderRadius: 10,
                              padding: 10,
                              marginBottom: 8,
                              opacity: proposal.localStatus === 'rejected' ? 0.55 : 1,
                            }}
                          >
                            <div style={{ fontSize: 13, fontWeight: 700, color: '#173b70' }}>
                              {proposal.destination_name}
                              <span style={{ fontWeight: 400, color: '#6b83a6' }}>
                                {' '}
                                ({proposal.destination_point_type})
                              </span>
                            </div>

                            {proposal.is_nested_access && (
                              <div
                                style={{
                                  fontSize: 10.5,
                                  fontWeight: 700,
                                  color: '#8e44ad',
                                  marginTop: 2,
                                }}
                              >
                                {t.autoConnectNestedAccessBadge}
                              </div>
                            )}

                            {(proposal.status === 'no_candidate' ||
                              proposal.status === 'needs_review') && (
                              <>
                                <div
                                  style={{
                                    fontSize: 12,
                                    marginTop: 4,
                                    color:
                                      proposal.status === 'needs_review'
                                        ? '#b9770e'
                                        : '#c0392b',
                                  }}
                                >
                                  {proposal.status === 'needs_review' && (
                                    <strong>{t.autoConnectNeedsReviewBadge}: </strong>
                                  )}
                                  {getAutoConnectReasonLabel(proposal.reason)}
                                </div>
                                {renderAutoConnectDiagnostics(proposal)}
                              </>
                            )}

                            {proposal.status === 'proposed' && (
                              <>
                                <div style={{ fontSize: 12, color: '#4a6a8f', marginTop: 4 }}>
                                  {t.autoConnectProposedCorridorLine(
                                    proposal.manualCandidateName ||
                                      selectedCandidate?.name ||
                                      '',
                                    selectedCandidate?.distance_meters != null
                                      ? `${selectedCandidate.distance_meters} m`
                                      : selectedCandidate?.distance_px != null
                                        ? `${selectedCandidate.distance_px}px (${t.autoConnectUncalibrated})`
                                        : '',
                                  )}
                                </div>

                                <div
                                  style={{
                                    fontSize: 11,
                                    fontWeight: 700,
                                    marginTop: 4,
                                    color:
                                      proposal.confidence === 'high'
                                        ? '#218c4a'
                                        : proposal.confidence === 'medium'
                                          ? '#b9770e'
                                          : proposal.confidence === 'low'
                                            ? '#c0662a'
                                            : '#8e44ad',
                                  }}
                                >
                                  {proposal.confidence === 'high' && t.autoConnectConfidenceHigh}
                                  {proposal.confidence === 'medium' && t.autoConnectConfidenceMedium}
                                  {proposal.confidence === 'low' && t.autoConnectConfidenceLow}
                                  {proposal.confidence === 'needs_review' && t.autoConnectNeedsReview}
                                </div>

                                {proposal.has_existing_invalid_edges && (
                                  <div style={{ fontSize: 11, color: '#c0392b', marginTop: 4 }}>
                                    {t.autoConnectInvalidEdgesWarning}
                                  </div>
                                )}

                                {selectedCandidate?.target_type === 'corridor_edge' && (
                                  <div style={{ fontSize: 11, color: '#6b4bb3', marginTop: 4 }}>
                                    {t.autoConnectTargetCorridorEdge}
                                  </div>
                                )}

                                {renderAutoConnectDiagnostics(proposal)}

                                {proposal.candidates.length > 1 && (
                                  <div style={{ display: 'flex', gap: 4, marginTop: 6, flexWrap: 'wrap' }}>
                                    {proposal.candidates.map((candidate) => {
                                      const key = autoConnectCandidateKey(candidate);
                                      const isSelected =
                                        proposal.selectedCandidateKey === key;

                                      return (
                                        <button
                                          key={key}
                                          type="button"
                                          onClick={() =>
                                            handleSelectAlternativeCandidate(
                                              proposal.destination_point_id,
                                              key,
                                            )
                                          }
                                          title={
                                            candidate.target_type === 'corridor_edge'
                                              ? t.autoConnectTargetCorridorEdge
                                              : candidate.name
                                          }
                                          style={{
                                            border: '1px solid #a9c3e3',
                                            borderRadius: 999,
                                            padding: '3px 8px',
                                            fontSize: 10.5,
                                            cursor: 'pointer',
                                            background: isSelected ? '#173b70' : 'white',
                                            color: isSelected ? 'white' : '#173b70',
                                          }}
                                        >
                                          {candidate.target_type === 'corridor_edge'
                                            ? `\u2295 ${candidate.name}`
                                            : candidate.name}
                                        </button>
                                      );
                                    })}
                                  </div>
                                )}

                                <div style={{ display: 'flex', gap: 6, marginTop: 8 }}>
                                  <button
                                    type="button"
                                    onClick={() =>
                                      handleAcceptProposal(proposal.destination_point_id)
                                    }
                                    style={{
                                      flex: 1,
                                      border: 'none',
                                      borderRadius: 8,
                                      padding: '6px 8px',
                                      fontSize: 11.5,
                                      fontWeight: 700,
                                      cursor: 'pointer',
                                      background:
                                        proposal.localStatus === 'accepted' ? '#218c4a' : '#eafaf1',
                                      color:
                                        proposal.localStatus === 'accepted' ? 'white' : '#218c4a',
                                    }}
                                  >
                                    {t.autoConnectAccept}
                                  </button>
                                  <button
                                    type="button"
                                    onClick={() =>
                                      handleRejectProposal(proposal.destination_point_id)
                                    }
                                    style={{
                                      flex: 1,
                                      border: 'none',
                                      borderRadius: 8,
                                      padding: '6px 8px',
                                      fontSize: 11.5,
                                      fontWeight: 700,
                                      cursor: 'pointer',
                                      background:
                                        proposal.localStatus === 'rejected' ? '#c0392b' : '#fdecea',
                                      color:
                                        proposal.localStatus === 'rejected' ? 'white' : '#c0392b',
                                    }}
                                  >
                                    {t.autoConnectReject}
                                  </button>
                                  <button
                                    type="button"
                                    onClick={() =>
                                      handleStartManualCorridorPick(proposal.destination_point_id)
                                    }
                                    style={{
                                      border: '1px solid #a9c3e3',
                                      borderRadius: 8,
                                      padding: '6px 8px',
                                      fontSize: 11.5,
                                      fontWeight: 700,
                                      cursor: 'pointer',
                                      background: 'white',
                                      color: '#173b70',
                                    }}
                                  >
                                    {t.autoConnectPickManually}
                                  </button>
                                </div>
                              </>
                            )}
                          </div>
                        );
                      })}
                    </div>

                  </FloatingToolPanel>
                )}

                {/* Auto Connect Destinations to Corridors — confirmation
                    modal (Section 9). Shown before any MongoDB write. */}
                {mode === 'auto-connect' && autoConnectPhase === 'confirming' && (
                  <div
                    style={{
                      position: 'fixed',
                      inset: 0,
                      zIndex: 10020,
                      background: 'rgba(9, 26, 53, 0.78)',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      padding: 20,
                    }}
                  >
                    <div
                      className="adm-form-card"
                      style={{ width: 'min(460px, 96vw)', padding: 24, textAlign: 'center' }}
                    >
                      <div className="adm-form-card-title">{t.autoConnectConfirmTitle}</div>

                      <div
                        style={{
                          fontSize: 13,
                          color: '#4a6a8f',
                          marginBottom: 16,
                          lineHeight: 1.6,
                        }}
                      >
                        {t.autoConnectConfirmBody}
                      </div>

                      <div
                        style={{
                          fontSize: 12.5,
                          color: '#173b70',
                          textAlign: isRTL ? 'right' : 'left',
                          background: '#f4f8fd',
                          borderRadius: 10,
                          padding: 12,
                          marginBottom: 16,
                          lineHeight: 1.8,
                        }}
                      >
                        {autoConnectSummary && (
                          <div>{t.autoConnectSummaryLine(autoConnectSummary)}</div>
                        )}
                        <div>
                          {t.autoConnectAcceptedCount(
                            autoConnectProposals.filter((p) => p.localStatus === 'accepted')
                              .length,
                          )}
                        </div>
                        <div>
                          {t.autoConnectRejectedCount(
                            autoConnectProposals.filter((p) => p.localStatus === 'rejected')
                              .length,
                          )}
                        </div>
                      </div>

                      {autoConnectError && (
                        <div
                          style={{
                            fontSize: 12.5,
                            color: '#c0392b',
                            marginBottom: 14,
                            fontWeight: 600,
                          }}
                        >
                          {autoConnectError}
                        </div>
                      )}

                      <div
                        className="adm-form-actions"
                        style={{ justifyContent: 'center', flexWrap: 'wrap' }}
                      >
                        <button
                          type="button"
                          className="adm-btn adm-btn-secondary"
                          onClick={handleCancelAutoConnect}
                          disabled={autoConnectPhase === 'applying'}
                        >
                          {t.cancel}
                        </button>
                        <button
                          type="button"
                          className="adm-btn adm-btn-secondary"
                          onClick={handleBackToAutoConnectPreview}
                          disabled={autoConnectPhase === 'applying'}
                        >
                          {t.autoConnectBackToPreview}
                        </button>
                        <button
                          type="button"
                          className="adm-btn adm-btn-primary"
                          onClick={handleConfirmAutoConnectApply}
                          disabled={autoConnectPhase === 'applying'}
                        >
                          {autoConnectPhase === 'applying'
                            ? t.autoConnectApplying
                            : t.autoConnectCreateAccepted}
                        </button>
                      </div>
                    </div>
                  </div>
                )}

                {/* Auto Connect Destinations to Corridors — result summary
                    (Section 12: "After apply: ... show the result
                    summary"). */}
                {mode === 'auto-connect' &&
                  autoConnectPhase === 'result' &&
                  autoConnectApplyResult && (
                    <div
                      style={{
                        position: 'fixed',
                        inset: 0,
                        zIndex: 10020,
                        background: 'rgba(9, 26, 53, 0.78)',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        padding: 20,
                      }}
                    >
                      <div
                        className="adm-form-card"
                        style={{ width: 'min(440px, 96vw)', padding: 24, textAlign: 'center' }}
                      >
                        <div className="adm-form-card-title">{t.autoConnectResultTitle}</div>

                        <div
                          style={{
                            fontSize: 12.5,
                            color: '#173b70',
                            textAlign: isRTL ? 'right' : 'left',
                            background: '#f4f8fd',
                            borderRadius: 10,
                            padding: 12,
                            marginBottom: 16,
                            lineHeight: 1.8,
                          }}
                        >
                          {t.autoConnectResultLine(autoConnectApplyResult)}
                        </div>

                        {autoConnectApplyResult.warnings?.length > 0 && (
                          <div
                            style={{
                              fontSize: 11.5,
                              color: '#c0392b',
                              marginBottom: 14,
                              textAlign: isRTL ? 'right' : 'left',
                            }}
                          >
                            {autoConnectApplyResult.warnings.map((warning, index) => (
                              <div key={index}>{warning}</div>
                            ))}
                          </div>
                        )}

                        <div className="adm-form-actions" style={{ justifyContent: 'center' }}>
                          <button
                            type="button"
                            className="adm-btn adm-btn-primary"
                            onClick={handleCloseAutoConnectResult}
                          >
                            {t.calibrateClose}
                          </button>
                        </div>
                      </div>
                    </div>
                  )}

                {/* Create Destinations from Approved Analysis — scanning
                    banner. */}
                {mode === 'semantic-destinations' && semanticDestPhase === 'scanning' && (
                  <div
                    style={{
                      position: 'absolute',
                      top: 20,
                      left: '50%',
                      transform: 'translateX(-50%)',
                      background: 'rgba(20, 55, 105, 0.92)',
                      color: 'white',
                      padding: '10px 20px',
                      borderRadius: 999,
                      fontSize: 12.5,
                      fontWeight: 700,
                    }}
                  >
                    {t.semanticDestScanning}
                  </div>
                )}

                {/* Create Destinations from Approved Analysis — preview
                    review panel. */}
                {mode === 'semantic-destinations' &&
                  semanticDestPhase === 'preview' &&
                  mapPanels[MAP_PANEL_IDS.semanticDestPreview]?.position && (
                  <FloatingToolPanel
                    title={t.semanticDestPreviewTitle}
                    {...buildMapPanelProps(MAP_PANEL_IDS.semanticDestPreview)}
                    footer={
                      <div className="adm-form-actions">
                        <button
                          type="button"
                          className="adm-btn adm-btn-secondary"
                          onClick={handleCancelSemanticDestinations}
                          style={{ flex: 1 }}
                        >
                          {t.cancel}
                        </button>
                        <button
                          type="button"
                          className="adm-btn adm-btn-primary"
                          onClick={handleOpenSemanticDestConfirm}
                          style={{ flex: 1 }}
                        >
                          {t.autoConnectReviewComplete}
                        </button>
                      </div>
                    }
                  >
                    <div className="qr-map-panel-summary">
                      {semanticDestSummary && (
                        <div style={{ fontSize: 11.5, marginTop: 6, lineHeight: 1.7, opacity: 0.9 }}>
                          <div>{t.semanticDestScannedCount(semanticDestSummary.scanned)}</div>
                          <div>{t.semanticDestNewCount(semanticDestSummary.new_rooms_proposed)}</div>
                          <div>
                            {t.semanticDestNeedsLocationCount(semanticDestSummary.needs_location_review)}
                          </div>
                          <div>
                            {t.semanticDestNestedCount(semanticDestSummary.nested_relationships_proposed)}
                          </div>
                        </div>
                      )}
                    </div>

                    {/* Section 1: "Place All Destinations" — the fast
                        batch placement entry point. Only offered when at
                        least one non-rejected proposal still needs a
                        manually-clicked location; existing-linked-point
                        proposals never need this. */}
                    {semanticDestProposals.some(
                      (proposal) =>
                        proposal.placement_source === 'needs_manual_placement' &&
                        proposal.localStatus !== 'rejected' &&
                        proposal.localStatus !== 'excluded',
                    ) && (
                      <div style={{ padding: '10px 18px 0' }}>
                        <button
                          type="button"
                          onClick={handleStartSemanticBatchPlacement}
                          style={{
                            width: '100%',
                            border: 'none',
                            borderRadius: 10,
                            padding: '10px 12px',
                            fontSize: 12.5,
                            fontWeight: 700,
                            cursor: 'pointer',
                            background: '#173b70',
                            color: 'white',
                          }}
                        >
                          {t.semanticBatchPlaceAll}
                        </button>
                      </div>
                    )}

                    {semanticDestManualPlaceTargetId && (
                      <div
                        style={{
                          padding: '8px 18px',
                          background: '#fff6e6',
                          fontSize: 11.5,
                          color: '#7a5200',
                          display: 'flex',
                          justifyContent: 'space-between',
                          alignItems: 'center',
                        }}
                      >
                        <span>{t.semanticDestManualPlaceInstructions}</span>
                        <button
                          type="button"
                          onClick={handleCancelManualSemanticPlacement}
                          style={{
                            border: 'none',
                            background: 'transparent',
                            color: '#7a5200',
                            textDecoration: 'underline',
                            cursor: 'pointer',
                            fontSize: 11.5,
                          }}
                        >
                          {t.cancel}
                        </button>
                      </div>
                    )}

                    {semanticDestError && (
                      <div style={{ padding: '8px 18px', fontSize: 12, color: '#c0392b', fontWeight: 600 }}>
                        {semanticDestError}
                      </div>
                    )}

                    <div>
                      {semanticDestProposals.length === 0 && (
                        <div style={{ fontSize: 12.5, color: '#4a6a8f', padding: '12px 4px' }}>
                          {t.semanticDestNothingToReview}
                        </div>
                      )}

                      {semanticDestProposals.map((proposal) => (
                        <div
                          key={proposal.semantic_item_id}
                          style={{
                            border: '1px solid #e3e9f2',
                            borderRadius: 10,
                            padding: 10,
                            marginBottom: 8,
                            opacity:
                              proposal.localStatus === 'rejected' || proposal.localStatus === 'excluded'
                                ? 0.55
                                : 1,
                          }}
                        >
                          <div style={{ fontSize: 13, fontWeight: 700, color: '#173b70' }}>
                            {proposal.name_en || proposal.name_original || proposal.semantic_item_id}
                          </div>

                          {(proposal.name_ar || proposal.name_he) && (
                            <div style={{ fontSize: 11, color: '#6b83a6', marginTop: 2 }}>
                              {[proposal.name_ar, proposal.name_he].filter(Boolean).join(' / ')}
                            </div>
                          )}

                          {proposal.excluded && (
                            <div style={{ fontSize: 11.5, color: '#8e44ad', marginTop: 4 }}>
                              {t.semanticDestExcluded}
                            </div>
                          )}

                          {!proposal.excluded && (
                            <>
                              <div style={{ fontSize: 11.5, color: '#4a6a8f', marginTop: 4 }}>
                                {proposal.placement_source === 'needs_manual_placement'
                                  ? t.semanticDestNeedsLocationReview
                                  : t.semanticDestExistingLocation}
                              </div>

                              {proposal.nested_parent_candidate && (
                                <div
                                  style={{
                                    fontSize: 11,
                                    color: '#8e44ad',
                                    marginTop: 6,
                                    background: '#f6effb',
                                    borderRadius: 6,
                                    padding: 6,
                                  }}
                                >
                                  <div style={{ fontWeight: 700 }}>{t.semanticDestNestedTitle}</div>
                                  <div>
                                    {t.semanticDestNestedLine(proposal.nested_parent_candidate.name)}
                                  </div>
                                  <label style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 4 }}>
                                    <input
                                      type="checkbox"
                                      checked={Boolean(proposal.confirmNested)}
                                      onChange={(event) =>
                                        handleToggleSemanticNested(
                                          proposal.semantic_item_id,
                                          event.target.checked,
                                        )
                                      }
                                    />
                                    {t.semanticDestConfirmNested}
                                  </label>
                                </div>
                              )}

                              <label
                                style={{
                                  display: 'flex',
                                  alignItems: 'center',
                                  gap: 6,
                                  marginTop: 6,
                                  fontSize: 11,
                                  color: '#173b70',
                                }}
                              >
                                <input
                                  type="checkbox"
                                  checked={Boolean(proposal.allowTransitThrough)}
                                  onChange={(event) =>
                                    handleToggleSemanticAllowTransit(
                                      proposal.semantic_item_id,
                                      event.target.checked,
                                    )
                                  }
                                />
                                {t.semanticDestAllowTransit}
                              </label>

                              <div style={{ display: 'flex', gap: 6, marginTop: 8, flexWrap: 'wrap' }}>
                                <button
                                  type="button"
                                  onClick={() =>
                                    handleAcceptSemanticProposal(proposal.semantic_item_id)
                                  }
                                  disabled={
                                    proposal.placement_source === 'needs_manual_placement' &&
                                    (proposal.x == null || proposal.y == null)
                                  }
                                  style={{
                                    flex: 1,
                                    border: 'none',
                                    borderRadius: 8,
                                    padding: '6px 8px',
                                    fontSize: 11.5,
                                    fontWeight: 700,
                                    cursor: 'pointer',
                                    background:
                                      proposal.localStatus === 'accepted' ? '#218c4a' : '#eafaf1',
                                    color: proposal.localStatus === 'accepted' ? 'white' : '#218c4a',
                                  }}
                                >
                                  {t.autoConnectAccept}
                                </button>
                                <button
                                  type="button"
                                  onClick={() =>
                                    handleRejectSemanticProposal(proposal.semantic_item_id)
                                  }
                                  style={{
                                    flex: 1,
                                    border: 'none',
                                    borderRadius: 8,
                                    padding: '6px 8px',
                                    fontSize: 11.5,
                                    fontWeight: 700,
                                    cursor: 'pointer',
                                    background:
                                      proposal.localStatus === 'rejected' ? '#c0392b' : '#fdecea',
                                    color: proposal.localStatus === 'rejected' ? 'white' : '#c0392b',
                                  }}
                                >
                                  {t.autoConnectReject}
                                </button>
                                {proposal.placement_source === 'needs_manual_placement' && (
                                  <button
                                    type="button"
                                    onClick={() =>
                                      handleStartManualSemanticPlacement(proposal.semantic_item_id)
                                    }
                                    style={{
                                      border: '1px solid #a9c3e3',
                                      borderRadius: 8,
                                      padding: '6px 8px',
                                      fontSize: 11.5,
                                      fontWeight: 700,
                                      cursor: 'pointer',
                                      background: 'white',
                                      color: '#173b70',
                                    }}
                                  >
                                    {t.semanticDestPickLocation}
                                  </button>
                                )}
                              </div>
                            </>
                          )}
                        </div>
                      ))}
                    </div>

                  </FloatingToolPanel>
                )}

                {/* Create Destinations from Approved Analysis —
                    confirmation. */}
                {mode === 'semantic-destinations' && semanticDestPhase === 'confirming' && (
                  <div
                    style={{
                      position: 'fixed',
                      inset: 0,
                      zIndex: 10020,
                      background: 'rgba(9, 26, 53, 0.78)',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      padding: 20,
                    }}
                  >
                    <div
                      className="adm-form-card"
                      style={{ width: 'min(460px, 96vw)', padding: 24, textAlign: 'center' }}
                    >
                      <div className="adm-form-card-title">{t.semanticDestConfirmTitle}</div>

                      <div
                        style={{
                          fontSize: 13,
                          color: '#4a6a8f',
                          marginBottom: 16,
                          lineHeight: 1.6,
                        }}
                      >
                        {semanticDestProposals.some((p) => p.confirmNested)
                          ? t.semanticDestNestedConfirmBody
                          : t.semanticDestConfirmBody}
                      </div>

                      {semanticDestError && (
                        <div
                          style={{
                            fontSize: 12.5,
                            color: '#c0392b',
                            marginBottom: 14,
                            fontWeight: 600,
                          }}
                        >
                          {semanticDestError}
                        </div>
                      )}

                      <div
                        className="adm-form-actions"
                        style={{ justifyContent: 'center', flexWrap: 'wrap' }}
                      >
                        <button
                          type="button"
                          className="adm-btn adm-btn-secondary"
                          onClick={handleCancelSemanticDestinations}
                          disabled={semanticDestPhase === 'applying'}
                        >
                          {t.cancel}
                        </button>
                        <button
                          type="button"
                          className="adm-btn adm-btn-secondary"
                          onClick={handleBackToSemanticDestPreview}
                          disabled={semanticDestPhase === 'applying'}
                        >
                          {t.autoConnectBackToPreview}
                        </button>
                        <button
                          type="button"
                          className="adm-btn adm-btn-primary"
                          onClick={handleConfirmSemanticDestApply}
                          disabled={semanticDestPhase === 'applying'}
                        >
                          {semanticDestPhase === 'applying'
                            ? t.autoConnectApplying
                            : t.semanticDestCreateAccepted}
                        </button>
                      </div>
                    </div>
                  </div>
                )}

                {/* Create Destinations from Approved Analysis — result
                    summary (Section 19). */}
                {mode === 'semantic-destinations' &&
                  semanticDestPhase === 'result' &&
                  semanticDestApplyResult && (
                    <div
                      style={{
                        position: 'fixed',
                        inset: 0,
                        zIndex: 10020,
                        background: 'rgba(9, 26, 53, 0.78)',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        padding: 20,
                      }}
                    >
                      <div
                        className="adm-form-card"
                        style={{ width: 'min(440px, 96vw)', padding: 24, textAlign: 'center' }}
                      >
                        <div className="adm-form-card-title">{t.semanticDestResultTitle}</div>

                        <div
                          style={{
                            fontSize: 12.5,
                            color: '#173b70',
                            textAlign: isRTL ? 'right' : 'left',
                            background: '#f4f8fd',
                            borderRadius: 10,
                            padding: 12,
                            marginBottom: 16,
                            lineHeight: 1.9,
                          }}
                        >
                          <div>{t.semanticDestResultRoomsLine(semanticDestApplyResult)}</div>
                          <div>{t.semanticDestResultPointsLine(semanticDestApplyResult)}</div>
                          <div>{t.semanticDestResultUpdatedLine(semanticDestApplyResult)}</div>
                          <div>{t.semanticDestResultNestedLine(semanticDestApplyResult)}</div>
                          <div>{t.semanticDestResultNeedsReviewLine(semanticDestApplyResult)}</div>
                          <div>{t.semanticDestResultFailedLine(semanticDestApplyResult)}</div>
                          <div>{t.semanticDestResultQrLine(semanticDestApplyResult)}</div>
                          <div>{t.semanticDestResultNotNavigableLine(semanticDestApplyResult)}</div>
                        </div>

                        {/* Rooms that were accepted but could not become
                            navigable, named rather than only counted, so the
                            admin knows exactly what still needs doing before
                            those rooms get a QR. */}
                        {semanticDestApplyResult.rooms_needing_review?.length > 0 && (
                          <div
                            style={{
                              fontSize: 11.5,
                              textAlign: isRTL ? 'right' : 'left',
                              background: '#fff8e6',
                              border: '1px solid #f0d9a0',
                              borderRadius: 10,
                              padding: 12,
                              marginBottom: 16,
                              lineHeight: 1.8,
                            }}
                          >
                            <div style={{ marginBottom: 6 }}>
                              {t.semanticDestNotNavigableHint}
                            </div>
                            <ul style={{ margin: 0, paddingInlineStart: 18 }}>
                              {semanticDestApplyResult.rooms_needing_review.map((entry) => (
                                <li key={entry.room_id}>
                                  {entry.name} — {SEMANTIC_DEST_REVIEW_REASONS[entry.reason]
                                    ? t[SEMANTIC_DEST_REVIEW_REASONS[entry.reason]]
                                    : entry.reason}
                                </li>
                              ))}
                            </ul>
                          </div>
                        )}

                        {semanticDestApplyResult.warnings?.length > 0 && (
                          <div
                            style={{
                              fontSize: 11.5,
                              color: '#c0392b',
                              marginBottom: 14,
                              textAlign: isRTL ? 'right' : 'left',
                            }}
                          >
                            {semanticDestApplyResult.warnings.map((warning, index) => (
                              <div key={index}>{warning}</div>
                            ))}
                          </div>
                        )}

                        <div className="adm-form-actions" style={{ justifyContent: 'center' }}>
                          <button
                            type="button"
                            className="adm-btn adm-btn-primary"
                            onClick={handleCloseSemanticDestResult}
                          >
                            {t.calibrateClose}
                          </button>
                        </div>
                      </div>
                    </div>
                  )}

                {/* Fast batch destination placement — Section 9 draft
                    resume/discard prompt. Shown BEFORE the batch panel
                    itself opens, so a resumed draft never briefly flashes
                    an empty/fresh queue first. */}
                {semanticBatchDraftPrompt && (
                  <div
                    style={{
                      position: 'fixed',
                      inset: 0,
                      zIndex: 10030,
                      background: 'rgba(9, 26, 53, 0.78)',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      padding: 20,
                    }}
                  >
                    <div
                      className="adm-form-card"
                      style={{ width: 'min(420px, 96vw)', padding: 24, textAlign: 'center' }}
                    >
                      <div className="adm-form-card-title">{t.semanticBatchResumeDraftTitle}</div>
                      <div style={{ fontSize: 12.5, color: '#4a6a8f', marginBottom: 16 }}>
                        {t.semanticBatchResumeDraftBody}
                      </div>
                      <div className="adm-form-actions" style={{ justifyContent: 'center' }}>
                        <button
                          type="button"
                          className="adm-btn adm-btn-secondary"
                          onClick={handleDiscardSemanticBatchDraft}
                        >
                          {t.semanticBatchDiscardDraft}
                        </button>
                        <button
                          type="button"
                          className="adm-btn adm-btn-primary"
                          onClick={handleResumeSemanticBatchDraft}
                        >
                          {t.semanticBatchResumeDraft}
                        </button>
                      </div>
                    </div>
                  </div>
                )}

                {/* Fast batch destination placement — Section 2/3/4: the
                    sequential placement panel. A real FloatingToolPanel
                    (draggable/collapsible) rather than a fixed sidebar —
                    this IS the fix for the old "Pick Location" bug, which
                    was caused by a fixed full-height panel physically
                    covering part of the map. */}
                {mode === 'semantic-destinations' &&
                  semanticBatchActive &&
                  !semanticBatchReviewOpen &&
                  panelPosition && (
                    (() => {
                      const activeItemId = semanticBatchQueue[semanticBatchIndex];
                      const activeProposal = semanticDestProposals.find(
                        (proposal) => proposal.semantic_item_id === activeItemId,
                      );
                      const activeStatus = activeItemId
                        ? semanticBatchStatuses[activeItemId]
                        : null;
                      const progress = computeBatchProgress(semanticBatchQueue, semanticBatchStatuses);
                      const canGoNext = activeStatus === 'placed' || activeStatus === 'rejected';
                      const autoPlacedCount = semanticDestProposals.filter(
                        (proposal) => proposal.autoPlaced,
                      ).length;
                      const autoPlacementReviewList = buildAutoPlacementReviewList(
                        semanticAutoPlacement?.proposals,
                      );

                      return (
                        <FloatingToolPanel
                          title={t.semanticBatchPanelTitle}
                          position={panelPosition}
                          onPositionChange={setPanelPosition}
                          isCollapsed={isPanelCollapsed}
                          onToggleCollapse={() => setIsPanelCollapsed((prev) => !prev)}
                          onDragStateChange={(dragging) => {
                            isPanelDraggingRef.current = dragging;
                          }}
                          containerRef={fullMapWorkspaceRef}
                          snapTopOffset={76}
                          isRTL={isRTL}
                          showSnapControls
                          moveLabel={t.panelMove}
                          minimizeLabel={t.panelMinimize}
                          restoreLabel={t.panelRestore}
                          snapLabels={{
                            left: t.panelDockLeft,
                            right: t.panelDockRight,
                            bottom: t.panelDockBottom,
                          }}
                          footer={
                            <div className="adm-form-actions" style={{ flexWrap: 'wrap', gap: 8 }}>
                              <button
                                type="button"
                                className="adm-btn adm-btn-cancel"
                                disabled={semanticBatchIndex === 0}
                                onClick={handleBatchPrevious}
                              >
                                {t.semanticBatchPrevious}
                              </button>
                              <button
                                type="button"
                                className="adm-btn adm-btn-cancel"
                                disabled={!activeItemId}
                                onClick={handleBatchSkip}
                              >
                                {t.semanticBatchSkip}
                              </button>
                              <button
                                type="button"
                                className="adm-btn adm-btn-cancel"
                                disabled={!activeItemId}
                                onClick={handleBatchReject}
                              >
                                {t.semanticBatchReject}
                              </button>
                              <button
                                type="button"
                                className="adm-btn adm-btn-cancel"
                                disabled={semanticBatchHistory.length === 0}
                                onClick={handleBatchUndo}
                              >
                                {t.semanticBatchUndo}
                              </button>
                              {activeStatus === 'placed' && (
                                <button
                                  type="button"
                                  className="adm-btn adm-btn-cancel"
                                  onClick={handleBatchChangeLocation}
                                >
                                  {t.semanticBatchChangeLocation}
                                </button>
                              )}
                              <button
                                type="button"
                                className="adm-btn adm-btn-primary"
                                onClick={handleRequestExitSemanticBatch}
                              >
                                {t.semanticBatchExit}
                              </button>
                            </div>
                          }
                        >
                          {activeProposal ? (
                            <>
                              <div style={{ fontSize: 11.5, color: '#6b83a6', marginBottom: 4 }}>
                                {t.semanticBatchDestinationOf(
                                  semanticBatchIndex + 1,
                                  semanticBatchQueue.length,
                                )}
                              </div>
                              <div style={{ fontSize: 15, fontWeight: 700, color: '#173b70' }}>
                                {activeProposal.name_en ||
                                  activeProposal.name_original ||
                                  activeProposal.semantic_item_id}
                              </div>
                              {(activeProposal.name_ar || activeProposal.name_he) && (
                                <div style={{ fontSize: 11, color: '#6b83a6', marginTop: 2 }}>
                                  {[activeProposal.name_ar, activeProposal.name_he]
                                    .filter(Boolean)
                                    .join(' / ')}
                                </div>
                              )}

                              {/* Positioned from a label PRINTED on this
                                  map, then wall- and line-of-sight-checked
                                  by the server. Never door detection: no
                                  door, opening or room outline is detected
                                  anywhere in this flow. Shown prominently
                                  because the admin must be able to tell an
                                  automatic position from one they clicked,
                                  and can move or reject it either way. */}
                              {activeProposal.autoPlaced && (
                                <div
                                  style={{
                                    marginTop: 10,
                                    padding: 8,
                                    borderRadius: 8,
                                    fontSize: 11.5,
                                    color: '#1b4d8f',
                                    background: '#eaf2fd',
                                    border: '1px solid #c5daf5',
                                  }}
                                >
                                  <div style={{ fontWeight: 700 }}>
                                    {t.semanticAutoPlacedBadge}
                                  </div>
                                  {activeProposal.autoPlacement?.matchedLabel && (
                                    <div style={{ marginTop: 3 }}>
                                      {t.semanticAutoPlacedDetail(
                                        activeProposal.autoPlacement.matchedLabel,
                                      )}
                                    </div>
                                  )}
                                  {activeProposal.autoPlacement?.matchedGraphElement?.name && (
                                    <div style={{ marginTop: 3 }}>
                                      {t.semanticAutoPlacedConnects(
                                        activeProposal.autoPlacement.matchedGraphElement.name,
                                      )}
                                    </div>
                                  )}
                                  <div style={{ marginTop: 3, color: '#4a6a8f' }}>
                                    {t.semanticAutoPlacedCheckHint}
                                  </div>
                                </div>
                              )}

                              <div
                                style={{
                                  marginTop: 10,
                                  padding: 8,
                                  borderRadius: 8,
                                  fontSize: 11.5,
                                  color:
                                    activeStatus === 'placed' ? '#218c4a' : '#7a5200',
                                  background:
                                    activeStatus === 'placed' ? '#eafaf1' : '#fff6e6',
                                }}
                              >
                                {activeStatus === 'placed'
                                  ? t.semanticBatchLocationRecorded
                                  : t.semanticBatchClickInstructions}
                              </div>

                              {semanticBatchFeedback && (
                                <div style={{ marginTop: 8, fontSize: 11.5, color: '#218c4a', fontWeight: 600 }}>
                                  {semanticBatchFeedback}
                                </div>
                              )}

                              <div
                                style={{
                                  marginTop: 14,
                                  fontSize: 11,
                                  color: '#4a6a8f',
                                  lineHeight: 1.8,
                                  borderTop: '1px solid #e3e9f2',
                                  paddingTop: 10,
                                }}
                              >
                                <div>{t.semanticBatchProgressPlaced(progress.placed, progress.total)}</div>
                                <div>{t.semanticBatchProgressRemaining(progress.remaining)}</div>
                                <div>{t.semanticBatchProgressRejected(progress.rejected)}</div>
                              </div>

                              {/* What the map's labels could and could not
                                  answer for. The refusals are named, not
                                  just counted — "5 rooms could not be
                                  placed" is not something an admin can
                                  act on. */}
                              {autoPlacedCount > 0 && (
                                <div
                                  style={{
                                    marginTop: 10,
                                    fontSize: 11,
                                    color: '#4a6a8f',
                                    lineHeight: 1.7,
                                    borderTop: '1px solid #e3e9f2',
                                    paddingTop: 10,
                                  }}
                                >
                                  <div>
                                    {t.semanticAutoPlacedSummary(
                                      autoPlacedCount,
                                      semanticBatchQueue.length,
                                    )}
                                  </div>
                                  {autoPlacementReviewList.length > 0 && (
                                    <>
                                      <div style={{ marginTop: 6, fontWeight: 600 }}>
                                        {t.semanticAutoPlacedNeedsClick}
                                      </div>
                                      <ul style={{ margin: '4px 0 0', paddingInlineStart: 16 }}>
                                        {autoPlacementReviewList.map((item) => (
                                          <li key={item.semanticItemId}>
                                            {item.name} — {describeAutoPlacementStatus(item.status)}
                                          </li>
                                        ))}
                                      </ul>
                                    </>
                                  )}
                                </div>
                              )}

                              {canGoNext && (
                                <div style={{ marginTop: 8, fontSize: 10.5, color: '#8ba0bd' }}>
                                  {t.semanticBatchEnterHint}
                                </div>
                              )}
                            </>
                          ) : (
                            <div style={{ fontSize: 12.5, color: '#4a6a8f' }}>
                              {t.semanticBatchAllResolved}
                            </div>
                          )}
                        </FloatingToolPanel>
                      );
                    })()
                  )}

                {navBuildOpen && mapPanels[MAP_PANEL_IDS.navBuild]?.position && (
                  <NavigationBuildPreviewPanel
                    result={navBuildResult}
                    loading={navBuildLoading}
                    error={navBuildError}
                    layers={navBuildLayers}
                    onToggleLayer={handleToggleNavBuildLayer}
                    onRun={handleRunNavBuildPreview}
                    onClose={handleCloseNavBuild}
                    strings={t}
                    panelProps={buildMapPanelProps(MAP_PANEL_IDS.navBuild)}
                  />
                )}

                {/* Fast batch destination placement — Section 5: final
                    review screen, opened automatically once every queue
                    item is placed/rejected (or manually via the panel's
                    review entry once ready). */}
                {mode === 'semantic-destinations' &&
                  semanticBatchActive &&
                  semanticBatchReviewOpen &&
                  mapPanels[MAP_PANEL_IDS.semanticBatchReview]?.position && (
                  <FloatingToolPanel
                    title={t.semanticBatchReviewTitle}
                    {...buildMapPanelProps(MAP_PANEL_IDS.semanticBatchReview)}
                    footer={
                      <div className="adm-form-actions" style={{ flexWrap: 'wrap', gap: 8 }}>
                        <button
                          type="button"
                          className="adm-btn adm-btn-secondary"
                          onClick={() => setSemanticBatchReviewOpen(false)}
                          style={{ flex: 1 }}
                        >
                          {t.semanticBatchBackToPlacement}
                        </button>
                        <button
                          type="button"
                          className="adm-btn adm-btn-secondary"
                          onClick={handleRequestExitSemanticBatch}
                          style={{ flex: 1 }}
                        >
                          {t.semanticBatchExit}
                        </button>
                        <button
                          type="button"
                          className="adm-btn adm-btn-primary"
                          disabled={!isBatchReadyToSave(semanticBatchQueue, semanticBatchStatuses)}
                          onClick={handleOpenSemanticBatchSaveConfirm}
                          style={{ flex: 1 }}
                        >
                          {t.semanticBatchSaveAll}
                        </button>
                      </div>
                    }
                  >
                    <div className="qr-map-panel-summary">
                      <div style={{ fontSize: 11.5, opacity: 0.9 }}>
                        {(() => {
                          const progress = computeBatchProgress(semanticBatchQueue, semanticBatchStatuses);
                          return t.semanticBatchProgressPlaced(progress.placed, progress.total);
                        })()}
                      </div>
                    </div>

                    {semanticBatchSaveError && (
                      <div style={{ padding: '8px 18px', fontSize: 12, color: '#c0392b', fontWeight: 600 }}>
                        {semanticBatchSaveError}
                      </div>
                    )}

                    <div>
                      {semanticDestProposals
                        .filter(
                          (proposal) =>
                            proposal.localStatus !== 'excluded' &&
                            (proposal.localStatus === 'accepted' ||
                              proposal.localStatus === 'rejected' ||
                              semanticBatchQueue.includes(proposal.semantic_item_id)),
                        )
                        .map((proposal) => {
                          const isRejected = proposal.localStatus === 'rejected';
                          const hasLocation = proposal.x != null && proposal.y != null;
                          const reviewStatus = isRejected
                            ? 'rejected'
                            : hasLocation
                              ? 'ready'
                              : 'missing';
                          const itemError = semanticBatchItemErrors[proposal.semantic_item_id];

                          return (
                            <button
                              key={proposal.semantic_item_id}
                              type="button"
                              onClick={() =>
                                handleSelectSemanticBatchReviewItem(proposal.semantic_item_id)
                              }
                              style={{
                                display: 'block',
                                width: '100%',
                                textAlign: isRTL ? 'right' : 'left',
                                border: '1px solid #e3e9f2',
                                borderRadius: 10,
                                padding: 10,
                                marginBottom: 8,
                                background: itemError ? '#fdecea' : 'white',
                                cursor: 'pointer',
                              }}
                            >
                              <div style={{ fontSize: 13, fontWeight: 700, color: '#173b70' }}>
                                {proposal.name_en || proposal.name_original || proposal.semantic_item_id}
                              </div>
                              <div style={{ fontSize: 11, color: '#6b83a6', marginTop: 2 }}>
                                {proposal.detected_category || proposal.proposed_room_type || '—'}
                                {' · '}
                                {t.semanticBatchFloorLabel(proposal.floor)}
                              </div>
                              <div style={{ fontSize: 11, marginTop: 4 }}>
                                {hasLocation
                                  ? `x=${proposal.x}, y=${proposal.y}`
                                  : t.semanticBatchNoLocationYet}
                              </div>
                              <div
                                style={{
                                  fontSize: 11,
                                  marginTop: 4,
                                  fontWeight: 700,
                                  color:
                                    reviewStatus === 'ready'
                                      ? '#218c4a'
                                      : reviewStatus === 'rejected'
                                        ? '#c0392b'
                                        : '#7a5200',
                                }}
                              >
                                {reviewStatus === 'ready' && t.semanticBatchStatusReady}
                                {reviewStatus === 'rejected' && t.semanticBatchStatusRejected}
                                {reviewStatus === 'missing' && t.semanticBatchStatusMissing}
                              </div>
                              {proposal.nested_parent_candidate && (
                                <div style={{ fontSize: 10.5, color: '#8e44ad', marginTop: 4 }}>
                                  {t.semanticDestNestedLine(proposal.nested_parent_candidate.name)}
                                  {proposal.confirmNested ? ` — ${t.semanticDestConfirmNested}` : ''}
                                </div>
                              )}
                              {proposal.allowTransitThrough && (
                                <div style={{ fontSize: 10.5, color: '#173b70', marginTop: 2 }}>
                                  {t.semanticDestAllowTransit}
                                </div>
                              )}
                              {itemError && (
                                <div style={{ fontSize: 10.5, color: '#c0392b', marginTop: 4 }}>
                                  {itemError}
                                </div>
                              )}
                            </button>
                          );
                        })}
                    </div>

                  </FloatingToolPanel>
                )}

                {/* Fast batch destination placement — Section 6: ONE final
                    confirmation dialog with counts before the single
                    all-or-nothing write. */}
                {semanticBatchConfirmOpen && (
                  <div
                    style={{
                      position: 'fixed',
                      inset: 0,
                      zIndex: 10030,
                      background: 'rgba(9, 26, 53, 0.78)',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      padding: 20,
                    }}
                  >
                    <div
                      className="adm-form-card"
                      style={{ width: 'min(420px, 96vw)', padding: 24, textAlign: 'center' }}
                    >
                      <div className="adm-form-card-title">{t.semanticBatchSaveConfirmTitle}</div>
                      <div style={{ fontSize: 12.5, color: '#173b70', marginBottom: 16 }}>
                        {t.semanticBatchSaveConfirmBody(buildBatchAcceptedPayload(semanticDestProposals).length)}
                      </div>
                      {semanticBatchSaveError && (
                        <div style={{ fontSize: 12, color: '#c0392b', marginBottom: 12 }}>
                          {semanticBatchSaveError}
                        </div>
                      )}
                      <div className="adm-form-actions" style={{ justifyContent: 'center' }}>
                        <button
                          type="button"
                          className="adm-btn adm-btn-secondary"
                          disabled={semanticBatchSaving}
                          onClick={handleCancelSemanticBatchSaveConfirm}
                        >
                          {t.cancel}
                        </button>
                        <button
                          type="button"
                          className="adm-btn adm-btn-primary"
                          disabled={semanticBatchSaving}
                          onClick={handleSaveAllSemanticBatchDestinations}
                        >
                          {semanticBatchSaving ? t.semanticDestScanning : t.semanticBatchSaveAll}
                        </button>
                      </div>
                    </div>
                  </div>
                )}

                {/* Fast batch destination placement — Section 4: Escape /
                    Exit-with-unsaved-progress warning. */}
                {semanticBatchExitWarningOpen && (
                  <div
                    style={{
                      position: 'fixed',
                      inset: 0,
                      zIndex: 10030,
                      background: 'rgba(9, 26, 53, 0.78)',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      padding: 20,
                    }}
                  >
                    <div
                      className="adm-form-card"
                      style={{ width: 'min(380px, 96vw)', padding: 24, textAlign: 'center' }}
                    >
                      <div className="adm-form-card-title">{t.semanticBatchExitWarningTitle}</div>
                      <div style={{ fontSize: 12.5, color: '#4a6a8f', marginBottom: 16 }}>
                        {t.semanticBatchExitWarningBody}
                      </div>
                      <div className="adm-form-actions" style={{ justifyContent: 'center' }}>
                        <button
                          type="button"
                          className="adm-btn adm-btn-secondary"
                          onClick={handleCancelExitSemanticBatch}
                        >
                          {t.cancel}
                        </button>
                        <button
                          type="button"
                          className="adm-btn adm-btn-primary"
                          onClick={handleConfirmExitSemanticBatch}
                        >
                          {t.semanticBatchExit}
                        </button>
                      </div>
                    </div>
                  </div>
                )}

                {mode === 'draw' && panelPosition && (
                  <FloatingToolPanel
                    title={t.drawMode}
                    position={panelPosition}
                    onPositionChange={setPanelPosition}
                    isCollapsed={isPanelCollapsed}
                    onToggleCollapse={() => setIsPanelCollapsed((prev) => !prev)}
                    onDragStateChange={(dragging) => {
                      isPanelDraggingRef.current = dragging;
                    }}
                    containerRef={fullMapWorkspaceRef}
                    snapTopOffset={76}
                    isRTL={isRTL}
                    showSnapControls
                    moveLabel={t.panelMove}
                    minimizeLabel={t.panelMinimize}
                    restoreLabel={t.panelRestore}
                    snapLabels={{
                      left: t.panelDockLeft,
                      right: t.panelDockRight,
                      bottom: t.panelDockBottom,
                    }}
                    footer={
                      <div
                        className="adm-form-actions"
                        style={{ flexWrap: 'wrap', gap: 8 }}
                      >
                        <button
                          type="button"
                          className="adm-btn adm-btn-cancel"
                          disabled={isSavingDraft || draftPoints.length === 0}
                          onClick={handleUndoDraft}
                        >
                          {t.drawUndo}
                        </button>

                        <button
                          type="button"
                          className="adm-btn adm-btn-cancel"
                          disabled={isSavingDraft || draftPoints.length === 0}
                          onClick={handleClearDraft}
                        >
                          {t.drawClear}
                        </button>

                        <button
                          type="button"
                          className="adm-btn adm-btn-cancel"
                          disabled={isSavingDraft}
                          onClick={handleCancelDraw}
                        >
                          {t.drawCancel}
                        </button>

                        <button
                          type="button"
                          className="adm-btn adm-btn-primary"
                          disabled={
                            isSavingDraft ||
                            draftPoints.length < 2 ||
                            !isDraftNamingValid
                          }
                          onClick={handleSaveDraft}
                        >
                          {isSavingDraft ? t.drawSaving : t.drawSave}
                        </button>
                      </div>
                    }
                  >
                    <div
                      style={{
                        fontSize: 12,
                        color: '#5f7fa6',
                        marginBottom: 10,
                      }}
                    >
                      {t.drawHint}
                    </div>

                    {renderFloorSelect(t.drawFloor, 'draw')}

                    <div className="adm-form-group">
                      <label className="adm-form-label">
                        {t.drawMergeModeLabel}
                      </label>
                      <select
                        className="adm-form-input"
                        value={mergeMode}
                        disabled={isSavingDraft}
                        onChange={(event) => setMergeMode(event.target.value)}
                      >
                        <option value="off">{t.drawMergeModeOff}</option>
                        <option value="reuseOnly">
                          {t.drawMergeModeReuseOnly}
                        </option>
                        <option value="nearby">
                          {t.drawMergeModeNearby}
                        </option>
                      </select>
                    </div>

                    <div
                      style={{
                        fontSize: 12.5,
                        fontWeight: 700,
                        color: '#173b70',
                        marginBottom: 10,
                      }}
                    >
                      {t.drawPointCount(draftPoints.length)}
                    </div>

                    {/* Compact draft-point editor: sequence number, New/
                        Existing status, an editable name for new points
                        (saved name, read-only, for reused ones), a
                        possible-auto-merge hint, and small secondary
                        coordinate text. Its own max-height + overflow-y
                        keeps a long draft (many points) scrollable in
                        place instead of growing the whole panel — the
                        panel-level scroll fix above already makes this
                        safe even if it does grow. */}
                    {draftPoints.length > 0 && (
                      <div className="adm-form-group">
                        <label className="adm-form-label">
                          {t.drawPointListTitle}
                        </label>
                        <div
                          style={{
                            maxHeight: 220,
                            overflowY: 'auto',
                            overscrollBehavior: 'contain',
                            display: 'flex',
                            flexDirection: 'column',
                            gap: 8,
                          }}
                        >
                          {draftPoints.map((point, index) => {
                            const isLastPoint =
                              index === draftPoints.length - 1;
                            const nameCheck =
                              point.kind === 'new'
                                ? validateDraftPointName(point.name)
                                : { ok: true };
                            const hasMergeHint =
                              mergeMode === 'nearby' &&
                              point.kind === 'new' &&
                              nearbyMergePreview.some(
                                (preview) => preview.draftIndex === index,
                              );

                            return (
                              <div
                                key={point.tempId}
                                style={{
                                  padding: 8,
                                  borderRadius: 10,
                                  background: '#f7fafd',
                                  border: '1px solid rgba(23, 59, 112, 0.10)',
                                }}
                              >
                                <div
                                  style={{
                                    display: 'flex',
                                    alignItems: 'center',
                                    gap: 6,
                                    marginBottom: 6,
                                  }}
                                >
                                  <span
                                    style={{
                                      fontWeight: 700,
                                      fontSize: 11.5,
                                      color: '#173b70',
                                    }}
                                  >
                                    {index + 1}.
                                  </span>
                                  <span
                                    style={{
                                      fontSize: 10,
                                      fontWeight: 700,
                                      textTransform: 'uppercase',
                                      letterSpacing: 0.3,
                                      padding: '2px 7px',
                                      borderRadius: 999,
                                      background:
                                        point.kind === 'existing'
                                          ? 'rgba(46, 204, 113, 0.16)'
                                          : 'rgba(242, 183, 5, 0.20)',
                                      color:
                                        point.kind === 'existing'
                                          ? '#1a7f37'
                                          : '#8a6100',
                                    }}
                                  >
                                    {point.kind === 'existing'
                                      ? t.drawStatusExisting
                                      : t.drawStatusNew}
                                  </span>

                                  {isLastPoint && (
                                    <button
                                      type="button"
                                      disabled={isSavingDraft}
                                      onClick={handleUndoDraft}
                                      style={{
                                        marginInlineStart: 'auto',
                                        border: 'none',
                                        background: 'none',
                                        color: '#b42318',
                                        fontSize: 11,
                                        fontWeight: 700,
                                        cursor: 'pointer',
                                      }}
                                    >
                                      {t.drawRemovePoint}
                                    </button>
                                  )}
                                </div>

                                {point.kind === 'existing' ? (
                                  <div
                                    style={{
                                      fontSize: 12.5,
                                      fontWeight: 600,
                                      color: '#173b70',
                                    }}
                                  >
                                    {point.name}
                                  </div>
                                ) : (
                                  <>
                                    <input
                                      className="adm-form-input"
                                      style={{ fontSize: 12.5 }}
                                      value={point.name || ''}
                                      placeholder={t.drawNamePlaceholder}
                                      disabled={isSavingDraft}
                                      onChange={(event) =>
                                        handleDraftPointNameChange(
                                          index,
                                          event.target.value,
                                        )
                                      }
                                    />
                                    {!nameCheck.ok && (
                                      <div
                                        style={{
                                          marginTop: 3,
                                          fontSize: 10.5,
                                          fontWeight: 700,
                                          color: '#b42318',
                                        }}
                                      >
                                        {nameCheck.reason === 'too-long'
                                          ? t.drawNameTooLong
                                          : nameCheck.reason === 'too-short'
                                            ? t.drawNameTooShort
                                            : t.drawNameEmpty}
                                      </div>
                                    )}
                                  </>
                                )}

                                {hasMergeHint && (
                                  <div
                                    style={{
                                      marginTop: 3,
                                      fontSize: 10.5,
                                      fontStyle: 'italic',
                                      color: '#8e44ad',
                                    }}
                                  >
                                    {t.drawStatusMergeHint}
                                  </div>
                                )}

                                <div
                                  style={{
                                    marginTop: 3,
                                    fontSize: 10,
                                    color: '#8aa4c8',
                                  }}
                                >
                                  X: {Math.round(point.x)} | Y:{' '}
                                  {Math.round(point.y)}
                                </div>
                              </div>
                            );
                          })}
                        </div>
                      </div>
                    )}

                    {draftSummary && (
                      <div
                        style={{
                          marginBottom: 10,
                          padding: 8,
                          borderRadius: 10,
                          background: '#f2f6fc',
                          fontSize: 11.5,
                          color: '#173b70',
                          lineHeight: 1.6,
                        }}
                      >
                        <div style={{ fontWeight: 700, marginBottom: 2 }}>
                          {t.drawSummaryTitle}
                        </div>
                        <div>{t.drawSummaryNewPoints(draftSummary.newPoints)}</div>
                        <div>
                          {t.drawSummaryReusedPoints(draftSummary.reusedPoints)}
                        </div>
                        <div>
                          {t.drawSummaryPlannedEdges(draftSummary.plannedEdges)}
                        </div>
                        <div>
                          {t.drawSummarySkippedEdges(draftSummary.skippedEdges)}
                        </div>
                      </div>
                    )}

                    {draftError && (
                      <div
                        style={{
                          marginBottom: 10,
                          padding: 8,
                          borderRadius: 10,
                          background: '#fff0f0',
                          color: '#b42318',
                          fontSize: 12,
                          fontWeight: 700,
                        }}
                      >
                        {draftError}
                      </div>
                    )}
                  </FloatingToolPanel>
                )}

                {mode === 'connector' && panelPosition && (
                  <VerticalConnectionsPanel
                    t={t}
                    activeMap={activeMap}
                    mapGroup={mapGroups.find((g) => g.id === activeMap?.mapGroupId) || null}
                    floorOptions={floorSelectOptions}
                    selectedMapId={selectedMapId}
                    onFloorChange={handleFloorSwitch}
                    floorLabel={t.floor}
                    pendingClick={connectorPendingClick}
                    onClickConsumed={() => setConnectorPendingClick(null)}
                    onStopsChanged={() => refreshRouteGraph(activeMap?.id)}
                    position={panelPosition}
                    onPositionChange={setPanelPosition}
                    isCollapsed={isPanelCollapsed}
                    onToggleCollapse={() => setIsPanelCollapsed((prev) => !prev)}
                    onDragStateChange={(dragging) => {
                      isPanelDraggingRef.current = dragging;
                    }}
                    containerRef={fullMapWorkspaceRef}
                    snapTopOffset={76}
                    isRTL={isRTL}
                  />
                )}

                {mode === 'test' && panelPosition && (
                  <FloatingToolPanel
                    title={t.testMode}
                    position={panelPosition}
                    onPositionChange={setPanelPosition}
                    isCollapsed={isPanelCollapsed}
                    onToggleCollapse={() => setIsPanelCollapsed((prev) => !prev)}
                    onDragStateChange={(dragging) => {
                      isPanelDraggingRef.current = dragging;
                    }}
                    containerRef={fullMapWorkspaceRef}
                    snapTopOffset={76}
                    isRTL={isRTL}
                    showSnapControls
                    moveLabel={t.panelMove}
                    minimizeLabel={t.panelMinimize}
                    restoreLabel={t.panelRestore}
                    snapLabels={{
                      left: t.panelDockLeft,
                      right: t.panelDockRight,
                      bottom: t.panelDockBottom,
                    }}
                    footer={
                      <div
                        className="adm-form-actions"
                        style={{ flexWrap: 'wrap', gap: 8 }}
                      >
                        <button
                          type="button"
                          className="adm-btn adm-btn-cancel"
                          disabled={!testResult && !testError}
                          onClick={handleClearTest}
                        >
                          {t.testClear}
                        </button>

                        <button
                          type="button"
                          className="adm-btn adm-btn-primary"
                          disabled={
                            isTestLoading || !testStartId || !testEndId
                          }
                          onClick={handleFindRoute}
                        >
                          {isTestLoading ? t.testCalculating : t.testFind}
                        </button>
                      </div>
                    }
                  >
                    {renderFloorSelect(t.floor, 'test')}

                    {!testStartId ? (
                      <div className="adm-form-group">
                        <label className="adm-form-label">
                          {t.testStart}
                        </label>
                        <select
                          className="adm-form-input"
                          value=""
                          onChange={(event) =>
                            setTestStartId(event.target.value)
                          }
                        >
                          <option value="">{t.testSelectStart}</option>
                          {routePoints.map((point) => (
                            <option
                              key={point.id || point._id}
                              value={point.id || point._id}
                            >
                              {point.name} ({point.point_type})
                            </option>
                          ))}
                        </select>
                      </div>
                    ) : (
                      <div
                        style={{
                          marginBottom: 10,
                          fontSize: 12.5,
                          color: '#173b70',
                        }}
                      >
                        <strong>{t.testStart}:</strong>{' '}
                        {
                          routePoints.find(
                            (point) =>
                              (point.id || point._id) === testStartId,
                          )?.name
                        }{' '}
                        <button
                          type="button"
                          onClick={handleChangeTestStart}
                          style={{
                            border: 'none',
                            background: 'none',
                            color: '#4a7ac8',
                            fontWeight: 700,
                            cursor: 'pointer',
                            fontSize: 11.5,
                          }}
                        >
                          {t.testChangeStart}
                        </button>
                      </div>
                    )}

                    {!testEndId ? (
                      <div className="adm-form-group">
                        <label className="adm-form-label">
                          {t.testEnd}
                        </label>
                        <select
                          className="adm-form-input"
                          value=""
                          onChange={(event) =>
                            setTestEndId(event.target.value)
                          }
                        >
                          <option value="">{t.testSelectEnd}</option>
                          {routePoints.map((point) => (
                            <option
                              key={point.id || point._id}
                              value={point.id || point._id}
                            >
                              {point.name} ({point.point_type})
                            </option>
                          ))}
                        </select>
                      </div>
                    ) : (
                      <div
                        style={{
                          marginBottom: 10,
                          fontSize: 12.5,
                          color: '#173b70',
                        }}
                      >
                        <strong>{t.testEnd}:</strong>{' '}
                        {
                          routePoints.find(
                            (point) =>
                              (point.id || point._id) === testEndId,
                          )?.name
                        }{' '}
                        <button
                          type="button"
                          onClick={handleChangeTestEnd}
                          style={{
                            border: 'none',
                            background: 'none',
                            color: '#4a7ac8',
                            fontWeight: 700,
                            cursor: 'pointer',
                            fontSize: 11.5,
                          }}
                        >
                          {t.testChangeEnd}
                        </button>
                      </div>
                    )}

                    {testError && (
                      <div
                        style={{
                          marginBottom: 10,
                          padding: 8,
                          borderRadius: 10,
                          background: '#fff0f0',
                          color: '#b42318',
                          fontSize: 12,
                          fontWeight: 700,
                        }}
                      >
                        {testError}
                      </div>
                    )}

                    {testResult && (
                      <div
                        style={{
                          marginBottom: 10,
                          padding: 8,
                          borderRadius: 10,
                          background: '#eafaf0',
                          color: '#1a7f37',
                          fontSize: 12,
                          fontWeight: 700,
                        }}
                      >
                        {t.testDistance(testResult.total_distance)}
                        <br />
                        {t.testStepCount(
                          (testResult.path_point_ids || []).length,
                        )}
                      </div>
                    )}
                  </FloatingToolPanel>
                )}

                {mode === 'point' && clickedPoint && panelPosition && (
                  <FloatingToolPanel
                    title={t.addPoint}
                    position={panelPosition}
                    onPositionChange={setPanelPosition}
                    isCollapsed={isPanelCollapsed}
                    onToggleCollapse={() => setIsPanelCollapsed((prev) => !prev)}
                    onDragStateChange={(dragging) => {
                      isPanelDraggingRef.current = dragging;
                    }}
                    containerRef={fullMapWorkspaceRef}
                    snapTopOffset={76}
                    isRTL={isRTL}
                    showSnapControls
                    moveLabel={t.panelMove}
                    minimizeLabel={t.panelMinimize}
                    restoreLabel={t.panelRestore}
                    snapLabels={{
                      left: t.panelDockLeft,
                      right: t.panelDockRight,
                      bottom: t.panelDockBottom,
                    }}
                    footer={
                      <div className="adm-form-actions">
                        <button
                          className="adm-btn adm-btn-cancel"
                          onClick={() => {
                            setClickedPoint(
                              null,
                            );

                            setPointName('');
                            setSelectedBuildingId('');
                            setSelectedRoomId('');
                          }}
                        >
                          {t.cancel}
                        </button>

                        <button
                          className="adm-btn adm-btn-primary"
                          onClick={
                            saveRoutePoint
                          }
                        >
                          {t.savePoint}
                        </button>
                      </div>
                    }
                  >
                    <div
                      style={{
                        fontWeight: 700,
                        color: '#173b70',
                        marginBottom: 10,
                      }}
                    >
                      X: {clickedPoint.x} |
                      Y: {clickedPoint.y}
                    </div>

                    <div className="adm-form-group">
                      <label className="adm-form-label">
                        {t.pointName}
                      </label>

                      <input
                        className="adm-form-input"
                        value={pointName}
                        onChange={(event) =>
                          setPointName(
                            event.target
                              .value,
                          )
                        }
                      />

                      {/* Section 16 — "Choose name from approved map
                          data": lets the admin pick a meaningful name
                          from published semantic entities instead of
                          typing a technical one. Purely fills the same
                          name field above; never places a point, never
                          touches coordinates/edges. */}
                      {activeMap?.id && (
                        <SemanticNameSelector
                          mapId={activeMap.id}
                          lang={lang}
                          onSelect={(picked) => setPointName(picked.displayName)}
                        />
                      )}
                    </div>

                    <div className="adm-form-group">
                      <label className="adm-form-label">
                        {t.pointType}
                      </label>

                      <select
                        className="adm-form-input"
                        value={pointType}
                        onChange={(event) =>
                          setPointType(
                            event.target
                              .value,
                          )
                        }
                      >
                        <option value="entrance">
                          entrance
                        </option>

                        <option value="hallway">
                          hallway
                        </option>

                        <option value="junction">
                          junction
                        </option>

                        <option value="stairs">
                          stairs
                        </option>

                        <option value="elevator">
                          elevator
                        </option>

                        <option value="room">
                          room
                        </option>

                        <option value="store">
                          store
                        </option>
                      </select>

                      {/* Destination data flow — a "room"/"store" point
                          automatically gets a linked destination Room on
                          save (no second Add Room step needed). */}
                      {isPlaceType && (
                        <div className="adm-point-destination-hint">
                          {t.pointWillBecomeDestination}
                        </div>
                      )}
                    </div>

                    {isPlaceType && (
                      <>
                        <div className="adm-form-group">
                          <label className="adm-form-label">
                            {t.building}
                          </label>

                          <select
                            className="adm-form-input"
                            value={selectedBuildingId}
                            onChange={(event) => {
                              setSelectedBuildingId(event.target.value);
                              setSelectedRoomId('');
                            }}
                          >
                            <option value="">{t.selectBuilding}</option>
                            {buildingsList.map((building) => (
                              <option key={building.id} value={building.id}>
                                {building.name_en || building.id}
                              </option>
                            ))}
                          </select>
                        </div>

                        <div className="adm-form-group">
                          <label className="adm-form-label">
                            {t.room}
                          </label>

                          <select
                            className="adm-form-input"
                            value={selectedRoomId}
                            disabled={
                              !selectedBuildingId || isRoomsLoading
                            }
                            onChange={(event) =>
                              setSelectedRoomId(event.target.value)
                            }
                          >
                            <option value="">{t.selectRoom}</option>
                            {roomsList.map((room) => (
                              <option key={room.id} value={room.id}>
                                {room.name_en || room.id}
                              </option>
                            ))}
                          </select>

                          {selectedRoomId &&
                            (() => {
                              const alreadyLinked = routePoints.find(
                                (point) => point.room_id === selectedRoomId,
                              );

                              if (!alreadyLinked) return null;

                              return (
                                <div
                                  style={{
                                    marginTop: 6,
                                    fontSize: 11.5,
                                    color: '#b47b09',
                                  }}
                                >
                                  {t.roomAlreadyLinked(alreadyLinked.name)}
                                </div>
                              );
                            })()}
                        </div>
                      </>
                    )}

                    {renderFloorSelect(t.floor, 'point')}

                    <label
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: 8,
                        marginBottom: 14,
                        fontSize: 12.5,
                        fontWeight: 700,
                        color: '#315b8f',
                        cursor: 'pointer',
                      }}
                    >
                      <input
                        type="checkbox"
                        checked={connectToNearest}
                        onChange={(event) =>
                          setConnectToNearest(event.target.checked)
                        }
                      />
                      {t.connectNearest}
                    </label>
                  </FloatingToolPanel>
                )}

                {/* Floor switcher: only rendered when the active map belongs
                    to a multi-floor MapGroup with more than one floor.
                    Workspace-level sibling of the map stage (top-left
                    corner, mirroring the close button at top-right) so its
                    position never depends on the current map's aspect
                    ratio or panel docking. Switching calls
                    handleFloorSwitch (never handleMapSelection — see its
                    comment) which clears any in-progress draft, resets
                    Test Route selections, and swaps selectedMapId so the
                    routePoints/routeEdges effects reload strictly for the
                    newly selected floor's own map_id. Coordinates and
                    points from the previous floor are never merged onto
                    the new floor's image. */}
                {activeMapGroupFloors.length > 1 && (
                  <div
                    style={{
                      position: 'absolute',
                      top: 24,
                      left: 24,
                      zIndex: 2,
                      display: 'flex',
                      flexWrap: 'wrap',
                      gap: 6,
                      maxWidth: '55vw',
                      background: 'rgba(255,255,255,0.94)',
                      borderRadius: 14,
                      padding: 8,
                      boxShadow: '0 4px 18px rgba(23,59,112,0.18)',
                    }}
                  >
                    <div
                      style={{
                        width: '100%',
                        fontSize: 10.5,
                        fontWeight: 800,
                        color: '#7891ac',
                        textTransform: 'uppercase',
                        letterSpacing: 0.4,
                        marginBottom: 2,
                      }}
                    >
                      {t.floorSwitcher}
                    </div>
                    {activeMapGroupFloors.map((floorMap) => {
                      const isActive = floorMap.id === selectedMapId;
                      return (
                        <button
                          key={floorMap.id}
                          type="button"
                          onClick={() => handleFloorSwitch(floorMap.id)}
                          style={{
                            border: isActive ? '2px solid #1f5fae' : '1px solid #dde8f5',
                            borderRadius: 999,
                            padding: '5px 12px',
                            fontSize: 12,
                            fontWeight: 700,
                            background: isActive ? '#1f5fae' : 'white',
                            color: isActive ? 'white' : '#315b8f',
                            cursor: 'pointer',
                          }}
                        >
                          {formatFloorDisplay(floorMap.floor, floorMap.floorLabel)}
                        </button>
                      );
                    })}
                  </div>
                )}

                {/* Close button: a workspace-level sibling of the map stage
                    and the floating panel, positioned against the
                    workspace's own corner (not the map stage), so it stays
                    put and reachable regardless of the map's aspect ratio
                    or where the panel is currently docked. Rendered after
                    the panel in source order so it always paints above it
                    in the rare case a docked/dragged panel would otherwise
                    overlap this corner. */}
                <button
                  type="button"
                  aria-label={t.back}
                  onClick={() =>
                    setIsMapOpen(false)
                  }
                  style={{
                    position: 'absolute',
                    top: 24,
                    right: 24,
                    width: 50,
                    height: 50,
                    border: 'none',
                    borderRadius: '50%',
                    cursor: 'pointer',
                    fontSize: 28,
                    background: 'white',
                    color: '#173b70',
                    zIndex: 2,
                  }}
                >
                  ×
                </button>
              </div>
            </div>
          )}
      </div>
    </div>
  );
};

export default AdminMapScreen;