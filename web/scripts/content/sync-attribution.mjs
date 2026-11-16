#!/usr/bin/env node
/**
 * Regenerate src/content/attribution.json (the schema read by src/lib/attribution.ts) from the data
 * track's outputs, which this script only reads:
 *   - docs/sources/attribution.json: the ACTIVE sources and their credit lines (the set shown),
 *   - data_pipeline/sources/registry.yaml: licence id, evidence URL, verification date, conditions,
 *     trust tier and reuse mode for each of them.
 * A listed source without an active registry entry and licence evidence is dropped, with a warning.
 *
 *   node scripts/content/sync-attribution.mjs [--check]   (--check: exit 1 if the file is out of date)
 */
import { readFileSync } from "node:fs";
import { parse } from "yaml";
import { WEB_ROOT, writeJsonAtomic } from "../measure/lib.mjs";

const REPO = `${WEB_ROOT}../`;
const LISTED = `${REPO}docs/sources/attribution.json`;
const REGISTRY = `${REPO}data_pipeline/sources/registry.yaml`;
const OUT = `${WEB_ROOT}src/content/attribution.json`;
const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;

function isoDate(value) {
  const text = value instanceof Date ? value.toISOString().slice(0, 10) : String(value ?? "");
  return ISO_DATE.test(text) ? text : null;
}

/** Merge one listed source with its registry record; null when it may not be shown. */
function mergeSource(listed, record) {
  const license = record?.license;
  if (!record || record.status !== "active" || !license?.evidence_url) return null;
  return {
    id: listed.id,
    name: listed.name,
    publisher: listed.publisher,
    homepage: listed.homepage,
    languages: listed.languages ?? record.languages ?? [],
    trust_tier: record.trust_tier ?? null,
    reuse_mode: record.reuse_mode ?? null,
    license: {
      id: license.id,
      name: listed.license_name ?? license.name,
      evidence_url: license.evidence_url,
      attribution: listed.attribution ?? license.attribution ?? "",
      conditions: license.conditions ?? [],
      verified_on: isoDate(license.verified_on),
    },
  };
}

function build() {
  const listed = JSON.parse(readFileSync(LISTED, "utf8"));
  const registry = parse(readFileSync(REGISTRY, "utf8"));
  const records = new Map((registry.sources ?? []).map((s) => [s.id, s]));
  const sources = [];
  for (const entry of listed) {
    const merged = mergeSource(entry, records.get(entry.id));
    if (merged) sources.push(merged);
    else console.warn(`skipped ${entry.id}: no active registry entry with licence evidence`);
  }
  const dates = sources.map((s) => s.license.verified_on).filter(Boolean).sort();
  return {
    version: 1,
    generated_on: dates.at(-1) ?? null,
    generated_from: "docs/sources/attribution.json + data_pipeline/sources/registry.yaml (web/scripts/content/sync-attribution.mjs)",
    sources,
  };
}

const next = build();
if (process.argv.includes("--check")) {
  const current = readFileSync(OUT, "utf8");
  const fresh = `${JSON.stringify(next, null, 2)}\n`;
  if (current !== fresh) {
    console.error("src/content/attribution.json is out of date: run node scripts/content/sync-attribution.mjs");
    process.exit(1);
  }
} else {
  writeJsonAtomic(OUT, next);
  console.log(`wrote ${next.sources.length} sources to ${OUT}`);
}
