/** @type {import("next").NextConfig} */
const isDev = process.env.NODE_ENV === "development";
const basePath = isDev ? "" : (process.env.NEXT_PUBLIC_BASE_PATH || "/spread-finder");
const apiProxyDest = process.env.NEXT_PUBLIC_API_PROXY_DEST || "http://localhost:8000";

const nextConfig = {
  output: "standalone",
  basePath,
  reactStrictMode: true,
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${apiProxyDest}/api/:path*`,
      },
      {
        source: "/option-strategy-finder/api/:path*",
        destination: `${apiProxyDest}/option-strategy-finder/api/:path*`,
      },
    ];
  },
};

module.exports = nextConfig;
