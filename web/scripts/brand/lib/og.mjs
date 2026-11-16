/** Open Graph card (1200 x 630): lockup, Arabic wordmark, tagline, languages. Text is outlined. */
import { markGroup, svgDoc, wordmarkOutline } from "./brand-svg.mjs";
import { FONTS, outlineText } from "./outline.mjs";

export const OG_SIZE = Object.freeze({ width: 1200, height: 630 });
const LEFT = 96;

/** One run of outlined text with its baseline at (x, baselineY); returns { svg, width }. */
function run(text, { font, weight, size, x, baselineY, color, direction = "ltr" }) {
  const out = outlineText(text, { font, weight, size, direction });
  const svg = `<path fill="${color}" transform="translate(${x} ${baselineY - out.ascent})" d="${out.d}"/>`;
  return { svg, width: out.width };
}

function rings(color) {
  const cx = 1110;
  const cy = 315;
  return [130, 215, 300, 385, 470]
    .map((r, i) => `<circle cx="${cx}" cy="${cy}" r="${r}" fill="none" stroke="${color}" stroke-width="2" opacity="${(0.22 - i * 0.04).toFixed(2)}"/>`)
    .join("");
}

function header({ mark, ink }) {
  const markSize = 132;
  const w = wordmarkOutline("latin", 120, 0);
  const markY = 112;
  const textX = LEFT + markSize + 30;
  const textY = markY + markSize / 2 - w.baseline / 2 - 6;
  return (
    markGroup({ x: LEFT - 6, y: markY, size: markSize, color: mark }) +
    `<path fill="${ink}" transform="translate(${textX + w.dx} ${textY + w.dy})" d="${w.d}"/>`
  );
}

function languages(color) {
  const size = 28;
  const baselineY = 556;
  const latin = run("English · Français · ", { font: FONTS.latin, weight: 500, size, x: LEFT, baselineY, color });
  const arabic = run("العربية", { font: FONTS.arabic, weight: 500, size, x: LEFT + latin.width, baselineY, color, direction: "rtl" });
  return latin.svg + arabic.svg;
}

export function ogSvg({ background, mark, ink, soft }) {
  const { width, height } = OG_SIZE;
  const ar = wordmarkOutline("arabic", 58, 0);
  const tagline = ["Health information that listens,", "and shows its sources."]
    .map((line, i) => run(line, { font: FONTS.latin, weight: 400, size: 46, x: LEFT, baselineY: 414 + i * 58, color: soft }).svg)
    .join("");
  const body =
    `<rect width="${width}" height="${height}" fill="${background}"/>` +
    rings(mark) +
    header({ mark, ink }) +
    `<path fill="${mark}" transform="translate(${LEFT + ar.dx} ${262 + ar.dy})" d="${ar.d}" opacity="0.9"/>` +
    tagline +
    languages(mark);
  return svgDoc({ width, height, title: "Ausculta: health information that listens, and shows its sources", body });
}
