import type { NextConfig } from "next";

// The browser only ever talks to this origin. Requests to /api/* are proxied to
// the FastAPI service, so the refresh cookie (path /api/v1/auth) is first-party
// and no CORS setup is needed.
const API_URL = (process.env.API_URL ?? "http://localhost:8000").replace(/\/$/, "");

const nextConfig: NextConfig = {
  cacheComponents: true,
  partialPrefetching: true,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${API_URL}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
