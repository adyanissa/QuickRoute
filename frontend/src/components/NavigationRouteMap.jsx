import { useEffect, useState } from 'react';
import { getMapById } from '../api/mapsApi';
import '../styles/NavigationRouteMap.css';

// ── NavigationRouteMap ───────────────────────────────────────────────────────
// End-user route map for IndoorNavigationScreen (professional navigation UX
// redesign, Section 4.E). Renders ONLY:
//   - the active floor's own map image;
//   - the route line through this floor segment's already-backend-computed
//     point order (`segment.coordinates` — the exact path Dijkstra/the
//     multi-floor route builder returned, never reordered or recalculated
//     here);
//   - a start marker (first floor only), a destination marker (last floor
//     only), small connector markers at any floor-transition endpoint, and
//     a "you are here" marker at the user's confirmed progress point.
// It deliberately never renders: RoutePoint names/ids, coordinates, admin
// graph nodes/edges, edge-editing controls, calibration controls, or any
// other admin-only affordance — those remain exclusively in
// screens/AdminMapScreen.jsx. This component only reads a Map document (for
// its image) and the route response already fetched by the parent screen;
// it never writes anything.
const NavigationRouteMap = ({
  segment,
  isFirstFloor,
  isLastFloor,
  activeStepIndex = 0,
  focusActive = false,
  labels = {},
}) => {
  const [mapData, setMapData] = useState(null);
  const [status, setStatus] = useState('idle'); // idle | loading | ready | error
  const [imgMetrics, setImgMetrics] = useState(null);

  const mapId = segment?.map_id || null;

  useEffect(() => {
    if (!mapId) {
      setMapData(null);
      setStatus('idle');
      return undefined;
    }

    let cancelled = false;
    setStatus('loading');
    setImgMetrics(null);

    getMapById(mapId)
      .then((map) => {
        if (cancelled) return;
        setMapData(map);
        setStatus('ready');
      })
      .catch((err) => {
        // Developer detail stays in the console only — the user only ever
        // sees the generic "floor map unavailable" empty state below
        // (Section 11).
        console.error('Failed to load floor map image for navigation:', err);
        if (!cancelled) setStatus('error');
      });

    return () => {
      cancelled = true;
    };
  }, [mapId]);

  const coordinates = Array.isArray(segment?.coordinates) ? segment.coordinates : [];

  if (!segment || coordinates.length === 0) {
    return null;
  }

  const imageUrl =
    mapData?.sourceImageUrl || mapData?.imageUrl || mapData?.displayImageUrl || null;

  if (status === 'idle' || status === 'loading') {
    return (
      <div className="s18-route-map s18-route-map--empty">
        <p>{labels.loading}</p>
      </div>
    );
  }

  if (status === 'error' || !imageUrl) {
    return (
      <div className="s18-route-map s18-route-map--empty">
        <p>{labels.unavailable}</p>
      </div>
    );
  }

  const clampedActiveIndex = Math.max(
    0,
    Math.min(activeStepIndex ?? 0, coordinates.length - 1),
  );

  const lastIndex = coordinates.length - 1;
  const first = coordinates[0];
  const last = coordinates[lastIndex];
  const activePoint = coordinates[clampedActiveIndex];

  const viewBox = imgMetrics
    ? focusActive
      ? computeFocusViewBox(coordinates, clampedActiveIndex, imgMetrics.naturalWidth, imgMetrics.naturalHeight)
      : `0 0 ${imgMetrics.naturalWidth} ${imgMetrics.naturalHeight}`
    : null;

  return (
    <div className="s18-route-map">
      <img
        src={imageUrl}
        alt=""
        className="s18-route-map-img"
        onLoad={(event) =>
          setImgMetrics({
            naturalWidth: event.currentTarget.naturalWidth,
            naturalHeight: event.currentTarget.naturalHeight,
          })
        }
        onError={() => setStatus('error')}
      />

      {imgMetrics && (
        <svg
          viewBox={viewBox}
          preserveAspectRatio="xMidYMid meet"
          className="s18-route-map-svg"
        >
          {/* Completed section — visually muted (Section 4.E visual hierarchy) */}
          {clampedActiveIndex > 0 && (
            <polyline
              points={coordinates
                .slice(0, clampedActiveIndex + 1)
                .map((c) => `${c.x},${c.y}`)
                .join(' ')}
              className="s18-route-line s18-route-line--completed"
              fill="none"
            />
          )}

          {/* Upcoming section — strongest route emphasis */}
          {lastIndex - clampedActiveIndex >= 1 && (
            <polyline
              points={coordinates
                .slice(clampedActiveIndex)
                .map((c) => `${c.x},${c.y}`)
                .join(' ')}
              className="s18-route-line s18-route-line--upcoming"
              fill="none"
            />
          )}

          {/* Connector endpoints (floor transition points), when this floor
              is not the very first/last leg of the whole journey. Plain,
              small, unlabeled markers — never a technical point name. */}
          {!isFirstFloor && first && (
            <circle
              cx={first.x}
              cy={first.y}
              r={Math.max(7, imgMetrics.naturalWidth * 0.007)}
              className="s18-route-marker s18-route-marker--connector"
            />
          )}
          {!isLastFloor && last && (
            <circle
              cx={last.x}
              cy={last.y}
              r={Math.max(7, imgMetrics.naturalWidth * 0.007)}
              className="s18-route-marker s18-route-marker--connector"
            />
          )}

          {/* Start marker — only on the very first floor of the journey */}
          {isFirstFloor && first && (
            <circle
              cx={first.x}
              cy={first.y}
              r={Math.max(8, imgMetrics.naturalWidth * 0.008)}
              className="s18-route-marker s18-route-marker--start"
            />
          )}

          {/* Destination marker — only on the very last floor, clearly
              distinguishable from every other marker (Section 4.E). */}
          {isLastFloor && last && (
            <g>
              <circle
                cx={last.x}
                cy={last.y}
                r={Math.max(10, imgMetrics.naturalWidth * 0.01)}
                className="s18-route-marker s18-route-marker--destination"
              />
              <path
                d={`M ${last.x} ${last.y - imgMetrics.naturalWidth * 0.02} l ${imgMetrics.naturalWidth * 0.006} ${imgMetrics.naturalWidth * 0.012} l -${imgMetrics.naturalWidth * 0.012} 0 z`}
                className="s18-route-marker-flag"
              />
            </g>
          )}

          {/* Current confirmed progress point ("you are here") */}
          {activePoint && (
            <circle
              cx={activePoint.x}
              cy={activePoint.y}
              r={Math.max(6, imgMetrics.naturalWidth * 0.006)}
              className="s18-route-marker s18-route-marker--you"
            />
          )}
        </svg>
      )}
    </div>
  );
};

// Auto-fits a small window of points around the active index into view —
// the closest equivalent to "fit the current relevant route section into
// view" this component implements (there is no manual pan/zoom control to
// preserve here; none existed on this screen before this feature).
function computeFocusViewBox(coordinates, centerIndex, naturalWidth, naturalHeight) {
  const windowSize = 2;
  const minSpan = Math.max(naturalWidth, naturalHeight) * 0.18;

  const start = Math.max(0, centerIndex - windowSize);
  const end = Math.min(coordinates.length - 1, centerIndex + windowSize);
  const slice = coordinates.slice(start, end + 1);

  if (slice.length === 0) {
    return `0 0 ${naturalWidth} ${naturalHeight}`;
  }

  const xs = slice.map((c) => c.x);
  const ys = slice.map((c) => c.y);

  let minX = Math.min(...xs);
  let maxX = Math.max(...xs);
  let minY = Math.min(...ys);
  let maxY = Math.max(...ys);

  const spanX = Math.max(maxX - minX, minSpan);
  const spanY = Math.max(maxY - minY, minSpan);
  const centerX = (minX + maxX) / 2;
  const centerY = (minY + maxY) / 2;

  const padding = 1.6; // extra breathing room around the focused points
  const width = Math.min(naturalWidth, spanX * padding);
  const height = Math.min(naturalHeight, spanY * padding);

  let x = Math.max(0, Math.min(naturalWidth - width, centerX - width / 2));
  let y = Math.max(0, Math.min(naturalHeight - height, centerY - height / 2));

  return `${x} ${y} ${width} ${height}`;
}

export default NavigationRouteMap;
