import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import HospSearchBar from '../components/HospSearchBar';
import DestinationCard from '../components/DestinationCard';
import BackButton from '../components/BackButton';
import QuickRouteLogo from '../components/QuickRouteLogo';
import { useLang } from '../context/LangContext';
import { getRooms } from '../api/roomsApi';
import { roomToViewModel } from '../utils/viewModels';
import { getLocalizedText, matchesLocalizedSearch } from '../utils/localization';
import { resolveDestinationName } from '../utils/destinationDisplayName';
import { formatFloorDisplay } from '../utils/mapGroupHelpers';
import {
  ALL_FLOORS,
  filterRoomsByFloor,
  reconcileFloorSelection,
  resolveFloorOptions,
  shouldShowFloorFilter,
} from '../utils/destinationFloors';
import { ROUTES } from '../config/routes';
import '../styles/DestinationSelectionScreen.css';

// Same key BarcodeEntryScreen writes to after a location code resolves —
// read here (as a fallback to route state) so a starting-location label
// still shows up if this screen is reached without the QR flow's own
// navigation state (e.g. a refresh).
const START_LOCATION_KEY = 'quickroute_start_location';

// Matches the selector on BarcodeEntryScreen one-for-one, and drives the
// SAME LangContext state — this screen adds no language state of its own.
const LANGUAGES = [
  { code: 'en', label: 'EN' },
  { code: 'he', label: 'עברית' },
  { code: 'ar', label: 'عربي' },
];

// ── Icons ────────────────────────────────────────────────────────────────────
// Inline SVG, the same convention every other QuickRoute screen uses. No
// icon package and no image asset is introduced for these.

const PinIcon = ({ size = 18 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true">
    <path
      d="M12 21s7-5.6 7-11a7 7 0 1 0-14 0c0 5.4 7 11 7 11z"
      stroke="currentColor" strokeWidth="1.9" strokeLinejoin="round" fill="none"
    />
    <circle cx="12" cy="10" r="2.6" stroke="currentColor" strokeWidth="1.9" fill="none" />
  </svg>
);

const FloorIcon = ({ size = 18 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true">
    <path
      d="M12 3l8.5 4.5L12 12 3.5 7.5 12 3z"
      stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" fill="none"
    />
    <path
      d="M3.5 12.4L12 16.9l8.5-4.5M3.5 16.9L12 21.4l8.5-4.5"
      stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"
    />
  </svg>
);

// ── Translations ──────────────────────────────────────────────────────────────
const UI = {
  en: {
    subtitle:   'Choose your destination',
    search:     'Search rooms & departments...',
    section:    'Destinations',
    count:      (n) => `${n} destination${n !== 1 ? 's' : ''}`,
    noResults:  'No destinations found',
    noData:     'No destinations found',
    loading:    'Loading destinations...',
    loadError:  'Failed to load destinations',
    back:       'Back',
    floor:      'Floor',
    startingFrom: 'Starting from',
    currentFloor: 'Current floor',
    notConnected: 'Navigation is not available for this destination yet.',
    allFloors:  'All',
    floorFilter: 'Filter destinations by floor',
    current:    'You are here',
  },
  ar: {
    subtitle:   'اختر وجهتك',
    search:     'ابحث عن الغرف...',
    section:    'الوجهات',
    count:      (n) => `${n} وجهة`,
    noResults:  'لا توجد نتائج',
    noData:     'لا توجد وجهات',
    loading:    'جاري تحميل الوجهات...',
    loadError:  'فشل تحميل الوجهات',
    back:       'رجوع',
    floor:      'طابق',
    startingFrom: 'الانطلاق من',
    currentFloor: 'الطابق الحالي',
    notConnected: 'التنقل إلى هذه الوجهة غير متاح بعد.',
    allFloors:  'الكل',
    floorFilter: 'تصفية الوجهات حسب الطابق',
    current:    'أنت هنا',
  },
  he: {
    subtitle:   'בחר יעד',
    search:     'חיפוש חדרים ומחלקות...',
    section:    'יעדים',
    count:      (n) => `${n} יעד`,
    noResults:  'לא נמצאו יעדים',
    noData:     'לא נמצאו יעדים',
    loading:    'טוען יעדים...',
    loadError:  'טעינת היעדים נכשלה',
    back:       'חזרה',
    floor:      'קומה',
    startingFrom: 'יוצא מ־',
    currentFloor: 'קומה נוכחית',
    notConnected: 'הניווט ליעד הזה עדיין לא זמין.',
    allFloors:  'הכל',
    floorFilter: 'סינון יעדים לפי קומה',
    current:    'נמצא כאן',
  },
};

// ── Screen ────────────────────────────────────────────────────────────────────
const DestinationSelectionScreen = () => {
  const { lang, setLang }     = useLang();
  const navigate              = useNavigate();
  const location               = useLocation();
  const [query, setQuery] = useState('');

  const isRTL  = lang === 'ar' || lang === 'he';
  const t      = UI[lang];

  const building = location.state?.building ?? null;

  // Real starting-location context, preferring what the QR flow just
  // resolved (route state) and falling back to the persisted resolve
  // result — never a guessed/fabricated value (Part 5).
  let persistedStart = null;
  try {
    const raw = localStorage.getItem(START_LOCATION_KEY);
    persistedStart = raw ? JSON.parse(raw) : null;
  } catch {
    persistedStart = null;
  }
  const startMatchesBuilding = persistedStart?.buildingId === building?.id;

  const startLabel = location.state?.startLabel
    ?? (startMatchesBuilding ? persistedStart?.label : null)
    ?? null;
  const startFloor = location.state?.startFloor
    ?? (startMatchesBuilding ? persistedStart?.floor : null)
    ?? null;

  // Which map/group the user is actually standing in. Used ONLY to decide
  // which floors are RELATED to them — never to restrict what is listed.
  // Both ids come from the backend's own resolve response (see
  // BarcodeEntryScreen), so this is the real stored relationship, not one
  // the frontend invented.
  const startMapId = startMatchesBuilding ? persistedStart?.mapId ?? null : null;
  const startMapGroupId = startMatchesBuilding
    ? persistedStart?.mapGroupId ?? null
    : null;

  const startContext = useMemo(
    () => ({ mapId: startMapId, mapGroupId: startMapGroupId }),
    [startMapId, startMapGroupId],
  );

  const [rooms, setRooms]     = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError]     = useState('');
  const [floorMapId, setFloorMapId] = useState(ALL_FLOORS);

  // The single in-flight GET /api/rooms, if there is one.
  //
  // Everything that wants rooms goes through requestRooms() and receives
  // the SAME promise while a request is outstanding, so two triggers in
  // quick succession — React StrictMode's double effect invocation in
  // development, or a focus and a visibilitychange arriving for one tab
  // switch — produce ONE network request instead of two. This matters
  // because each of these is a real round trip, and duplicates pile up
  // against the browser's per-origin connection limit (the "Stalled" time
  // in DevTools) rather than being free.
  const roomsRequestRef = useRef(null);

  const requestRooms = useCallback((buildingId) => {
    const existing = roomsRequestRef.current;

    if (existing) {
      if (existing.key === buildingId) return existing.promise;

      // A request for a DIFFERENT building is now stale — abort it rather
      // than let it land and race the one we actually want.
      existing.controller.abort();
    }

    const controller = new AbortController();
    const entry = {
      key: buildingId,
      controller,
      promise: getRooms(
        { building_id: buildingId },
        { signal: controller.signal },
      ),
    };

    roomsRequestRef.current = entry;

    entry.promise
      // Each consumer handles its own errors; this chain exists only so a
      // rejection can never surface as an unhandled promise rejection, and
      // so the slot is freed on failure as well as success.
      .catch(() => {})
      .finally(() => {
        if (roomsRequestRef.current === entry) roomsRequestRef.current = null;
      });

    return entry.promise;
  }, []);

  // Armed when the user leaves (tab hidden or window blurred), consumed by
  // the first event that brings them back. Without it, one return fires
  // BOTH `visibilitychange` and `focus` — two refreshes for one gesture.
  const wasAwayRef = useRef(false);

  useEffect(() => {
    let cancelled = false;
    const buildingId = building?.id ?? null;

    const loadRooms = async () => {
      if (!buildingId) {
        setRooms([]);
        setLoading(false);
        return;
      }

      setLoading(true);
      setError('');

      try {
        const data = await requestRooms(buildingId);

        if (!cancelled) {
          // Never display an inactive destination — Part 3 rule 4.
          const viewModels = (Array.isArray(data) ? data : [])
            .map(roomToViewModel)
            .filter((r) => r.isActive !== false);
          setRooms(viewModels);
        }
      } catch (err) {
        // A request we deliberately superseded is not a failure — it must
        // never reach the user as "Failed to load destinations".
        if (cancelled || err?.name === 'AbortError') return;

        console.error('Failed to load rooms:', err);

        setRooms([]);
        setError(t.loadError);
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    loadRooms();

    // Refetch whenever this tab/window regains focus or becomes visible
    // again — e.g. an admin connected Sakara to the graph in another tab
    // (or the user navigated here, then to Admin, then back) while this
    // screen stayed mounted with its last-fetched (now stale) navigability
    // snapshot. Without this, a destination that just became navigable
    // would stay disabled until an unrelated building-switch/remount.
    //
    // Both listeners are kept, because they cover different departures: a
    // tab switch fires `visibilitychange`, while moving to another WINDOW
    // often leaves the page "visible" and only fires blur/focus. They are
    // funnelled through the armed flag above so one departure-and-return
    // triggers at most ONE refresh, whichever events happen to fire.
    const markAway = () => {
      wasAwayRef.current = true;
    };

    const handleReturn = () => {
      if (document.visibilityState === 'hidden') {
        markAway();
        return;
      }

      if (!wasAwayRef.current) return;

      wasAwayRef.current = false;
      loadRooms();
    };

    window.addEventListener('blur', markAway);
    window.addEventListener('focus', handleReturn);
    document.addEventListener('visibilitychange', handleReturn);

    return () => {
      cancelled = true;
      window.removeEventListener('blur', markAway);
      window.removeEventListener('focus', handleReturn);
      document.removeEventListener('visibilitychange', handleReturn);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [building?.id, requestRooms]);

  // Re-resolves every room's displayed `name` for the CURRENT `lang`
  // whenever the user switches language — purely an in-memory
  // recomputation over the already-fetched `rooms`/`names` data, never a
  // new API request, MongoDB write, or AI re-analysis (Section 9: the
  // selected language controls presentation only).
  const localizedRooms = useMemo(
    // resolveDestinationName rather than the shared getLocalizedText:
    // a room can have a real name_en while names.en is null, and the
    // shared helper's ['en','ar','he'] fallback answers an ENGLISH request
    // with the Arabic name in that case. See utils/destinationDisplayName.js.
    () => rooms.map((r) => ({ ...r, name: resolveDestinationName(r.names, lang, r.nameEn) })),
    [rooms, lang],
  );

  // The building's own name, re-resolved for the current language from
  // the translations already attached to the view model — same helper,
  // same fallback chain, and no refetch when the language changes.
  const buildingName = building
    ? getLocalizedText(building.names, lang, building.name || building.nameEn)
    : '';

  // Real secondary metadata only. A campus value that merely repeats the
  // building's own name is noise, so it is hidden — and nothing is
  // substituted in its place.
  const buildingMeta =
    building?.campus &&
    building.campus !== buildingName &&
    building.campus !== building.nameEn
      ? building.campus
      : '';

  // Floors that genuinely exist in the user's related map group, derived
  // from the destinations already loaded. Never a fixed list.
  const floorOptions = useMemo(
    () => resolveFloorOptions(localizedRooms, startContext),
    [localizedRooms, startContext],
  );

  const showFloorFilter = shouldShowFloorFilter(floorOptions);

  // A selection that no longer matches a real option (rooms reloaded,
  // different start) falls back to All instead of showing nothing.
  const activeFloorMapId = reconcileFloorSelection(floorMapId, floorOptions);

  // Search and the floor filter compose: the floor narrows the list, the
  // query narrows it again, and the count below reflects both.
  const filtered = useMemo(() => {
    const onFloor = filterRoomsByFloor(localizedRooms, activeFloorMapId);

    if (!query.trim()) return onFloor;

    // Multilingual search (Section 10): a destination must be findable by
    // any of its stored translations, not just the one currently on
    // screen — e.g. searching "شفاء" finds "Al Shifaa Pharmacy" even while
    // the UI language is English. Falls back to the plain nameEn/type/
    // description match for a legacy room with no `names` object at all.
    return onFloor.filter((r) =>
      matchesLocalizedSearch(r.names, r.nameEn, query) ||
      r.type.replace('_', ' ').toLowerCase().includes(query.toLowerCase()) ||
      (r.description && r.description.toLowerCase().includes(query.toLowerCase()))
    );
  }, [localizedRooms, activeFloorMapId, query]);

  const handleRoomClick = (room) => {
    // Unconnected destinations are disabled in the card itself — this is
    // a defensive second guard, never reachable via a real click. Uses
    // the backend's own live is_navigable verdict — never re-derived
    // here from routePointId/routePointConnected (that one-shot field is
    // always false on a plain GET, which was the root cause of every
    // destination staying permanently disabled regardless of real graph
    // state — see viewModels.js's roomToViewModel for the field mapping).
    if (!room.isNavigable) return;
    navigate(ROUTES.navigation, { state: { building, destination: room, lang } });
  };

  return (
    <div className="layout-wrapper">
      <div className="layout-shell s17-shell" dir={isRTL ? 'rtl' : 'ltr'}>

        {/* ── Gradient Header ── */}
        <div className="s17-header">
          <div className="s17-header-inner">

            {/* Back + language on one line, so the hero stays short */}
            <div className="s17-topbar">
              {/* Back goes to the location-code entry screen by its
                  CANONICAL ROUTE, not through history and not to the
                  building picker: the QR flow reaches this screen directly
                  from /start, so /start is where "back" genuinely leads.
                  Using the route rather than history.back() also means a
                  user who happened to arrive via the building list can
                  never be dropped back onto that intermediate step. */}
              <BackButton
                onClick={() => navigate(ROUTES.start)}
                label={t.back}
                isRTL={isRTL}
                spacing="compact"
              />

              <div className="s17-lang-pill" role="group" aria-label="Language selector">
                {LANGUAGES.map((l) => (
                  <button
                    key={l.code}
                    type="button"
                    className={`s17-lang-btn${lang === l.code ? ' active' : ''}`}
                    onClick={() => setLang(l.code)}
                    aria-pressed={lang === l.code}
                  >
                    {l.label}
                  </button>
                ))}
              </div>
            </div>

            {/* Branding */}
            <div className="s17-brand">
              <QuickRouteLogo size={24} />
              <span className="s17-wordmark">Quick<span>Route</span></span>
            </div>

            {/* Building identity — the resolved Building, named once. */}
            {building && (
              <div className="s17-identity">
                <span className="s17-identity-icon" aria-hidden="true">
                  <PinIcon size={20} />
                </span>
                <div className="s17-identity-text">
                  <h1 className="s17-identity-name">{buildingName}</h1>
                  {buildingMeta && (
                    <p className="s17-identity-meta">{buildingMeta}</p>
                  )}
                </div>
              </div>
            )}

            <p className="s17-subtitle">{t.subtitle}</p>

            {/* Real starting-location context — shown only when the
                backend actually resolved one (QR flow); never fabricated
                (Part 5). */}
            {(startLabel || startFloor != null) && (
              <div className="s17-status-row">
                {startLabel && (
                  <div className="s17-status-card">
                    <span className="s17-status-icon" aria-hidden="true">
                      <PinIcon size={16} />
                    </span>
                    <span className="s17-status-text">
                      <span className="s17-status-label">{t.startingFrom}</span>
                      <strong className="s17-status-value">{startLabel}</strong>
                    </span>
                  </div>
                )}
                {startFloor != null && (
                  <div className="s17-status-card">
                    <span className="s17-status-icon" aria-hidden="true">
                      <FloorIcon size={16} />
                    </span>
                    <span className="s17-status-text">
                      <span className="s17-status-label">{t.currentFloor}</span>
                      <strong className="s17-status-value">
                        {formatFloorDisplay(startFloor, null)}
                      </strong>
                    </span>
                  </div>
                )}
              </div>
            )}

          </div>
        </div>

        {/* ── Search bar — ONE surface, no outer container ── */}
        <div className="s17-searchbar">
          <HospSearchBar
            value={query}
            onChange={setQuery}
            placeholder={t.search}
            isRTL={isRTL}
          />
        </div>

        {/* ── Scrollable room list ── */}
        <div className="s17-content">

          {loading ? (
            <div className="s17-skeleton-list">
              {[0, 1, 2, 3].map((i) => (
                <div key={i} className="s17-skeleton-card" />
              ))}
            </div>
          ) : error ? (
            <div className="s17-empty"><p>{error}</p></div>
          ) : rooms.length === 0 ? (
            <div className="s17-empty"><p>{t.noData}</p></div>
          ) : (
            <>
              {/* Floor filter — one chip per REAL map that actually holds
                  a destination in the user's own map group. Hidden
                  entirely when there is nothing to choose between. */}
              {showFloorFilter && (
                <div
                  className="s17-floors"
                  role="group"
                  aria-label={t.floorFilter}
                >
                  <button
                    type="button"
                    className={`s17-floor-chip${!activeFloorMapId ? ' active' : ''}`}
                    onClick={() => setFloorMapId(ALL_FLOORS)}
                    aria-pressed={!activeFloorMapId}
                  >
                    {t.allFloors}
                  </button>

                  {floorOptions.map((option) => (
                    <button
                      key={option.mapId}
                      type="button"
                      className={
                        `s17-floor-chip${activeFloorMapId === option.mapId ? ' active' : ''}`
                        + `${option.isCurrent ? ' is-current' : ''}`
                      }
                      onClick={() => setFloorMapId(option.mapId)}
                      aria-pressed={activeFloorMapId === option.mapId}
                      title={option.isCurrent ? t.current : undefined}
                    >
                      {option.label}
                    </button>
                  ))}
                </div>
              )}

              <div className="s17-section-row">
                <span className="s17-section-label">{t.section}</span>
                <span className="s17-section-count">{t.count(filtered.length)}</span>
              </div>

              {filtered.length === 0 ? (
                <div className="s17-empty">
                  <svg width="44" height="44" viewBox="0 0 24 24" fill="none" opacity="0.30">
                    <circle cx="11" cy="11" r="8" stroke="#8aaacb" strokeWidth="1.5"/>
                    <path d="M21 21l-4.35-4.35" stroke="#8aaacb" strokeWidth="1.5" strokeLinecap="round"/>
                  </svg>
                  <p>{t.noResults}</p>
                </div>
              ) : (
                <div className="s17-list">
                  {filtered.map((room) => (
                    <DestinationCard
                      key={room.id}
                      variant="room"
                      data={room}
                      onClick={() => handleRoomClick(room)}
                      // Enabled only when the backend explicitly says so —
                      // never inferred/assumed on the frontend. A brand
                      // new destination with no graph edge yet correctly
                      // stays disabled (isNavigable defaults to false
                      // whenever the backend field is missing/falsy).
                      disabled={!room.isNavigable}
                      disabledLabel={t.notConnected}
                    />
                  ))}
                </div>
              )}
            </>
          )}

        </div>


      </div>
    </div>
  );
};

export default DestinationSelectionScreen;
