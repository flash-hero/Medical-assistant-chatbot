import { expectNoSeriousA11yViolations } from "./support/axe";
import { LOCALES, MESSAGES } from "./support/chat";
import { expect, test } from "./support/fixtures";

test("the root redirects to a locale", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveURL(/\/(en|fr|ar)$/);
});

for (const locale of LOCALES) {
  const m = MESSAGES[locale];

  test.describe(`site (${locale})`, () => {
    test("landing page: language, direction, brand, call to action", async ({ page, metrics }) => {
      await page.goto(`/${locale}`);
      const html = page.locator("html");
      await expect(html).toHaveAttribute("lang", locale);
      await expect(html).toHaveAttribute("dir", locale === "ar" ? "rtl" : "ltr");
      await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
      await expect(page.locator('link[rel="icon"][href="/brand/ausculta-favicon.svg"]')).toHaveCount(1);
      await expect(page.locator('meta[property="og:image"]')).toHaveAttribute("content", /\/brand\/ausculta-og\.png$/);

      const cta = page.locator('section[aria-labelledby="hero-title"]').getByRole("link", { name: m.Common.askCta });
      await cta.click();
      await expect(page).toHaveURL(new RegExp(`/${locale}/chat$`));
      await expect(page.getByTestId("ai-label")).toHaveText(m.Common.aiAssistant);

      // axe runs on a fresh landing document, after the client-side navigation: in Playwright's
      // Firefox any client-side navigation that follows an axe run (aria-allowed-attr) crashes the
      // content process, on every route; without axe the same navigation is fine.
      await page.goto(`/${locale}`);
      await expectNoSeriousA11yViolations(page, metrics, "landing");
    });

    test("sources and about pages are accessible", async ({ page, metrics }) => {
      for (const path of ["sources", "about"]) {
        await page.goto(`/${locale}/${path}`);
        await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
        await expectNoSeriousA11yViolations(page, metrics, path);
      }
    });

    test("the chat empty state is accessible in both themes", async ({ page, metrics }) => {
      await page.goto(`/${locale}/chat`);
      await expect(page.getByTestId("example-question").first()).toBeEnabled();
      await expect(page.getByTestId("demo-banner")).toBeVisible();
      await expectNoSeriousA11yViolations(page, metrics, "chat light");
      await page.emulateMedia({ colorScheme: "dark" });
      await expectNoSeriousA11yViolations(page, metrics, "chat dark");
    });
  });
}

test("brand files are served", async ({ request }) => {
  for (const path of ["/favicon.ico", "/brand/ausculta-favicon.svg", "/brand/ausculta-og.png", "/brand/ausculta-app-icon-192.png", "/manifest.webmanifest"]) {
    const response = await request.get(path);
    expect(response.status(), path).toBe(200);
  }
});
