import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import QuickRouteLogo from '../components/QuickRouteLogo';
import { useLang } from '../context/LangContext';
import { validateInvitationCode } from '../api/invitationCodesApi';
import '../styles/RegisterVerificationScreen.css';

const UI = {
  en: {
    title: 'Sign Up',
    placeholder: 'Enter identification code',
    continue: 'Continue',
    back: 'Back',
    loading: 'Checking code...',
    required: 'Please enter the identification code',
    invalid: 'Invalid or used identification code',
  },
  ar: {
    title: 'إنشاء حساب',
    placeholder: 'أدخل رمز التعريف',
    continue: 'متابعة',
    back: 'رجوع',
    loading: 'جاري فحص الرمز...',
    required: 'أدخلي رمز التعريف',
    invalid: 'رمز التعريف غير صحيح أو مستخدم',
  },
  he: {
    title: 'הרשמה',
    placeholder: 'הזן קוד מזהה',
    continue: 'המשך',
    back: 'חזרה',
    loading: 'בודק קוד...',
    required: 'יש להזין קוד מזהה',
    invalid: 'קוד מזהה לא תקין או כבר בשימוש',
  },
};

const BarcodeIcon = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
    <rect x="1" y="4" width="2.5" height="16" rx="0.6" fill="currentColor" />
    <rect x="5" y="4" width="1.2" height="16" rx="0.4" fill="currentColor" opacity="0.7" />
    <rect x="7.5" y="4" width="2" height="16" rx="0.5" fill="currentColor" />
    <rect x="11" y="4" width="1.2" height="16" rx="0.4" fill="currentColor" opacity="0.7" />
    <rect x="13.5" y="4" width="2" height="16" rx="0.5" fill="currentColor" />
    <rect x="17" y="4" width="1.2" height="16" rx="0.4" fill="currentColor" opacity="0.7" />
    <rect x="19.5" y="4" width="2" height="16" rx="0.6" fill="currentColor" />
  </svg>
);

const ArrowRightIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true">
    <path d="M5 12h14M13 6l6 6-6 6" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

const ArrowLeftIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true">
    <path d="M19 12H5M11 18l-6-6 6-6" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

const BackArrowLTR = () => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" aria-hidden="true">
    <path d="M19 12H5M11 18l-6-6 6-6" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

const BackArrowRTL = () => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" aria-hidden="true">
    <path d="M5 12h14M13 6l6 6-6 6" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

const RegisterVerificationScreen = () => {
  const { lang } = useLang();
  const navigate = useNavigate();

  const [barcode, setBarcode] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const isRTL = lang === 'ar' || lang === 'he';
  const t = UI[lang];

  const handleContinue = async () => {
    setError('');

    const code = barcode.trim();

    if (!code) {
      setError(t.required);
      return;
    }

    try {
      setLoading(true);

      await validateInvitationCode(code);

      localStorage.setItem('quickroute_invitation_code', code);

      navigate('/screen/04');
    } catch (err) {
      setError(err.message || t.invalid);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="layout-wrapper">
      <div className="layout-shell s03-shell" dir={isRTL ? 'rtl' : 'ltr'}>

        <div className={`s03-topbar${isRTL ? ' s03-topbar-rtl' : ''}`}>
          <button
            className={`s03-back-btn${isRTL ? ' s03-back-btn-rtl' : ''}`}
            onClick={() => navigate('/screen/01')}
            aria-label={t.back}
            type="button"
          >
            {isRTL ? <BackArrowRTL /> : <BackArrowLTR />}
            {t.back}
          </button>
        </div>

        <div className="s03-brand">
          <div className="s03-logo-card">
            <QuickRouteLogo size={46} />
          </div>
          <div className="s03-wordmark">
            Quick<span>Route</span>
          </div>
        </div>

        <div className="s03-heading">
          <h1 className="s03-title">{t.title}</h1>
        </div>

        <div className="s03-form">
          <div className="s03-input-wrap">
            <span className={`s03-input-icon${isRTL ? ' s03-input-icon-rtl' : ''}`}>
              <BarcodeIcon />
            </span>
            <input
              className={`s03-input${isRTL ? ' s03-input-rtl' : ''}`}
              type="text"
              placeholder={t.placeholder}
              value={barcode}
              onChange={(e) => setBarcode(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  handleContinue();
                }
              }}
              dir={isRTL ? 'rtl' : 'ltr'}
              aria-label="Identification code"
            />
          </div>

          {error && (
            <p style={{ color: '#b42318', textAlign: 'center', marginTop: '8px' }}>
              {error}
            </p>
          )}

          <button
            className="s03-continue-btn"
            aria-label={t.continue}
            onClick={handleContinue}
            type="button"
            disabled={loading}
          >
            {isRTL ? <ArrowLeftIcon /> : null}
            <span>{loading ? t.loading : t.continue}</span>
            {isRTL ? null : <ArrowRightIcon />}
          </button>
        </div>

      </div>
    </div>
  );
};

export default RegisterVerificationScreen;