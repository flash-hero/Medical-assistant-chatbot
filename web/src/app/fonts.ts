import localFont from "next/font/local";

/**
 * Self-hosted at build time through next/font: no runtime request to any third party.
 * Atkinson Hyperlegible Next (Braille Institute, OFL) was designed for low-vision readers; its
 * Latin subset covers French (including œ). Readex Pro (OFL) is an Arabic family drawn for
 * readability, with a matching humanist rhythm. The stack falls back per glyph, so Latin text
 * always uses Atkinson and Arabic text uses Readex Pro, in every locale.
 */
export const latinFont = localFont({
  src: "../../node_modules/@fontsource-variable/atkinson-hyperlegible-next/files/atkinson-hyperlegible-next-latin-wght-normal.woff2",
  variable: "--font-latin",
  weight: "200 800",
  style: "normal",
  display: "swap",
  preload: true,
  fallback: ["ui-sans-serif", "system-ui", "Segoe UI", "Arial"],
  adjustFontFallback: "Arial",
});

export const arabicFont = localFont({
  src: "../../node_modules/@fontsource-variable/readex-pro/files/readex-pro-arabic-wght-normal.woff2",
  variable: "--font-arabic",
  weight: "160 700",
  style: "normal",
  display: "swap",
  preload: true,
  fallback: ["Segoe UI", "Tahoma", "Arial"],
  adjustFontFallback: false,
});
