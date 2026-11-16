import createMiddleware from "next-intl/middleware";
import type { NextRequest } from "next/server";
import { routing } from "./i18n/routing";
import { buildCsp, createNonce } from "./lib/security/csp";

const intl = createMiddleware(routing);

export default function proxy(request: NextRequest) {
  const nonce = createNonce();
  const csp = buildCsp({ nonce, isDev: process.env.NODE_ENV === "development" });
  // next-intl copies the request headers into the rewritten request, so Next.js sees the nonce.
  request.headers.set("x-nonce", nonce);
  request.headers.set("Content-Security-Policy", csp);
  const response = intl(request);
  response.headers.set("Content-Security-Policy", csp);
  return response;
}

export const config = {
  matcher: [
    {
      // Everything except the API rewrite, Next internals, and files with an extension.
      source: "/((?!api|_next|_vercel|brand|.*\..*).*)",
      missing: [
        { type: "header", key: "next-router-prefetch" },
        { type: "header", key: "purpose", value: "prefetch" },
      ],
    },
  ],
};
