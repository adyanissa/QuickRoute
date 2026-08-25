// Pure helpers for map-based destination placement (AdminRoomsScreen.jsx
// "Select Location on Map" mode) and for the end-user destination
// resolution it feeds (IndoorNavigationScreen.jsx). Kept dependency-free
// so the coordinate math and resolution rules can be unit-tested without
// a DOM/React harness — see destinationPlacement.test.mjs.

// Converts a raw click event's page coordinates into the map's
// original-image pixel coordinate system — the same system RoutePoint
// x/y, the OCR crop, and the corridor-graph overlay already use. This
// must never be confused with on-screen/display pixels, which change
// with zoom, container size, and layout.
export function computeOriginalImageCoords({
  clientX,
  clientY,
  rectLeft,
  rectTop,
  rectWidth,
  rectHeight,
  naturalWidth,
  naturalHeight,
}) {
  if (!rectWidth || !rectHeight || !naturalWidth || !naturalHeight) {
    return null;
  }

  const displayX = clientX - rectLeft;
  const displayY = clientY - rectTop;

  const scaleX = naturalWidth / rectWidth;
  const scaleY = naturalHeight / rectHeight;

  const x = Math.round(displayX * scaleX);
  const y = Math.round(displayY * scaleY);

  // Clamp to the image bounds — a click right on the image's edge can
  // otherwise round to exactly naturalWidth/naturalHeight (one pixel
  // outside the valid 0..naturalWidth-1 index) from floating-point rect
  // measurement.
  return {
    x: Math.min(Math.max(x, 0), naturalWidth),
    y: Math.min(Math.max(y, 0), naturalHeight),
  };
}

// The ONLY way a destination's linked navigation point should ever be
// resolved: the id the backend stored directly on the Room when it was
// placed (RoomResponse.route_point_id). Never "the first RoutePoint
// whose room_id happens to match" — that was the old, fragile lookup —
// and never a hard-coded or nearest-arbitrary fallback.
export function getDestinationRoutePointId(room) {
  return room?.routePointId || room?.route_point_id || null;
}

// A resolved RoutePoint must actually belong to the map currently being
// navigated — the same defensive check IndoorNavigationScreen already
// applies to a location-code-resolved start point, applied symmetrically
// here to the destination end point.
export function pointBelongsToMap(point, mapId) {
  if (!point || !mapId) return false;
  return (point.map_id ?? point.mapId) === mapId;
}

// Only ever called from an explicit admin action ("Use this name") —
// never automatically when an OCR response arrives — so a suggestion can
// never end up saved without the admin consciously applying it first
// (and clicking Save is itself a second, separate confirmation).
export function applySuggestedName(suggestionText) {
  return (suggestionText || '').trim();
}

// Decides what the OCR result panel should show, without any React/DOM
// dependency. Never reports a suggestion as usable when it's empty — an
// empty or low-confidence result is presented as "no reliable
// suggestion", never silently hidden and never auto-filled.
export function summarizeOcrSuggestion(result) {
  if (!result || !result.available) {
    return {
      canApply: false,
      text: '',
      confidence: 0,
      lowConfidence: true,
      message: result?.reason || 'OCR is not available for this map.',
    };
  }

  const text = (result.text || '').trim();

  if (!text) {
    return {
      canApply: false,
      text: '',
      confidence: result.confidence ?? 0,
      lowConfidence: true,
      message: result.reason || 'No legible text found at this location.',
    };
  }

  const lowConfidence = Boolean(result.lowConfidence ?? result.low_confidence);

  return {
    canApply: true,
    text,
    confidence: result.confidence ?? 0,
    lowConfidence,
    message: lowConfidence
      ? 'Low-confidence suggestion — please verify before using it.'
      : null,
  };
}
