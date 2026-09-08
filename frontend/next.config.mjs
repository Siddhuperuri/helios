/** @type {import('next').NextConfig} */

/**
 * The API is served from the same origin as the app, and that is a deliberate deployment
 * decision rather than a convenience.
 *
 * The refresh token is a `SameSite=Lax` cookie. Lax means the browser withholds it from
 * cross-site requests — and `localhost:3000` calling `127.0.0.1:8000` is cross-site, since
 * "site" is the host, not the port. So a split-origin development setup silently breaks
 * silent refresh: everything works until an access token expires, at which point the user
 * is signed out with no explanation.
 *
 * In production Nginx already routes `/api/*` to the backend cluster and everything else
 * to the frontend, so the two share an origin. This rewrite makes development match that,
 * which means the cookie path is exercised the same way in both. `NEXT_PUBLIC_API_BASE` is
 * therefore empty by default — the clients call `/api/...` relatively.
 *
 * Setting `NEXT_PUBLIC_API_BASE` to an absolute URL still works and disables the rewrite,
 * for a deployment that genuinely splits the origins. That configuration additionally needs
 * `SOLAR_COOKIE_SAMESITE=none`, `SOLAR_COOKIE_SECURE=true` and the frontend origin in
 * `SOLAR_CORS_ORIGINS`.
 */
const BACKEND_ORIGIN = (process.env.SOLAR_BACKEND_ORIGIN ?? 'http://127.0.0.1:8000').replace(
  /\/$/,
  '',
);

const usesSameOrigin = !process.env.NEXT_PUBLIC_API_BASE;

const nextConfig = {
  reactStrictMode: true,

  /**
   * How long the development rewrite will wait for the backend.
   *
   * Next's dev proxy gives up after 30 seconds and answers with its own plain-text
   * "Internal Server Error" — no JSON envelope, no remedy, nothing the client can explain
   * to the user. That is under half the time a legitimate request here can take: an
   * analysis trains and cross-validates inside the request, the four-model ensemble fits
   * every base model once per inner fold, and a model comparison over a long period runs
   * for minutes. The result was a request that completed perfectly on the backend while
   * the browser was told the server had failed.
   *
   * 300 seconds matches `proxy_read_timeout` in deploy/nginx/conf.d/helios.conf, so
   * development and production now wait the same length of time. Deliberately not
   * unlimited: a request that has hung for five minutes is a fault worth surfacing.
   */
  experimental: {
    proxyTimeout: 300_000,
  },

  /**
   * Emit a self-contained server bundle.
   *
   * Next traces the modules the server actually reaches and writes them, plus a minimal
   * `server.js`, to `.next/standalone`. The production image copies that instead of the
   * whole `node_modules` tree, which is the difference between shipping the dependencies
   * the app uses and shipping every dependency it was built with.
   */
  output: 'standalone',

  async rewrites() {
    if (!usesSameOrigin) return [];
    return [{ source: '/api/:path*', destination: `${BACKEND_ORIGIN}/api/:path*` }];
  },

  async headers() {
    return [
      {
        source: '/:path*',
        headers: [
          { key: 'X-Content-Type-Options', value: 'nosniff' },
          { key: 'Referrer-Policy', value: 'strict-origin-when-cross-origin' },
          { key: 'X-Frame-Options', value: 'DENY' },
          // The calculator asks for a GPS fix on request; nothing else here needs a
          // device permission, so everything else is denied outright.
          {
            key: 'Permissions-Policy',
            value: 'camera=(), microphone=(), payment=(), interest-cohort=()',
          },
        ],
      },
    ];
  },
};

export default nextConfig;
