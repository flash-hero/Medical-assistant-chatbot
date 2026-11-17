import { test as base, expect, type Page, type TestInfo } from "@playwright/test";

export const METRICS_ATTACHMENT = "ausculta-metrics";

export interface CspViolation {
  readonly directive: string;
  readonly blocked: string;
  readonly source: string;
}

interface Metrics {
  cspViolations: CspViolation[];
  axeSeriousOrCritical: number;
  axeRuns: number;
}

/**
 * Every test page reports CSP violations through a binding (it survives navigations); the
 * `securitypolicyviolation` event fires in Chromium, Firefox and WebKit. Each test asserts zero and
 * attaches its counts to its result (see attachMetrics).
 */
async function watchCsp(page: Page, sink: CspViolation[]): Promise<void> {
  await page.exposeBinding("__ausculta_csp", (_source, violation: CspViolation) => {
    sink.push(violation);
  });
  await page.addInitScript(() => {
    document.addEventListener("securitypolicyviolation", (event) => {
      const report = (window as unknown as { __ausculta_csp?: (v: unknown) => void }).__ausculta_csp;
      report?.({ directive: event.effectiveDirective, blocked: event.blockedURI, source: `${event.sourceFile}:${event.lineNumber}` });
    });
  });
}

/** First time (performance.now) each watched test id appears in the DOM, to assert ordering. */
async function watchAppearance(page: Page): Promise<void> {
  await page.addInitScript(() => {
    const seen: Record<string, number> = {};
    (window as unknown as { __ausculta_seen: Record<string, number> }).__ausculta_seen = seen;
    const ids = ["safety-banner", "answer-text"];
    const scan = () => {
      for (const id of ids) {
        if (seen[id] === undefined && document.querySelector(`[data-testid="${id}"]`)) seen[id] = performance.now();
      }
    };
    new MutationObserver(scan).observe(document, { childList: true, subtree: true });
  });
}

/** Attached to the result, so the JSON report carries it (scripts/measure/ui-metrics.mjs sums them). */
async function attachMetrics(testInfo: TestInfo, metrics: Metrics): Promise<void> {
  const record = {
    csp_violations: metrics.cspViolations.length,
    csp_details: metrics.cspViolations.slice(0, 10),
    axe_serious_or_critical: metrics.axeSeriousOrCritical,
    axe_runs: metrics.axeRuns,
  };
  await testInfo.attach(METRICS_ATTACHMENT, { body: JSON.stringify(record), contentType: "application/json" });
}

export const test = base.extend<{ metrics: Metrics; _guards: void }>({
  metrics: async ({}, use) => {
    await use({ cspViolations: [], axeSeriousOrCritical: 0, axeRuns: 0 });
  },
  _guards: [
    async ({ page, metrics }, use, testInfo) => {
      await watchCsp(page, metrics.cspViolations);
      await watchAppearance(page);
      await use();
      await attachMetrics(testInfo, metrics);
      expect(metrics.cspViolations, "CSP violations").toEqual([]);
    },
    { auto: true },
  ],
});

export { expect };
