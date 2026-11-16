# Progress: ENGINE-GUARDRAILS track

Owned directories: `app/guardrails/**`, `config/safety/**`, `evals/safety/**`, `tests/app/guardrails/**`.
Metrics file: `C:\dev\ausculta-data\reports\engine-guardrails.metrics.json`.

## Deliverables

| # | Deliverable | Status | Numbers |
|---|---|---|---|
| 1 | Tests for every guardrail module, coverage >= 90% for `app/guardrails` | done | 417 tests pass; `app/guardrails` coverage 98% (branch), re-verified 2026-11-16 |
| 2 | Safety evaluation sets (EN/FR/AR) in `evals/safety/sets/` | done | 925 items (EN 307, FR 307, AR 311); held-out split frozen (186 ids) |
| 3 | Deterministic evaluator writing `engine-guardrails.metrics.json` | in progress | |
| 4 | Lexicon tuning (recall >= 90%, hard-negative FP <= 10%, held-out 20%) | not started | |

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

## Log

- 2026-11-16: resumed. Found 15 guardrail modules on disk (from the cut-off run), only pii/ingress tested.
- 2026-11-16: deliverable 1 done. Seed sets (`evals/safety/seeds/*.yaml`) are 100% detected / 0 false positives,
  so they were the lexicon's training data: the new eval sets must be written independently of them.
- 2026-11-16 (run 3): re-verified deliverable 1 (417 passed, 98%). Wrote the 925-item eval sets and froze the split.

## Next step

Evaluator `evals/safety/lexicon_eval.py` (+ tests in `tests/app/guardrails/test_safety_eval*.py`), first
baseline metrics, then tune on the `tune` split only.
