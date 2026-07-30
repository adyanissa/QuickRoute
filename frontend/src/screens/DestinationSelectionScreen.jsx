import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import HospSearchBar from '../components/HospSearchBar';
import DestinationCard from '../components/DestinationCard';
import BackButton from '../components/BackButton';
import { useLang } from '../context/LangContext';
import { getRooms } from '../api/roomsApi';
import { roomToViewModel } from '../utils/viewModels';
import { getLocalizedText, matchesLocalizedSearch } from '../utils/localization';
import { formatFloor } from '../components/DestinationCard';
import '../styles/DestinationSelectionScreen.css';

// Same key BarcodeEntryScreen writes to after a location code resolves —
// read here (as a fallback to route state) so a starting-location label
// still shows up if this screen is reached without the QR flow's own
// navigation state (e.g. a refresh).
const START_LOCATION_KEY = 'quickroute_start_location';

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
  },
};

// ── Screen ────────────────────────────────────────────────────────────────────
const DestinationSelectionScreen = () => {
  const { lang }              = useLang();
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
  const startLabel = location.state?.startLabel
    ?? (persistedStart?.buildingId === building?.id ? persistedStart?.label : null)
    ?? null;
  const startFloor = location.state?.startFloor
    ?? (persistedStart?.buildingId === building?.id ? persistedStart?.floor : null)
    ?? null;

  const [rooms, setRooms]     = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError]     = useState('');

  useEffect(() => {
    let cancelled = false;

    const loadRooms = async () => {
      if (!building?.id) {
        setRooms([]);
        setLoading(false);
        return;
      }

      setLoading(true);
      setError('');

      try {
        const data = await getRooms({ building_id: building.id });

        if (!cancelled) {
          // Never display an inactive destination — Part 3 rule 4.
          const viewModels = (Array.isArray(data) ? data : [])
            .map(roomToViewModel)
            .filter((r) => r.isActive !== false);
          setRooms(viewModels);
        }
      } catch (err) {
        console.error('Failed to load rooms:', err);

        if (!cancelled) {
          setRooms([]);
          setError(t.loadError);
        }
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
    const handleFocusOrVisible = () => {
      if (document.visibilityState === 'hidden') return;
      loadRooms();
    };
    window.addEventListener('focus', handleFocusOrVisible);
    document.addEventListener('visibilitychange', handleFocusOrVisible);

    return () => {
      cancelled = true;
      window.removeEventListener('focus', handleFocusOrVisible);
      document.removeEventListener('visibilitychange', handleFocusOrVisible);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [building?.id]);

  // Re-resolves every room's displayed `name` for the CURRENT `lang`
  // whenever the user switches language — purely an in-memory
  // recomputation over the already-fetched `rooms`/`names` data, never a
  // new API request, MongoDB write, or AI re-analysis (Section 9: the
  // selected language controls presentation only).
  const localizedRooms = useMemo(
    () => rooms.map((r) => ({ ...r, name: getLocalizedText(r.names, lang, r.nameEn) })),
    [rooms, lang],
  );

  // Multilingual search (Section 10): a destination must be findable by
  // any of its stored translations, not just the one currently on
  // screen — e.g. searching "شفاء" finds "Al Shifaa Pharmacy" even while
  // the UI language is English. Falls back to the plain nameEn/type/
  // description match for a legacy room with no `names` object at all.
  const filtered = query.trim()
    ? localizedRooms.filter((r) =>
        matchesLocalizedSearch(r.names, r.nameEn, query) ||
        r.type.replace('_', ' ').toLowerCase().includes(query.toLowerCase()) ||
        (r.description && r.description.toLowerCase().includes(query.toLowerCase()))
      )
    : localizedRooms;

  const handleRoomClick = (room) => {
    // Unconnected destinations are disabled in the card itself — this is
    // a defensive second guard, never reachable via a real click. Uses
    // the backend's own live is_navigable verdict — never re-derived
    // here from routePointId/routePointConnected (that one-shot field is
    // always false on a plain GET, which was the root cause of every
    // destination staying permanently disabled regardless of real graph
    // state — see viewModels.js's roomToViewModel for the field mapping).
    if (!room.isNavigable) return;
    navigate('/map', { state: { building, destination: room, lang } });
  };

  return (
    <div className="layout-wrapper">
      <div className="layout-shell s17-shell" dir={isRTL ? 'rtl' : 'ltr'}>

        {/* ── Gradient Header ── */}
        <div className="s17-header">

          <BackButton
            onClick={() => navigate('/screen/16')}
            label={t.back}
            isRTL={isRTL}
          />

          {/* Building card row */}
          {building && (
            <div className="s17-building-row">
              <div className="s17-building-icon" style={{ background: building.iconBg }}>
                <span className="s17-building-tag" style={{ color: building.iconColor }}>
                  {building.tag}
                </span>
              </div>
              <div className="s17-building-text">
                <h1 className="s17-building-name">{building.name}</h1>
                <p className="s17-building-en">{building.nameEn}</p>
              </div>
            </div>
          )}

          <p className="s17-subtitle">{t.subtitle}</p>

          {/* Real starting-location context — shown only when the
              backend actually resolved one (QR flow); never fabricated
              (Part 5). */}
          {(startLabel || startFloor != null) && (
            <div className="s17-start-row">
              {startLabel && (
                <span className="s17-start-chip">{t.startingFrom}: {startLabel}</span>
              )}
              {startFloor != null && (
                <span className="s17-start-chip">{t.currentFloor}: {formatFloor(startFloor)}</span>
              )}
            </div>
          )}

        </div>

        {/* ── Floating search bar ── */}
        <div className="s17-search-wrap">
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
