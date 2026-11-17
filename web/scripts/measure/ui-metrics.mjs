#!/usr/bin/env node
/**
 * Turn the UI measurements into release-gate metric records (format: evals/gates_eval.py, names:
 * evals/gates.yaml "ui.*") and write them to {AUSCULTA_DATA_ROOT}/reports/ui.metrics.json.
 *
 * Inputs (each optional; a missing input means its gates stay MISSING, never invented):
 *   --e2e         Playwright JSON report      (default test-results/e2e-report.json)
 *   --route-js    scripts/measure/route-js.mjs output   (default test-results/measure/route-js.json)
 *   --lighthouse  scripts/measure/lighthouse.mjs output (default test-results/measure/lighthouse.json)
 *
 *   node scripts/measure/ui-metrics.mjs [--out <file>] [--dry-run]
 */
import { existsSync, readFileSync } from "node:fs";
import { argValue, MEASURE_DIR, WEB_ROOT, writeJsonAtomic } from "./lib.mjs";
import { lighthouseRecords, routeJsRecords } from "./ui-metrics-lib.mjs";
import { e2eRecords, summariseE2e } from "./e2e-summary.mjs";

const DATA_ROOT = process.env.AUSCULTA_DATA_ROOT ?? "C:/dev/ausculta-data";
const OUT = argValue("out", `${DATA_ROOT}/reports/ui.metrics.json`);

function readJson(path) {
  if (!existsSync(path)) {
    console.warn(`missing input: ${path}`);
    return null;
  }
  return JSON.parse(readFileSync(path, "utf8"));
}

const now = new Date().toISOString();
const e2e = readJson(argValue("e2e", `${WEB_ROOT}test-results/e2e-report.json`));
const routeJs = readJson(argValue("route-js", `${MEASURE_DIR}route-js.json`));
const lh = readJson(argValue("lighthouse", `${MEASURE_DIR}lighthouse.json`));

const records = [
  ...(e2e ? e2eRecords(summariseE2e(e2e), now) : []),
  ...(lh ? lighthouseRecords(lh) : []),
  ...(routeJs ? routeJsRecords(routeJs) : []),
];

for (const r of records) console.log(`${r.metric} = ${r.value} ${JSON.stringify(r.labels)}`);
if (process.argv.includes("--dry-run")) process.exit(0);
writeJsonAtomic(OUT, records);
console.log(`wrote ${records.length} records to ${OUT}`);
