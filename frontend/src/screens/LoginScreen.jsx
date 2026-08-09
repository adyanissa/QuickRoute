import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import QuickRouteLogo from '../components/QuickRouteLogo';
import { useLang } from '../context/LangContext';
import { useAuth } from '../context/AuthContext';
import { loginUser } from '../api/authApi';
import { resolvePostLoginRoute } from '../utils/roleRouting';
import '../styles/LoginScreen.css';

const UI = {
  en: {
    title: 'Login',
    userPlaceholder: 'Enter email',
    passPlaceholder: 'Enter password',
    signIn: 'Sign In',
    back: 'Back',
    loading: 'Signing in...',
    required: 'Please enter email and password',
    failed: 'Login failed. Please check your details.',
  },
  ar: {
    title: 'تسجيل الدخول',
    userPlaceholder: 'أدخل البريد الإلكتروني',
    passPlaceholder: 'أدخل كلمة المرور',
    signIn: 'دخول',
    back: 'رجوع',
    loading: 'جاري تسجيل الدخول...',
    required: 'أدخل البريد الإلكتروني وكلمة المرور',
    failed: 'فشل تسجيل الدخول. افحصي البيانات.',
  },
  he: {
    title: 'התחברות',
    userPlaceholder: 'הזן אימייל',
    passPlaceholder: 'הזן סיסמה',
    signIn: 'כניסה',
    back: 'חזרה',
    loading: 'מתחבר...',
    required: 'יש להזין אימייל וסיסמה',
    failed: 'ההתחברות נכשלה. בדקי את הפרטים.',
  },
};

const UserIcon = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
    <circle cx="12" cy="8" r="4" stroke="currentColor" strokeWidth="1.8" />
    <path d="M4 20c0-4 3.6-7 8-7s8 3 8 7" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
  </svg>
);

const LockIcon = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
    <rect x="5" y="11" width="14" height="10" rx="2.5" stroke="currentColor" strokeWidth="1.8" />
    <path d="M8 11V7a4 4 0 0 1 8 0v4" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
    <circle cx="12" cy="16" r="1.5" fill="currentColor" opacity="0.6" />
  </svg>
);

const EyeIcon = ({ open }) =>
  open ? (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M1 12s4-7 11-7 11 7 11 7-4 7-11 7S1 12 1 12z" stroke="currentColor" strokeWidth="1.8" />
      <circle cx="12" cy="12" r="3" stroke="currentColor" strokeWidth="1.8" />
    </svg>
  ) : (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
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

const LoginScreen = () => {
  const { lang } = useLang();
  const navigate = useNavigate();
  const { login } = useAuth();

  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [showPass, setShowPass] = useState(false);

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const isRTL = lang === 'ar' || lang === 'he';
  const t = UI[lang];

  const handleLogin = async () => {
    setError('');

    if (!username.trim() || !password.trim()) {
      setError(t.required);
      return;
    }

    try {
      setLoading(true);

      const data = await loginUser({
        email: username.trim(),
        password: password,
      });

      const user = data.user;

      login(user, data.access_token);
      navigate(resolvePostLoginRoute(user));
    } catch (err) {
      setError(err.message || t.failed);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="layout-wrapper">
      <div className="layout-shell s02-shell" dir={isRTL ? 'rtl' : 'ltr'}>

        <div className={`s02-topbar${isRTL ? ' s02-topbar-rtl' : ''}`}>
          <button
            className={`s02-back-btn${isRTL ? ' s02-back-btn-rtl' : ''}`}
            onClick={() => navigate('/screen/01')}
            aria-label={t.back}
            type="button"
          >
            {isRTL ? <BackArrowRTL /> : <BackArrowLTR />}
            {t.back}
          </button>
        </div>

        <div className="s02-brand">
          <div className="s02-logo-card">
            <QuickRouteLogo size={46} />
          </div>
          <div className="s02-wordmark">
            Quick<span>Route</span>
          </div>
        </div>

        <div className="s02-heading">
          <h1 className="s02-title">{t.title}</h1>
        </div>

        <div className="s02-form">

          <div className="s02-input-wrap">
            <span className={`s02-input-icon${isRTL ? ' s02-input-icon-rtl' : ''}`}>
              <UserIcon />
            </span>
            <input
              className={`s02-input${isRTL ? ' s02-input-rtl' : ''}`}
              type="email"
              autoComplete="email"
              placeholder={t.userPlaceholder}
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              dir={isRTL ? 'rtl' : 'ltr'}
            />
          </div>

          <div className="s02-input-wrap">
            <span className={`s02-input-icon${isRTL ? ' s02-input-icon-rtl' : ''}`}>
              <LockIcon />
            </span>
            <input
              className={`s02-input s02-input-pwd${isRTL ? ' s02-input-rtl' : ''}`}
              type={showPass ? 'text' : 'password'}
              autoComplete="current-password"
              placeholder={t.passPlaceholder}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  handleLogin();
                }
              }}
              dir={isRTL ? 'rtl' : 'ltr'}
            />
            <button
              className={`s02-eye-btn${isRTL ? ' s02-eye-btn-rtl' : ''}`}
              onClick={() => setShowPass((v) => !v)}
              aria-label={showPass ? 'Hide password' : 'Show password'}
              type="button"
            >
              <EyeIcon open={showPass} />
            </button>
          </div>

          {error && (
            <p style={{ color: '#b42318', textAlign: 'center', marginTop: '8px' }}>
              {error}
            </p>
          )}

          <button
            className="s02-signin-btn"
            onClick={handleLogin}
            aria-label={t.signIn}
            type="button"
            disabled={loading}
          >
            {loading ? t.loading : t.signIn}
          </button>

        </div>

      </div>
    </div>
  );
};

export default LoginScreen;