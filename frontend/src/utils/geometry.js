// Small geometry helpers shared by the admin map-editing tools (Draw
// Walkable Path, Connect Place). All distances here operate in original
// image pixel space — the same coordinate system RoutePoint x/y already
// uses — never in on-screen/display pixels.

export function pixelDistance(ax, ay, bx, by) {
  return Math.sqrt((bx - ax) ** 2 + (by - ay) ** 2);
}

// Turns a "comfortable to click" screen-pixel radius into the equivalent
// radius in the map's original-image pixel space, given the current
// render scale (naturalWidth / renderedWidth — i.e. how many native
// pixels one on-screen pixel currently represents).
//
// This exists because a *fixed* native-pixel snap threshold silently
// breaks on any map whose native resolution is much larger than its
// on-screen size — which is the common case: PDF maps are rasterized at
// ~200 DPI (backend MAP_PDF_RENDER_DPI) and easily end up several
// thousand pixels wide while the admin panel renders them in a
// few-hundred-pixel-wide container. A "click directly on" a point in that
// situation can be dozens of native pixels away from the stored x/y even
// though it lands squarely on the rendered marker on screen, so a small
// fixed native threshold (e.g. 18px) can shrink to just a handful of
// *screen* pixels — effectively impossible to hit on purpose. Scaling the
// threshold by the live render ratio keeps the actual clickable target a
// consistent, comfortable size on screen regardless of the map's native
// resolution or how zoomed in the current view is.
export function resolveSnapThresholdPx(screenPx, scale, minNativePx = 0) {
  const safeScale = Number.isFinite(scale) && scale > 0 ? scale : 1;
  return Math.max(screenPx * safeScale, minNativePx);
}

// Finds the closest RoutePoint to (x, y) that is within `thresholdPx` and,
// when `floor` is provided, on the same floor. Inactive points are never
// offered as a reuse target. Returns null when nothing is close enough —
// the caller should then treat the click as a brand new point instead of
// reusing an existing one.
export function findNearestPointWithinThreshold(points, x, y, thresholdPx, floor) {
  let closest = null;
  let closestDistance = Infinity;

  for (const point of points) {
    if (point.is_active === false) {
      continue;
    }

    if (floor !== undefined && floor !== null && point.floor !== floor) {
      continue;
    }

    const pointX = Number(point.x);
    const pointY = Number(point.y);

    if (!Number.isFinite(pointX) || !Number.isFinite(pointY)) {
      continue;
    }

    const distance = pixelDistance(x, y, pointX, pointY);

    if (distance <= thresholdPx && distance < closestDistance) {
      closest = point;
      closestDistance = distance;
    }
  }

  return closest;
}
