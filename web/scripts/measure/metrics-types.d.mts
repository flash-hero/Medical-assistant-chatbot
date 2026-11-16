/** Shared types for the measurement modules (see e2e-summary.d.mts and ui-metrics-lib.d.mts). */
export interface MetricRecord {
  readonly metric: string;
  readonly value: number;
  readonly labels: Readonly<Record<string, string>>;
  readonly sample_size: number;
  readonly source: string;
  readonly measured_at: string;
  readonly free_tier: boolean;
}
