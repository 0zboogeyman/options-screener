import { Html, Head, Main, NextScript } from 'next/document';

export default function Document() {
  return (
    <Html lang="zh-CN">
      <Head>
        <link rel="icon" type="image/svg+xml" href="/favicon.svg" />
        <link rel="apple-touch-icon" href="/favicon.svg" />
        <meta name="theme-color" content="#0a1628" />
        <meta name="description" content="基于 Deribit 期权数据的智能期权策略筛选工具" />
        {/* 运行期站点配置（统计/广告）：同步加载，保证 React hydrate 前
            window.__SITE_CONFIG__ 就位。默认空配置，可用 docker 挂载覆盖。 */}
        <script src="/override/site-config.js"></script>
      </Head>
      <body>
        <Main />
        <NextScript />
      </body>
    </Html>
  );
}
