import { createContext, useContext, useState, useCallback } from 'react';

const LangContext = createContext(null);

// RBAC/dashboard cleanup task, Section 8 — "persist the selected
// language" was previously not implemented at all: `lang` reset to 'en'
// on every reload/navigation. Backed by localStorage the exact same way
// AuthContext persists the session, with the identical
// try/catch-and-ignore pattern for private-mode/quota failures (falls
// back to in-memory-only for that session rather than crashing).
const STORAGE_KEY = 'quickroute_lang';
const SUPPORTED_LANGS = ['en', 'ar', 'he'];

function readStoredLang() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return SUPPORTED_LANGS.includes(raw) ? raw : 'en';
  } catch {
    return 'en';
  }
}

export const LangProvider = ({ children }) => {
  const [lang, setLangState] = useState(readStoredLang);

  const setLang = useCallback((next) => {
    if (!SUPPORTED_LANGS.includes(next)) return;
    setLangState(next);
    try {
      localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // Ignore storage errors — the in-memory value still applies for
      // the rest of this session.
    }
  }, []);

  return (
    <LangContext.Provider value={{ lang, setLang }}>
      {children}
    </LangContext.Provider>
  );
};

export const useLang = () => useContext(LangContext);
