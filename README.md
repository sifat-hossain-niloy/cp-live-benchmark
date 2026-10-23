# CF-Live

Contamination-resistant Codeforces evaluation infrastructure, with reviewed private tests
and a static public leaderboard.

[Live site](https://sifat-hossain-niloy.github.io/cp-live-benchmark/) ·
[Methodology](docs/methodology.md) · [Reviewer handoff](docs/handoff.md) ·
[Architecture](docs/architecture.md) · [Initial inventory](docs/collection-2026-10-23.md)

**Status: infrastructure preview, not a completed benchmark study.** The initial live
collection found 94 candidates since September 1, 2026. Sixty statements were parsed;
three image-bearing candidates were then excluded, leaving 91 candidates and 57 private
draft problem directories. No problem has been human-approved or verified, no model
metadata has been invented, and no paid model evaluations have run. The public site
shows those preparation counts and leaves model scores empty.

## Setup

Requirements: Python 3.11+ (3.12 recommended), [uv](https://docs.astral.sh/uv/), Node
22.12+ (24 recommended), npm, and Docker with cgroup v2. Linux and Docker Desktop on macOS
are tested. Docker must be running; never run submissions directly on the host.

```sh
git clone https://github.com/sifat-hossain-niloy/cp-live-benchmark.git
cd cp-live-benchmark
uv sync --frozen --extra dev --python 3.12
npm ci --prefix site
uv run cflive --help
uv run cflive judge-build
uv run cflive judge-info
```

All commands operate in the current project by default. Use `cflive --root /path/to/project`
to select another workspace. The editable installation exposes `cflive`; examples use
`uv run` to select the locked environment.

## Collect and prepare problems

```sh
uv run cflive collect --since 2026-09-01
uv run cflive inventory
uv run cflive scrape --limit 60
uv run cflive scaffold 2259A
```

Collection is idempotent and refreshes previously unrated records. Only finished, eligible
contests enter the candidate pool. Combined Div. 1/2 rounds remain a separate division.
HTML is fetched no faster than one page per three seconds and cached; existing pages
are never fetched again. API requests are separated by at least 2.1 seconds. Failed
scrapes are resumable. `--problems ID --problems OTHER_ID` restricts scraping.

The HTTP parser is the default. If browser rendering is needed:

```sh
uv run playwright install chromium
uv run cflive scrape --browser --limit 10
```

An access challenge is an error, never a statement. The scraper conservatively excludes
all statement images and flags multi-answer wording for a custom checker.

`scaffold` creates `problems/ID/` without overwriting existing work:

| Asset | Contract |
| --- | --- |
| `statement.json` | Private parsed statement, limits, samples, and notes |
| `reference.cpp` | Known Accepted C++17 source, with source-hash-bound provenance |
| `brute.py` or `brute.cpp` | Independent small-input oracle; stdin → stdout |
| `gen.py` | `--mode MODE --seed INTEGER`; stdout is one complete valid test input |
| `validator.py` | Read stdin, exit 0 only if every exact constraint holds |
| `checker.py` | Required for multi-answer tasks; protocol below |
| `meta.json` | Limits, checker, provenance, seed/count plan, status, and approval |
| `REVIEW.md` | Private review checklist |

Initial assets are **drafts that fail intentionally**, not plausible-looking accepted
solutions. Replace them with real implementations. Generator modes are `small_random`,
`edge`, `max_size`, and `adversarial`. Set adversarial counts/patterns when relevant.
Use `brute.cpp` for a faster oracle if needed; it takes precedence over `brute.py`.

For ordinary unique-output tasks, `meta.json` supports `exact`, `tokens`, or `float:1e-6`.
The float checker requires finite values and applies `abs(actual-expected) <= epsilon *
max(1,abs(expected))` token-wise. `exact` includes trailing whitespace; `tokens` ignores it.
Custom checkers receive three paths in order: input, reference answer, contestant output.
They must validate feasibility and optimal objective and print a JSON object such as
`{"accepted": true, "message": "valid optimum"}`. Exceptions are infrastructure failures.

## Reference provenance, approval, and verification

After reviewing a known Accepted reference, attest that the local source equals it:

```sh
uv run cflive attest-reference PROBLEM_ID SUBMISSION_ID CF_HANDLE --reviewer YOUR_NAME
uv run cflive approve PROBLEM_ID --reviewer YOUR_NAME
uv run cflive verify PROBLEM_ID
```

The API independently confirms the submission ID, matching problem, C++ language, and
Accepted verdict in the user's latest 10,000 submissions. **Source equality is your
attestation** because the Codeforces API does not expose source code. An editorial
reference can instead have manually reviewed `kind: editorial` provenance in `meta.json`
with `verified: true`, `url`, `attested_by`, `attested_at`, and the exact local reference
`source_sha256`. This is an assertion about a known Accepted implementation, not permission
to label unsubmitted AI-generated code as Accepted.

Approval hashes all assets. Any change to constraints, generators, validators, checkers,
reference, brute, or provenance invalidates eligibility. Approval is a human operation;
automated scaffold creation never approves a problem.

Verification checks every generated input, official samples, >=500 small random
reference/brute comparisons and all edges, and >=5 max-size cases within half the
calibrated time allowance. The final suite must have 20–80 cases. Reports, failing inputs,
and hidden suites stay in `problems/ID/hidden/`. Interrupted or failed re-verification
revokes the previous verified state. Changing hidden tests also invalidates eligibility.
Verification starts at factor 1 if calibration is absent; production evaluation requires
re-verification with the measured calibrated judge identity.

## Calibration

Prepare a private JSON array containing `reference_path`, `input_path`, `cf_cpu_ms`, and
`evidence_url` for each measured, input-matched reference baseline. `cf_cpu_ms` is measured
CPU on the comparison machine for that input, not a guessed constant or the maximum time
from an unknown official test suite.

```sh
uv run cflive calibrate data/baselines.json --machine-id YOUR_MACHINE_ID
```

The command runs each baseline three times, uses median CPU ratios, and saves
`data/calibration.json`. The evidence, input/source hashes, image ID, platform, compiler
versions, and factor are recorded. Recalibrate after machine, image, or platform changes.
The local image ID is immutable but not registry-pullable; registry digests are also
recorded when available. Verify problems again with this calibration before evaluation.

## Configure models and evaluate

Fill `models.yaml` from primary sources. The four provider entries are intentionally
incomplete. Each needs an exact model ID, display name, provider, training cutoff,
cutoff source URL, release date, sampling, output cap, and flat per-million input/output
prices with their source URL. Do not guess undisclosed cutoffs. If only a month is
specified, use its final day and document the interpretation. The entire cutoff day is
excluded in UTC.

```sh
uv run cflive models
# Set the appropriate credential in your shell, never in tracked files:
# OPENAI_API_KEY, ANTHROPIC_API_KEY, GOOGLE_API_KEY, or OPENROUTER_API_KEY
uv run cflive eval --model CONFIG_NAME --samples 4 --budget 5 --workers 2
# Optionally restrict problems:
uv run cflive eval --model CONFIG_NAME --problems PROBLEM_ID --samples 4 --budget 1
```

The default language is `cpp17`; set `language: python3` to switch the fixed prompt and
judge. Sampling parameters are provider-native allowlisted fields; unsupported model
settings fail explicitly. Anthropic API version defaults to `2023-06-01` and is configurable.
OpenRouter requires an explicit conservative `input_reservation_tokens` billing ceiling.
This setting is not a claim about context limits. Other providers use token preflight counts
plus a formatting margin. Prices must be valid ceilings for the selected flat text workload;
account limits are needed for a strict provider-side billing cap.

Each response is durably cached before judging. Request-affecting settings, prompt content,
model, problem, and sample index identify the slot. Metadata-only changes preserve cached
responses. Provider and judge concurrency are separately bounded. A run snapshot records
parameters, hashes, dates, image identity, compiler versions, costs, and calibration.
Only verified post-cutoff problems are evaluated. Single-shot only: no tools or judge feedback.

Budget reservations prevent scheduling responses whose configured maximum cost exceeds
the remaining budget. Explicit rejections release reservations. Ambiguous timeouts/server
failures retain them and **never automatically replay**. To resume, use the same arguments
plus `--resume RUN_ID`; configuration, budget, prompt, judge, and problem set must match.
Check provider billing/logs before reconciliation:

```sh
# Recover the original provider JSON response, without another model call:
uv run cflive reconcile-generation GENERATION_ID --response data/recovered.json --note 'Provider log evidence'
# OR, only after confirming that the attempt was not billed:
uv run cflive reconcile-generation GENERATION_ID --confirmed-not-billed --note 'Billing evidence'
```

Recovery writes a private audit record. Then rerun evaluation to judge cached responses.
Do not release uncertain reservations merely to make the pipeline continue.

## Score, build, and publish

```sh
uv run cflive score
uv run cflive score --common
uv run cflive score --common --tag math --rating-band 1400 --since 2026-09-01
uv run cflive build-site
npm --prefix site run dev
```

The site has individual/common windows, date slider, rating/tag/division filters,
model selection, difficulty profiles, tag heatmaps, verdict distributions, per-problem
outcomes, methodology, light/dark mode, and a mobile layout. Client filters recompute the
same score formulas and deterministic 1,000-resample bootstrap as Python. No backend is needed.

The score averages accepted/sample fractions over problems. Logistic skill is a performance
proxy, with whole-problem bootstrap intervals and unbounded saturated estimates. Fewer than
20 scored or eligible problems is flagged as insufficient data. Only complete sample groups
from the latest complete or budget-stopped run per model are published. Common comparisons
use the same completed problem IDs, never unequal denominators disguised as a shared window.

Public JSON is an allowlist of metadata and results. It excludes statements, hidden tests,
generators, reference/brute source, raw responses, local paths, and private reports. Model
solution publication is disabled by default. A public title is metadata from the API, not
permission to republish the full statement.

To update GitHub Pages intentionally:

```sh
uv run cflive build-site --save-snapshot
# Review site/snapshots/latest.json before committing.
git add site/snapshots/latest.json
git commit -m 'Publish reviewed benchmark snapshot'
git push
```

`.github/workflows/ci-pages.yml` runs offline tests, real Docker security/verdict tests,
frontend score tests, and the production build before deploying. Actions are pinned by
commit. CI uses only the committed public snapshot; it never sees the private database.
Set Pages to **GitHub Actions** in a fork. The app uses relative assets and hash routes so
repository-path hosting works. `BASE_PATH` can override the Vite base if needed.

## Tests and reproducibility

```sh
uv run pytest -q                         # offline suite; Docker cases explicitly skipped
uv run cflive judge-build
CFLIVE_DOCKER_TESTS=1 uv run pytest -q     # includes real sandbox/security cases
npm --prefix site test
npm --prefix site run build
uv run ruff check
```

No tests call a live Codeforces API or live model. HTTP is mocked; statement fixtures and
model outcomes are synthetic. Real Docker tests use tiny local programs. Integration tests
cover failed verification, stale approvals, changed hidden tests, paid-response replay
prevention, pre-call budgets, incomplete sample exclusion, fake-provider exclusion, and
public-export privacy. Scoring tests recover known synthetic skill and match Python/browser
bootstrap intervals.

Keep private backups of `data/`, `problems/`, and `artifacts/` for reproduction. The SQLite
schema is versioned and migrates at connection time; newer unsupported schemas are refused.
Do not put API credentials in the database, commands, prompts, or committed configuration.

## Limits of this MVP

The intended 40–60 verified problems and 3–5 evaluated models **are not yet achieved**.
They require the owner's accepted references, problem review/approval, measured calibration
baselines, documented model metadata, and provider credentials. The included scaffolds
are a review workspace, not verified tests. Provider contracts are fixture-tested; no live
model API smoke calls or paid experiment have been performed.

Docker startup per test favors isolation over throughput; 500 differential cases involve
many containers and can take substantial time. Calibrated CPU time includes small supervisor
overhead; memory caps include sandbox processes. Curated tests cannot prove correctness,
model cutoffs are disclosures rather than guarantees, and logistic estimates are not
Codeforces ratings. See the [methodology](docs/methodology.md) for interpretation limits.
Multi-turn evaluation, weekly scheduling, and automated failure clustering are intentionally
outside the MVP. Codeforces statements belong to their authors; this project links to them
and is not affiliated with Codeforces.
