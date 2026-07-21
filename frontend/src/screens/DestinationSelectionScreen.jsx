import { useEffect, useState } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import HospSearchBar from '../components/HospSearchBar';
import DestinationCard from '../components/DestinationCard';
import BackButton from '../components/BackButton';
import { useLang } from '../context/LangContext';
import { getRooms } from '../api/roomsApi';
import { roomToViewModel } from '../utils/viewModels';
import '../styles/DestinationSelectionScreen.css';

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
    goBtn:      'Go',
    floor:      'Floor',
    selected:   'Selected destination',
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
    goBtn:      'اذهب',
    floor:      'طابق',
    selected:   'الوجهة المختارة',
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
    goBtn:      'המשך',
    floor:      'קומה',
    selected:   'יעד נבחר',
  },
};

// ── Screen ────────────────────────────────────────────────────────────────────
const DestinationSelectionScreen = () => {
  const { lang }              = useLang();
  const navigate              = useNavigate();
  const location              = useLocation();
  const [query, setQuery] = useState('');

  const isRTL  = lang === 'ar' || lang === 'he';
  const t      = UI[lang];

  const building = location.state?.building ?? null;

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
          setRooms((Array.isArray(data) ? data : []).map(roomToViewModel));
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

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [building?.id]);

  const filtered = query.trim()
    ? rooms.filter((r) =>
        r.name.toLowerCase().includes(query.toLowerCase()) ||
        r.type.replace('_', ' ').toLowerCase().includes(query.toLowerCase()) ||
        (r.description && r.description.toLowerCase().includes(query.toLowerCase()))
      )
    : rooms;

  const handleRoomClick = (room) => {
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
            <div className="s17-empty"><p>{t.loading}</p></div>
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
