import type { NextConfig } from "next";
import createNextIntlPlugin from "next-intl/plugin";

const withNextIntl = createNextIntlPlugin("./src/i18n/request.ts");

/**
 * Origin of the FastAPI service. The browser always calls `/api/v1/*` on the web origin; Next.js
 * proxies it here. Rewrites are compiled into the build manifest, so API_ORIGIN is read at BUILD
 * time. In production Caddy routes `/api/*` to the API before requests ever reach Next.js.
 */
function resolveApiOrigin(raw: string | undefined): string {
  const value = raw?.trim() || "http://127.0.0.1:8000";
  const url = new URL(value);
  if (url.protocol !== "http:" && url.protocol !== "https:") {
    throw new Error(`API_ORIGIN must be an http(s) URL, got ${url.protocol}`);
  }
  return url.origin;
}

const API_ORIGIN = resolveApiOrigin(process.env.API_ORIGIN);

/** Static security headers. The CSP (per-request nonce) is set in src/proxy.ts. */
const SECURITY_HEADERS = [
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "no-referrer" },
  {
    key: "Permissions-Policy",
    value: "camera=(), microphone=(), geolocation=(), payment=(), usb=(), browsing-topics=()",
  },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Cross-Origin-Opener-Policy", value: "same-origin" },
];

const nextConfig: NextConfig = {
  output: "standalone",
  poweredByHeader: false,
  reactStrictMode: true,
  // `next dev` would otherwise write an AGENTS.md into the project.
  agentRules: false,
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API_ORIGIN}/api/:path*` }];
  },
  async headers() {
    return [{ source: "/:path*", headers: SECURITY_HEADERS }];
  },
};

export default withNextIntl(nextConfig);
