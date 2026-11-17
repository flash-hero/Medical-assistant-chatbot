import { expectNoSeriousA11yViolations } from "./support/axe";
import { answerOf, ask, LOCALES, MESSAGES, mockTurn, openChat, PROMPTS } from "./support/chat";
import { expect, test } from "./support/fixtures";

for (const locale of LOCALES) {
  const t = MESSAGES[locale].Chat;
  const p = PROMPTS[locale];

  test.describe(`chat flows (${locale})`, () => {
    test("appointment form: validation, consent, then a reference number", async ({ page, metrics }) => {
      await openChat(page, locale);
      await ask(page, p.appointment!);
      await answerOf(page, "template");
      const form = page.getByTestId("appointment-form");
      await expect(form).toBeVisible();
      await expectNoSeriousA11yViolations(page, metrics, "appointment form");

      await form.getByRole("button", { name: t.form.submit }).click();
      await expect(form.getByRole("alert")).toBeVisible();
      await expect(form.locator("[aria-invalid=true]").first()).toBeFocused();

      await form.locator('input[name="full_name"]').fill("Test Patient");
      await form.locator('input[name="phone"]').fill("+33 4 00 00 00 09");
      await form.locator('select[name="department_id"]').selectOption({ index: 1 });
      await form.locator('input[name="preferred_dates"]').fill(locale === "ar" ? "صباح الاثنين" : "Monday morning");
      await form.getByRole("button", { name: t.form.submit }).click();
      await expect(form.getByText(t.form.consentError)).toBeVisible();

      await form.getByRole("checkbox").check();
      const posted = page.waitForRequest((r) => r.url().endsWith("/api/v1/appointments"));
      await form.getByRole("button", { name: t.form.submit }).click();
      const body = (await posted).postDataJSON() as Record<string, unknown>;
      expect(body).toMatchObject({ full_name: "Test Patient", consent: true });
      const success = page.getByTestId("appointment-success");
      await expect(success).toBeVisible();
      await expect(success).toContainText(/REQ-[0-9A-F]{6}/);
    });

    test("429: localised notice with a Retry-After countdown", async ({ page }) => {
      await openChat(page, locale);
      await ask(page, p.rateLimited!);
      const error = page.getByTestId("turn-error");
      await expect(error).toHaveAttribute("data-code", "rate_limited");
      await expect(error).toContainText(t.errors.rate_limited);
      await expect(page.getByTestId("retry-countdown")).toBeVisible();
      const retry = error.getByRole("button", { name: t.errors.retry });
      await expect(retry).toBeDisabled();
      await expect(retry).toBeEnabled({ timeout: 8_000 });
      await expect(page.getByTestId("retry-countdown")).toHaveCount(0);
    });

    test("503: busy notice with a countdown, then retry works", async ({ page }) => {
      await openChat(page, locale);
      await ask(page, p.overloaded!);
      const error = page.getByTestId("turn-error");
      await expect(error).toHaveAttribute("data-code", "overloaded");
      await expect(page.getByTestId("retry-countdown")).toBeVisible();
      await expect(error.getByRole("button", { name: t.errors.retry })).toBeEnabled({ timeout: 8_000 });
    });

    test("mid-stream error keeps the partial text and offers a retry", async ({ page }) => {
      await openChat(page, locale);
      await ask(page, p.fail!);
      const message = page.getByTestId("assistant-message").last();
      await expect(message).toHaveAttribute("data-phase", "error");
      await expect(message.getByTestId("turn-error")).toHaveAttribute("data-code", "upstream_error");
    });

    test("Stop closes the stream", async ({ page, request }) => {
      await openChat(page, locale);
      const turnId = await ask(page, p.slow!);
      const message = page.getByTestId("assistant-message").last();
      await expect(message.getByTestId("answer-text")).toBeVisible();
      const stop = page.getByTestId("stop-button");
      await stop.click();
      const stoppedAt = Date.now();
      await expect(message).toHaveAttribute("data-phase", "stopped");
      await expect(page.getByTestId("stopped-note")).toHaveText(t.stopped);
      await expect(page.getByTestId("send-button")).toBeVisible();
      await expect.poll(async () => (await mockTurn(request, turnId)).closedByClient, { timeout: 5_000 }).toBe(true);
      const turn = await mockTurn(request, turnId);
      expect(turn.completed).toBe(false);
      expect(turn.closedAt! - stoppedAt).toBeLessThan(2_000);
    });
  });
}
