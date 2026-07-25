import { useEffect } from 'react';

/** 读取 window.__SITE_CONFIG__，按需注入统计脚本（Umami）与 AdSense 全局脚本。
 *
 *  配置来自 /override/site-config.js（_document.tsx 同步加载，先于本组件执行）。
 *  全部为空则不注入任何内容——默认部署零第三方请求。
 */
export default function SiteScripts() {
  useEffect(() => {
    const cfg = (window as any).__SITE_CONFIG__;
    if (!cfg) return;

    // Umami 自托管统计
    if (cfg.umami?.src && cfg.umami?.websiteId) {
      const s = document.createElement('script');
      s.src = cfg.umami.src;
      s.defer = true;
      s.setAttribute('data-website-id', cfg.umami.websiteId);
      document.head.appendChild(s);
    }

    // Google AdSense 全局脚本（配置了 client id 才加载）
    if (cfg.adsenseClient) {
      const s = document.createElement('script');
      s.src = `https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=${encodeURIComponent(cfg.adsenseClient)}`;
      s.async = true;
      s.crossOrigin = 'anonymous';
      document.head.appendChild(s);
    }
  }, []);

  return null;
}
