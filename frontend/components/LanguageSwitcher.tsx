import { useState, useRef, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import i18n, { SUPPORTED_LANGS, type Lang } from '../lib/i18n';
import { usePersistedState } from '../lib/usePersistedState';

const LANG_LABELS: Record<Lang, string> = {
  'zh-CN': '简体中文',
  'zh-TW': '繁體中文',
  en: 'English',
};

const LANG_SHORT: Record<Lang, string> = {
  'zh-CN': '中',
  'zh-TW': '繁',
  en: 'EN',
};

export default function LanguageSwitcher() {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [lang, setLang] = usePersistedState<Lang>('lang', 'zh-CN');
  const ref = useRef<HTMLDivElement>(null);

  // 外部点击关闭
  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [open]);

  const handleSelect = (l: Lang) => {
    setLang(l);
    i18n.changeLanguage(l);
    if (typeof document !== 'undefined') {
      document.documentElement.lang = l;
    }
    setOpen(false);
  };

  return (
    <div className="lang-switcher" ref={ref}>
      <button
        className="lang-switcher-btn"
        onClick={() => setOpen(o => !o)}
        aria-label={t('lang.aria')}
        title={t('lang.aria')}
      >
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="12" cy="12" r="10" />
          <path d="M2 12h20" />
          <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z" />
        </svg>
        <span className="lang-switcher-label">{LANG_SHORT[lang]}</span>
      </button>
      {open && (
        <ul className="lang-switcher-menu" role="menu">
          {SUPPORTED_LANGS.map(l => (
            <li key={l} role="menuitem">
              <button
                className={`lang-option ${l === lang ? 'active' : ''}`}
                onClick={() => handleSelect(l)}
              >
                {LANG_LABELS[l]}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
