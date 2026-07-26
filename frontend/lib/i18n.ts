import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';

import zhCN from '../locales/zh-CN/common.json';
import zhTW from '../locales/zh-TW/common.json';
import en from '../locales/en/common.json';

export const SUPPORTED_LANGS = ['zh-CN', 'zh-TW', 'en'] as const;
export type Lang = typeof SUPPORTED_LANGS[number];
export const DEFAULT_LANG: Lang = 'zh-CN';
export const LANG_STORAGE_KEY = 'pref:lang';
export const GEO_PROBED_KEY = 'pref:geo_probed';

i18n
  .use(initReactI18next)
  .init({
    resources: {
      'zh-CN': { common: zhCN },
      'zh-TW': { common: zhTW },
      en: { common: en },
    },
    lng: DEFAULT_LANG,
    fallbackLng: DEFAULT_LANG,
    defaultNS: 'common',
    interpolation: { escapeValue: false },
    react: {
      useSuspense: false,
      bindI18n: 'languageChanged',
    },
  });

export default i18n;
