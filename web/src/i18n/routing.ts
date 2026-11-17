import { defineRouting } from "next-intl/routing";

export const LOCALES = ["en", "fr", "ar"] as const;
export type Locale = (typeof LOCALES)[number];

export const routing = defineRouting({
  locales: LOCALES,
  defaultLocale: "en",
  localePrefix: "always",
  // No locale cookie: the URL is the single source of truth, and we set as few cookies as possible.
  localeCookie: false,
});

const RTL_LOCALES: ReadonlySet<Locale> = new Set(["ar"]);

export function isLocale(value: unknown): value is Locale {
  return typeof value === "string" && (LOCALES as readonly string[]).includes(value);
}

export function directionOf(locale: Locale): "ltr" | "rtl" {
  return RTL_LOCALES.has(locale) ? "rtl" : "ltr";
}
