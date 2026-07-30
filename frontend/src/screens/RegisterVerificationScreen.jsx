import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import QuickRouteLogo from '../components/QuickRouteLogo';
import { useLang } from '../context/LangContext';
import { validateInvitationCode } from '../api/invitationCodesApi';
import '../styles/RegisterVerificationScreen.css';

const ROLE_LABELS = {
  en: {
    super_admin: 'Super Admin', global_manager: 'Global Manager',
    building_manager: 'Building Manager', regular_user: 'Regular User',
  },
  ar: {
    super_admin: 'مشرف عام', global_manager: 'مدير عام',
    building_manager: 'مدير مبنى', regular_user: 'مستخدم عادي',
  },
  he: {
    super_admin: 'מנהל-על', global_manager: 'מנהל גלובלי',
    building_manager: 'מנהל מבנה', regular_user: 'משתמש רגיל',
  },
};

const UI = {
  en: {
    title: 'Sign Up',
    placeholder: 'Enter identification code',
    continue: 'Continue',
    back: 'Back',
    loading: 'Checking code...',
    required: 'Please enter the identification code',
    invalid: 'Invalid or used identification code',
    previewTitle: 'Invitation Details',
    role: 'Role',
    buildings: 'Buildings',
    allBuildings: 'All buildings',
    noBuildings: 'None',
    email: 'Restricted to',
    expires: 'Expires',
    never: 'No expiration',
    continueToAccount: 'Continue to Account Creation',
    editCode: 'Use a different code',
  },
  ar: {
    title: 'إنشاء حساب',
    placeholder: 'أدخل رمز التعريف',
    continue: 'متابعة',
    back: 'رجوع',
    loading: 'جاري فحص الرمز...',
    required: 'أدخلي رمز التعريف',
    invalid: 'رمز التعريف غير صحيح أو مستخدم',
    previewTitle: 'تفاصيل الدعوة',
    role: 'الدور',
    buildings: 'المباني',
    allBuildings: 'كل المباني',
    noBuildings: 'لا شيء',
    email: 'مقصور على',
    expires: 'ينتهي',
    never: 'بدون انتهاء',
    continueToAccount: 'متابعة لإنشاء الحساب',
    editCode: 'استخدم رمزًا آخر',
  },
  he: {
    title: 'הרשמה',
    placeholder: 'הזן קוד מזהה',
    continue: 'המשך',
    back: 'חזרה',
    loading: 'בודק קוד...',
    required: 'יש להזין קוד מזהה',
    invalid: 'קוד מזהה לא תקין או כבר בשימוש',
    previewTitle: 'פרטי ההזמנה',
    role: 'תפקיד',
    buildings: 'מבנים',
    allBuildings: 'כל המבנים',
    noBuildings: 'ללא',
    email: 'מוגבל ל',
    expires: 'פג תוקף',
    never: 'ללא תפוגה',
    continueToAccount: 'המשך ליצירת חשבון',
    editCode: 'השתמש בקוד אחר',
  },
};

const INVITATION_CODE_KEY = 'quickroute_invitation_code';
const INVITATION_PREVIEW_KEY = 'quickroute_invitation_preview';

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
  const [preview, setPreview] = useState(null);

  const isRTL = lang === 'ar' || lang === 'he';
  const t = UI[lang];
  const roleLabels = ROLE_LABELS[lang];

  const handleContinue = async () => {
    setError('');

    const code = barcode.trim();

    if (!code) {
      setError(t.required);
      return;
    }

    try {
      setLoading(true);

      const result = await validateInvitationCode(code);

      localStorage.setItem(INVITATION_CODE_KEY, code);
      localStorage.setItem(INVITATION_PREVIEW_KEY, JSON.stringify(result));

      // Show a safe summary (role, buildings, email restriction,
      // expiration) before moving on to account creation, so the invited
      // person can confirm what they're signing up for.
      setPreview(result);
    } catch (err) {
      setError(err.message || t.invalid);
    } finally {
      setLoading(false);
    }
  };

  const handleEditCode = () => {
    setPreview(null);
    setError('');
    localStorage.removeItem(INVITATION_CODE_KEY);
    localStorage.removeItem(INVITATION_PREVIEW_KEY);
  };

  const handleContinueToAccount = () => {
    navigate('/screen/04');
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

        {preview ? (
          <div className="s03-form">
            <div style={{
              borderRadius: 14, padding: 16, background: 'rgba(74,122,200,0.06)',
              border: '1px solid rgba(74,122,200,0.18)', textAlign: isRTL ? 'right' : 'left',
            }}>
              <div style={{ fontWeight: 800, fontSize: 14, marginBottom: 10 }}>{t.previewTitle}</div>
              <div style={{ fontSize: 13, lineHeight: 1.9 }}>
                <div><strong>{t.role}:</strong> {roleLabels[preview.role] || preview.role}</div>
                <div>
                  <strong>{t.buildings}:</strong>{' '}
                  {preview.all_buildings
                    ? t.allBuildings
                    : (preview.buildings || []).map((b) => b.name).join(', ') || t.noBuildings}
                </div>
                {preview.intended_email && (
                  <div><strong>{t.email}:</strong> {preview.intended_email}</div>
                )}
                <div>
                  <strong>{t.expires}:</strong>{' '}
                  {preview.expires_at ? new Date(preview.expires_at).toLocaleString() : t.never}
                </div>
              </div>
            </div>

            <button
              className="s03-continue-btn"
              aria-label={t.continueToAccount}
              onClick={handleContinueToAccount}
              type="button"
              style={{ marginTop: 16 }}
            >
              {isRTL ? <ArrowLeftIcon /> : null}
              <span>{t.continueToAccount}</span>
              {isRTL ? null : <ArrowRightIcon />}
            </button>

            <button
              type="button"
              onClick={handleEditCode}
              style={{
                display: 'block', margin: '12px auto 0', background: 'none', border: 'none',
                color: '#5a7aaa', fontSize: 13, textDecoration: 'underline', cursor: 'pointer',
              }}
            >
              {t.editCode}
            </button>
          </div>
        ) : (
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
        )}

      </div>
    </div>
  );
};

export default RegisterVerificationScreen;