/** @type {import("next").NextConfig} */
const basePath = process.env.NEXT_PUBLIC_BASE_PATH || "";

const nextConfig = {
  // 静态导出：产物为纯 HTML/JS/CSS（out/ 目录），由 FastAPI StaticFiles 同源托管。
  // 不再需要 Next.js Node 运行时，也不再需要 /api rewrite 代理——
  // 页面与 API 同端口同域，浏览器直接请求相对路径 /api/*。
  output: "export",
  basePath,
  reactStrictMode: true,
  // 静态导出无服务端，关闭基于 Node 服务的图片优化
  images: { unoptimized: true },
};

module.exports = nextConfig;
