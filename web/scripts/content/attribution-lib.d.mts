/** Types for attribution-lib.mjs (unit-tested in tests/unit/attribution-sync.test.ts). */
export interface ListedSource {
  readonly id: string;
  readonly name: string;
  readonly publisher: string;
  readonly homepage: string;
  readonly languages?: readonly string[];
  readonly license_name?: string;
  readonly attribution?: string;
}

export interface RegistryRecord {
  readonly id: string;
  readonly status?: string;
  readonly languages?: readonly string[];
  readonly trust_tier?: number;
  readonly reuse_mode?: string;
  readonly license?: {
    readonly id?: string;
    readonly name?: string;
    readonly evidence_url?: string;
    readonly attribution?: string;
    readonly conditions?: readonly string[];
    readonly verified_on?: string | Date;
  };
}

export interface WebAttributionSource {
  readonly id: string;
  readonly name: string;
  readonly publisher: string;
  readonly homepage: string;
  readonly languages: readonly string[];
  readonly trust_tier: number | null;
  readonly reuse_mode: string | null;
  readonly license: {
    readonly id: string | undefined;
    readonly name: string | undefined;
    readonly evidence_url: string;
    readonly attribution: string;
    readonly conditions: readonly string[];
    readonly verified_on: string | null;
  };
}

export const GENERATED_FROM: string;
export function isoDate(value: unknown): string | null;
export function mergeSource(listed: ListedSource, record: RegistryRecord | undefined): WebAttributionSource | null;
export function buildAttribution(
  listed: unknown,
  registry: { readonly sources?: readonly RegistryRecord[] } | null | undefined,
): {
  readonly attribution: { version: 1; generated_on: string | null; generated_from: string; sources: WebAttributionSource[] };
  readonly dropped: string[];
};
