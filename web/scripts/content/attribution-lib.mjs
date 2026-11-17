/**
 * Pure merge rules behind scripts/content/sync-attribution.mjs (unit-tested in
 * tests/unit/attribution-sync.test.ts). Input: the data track's listed sources
 * (docs/sources/attribution.json) and its parsed registry (data_pipeline/sources/registry.yaml).
 */
const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;
export const GENERATED_FROM =
  "docs/sources/attribution.json + data_pipeline/sources/registry.yaml (web/scripts/content/sync-attribution.mjs)";

/** YAML parses bare dates as Date objects; keep only YYYY-MM-DD. */
export function isoDate(value) {
  const text = value instanceof Date ? value.toISOString().slice(0, 10) : String(value ?? "");
  return ISO_DATE.test(text) ? text : null;
}

/** Merge one listed source with its registry record; null when it may not be shown. */
export function mergeSource(listed, record) {
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

/**
 * Build the web copy. Returns the file content and the ids that were dropped (no active registry
 * entry with licence evidence), so the caller can warn about them.
 */
export function buildAttribution(listed, registry) {
  if (!Array.isArray(listed)) throw new TypeError("docs/sources/attribution.json must be a JSON array");
  const records = new Map((registry?.sources ?? []).map((s) => [s.id, s]));
  const sources = [];
  const dropped = [];
  for (const entry of listed) {
    const merged = mergeSource(entry, records.get(entry.id));
    if (merged) sources.push(merged);
    else dropped.push(String(entry.id));
  }
  const dates = sources
    .map((s) => s.license.verified_on)
    .filter(Boolean)
    .sort();
  return {
    attribution: { version: 1, generated_on: dates.at(-1) ?? null, generated_from: GENERATED_FROM, sources },
    dropped,
  };
}
