/**
 * Attribution data (src/content/attribution.json), generated from data_pipeline/sources/registry.yaml.
 * Validated at render time: an entry without an http(s) homepage and licence evidence is not shown.
 */

import { asArray, asHttpUrl, asInt, asString, isIsoDate, isRecord, uniqueBy } from "@/lib/validate";

export interface AttributionLicense {
  readonly id: string;
  readonly name: string;
  readonly evidenceUrl: string;
  readonly attribution: string;
  readonly conditions: readonly string[];
  readonly verifiedOn: string | null;
}

export interface AttributionSource {
  readonly id: string;
  readonly name: string;
  readonly publisher: string;
  readonly homepage: string;
  readonly languages: readonly string[];
  readonly trustTier: number | null;
  readonly license: AttributionLicense;
}

export interface Attribution {
  readonly generatedOn: string | null;
  readonly sources: readonly AttributionSource[];
}

/** A real calendar date only: an impossible one would throw when the page formats it (review T11). */
function isoDate(value: unknown): string | null {
  return isIsoDate(value) ? value : null;
}

function strings(value: unknown, max: number): readonly string[] {
  return (asArray(value) ?? []).map((item) => asString(item, max)).filter((item): item is string => item !== null);
}

function parseLicense(raw: unknown): AttributionLicense | null {
  if (!isRecord(raw)) return null;
  const id = asString(raw.id, 100);
  const name = asString(raw.name, 300);
  const evidenceUrl = asHttpUrl(raw.evidence_url);
  if (!id || !name || !evidenceUrl) return null;
  return {
    id,
    name,
    evidenceUrl,
    attribution: asString(raw.attribution, 500) ?? "",
    conditions: strings(raw.conditions, 1000).slice(0, 20),
    verifiedOn: isoDate(raw.verified_on),
  };
}

function parseSource(raw: unknown): AttributionSource | null {
  if (!isRecord(raw)) return null;
  const id = asString(raw.id, 100);
  const name = asString(raw.name, 300);
  const publisher = asString(raw.publisher, 300);
  const homepage = asHttpUrl(raw.homepage);
  const license = parseLicense(raw.license);
  if (!id || !name || !publisher || !homepage || !license) return null;
  return { id, name, publisher, homepage, languages: strings(raw.languages, 5), trustTier: asInt(raw.trust_tier, 1, 5), license };
}

/**
 * A short, varied selection for the landing page: the first source of each publisher, in file
 * order, at most `max`. The full list lives on the Sources page.
 */
export function featuredSources(sources: readonly AttributionSource[], max: number): readonly AttributionSource[] {
  const publishers = new Set<string>();
  const featured: AttributionSource[] = [];
  for (const source of sources) {
    if (featured.length >= max) break;
    if (publishers.has(source.publisher)) continue;
    publishers.add(source.publisher);
    featured.push(source);
  }
  return featured;
}

export function parseAttribution(raw: unknown): Attribution {
  if (!isRecord(raw) || !Array.isArray(raw.sources)) return { generatedOn: null, sources: [] };
  const sources = raw.sources.map(parseSource).filter((s): s is AttributionSource => s !== null);
  return { generatedOn: isoDate(raw.generated_on), sources: uniqueBy(sources, (s) => s.id) };
}
