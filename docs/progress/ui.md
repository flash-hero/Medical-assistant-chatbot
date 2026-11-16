# UI track (P3D) progress

Owner dirs: `web/**`, `docs/brand/**`. Metrics: `C:\dev\ausculta-data\reports\ui.metrics.json` (gate prefix `ui.`).

## Baseline found at resume (2026-11-16, run 3)

- Next.js 16 app: landing, chat, sources, about; next-intl EN/FR/AR; SSE parser, markdown renderer, chat components.
- Run 2 (cut off) left on disk: brand files + docs/brand/README.md, mock API (server.mjs, scenarios.mjs,
  form-scenario.mjs), Playwright config + 5 spec files + support fixtures (axe, CSP listener), serve-standalone script.
- Run 3 start: typecheck 0 errors, eslint 0 errors / 0 warnings, Vitest 146/146.
- Missing at run 3 start: scripts/measure-route-js.mjs, scripts/lighthouse.mjs, e2e metrics aggregator
  (referenced by package.json / fixtures but absent); no E2E run, no measurements.

## Deliverables

| # | Deliverable | Status | Notes |
|---|---|---|---|
| 1 | Brand files (mark, wordmarks, variants, favicon, app icons, OG) + docs/brand/README.md | done | `npm run brand` (scripts/brand/build-brand.mjs): 23 SVG, 5 PNG, public/favicon.ico. Manifest + OG metadata wired. Contrast 18/18 pairs pass. |
| 2 | `web/e2e/mock-api/server.mjs` (all scripted scenarios, EN/FR/AR) | done (verify in E2E) | 14 scenarios by keyword; `/__mock/turns/<id>` hook for the Stop test. |
| 3 | Production build clean, eslint warning fixed | done | `API_ORIGIN=http://127.0.0.1:4010 next build`: 0 warnings, 0 errors (run 3). eslint 0/0. |
| 4 | Playwright E2E (chromium/firefox/webkit, desktop+mobile, EN/FR/AR, axe, CSP listener) | in progress | chromium-desktop first run: 43/55; fixed (see below); full 330-test run in progress |
| 5 | Measurements (Lighthouse, chat JS gzip, motion-audit) + ui.metrics.json | in progress | scripts written: scripts/measure/{route-js,lighthouse,ui-metrics,e2e-summary,ui-metrics-lib,lib}.mjs (+7 unit tests) |
| 6 | attribution.json from data track | in progress | scripts/content/sync-attribution.mjs written (needs `yaml` devDependency) |

## Bugs found and fixed by the E2E run (run 3)

- **proxy.ts matcher excluded every page** (`"\."` in a JS string is `.`): no CSP header, no nonce, and
  next-intl `<Link>` in server components fell back to `/en` (FR/AR CTA went to /en/chat). Fixed: `"\\."`.
- With the CSP live, Motion's `popLayout` injected an un-nonced `<style>`: chat page now passes the
  request nonce to `<MotionConfig nonce>`.
- axe `label-content-name-mismatch` (serious) on tel: links and source chips: names now come from
  content with sr-only prefixes (no aria-label); new message key `Chat.sourceNumber` (EN/FR/AR).
- Appointment form did not focus the first invalid field (queried aria-invalid before re-render):
  now focuses by control name in field order.

## Gate numbers

Not measured yet.

## Next step

Finish full E2E run; fix Firefox timeouts/crashes (machine at 100% CPU from other tracks); then
`npm run measure:js`, `npm run lighthouse`, motion-audit, `npm run measure:metrics`.
