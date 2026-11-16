import { describe, expect, it } from "vitest";
import { e2eRecords, summariseE2e } from "../../scripts/measure/e2e-summary.mjs";
import { lighthouseRecords, routeJsRecords } from "../../scripts/measure/ui-metrics-lib.mjs";

const NOW = "2026-11-16T12:00:00.000Z";

function attachment(csp: number, axe: number, axeRuns: number) {
  const body = Buffer.from(JSON.stringify({ csp_violations: csp, axe_serious_or_critical: axe, axe_runs: axeRuns })).toString("base64");
  return [{ name: "ausculta-metrics", contentType: "application/json", body }];
}

function spec(title: string, results: ReadonlyArray<{ project: string; status: string; attachments?: unknown[] }>) {
  return {
    title,
    file: "chat.spec.ts",
    tests: results.map((r) => ({ projectName: r.project, results: [{ status: r.status, attachments: r.attachments ?? [] }] })),
  };
}

const REPORT = {
  stats: { startTime: "2026-11-16T11:00:00.000Z" },
  suites: [
    {
      title: "chat.spec.ts",
      specs: [spec("streams", [{ project: "chromium-desktop", status: "passed", attachments: attachment(0, 0, 2) }])],
      suites: [
        {
          title: "nested",
          specs: [
            spec("keyboard", [
              { project: "firefox-desktop", status: "passed", attachments: attachment(0, 1, 1) },
              { project: "webkit-mobile", status: "skipped" },
              { project: "webkit-desktop", status: "failed", attachments: attachment(2, 0, 0) },
            ]),
          ],
        },
      ],
    },
  ],
};

describe("summariseE2e", () => {
  it("counts per browser, excludes skipped tests and sums the attached metrics", () => {
    const summary = summariseE2e(REPORT);
    expect(summary.byBrowser).toEqual({
      chromium: { executed: 1, passed: 1, skipped: 0 },
      firefox: { executed: 1, passed: 1, skipped: 0 },
      webkit: { executed: 1, passed: 0, skipped: 1 },
    });
    expect(summary.totals).toMatchObject({ executed: 3, passed: 2, skipped: 1, csp: 2, axe: 1, axeRuns: 3, withMetrics: 3 });
    expect(summary.totals.failures).toEqual(["webkit-desktop chat.spec.ts > keyboard: failed"]);
  });

  it("turns the summary into the three e2e gate records", () => {
    const records = e2eRecords(summariseE2e(REPORT), NOW);
    expect(records.map((r) => [r.metric, r.value, r.sample_size])).toEqual([
      ["playwright_pass_rate", 2 / 3, 3],
      ["axe_serious_or_critical", 1, 3],
      ["csp_violations_in_e2e", 2, 3],
    ]);
    expect(records[0]).toMatchObject({ measured_at: "2026-11-16T11:00:00.000Z", free_tier: false, labels: { webkit: "0/1", skipped: "1" } });
  });

  it("leaves the axe and CSP gates missing when no test attached metrics", () => {
    const bare = { suites: [{ title: "x", specs: [spec("t", [{ project: "chromium-desktop", status: "passed" }])] }] };
    const records = e2eRecords(summariseE2e(bare), NOW);
    expect(records.map((r) => r.metric)).toEqual(["playwright_pass_rate"]);
    expect(records[0]).toMatchObject({ value: 1, measured_at: NOW });
  });

  it("reports a zero pass rate for an empty report", () => {
    expect(e2eRecords(summariseE2e({}), NOW)[0]).toMatchObject({ value: 0, sample_size: 0 });
  });
});

describe("lighthouseRecords", () => {
  const run = (url: string, formFactor: string, accessibility: number, performance: number) => ({
    url,
    form_factor: formFactor,
    scores: { performance, accessibility, "best-practices": 100, seo: 100 },
  });

  it("gates on the worst accessibility score and reports performance per run", () => {
    const records = lighthouseRecords({ measured_at: NOW, runs: [run("/en", "mobile", 100, 93), run("/en/chat", "mobile", 96, 88)] });
    expect(records[0]).toMatchObject({ metric: "lighthouse_accessibility", value: 96, sample_size: 2, labels: { worst_page: "/en/chat" } });
    expect(records.slice(1).map((r) => [r.metric, r.value, r.labels.target])).toEqual([
      ["lighthouse_performance", 93, "90"],
      ["lighthouse_performance", 88, "85"],
    ]);
  });

  it("emits nothing without runs", () => {
    expect(lighthouseRecords({ measured_at: NOW, runs: [] })).toEqual([]);
  });
});

describe("routeJsRecords", () => {
  it("gates on the heaviest chat route; other routes are informational", () => {
    const routes = [
      { route: "/en/chat", scripts: 12, raw_kb: 400, gzip_kb: 140.2 },
      { route: "/ar/chat", scripts: 12, raw_kb: 402, gzip_kb: 141.5 },
      { route: "/en", scripts: 10, raw_kb: 300, gzip_kb: 110 },
    ];
    const records = routeJsRecords({ measured_at: NOW, routes });
    expect(records.map((r) => [r.metric, r.value, r.labels.route])).toEqual([
      ["chat_route_js_gzip_kb", 141.5, "/ar/chat"],
      ["route_js_gzip_kb", 110, "/en"],
    ]);
  });
});
