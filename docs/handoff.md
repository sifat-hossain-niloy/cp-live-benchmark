# Reviewer handoff — October 23, 2026

[Public preview](https://sifat-hossain-niloy.github.io/cp-live-benchmark/) ·
[Setup and commands](../README.md) · [Methodology](methodology.md)

## What is ready

The seven infrastructure phases are implemented: collection/statement parsing/SQLite,
pinned Docker judging and measured-baseline calibration, hash-bound approval and verification,
four provider adapters, durable response caching and conservative budgets, statistical
scoring, a static leaderboard, and reproduction documentation. GitHub Actions tests before
publishing the committed safe snapshot to Pages.

Initial collection since September 1, 2026 found 94 candidates. Three interactive tasks were
excluded before that count. Of 60 parsed statements, three image-bearing candidates were
then excluded (`2275E`, `2274A`, `2273B`), leaving **91 candidates and 57 private scaffolds**.
All 60 cached statements have nonempty legend, input, and output sections. Twelve statements
were flagged as potentially multi-answer; review that classification and implement the
appropriate custom checker before approval.

The 57 non-excluded scaffolded problems span ratings 800–2000:

| Division | Draft problem directories |
| --- | ---: |
| Div. 1 | 6 |
| Div. 1 + Div. 2 | 9 |
| Div. 2 | 14 |
| Div. 3 | 18 |
| Educational | 10 |

These are starter directories, **not completed generators, approved tests, accepted
references, or verified benchmark problems**. Their draft programs intentionally fail.
The published site has no fabricated scores. No paid model calls have been made.

## Required evidence before a scored study

1. Select 40–60 candidates with an appropriate spread of difficulty and divisions. The
   existing 57 private directories are a practical starting set; harder candidates remain
   in SQLite and the public registry. The initial inventory is in
   [collection-2026-10-23.md](collection-2026-10-23.md).
2. Supply known Accepted reference source and independently implement/review the brute,
   exact validator, seeded generator, and checker. Everything belongs under gitignored
   `problems/ID/`. The parsed statement and `REVIEW.md` are already there. Edit the
   generation plan in `meta.json`; do not weaken the 500-small, 5-max, or 20–80-suite gates.
3. Confirm source equality and run `attest-reference`, then `approve`. Source attestation
   is a human check, separate from the API's Accepted verdict check. Existing CLI gates
   prevent absent provenance, changed references, and stale approvals from entering scores.
4. Supply measured, input-matched calibration baselines with evidence. A maximum CF
   submission time over unknown official tests is not an input-matched CPU baseline.
   Run `calibrate`, then `verify` with the calibrated image. Every problem must pass.
5. Fill model IDs, cutoffs with source URLs, release dates, sampling, and flat price ceilings
   in `models.yaml`. Four provider slots are present; no actual model facts were guessed.
   Supply credentials in shell environment variables. Run `cflive models` before evaluation.
6. Evaluate with a deliberate budget and sample count, inspect private reports, run `score`,
   then `build-site --save-snapshot`. Review the public JSON and commit/push it. Pages
   deployment is gated on CI. Start with a small budget to exercise live provider contracts;
   provider adapters have offline schema tests but no live smoke calls yet.

## Private local state

- `data/cflive.sqlite3`: candidate metadata, normalized tags, schema migrations, approvals,
  prompt/generation/judgment/run tables.
- `data/html/`: 60 successful raw pages, never published.
- `data/statements/`: 60 parsed statements, never published.
- `problems/`: 57 draft directories; never committed.
- `artifacts/`: compiled sandbox programs and local QA artifacts; never committed.
- `data/calibration.json`: not present until measured baselines are supplied.
- `models.yaml`: tracked incomplete configurations; intentionally refused by `eval`.
- `site/snapshots/latest.json`: intentionally public, allowlisted metadata; safe to review
  and version. It contains no statements, hidden tests, generators, raw responses, or code.

Back up the private directories separately before moving machines. A Git clone alone
reproduces the code and public snapshot, not the unpublished test corpus or evaluation data.

## Verification performed

The automated suite covers collection filtering/rate limits, parsing/LaTeX/samples/images,
checker semantics, real sandbox verdicts and security, source/approval hash invalidation,
verification failures with preserved inputs, paid-response caching, uncertain billing,
pre-call budgets, incomplete-group exclusion, fake-provider exclusion, and public-export
privacy. Synthetic statistical tests recover known skill and validate cluster bootstrap
behavior. Browser and Python bootstrap results match on a fixed fixture. Frontend tests,
TypeScript checks, and the production build pass.

Browser QA exercised navigation, a rating-band filter (1400 returned six candidates), a
problem detail/Codeforces link, light and dark themes, and desktop/mobile layout. A mobile
header overflow found during QA was fixed. Charts are loaded separately from the initial
application bundle. The public site remains a preparation preview until the evidence above
is supplied.

## Material limitations

The 40–60 verified-problem / 3–5-model target is still pending the required evidence.
No owner approvals, Accepted reference source, calibration baselines, or model facts were
fabricated to meet the target. Each test uses a fresh Docker container, so 500 differential
cases can take substantial time. Local image IDs are immutable but not registry-pullable;
image platform and compiler versions are recorded, and each machine requires calibration.
The static site supports current result exploration; multi-turn evaluation, weekly
collection, and automatic failure clustering are outside this MVP.
