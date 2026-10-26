import { PHASE_DEVELOPMENT_SERVER } from "next/constants.js";

const API_ORIGIN = process.env.FINALLY_API_ORIGIN || "http://localhost:8000";

/**
 * Production builds are a static export (served by FastAPI from the same origin).
 * `next dev` proxies /api/* to the backend instead, since rewrites don't apply to exports.
 */
export default function nextConfig(phase) {
  const base = {
    reactStrictMode: true,
    images: { unoptimized: true },
    // The SSE stream must not be gzip-buffered by the dev proxy.
    compress: false,
  };
  if (phase === PHASE_DEVELOPMENT_SERVER) {
    return {
      ...base,
      async rewrites() {
        return [{ source: "/api/:path*", destination: `${API_ORIGIN}/api/:path*` }];
      },
    };
  }
  return { ...base, output: "export", trailingSlash: false };
}
