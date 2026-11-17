import { expectNoSeriousA11yViolations } from "./support/axe";
import { appearanceTimes, ask, LOCALES, MESSAGES, openChat, PROMPTS } from "./support/chat";
import { expect, test } from "./support/fixtures";

for (const locale of LOCALES) {
  const t = MESSAGES[locale].Chat;
  const p = PROMPTS[locale];

  test.describe(`safety (${locale})`, () => {
    test("emergency: the banner comes first, with tap-to-call links", async ({ page, metrics }) => {
      await openChat(page, locale);
      await ask(page, p.emergency!);
      const banner = page.getByTestId("safety-banner");
      await expect(banner).toBeVisible();
      await expect(banner).toHaveAttribute("data-kind", "emergency");
      await expect(banner).toHaveAttribute("role", "alert");
      const call = banner.locator('a[href="tel:112"]');
      await expect(call).toBeVisible();
      await expect(call).toContainText("112");
      await expect(banner.locator('a[href^="tel:+33"]')).toHaveCount(1);

      await expect(page.getByTestId("answer-text")).toBeVisible();
      const seen = await appearanceTimes(page);
      expect(seen["safety-banner"], "banner rendered").toBeDefined();
      expect(seen["safety-banner"]!).toBeLessThanOrEqual(seen["answer-text"]!);
      await expectNoSeriousA11yViolations(page, metrics, "emergency banner");
    });

    test("self-harm: crisis line first, and the banner stays for the session", async ({ page }) => {
      await openChat(page, locale);
      await ask(page, p.selfHarm!);
      const banner = page.getByTestId("safety-banner");
      await expect(banner).toHaveAttribute("data-kind", "self_harm");
      const links = banner.locator('a[href^="tel:"]');
      await expect(links.first()).toHaveAttribute("href", "tel:3114");
      await expect(links).toHaveCount(2);

      await expect(page.getByTestId("assistant-message").last()).toHaveAttribute("data-phase", "done");
      await page.getByTestId("new-conversation").click();
      await expect(page.getByTestId("empty-state")).toBeVisible();
      await expect(banner).toBeVisible();
    });

    test("talk to a person: the handoff dialog lists dialable contacts", async ({ page, metrics }) => {
      await openChat(page, locale);
      const trigger = page.getByTestId("handoff-button");
      await trigger.click();
      const dialog = page.getByTestId("handoff-dialog");
      await expect(dialog).toBeVisible();
      await expect(dialog.getByRole("heading", { name: t.handoffTitle })).toBeVisible();
      await expect(dialog.locator('a[href^="tel:"]')).toHaveCount(3);
      await expectNoSeriousA11yViolations(page, metrics, "handoff dialog");
      await page.keyboard.press("Escape");
      await expect(dialog).toBeHidden();
      await expect(trigger).toBeFocused();
    });
  });
}
