import { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import QuickRouteLogo from '../components/QuickRouteLogo';
import { useLang } from '../context/LangContext';
import { resolveLocationCode } from '../api/locationCodesApi';
import { getBuildingById } from '../api/buildingsApi';
import { buildingToViewModel } from '../utils/viewModels';
import { LOCATION_CODE_QUERY_PARAM } from '../config/publicUrl';
import { ROUTES } from '../config/routes';
import '../styles/BarcodeEntryScreen.css';

// Where the resolved starting location (from a scanned/typed code) is kept
// so IndoorNavigationScreen can pick it up later instead of always
// defaulting to the map's first entrance point.
const START_LOCATION_KEY = 'quickroute_start_location';

const LANGUAGES = [
  { code: 'ar', label: 'عربي' },
  { code: 'he', label: 'עברית' },
  { code: 'en', label: 'EN' },
];

const UI = {
  en: {
    welcome:    'Welcome',
    subtitle:   'Enter a barcode number to get started',
    placeholder:'Barcode number...',
    go:         'Go',
    or:         'OR',
    login:      'Login',
    signup:     'Sign Up',
    checking:   'Checking code...',
    required:   'Please enter a barcode number',
    invalid:    'Invalid or inactive barcode. Please try again.',
    noBuilding: 'This location code is not linked to a valid building.',
  },
  ar: {
    welcome:    'أهلاً وسهلاً',
    subtitle:   'أدخل رقم الباركود للبدء',
    placeholder:'رقم الباركود...',
    go:         'ابدأ',
    or:         'أو',
    login:      'تسجيل الدخول',
    signup:     'إنشاء حساب',
    checking:   'جاري التحقق من الرمز...',
    required:   'الرجاء إدخال رقم الباركود',
    invalid:    'رمز الباركود غير صحيح أو غير مفعّل. حاول مرة أخرى.',
    noBuilding: 'رمز الموقع هذا غير مرتبط بمبنى صالح.',
  },
  he: {
    welcome:    'ברוכים הבאים',
    subtitle:   'הזן מספר ברקוד כדי להתחיל',
    placeholder:'מספר ברקוד...',
    go:         'התחל',
    or:         'או',
    login:      'התחברות',
    signup:     'הרשמה',
    checking:   'בודק קוד...',
    required:   'יש להזין מספר ברקוד',
    invalid:    'ברקוד לא תקין או לא פעיל. נסה שוב.',
    noBuilding: 'קוד המיקום הזה אינו מקושר לבניין תקף.',
  },
};

const BarcodeIcon = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
    <rect x="1"  y="4" width="2.5" height="16" rx="0.6" fill="currentColor" />
    <rect x="5"  y="4" width="1.2" height="16" rx="0.4" fill="currentColor" opacity="0.7" />
    <rect x="7.5"y="4" width="2"   height="16" rx="0.5" fill="currentColor" />
    <rect x="11" y="4" width="1.2" height="16" rx="0.4" fill="currentColor" opacity="0.7" />
    <rect x="13.5"y="4"width="2"   height="16" rx="0.5" fill="currentColor" />
    <rect x="17" y="4" width="1.2" height="16" rx="0.4" fill="currentColor" opacity="0.7" />
    <rect x="19.5"y="4"width="2"   height="16" rx="0.6" fill="currentColor" />
  </svg>
);

const ArrowRightIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true">
    <path
      d="M5 12h14M13 6l6 6-6 6"
      stroke="currentColor"
      strokeWidth="2.2"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);

const ArrowLeftIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true">
    <path
      d="M19 12H5M11 18l-6-6 6-6"
      stroke="currentColor"
      strokeWidth="2.2"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);

const BarcodeEntryScreen = () => {
  const { lang, setLang } = useLang();
  const navigate           = useNavigate();
  const [searchParams] = useSearchParams();

  // A scanned QuickRoute QR arrives as {PUBLIC_FRONTEND_URL}/?locationCode=CODE
  // and is forwarded here by App.jsx's root redirect. It is read as a plain
  // parameter — there is no separate scan route and no second resolution
  // path; it feeds the identical function manual entry uses.
  const urlCode = (searchParams.get(LOCATION_CODE_QUERY_PARAM) ?? '').trim();

  // Prefilled from the URL on the very first render (not written from an
  // effect), so the field shows the scanned code while it is resolving and
  // still holds it if resolution fails and the user wants to retry.
  const [barcode, setBarcode] = useState(urlCode);
  const [isResolving, setIsResolving] = useState(false);
  const [error, setError] = useState('');

  const isRTL = lang === 'ar' || lang === 'he';
  const t     = UI[lang];

  /**
   * The ONE place a LocationCode is turned into a journey.
   *
   * Both entry paths call this and nothing else:
   *   A. manual typing  -> handleGo() below
   *   B. ?locationCode= -> the mount effect below
   *
   * so a scanned code and a typed code cannot diverge — same resolve call,
   * same validation, same error states, same persisted record, same
   * navigation target.
   *
   * What it establishes is the user's START position: the resolved
   * RoutePoint is written to quickroute_start_location and nothing else.
   * The DESTINATION is still chosen by the user afterwards on the
   * Destination Selection screen, exactly as before — a scanned room never
   * becomes the destination.
   */
  const resolveAndContinue = useCallback(async (rawCode) => {
    const code = (rawCode ?? '').trim();

    if (!code) {
      setError(t.required);
      return;
    }

    setError('');
    setIsResolving(true);

    try {
      // Resolve the code to an exact start RoutePoint. The resolve endpoint
      // itself re-validates that the point/map still exist and that the
      // code is active, so a successful response is safe to trust.
      const resolved = await resolveLocationCode(code);

      // A Location Code with no building relationship is a distinct,
      // honest error state — never silently fall back to a
      // frontend-guessed building (QuickRoute UX Final Cleanup, Part 3
      // rule 7).
      if (!resolved?.building_id) {
        setError(t.noBuilding);
        return;
      }

      const buildingRaw = await getBuildingById(resolved.building_id);
      const building = buildingToViewModel(buildingRaw);

      // Persist the full resolved starting location — including the
      // map group, floor and human-readable label the backend already
      // resolves fresh on every call — so IndoorNavigationScreen and the
      // Destination Selection header can show real "starting location"
      // and "current floor" values instead of always defaulting to a
      // generic entrance point (Part 3 / Part 2.B).
      localStorage.setItem(
        START_LOCATION_KEY,
        JSON.stringify({
          routePointId: resolved.route_point_id,
          mapId: resolved.map_id,
          mapGroupId: resolved.map_group_id ?? null,
          floor: resolved.floor ?? null,
          buildingId: resolved.building_id,
          code: resolved.code,
          label: resolved.label ?? null,
        }),
      );

      navigate(ROUTES.destinations, {
        state: {
          building,
          startLabel: resolved.label ?? null,
          startFloor: resolved.floor ?? null,
        },
      });
    } catch (err) {
      console.error('Failed to resolve location code:', err);
      // An unknown, inactive or malformed code from a URL lands on exactly
      // the same safe invalid-code message a mistyped code has always
      // produced — never a crash, a blank screen or a guessed building.
      setError(t.invalid);
    } finally {
      setIsResolving(false);
    }
  }, [navigate, t]);

  const handleGo = () => resolveAndContinue(barcode);

  // Auto-resolve a code that arrived in the URL.
  //
  // The ref guard is keyed by the code itself, so React 19 development
  // StrictMode — which mounts, unmounts and re-mounts every component,
  // running effects twice — cannot resolve or navigate twice. Refs survive
  // that double invocation; a boolean local would not.
  //
  // The call is deferred by a microtask so this effect writes no state
  // synchronously (react-hooks/set-state-in-effect).
  const autoResolvedCodeRef = useRef(null);

  useEffect(() => {
    if (!urlCode) return;
    if (autoResolvedCodeRef.current === urlCode) return;

    autoResolvedCodeRef.current = urlCode;

    Promise.resolve().then(() => {
      resolveAndContinue(urlCode);
    });
  }, [urlCode, resolveAndContinue]);

  return (
    <div className="layout-wrapper">
      <div className="layout-shell s01-shell" dir={isRTL ? 'rtl' : 'ltr'}>

        {/* ── Language selector ── */}
        <div className="s01-lang-bar">
          <div className="s01-lang-pill" role="group" aria-label="Language selector">
            {LANGUAGES.map((l) => (
              <button
                key={l.code}
                className={`s01-lang-btn${lang === l.code ? ' active' : ''}`}
                onClick={() => setLang(l.code)}
                aria-pressed={lang === l.code}
              >
                {l.label}
              </button>
            ))}
          </div>
        </div>

        {/* ── Branding ── */}
        <div className="s01-brand">
          <div className="s01-logo-card">
            <QuickRouteLogo size={52} />
          </div>
          <div className="s01-wordmark">
            Quick<span>Route</span>
          </div>
        </div>

        {/* ── Welcome heading ── */}
        <div className="s01-welcome">
          <h1 className="s01-title">{t.welcome}</h1>
          <p className="s01-subtitle">{t.subtitle}</p>
        </div>

        {/* ── Input + Go ── */}
        <div className="s01-form">
          <div className="s01-input-wrap">
            <span className={`s01-input-icon ${isRTL ? 's01-icon-rtl' : ''}`}>
              <BarcodeIcon />
            </span>
            <input
              className={`s01-input ${isRTL ? 's01-input-rtl' : ''}`}
              type="text"
              inputMode="numeric"
              placeholder={t.placeholder}
              value={barcode}
              onChange={(e) => { setBarcode(e.target.value); if (error) setError(''); }}
              onKeyDown={(e) => { if (e.key === 'Enter' && !isResolving) handleGo(); }}
              dir={isRTL ? 'rtl' : 'ltr'}
              aria-label="Barcode number"
              disabled={isResolving}
            />
          </div>

          <button
            className="s01-go-btn"
            aria-label={t.go}
            onClick={handleGo}
            disabled={isResolving}
          >
            {isRTL ? <ArrowLeftIcon /> : null}
            <span>{isResolving ? t.checking : t.go}</span>
            {isRTL ? null : <ArrowRightIcon />}
          </button>

          {error && <p className="s01-barcode-error">{error}</p>}
        </div>

        {/* ── Auth ── */}
        <div className="s01-auth">
          <div className="s01-auth-divider">
            <span />
            <p>{t.or}</p>
            <span />
          </div>
          <div className="s01-auth-row">
            <button className="s01-auth-btn s01-login-btn" onClick={() => navigate(ROUTES.login)}>{t.login}</button>
            <button className="s01-auth-btn s01-signup-btn" onClick={() => navigate(ROUTES.signup)}>{t.signup}</button>
          </div>
        </div>

      </div>
    </div>
  );
};

export default BarcodeEntryScreen;
