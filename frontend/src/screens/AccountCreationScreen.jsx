import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import QuickRouteLogo from '../components/QuickRouteLogo';
import { useLang } from '../context/LangContext';
import '../styles/AccountCreationScreen.css';

const UI = {
  en: {
    title:           'Create Account',
    groupUser:       'Username',
    groupPass:       'Password',
    username:        'New username',
    confirmUsername: 'Confirm username',
    password:        'New password',
    confirmPassword: 'Confirm password',
    finish:          'Finish',
    back:            'Back',
  },
  ar: {
    title:           'إنشاء حساب',
    groupUser:       'اسم المستخدم',
    groupPass:       'كلمة المرور',
    username:        'اسم مستخدم جديد',
    confirmUsername: 'تأكيد اسم المستخدم',
    password:        'كلمة مرور جديدة',
    confirmPassword: 'تأكيد كلمة المرور',
    finish:          'إنهاء',
    back:            'رجوع',
  },
  he: {
    title:           'יצירת חשבון',
    groupUser:       'שם משתמש',
    groupPass:       'סיסמה',
    username:        'שם משתמש חדש',
    confirmUsername: 'אימות שם משתמש',
    password:        'סיסמה חדשה',
    confirmPassword: 'אימות סיסמה',
    finish:          'סיום',
    back:            'חזרה',
  },
};

const UserIcon = () => (
  <svg width="17" height="17" viewBox="0 0 24 24" fill="none" aria-hidden="true">
    <circle cx="12" cy="8" r="4" stroke="currentColor" strokeWidth="1.8" />
    <path d="M4 20c0-4 3.6-7 8-7s8 3 8 7" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
  </svg>
);

const LockIcon = () => (
  <svg width="17" height="17" viewBox="0 0 24 24" fill="none" aria-hidden="true">
    <rect x="5" y="11" width="14" height="10" rx="2.5" stroke="currentColor" strokeWidth="1.8" />
    <path d="M8 11V7a4 4 0 0 1 8 0v4" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
    <circle cx="12" cy="16" r="1.5" fill="currentColor" opacity="0.6" />
  </svg>
);

const CheckIcon = () => (
  <svg width="17" height="17" viewBox="0 0 24 24" fill="none" aria-hidden="true">
    <rect x="5" y="11" width="14" height="10" rx="2.5" stroke="currentColor" strokeWidth="1.8" />
    <path d="M8 11V7a4 4 0 0 1 8 0v4" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
    <path d="M9.5 16l2 2 3-3" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

const EyeIcon = ({ open }) =>
  open ? (
    <svg width="17" height="17" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M1 12s4-7 11-7 11 7 11 7-4 7-11 7S1 12 1 12z" stroke="currentColor" strokeWidth="1.8" />
      <circle cx="12" cy="12" r="3" stroke="currentColor" strokeWidth="1.8" />
    </svg>
  ) : (
    <svg width="17" height="17" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19M1 1l22 22" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
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

const AccountCreationScreen = () => {
  const { lang }  = useLang();
  const navigate  = useNavigate();
  const isRTL     = lang === 'ar' || lang === 'he';
  const t         = UI[lang];

  const [username,        setUsername]        = useState('');
  const [confirmUsername, setConfirmUsername] = useState('');
  const [password,        setPassword]        = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [showPass,        setShowPass]        = useState(false);
  const [showConfPass,    setShowConfPass]    = useState(false);

  return (
    <div className="layout-wrapper">
      <div className="layout-shell s04-shell" dir={isRTL ? 'rtl' : 'ltr'}>

        {/* ── Back button ── */}
        <div className={`s04-topbar${isRTL ? ' s04-topbar-rtl' : ''}`}>
          <button
            className={`s04-back-btn${isRTL ? ' s04-back-btn-rtl' : ''}`}
            onClick={() => navigate('/screen/03')}
            aria-label={t.back}
          >
            {isRTL ? <BackArrowRTL /> : <BackArrowLTR />}
            {t.back}
          </button>
        </div>

        {/* ── Branding ── */}
        <div className="s04-brand">
          <div className="s04-logo-card">
            <QuickRouteLogo size={40} />
          </div>
          <div className="s04-wordmark">
            Quick<span>Route</span>
          </div>
        </div>

        {/* ── Page title ── */}
        <div className="s04-heading">
          <h1 className="s04-title">{t.title}</h1>
        </div>

        {/* ── Form ── */}
        <div className="s04-form">

          {/* Username group */}
          <div className="s04-field-group">
            <span className="s04-group-label">{t.groupUser}</span>

            <div className="s04-input-wrap">
              <span className={`s04-input-icon${isRTL ? ' s04-input-icon-rtl' : ''}`}>
                <UserIcon />
              </span>
              <input
                className={`s04-input${isRTL ? ' s04-input-rtl' : ''}`}
                type="text"
                autoComplete="username"
                placeholder={t.username}
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                dir={isRTL ? 'rtl' : 'ltr'}
              />
            </div>

            <div className="s04-input-wrap">
              <span className={`s04-input-icon${isRTL ? ' s04-input-icon-rtl' : ''}`}>
                <CheckIcon />
              </span>
              <input
                className={`s04-input${isRTL ? ' s04-input-rtl' : ''}`}
                type="text"
                autoComplete="username"
                placeholder={t.confirmUsername}
                value={confirmUsername}
                onChange={(e) => setConfirmUsername(e.target.value)}
                dir={isRTL ? 'rtl' : 'ltr'}
              />
            </div>
          </div>

          <div className="s04-divider" />

          {/* Password group */}
          <div className="s04-field-group">
            <span className="s04-group-label">{t.groupPass}</span>

            <div className="s04-input-wrap">
              <span className={`s04-input-icon${isRTL ? ' s04-input-icon-rtl' : ''}`}>
                <LockIcon />
              </span>
              <input
                className={`s04-input s04-input-pwd${isRTL ? ' s04-input-rtl' : ''}`}
                type={showPass ? 'text' : 'password'}
                autoComplete="new-password"
                placeholder={t.password}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                dir={isRTL ? 'rtl' : 'ltr'}
              />
              <button
                className={`s04-eye-btn${isRTL ? ' s04-eye-btn-rtl' : ''}`}
                onClick={() => setShowPass((v) => !v)}
                aria-label={showPass ? 'Hide password' : 'Show password'}
                type="button"
              >
                <EyeIcon open={showPass} />
              </button>
            </div>

            <div className="s04-input-wrap">
              <span className={`s04-input-icon${isRTL ? ' s04-input-icon-rtl' : ''}`}>
                <LockIcon />
              </span>
              <input
                className={`s04-input s04-input-pwd${isRTL ? ' s04-input-rtl' : ''}`}
                type={showConfPass ? 'text' : 'password'}
                autoComplete="new-password"
                placeholder={t.confirmPassword}
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                dir={isRTL ? 'rtl' : 'ltr'}
              />
              <button
                className={`s04-eye-btn${isRTL ? ' s04-eye-btn-rtl' : ''}`}
                onClick={() => setShowConfPass((v) => !v)}
                aria-label={showConfPass ? 'Hide password' : 'Show password'}
                type="button"
              >
                <EyeIcon open={showConfPass} />
              </button>
            </div>
          </div>

          {/* Finish */}
          <button
            className="s04-finish-btn"
            aria-label={t.finish}
            onClick={() => navigate('/screen/02')}
          >
            {t.finish}
          </button>

        </div>

      </div>
    </div>
  );
};

export default AccountCreationScreen;
