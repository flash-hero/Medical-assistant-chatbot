#!/usr/bin/env node
/**
 * Builds every Ausculta brand file into public/brand (and public/favicon.ico) from one source:
 * the mark geometry (src/components/brand/mark-geometry.ts), the self-hosted fonts and the colour
 * tokens (src/styles/tokens.css). Re-run after changing any of them:  npm run brand
 */
import { mkdirSync, readFileSync, renameSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { parseLightDarkTokens, parseOklch, toHex } from "../lib/oklch.mjs";
import { appIconSvg, faviconSvg, lockupSvg, markSvg, wordmarkSvg } from "./lib/brand-svg.mjs";
import { OG_SIZE, ogSvg } from "./lib/og.mjs";
import { openRasterizer, pngsToIco } from "./lib/raster.mjs";

const ROOT = fileURLToPath(new URL("../../", import.meta.url));
const OUT = `${ROOT}public/brand/`;

function writeAtomic(path, data) {
  const temp = `${path}.${process.pid}.tmp`;
  writeFileSync(temp, data);
  renameSync(temp, path);
}

function palette() {
  const tokens = parseLightDarkTokens(readFileSync(`${ROOT}src/styles/tokens.css`, "utf8"));
  const hex = (name, theme) => toHex(tokens[name][theme].rgb);
  return {
    brand: hex("brand", "light"),
    brandOnDark: hex("brand", "dark"),
    ink: hex("ink", "light"),
    inkOnDark: hex("ink", "dark"),
    onBrand: hex("on-brand", "light"),
    ogBackground: toHex(parseOklch("oklch(0.3 0.06 168)")),
    ogSoft: toHex(parseOklch("oklch(0.9 0.025 165)")),
    black: "#000000",
    white: "#ffffff",
  };
}

/** [name, svg] for every vector file, in light / on-dark / mono variants. */
function vectorFiles(c) {
  const variants = [
    ["", c.brand, c.ink],
    ["-on-dark", c.brandOnDark, c.inkOnDark],
    ["-mono-black", c.black, c.black],
    ["-mono-white", c.white, c.white],
  ];
  const files = [["ausculta-favicon.svg", faviconSvg(c.brand, c.brandOnDark)]];
  for (const [suffix, markColor, textColor] of variants) {
    files.push([`ausculta-mark${suffix}.svg`, markSvg(markColor)]);
    for (const script of ["latin", "arabic"]) {
      files.push([`ausculta-wordmark-${script}${suffix}.svg`, wordmarkSvg(script, textColor)]);
      files.push([`ausculta-lockup-${script}${suffix}.svg`, lockupSvg(script, { markColor, textColor })]);
    }
  }
  files.push(["ausculta-app-icon.svg", appIconSvg({ background: c.brand, foreground: c.onBrand })]);
  files.push(["ausculta-og.svg", ogSvg({ background: c.ogBackground, mark: c.brandOnDark, ink: c.white, soft: c.ogSoft })]);
  return files;
}

async function rasterFiles(raster, c, vectors) {
  const icon = appIconSvg({ background: c.brand, foreground: c.onBrand });
  const maskable = appIconSvg({ background: c.brand, foreground: c.onBrand, markRatio: 0.5 });
  const pngs = [
    ["ausculta-app-icon-180.png", await raster.svgToPng(icon, 180, 180)],
    ["ausculta-app-icon-192.png", await raster.svgToPng(icon, 192, 192)],
    ["ausculta-app-icon-512.png", await raster.svgToPng(icon, 512, 512)],
    ["ausculta-app-icon-maskable-512.png", await raster.svgToPng(maskable, 512, 512)],
    ["ausculta-og.png", await raster.svgToPng(vectors.get("ausculta-og.svg"), OG_SIZE.width, OG_SIZE.height)],
  ];
  // The favicon's light drawing on a transparent ground; 16/32/48 cover tabs, taskbars and shortcuts.
  const favicon = markSvg(c.brand, { small: true });
  const sizes = [16, 32, 48];
  const icoImages = await Promise.all(sizes.map(async (size) => ({ size, png: await raster.svgToPng(favicon, size, size) })));
  return { pngs, ico: pngsToIco(icoImages) };
}

async function main() {
  mkdirSync(OUT, { recursive: true });
  const colours = palette();
  const vectors = new Map(vectorFiles(colours));
  for (const [name, svg] of vectors) writeAtomic(`${OUT}${name}`, svg);
  const raster = await openRasterizer();
  try {
    const { pngs, ico } = await rasterFiles(raster, colours, vectors);
    for (const [name, png] of pngs) writeAtomic(`${OUT}${name}`, png);
    writeAtomic(`${ROOT}public/favicon.ico`, ico);
    console.log(`brand: ${vectors.size} SVG, ${pngs.length} PNG, favicon.ico -> public/brand`);
  } finally {
    await raster.close();
  }
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
