import { useNavigate } from 'react-router-dom';
import QuickRouteLogo from '../components/QuickRouteLogo';
import { useLang } from '../context/LangContext';
import { ROUTES } from '../config/routes';
import '../styles/WelcomeScreen.css';

const LANGUAGES = [
  { code: 'ar', label: 'عربي' },
  { code: 'he', label: 'עברית' },
  { code: 'en', label: 'EN' },
];

const UI = {
  en: { welcome: 'Welcome', go: 'Go →' },
  ar: { welcome: 'أهلاً وسهلاً', go: '← ابدأ' },
  he: { welcome: 'ברוכים הבאים', go: '← התחל' },
};

const WelcomeScreen = () => {
  const { lang, setLang } = useLang();
  const navigate           = useNavigate();
  const isRTL              = lang === 'ar' || lang === 'he';
  const t                  = UI[lang];

  return (
    <div className="layout-wrapper">
      <div className="layout-shell s15-shell" dir={isRTL ? 'rtl' : 'ltr'}>

        {/* ── Language selector ── */}
        <div className="s15-lang-bar">
          <div className="s15-lang-pill" role="group" aria-label="Language selector">
            {LANGUAGES.map((l) => (
              <button
                key={l.code}
                className={`s15-lang-btn${lang === l.code ? ' active' : ''}`}
                onClick={() => setLang(l.code)}
                aria-pressed={lang === l.code}
              >
                {l.label}
              </button>
            ))}
          </div>
        </div>

        {/* ── Branding ── */}
        <div className="s15-brand">
          <div className="s15-logo-card">
            <QuickRouteLogo size={52} />
          </div>
          <div className="s15-wordmark">
            Quick<span>Route</span>
          </div>
        </div>

        {/* ── Welcome heading ── */}
        <div className="s15-welcome">
          <h1 className="s15-title">{t.welcome}</h1>
        </div>


        {/* ── Spacer ── */}
        <div className="s15-spacer" />

        {/* ── Go button ── */}
        <div className="s15-footer">
          <button className="s15-go-btn" onClick={() => navigate(ROUTES.buildings)}>
            {t.go}
          </button>
        </div>

      </div>
    </div>
  );
};

export default WelcomeScreen;
