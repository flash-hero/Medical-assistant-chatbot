/**
 * Attribution data (src/content/attribution.json), generated from data_pipeline/sources/registry.yaml.
 * Validated at render time: an entry without an http(s) homepage and licence evidence is not shown.
 */

import { asArray, asHttpUrl, asInt, asString, isRecord } from "@/lib/validate";

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

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;

function isoDate(value: unknown): string | null {
  const text = asString(value, 10);
  return text !== null && ISO_DATE.test(text) ? text : null;
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

export function parseAttribution(raw: unknown): Attribution {
  if (!isRecord(raw) || !Array.isArray(raw.sources)) return { generatedOn: null, sources: [] };
  const sources = raw.sources.map(parseSource).filter((s): s is AttributionSource => s !== null);
  return { generatedOn: isoDate(raw.generated_on), sources };
}
