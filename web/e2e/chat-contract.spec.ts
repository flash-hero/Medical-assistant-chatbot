import { expectNoSeriousA11yViolations } from "./support/axe";
import { ask, LOCALES, MESSAGES, openChat, PROMPTS } from "./support/chat";
import { expect, test } from "./support/fixtures";

/**
 * What the real server can send and the scripted happy paths did not: several safety events in one
 * turn, a safety event that drifted from the contract, an impossible citation date, a proxy error page
 * without the JSON envelope (review T2, T4, T5, T11).
 */
for (const locale of LOCALES) {
  const t = MESSAGES[locale].Chat;
  const p = PROMPTS[locale];

  test.describe(`server contract edge cases (${locale})`, () => {
    test("two safety events in one turn: both shown, emergency first, contacts merged (T2)", async ({ page, metrics }) => {
      await openChat(page, locale);
      await ask(page, p.emergencyAbuse!);
      const banner = page.getByTestId("safety-banner");
      await expect(banner).toBeVisible();
      await expect(banner).toHaveAttribute("data-kind", "emergency");
      const kinds = banner.locator("[data-safety-kind]");
      await expect(kinds).toHaveCount(2);
      await expect(kinds.nth(0)).toHaveAttribute("data-safety-kind", "emergency");
      await expect(kinds.nth(1)).toHaveAttribute("data-safety-kind", "abuse_disclosure");
      const calls = banner.locator('a[href^="tel:"]');
      await expect(calls.first()).toHaveAttribute("href", "tel:112");
      await expect(calls).toHaveCount(3); // 112, switchboard, front desk: 112 is listed once
      await expect(page.getByTestId("assistant-message").last()).toHaveAttribute("data-phase", "done");
      await expect(kinds).toHaveCount(2); // the later event did not replace the emergency one
      await expectNoSeriousA11yViolations(page, metrics, "two safety events");
    });

    test("a drifted safety event still shows a banner, and an impossible date does not break the drawer (T4, T11)", async ({ page }) => {
      await openChat(page, locale);
      await ask(page, p.drift!);
      const banner = page.getByTestId("safety-banner");
      await expect(banner).toBeVisible();
      await expect(banner).toHaveAttribute("data-kind", "emergency");
      await expect(banner.locator('a[href="tel:112"]')).toHaveCount(1);
      const message = page.getByTestId("assistant-message").last();
      await expect(message).toHaveAttribute("data-phase", "done");
      await message.getByTestId("answer-text").locator('[data-cite="1"]').first().click();
      const drawer = page.getByTestId("source-drawer");
      await expect(drawer.getByTestId("source-title")).toBeVisible();
      await expect(page.getByTestId("error-page")).toHaveCount(0);
      await expect(drawer).not.toContainText("2025-13-45");
    });

    test("a proxy error page shows a localised message, never a raw code (T5)", async ({ page }) => {
      await openChat(page, locale);
      await ask(page, p.badGateway!);
      const error = page.getByTestId("turn-error");
      await expect(error).toHaveAttribute("data-code", "http_502");
      await expect(error).toContainText(t.errors.unknown);
      await expect(error).not.toContainText("http_502");
      await expect(error).not.toContainText("Bad Gateway");
    });
  });
}
