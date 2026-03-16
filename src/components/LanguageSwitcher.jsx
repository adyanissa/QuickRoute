import React from 'react';
import { useLanguage } from '../context/LanguageContext';
import '../styles/LanguageSwitcher.css';

const LANGUAGE_OPTIONS = [
  { code: 'ar', label: 'عربي' },
  { code: 'he', label: 'עברית' },
  { code: 'en', label: 'EN' },
];

const LanguageSwitcher = () => {
  const { language, changeLanguage } = useLanguage();

  return (
    <div className="lang-seg" role="group" aria-label="Language selector">
      {LANGUAGE_OPTIONS.map((opt) => (
        <button
          key={opt.code}
          className={`lang-seg-btn${opt.code === language ? ' active' : ''}`}
          onClick={() => changeLanguage(opt.code)}
          aria-pressed={opt.code === language}
        >
          {opt.label}
        </button>
      ))}
    </div>
  );
};

export default LanguageSwitcher;
