import type { AppProps } from 'next/app';
import { ThemeProvider } from '../components/ThemeContext';
import ThemeToggle from '../components/ThemeToggle';
import { ToastProvider } from '../components/Toast';
import '../styles/globals.css';

export default function MyApp({ Component, pageProps }: AppProps) {
  return (
    <ThemeProvider>
      <ToastProvider>
        <ThemeToggle />
        <Component {...pageProps} />
      </ToastProvider>
    </ThemeProvider>
  );
}
