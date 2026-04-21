const { withSentryConfig } = require("@sentry/nextjs");

/** @type {import('next').NextConfig} */
const nextConfig = {
  // Enable React strict mode for development
  reactStrictMode: true,
  output: "standalone",

  // Backend API proxy to avoid CORS in development
  async rewrites() {
    const backendUrl = process.env.NEXT_INTERNAL_BACKEND_URL || "http://127.0.0.1:8000";
    return [
      {
        source: "/api/v1/:path*",
        destination: `${backendUrl}/api/v1/:path*`,
      },
      {
        source: "/api/health",
        destination: `${backendUrl}/api/health`,
      },
      {
        source: "/metrics",
        destination: `${backendUrl}/metrics`,
      },
    ];
  },

  // Image optimization
  images: {
    remotePatterns: [
      { protocol: "https", hostname: "*.supabase.co" },
    ],
  },
};

module.exports = withSentryConfig(nextConfig, {
  // Suppress Sentry CLI output during build
  silent: true,
  // Upload source maps only in CI/production
  disableSourceMapUpload: process.env.NODE_ENV !== "production",
  // Automatically instrument Next.js data fetching methods
  autoInstrumentServerFunctions: true,
});
