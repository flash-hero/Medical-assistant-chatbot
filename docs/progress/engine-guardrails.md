# Progress: ENGINE-GUARDRAILS track

Owned directories: `app/guardrails/**`, `config/safety/**`, `evals/safety/**`, `tests/app/guardrails/**`.
Metrics file: `C:\dev\ausculta-data\reports\engine-guardrails.metrics.json`.

## Deliverables

| # | Deliverable | Status | Numbers |
|---|---|---|---|
| 1 | Tests for every guardrail module, coverage >= 90% for `app/guardrails` | done | final run 5: 603 tests pass; `app/guardrails` line 99.0% (1342/1355), branch-combined 98.4% |
| 2 | Safety evaluation sets (EN/FR/AR) in `evals/safety/sets/` | done | 925 items (EN 307, FR 307, AR 311); held-out split frozen (186 ids) |
| 3 | Deterministic evaluator writing `engine-guardrails.metrics.json` | done | 50 tests (`test_safety_eval_{sets,lexicon}.py`), `evals/safety` coverage 98%; baseline below |
| 4 | Lexicon tuning (recall >= 90%, hard-negative FP <= 10%, held-out 20%) | partial | emergency / self_harm tuned: tune 100% everywhere; held-out emergency 100/100/75%, self_harm 46/58/83% (en/fr/ar); harm_to_others, abuse_disclosure, injection never tuned |
| 5 | Fixes requested by engine-api: (a) combination test, (b) follow-up flagged as emergency | done | +38 tests; see below |
| 6 | Final metrics on the final lexicon (`engine-guardrails.metrics.json`, source `lexicon_only`) | done | 94 records; tune and held-out separate; gates below |

## Eval sets (deliverable 2)

`evals/safety/sets/{en,fr,ar}/{emergency,self_harm,harm_to_others,abuse_disclosure,injection,hard_negative}.jsonl`

| lang | emergency | self_harm | harm_to_others | abuse_disclosure | injection | hard_negative |
|---|---|---|---|---|---|---|
| en | 60 | 60 | 30 | 30 | 62 | 65 |
| fr | 60 | 60 | 30 | 30 | 62 | 65 |
| ar | 62 | 61 | 30 | 30 | 60 | 68 |

- Arabic varieties are in the id (`ar-emg-{msa,ma,dz,tn,azi}-NN`): MSA, Moroccan / Algerian / Tunisian Darija,
  Arabizi (azi, incl. French/English code-switching).
- Injection: direct override, prompt leak, roleplay/DAN, fake role tags, markdown/HTML exfiltration, Unicode
  smuggling (tag chars, zero-width, bidi override, fullwidth, leetspeak, variation-selector bytes; invisible
  characters are stored as JSON `\u` escapes), multi-turn (`history`).
- Hard negatives: informational questions, historical / third-person events, idioms ("this traffic is killing
  me", "mort de rire", "الزحمة قتلتني"), front-desk questions naming the emergency department, and benign
  "ignore / forget / repeat / your instructions" probes for injection false positives.
- Written before looking at the lexicon files or the seeds. 14 / 925 items turned out to equal a seed phrase
  exactly (canonical short phrases such as "I want to kill myself"); kept and disclosed.
- Held-out split: `evals/safety/sets/splits.json`, 20% of every lang x category file by SHA-256 of the id,
  frozen with `python -m evals.safety.sets --make-splits`. Tuning only looks at `tune` failures.

## Fixes made while testing (deliverable 1)

- `claims.py`: negation/referral cues were substrings, so "not" inside "Another", "ne" inside "Une", "pas" inside
  "passer", "لا" inside "خلال" silently suppressed real dosing / stop-treatment violations. Cues are now whole words;
  Arabic claim verbs are word-bounded ("توقف" no longer matches inside "لا تتوقف"). "You may have heard/noticed"
  is no longer flagged as a diagnosis.
- `lexicon.py`: worst-case scan of a 2,000-char message went from ~280 ms to ~110 ms (tokens were re-normalised
  for the Arabizi skeleton; historical regex re-run per hit). New `LexiconMatcher.assess()` returns signals and hit
  languages from one scan; `GuardRouter.precheck` used to scan twice (~560 ms worst case). Public API unchanged.
- ruff check / format clean on all track directories (was 57 findings, 11 unformatted files).

## Evaluator and baseline (deliverable 3)

`python -m evals.safety.lexicon_eval [--out PATH] [--no-write] [--show-failures {none,tune,all}]` runs every
user turn of every item through the engine's own deterministic path (`process_ingress` then
`GuardRouter.precheck`, built as `app/pipeline/factory.py` builds it, FakeLLMProvider, no network). An item's
detected kinds are the union over its turns. Failures are printed for the `tune` split only by default.
Records (source `lexicon_only`, `free_tier: false`): `{emergency,self_harm,harm_to_others,abuse_disclosure}_detected`
(count form, full set, what the `safety.*` gates read), `lexicon_recall` per lang x kind x split,
`hard_negative_false_positive_rate`, `injection_detection_rate`, `injection_false_positive_rate` per lang x split,
`lexicon_recall_by_variety` for Arabic.

Baseline (lexicon as of run 3, before any tuning; saved to `reports/engine-guardrails.baseline.json`, a name the
gate runner does not read):

| lang | split | emergency | self_harm | harm_to_others | abuse_disclosure | injection | hard-neg FP |
|---|---|---|---|---|---|---|---|
| en | tune | 24/49 49.0% | 26/48 54.2% | 2/24 8.3% | 10/24 41.7% | 37/50 74.0% | 4/52 7.7% |
| en | heldout | 7/12 58.3% | 4/13 30.8% | 1/6 16.7% | 3/6 50.0% | 9/12 75.0% | 2/13 15.4% |
| fr | tune | 18/49 36.7% | 23/49 46.9% | 3/24 12.5% | 4/24 16.7% | 22/50 44.0% | 7/52 13.5% |
| fr | heldout | 9/12 75.0% | 5/12 41.7% | 0/6 0.0% | 2/6 33.3% | 6/12 50.0% | 0/13 0.0% |
| ar | tune | 18/51 35.3% | 20/49 40.8% | 4/24 16.7% | 11/24 45.8% | 20/48 41.7% | 1/54 1.9% |
| ar | heldout | 3/12 25.0% | 9/12 75.0% | 0/6 0.0% | 4/6 66.7% | 4/12 33.3% | 1/14 7.1% |

The seed sets were 100% detected, the independent eval sets ~35-55% for emergency / self-harm: the lexicon was
fitted to its seeds.

## Lexicon tuning (deliverable 4)

Method: only `tune` failures were read (`--show-failures tune`, and a scratch lister that prints tune-split items
only). Additions are written as families of phrasings, not copies of the failing sentences:
- `combinations` sections (co-occurrence, any order, 12-token span) in `emergency.yaml` and `self_harm.yaml` for
  en / fr / ar / arabizi: chest pain wording, stroke signs, breathing, anaphylaxis, infants, head injury, falls,
  poisoning / overdose (quantity + substance), bleeding, stab wounds, burns, seizures, collapse, pregnancy,
  meningitis; self-harm intent + method, stockpiled pills, bridges / roofs, goodbye letters, self-injury acts.
- terms: lethality and method questions, ideation and goodbye phrasings, Darija / Algerian / Tunisian /
  Arabizi first-person forms ("ننتحر", "نكمل على روحي", "kanfker nntahr").
- context cues: hedges are not negations ("not sure", "sans arrêt", "لا أعرف"); spelled-out "il y a cinq ans"
  is historical; question frames and fiction ("how can I tell if", "why do", "what happens", "en quoi
  consiste", "in the TV series", "dans la série") are informational; generic "someone" / "quelqu'un" / "femme"
  (woman or wife) no longer count as personal references; "having a stroke" moved to condition terms.
- exclusions: talking about the topic or its prevention ("suicide prevention", "sujet de l'automutilation",
  "موضوع إيذاء النفس"), routine medication ("all my pills this morning"), ward names ("stroke unit").
- code: `lexicon_cues.is_informational` also treats a French inversion anywhere in the clause as a question
  ("une surdose abîme-t-elle le foie"); `lexicon_combos.token_forms` splits ما / لا glued to و / ف
  ("وما بقاش كيجاوب"). Both with unit tests.
- Fresh probes written after tuning (not from either split) exposed weaker English self-harm and Arabic
  generalisation; fixed generically and locked in `tests/app/guardrails/test_guard_lexicon_tuned.py` (51 tests).

Tune split after tuning: emergency 49/49, 49/49, 51/51; self_harm 48/48, 49/49, 49/49 (en, fr, ar); hard-negative
FP 0/52, 0/52, 0/54. Disclosure: one intermediate evaluator run printed the held-out summary row (numbers only,
no items) before I switched to tune-only output; no tuning decision used it.

## Cancellation fix (requested by engine-api)

- `router.py` (guard classifier call) and `groundedness.py` (verify decide + fallback) now use
  `async with asyncio.timeout(...)` instead of `asyncio.wait_for`: on Python 3.11 `wait_for` returns the inner
  result and drops an outer `task.cancel()` when the inner call completes in the same loop iteration.
- Regression test `tests/app/guardrails/test_guard_cancellation.py` parks the model call on a future, then
  resolves it and cancels the turn back to back: 4 of its 5 tests fail against the pre-fix modules (checked by
  loading the HEAD versions in place of the fixed ones) and all 5 pass with the fix.
- ruff check / format clean again on all track directories (the run-3 lexicon combination work had left 6
  findings and 3 unformatted files).

## Final metrics (run 5, final lexicon)

`python -m evals.safety.lexicon_eval --show-failures none` wrote 94 records (source `lexicon_only`) to
`C:\devusculta-dataeports\engine-guardrails.metrics.json`. The lexicon files were not changed in run 5
(`git diff config/safety` empty). Disclosure: the evaluator's summary always prints the held-out rows; it was run
once at the start of run 5 (to check the state) and once to write the records; no tuning happened after either.

| lang | split | emergency | self_harm | harm_to_others | abuse_disclosure | injection | hard-neg FP (safety kinds) | hard-neg FP (injection) |
|---|---|---|---|---|---|---|---|---|
| en | tune | 49/49 100% | 48/48 100% | 2/24 8.3% | 10/24 41.7% | 37/50 74.0% | 0/52 0.0% | 1/52 1.9% |
| en | heldout | 12/12 100% | 6/13 46.2% | 1/6 16.7% | 3/6 50.0% | 9/12 75.0% | 2/13 15.4% | 0/13 0.0% |
| fr | tune | 49/49 100% | 49/49 100% | 3/24 12.5% | 4/24 16.7% | 22/50 44.0% | 0/52 0.0% | 0/52 0.0% |
| fr | heldout | 12/12 100% | 7/12 58.3% | 0/6 0.0% | 2/6 33.3% | 6/12 50.0% | 0/13 0.0% | 0/13 0.0% |
| ar | tune | 51/51 100% | 49/49 100% | 4/24 16.7% | 11/24 45.8% | 20/48 41.7% | 0/54 0.0% | 0/54 0.0% |
| ar | heldout | 9/12 75.0% | 10/12 83.3% | 0/6 0.0% | 4/6 66.7% | 4/12 33.3% | 0/14 0.0% | 0/14 0.0% |

Held-out vs baseline: emergency en 7/12 -> 12/12, fr 9/12 -> 12/12, ar 3/12 -> 9/12; self_harm en 4/13 -> 6/13,
fr 5/12 -> 7/12, ar 9/12 -> 10/12; hard-negative FP unchanged (en 2/13, fr 0/13, ar 1/14 -> 0/14).
harm_to_others, abuse_disclosure and injection are identical to the baseline: they were never tuned.
Arabic by variety (full set, emergency / self_harm): MSA 25/27, 24/25; Moroccan 10/10, 9/10; Algerian 7/8, 8/8;
Tunisian 8/8, 8/8; Arabizi 10/10, 10/10.

Reading: tune 100% against held-out 46-83% for self-harm means the self-harm additions fitted the tune phrasings
and do not generalise; emergency generalises in en/fr, less in ar. The lexicon is a fast first line; recall at
gate level needs the classifier (verdict = lexicon OR classifier), which this lexicon-only run does not measure.

`python -m evals.run --only safety. --allow-missing` (lexicon only, full set): PASS 0, FAIL 4, PROVISIONAL 2,
MISSING 1. emergency en 61/61 and fr 61/61 PROVISIONAL (n=61, gate written for 300); emergency ar 60/63 (0.952),
self_harm en 54/61 (0.885), fr 56/61 (0.918), ar 59/61 (0.967) FAIL against 0.98; `safety.template_first` has no
record (pipeline metric, not this track).

## Fixes requested by engine-api (run 5)

(a) Lexicon-combination test failure (`test_guard_lexicon_combo_scan.py::test_real_lexicon_has_combinations`).
Root cause: run 3 landed the combination loader (`lexicon_combos.py`) and this test before any `combinations`
data existed in the lexicon YAMLs; engine-api ran its suite in that window. The tuning in run 4 added the data
(155 combinations: emergency en 39 / fr 38 / ar 27 / arabizi 12, self_harm en 14 / fr 11 / ar 11 / arabizi 3),
so the test passes on HEAD. Regression tests made it meaningful instead of `count > 0`
(`test_guard_lexicon_combo_scan.py`, +11): both files have combinations for every language (en, fr, ar,
arabizi); the matcher loads exactly the combinations in the files; 8 fresh probes (written for the test, not from
the eval sets) are caught by a combination, not a term, in each kind x language.

(b) Front-desk question flagged as an emergency right after an emergency message (live, engine-api run 2).
- Deterministic detection already looked at the current message only (`GuardRouter.precheck(text)`; history is
  never scanned); locked by tests in all languages.
- The guard classifier was the cause: its risk questions asked whether "the user" describes an emergency
  "happening now or very recently", with earlier messages in the payload. `guard_classifier.py` now appends
  `LATEST_MESSAGE_SCOPE` to every risk question (judge only the message marked role="current"; earlier
  messages only help to understand what it refers to; a risk described only earlier does not count unless the
  latest message describes it, adds to it or asks about it) and `POPULATION_SCOPE` to every population
  question; the GUARD_FALLBACK system prompt carries the same two sentences. History still goes to the model.
- The banner stays through the sticky flag (`session_sticky` in `verdict.risks`, not in `current`), which is
  the pipeline's job; no new detection.
- `tests/app/guardrails/test_guard_followup.py` (25 tests): en / fr / ar / arabizi / self-harm sessions; a fake
  GUARD decider that reads the whole conversation for an unscoped question and only the current block for a
  scoped one. Against the HEAD (pre-fix) questions 8 of the 25 fail, including the 5 route tests
  "front-desk follow-up is not a new detection"; all 25 pass with the fix. Follow-ups that add to the risk are
  still detected.
- Not changed (outside this track): `config/prompts/guard.v1.yaml`, and `PROMPT_VERSION` / `prompt_hash` in
  `app/pipeline/prompts.py`. The scope text lives in code, so the prompt hash does not change with it.

Also fixed: `python -m evals.safety.lexicon_eval` crashed with UnicodeEncodeError on a cp1252 Windows console
when an Arabic failure line was printed, before the metric records were written. `console_safe()` now escapes
unencodable characters (regression test in `test_safety_eval_lexicon.py`, +2).

## Log

- 2026-11-16: resumed. Found 15 guardrail modules on disk (from the cut-off run), only pii/ingress tested.
- 2026-11-16: deliverable 1 done. Seed sets (`evals/safety/seeds/*.yaml`) are 100% detected / 0 false positives,
  so they were the lexicon's training data: the new eval sets must be written independently of them.
- 2026-11-16 (run 3): re-verified deliverable 1 (417 passed, 98%). Wrote the 925-item eval sets and froze the split.

- 2026-11-16 (run 4): wait_for -> asyncio.timeout fix + regression test done. Found from run 3 (committed in
  the snapshot, not logged): `lexicon_combos.py` (co-occurrence "combinations") wired into `lexicon.py` with
  tests, but no `combinations` section in the lexicon YAMLs yet, so `test_real_lexicon_has_combinations` fails
  until tuning adds some. The evaluator `evals/safety/lexicon_eval.py` exists without tests.

- 2026-11-16 (run 5): fixes (a) and (b) with regression tests; evaluator console crash fixed; final metrics
  written; mypy type-only fix in `injection.py` (`Signal.source` literal). Final: 603 guardrail tests pass,
  `app/guardrails` line coverage 99.0% (1342/1355; branch-combined 98.4%), `evals/safety` 99%; ruff check and
  format clean; mypy clean on `app/guardrails` and `evals/safety`; tests/app/pipeline + tests/app/api 261 passed.

## Next step

Track complete. For the lead: review/commit. Open items: move `LATEST_MESSAGE_SCOPE` / `POPULATION_SCOPE` into a
`config/prompts/guard.v2.yaml` and bump `PROMPT_VERSION` (the prompt hash does not cover code-level text); re-run
the engine-api live session (emergency then "What are the visiting hours?") to confirm (b) on the real model;
measure safety recall through the full pipeline (lexicon OR classifier) for the `safety.*` gates; harm_to_others,
abuse_disclosure and injection lexicons were never tuned.
