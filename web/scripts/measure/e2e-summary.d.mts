/** Types for e2e-summary.mjs (unit-tested in tests/unit/ui-metrics.test.ts). */
import type { MetricRecord } from "./metrics-types.d.mts";

export interface BrowserCounts {
  executed: number;
  passed: number;
  skipped: number;
}

export interface E2eSummary {
  readonly measuredAt: string | null;
  readonly byBrowser: Record<string, BrowserCounts>;
  readonly totals: BrowserCounts & {
    csp: number;
    axe: number;
    axeRuns: number;
    withMetrics: number;
    failures: string[];
  };
}

export function summariseE2e(report: unknown): E2eSummary;
export function e2eRecords(summary: E2eSummary, fallbackTime: string): MetricRecord[];
