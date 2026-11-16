import type { Metadata } from "next";
import { LOCALES, type Locale } from "@/i18n/routing";

/** Public origin, used only for absolute metadata URLs (canonical, hreflang). */
function resolveSiteUrl(raw: string | undefined): URL {
  try {
    const url = new URL(raw?.trim() || "http://localhost:3000");
    return url.protocol === "https:" || url.protocol === "http:" ? url : new URL("http://localhost:3000");
  } catch {
    return new URL("http://localhost:3000");
  }
}

export const SITE_URL = resolveSiteUrl(process.env.SITE_URL);

export type SitePath = "/" | "/chat" | "/sources" | "/about";

/** Canonical + hreflang alternates for one route in every locale. */
export function alternatesFor(locale: Locale, path: SitePath): Metadata["alternates"] {
  const suffix = path === "/" ? "" : path;
  const languages = Object.fromEntries(LOCALES.map((l) => [l, `/${l}${suffix}`]));
  return { canonical: `/${locale}${suffix}`, languages: { ...languages, "x-default": `/en${suffix}` } };
}

export const MAX_MESSAGE_CHARS = 2000;
