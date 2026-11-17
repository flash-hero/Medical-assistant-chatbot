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
| 4 | Playwright E2E (chromium/firefox/webkit, desktop+mobile, EN/FR/AR, axe, CSP listener) | done (run 4) | Full run 2026-11-16T11:54Z, 2 workers, retries 0, build after attribution sync: **326/326 passed, 0 failed, 0 flaky, 4 skipped** (keyboard flow on the 2 emulated-mobile projects, by design) in 7.1 min. chromium 108/108, firefox 110/110, webkit 108/108. axe serious/critical 0 over 180 axe runs; CSP violations 0 over 326 tests. Report copied to web/test-results/measure/e2e-report-full.json. |
| 5 | Measurements (Lighthouse, chat JS gzip, motion-audit) + ui.metrics.json | done (run 5) | scripts/measure/{route-js,lighthouse,ui-metrics,e2e-summary,ui-metrics-lib,lib}.mjs (+7 unit tests). 18 records in reports/ui.metrics.json; `evals.run --only ui.`: 5 PASS, 0 FAIL, 0 MISSING. E2E re-run on the final build: 326/326. Numbers and the chat CLS fix: see "Run 5" below. |
| 6 | attribution.json from data track | done (run 4) | `yaml@2.9.1` devDependency; merge rules in scripts/content/attribution-lib.mjs (+7 tests); `node scripts/content/sync-attribution.mjs` wrote 13 sources (generated_on 2026-11-15), `--check` up to date. Landing shows first source per publisher (max 5) + "N more" line (`Landing.sourcesMore`, EN/FR/AR); Sources page lists all 13. Vitest 163/163. |

## Bugs found and fixed by the E2E run (run 3)

- **proxy.ts matcher excluded every page** (`"\."` in a JS string is `.`): no CSP header, no nonce, and
  next-intl `<Link>` in server components fell back to `/en` (FR/AR CTA went to /en/chat). Fixed: `"\\."`.
- With the CSP live, Motion's `popLayout` injected an un-nonced `<style>`: chat page now passes the
  request nonce to `<MotionConfig nonce>`.
- axe `label-content-name-mismatch` (serious) on tel: links and source chips: names now come from
  content with sr-only prefixes (no aria-label); new message key `Chat.sourceNumber` (EN/FR/AR).
- Appointment form did not focus the first invalid field (queried aria-invalid before re-render):
  now focuses by control name in field order.

## Run 4 (2026-11-16) E2E fixes

Last full run of run 3 (11:01, 4 workers, fixtures from before the metrics attachment): 316 passed,
10 failed, 4 skipped. Causes and fixes:

- Firefox (6x landing): "Page crashed" on the CTA click. Bisected: any client-side navigation after
  an axe-core run (rule aria-allowed-attr alone is enough) crashes Playwright's Firefox content
  process, on every route (sources->about too); without axe the same click works. Landing test now
  checks the CTA first, then runs axe on a fresh landing document.
- WebKit desktop keyboard (2x): Playwright's WebKit (Windows) never moves Tab focus to links, even
  with Alt+Tab (Safari default). Flow still runs on WebKit; the skip-link and drawer-source-link
  focus steps are asserted on Chromium and Firefox only.
- The "inline style-src-elem" CSP violation seen on failing WebKit tests comes from Playwright's
  failure screenshot (caret-hiding style); it never appears on a passing test.
- firefox-desktop "streams an answer" and webkit-mobile "feedback" timeouts: did not reproduce
  in isolation with 2 workers (40/40 and 36/36 passed).

## Run 4: chat JS budget (ui.chat_js_gzip_kb <= 200)

First measurement after the attribution sync: /en|fr|ar/chat **235.5 kB gzip** (13 scripts) -> over
budget. Chat-only chunk 75.7 kB gzip, of which Motion (LazyMotion+domAnimation+AnimatePresence+m,
measured alone with rolldown: 32.8 kB gzip) and Phosphor icons (18 icons x 6 weights: 52 kB raw,
12.8 kB gzip). Changes:

- Motion removed from the chat (and from package.json): its only jobs were three enter animations
  (turn, safety banner, status step), now CSS keyframes `.enter-rise/.enter-drop/.enter-step`
  (components.css; 1ms under reduced motion via the duration tokens). `useSmoothText` uses a local
  `usePrefersReducedMotion` (useSyncExternalStore, +2 tests). The Motion `nonce` plumbing in the
  chat page is gone (nothing injects styles any more). Deviation from the plan's "Motion on the chat
  route" stack line, made for the release gate; docs/brand/README.md updated.
- Icons: `src/components/ui/icons.tsx` generated by `npm run icons` (scripts/icons/build-icons.mjs)
  from @phosphor-icons/react defs, only the weights used (35 icons; Phosphor now a devDependency).
- Result: **177.5 kB gzip** (581.4 kB raw) on each chat route; landing /en 206.6 kB (not gated,
  includes GSAP+Lenis loaded after hydration).

## Run 5 (2026-11-16, after the PC restart)

State found: the 326/326 run (11:54Z) predates the Motion removal and generated icons (build 12:07Z).
A full run on the 12:07 build (12:08Z) gave 325/326: one firefox-mobile "Page crashed" in the
appointment-form test (kept as test-results/measure/e2e-report-1208-prev-build.json). So E2E must be
re-run on the final build.

First Lighthouse pass (12:07 build): accessibility 100 everywhere, but chat performance mobile
88/84/86 (en/fr/ar), below the 85 target on /fr/chat. Cause: CLS 0.25-0.27 (mobile), 0.01-0.20
(desktop) on `main#main`. The motion audit flagged the same (CLS 0.22 at 390 px, 0.073 at 1440 px;
landing clean). Two late insertions after POST /session answered:

- The demo banner rendered only once the session said `demo_mode: true`, pushing the conversation
  down. Fix: `src/lib/chat/demo-mode.ts` `isDemoMode()` (+3 tests): unknown (loading or failed
  session) counts as demo, the API client's own default for a missing `demo_mode`; the session can
  turn it off, a turn's meta can only turn it on. Banner is now in the server-rendered page, and no
  longer flickers away on "new conversation". Trade-off: a non-demo deployment shows the banner
  until its session answers.
- The composer's "N questions left" text appeared late and re-wrapped the hint row. Fix: an
  invisible, aria-hidden copy for the contract default (`DEFAULT_TURNS_PER_SESSION = 20`, lib/site.ts)
  holds the slot until the session answers; the character counter is `whitespace-nowrap` (it broke
  mid-phrase at 390 px).
- ChatApp.tsx JSX re-indented (leftover from removing `<MotionConfig>`).

## Gate numbers (run 5, build 16:48Z, all three locales)

- Chat route JS (`npm run measure:js`): /en|fr|ar/chat **177.5 kB gzip** (13 scripts, 581.6 kB raw);
  /en 206.6 kB gzip (15 scripts, not gated).
- Lighthouse 13.6 (`npm run lighthouse`), performance / accessibility / best practices:
  - mobile: /en 98/100/100, /fr 98/100/100, /ar 99/100/100, /en/chat 99/100/100,
    /fr/chat 100/100/100, /ar/chat 100/100/100 (CLS 0 on every page; TBT 64-153 ms; LCP 0.96-1.13 s).
  - desktop: 100/100/100 on all six pages.
  - SEO 54 everywhere, by design: `robots: noindex, nofollow` in the locale layout, and the canonical
    host is SITE_URL (default localhost:3000) while the measurement runs on 127.0.0.1:3100.
- Motion audit (1440 + 390, normal + reduced motion, 16 steps): /en, /en/chat, /ar/chat: CLS 0,
  LoAF 0, p95 frame 16.8 ms, stuck-invisible 0, console errors 0, overflow 0. Reports under
  test-results/measure/motion-*/.
- Checks on the final code: typecheck 0, eslint 0/0, Vitest 168/168 (coverage: statements 90.97%,
  branches 85.66%), `API_ORIGIN=http://127.0.0.1:4010 next build` 0 warnings.
- E2E, full suite on the 16:48Z build (2026-11-16T16:52Z, 2 workers, retries 0): **326/326 passed,
  0 failed, 0 flaky, 4 skipped** (keyboard flow on the 2 emulated-mobile projects, by design) in 7.6 min.
  chromium 108/108, firefox 110/110, webkit 108/108 (each of the 6 projects: 55 or 53+2 skipped);
  axe serious/critical 0 over 180 axe runs; CSP violations 0 over 326 tests.
  Report: test-results/e2e-report.json (copy: test-results/measure/e2e-report-final.json).
- `npm run measure:metrics` wrote 18 records; `python -m evals.run --only ui. --allow-missing`:
  ui.e2e_pass_rate 1 (n=326), ui.axe_serious 0 (n=180), ui.lighthouse_a11y 100 (n=12),
  ui.csp_violations 0 (n=326), ui.chat_js_gzip_kb 177.5 (n=3): **PASS 5, FAIL 0, MISSING 0**.

## Run 6 (2026-11-17): review fixes T1-T18 (docs/reviews/2026-11-16-p3-review.md, "Web (T)")

Each finding got a failing test first (Vitest, plus E2E where the mock can reproduce it), then the fix.
The mock API now follows the real contract, so the E2E suite would have caught T1 and T3: answers are
written in the question's language (`detectLanguage`, like the server's classifier) and tagged with
`language`; department options are ids (app/pipeline/forms.py) with a `consent` select and a
`preferred_dates` textarea; phone/e-mail rules match app/api/schemas.py; new scenarios
`emergency_abuse` (two safety events in one turn), `safety_drift` (drifted safety event + impossible
citation date), `bad_gateway` (502 HTML page, no envelope); the medication answer cites an English and a
French source.

| ID | Fix | Proving tests |
|---|---|---|
| T1 | `lib/i18n/text-language.ts` (language by script/function words, direction by dominant script); `lib/chat/language.ts` `answerLanguage` = `answer.language` ?? detection ?? UI locale. Answer container gets that `lang`/`dir`, every paragraph/list item its own `dir`; question bubble, safety title/message, notices and error text get their own `lang`/`dir`; the drawer compares the source with the answer's language and formats dates in the UI locale. | text-language.test.ts, events.test.ts "T1", chat-ui.test.tsx "T1"; E2E chat-answers "answers in the language of the question (T1)" |
| T2 | `lib/chat/safety.ts`: safety kept per kind in SAFETY_ORDER (state and turn), banner renders all, contacts merged by dialled number; "new conversation" keeps the merged list. | safety.test.ts, reducer.test.ts "T2", chat-ui "T2"; E2E chat-contract "two safety events" |
| T3 | Department option labels from the hospital profile (`departmentLabel`), humanised id only without a profile. | chat-ui "T3", mock-scenarios "T3"; E2E chat-flows appointment (option text, body `department_id: "cardiology"`) |
| T4 | `parseSafety` never rejects: unknown kind -> emergency, text truncated (500/4000), contacts filtered one by one, bad `sticky` -> true; unparseable payload -> `FALLBACK_SAFETY`. Banner falls back to i18n text and the hospital's emergency/crisis numbers, else "call your local emergency number". | events "T4", run-turn "T4", chat-ui "T4"; E2E chat-contract "drifted safety event" |
| T5 | `ApiError.serverMessage` (envelope message only); `toTurnError` forwards nothing else. | api "T5", run-turn "T5", chat-ui "T5"; E2E chat-contract "proxy error page" |
| T6 | `createSseParser`: one regex scan per chunk from the last offset, incomplete line kept in pieces, data lines pushed; cap 256 K chars per event (data + current line) -> `SseBufferOverflow` -> `invalid_response`. 150 K chars fed one at a time: linear. | sse-parser "T6", run-turn "T6" |
| T7 | Badge text from distinct citation languages differing from the answer's (`foreignSourceLanguages`, `Intl.ListFormat`), "all"/"some" wording, EN/FR/AR. | text-language "T7", chat-ui "T7"; E2E chat-answers verified (badge names the languages) |
| T8 | Stop -> focus to the message box when Stop had focus; feedback thank-you and appointment confirmation take focus; stopped note `role="status"` and announced through the live region. | chat-ui "T8"; E2E keyboard (focus after Stop), feedback (thanks focused), appointment (confirmation focused) |
| T9 | "Incomplete, not checked" note when streamed text has no confirmed answer (error or stopped). | chat-ui "T9"; E2E chat-flows mid-stream error and Stop |
| T10 | `readSseStream` idle timeout 45 s (any bytes reset it, keep-alives included) -> `timeout` error; `safeFetch` deadline 20 s for JSON calls (body included), 45 s for the chat headers. | sse-parser "T10", api "T10", run-turn "T10" |
| T11 | `app/[locale]/error.tsx` (localised, emergency/crisis/front-desk numbers fetched from GET /hospital, `retry()`); layout serialises only `ErrorPage` messages; citation and attribution dates validated as real calendar dates; drawer date formatting cannot throw. | chat-ui "T11", events "T11", validate "T11", attribution "T11"; E2E chat-contract (drawer with an impossible date) |
| T12 | `telHref` drops the "(0)" trunk prefix of international numbers. | api "T12" |
| T13 | Non-sticky safety events render inside their turn (`turn-safety`, `role="alert"`). | reducer "T13", chat-ui "T13" |
| T14 | Client phone/e-mail rules = server's; submission errors explained by code (invalid input, rate limit, unavailable, expired, network); `Idempotency-Key` header, same key for an unchanged retry. | form-validate "T14", api "T14", chat-ui "T14", mock-scenarios "T3" |
| T15 | `done` without answer or form -> `no_answer` error with Retry (no blank bubble). | reducer "T15", chat-ui "T5/T15" |
| T16 | Server lists de-duplicated at the parse boundary (citations by n, fields by name, options, departments, crisis lines, safety contacts, attribution sources); handoff contacts keyed by role, licence conditions by index. | events "T16", api "T16", attribution "T16" |
| T17 | `asHttpUrl` refuses user info (`https://trusted@evil/`). | validate "T17" |
| T18 | Questions-left: seeded from the session, -1 on `meta`, server value on `done`, 0 on `session_exhausted`; a blocked send says why (connecting / busy / no questions left / too long) in a live region; sources page `lang`/`dir` from the text (French names and attribution lines); spell-check, autocorrect and Grammarly off on every health text field. | reducer "T18", chat-ui "T18", text-language "T18"; E2E site (spellcheck attribute) |

Checks (memory shared with an index build, so chromium-desktop only for now, 1 worker):
typecheck 0, eslint 0/0, Vitest **282/282** (was 168; coverage statements 94.6%, branches 90.5%).
`API_ORIGIN=http://127.0.0.1:4010 next build`: 0 warnings. E2E chromium-desktop on the final build
(2026-11-17, 1 worker, retries 0): **67/67 passed** (was 55: + chat-contract.spec.ts 3 tests x 3 locales,
+ one T1 test per locale), CSP violations 0 over 67 tests, axe serious/critical 0 over 33 axe runs.
Report: test-results/measure/e2e-report-run6-chromium-desktop.json (test-results/e2e-report.json is still
the 16 Nov full-matrix report). The full matrix (firefox, webkit, mobile) waits for the lead's go-ahead.

Chat route JS (`npm run measure:js`): /en|fr|ar/chat **183.7 kB gzip** (14 scripts, 596.4 kB raw), budget
200; /en 209.2 kB (not gated). The first build measured 190.1 kB: the new `[locale]/error.tsx` boundary is
part of the layout and Turbopack duplicated its imports (API client + event parser, icon module via
ContactLink) into a separate chunk. Fixed: the boundary loads the API client with `import()` only once an
error is shown, and draws its call links without the icon module (error chunk 9 kB -> about 2.6 kB gzip).
The rest of the growth over run 5 (177.5) is the T1-T18 code itself. Lighthouse not re-run: the empty
chat page's layout is unchanged (the composer's new status line is `empty:sr-only`).

Open (not web): the API does not read `Idempotency-Key` yet (POST /appointments); the client sends it.

## Open issues

- Playwright's Firefox on Windows can crash the content process after an axe-core run ("Page
  crashed"). Worked around in the landing test (run 4). It happened once more, in the appointment-form
  test on the 12:08Z run, and not in the final run. It is a Playwright/Firefox problem, not app behaviour.
- SEO 54 is by design (noindex). Set SITE_URL in deployment so canonical/hreflang use the real host.

## Next step

Run 6: full Playwright matrix (chromium, firefox, webkit; desktop and mobile; 1 worker) once the lead
says memory is free, then update the numbers above and the review's Status column. Earlier note: UI track complete. For the lead: review and commit the run 5 changes (web/src/lib/chat/demo-mode.ts,
web/tests/unit/demo-mode.test.ts, web/src/components/chat/{Composer,ChatApp}.tsx,
web/src/components/chat/hooks/useChatController.ts, web/src/lib/site.ts, this file).
