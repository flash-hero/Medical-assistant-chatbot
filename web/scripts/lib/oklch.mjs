/** OKLCH -> sRGB conversion (CSS Color 4) and WCAG 2 contrast. Out-of-gamut colours are clipped. */

function oklchToOklab(l, c, h) {
  const rad = (h * Math.PI) / 180;
  return [l, c * Math.cos(rad), c * Math.sin(rad)];
}

function oklabToLinearSrgb([L, a, b]) {
  const l = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3;
  const m = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3;
  const s = (L - 0.0894841775 * a - 1.291485548 * b) ** 3;
  return [
    4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
    -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
    -0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s,
  ];
}

const clip = (x) => Math.min(1, Math.max(0, x));

function gamma(x) {
  return x <= 0.0031308 ? 12.92 * x : 1.055 * x ** (1 / 2.4) - 0.055;
}

/** @returns {[number, number, number]} sRGB components in 0..1 */
export function oklchToSrgb(l, c, h) {
  return oklabToLinearSrgb(oklchToOklab(l, c, h)).map((x) => clip(gamma(x)));
}

export function toHex(rgb) {
  return `#${rgb.map((x) => Math.round(x * 255).toString(16).padStart(2, "0")).join("")}`;
}

function luminance(rgb) {
  const lin = rgb.map((x) => (x <= 0.04045 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4));
  return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2];
}

export function contrast(a, b) {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

const OKLCH = /oklch\(\s*([\d.]+)\s+([\d.]+)\s+([\d.]+)\s*\)/;

export function parseOklch(text) {
  const match = OKLCH.exec(text);
  if (!match) throw new Error(`not an oklch() colour: ${text}`);
  return oklchToSrgb(Number(match[1]), Number(match[2]), Number(match[3]));
}

/** Read `--name: light-dark(oklch(...), oklch(...))` pairs from a CSS file's text. */
export function parseLightDarkTokens(css) {
  const tokens = {};
  const decl = /--([a-z0-9-]+):\s*light-dark\((oklch\([^)]*\)),\s*(oklch\([^)]*\))\)/g;
  for (const m of css.matchAll(decl)) {
    tokens[m[1]] = { light: { css: m[2], rgb: parseOklch(m[2]) }, dark: { css: m[3], rgb: parseOklch(m[3]) } };
  }
  return tokens;
}
