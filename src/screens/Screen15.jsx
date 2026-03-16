import React from 'react';
import { useNavigate } from 'react-router-dom';
import { useLanguage } from '../context/LanguageContext';
import translations from '../translations/translations';
import LanguageSwitcher from '../components/LanguageSwitcher';
import QuickRouteLogo from '../components/QuickRouteLogo';
import '../styles/Screen15.css';

const Screen15 = () => {
  const navigate = useNavigate();
  const { language, isRTL } = useLanguage();
  const t = translations[language];

  return (
    <div className="s15-shell">
      <div className="s15-container" dir={isRTL ? 'rtl' : 'ltr'}>
        {/* Language switcher — physical top-right, always */}
        <div className="s15-lang-corner">
          <LanguageSwitcher />
        </div>

        {/* Main content */}
        <div className="s15-content">
          <h1 className="s15-welcome">{t.welcomeTo}</h1>

          <div className="s15-logo-wrapper">
            <div className="s15-logo-box">
              <QuickRouteLogo size={68} />
            </div>
            <span className="s15-brand">{t.appName}</span>
          </div>

          <button
            className="s15-go-btn"
            onClick={() => navigate('/screen/16')}
          >
            {t.go}
          </button>
        </div>

        {/* Back button — bottom-start corner (left LTR, right RTL) */}
        <div className="s15-back-corner">
          <button className="s15-back-btn" onClick={() => navigate(-1)}>
            {t.back}
          </button>
        </div>
      </div>
    </div>
  );
};

export default Screen15;
