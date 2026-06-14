import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import QuickRouteLogo from '../components/QuickRouteLogo';
import { useLang } from '../context/LangContext';
import '../styles/BarcodeEntryScreen.css';

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
  },
  ar: {
    welcome:    'أهلاً وسهلاً',
    subtitle:   'أدخل رقم الباركود للبدء',
    placeholder:'رقم الباركود...',
    go:         'ابدأ',
    or:         'أو',
    login:      'تسجيل الدخول',
    signup:     'إنشاء حساب',
  },
  he: {
    welcome:    'ברוכים הבאים',
    subtitle:   'הזן מספר ברקוד כדי להתחיל',
    placeholder:'מספר ברקוד...',
    go:         'התחל',
    or:         'או',
    login:      'התחברות',
    signup:     'הרשמה',
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
  const [barcode, setBarcode] = useState('');

  const isRTL = lang === 'ar' || lang === 'he';
  const t     = UI[lang];

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
              onChange={(e) => setBarcode(e.target.value)}
              dir={isRTL ? 'rtl' : 'ltr'}
              aria-label="Barcode number"
            />
          </div>

          <button className="s01-go-btn" aria-label={t.go} onClick={() => navigate('/screen/16')}>
            {isRTL ? <ArrowLeftIcon /> : null}
            <span>{t.go}</span>
            {isRTL ? null : <ArrowRightIcon />}
          </button>
        </div>

        {/* ── Auth ── */}
        <div className="s01-auth">
          <div className="s01-auth-divider">
            <span />
            <p>{t.or}</p>
            <span />
          </div>
          <div className="s01-auth-row">
            <button className="s01-auth-btn s01-login-btn" onClick={() => navigate('/screen/02')}>{t.login}</button>
            <button className="s01-auth-btn s01-signup-btn" onClick={() => navigate('/screen/03')}>{t.signup}</button>
          </div>
        </div>

      </div>
    </div>
  );
};

export default BarcodeEntryScreen;
