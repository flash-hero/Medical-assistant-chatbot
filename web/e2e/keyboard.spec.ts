import type { Page } from "@playwright/test";
import { answerOf, MESSAGES, PROMPTS, type Locale } from "./support/chat";
import { expect, test } from "./support/fixtures";

const MAX_TABS = 40;

/**
 * Playwright's WebKit follows Safari's default ("Press Tab to highlight each item" off): Tab never
 * stops on links, and on Windows no modifier changes that. On WebKit the flow still runs end to end
 * with the keyboard; only the two steps that land on a link (skip link, drawer source link) are
 * checked in Chromium and Firefox alone.
 */
function tabsToLinks(browserName: string): boolean {
  return browserName !== "webkit";
}

/** Press Tab (or Shift+Tab) until `predicate` holds for the focused element. */
async function tabUntil(page: Page, predicate: string, backwards = false): Promise<void> {
  for (let i = 0; i < MAX_TABS; i += 1) {
    const done = await page.evaluate((selector) => document.activeElement?.matches(selector) ?? false, predicate);
    if (done) return;
    await page.keyboard.press(backwards ? "Shift+Tab" : "Tab");
  }
  throw new Error(`focus never reached ${predicate}`);
}

for (const locale of ["en", "ar"] as const satisfies readonly Locale[]) {
  const t = MESSAGES[locale].Chat;

  test(`keyboard-only conversation (${locale})`, async ({ page, isMobile, browserName }) => {
    test.skip(isMobile, "keyboard flow runs on desktop projects");
    const links = tabsToLinks(browserName);
    await page.goto(`/${locale}/chat`);
    await expect(page.getByTestId("example-question").first()).toBeEnabled();

    if (links) {
      await page.keyboard.press("Tab");
      await expect(page.locator(".skip-link")).toBeFocused();
      await page.keyboard.press("Enter");
      await expect(page.locator("#main")).toBeFocused();
    }

    await tabUntil(page, '[data-testid="composer-input"]');
    await page.keyboard.type(PROMPTS[locale].streamed!);
    await page.keyboard.press("Enter");
    await answerOf(page, "streamed");

    await tabUntil(page, "[data-cite]", true);
    const chip = await page.evaluateHandle(() => document.activeElement);
    await page.keyboard.press("Enter");
    const drawer = page.getByTestId("source-drawer");
    await expect(drawer).toBeVisible();
    await expect(drawer.getByRole("button", { name: t.drawer.close })).toBeFocused();
    if (links) {
      await page.keyboard.press("Tab");
      await expect(drawer.getByTestId("source-link")).toBeFocused();
    }
    await page.keyboard.press("Escape");
    await expect(drawer).toBeHidden();
    expect(await chip.evaluate((el) => el === document.activeElement)).toBe(true);

    await tabUntil(page, '[data-testid="composer-input"]');
    await page.keyboard.type(PROMPTS[locale].slow!);
    await page.keyboard.press("Enter");
    await expect(page.getByTestId("stop-button")).toBeVisible();
    await tabUntil(page, '[data-testid="stop-button"]');
    await page.keyboard.press("Enter");
    await expect(page.getByTestId("stopped-note")).toHaveText(t.stopped);
  });
}
