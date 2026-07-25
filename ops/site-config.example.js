// 站点运行期配置示例（统计代码 / 广告位）。
//
// 使用方法：
//   1. 复制本文件：cp ops/site-config.example.js ops/site-override/site-config.js
//      （ops/site-override/ 已入 .gitignore，你的真实配置不会进仓库）
//   2. 按需填写下方字段
//   3. 在 docker-compose.override.yml 中挂载目录（模板见
//      docker-compose.override.yml.example 场景 4）：
//        services:
//          app:
//            volumes:
//              - ./ops/site-override:/app/frontend/out/override:ro
//   4. docker compose up -d 后刷新页面生效；以后改配置只需保存文件+刷新页面，
//      不用 rebuild、不用重启容器。
window.__SITE_CONFIG__ = {
  // ── Umami 自托管统计 ─────────────────────────────────────────────
  // src 填你的 Umami 实例脚本地址，websiteId 在 Umami 后台「网站」里获取。
  // 两个都填才会注入；留空则不加载任何统计代码。
  umami: {
    src: "https://analytics.yourdomain.com/script.js",
    websiteId: "00000000-0000-0000-0000-000000000000",
  },

  // ── Google AdSense（可选）────────────────────────────────────────
  // 填 ca-pub-xxxxxxxxxxxxxxxx 后自动全局加载 adsbygoogle.js；
  // 此时下方 ads 里填各广告单元的 slot id（纯数字字符串）。
  // 不用 AdSense（只放直客 HTML 广告）则保持空字符串。
  adsenseClient: "",

  // ── 广告位内容 ───────────────────────────────────────────────────
  // 位置说明：ad-footer-top = 主内容区底部、footer 免责声明上方（唯一预留位）。
  //   * 配了 adsenseClient → 填 slot id，如 "1234567890"
  //   * 未配 adsenseClient → 填任意 HTML 片段（直客图片/文字链）
  // 空字符串 = 不显示（不占页面空间）。
  ads: {
    // AdSense 形态示例：
    // "ad-footer-top": "1234567890",
    //
    // 直客 HTML 形态示例：
    // "ad-footer-top": "<a href='https://example.com' target='_blank' rel='sponsored noopener'><img src='https://example.com/banner.png' style='max-width:100%' alt='ad'></a>",
    "ad-footer-top": "",
  },
};
