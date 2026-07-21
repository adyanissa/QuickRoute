import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import QuickRouteLogo from '../components/QuickRouteLogo';
import HospSearchBar from '../components/HospSearchBar';
import DestinationCard from '../components/DestinationCard';
import BackButton from '../components/BackButton';
import { useLang } from '../context/LangContext';
import { getBuildings } from '../api/buildingsApi';
import { buildingToViewModel } from '../utils/viewModels';
import '../styles/BuildingSelectionScreen.css';

// ── Translations ──────────────────────────────────────────────────────────────
const UI = {
  en: {
    title:     'Where do you\nwant to go?',
    location:  'Rabin Medical Center',
    search:    'Search buildings...',
    section:   'Buildings',
    count:     (n) => `${n} location${n !== 1 ? 's' : ''}`,
    noResults: 'No buildings found',
    noData:    'No buildings found',
    loading:   'Loading buildings...',
    loadError: 'Failed to load buildings',
    wordmark:  ['Quick', 'Route'],
    back:      'Back',
  },
  ar: {
    title:     'أين تريد\nالذهاب؟',
    location:  'مركز رابين الطبي',
    search:    'ابحث عن المبنى...',
    section:   'المباني',
    count:     (n) => `${n} موقع`,
    noResults: 'لا توجد نتائج',
    noData:    'لا توجد مبانٍ',
    loading:   'جاري تحميل المباني...',
    loadError: 'فشل تحميل المباني',
    wordmark:  ['Quick', 'Route'],
    back:      'رجوع',
  },
  he: {
    title:     'לאן אתה\nרוצה להגיע?',
    location:  'מרכז רבין הרפואי',
    search:    'חיפוש מבנים...',
    section:   'מבנים',
    count:     (n) => `${n} מיקום`,
    noResults: 'לא נמצאו מבנים',
    noData:    'לא נמצאו מבנים',
    loading:   'טוען מבנים...',
    loadError: 'טעינת המבנים נכשלה',
    wordmark:  ['Quick', 'Route'],
    back:      'חזרה',
  },
};

const LANGUAGES = [
  { code: 'ar', label: 'عربي' },
  { code: 'he', label: 'עברית' },
  { code: 'en', label: 'EN' },
];

// ── Icons ─────────────────────────────────────────────────────────────────────
const PinIcon = () => (
  <svg width="11" height="11" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
    <path d="M12 2a7 7 0 0 1 7 7c0 5.25-7 13-7 13S5 14.25 5 9a7 7 0 0 1 7-7z" opacity="0.9"/>
    <circle cx="12" cy="9" r="2.8" fill="white"/>
  </svg>
);

// ── Screen ────────────────────────────────────────────────────────────────────
const BuildingSelectionScreen = () => {
  const { lang, setLang } = useLang();
  const navigate          = useNavigate();
  const [query, setQuery] = useState('');

  const [buildings, setBuildings] = useState([]);
  const [loading, setLoading]     = useState(true);
  const [error, setError]         = useState('');

  const isRTL = lang === 'ar' || lang === 'he';
  const t     = UI[lang];

  useEffect(() => {
    let cancelled = false;

    const loadBuildings = async () => {
      setLoading(true);
      setError('');

      try {
        const data = await getBuildings();

        if (!cancelled) {
          setBuildings((Array.isArray(data) ? data : []).map(buildingToViewModel));
        }
      } catch (err) {
        console.error('Failed to load buildings:', err);

        if (!cancelled) {
          setBuildings([]);
          setError(t.loadError);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    loadBuildings();

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const filtered = query.trim()
    ? buildings.filter((b) =>
        b.name.toLowerCase().includes(query.toLowerCase()) ||
        b.nameEn.toLowerCase().includes(query.toLowerCase()) ||
        b.tag.toLowerCase().includes(query.toLowerCase())
      )
    : buildings;

  const handleSelect = (building) => {
    navigate('/screen/17', { state: { building } });
  };

  return (
    <div className="layout-wrapper">
      <div className="layout-shell s16-shell" dir={isRTL ? 'rtl' : 'ltr'}>

        {/* ── Gradient Header ── */}
        <div className="s16-header">

          <BackButton
            onClick={() => navigate('/screen/01')}
            label={t.back}
            isRTL={isRTL}
          />

          {/* Top row: logo + language switcher */}
          <div className="s16-topbar">
            <div className="s16-logo-row">
              <div className="s16-logo-card">
                <QuickRouteLogo size={26} />
              </div>
              <span className="s16-wordmark">
                {t.wordmark[0]}<span>{t.wordmark[1]}</span>
              </span>
            </div>

            {/* Language switcher pill */}
            <div className="s16-lang-pill" role="group" aria-label="Language selector">
              {LANGUAGES.map((l) => (
                <button
                  key={l.code}
                  className={`s16-lang-btn${lang === l.code ? ' active' : ''}`}
                  onClick={() => setLang(l.code)}
                  aria-pressed={lang === l.code}
                >
                  {l.label}
                </button>
              ))}
            </div>
          </div>

          {/* Location badge */}
          <div className="s16-location-badge">
            <PinIcon />
            <span>{t.location}</span>
          </div>

          {/* Title */}
          <h1 className="s16-title">
            {t.title.split('\n').map((line, i) => (
              <span key={i}>{line}{i === 0 && <br />}</span>
            ))}
          </h1>

        </div>

        {/* ── Floating search bar ── */}
        <div className="s16-search-wrap">
          <HospSearchBar
            value={query}
            onChange={setQuery}
            placeholder={t.search}
            isRTL={isRTL}
          />
        </div>

        {/* ── Scrollable buildings list ── */}
        <div className="s16-content">

          <div className="s16-section-row">
            <span className="s16-section-label">{t.section}</span>
            <span className="s16-section-count">{t.count(filtered.length)}</span>
          </div>

          {loading ? (
            <div className="s16-empty">
              <p>{t.loading}</p>
            </div>
          ) : error ? (
            <div className="s16-empty">
              <p>{error}</p>
            </div>
          ) : buildings.length === 0 ? (
            <div className="s16-empty">
              <p>{t.noData}</p>
            </div>
          ) : filtered.length === 0 ? (
            <div className="s16-empty">
              <svg width="46" height="46" viewBox="0 0 24 24" fill="none" opacity="0.30">
                <circle cx="11" cy="11" r="8" stroke="#8aaacb" strokeWidth="1.5"/>
                <path d="M21 21l-4.35-4.35" stroke="#8aaacb" strokeWidth="1.5" strokeLinecap="round"/>
              </svg>
              <p>{t.noResults}</p>
            </div>
          ) : (
            <div className="s16-list">
              {filtered.map((building) => (
                <DestinationCard
                  key={building.id}
                  variant="building"
                  data={building}
                  onClick={() => handleSelect(building)}
                />
              ))}
            </div>
          )}

        </div>

      </div>
    </div>
  );
};

export default BuildingSelectionScreen;
