/**
 * Text -> SVG outlines with fontkit (OpenType shaping, so Arabic joins correctly). Used only by the
 * brand build: shipped wordmarks never depend on a font being installed.
 */
import { fileURLToPath } from "node:url";
import * as fontkit from "fontkit";

const FONT_DIR = fileURLToPath(new URL("../../../node_modules/@fontsource-variable/", import.meta.url));

export const FONTS = Object.freeze({
  latin: `${FONT_DIR}atkinson-hyperlegible-next/files/atkinson-hyperlegible-next-latin-wght-normal.woff2`,
  arabic: `${FONT_DIR}readex-pro/files/readex-pro-arabic-wght-normal.woff2`,
});

/** Minimal point with the `copy()` fontkit's variation processor expects. */
class VPoint {
  constructor(onCurve, endContour, x, y) {
    Object.assign(this, { onCurve, endContour, x, y });
  }
  copy() {
    return new VPoint(this.onCurve, this.endContour, this.x, this.y);
  }
}

const phantoms = () => [0, 1, 2, 3].map(() => new VPoint(false, true, 0, 0));

/** gvar-varied copy of a pre-decoded WOFF2 glyph (advances come from HVAR, so phantoms stay zero). */
function variedDecode() {
  const base = this._font._transformedGlyphs[this.id];
  const processor = this._font._variationProcessor;
  if (!base || !processor || base.numberOfContours === 0) return base;
  if (this._varied) return this._varied;
  if (base.numberOfContours > 0) {
    const all = [...base.points.map((p) => p.copy()), ...phantoms()];
    processor.transformPoints(this.id, all);
    this._varied = { ...base, points: all.slice(0, -4) };
  } else {
    const all = [...base.components.map((c) => new VPoint(true, true, c.dx, c.dy)), ...phantoms()];
    processor.transformPoints(this.id, all);
    this._varied = { ...base, components: base.components.map((c, i) => ({ ...c, dx: all[i].x, dy: all[i].y })) };
  }
  return this._varied;
}

/**
 * fontkit 2.0.4 does not apply variations to WOFF2 glyphs (getVariation() re-parses the WOFF2 buffer
 * as TrueType and fails; WOFF2 glyphs skip gvar). So: decode the transformed glyf table at the default
 * instance, then set the coordinates and apply gvar deltas in a patched glyph decoder.
 */
function openFont(path, weight) {
  const font = fontkit.openSync(path);
  if (!font.fvar || !font.directory.tables.glyf?.transformed) return font;
  Object.defineProperty(font, "_variationProcessor", { value: null, configurable: true, writable: true });
  font._transformGlyfTable();
  delete font._variationProcessor;
  font.variationCoords = font.fvar.axis.map((axis) =>
    axis.axisTag.trim() === "wght" ? Math.min(axis.maxValue, Math.max(axis.minValue, weight)) : axis.defaultValue,
  );
  Object.getPrototypeOf(font.getGlyph(0))._decode = variedDecode;
  return font;
}

function round(n) {
  return Math.round(n * 100) / 100;
}

/** Serialise a fontkit path into absolute SVG commands, flipping y (font units are y-up). */
function pathToSvg(path, dx, scale, baseline) {
  const x = (v) => round(dx + v * scale);
  const y = (v) => round(baseline - v * scale);
  return path.commands
    .map(({ command, args }) => {
      switch (command) {
        case "moveTo":
          return `M${x(args[0])} ${y(args[1])}`;
        case "lineTo":
          return `L${x(args[0])} ${y(args[1])}`;
        case "quadraticCurveTo":
          return `Q${x(args[0])} ${y(args[1])} ${x(args[2])} ${y(args[3])}`;
        case "bezierCurveTo":
          return `C${x(args[0])} ${y(args[1])} ${x(args[2])} ${y(args[3])} ${x(args[4])} ${y(args[5])}`;
        case "closePath":
          return "Z";
        default:
          throw new Error(`unknown path command ${command}`);
      }
    })
    .join("");
}

/**
 * Outline `text` at `size` px. Returns { d, width, ascent, descent, bbox } in px with the baseline at
 * y = ascent, so the outline sits in a box of height ascent + descent starting at y = 0.
 * `tracking` is extra advance per glyph in em (negative tightens).
 */
export function outlineText(text, { font: fontPath, weight, size, tracking = 0, direction = "ltr" }) {
  const font = openFont(fontPath, weight);
  const scale = size / font.unitsPerEm;
  const run = font.layout(text, undefined, undefined, undefined, direction);
  const ascent = font.ascent * scale;
  const descent = -font.descent * scale;
  const parts = [];
  let pen = 0;
  run.glyphs.forEach((glyph, i) => {
    const pos = run.positions[i];
    const gx = pen + pos.xOffset * scale;
    const baseline = ascent - pos.yOffset * scale;
    parts.push(pathToSvg(glyph.path, gx, scale, baseline));
    pen += pos.xAdvance * scale + (i < run.glyphs.length - 1 ? tracking * size : 0);
  });
  const missing = run.glyphs.filter((g) => g.id === 0).length;
  if (missing > 0) throw new Error(`${missing} glyph(s) of "${text}" are missing from ${fontPath}`);
  return { d: parts.join(""), width: round(pen), ascent: round(ascent), descent: round(descent) };
}

/** Tight vertical bounds of the ink (not the font's line box), measured from the outline's points. */
export function inkBounds(d) {
  const nums = d.match(/-?\d+(?:\.\d+)?/g)?.map(Number) ?? [];
  const xs = nums.filter((_, i) => i % 2 === 0);
  const ys = nums.filter((_, i) => i % 2 === 1);
  return { minX: Math.min(...xs), maxX: Math.max(...xs), minY: Math.min(...ys), maxY: Math.max(...ys) };
}
