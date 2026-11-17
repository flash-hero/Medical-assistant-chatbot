#!/usr/bin/env node
/**
 * Lighthouse (performance, accessibility, best practices, SEO) on the production build in front of
 * the mock API (both started automatically when not running). Mobile uses Lighthouse's default
 * simulated throttling (Moto G Power, slow 4G); desktop uses its desktop preset.
 *
 *   node scripts/measure/lighthouse.mjs [--port 3100] [--pages /en,/en/chat] [--form-factors mobile,desktop]
 *
 * Writes test-results/measure/lighthouse.json (scores per run) and one HTML report per run.
 */
import * as chromeLauncher from "chrome-launcher";
import { mkdirSync, writeFileSync } from "node:fs";
import lighthouse, { desktopConfig } from "lighthouse";
import { argValue, ensureServers, MEASURE_DIR, writeJsonAtomic } from "./lib.mjs";

const PORT = Number(argValue("port", "3100"));
const PAGES = argValue("pages", "/en,/fr,/ar,/en/chat,/fr/chat,/ar/chat").split(",");
const FORM_FACTORS = argValue("form-factors", "mobile,desktop").split(",");
const CATEGORIES = ["performance", "accessibility", "best-practices", "seo"];
const CHROME_FLAGS = ["--headless=new", "--no-first-run", "--disable-extensions"];

function scoresOf(lhr) {
  return Object.fromEntries(CATEGORIES.map((id) => [id, Math.round((lhr.categories[id]?.score ?? 0) * 100)]));
}

function failedAudits(lhr, category) {
  const refs = lhr.categories[category]?.auditRefs ?? [];
  return refs
    .filter((ref) => ref.weight > 0 && lhr.audits[ref.id]?.score !== null && lhr.audits[ref.id]?.score < 1)
    .map((ref) => ({ id: ref.id, score: lhr.audits[ref.id].score, title: lhr.audits[ref.id].title }));
}

async function runOnce(port, url, formFactor) {
  const flags = { port, output: "html", logLevel: "error", onlyCategories: CATEGORIES };
  const result = await lighthouse(url, flags, formFactor === "desktop" ? desktopConfig : undefined);
  if (!result) throw new Error(`Lighthouse returned no result for ${url}`);
  const { lhr } = result;
  const name = `lighthouse-${formFactor}${new URL(url).pathname.replaceAll("/", "-")}.html`;
  writeFileSync(`${MEASURE_DIR}${name}`, result.report, "utf8");
  return {
    url: new URL(url).pathname,
    form_factor: formFactor,
    scores: scoresOf(lhr),
    metrics: {
      lcp_ms: Math.round(lhr.audits["largest-contentful-paint"]?.numericValue ?? 0),
      tbt_ms: Math.round(lhr.audits["total-blocking-time"]?.numericValue ?? 0),
      cls: Number((lhr.audits["cumulative-layout-shift"]?.numericValue ?? 0).toFixed(3)),
    },
    accessibility_failures: failedAudits(lhr, "accessibility"),
    performance_failures: failedAudits(lhr, "performance").slice(0, 8),
    report: name,
    runtime_error: lhr.runtimeError?.message ?? null,
  };
}

async function killChrome(chrome) {
  try {
    await chrome.kill();
  } catch (error) {
    // Windows can refuse to delete Chrome's temp profile right after exit; the scores are already saved.
    console.warn(`chrome cleanup: ${error instanceof Error ? error.message : error}`);
  }
}

mkdirSync(MEASURE_DIR, { recursive: true });
const { base, stop } = await ensureServers(PORT);
const runs = [];
try {
  for (const formFactor of FORM_FACTORS) {
    for (const page of PAGES) {
      const chrome = await chromeLauncher.launch({ chromeFlags: CHROME_FLAGS });
      try {
        const run = await runOnce(chrome.port, `${base}${page}`, formFactor);
        runs.push(run);
        console.log(`${formFactor} ${page}: ${JSON.stringify(run.scores)}`);
      } finally {
        await killChrome(chrome);
      }
    }
  }
  writeJsonAtomic(`${MEASURE_DIR}lighthouse.json`, { measured_at: new Date().toISOString(), base, runs });
} finally {
  stop();
}
