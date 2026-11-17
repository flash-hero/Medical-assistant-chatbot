#!/usr/bin/env node
/**
 * WCAG 2.2 contrast check of the design tokens in both themes. Exits 1 if any pair is below its minimum.
 * Usage: node scripts/check-contrast.mjs [--markdown]
 */
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { contrast, parseLightDarkTokens, toHex } from "./lib/oklch.mjs";

const TOKENS = fileURLToPath(new URL("../src/styles/tokens.css", import.meta.url));

/** [foreground, background, minimum ratio, usage] */
const PAIRS = [
  ["ink", "bg", 4.5, "Body text"],
  ["ink", "surface", 4.5, "Body text on cards"],
  ["ink-2", "bg", 4.5, "Secondary text"],
  ["ink-2", "surface", 4.5, "Secondary text on cards"],
  ["ink-2", "surface-2", 4.5, "Secondary text on tinted bands"],
  ["brand", "bg", 4.5, "Links and brand text"],
  ["brand", "surface", 4.5, "Links on cards"],
  ["brand", "surface-2", 4.5, "Links on tinted bands"],
  ["on-brand", "brand", 4.5, "Primary button label"],
  ["brand-ink", "brand-soft", 4.5, "Citation chip"],
  ["danger-ink", "danger-soft", 4.5, "Emergency banner text"],
  ["on-danger", "danger", 4.5, "Emergency call button"],
  ["warn-ink", "warn-soft", 4.5, "Demo and notice text"],
  ["focus", "bg", 3, "Focus ring"],
  ["focus", "surface", 3, "Focus ring on cards"],
  ["line-strong", "bg", 3, "Input borders (non-text UI)"],
  ["line-strong", "surface", 3, "Input borders on cards"],
  ["danger", "bg", 3, "Emergency border and icon"],
];

const tokens = parseLightDarkTokens(readFileSync(TOKENS, "utf8"));
const markdown = process.argv.includes("--markdown");
const rows = [];
let failures = 0;

for (const [fg, bg, min, usage] of PAIRS) {
  if (!tokens[fg] || !tokens[bg]) throw new Error(`missing token pair ${fg}/${bg}`);
  const ratios = ["light", "dark"].map((theme) => contrast(tokens[fg][theme].rgb, tokens[bg][theme].rgb));
  const ok = ratios.every((r) => r >= min);
  if (!ok) failures += 1;
  rows.push({ fg, bg, min, usage, light: ratios[0].toFixed(2), dark: ratios[1].toFixed(2), ok });
}

if (markdown) {
  console.log("| Foreground | Background | Use | Light | Dark | Minimum |");
  console.log("|---|---|---|---|---|---|");
  for (const r of rows) console.log(`| \`--${r.fg}\` | \`--${r.bg}\` | ${r.usage} | ${r.light}:1 | ${r.dark}:1 | ${r.min}:1 |`);
  console.log("\n| Token | Light | Dark |\n|---|---|---|");
  for (const [name, t] of Object.entries(tokens)) {
    console.log(`| \`--${name}\` | \`${t.light.css}\` ${toHex(t.light.rgb)} | \`${t.dark.css}\` ${toHex(t.dark.rgb)} |`);
  }
} else {
  for (const r of rows) {
    console.log(`${r.ok ? "PASS" : "FAIL"} ${r.fg} on ${r.bg}: light ${r.light}, dark ${r.dark} (min ${r.min}) ${r.usage}`);
  }
}
console.log(`\n${rows.length - failures}/${rows.length} pairs pass.`);
process.exit(failures === 0 ? 0 : 1);
