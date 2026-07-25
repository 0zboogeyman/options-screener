import type { AppProps } from 'next/app';
import Head from 'next/head';
import { ThemeProvider } from '../components/ThemeContext';
import ThemeToggle from '../components/ThemeToggle';
import { ToastProvider } from '../components/Toast';
import '../styles/globals.css';

export default function MyApp({ Component, pageProps }: AppProps) {
  return (
    <ThemeProvider>
      <Head>
        <title>BTC/ETH期权策略扫描</title>
      </Head>
      <ToastProvider>
        <ThemeToggle />
        <Component {...pageProps} />
      </ToastProvider>
    </ThemeProvider>
  );
}
