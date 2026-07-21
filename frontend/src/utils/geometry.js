// Small geometry helpers shared by the admin map-editing tools (Draw
// Walkable Path, Connect Place). All distances here operate in original
// image pixel space — the same coordinate system RoutePoint x/y already
// uses — never in on-screen/display pixels.

export function pixelDistance(ax, ay, bx, by) {
  return Math.sqrt((bx - ax) ** 2 + (by - ay) ** 2);
}

// Finds the closest RoutePoint to (x, y) that is within `thresholdPx` and,
// when `floor` is provided, on the same floor. Returns null when nothing
// is close enough — the caller should then treat the click as a brand new
// point instead of reusing an existing one.
export function findNearestPointWithinThreshold(points, x, y, thresholdPx, floor) {
  let closest = null;
  let closestDistance = Infinity;

  for (const point of points) {
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
