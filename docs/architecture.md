# CF-Live implementation plan

The user authorized autonomous implementation, overriding the initial design-approval wait.
Human approval of problem assets and documented model cutoff evidence remain data-quality gates.

## Repository

`src/cflive/`: typed Python CLI and pipeline modules. `judge/`: pinned Docker image and
resource supervisor. `prompts/`: versioned templates. `tests/`: synthetic fixtures and
offline tests, with explicitly enabled real Docker security tests. `site/`: React,
TypeScript, Vite, Tailwind, and Recharts static client. `docs/`: methodology and operations.
`.github/workflows/`: CI and GitHub Pages deployment. `uv.lock` and `site/package-lock.json`
pin dependencies. Gitignored `data/`, `problems/`, and `artifacts/` contain all private data.

## Storage

SQLite schema version 2 lives in `src/cflive/db.py`. Foreign keys and WAL are enabled.
`contests` stores API objects and UTC starts; `problems` stores identity, metadata,
exclusions, scrape status; `problem_tags` is normalized. `test_sets` binds approvals and
verification reports to artifact and hidden-test hashes. `models` stores sourced model
configuration; `prompts` content-addresses exact rendered prompts. `runs` records budgets,
configuration snapshots, judge identity and toolchain; `generations` caches responses by
model/problem/prompt/config/sample; `judgments` binds results to exact run and test version.
Public export uses an explicit field allowlist, never a database dump.

## Judge

Compile and execution are separate, non-root Docker containers. Each test starts fresh.
Root is read-only; only a size-limited `/work` tmpfs is writable. No network, dropped
capabilities, no privilege escalation, 64 PIDs, one CPU, equal memory/swap caps, capped
stdout and stderr, CPU and wall-clock deadlines. A root-owned Python supervisor measures
CPU and peak RSS using `wait4`, reads cgroup OOM counters, and returns structured results.
Container identity is resolved to an immutable image ID plus registry digest and recorded
with exact compiler versions. Local-only image IDs are explicitly labeled.

Approval hashes reference, brute, generator, validator, checker, statement, and metadata.
Any change invalidates eligibility. Verification requires official samples, >=500 seeded
small cases plus edges, validators, max-size CPU performance, and a final 20–80-test set
with >=5 max-size tests. Reference provenance must be checked; drafts cannot enter scores.

## Phases and acceptance

1. Collect, scrape, schema, offline tests; collect live inventory and report counts.
2. Docker judge, calibration identity, real verdict and security tests.
3. Scaffold, approval, provenance and verification, mutation-invalidation tests.
4. Documented provider adapters, deterministic caching, conservative budget reservations.
5. Balanced per-problem pass@1, logistic skill MLE, problem-level bootstrap, common window.
6. Safe JSON export, responsive static site and methodology, CI/Pages deployment.
7. Setup/reproduction/limitations documentation and a clear handoff of missing evidence.

Migration 2 adds durable generation reservations and recovery diagnostics.

Each phase ends in passing applicable tests and a Git commit. Never fabricate benchmark
scores, approvals, model metadata, accepted references, or verification coverage to meet
the volume target. A published empty state is valid infrastructure, not a completed study.
