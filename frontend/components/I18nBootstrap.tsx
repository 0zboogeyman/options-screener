import { useEffect } from 'react';
import i18n, { DEFAULT_LANG, LANG_STORAGE_KEY, GEO_PROBED_KEY, SUPPORTED_LANGS, type Lang } from '../lib/i18n';

function isLang(x: unknown): x is Lang {
  return typeof x === 'string' && (SUPPORTED_LANGS as readonly string[]).includes(x);
}

function applyLang(lang: Lang) {
  if (i18n.language !== lang) i18n.changeLanguage(lang);
  if (typeof document !== 'undefined') {
    document.documentElement.lang = lang;
  }
}

/** 首访副作用组件：读 localStorage → 无则调 /api/geo → changeLanguage。
 * 返回 null，不渲染任何 UI，与 SSG HTML 无冲突。 */
export default function I18nBootstrap() {
  useEffect(() => {
    // 1) 优先读 localStorage 用户偏好（与 usePersistedState 的 JSON 序列化格式一致）
    let stored: unknown = null;
    try {
      const raw = localStorage.getItem(LANG_STORAGE_KEY);
      if (raw != null) stored = JSON.parse(raw);
    } catch { /* 隐私模式或损坏数据 */ }

    if (isLang(stored)) {
      applyLang(stored);
      return; // 已有偏好，不再调 /api/geo
    }

    // 2) 无偏好 → 调后端 /api/geo 异步识别
    const ctrl = new AbortController();
    fetch('/api/geo', { signal: ctrl.signal })
      .then(r => (r.ok ? r.json() : null))
      .then(d => {
        const lang = isLang(d?.lang) ? d.lang : DEFAULT_LANG;
        applyLang(lang);
        try { localStorage.setItem(GEO_PROBED_KEY, JSON.stringify(true)); } catch { /* ignore */ }
      })
      .catch(() => {
        // 网络失败/IP 限流 → 用默认语言，不写偏好（下次访问仍会重试）
        applyLang(DEFAULT_LANG);
      });

    return () => ctrl.abort();
  }, []);

  return null;
}
