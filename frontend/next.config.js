/** @type {import("next").NextConfig} */
const isDev = process.env.NODE_ENV === "development";
const basePath = isDev ? "" : (process.env.NEXT_PUBLIC_BASE_PATH || "/option-strategy-finder");

const nextConfig = {
  output: "standalone",
  basePath,
  reactStrictMode: true,
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: "http://localhost:8000/api/:path*",
      },
      {
        source: "/option-strategy-finder/api/:path*",
        destination: "http://localhost:8000/option-strategy-finder/api/:path*",
      },
    ];
  },
};

module.exports = nextConfig;
