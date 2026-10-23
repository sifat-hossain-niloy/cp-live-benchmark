# CF-Live methodology

CF-Live measures single-shot programming performance on recent Codeforces problems.
The current publication is an infrastructure preview. It contains no model scores until
reviewed problem assets and sourced model configurations pass all gates.

## Contamination rule

A contest must start strictly after the entire documented model training-cutoff day in
UTC. Month-level disclosures should use the last day of that month, recording that
interpretation beside the source. A missing cutoff or source URL blocks evaluation.
Contest start, rather than scrape date or model release date, is the contamination timestamp.
Post-cutoff selection reduces risk; it cannot establish that training disclosures are complete
or rule out subsequent exposure, retrieval, or unpublished model updates. Use exact snapshots.

The individual view uses each model's completed post-cutoff problem groups. The common
window uses the intersection of completed problem groups after the latest cutoff among
compared models. Every model in that comparison faces exactly the same problem IDs. Empty
intersections produce empty scores. Date, rating, tag, and division filters apply to both.

## Collection and statements

The Codeforces API's `Contest.type` is the scoring system (`CF`, `IOI`, `ICPC`), not a
contest division. Divisions are conservatively inferred from contest names. Finished
Codeforces Div. 1, 2, 3, 4, and Educational rounds are eligible; team, Gym, April Fools,
special, interactive, and unrated tasks are excluded. Combined rounds have their own
`Div. 1+Div. 2` label. Unrated records are kept privately and refreshed on future collection.

API calls are spaced by at least 2.1 seconds and retry rate limits, transient transport
errors, and server failures with exponential backoff. Statement requests are spaced by
three seconds. Successful raw HTML is cached immutably and parsed locally. Browser
rendering is an optional fallback; access challenges are never cached as statements.
Potentially essential images are conservatively excluded. Multi-answer wording flags a
custom checker requirement, with final interpretation requiring human review.

## Approval and verification

A human checks that the local reference source equals an Accepted solution or a known
Accepted editorial implementation. For submission provenance, the API confirms the actual
Accepted verdict and matching problem; source equality is a human attestation because the
API does not supply submission source. Provenance is bound to the local reference hash.

The reviewer approves the reference, independent brute-force oracle, seeded generator,
exact-constraint validator, custom checker if needed, statement parsing, and metadata.
Approval records the reviewer, time, and artifact hash. Edits invalidate approval.
Local limits, dates, ratings, and tags must match the collected CF source. Source refreshes
invalidate mismatched approval, and run snapshots freeze the selected problem metadata.

Verification requires:

- Every generated input passes the validator.
- The reference matches brute force via the checker on at least 500 small random inputs
  and all configured edge inputs.
- The reference passes all official samples.
- Every max-size reference run uses at most 50% of the calibrated time limit.
- The final private suite contains 20–80 tests: samples, edges, small random inputs,
  at least five max-size tests, and adversarial patterns where relevant.
- Human approval is current, including all assets and provenance.

Exact, token, and finite relative-or-absolute numeric comparators are supported. Custom
checkers receive the input, reference answer, and contestant output in a sandbox. They must
validate feasibility and the optimal objective, not textual identity. They print a JSON
object with a boolean `accepted` field; exceptions and invalid reports are infrastructure
errors rather than wrong answers. Failing inputs and reports remain private. Successful cases are transactionally
checkpointed in SQLite with payload hashes and an exact environment/asset identity. A
failed or interrupted run resumes only matching cases; an unchanged verified suite returns
its prior report. `verify --force` remeasures all cases. Image, machine fingerprint,
compiler, calibration, output-policy, verifier/checker implementation, or approved-asset
changes invalidate reuse. The
machine fingerprint hashes the host identity and Docker daemon ID, CPU allocation, memory
allocation, and kernel version. Published results must still match their frozen suite hash
and judge identity after re-verification.

## Judge and calibration

The base image is pinned by a multi-platform digest. It supplies GCC 12.2.0 and Python
3.11.11; the build asserts both versions. C++17 compilation uses `-O2 -pipe` and a
30-second CPU and wall limit. Python syntax errors are compilation errors.

Every test starts a fresh non-root Docker container with no network, read-only root,
a 192 MB `/work` tmpfs, all capabilities dropped, no privilege escalation, equal memory
and swap limits, 64 PIDs, one CPU, capped combined stdout/stderr (64 MB by default), and
a wall deadline of `max(3, 3 * calibrated_cpu_seconds + 1)`. CPU accounting uses cgroup v2,
including descendants and small supervisor overhead; peak RSS uses `wait4`. An OOM kill
maps to MLE. Output inodes are held by the supervisor to avoid symlink/FIFO replacement.
The report channel is protected against same-UID `/proc` file-descriptor access.

The calibrated CPU limit is the Codeforces limit multiplied by a machine-specific factor.
The factor is the median local/reference CPU ratio over measured input-matched baselines,
with three local executions per baseline. Baseline evidence, input/source hashes, machine
ID, platform, compiler versions, and image identity are retained. Production evaluation
requires this calibration and a verification report for the same image and factor. A local
image ID is a content identity, not a registry-pullable digest; registry digests are recorded
when available. Cross-platform comparisons require separate calibration and verification.

Verdicts are AC, WA, TLE, MLE, RE, CE, NO_CODE, and OUTPUT_LIMIT. Judging stops at the first
failure, recording its category. Infrastructure failures never silently become verdicts.
The Docker tests cover these verdicts, non-root identity, blocked network/write access,
report-channel protection, and bounded fork exhaustion. Docker isolation shares a host
kernel; it is not a proof against kernel vulnerabilities.

## Evaluation and budgets

Provider adapters use OpenAI Responses, Anthropic Messages, Google generateContent, and
OpenRouter chat completions. The fixed prompt requests one fenced C++17 or Python solution.
No feedback, tools, web search, or multi-turn repair is provided. Default sample count is four.
The exact rendered prompt is hashed and stored privately; the template is public.

The durable cache key includes model configuration name, problem ID, rendered prompt hash,
request-affecting configuration hash, and sample index. Display names, price-source updates,
cutoff-source updates, timeouts, and concurrency do not invalidate identical paid requests.
Changing model ID, provider, sampling, language, token cap, or Anthropic API version does.
Every run stores the full metadata and request snapshot.

Maximum cost is reserved transactionally before each generation. OpenAI, Anthropic, and
Google use their token-count endpoints plus a conservative formatting margin. OpenRouter
requires an explicit input-token billing reservation, at least UTF-8 prompt bytes + 4096;
this is an operator ceiling, not a claim about a model's context window. Output caps include
reasoning where supported. A cap is only as reliable as the configured flat price ceilings,
provider accounting, and output-limit semantics. Providers may change prices or apply fees;
use their account-level limits when a strict external billing cap is necessary.

Responses are stored before judging. Only explicit pre-generation rejections release
reservations. Rate-limit rejections are retried; ambiguous timeouts or server failures are
not automatically replayed, because they may already have been billed. Manual billing
reconciliation is audited privately. OpenAI/Anthropic output counts include reasoning;
Google's separate thought count is added once. Provider-reported OpenRouter cost is used
when available; otherwise sourced flat token prices provide an estimate. Raw token details
are retained privately. No production model calls are made by tests.

## Scoring

For problem j with n_j samples and k_j accepted samples:

`pass@1 = (1 / number_of_problems) * sum_j(k_j / n_j)`

This gives each problem equal weight. Only complete sample groups from the latest complete
or budget-stopped single-shot run per model are exported. Runs needing attention are not
published. Fake providers are excluded from public model records and scores.

A logistic performance proxy maximizes per-sample binomial likelihood under:

`P(solve | rating r, skill s) = 1 / (1 + 10 ** ((r - s) / 400))`

The derivative is monotone, so bisection finds the finite MLE. All-success or all-failure
samples have an unbounded MLE; no finite rating is invented. The 95% percentile confidence
interval uses 1,000 bootstrap resamples of **whole problems**, retaining all samples within
a selected problem. A shared LCG32 implementation (seed 1729, multiplier 1664525, increment
1013904223, modulo 2^32) makes browser and Python estimates reproducible. Intervals may have
unbounded endpoints. These are not official Codeforces ratings or claims of human equivalence.

Fewer than 20 measured or eligible problems is flagged as insufficient data. Cost per solved
problem is total generation cost divided by distinct problems with at least one AC sample;
it depends on the sample count and is undefined if none were solved. Breakdowns cover
100-point rating bands, tags, divisions, and verdicts. Tags overlap, so tag totals can overlap.

## Publication boundary and limitations

Public JSON is an explicit metadata/result allowlist. Full statements, raw HTML, generators,
validators, brute-force/reference source, test inputs/answers, raw responses, local paths,
and private verification reports are excluded. Model solutions are not exported by default.
Metadata titles, ratings, tags, dates, and links come from the public Codeforces API.
Only an intentionally exported snapshot is committed for Pages; CI never accesses private
research data. Problem statements belong to their authors. CF-Live is not affiliated with
Codeforces.

Curated tests and human review cannot prove correctness. The sample is selected and can be
small or uneven. Model samples are correlated. Machine variation and a simplified logistic
curve limit rating interpretation. Confidence intervals measure problem-sampling variation,
not these systematic uncertainties. This MVP has no multi-turn scores or automatic weekly
collection. Both would require separately described evaluation protocols.

Primary API sources checked during implementation:
[Codeforces objects](https://codeforces.com/apiHelp/objects),
[Codeforces rate limits](https://codeforces.com/apiHelp),
[OpenAI token counting](https://developers.openai.com/api/docs/guides/token-counting),
[OpenAI Responses](https://developers.openai.com/api/reference/resources/responses),
[Anthropic Messages](https://platform.claude.com/docs/en/api/messages/create),
[Google generateContent](https://ai.google.dev/api/generate-content),
[OpenRouter API](https://openrouter.ai/docs/api_reference/overview).
