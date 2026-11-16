#!/usr/bin/env node
/**
 * First-load JavaScript per route, gzip-compressed: every same-origin script the browser fetches
 * while loading the page until the network is idle (so chunks loaded right after hydration count
 * too), each compressed with zlib's default gzip level. Needs the production build and the mock API
 * (started automatically when not running).
 *
 *   node scripts/measure/route-js.mjs [--port 3100] [--routes /en/chat,/en] [--out test-results/measure/route-js.json]
 */
import { chromium } from "@playwright/test";
import { gzipSync } from "node:zlib";
import { argValue, ensureServers, MEASURE_DIR, writeJsonAtomic } from "./lib.mjs";

const PORT = Number(argValue("port", "3100"));
const ROUTES = argValue("routes", "/en/chat,/fr/chat,/ar/chat,/en").split(",");
const OUT = argValue("out", `${MEASURE_DIR}route-js.json`);
const KB = 1024;

async function measureRoute(browser, base, route) {
  const context = await browser.newContext();
  const page = await context.newPage();
  const origin = new URL(base).origin;
  const pending = [];
  const scripts = [];
  page.on("response", (response) => {
    const request = response.request();
    if (request.resourceType() !== "script" || new URL(request.url()).origin !== origin) return;
    pending.push(
      response.body().then((body) => {
        scripts.push({ url: new URL(request.url()).pathname, raw: body.length, gzip: gzipSync(body).length });
      }),
    );
  });
  await page.goto(`${base}${route}`, { waitUntil: "networkidle" });
  await Promise.all(pending);
  await context.close();
  const total = (key) => scripts.reduce((sum, s) => sum + s[key], 0);
  return {
    route,
    scripts: scripts.length,
    raw_kb: Number((total("raw") / KB).toFixed(1)),
    gzip_kb: Number((total("gzip") / KB).toFixed(1)),
    files: scripts.sort((a, b) => b.gzip - a.gzip),
  };
}

const { base, stop } = await ensureServers(PORT);
const browser = await chromium.launch();
try {
  const results = [];
  for (const route of ROUTES) results.push(await measureRoute(browser, base, route));
  writeJsonAtomic(OUT, { measured_at: new Date().toISOString(), base, routes: results });
  for (const r of results) console.log(`${r.route}: ${r.scripts} scripts, ${r.gzip_kb} kB gzip (${r.raw_kb} kB raw)`);
} finally {
  await browser.close();
  stop();
}
