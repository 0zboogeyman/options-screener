import { Html, Head, Main, NextScript } from 'next/document';

export default function Document() {
  return (
    <Html lang="zh-CN">
      <Head>
        <link rel="icon" type="image/svg+xml" href="/favicon.svg" />
        <link rel="apple-touch-icon" href="/favicon.svg" />
        <meta name="theme-color" content="#0a1628" />
        <meta name="description" content="基于 Deribit 期权数据的智能期权策略筛选工具" />
      </Head>
      <body>
        <Main />
        <NextScript />
      </body>
    </Html>
  );
}
