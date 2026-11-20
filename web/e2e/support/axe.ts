import AxeBuilder from "@axe-core/playwright";
import type { Page } from "@playwright/test";
import { expect } from "./fixtures";

interface AxeMetrics {
  axeSeriousOrCritical: number;
  axeRuns: number;
}

const TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa", "best-practice"];
const SETTLE_TIMEOUT_MS = 3_000;

/**
 * Wait until no CSS transition is running. Colour transitions (Tailwind `transition-colors`, 150 ms)
 * still run under reduced motion, and right after a theme switch axe would otherwise measure contrast
 * on mid-fade colours (text and background both grey), a false positive no reader ever sees.
 */
async function settleTransitions(page: Page): Promise<void> {
  await page
    .waitForFunction(
      () => {
        void getComputedStyle(document.body).color; // flush pending style, so new transitions have started
        return document
          .getAnimations()
          .every((animation) => animation.constructor.name !== "CSSTransition" || animation.playState !== "running");
      },
      undefined,
      { timeout: SETTLE_TIMEOUT_MS },
    )
    .catch(() => undefined); // a transition that never ends must not hide the axe result itself
}

/**
 * Run axe-core on the current page and assert no serious or critical violation. Minor and moderate
 * findings are attached to the report for review but do not fail the test.
 */
export async function expectNoSeriousA11yViolations(page: Page, metrics: AxeMetrics, label: string): Promise<void> {
  await settleTransitions(page);
  const results = await new AxeBuilder({ page }).withTags(TAGS).analyze();
  const blocking = results.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
  metrics.axeRuns += 1;
  metrics.axeSeriousOrCritical += blocking.reduce((sum, v) => sum + v.nodes.length, 0);
  const summary = blocking.map((v) => ({
    id: v.id,
    impact: v.impact,
    help: v.help,
    targets: v.nodes.slice(0, 5).map((n) => n.target.join(" ")),
  }));
  expect(summary, `axe serious/critical violations (${label})`).toEqual([]);
}
