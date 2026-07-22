/** @type {import("next").NextConfig} */
const basePath = process.env.NEXT_PUBLIC_BASE_PATH || "";

const nextConfig = {
  output: "standalone",
  basePath,
  reactStrictMode: true,
  async rewrites() {
    const apiProxyDest = process.env.NEXT_PUBLIC_API_PROXY_DEST || "http://localhost:8000";
    return [
      {
        source: "/api/:path*",
        destination: `${apiProxyDest}/api/:path*`,
        basePath: false,
      },
    ];
  },
};

module.exports = nextConfig;
