import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { useLang } from '../context/LangContext';
import { formatFloor } from '../components/DestinationCard';
import RouteSteps from '../components/RouteSteps';
import BackButton from '../components/BackButton';
import { getCurrentMap } from '../api/mapsApi';
import { getRoutePoints, getRoutePointById } from '../api/routePointsApi';
import { calculateRoute } from '../api/navigationApi';
import {
  formatDistance,
  formatTime,
  estimateTimeFromDistance,
  buildStepsFromPath,
} from '../utils/routeHelpers';
import '../styles/IndoorNavigationScreen.css';

// Same key BarcodeEntryScreen writes to after a location code resolves.
// If present and it matches the map currently loaded, IndoorNavigationScreen
// starts from that exact RoutePoint instead of the map's first entrance.
const START_LOCATION_KEY = 'quickroute_start_location';

// ── Translations ──────────────────────────────────────────────────────────────
const UI = {
  en: {
    back:        'Back',
    destination: 'Your Destination',
    routeReady:  'Route ready',
    navigating:  'Navigating',
    arrived:     'Arrived',
    startNav:    'Start Navigation',
    cancelNav:   'Cancel navigation',
    done:        'Done',
    you:         'You',
    directions:  'Directions',
    navHint:     'Tap ✓ on each step when completed',
    arrivedTitle:'You have arrived!',
    arrivedSub:  'Destination reached',
    loadingMap:  'Loading map...',
    loadingRoute:'Calculating route...',
    noMap:       'No map available yet',
    noMapHint:   'An admin needs to upload a campus map first',
    noRoute:     'No route is available between the selected points',
    noRouteHint: 'This destination has not been connected to the navigation network yet',
    noStartPoint:'No entrance point has been set up on the current map yet',
  },
  ar: {
    back:        'رجوع',
    destination: 'وجهتك',
    routeReady:  'المسار جاهز',
    navigating:  'جارٍ التنقل',
    arrived:     'وصلت',
    startNav:    'ابدأ التنقل',
    cancelNav:   'إلغاء التنقل',
    done:        'تم',
    you:         'أنت',
    directions:  'التعليمات',
    navHint:     'اضغط ✓ بعد إتمام كل خطوة',
    arrivedTitle:'لقد وصلت!',
    arrivedSub:  'تم الوصول إلى الوجهة',
    loadingMap:  'جاري تحميل الخريطة...',
    loadingRoute:'جاري حساب المسار...',
    noMap:       'لا توجد خريطة متاحة بعد',
    noMapHint:   'يجب على المشرف رفع خريطة الحرم أولاً',
    noRoute:     'لا يوجد مسار متاح بين النقطتين المختارتين',
    noRouteHint: 'لم يتم ربط هذه الوجهة بشبكة التنقل بعد',
    noStartPoint:'لم يتم إعداد نقطة دخول على الخريطة الحالية بعد',
  },
  he: {
    back:        'חזרה',
    destination: 'היעד שלך',
    routeReady:  'מסלול מוכן',
    navigating:  'מנווט',
    arrived:     'הגעת',
    startNav:    'התחל ניווט',
    cancelNav:   'בטל ניווט',
    done:        'סיום',
    you:         'אתה',
    directions:  'הוראות',
    navHint:     'הקש ✓ בכל שלב שהשלמת',
    arrivedTitle:'הגעת ליעד!',
    arrivedSub:  'הגעת ליעדך',
    loadingMap:  'טוען מפה...',
    loadingRoute:'מחשב מסלול...',
    noMap:       'עדיין אין מפה זמינה',
    noMapHint:   'על מנהל להעלות מפת קמפוס תחילה',
    noRoute:     'אין מסלול זמין בין הנקודות שנבחרו',
    noRouteHint: 'היעד הזה עדיין לא חובר לרשת הניווט',
    noStartPoint:'עדיין לא הוגדרה נקודת כניסה במפה הנוכחית',
  },
};

// ── Icons ─────────────────────────────────────────────────────────────────────

const ClockIcon = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
    <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="1.8"/>
    <path d="M12 7v5l3 2" stroke="currentColor" strokeWidth="1.8"
      strokeLinecap="round" strokeLinejoin="round"/>
  </svg>
);

const WalkIcon = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
    <circle cx="12" cy="4" r="2" stroke="currentColor" strokeWidth="1.8"/>
    <path d="M9 20l1.5-5L9 12l3 2 2.5-4" stroke="currentColor"
      strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/>
    <path d="M7 8.5L9 12M15 8l-1.5 3.5" stroke="currentColor"
      strokeWidth="1.8" strokeLinecap="round"/>
  </svg>
);

const NavArrow = ({ flip }) => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none"
    style={flip ? { transform: 'scaleX(-1)' } : undefined}>
    <path d="M5 12h14M13 6l6 6-6 6" stroke="currentColor"
      strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"/>
  </svg>
);

const BigCheckIcon = () => (
  <svg width="28" height="28" viewBox="0 0 24 24" fill="none">
    <circle cx="12" cy="12" r="11" fill="rgba(39,174,96,0.15)" stroke="#27ae60" strokeWidth="1.5"/>
    <path d="M7 12l4 4 6-7" stroke="#27ae60" strokeWidth="2.2"
      strokeLinecap="round" strokeLinejoin="round"/>
  </svg>
);

const MapPlaceholderIcon = () => (
  <svg width="34" height="34" viewBox="0 0 24 24" fill="none">
    <path d="M9 20L3 17V4l6 3M9 20l6-3M9 20V7M15 17l6 3V7l-6-3M15 17V4M9 7l6-3"
      stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"/>
  </svg>
);

// ── Real-map route overlay ─────────────────────────────────────────────────
// Draws the actual returned path (a list of real RoutePoint x/y coordinates,
// which are pixel coordinates on the uploaded map image) on top of the
// real map image. No coordinates here are invented — they come straight
// from the backend's path_details response.
const RouteOverlay = ({ imageRef, metrics, pathDetails, hasArrived }) => {
  if (!metrics || !Array.isArray(pathDetails) || pathDetails.length === 0) {
    return null;
  }

  const routeColor = hasArrived ? '#27ae60' : '#4a7ac8';

  const toPosition = (point) => {
    const x = Number(point.x);
    const y = Number(point.y);
    if (!Number.isFinite(x) || !Number.isFinite(y)) return null;

    return {
      left: (x / metrics.naturalWidth) * metrics.displayWidth,
      top: (y / metrics.naturalHeight) * metrics.displayHeight,
    };
  };

  const positions = pathDetails.map(toPosition).filter(Boolean);

  if (positions.length === 0) return null;

  const pathD = positions
    .map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.left} ${p.top}`)
    .join(' ');

  const start = positions[0];
  const dest = positions[positions.length - 1];

  return (
    <svg
      className="s18-route-svg"
      viewBox={`0 0 ${metrics.displayWidth} ${metrics.displayHeight}`}
      preserveAspectRatio="none"
      xmlns="http://www.w3.org/2000/svg"
    >
      <path d={pathD}
        stroke={hasArrived ? 'rgba(39,174,96,0.22)' : 'rgba(74,122,200,0.22)'}
        strokeWidth="8" fill="none" strokeLinecap="round" strokeLinejoin="round"/>

      <path className="s18-route-path" d={pathD}
        stroke={routeColor} strokeWidth="3.5" fill="none"
        strokeLinecap="round" strokeLinejoin="round"/>

      {positions.slice(1, -1).map((p, i) => (
        <circle key={i} cx={p.left} cy={p.top} r="4" fill={routeColor} opacity="0.55"/>
      ))}

      {start && (
        <>
          <circle cx={start.left} cy={start.top} r="7" fill="white" stroke={routeColor} strokeWidth="2.5"/>
          <circle cx={start.left} cy={start.top} r="3.5" fill={routeColor}/>
        </>
      )}

      {dest && (
        <>
          <circle cx={dest.left} cy={dest.top} r="7" fill="white" opacity="0.95"/>
          <circle cx={dest.left} cy={dest.top} r="3.5" fill={routeColor}/>
        </>
      )}
    </svg>
  );
};

// ── Screen ────────────────────────────────────────────────────────────────────
const IndoorNavigationScreen = () => {
  const { lang }  = useLang();
  const navigate  = useNavigate();
  const location  = useLocation();

  const isRTL = lang === 'ar' || lang === 'he';
  const t     = UI[lang];

  const building = location.state?.building    ?? null;
  const room     = location.state?.destination ?? location.state?.room ?? null;

  // Navigation (walkthrough) state
  const [isNavigating, setIsNavigating]     = useState(false);
  const [completedSteps, setCompletedSteps] = useState(new Set());

  // Real map + real route state
  const [map, setMap]                 = useState(null);
  const [mapLoading, setMapLoading]   = useState(true);
  const [mapError, setMapError]       = useState('');

  const [routeResult, setRouteResult] = useState(null);
  const [routeLoading, setRouteLoading] = useState(false);
  const [routeError, setRouteError]     = useState('');

  const [imgMetrics, setImgMetrics] = useState(null);
  const mapImageRef = useRef(null);

  // 1. Load the real current map.
  useEffect(() => {
    let cancelled = false;

    const loadMap = async () => {
      setMapLoading(true);
      setMapError('');

      try {
        const data = await getCurrentMap();

        if (!cancelled) {
          setMap(data);
          if (!data?.hasImage) setMapError(t.noMap);
        }
      } catch (err) {
        console.error('Failed to load current map:', err);

        if (!cancelled) {
          setMap(null);
          setMapError(t.noMap);
        }
      } finally {
        if (!cancelled) setMapLoading(false);
      }
    };

    loadMap();

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 2. Resolve real start/end route points for this map + room, then call
  //    the real navigation API. No local/fake route is ever calculated.
  useEffect(() => {
    if (!map?.id) return undefined;

    let cancelled = false;

    const loadRoute = async () => {
      setRouteLoading(true);
      setRouteError('');
      setRouteResult(null);

      try {
        let startPoint = null;

        // Prefer a start point resolved from a scanned/typed location code,
        // but only if it was resolved for this exact map — a code scanned
        // for a different building/map must never be used here.
        let resolvedStart = null;
        try {
          const raw = localStorage.getItem(START_LOCATION_KEY);
          resolvedStart = raw ? JSON.parse(raw) : null;
        } catch {
          resolvedStart = null;
        }

        if (resolvedStart?.routePointId && resolvedStart.mapId === map.id) {
          try {
            const point = await getRoutePointById(resolvedStart.routePointId);
            if (point && point.map_id === map.id) {
              startPoint = point;
            }
          } catch (lookupErr) {
            // The resolved point no longer exists (e.g. deleted since the
            // code was scanned) — fall back to the default entrance below.
            console.warn('Resolved start point lookup failed:', lookupErr);
          }
        }

        if (!startPoint) {
          const entrancePoints = await getRoutePoints({
            map_id: map.id,
            point_type: 'entrance',
          });

          startPoint = Array.isArray(entrancePoints) ? entrancePoints[0] : null;
        }

        if (!startPoint) {
          if (!cancelled) setRouteError(t.noStartPoint);
          return;
        }

        if (!room?.id) {
          // No destination selected — nothing to route to.
          return;
        }

        const destinationPoints = await getRoutePoints({
          map_id: map.id,
          room_id: room.id,
        });

        const endPoint = Array.isArray(destinationPoints) ? destinationPoints[0] : null;

        if (!endPoint) {
          if (!cancelled) setRouteError(t.noRoute);
          return;
        }

        const result = await calculateRoute({
          mapId: map.id,
          startPointId: startPoint.id,
          endPointId: endPoint.id,
        });

        if (!cancelled) setRouteResult(result);
      } catch (err) {
        console.error('Failed to calculate route:', err);
        if (!cancelled) setRouteError(t.noRoute);
      } finally {
        if (!cancelled) setRouteLoading(false);
      }
    };

    loadRoute();

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [map?.id, room?.id]);

  const pathDetails = routeResult?.path_details ?? [];
  const totalDistance = routeResult?.total_distance ?? null;
  const timeMin = totalDistance != null ? estimateTimeFromDistance(totalDistance) : null;

  const steps = useMemo(
    () => buildStepsFromPath(pathDetails, lang),
    [pathDetails, lang]
  );

  const activeStep = steps.findIndex((_, i) => !completedSteps.has(i));
  const hasArrived = isNavigating && steps.length > 0 && completedSteps.size === steps.length;

  const handleStepToggle = (index) => {
    setCompletedSteps(prev => {
      const next = new Set(prev);
      if (next.has(index)) next.delete(index);
      else next.add(index);
      return next;
    });
  };

  const handleStartNav = () => {
    setIsNavigating(true);
    setCompletedSteps(new Set());
  };

  const handleCancelNav = () => {
    setIsNavigating(false);
    setCompletedSteps(new Set());
  };

  const syncImgMetrics = () => {
    const image = mapImageRef.current;
    if (!image?.naturalWidth || !image?.naturalHeight) return;

    const rect = image.getBoundingClientRect();

    setImgMetrics({
      displayWidth: rect.width,
      displayHeight: rect.height,
      naturalWidth: image.naturalWidth,
      naturalHeight: image.naturalHeight,
    });
  };

  useEffect(() => {
    const handleResize = () => syncImgMetrics();
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);

  const mapImageUrl = map?.displayImageUrl || map?.sourceImageUrl || map?.imageUrl || null;
  const hasRealRoute = pathDetails.length > 0;

  // Badge config
  const badgeClass = hasArrived
    ? 's18-route-badge s18-route-badge--arrived'
    : isNavigating
      ? 's18-route-badge s18-route-badge--nav'
      : 's18-route-badge';
  const badgeText = hasArrived ? t.arrived : isNavigating ? t.navigating : t.routeReady;

  return (
    <div className="layout-wrapper">
      <div className="layout-shell s18-shell" dir={isRTL ? 'rtl' : 'ltr'}>

        {/* ── Header ── */}
        <div className="s18-header">
          <BackButton
            onClick={() => navigate('/screen/17', { state: { building } })}
            label={t.back}
            isRTL={isRTL}
            spacing="compact"
          />

          {building && (
            <div className="s18-header-info">
              <span className="s18-header-building">{building.name}</span>
              {room && (
                <>
                  <span className="s18-header-sep">·</span>
                  <span className="s18-header-room">{room.name}</span>
                </>
              )}
            </div>
          )}
        </div>

        {/* ── Map ── */}
        <div className="s18-map-wrap">
          <div className={`s18-map-container${isNavigating ? ' s18-map-container--nav' : ''}`}>
            {mapLoading ? (
              <div className="s18-map-empty">
                <p>{t.loadingMap}</p>
              </div>
            ) : mapImageUrl ? (
              <>
                <img
                  ref={mapImageRef}
                  src={mapImageUrl}
                  alt={map?.title || 'Campus map'}
                  className="s18-map-img"
                  style={{ objectFit: 'contain', background: '#eef3f9' }}
                  draggable="false"
                  onLoad={syncImgMetrics}
                />
                {hasRealRoute && (
                  <RouteOverlay
                    imageRef={mapImageRef}
                    metrics={imgMetrics}
                    pathDetails={pathDetails}
                    hasArrived={hasArrived}
                  />
                )}
              </>
            ) : (
              <div className="s18-map-empty">
                <MapPlaceholderIcon />
                <p>{mapError || t.noMap}</p>
              </div>
            )}
          </div>

          {hasRealRoute && (
            <div className={badgeClass}>
              <span className="s18-route-dot" />
              <span>{badgeText}</span>
            </div>
          )}
        </div>

        {/* ── Scrollable bottom ── */}
        <div className="s18-bottom">

          {/* Arrival banner */}
          {hasArrived && (
            <div className="s18-arrival">
              <BigCheckIcon />
              <div className="s18-arrival-text">
                <p className="s18-arrival-title">{t.arrivedTitle}</p>
                <p className="s18-arrival-sub">{t.arrivedSub}</p>
              </div>
            </div>
          )}

          {/* Info card */}
          <div className={`s18-info-card${hasArrived ? ' s18-info-card--arrived' : ''}`}>
            <p className="s18-dest-label">{t.destination}</p>

            {building ? (
              <>
                <h2 className="s18-dest-name">{room ? room.name : building.name}</h2>
                <p className="s18-dest-meta">
                  <span
                    className="s18-building-chip"
                    style={{ color: building.iconColor, background: building.iconBg }}
                  >
                    {building.tag}
                  </span>
                  {room && (
                    <>
                      <span className="s18-floor-chip">{formatFloor(room.floor)}</span>
                      <span className="s18-type-chip">{room.type.replace('_', ' ')}</span>
                    </>
                  )}
                </p>
              </>
            ) : (
              <h2 className="s18-dest-name">—</h2>
            )}

            <div className="s18-stats">
              <div className="s18-stat">
                <ClockIcon />
                <span>{timeMin != null ? formatTime(timeMin) : '—'}</span>
              </div>
              <div className="s18-stat-divider" />
              <div className="s18-stat">
                <WalkIcon />
                <span>{totalDistance != null ? formatDistance(totalDistance) : '—'}</span>
              </div>
            </div>
          </div>

          {/* Route status / empty states — never a fake fallback route */}
          {routeLoading && (
            <div className="s18-info-card">
              <p>{t.loadingRoute}</p>
            </div>
          )}

          {!routeLoading && routeError && (
            <div className="s18-info-card">
              <p>{routeError}</p>
              <p className="s18-dest-meta" style={{ marginTop: 6 }}>{t.noRouteHint}</p>
            </div>
          )}

          {/* Directions section — built only from the real returned path */}
          {!routeLoading && !routeError && steps.length > 0 && (
            <div className="s18-directions">
              <div className="s18-directions-header">
                <p className="s18-directions-label">{t.directions}</p>
                {isNavigating && !hasArrived && (
                  <p className="s18-nav-hint">{t.navHint}</p>
                )}
              </div>
              <RouteSteps
                outdoorSteps={steps}
                indoorSteps={[]}
                lang={lang}
                isNavigating={isNavigating}
                completedSteps={completedSteps}
                activeStep={activeStep}
                onStepToggle={handleStepToggle}
              />
            </div>
          )}

          {/* Bottom action */}
          {steps.length > 0 && (
            hasArrived ? (
              <button className="s18-done-btn" type="button" onClick={handleCancelNav}>
                <span>{t.done}</span>
              </button>
            ) : isNavigating ? (
              <button className="s18-cancel-btn" type="button" onClick={handleCancelNav}>
                {t.cancelNav}
              </button>
            ) : (
              <button className="s18-nav-btn" type="button" onClick={handleStartNav}>
                <span>{t.startNav}</span>
                <NavArrow flip={isRTL} />
              </button>
            )
          )}

        </div>
      </div>
    </div>
  );
};

export default IndoorNavigationScreen;
