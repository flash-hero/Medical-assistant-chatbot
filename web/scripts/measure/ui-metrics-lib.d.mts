/** Types for ui-metrics-lib.mjs (unit-tested in tests/unit/ui-metrics.test.ts). */
import type { MetricRecord } from "./metrics-types.d.mts";

export interface LighthouseRun {
  readonly url: string;
  readonly form_factor: string;
  readonly scores: Readonly<Record<"performance" | "accessibility" | "best-practices" | "seo", number>>;
}

export interface RouteJs {
  readonly route: string;
  readonly scripts: number;
  readonly raw_kb: number;
  readonly gzip_kb: number;
}

export function lighthouseRecords(lh: { readonly measured_at: string; readonly runs: readonly LighthouseRun[] }): MetricRecord[];
export function routeJsRecords(routeJs: { readonly measured_at: string; readonly routes: readonly RouteJs[] }): MetricRecord[];
