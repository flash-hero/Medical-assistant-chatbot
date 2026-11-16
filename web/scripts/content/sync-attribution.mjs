#!/usr/bin/env node
/**
 * Regenerate src/content/attribution.json (the schema read by src/lib/attribution.ts) from the data
 * track's outputs, which this script only reads:
 *   - docs/sources/attribution.json: the ACTIVE sources and their credit lines (the set shown),
 *   - data_pipeline/sources/registry.yaml: licence id, evidence URL, verification date, conditions,
 *     trust tier and reuse mode for each of them.
 * A listed source without an active registry entry and licence evidence is dropped, with a warning.
 * Merge rules: scripts/content/attribution-lib.mjs.
 *
 *   node scripts/content/sync-attribution.mjs [--check]   (--check: exit 1 if the file is out of date)
 */
import { readFileSync } from "node:fs";
import { parse } from "yaml";
import { WEB_ROOT, writeJsonAtomic } from "../measure/lib.mjs";
import { buildAttribution } from "./attribution-lib.mjs";

const REPO = `${WEB_ROOT}../`;
const LISTED = `${REPO}docs/sources/attribution.json`;
const REGISTRY = `${REPO}data_pipeline/sources/registry.yaml`;
const OUT = `${WEB_ROOT}src/content/attribution.json`;

function readInputs() {
  try {
    return { listed: JSON.parse(readFileSync(LISTED, "utf8")), registry: parse(readFileSync(REGISTRY, "utf8")) };
  } catch (error) {
    throw new Error(`cannot read the data track's attribution inputs: ${error instanceof Error ? error.message : error}`);
  }
}

function main() {
  const { listed, registry } = readInputs();
  const { attribution, dropped } = buildAttribution(listed, registry);
  for (const id of dropped) console.warn(`skipped ${id}: no active registry entry with licence evidence`);
  if (process.argv.includes("--check")) {
    const fresh = `${JSON.stringify(attribution, null, 2)}\n`;
    if (readFileSync(OUT, "utf8") !== fresh) {
      console.error("src/content/attribution.json is out of date: run node scripts/content/sync-attribution.mjs");
      process.exit(1);
    }
    console.log(`up to date (${attribution.sources.length} sources)`);
    return;
  }
  writeJsonAtomic(OUT, attribution);
  console.log(`wrote ${attribution.sources.length} sources to ${OUT}`);
}

try {
  main();
} catch (error) {
  console.error(error instanceof Error ? error.message : error);
  process.exit(1);
}
