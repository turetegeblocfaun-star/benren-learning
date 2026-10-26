import type { NextConfig } from "next";

const productionBackendUrl =
  "https://sbfckr523j36jk3lcagcm.apigateway-cn-beijing.volceapi.com";
const backendUrl = (
  process.env.BACKEND_URL ??
  (process.env.NODE_ENV === "production" ? productionBackendUrl : "http://127.0.0.1:8100")
).replace(/\/$/, "");

const nextConfig: NextConfig = {
  output: "standalone",
  experimental: {
    // Rewrites proxy browser uploads through Next so the HttpOnly session stays
    // same-origin. Keep this aligned with backend MAX_BATCH_BYTES (500 MiB).
    proxyClientMaxBodySize: 500 * 1024 * 1024,
  },
  // Include the API mode in Next's configuration hash. This prevents a dev
  // server restarted in Mock mode from reusing a bundle compiled in real mode
  // (and vice versa) during the integration regression suite.
  env: {
    NEXT_PUBLIC_API_MODE: process.env.NEXT_PUBLIC_API_MODE ?? "real",
  },
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${backendUrl}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
