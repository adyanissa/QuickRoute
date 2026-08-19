import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import QuickRouteLogo from '../components/QuickRouteLogo';
import HospSearchBar from '../components/HospSearchBar';
import DestinationCard from '../components/DestinationCard';
import BackButton from '../components/BackButton';
import { useLang } from '../context/LangContext';
import { getBuildings } from '../api/buildingsApi';
import { buildingToViewModel } from '../utils/viewModels';
import { getLocalizedText, matchesLocalizedSearch } from '../utils/localization';
import { ROUTES } from '../config/routes';
import '../styles/BuildingSelectionScreen.css';

// ── Translations ──────────────────────────────────────────────────────────────
// QuickRoute UX Final Cleanup, Part 4: no hardcoded fake facility name
// badge, no "BUILDINGS" technical section heading — a friendly hero
// heading and an honest empty state instead.
const UI = {
  en: {
    title:      'Where would you\nlike to go?',
    subtitle:   'Choose a location to view its available destinations.',
    search:     'Search available locations...',
    noResults:  'No locations match your search',
    noDataTitle:'No locations are available yet',
    noDataDesc: 'Ask an administrator to configure a building and its destinations.',
    loading:    'Loading locations...',
    loadError:  'Failed to load locations',
    back:       'Back',
    wordmark:   ['Quick', 'Route'],
  },
  ar: {
    title:      'إلى أين تريد\nالذهاب؟',
    subtitle:   'اختر موقعًا لعرض وجهاته المتاحة.',
    search:     'ابحث عن المواقع المتاحة...',
    noResults:  'لا توجد مواقع مطابقة لبحثك',
    noDataTitle:'لا توجد مواقع متاحة بعد',
    noDataDesc: 'يرجى مطالبة المشرف بإعداد مبنى ووجهاته.',
    loading:    'جاري تحميل المواقع...',
    loadError:  'فشل تحميل المواقع',
    back:       'رجوع',
    wordmark:   ['Quick', 'Route'],
  },
  he: {
    title:      'לאן תרצה\nלהגיע?',
    subtitle:   'בחר מיקום כדי לראות את היעדים הזמינים בו.',
    search:     'חיפוש מיקומים זמינים...',
    noResults:  'לא נמצאו מיקומים התואמים לחיפוש',
    noDataTitle:'עדיין אין מיקומים זמינים',
    noDataDesc: 'יש לבקש ממנהל המערכת להגדיר בניין ויעדים.',
    loading:    'טוען מיקומים...',
    loadError:  'טעינת המיקומים נכשלה',
    back:       'חזרה',
    wordmark:   ['Quick', 'Route'],
  },
};

const LANGUAGES = [
  { code: 'ar', label: 'عربي' },
  { code: 'he', label: 'עברית' },
  { code: 'en', label: 'EN' },
];

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
          // GET /api/buildings returns every building regardless of
          // status — never show an inactive one to a normal user
          // (Part 3 rule 4's spirit, applied to buildings too).
          const viewModels = (Array.isArray(data) ? data : [])
            .map(buildingToViewModel)
            .filter((b) => b.isActive !== false);
          setBuildings(viewModels);
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

  // Re-resolves every building's displayed `name` for the CURRENT `lang`
  // whenever the user switches language — a pure in-memory recomputation
  // over the already-fetched `buildings`/`names` data, never a new API
  // request (Section 9). Buildings have no admin-approved multilingual
  // `names` source today, so this is currently a no-op vs. the fetch-time
  // 'en' default, but keeps this screen forward-compatible and consistent
  // with DestinationSelectionScreen.jsx.
  const localizedBuildings = useMemo(
    () => buildings.map((b) => ({ ...b, name: getLocalizedText(b.names, lang, b.nameEn) })),
    [buildings, lang],
  );

  const filtered = query.trim()
    ? localizedBuildings.filter((b) =>
        matchesLocalizedSearch(b.names, b.nameEn, query) ||
        b.tag.toLowerCase().includes(query.toLowerCase()) ||
        (b.campus && b.campus.toLowerCase().includes(query.toLowerCase()))
      )
    : localizedBuildings;

  const handleSelect = (building) => {
    navigate(ROUTES.destinations, { state: { building } });
  };

  return (
    <div className="layout-wrapper">
      <div className="layout-shell s16-shell" dir={isRTL ? 'rtl' : 'ltr'}>

        {/* ── Gradient Header ── */}
        <div className="s16-header">

          <BackButton
            onClick={() => navigate(ROUTES.start)}
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

          {/* Hero heading — Part 4.B: friendly, no facility badge */}
          <h1 className="s16-title">
            {t.title.split('\n').map((line, i) => (
              <span key={i}>{line}{i === 0 && <br />}</span>
            ))}
          </h1>
          <p className="s16-hero-subtitle">{t.subtitle}</p>

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

        {/* ── Scrollable locations grid — no "BUILDINGS" heading (Part 4) ── */}
        <div className="s16-content">

          {loading ? (
            <div className="s16-skeleton-list">
              {[0, 1, 2, 3].map((i) => (
                <div key={i} className="s16-skeleton-card" />
              ))}
            </div>
          ) : error ? (
            <div className="s16-empty">
              <p className="s16-empty-title">{error}</p>
            </div>
          ) : buildings.length === 0 ? (
            <div className="s16-empty">
              <svg width="46" height="46" viewBox="0 0 24 24" fill="none" opacity="0.30">
                <path d="M12 2a7 7 0 0 1 7 7c0 5.25-7 13-7 13S5 14.25 5 9a7 7 0 0 1 7-7z"
                  stroke="#8aaacb" strokeWidth="1.5"/>
                <circle cx="12" cy="9" r="2.6" stroke="#8aaacb" strokeWidth="1.5"/>
              </svg>
              <p className="s16-empty-title">{t.noDataTitle}</p>
              <p className="s16-empty-desc">{t.noDataDesc}</p>
            </div>
          ) : filtered.length === 0 ? (
            <div className="s16-empty">
              <svg width="46" height="46" viewBox="0 0 24 24" fill="none" opacity="0.30">
                <circle cx="11" cy="11" r="8" stroke="#8aaacb" strokeWidth="1.5"/>
                <path d="M21 21l-4.35-4.35" stroke="#8aaacb" strokeWidth="1.5" strokeLinecap="round"/>
              </svg>
              <p className="s16-empty-title">{t.noResults}</p>
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
