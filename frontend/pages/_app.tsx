import type { AppProps } from 'next/app';
import Head from 'next/head';
import { useTranslation } from 'react-i18next';
import '../lib/i18n';
import { ThemeProvider } from '../components/ThemeContext';
import ThemeToggle from '../components/ThemeToggle';
import LanguageSwitcher from '../components/LanguageSwitcher';
import I18nBootstrap from '../components/I18nBootstrap';
import { ToastProvider } from '../components/Toast';
import DisclaimerModal from '../components/DisclaimerModal';
import SiteScripts from '../components/SiteScripts';
import '../styles/globals.css';

export default function MyApp({ Component, pageProps }: AppProps) {
  const { t } = useTranslation();
  return (
    <ThemeProvider>
      <Head>
        <title>{t('app.title')}</title>
      </Head>
      <ToastProvider>
        <ThemeToggle />
        <LanguageSwitcher />
        <I18nBootstrap />
        <Component {...pageProps} />
        <DisclaimerModal />
        <SiteScripts />
      </ToastProvider>
    </ThemeProvider>
  );
}
