import { defineConfig, devices } from "@playwright/test";

/**
 * E2E suite: the production build (standalone server) in front of the mock API (e2e/mock-api/server.mjs).
 * Build first, pointing the /api rewrite at the mock:
 *   API_ORIGIN=http://127.0.0.1:4010 npm run build && npm run test:e2e
 * e2e/global-setup.ts refuses to run against a build that proxies anywhere else.
 */
const WEB_PORT = Number(process.env.E2E_WEB_PORT ?? 3100);
const MOCK_PORT = Number(process.env.MOCK_API_PORT ?? 4010);
export const BASE_URL = `http://127.0.0.1:${WEB_PORT}`;
const reuse = !process.env.CI;

/** Mobile viewport without device emulation, for Firefox (Playwright has no mobile Firefox). */
const PHONE_VIEWPORT = { viewport: { width: 390, height: 844 } };

export default defineConfig({
  testDir: "./e2e",
  testMatch: "**/*.spec.ts",
  outputDir: "./test-results/e2e",
  globalSetup: "./e2e/global-setup.ts",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  // CI: one retry for browser-process crashes on shared runners (reported as "flaky", never hidden); local: 0
  retries: process.env.CI ? 1 : 0,
  workers: process.env.E2E_WORKERS ? Number(process.env.E2E_WORKERS) : 4,
  timeout: 45_000,
  expect: { timeout: 10_000 },
  reporter: [["list"], ["json", { outputFile: "./test-results/e2e-report.json" }]],
  use: {
    baseURL: BASE_URL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    reducedMotion: "reduce",
  },
  projects: [
    { name: "chromium-desktop", use: { ...devices["Desktop Chrome"] } },
    { name: "firefox-desktop", use: { ...devices["Desktop Firefox"] } },
    { name: "webkit-desktop", use: { ...devices["Desktop Safari"] } },
    { name: "chromium-mobile", use: { ...devices["Pixel 7"] } },
    { name: "firefox-mobile", use: { ...devices["Desktop Firefox"], ...PHONE_VIEWPORT } },
    { name: "webkit-mobile", use: { ...devices["iPhone 15"] } },
  ],
  webServer: [
    {
      command: "node e2e/mock-api/server.mjs",
      url: `http://127.0.0.1:${MOCK_PORT}/api/v1/health`,
      env: { MOCK_API_PORT: String(MOCK_PORT) },
      reuseExistingServer: reuse,
      timeout: 30_000,
    },
    {
      // The standalone production server, laid out as in deploy/web.Dockerfile.
      command: `node scripts/e2e/serve-standalone.mjs --port ${WEB_PORT}`,
      url: `${BASE_URL}/en`,
      reuseExistingServer: reuse,
      timeout: 120_000,
    },
  ],
});
