/**
 * Summarise a Playwright JSON report: pass rate per browser and overall, plus the CSP and axe counts
 * every test attaches (e2e/support/fixtures.ts, attachment "ausculta-metrics").
 */
const METRICS_ATTACHMENT = "ausculta-metrics";
const BROWSERS = ["chromium", "firefox", "webkit"];
const PASSED = new Set(["passed"]);

function* specResults(suite) {
  for (const spec of suite.specs ?? []) {
    for (const test of spec.tests) {
      for (const result of test.results) yield { title: spec.title, file: spec.file, project: test.projectName, result };
    }
  }
  for (const child of suite.suites ?? []) yield* specResults(child);
}

function attachedMetrics(result) {
  const attachment = (result.attachments ?? []).find((a) => a.name === METRICS_ATTACHMENT && a.body);
  if (!attachment) return null;
  return JSON.parse(Buffer.from(attachment.body, "base64").toString("utf8"));
}

function emptyCounts() {
  return { executed: 0, passed: 0, skipped: 0 };
}

function browserOf(project) {
  return BROWSERS.find((b) => project.startsWith(b)) ?? project;
}

/** Fold every result of the report into totals. Skipped tests are excluded from the pass rate. */
export function summariseE2e(report) {
  const byBrowser = Object.fromEntries(BROWSERS.map((b) => [b, emptyCounts()]));
  const totals = { ...emptyCounts(), csp: 0, axe: 0, axeRuns: 0, withMetrics: 0, failures: [] };
  for (const suite of report.suites ?? []) {
    for (const { title, file, project, result } of specResults(suite)) {
      const bucket = (byBrowser[browserOf(project)] ??= emptyCounts());
      if (result.status === "skipped") {
        bucket.skipped += 1;
        totals.skipped += 1;
        continue;
      }
      const ok = PASSED.has(result.status);
      bucket.executed += 1;
      bucket.passed += ok ? 1 : 0;
      totals.executed += 1;
      totals.passed += ok ? 1 : 0;
      if (!ok) totals.failures.push(`${project} ${file} > ${title}: ${result.status}`);
      const m = attachedMetrics(result);
      if (m) {
        totals.withMetrics += 1;
        totals.csp += m.csp_violations;
        totals.axe += m.axe_serious_or_critical;
        totals.axeRuns += m.axe_runs;
      }
    }
  }
  return { measuredAt: report.stats?.startTime ?? null, byBrowser, totals };
}

function ratio(counts) {
  return `${counts.passed}/${counts.executed}`;
}

/** Gate records for ui.e2e_pass_rate, ui.axe_serious and ui.csp_violations. */
export function e2eRecords(summary, fallbackTime) {
  const { totals, byBrowser } = summary;
  const measuredAt = summary.measuredAt ?? fallbackTime;
  const base = { source: "web/playwright", measured_at: measuredAt, free_tier: false };
  const perBrowser = Object.fromEntries(Object.entries(byBrowser).map(([b, c]) => [b, ratio(c)]));
  const records = [
    {
      metric: "playwright_pass_rate",
      value: totals.executed === 0 ? 0 : totals.passed / totals.executed,
      labels: { browsers: BROWSERS.join(","), ...perBrowser, skipped: String(totals.skipped) },
      sample_size: totals.executed,
      ...base,
    },
  ];
  if (totals.withMetrics === 0) return records; // counts unavailable: leave those gates MISSING
  const coverage = { tests_with_metrics: String(totals.withMetrics) };
  records.push(
    { metric: "axe_serious_or_critical", value: totals.axe, labels: { ...coverage, axe_runs: String(totals.axeRuns) }, sample_size: totals.axeRuns, ...base },
    { metric: "csp_violations_in_e2e", value: totals.csp, labels: coverage, sample_size: totals.withMetrics, ...base },
  );
  return records;
}
