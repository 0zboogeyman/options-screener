// 站点运行期配置（统计代码 / 广告位）。
//
// 本文件是默认空配置（进 git）：不注入任何统计脚本、不显示广告。
// 自定义方法（无需重新构建镜像）：
//   1. cp ops/site-config.example.js ops/site-override/site-config.js
//   2. 按需填写该文件
//   3. 在 docker-compose.override.yml 挂载 ops/site-override 目录
//      （模板见 docker-compose.override.yml.example 场景 4）
//   4. docker compose up -d 后刷新页面即生效
//
// 前端加载点：pages/_document.tsx 同步引入 /override/site-config.js。
window.__SITE_CONFIG__ = {
  // Umami 自托管统计：src 与 websiteId 都填写才会注入
  // <script defer src="..." data-website-id="...">
  umami: { src: "", websiteId: "" },

  // Google AdSense 客户端 ID（ca-pub-xxxxxxxxxxxxxxxx）。
  // 填写后自动全局加载 adsbygoogle.js；此时下方 ads 各位置填 slot id（纯数字字符串）。
  adsenseClient: "",

  // 广告位内容：
  //   * 配了 adsenseClient → 填 AdSense slot id（如 "1234567890"）
  //   * 未配 adsenseClient → 填任意 HTML 片段（直客图片/文字链广告）
  // 空字符串 = 不显示（广告位不占页面空间）。
  ads: {
    "ad-footer-top": "",
  },
};
