import { expectNoSeriousA11yViolations } from "./support/axe";
import { answerOf, ask, LOCALES, MESSAGES, openChat, OTHER_LANGUAGE, PROMPTS } from "./support/chat";
import { expect, test } from "./support/fixtures";

for (const locale of LOCALES) {
  const t = MESSAGES[locale].Chat;
  const p = PROMPTS[locale];

  test.describe(`chat answers (${locale})`, () => {
    test("streams an answer with citations and opens the source drawer", async ({ page, metrics }) => {
      await openChat(page, locale);
      await expect(page.getByTestId("ai-label")).toBeVisible();
      await page.getByTestId("example-question").first().click();
      const answer = await answerOf(page, "streamed");
      await expect(answer.locator("[data-cite]")).not.toHaveCount(0);
      await expect(page.locator("[data-cite-chip]")).toHaveCount(2);
      await expect(page.getByRole("heading", { name: t.seekCareTitle })).toBeVisible();

      const chip = answer.locator('[data-cite="1"]').first();
      await chip.click();
      const drawer = page.getByTestId("source-drawer");
      await expect(drawer).toBeVisible();
      await expect(drawer.getByTestId("source-title")).toHaveText("Hemoglobin A1C (HbA1c) Test");
      await expect(drawer.getByTestId("source-snippet")).toContainText("average blood sugar");
      const link = drawer.getByTestId("source-link");
      await expect(link).toHaveAttribute("href", "https://medlineplus.gov/lab-tests/hemoglobin-a1c-hba1c-test/");
      await expect(link).toHaveAttribute("target", "_blank");
      await expect(link).toHaveAttribute("rel", /noopener/);
      await expectNoSeriousA11yViolations(page, metrics, "source drawer open");

      await page.keyboard.press("Escape");
      await expect(drawer).toBeHidden();
      await expect(chip).toBeFocused();
      await expectNoSeriousA11yViolations(page, metrics, "answered conversation");
    });

    test("shows the verified state for a checked medication answer", async ({ page }) => {
      await openChat(page, locale);
      await ask(page, p.verified!);
      const answer = await answerOf(page, "verified");
      await expect(answer).toContainText(locale === "ar" ? "الإيبوبروفين" : locale === "fr" ? "ibuprofène" : "Ibuprofen");
      await expect(page.getByTestId("verified-badge")).toHaveText(t.verified);
      await expect(page.locator("[data-cite-chip]")).toHaveCount(2);
      // T7: the badge names the languages the sources are really in (an English and a French source).
      const badge = page.getByTestId("source-language-badge");
      const foreign = { en: ["fr"], fr: ["en"], ar: ["en", "fr"] } as const;
      for (const language of foreign[locale]) await expect(badge).toContainText(t.languageNames[language]);
    });

    test("answers in the language of the question, with its own direction (T1)", async ({ page }) => {
      const other = OTHER_LANGUAGE[locale];
      await openChat(page, locale);
      await ask(page, other.prompt);
      const answer = await answerOf(page, "streamed");
      await expect(answer).toHaveAttribute("lang", other.language);
      await expect(answer.locator("p").first()).toHaveAttribute("dir", other.dir);
      const bubble = page.getByTestId("user-message").last();
      await expect(bubble).toHaveAttribute("lang", other.language);
      await expect(bubble).toHaveAttribute("dir", other.dir);
      await expect(page.locator("html")).toHaveAttribute("dir", locale === "ar" ? "rtl" : "ltr");
      // The cited source is English, the answer is not: the drawer says so, in the UI language.
      await answer.locator('[data-cite="1"]').first().click();
      const drawer = page.getByTestId("source-drawer");
      await expect(drawer.getByTestId("source-language-note")).toContainText(t.languageNames.en);
    });

    test("answers a front-desk question from the hospital profile", async ({ page }) => {
      await openChat(page, locale);
      await ask(page, p.frontDesk!);
      const answer = await answerOf(page, "template");
      await expect(answer).toContainText(locale === "fr" ? "12 h" : "12:00");
      await expect(page.locator("[data-cite-chip]")).toHaveCount(0);
    });

    test("abstains when the sources have nothing reliable", async ({ page }) => {
      await openChat(page, locale);
      await ask(page, p.abstain!);
      await answerOf(page, "abstain");
      await expect(page.locator("[data-cite-chip]")).toHaveCount(0);
    });

    test("refuses a prompt-injection attempt", async ({ page }) => {
      await openChat(page, locale);
      await ask(page, p.injection!);
      await answerOf(page, "refusal");
      await expect(page.getByTestId("safety-banner")).toHaveCount(0);
    });

    test("records feedback on an answer", async ({ page }) => {
      await openChat(page, locale);
      await ask(page, p.frontDesk!);
      await answerOf(page, "template");
      const feedback = page.getByTestId("feedback");
      await feedback.getByRole("button", { name: t.feedback.down }).click();
      await page.getByTestId("feedback-form").getByRole("button", { name: t.feedback.submit }).click();
      await expect(page.getByText(t.feedback.thanks)).toBeVisible();
      // T8: the controls are gone; focus moves to the thank-you note, not to the page.
      await expect(page.getByTestId("feedback-thanks")).toBeFocused();
    });
  });
}
