/**
 * Ausculta brand SVG builders. Every output is a self-contained SVG with outlined text (no font needed)
 * and colours resolved from src/styles/tokens.css, so the files stay in sync with the app.
 */
import { DOT, DOT_SMALL, GRID, RIM_PATH, RIM_PATH_SMALL } from "../../../src/components/brand/mark-geometry.ts";
import { FONTS, inkBounds, outlineText } from "./outline.mjs";

const r2 = (n) => Math.round(n * 100) / 100;

/** The mark's own drawing in grid units (32 x 32), as path data for one fill. */
export function markShapes({ small = false } = {}) {
  const dot = small ? DOT_SMALL : DOT;
  const rim = small ? RIM_PATH_SMALL : RIM_PATH;
  const circle = `M${dot.cx + dot.r} ${dot.cy}A${dot.r} ${dot.r} 0 1 0 ${dot.cx - dot.r} ${dot.cy}A${dot.r} ${dot.r} 0 1 0 ${dot.cx + dot.r} ${dot.cy}Z`;
  return { rim, dot: circle };
}

/** <g> drawing the mark at (x, y) with side `size`, in `color`. */
export function markGroup({ x = 0, y = 0, size = GRID, color, small = false }) {
  const { rim, dot } = markShapes({ small });
  const scale = r2(size / GRID);
  return (
    `<g transform="translate(${r2(x)} ${r2(y)}) scale(${scale})" fill="${color}">` +
    `<path fill-rule="evenodd" d="${rim}"/><path d="${dot}"/></g>`
  );
}

export function svgDoc({ width, height, title, body, extraHead = "" }) {
  return (
    `<svg xmlns="http://www.w3.org/2000/svg" width="${r2(width)}" height="${r2(height)}" ` +
    `viewBox="0 0 ${r2(width)} ${r2(height)}" role="img" aria-label="${title}">` +
    `<title>${title}</title>${extraHead}${body}</svg>\n`
  );
}

export const WORDMARKS = Object.freeze({
  latin: { text: "Ausculta", font: FONTS.latin, weight: 700, tracking: -0.012, direction: "ltr", label: "Ausculta" },
  arabic: { text: "أوسكولتا", font: FONTS.arabic, weight: 600, tracking: 0, direction: "rtl", label: "أوسكولتا (Ausculta)" },
});

/** Outline a wordmark at font size `size`, trimmed to its ink with `pad` px around it. */
export function wordmarkOutline(script, size = 100, pad = 0) {
  const spec = WORDMARKS[script];
  const out = outlineText(spec.text, { font: spec.font, weight: spec.weight, size, tracking: spec.tracking, direction: spec.direction });
  const ink = inkBounds(out.d);
  return {
    d: out.d,
    width: r2(ink.maxX - ink.minX + 2 * pad),
    height: r2(ink.maxY - ink.minY + 2 * pad),
    dx: r2(pad - ink.minX),
    dy: r2(pad - ink.minY),
    baseline: r2(out.ascent - ink.minY + pad),
    capTop: pad,
    label: spec.label,
  };
}

export function wordmarkSvg(script, color) {
  const w = wordmarkOutline(script, 100, 4);
  const body = `<path fill="${color}" transform="translate(${w.dx} ${w.dy})" d="${w.d}"/>`;
  return svgDoc({ width: w.width, height: w.height, title: w.label, body });
}

/**
 * Horizontal lockup: mark at the reading start (left for Latin, right for Arabic), sized to 1.3x the
 * height from the top of the letters to the baseline, and centred on that band.
 */
export function lockupSvg(script, { markColor, textColor }) {
  const w = wordmarkOutline(script, 100, 0);
  const band = w.baseline; // ink top (0) to baseline
  const markSize = r2(band * 1.3 * (GRID / 27.5)); // the mark's ink spans ~27.5 of its 32 grid units
  const gap = r2(markSize * 0.22);
  const pad = 6;
  const markY = r2(pad + band / 2 - markSize * (15.75 / GRID)); // ink centre of the mark is ~15.75
  const height = r2(Math.max(w.height, markY + markSize - pad) + 2 * pad);
  const width = r2(markSize + gap + w.width + 2 * pad);
  const latin = script === "latin";
  const markX = latin ? pad : r2(width - pad - markSize);
  const textX = latin ? r2(pad + markSize + gap) : pad;
  const body =
    markGroup({ x: markX, y: markY, size: markSize, color: markColor }) +
    `<path fill="${textColor}" transform="translate(${r2(textX + w.dx)} ${r2(pad + w.dy)})" d="${w.d}"/>`;
  return svgDoc({ width, height, title: w.label, body });
}

/** Square mark with a little air, for avatars and standalone use. */
export function markSvg(color, { small = false, title = "Ausculta" } = {}) {
  return svgDoc({ width: GRID, height: GRID, title, body: markGroup({ color, small }) });
}

/** Favicon: the heavier small drawing, recoloured for dark browser chrome through a media query. */
export function faviconSvg(light, dark) {
  const head = `<style>.m{fill:${light}}@media (prefers-color-scheme:dark){.m{fill:${dark}}}</style>`;
  const { rim, dot } = markShapes({ small: true });
  const body = `<g class="m"><path fill-rule="evenodd" d="${rim}"/><path d="${dot}"/></g>`;
  return svgDoc({ width: GRID, height: GRID, title: "Ausculta", body, extraHead: head });
}

/**
 * App icon: full-bleed brand square, mark in the on-brand colour inside the maskable safe zone
 * (a centred circle of 80% diameter), so platforms may crop it to any shape.
 */
export function appIconSvg({ background, foreground, size = 512, markRatio = 0.56 }) {
  const markSize = size * markRatio;
  const offset = (size - markSize) / 2;
  const nudge = size * 0.012; // the tail sits low-left; shift up-right to centre the ink optically
  const body =
    `<rect width="${size}" height="${size}" fill="${background}"/>` +
    markGroup({ x: offset + nudge, y: offset - nudge, size: markSize, color: foreground });
  return svgDoc({ width: size, height: size, title: "Ausculta", body });
}
