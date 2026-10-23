import { lazy, Suspense, useEffect, useMemo, useState } from "react";
import {
  ArrowDownToLine,
  ArrowRight,
  ArrowUpRight,
  Braces,
  Check,
  ChevronRight,
  CircleDot,
  ExternalLink,
  GitFork as Github,
  Info,
  Layers3,
  Moon,
  ShieldCheck,
  SlidersHorizontal,
  Sun,
} from "lucide-react";
import { scores, selectIds } from "./scoring";
import type { Dataset, Filters, Problem, Score } from "./types";

const REPO = "https://github.com/sifat-hossain-niloy/cp-live-benchmark";
import { COLORS } from "./palette";
const CandidateDistribution = lazy(() =>
  import("./charts").then((m) => ({ default: m.CandidateDistribution })),
);
const Analysis = lazy(() =>
  import("./charts").then((m) => ({ default: m.Analysis })),
);
const percent = (value: number | null) =>
  value === null ? "—" : `${(value * 100).toFixed(1)}%`;
const money = (value: number | null) =>
  value === null ? "—" : `$${value.toFixed(value < 1 ? 3 : 2)}`;
const integer = (value: number | null) =>
  value === null ? "—" : Math.round(value).toLocaleString();

function useRoute() {
  const [route, setRoute] = useState(
    window.location.hash.slice(1) || "benchmark",
  );
  useEffect(() => {
    const onChange = () =>
      setRoute(window.location.hash.slice(1) || "benchmark");
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return route;
}
function App() {
  const [data, setData] = useState<Dataset | null>(null),
    [error, setError] = useState("");
  const [dark, setDark] = useState(
    document.documentElement.dataset.theme === "dark",
  );
  const route = useRoute();
  useEffect(() => {
    const [page, section] = route.split("/");
    if (page === "methodology" && section)
      document.getElementById(section)?.scrollIntoView();
    else window.scrollTo(0, 0);
  }, [route, data]);
  useEffect(() => {
    const controller = new AbortController();
    fetch(`${import.meta.env.BASE_URL}data.json`, { signal: controller.signal })
      .then((r) => {
        if (!r.ok) throw new Error(`Snapshot unavailable (HTTP ${r.status})`);
        return r.json();
      })
      .then((d) => {
        if (d.schema_version !== 1) throw new Error("Unsupported data version");
        setData(d);
      })
      .catch((e) => {
        if (e.name !== "AbortError") setError(e.message);
      });
    return () => controller.abort();
  }, []);
  function toggleTheme() {
    const next = !dark;
    setDark(next);
    document.documentElement.dataset.theme = next ? "dark" : "light";
    try {
      localStorage.setItem("cflive-theme", next ? "dark" : "light");
    } catch {
      /* Browser-local preference is optional. */
    }
  }
  return (
    <>
      <a
        className="skip-link"
        href="#main"
        onClick={(e) => {
          e.preventDefault();
          document.getElementById("main")?.focus();
        }}
      >
        Skip to content
      </a>
      <header className="header">
        <div className="header-inner">
          <a href="#benchmark" className="logo" aria-label="CF-Live home">
            <span className="logo-symbol">
              <Braces size={22} />
            </span>
            <span>
              CF<span className="logo-divider">/</span>LIVE
              <span className="logo-dot" />
            </span>
          </a>
          <nav aria-label="Main navigation">
            {["benchmark", "problems", "methodology"].map((page) => (
              <a
                key={page}
                href={`#${page}`}
                aria-current={
                  (route.startsWith("problem/")
                    ? "problems"
                    : route.split("/")[0]) === page
                    ? "page"
                    : undefined
                }
                className={
                  (route.startsWith("problem/")
                    ? "problems"
                    : route.split("/")[0]) === page
                    ? "active"
                    : ""
                }
              >
                {page === "benchmark"
                  ? "Leaderboard"
                  : page[0].toUpperCase() + page.slice(1)}
              </a>
            ))}
          </nav>
          <div className="header-actions">
            <a
              className="github-link"
              href={REPO}
              target="_blank"
              rel="noreferrer"
            >
              <Github size={17} />
              <span>Source</span>
              <ArrowUpRight size={13} />
            </a>
            <button
              className="icon-button"
              onClick={toggleTheme}
              aria-label={dark ? "Use light mode" : "Use dark mode"}
            >
              {dark ? <Sun size={18} /> : <Moon size={18} />}
            </button>
          </div>
        </div>
      </header>
      <main id="main" tabIndex={-1}>
        {error ? (
          <div className="load-state">
            <Info />
            <h1>Snapshot unavailable</h1>
            <p>
              {error}. Build a public snapshot with{" "}
              <code>cflive build-site</code>.
            </p>
            <button onClick={() => window.location.reload()}>Retry</button>
          </div>
        ) : !data ? (
          <div className="load-state" role="status">
            Loading benchmark snapshot…
          </div>
        ) : route.startsWith("methodology") ? (
          <Methodology />
        ) : route.startsWith("problem/") ? (
          <ProblemDetail data={data} id={route.slice(8)} />
        ) : (
          <Workspace data={data} catalog={route === "problems"} />
        )}
      </main>
      <footer>
        <div className="footer-inner">
          <div className="footer-brand">
            <Braces size={18} />
            <strong>CF-Live</strong>
            <span>Evidence before scores.</span>
          </div>
          <p>
            Not affiliated with Codeforces. Problem statements belong to their
            authors and are linked, never hosted.
          </p>
          <a href={`${REPO}/blob/main/docs/methodology.md`}>
            Methodology <ArrowUpRight size={13} />
          </a>
        </div>
      </footer>
    </>
  );
}

function Workspace({ data, catalog }: { data: Dataset; catalog: boolean }) {
  const [filters, setFilters] = useState<Filters>({
    common: false,
    since: "",
    rating: "",
    tag: "",
    division: "",
    models: data.models.map((m) => m.name),
  });
  const [search, setSearch] = useState("");
  const ranked = useMemo(() => scores(data, filters), [data, filters]);
  const selected = useMemo(() => selectIds(data, filters), [data, filters]);
  const dates = useMemo(
    () => [...new Set(data.problems.map((p) => p.contest_date))].sort(),
    [data],
  );
  const visibleProblems = data.problems.filter(
    (p) =>
      (!filters.since || p.contest_date >= filters.since) &&
      (!filters.rating ||
        Math.floor(p.rating / 100) * 100 === Number(filters.rating)) &&
      (!filters.tag || p.tags.includes(filters.tag)) &&
      (!filters.division || p.division === filters.division) &&
      `${p.id} ${p.name}`.toLowerCase().includes(search.toLowerCase()),
  );
  const update = (key: keyof Filters, value: Filters[keyof Filters]) =>
    setFilters((f) => ({ ...f, [key]: value }));
  const uniqueScored = new Set(
    [...selected.values()].flatMap((ids) => [...ids]),
  ).size;
  const generated = new Date(data.generated_at).toLocaleString("en-GB", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  });
  return (
    <div className="workspace">
      <section className="hero">
        <div className="hero-main">
          <div className="eyebrow">
            <span className="status-dot" />
            {catalog ? "PROBLEM REGISTRY" : "THE CF-LIVE BENCHMARK"}
            <span className="eyebrow-separator">/</span> RESEARCH PREVIEW
          </div>
          <h1>
            {catalog ? (
              <>
                The problems behind
                <br />
                the performance.
              </>
            ) : (
              <>
                Fresh problems.
                <br />
                <span>Measured performance.</span>
              </>
            )}
          </h1>
          <p>
            {catalog
              ? "A transparent registry of recent Codeforces candidates. Only reviewed, verified test sets can contribute to the leaderboard."
              : "How well do language models solve problems they haven’t trained on? Recent Codeforces contests, documented cutoffs, and independently verified private tests."}
          </p>
          <div className="hero-links">
            <a href="#methodology">
              Explore the methodology <ArrowRight size={16} />
            </a>
            <span>Single-shot · C++17 / Python 3</span>
          </div>
        </div>
        <aside className="protocol-card">
          <div className="protocol-heading">
            <ShieldCheck size={20} />
            <span>BUILT FOR CREDIBLE RESULTS</span>
          </div>
          <div>
            <Check />
            <p>
              <strong>After the cutoff</strong>
              <span>
                Contest dates checked against sourced training cutoffs.
              </span>
            </p>
          </div>
          <div>
            <Check />
            <p>
              <strong>Verified before scored</strong>
              <span>Human approval, brute-force checks, and stress tests.</span>
            </p>
          </div>
          <div>
            <Check />
            <p>
              <strong>Reproduce every run</strong>
              <span>
                Versioned prompts, sampling, toolchains, and judge images.
              </span>
            </p>
          </div>
          <a
            href={`${import.meta.env.BASE_URL}data.json`}
            download="cflive-public-snapshot.json"
          >
            Download public snapshot <ArrowDownToLine size={14} />
          </a>
        </aside>
      </section>
      <section className="stats-grid" aria-label="Benchmark inventory">
        <Stat
          label="VERIFIED PROBLEMS"
          value={data.inventory.verified_problems}
          detail="Eligible for evaluation"
          icon={<ShieldCheck />}
        />
        <Stat
          label="EVALUATED MODELS"
          value={data.inventory.evaluated_models}
          detail={`${data.inventory.configured_models} configurations ready`}
          icon={<Braces />}
        />
        <Stat
          label="RECENT CANDIDATES"
          value={data.inventory.collected_candidates}
          detail={`${data.inventory.statements_cached} statements cached privately`}
          icon={<Layers3 />}
        />
        <Stat
          label="REVIEW WORKSPACE"
          value={data.inventory.draft_directories}
          detail="Private problem directories"
          icon={<CircleDot />}
        />
      </section>
      <section className="results-section">
        <div className="section-title">
          <div>
            <div className="eyebrow small">
              {catalog ? "EXPLORE THE DATA" : "THE RESULTS"}
            </div>
            <h2>{catalog ? "Problem registry" : "Model leaderboard"}</h2>
          </div>
          <div className="snapshot-label">
            <span className="status-dot muted" />
            Snapshot · {generated} UTC
          </div>
        </div>
        <div className="filter-panel">
          <div className="filter-top">
            <div
              className="segmented"
              role="group"
              aria-label="Evaluation window"
            >
              <button
                className={!filters.common ? "selected" : ""}
                onClick={() => update("common", false)}
              >
                Each model’s window
              </button>
              <button
                className={filters.common ? "selected" : ""}
                onClick={() => update("common", true)}
              >
                Common window <span className="mini-tag">FAIR</span>
              </button>
            </div>
            <span className="filter-description">
              {filters.common
                ? "Same completed problems after the latest compared cutoff."
                : "Each model is scored on its completed post-cutoff problems."}
            </span>
          </div>
          <div className="filter-row">
            <span className="filter-label">
              <SlidersHorizontal size={15} />
              FILTERS
            </span>
            <label>
              <span className="sr-only">Rating band</span>
              <select
                value={filters.rating}
                onChange={(e) => update("rating", e.target.value)}
              >
                <option value="">All ratings</option>
                {[
                  ...new Set(
                    data.problems.map((p) => Math.floor(p.rating / 100) * 100),
                  ),
                ]
                  .sort((a, b) => a - b)
                  .map((r) => (
                    <option key={r} value={r}>
                      {r}–{r + 99}
                    </option>
                  ))}
              </select>
            </label>
            <label>
              <span className="sr-only">Problem tag</span>
              <select
                value={filters.tag}
                onChange={(e) => update("tag", e.target.value)}
              >
                <option value="">All tags</option>
                {[...new Set(data.problems.flatMap((p) => p.tags))]
                  .sort()
                  .map((t) => (
                    <option key={t}>{t}</option>
                  ))}
              </select>
            </label>
            <label>
              <span className="sr-only">Contest division</span>
              <select
                value={filters.division}
                onChange={(e) => update("division", e.target.value)}
              >
                <option value="">All divisions</option>
                {[...new Set(data.problems.map((p) => p.division))]
                  .sort()
                  .map((d) => (
                    <option key={d}>{d}</option>
                  ))}
              </select>
            </label>
            <button
              className="reset-button"
              onClick={() =>
                setFilters({
                  common: false,
                  since: "",
                  rating: "",
                  tag: "",
                  division: "",
                  models: data.models.map((m) => m.name),
                })
              }
            >
              Reset
            </button>
            <span className="window-count">
              {catalog ? visibleProblems.length : uniqueScored}{" "}
              {catalog ? "candidates" : "scored problems"}
            </span>
          </div>
          <div className="date-filter">
            <label htmlFor="date-window">
              Contests from <strong>{filters.since || dates[0] || "—"}</strong>
            </label>
            <input
              id="date-window"
              aria-label="Contest start date slider"
              type="range"
              min={0}
              max={Math.max(0, dates.length - 1)}
              value={Math.max(
                0,
                dates.findIndex((d) => d >= (filters.since || dates[0])),
              )}
              onChange={(e) =>
                update("since", dates[Number(e.target.value)] || "")
              }
              disabled={!dates.length}
            />
            <label>
              <span className="sr-only">Exact start date</span>
              <input
                type="date"
                value={filters.since || dates[0] || ""}
                onChange={(e) => update("since", e.target.value)}
              />
            </label>
          </div>
          {!!data.models.length && (
            <div className="model-selector" aria-label="Compared models">
              {data.models.map((m, i) => (
                <label key={m.name}>
                  <input
                    type="checkbox"
                    checked={filters.models.includes(m.name)}
                    onChange={(e) =>
                      update(
                        "models",
                        e.target.checked
                          ? [...filters.models, m.name]
                          : filters.models.filter((n) => n !== m.name),
                      )
                    }
                  />
                  <span style={{ background: COLORS[i % COLORS.length] }} />
                  {m.display_name}
                </label>
              ))}
            </div>
          )}
        </div>
        {catalog ? (
          <ProblemCatalog
            problems={visibleProblems}
            search={search}
            setSearch={setSearch}
          />
        ) : (
          <>
            <Leaderboard ranked={ranked} />
            {!data.results.length ? (
              <Readiness data={data} />
            ) : (
              <Suspense
                fallback={<div className="panel">Loading analysis…</div>}
              >
                <Analysis ranked={ranked} />
              </Suspense>
            )}
          </>
        )}
      </section>
      {!catalog && (
        <Suspense fallback={<div className="panel">Loading chart…</div>}>
          <CandidateDistribution
            problems={visibleProblems}
            hasResults={data.results.length > 0}
          />
        </Suspense>
      )}
    </div>
  );
}
function Stat({
  label,
  value,
  detail,
  icon,
}: {
  label: string;
  value: number;
  detail: string;
  icon: React.ReactNode;
}) {
  return (
    <article className="stat">
      <div>
        <span>{label}</span>
        {icon}
      </div>
      <strong>{value.toLocaleString()}</strong>
      <p>{detail}</p>
    </article>
  );
}
function Leaderboard({ ranked }: { ranked: Score[] }) {
  return (
    <div className="leaderboard-card">
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th className="rank-column">#</th>
              <th>
                Model <span>provider / snapshot</span>
              </th>
              <th>
                Pass@1 <span>mean over problems</span>
              </th>
              <th>
                Estimated rating <span>95% problem-bootstrap CI</span>
              </th>
              <th>
                Problems <span>scored / eligible</span>
              </th>
              <th>
                Cost / solved <span>≥1 accepted sample</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {!ranked.length ? (
              <tr>
                <td colSpan={6}>
                  <div className="empty-board">
                    <div className="empty-icon">
                      <Braces size={25} />
                    </div>
                    <h3>Good benchmarks start with evidence.</h3>
                    <p>
                      No model scores are published yet. Reviewed tests and
                      sourced model cutoffs come first.
                    </p>
                    <a href="#methodology">
                      See what qualifies for the leaderboard{" "}
                      <ArrowRight size={15} />
                    </a>
                  </div>
                </td>
              </tr>
            ) : (
              ranked.map((s, i) => (
                <tr key={s.model.name}>
                  <td className="rank-column">
                    {String(i + 1).padStart(2, "0")}
                  </td>
                  <td>
                    <strong>{s.model.display_name}</strong>
                    <span className="model-meta">
                      {s.model.provider} · {s.model.model_id}
                    </span>
                    {s.insufficient && (
                      <span className="badge amber">Insufficient data</span>
                    )}
                  </td>
                  <td className="pass-cell">{percent(s.pass1)}</td>
                  <td>
                    <strong>{integer(s.rating)}</strong>
                    <span className="model-meta">
                      {s.ci.unbounded_low ? "−∞" : integer(s.ci.low)} –{" "}
                      {s.ci.unbounded_high ? "+∞" : integer(s.ci.high)}
                    </span>
                  </td>
                  <td>
                    <strong>{s.problems}</strong>
                    <span className="muted-text"> / {s.eligible}</span>
                  </td>
                  <td>
                    <strong>{money(s.costPerSolved)}</strong>
                    <span className="model-meta">{money(s.cost)} total</span>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
      <div className="table-note">
        <Info size={14} />
        <span>
          Rating is a logistic performance estimate, not an official Codeforces
          rating. Fewer than 20 measured or eligible problems is insufficient
          data.
        </span>
      </div>
    </div>
  );
}
function Readiness({ data }: { data: Dataset }) {
  return (
    <div className="readiness-grid">
      <article className="panel readiness">
        <div className="panel-heading">
          <span className="overline">FROM CANDIDATE TO SCORE</span>
          <span className="badge">Setup in progress</span>
        </div>
        <h3>
          The pipeline is ready.
          <br />
          The evidence comes next.
        </h3>
        <p>Results stay unpublished until every evaluation gate passes.</p>
        <ol>
          <li className="done">
            <span>
              <Check size={13} />
            </span>
            <div>
              <strong>Collect recent contests</strong>
              <small>
                {data.inventory.collected_candidates} eligible candidates in
                this snapshot
              </small>
            </div>
          </li>
          <li className={data.inventory.verified_problems ? "done" : ""}>
            <span>
              {data.inventory.verified_problems ? <Check size={13} /> : 2}
            </span>
            <div>
              <strong>Review and verify private tests</strong>
              <small>
                {data.inventory.draft_directories} draft directories ·{" "}
                {data.inventory.verified_problems} verified
              </small>
            </div>
          </li>
          <li className={data.inventory.configured_models ? "done" : ""}>
            <span>3</span>
            <div>
              <strong>Document cutoffs and run models</strong>
              <small>
                Source model metadata, calibrate the judge, then evaluate
              </small>
            </div>
          </li>
        </ol>
        <a className="text-link" href={`${REPO}/blob/main/docs/handoff.md`}>
          Open the reviewer handoff <ArrowUpRight size={15} />
        </a>
      </article>
      <article className="panel provider-panel">
        <div className="panel-heading">
          <span className="overline">MODEL CONFIGURATION</span>
          <Braces size={17} />
        </div>
        <h3>Four providers. One protocol.</h3>
        <p>
          Exact snapshots, cutoffs, and prices must be supported by primary
          sources.
        </p>
        <div className="provider-list">
          {data.model_configurations.map((m, i) => (
            <div key={m.name}>
              <span
                className="provider-mark"
                style={{ color: COLORS[i % COLORS.length] }}
              >
                {m.provider.slice(0, 1).toUpperCase()}
              </span>
              <div>
                <strong>
                  {(
                    {
                      openai: "OpenAI",
                      anthropic: "Anthropic",
                      google: "Google",
                      openrouter: "OpenRouter",
                    } as Record<string, string>
                  )[m.provider] || m.provider}
                </strong>
                <small>
                  {m.ready
                    ? "Configuration sourced"
                    : "Exact model and source metadata needed"}
                </small>
              </div>
              <span className={`badge ${m.ready ? "green" : ""}`}>
                {m.ready ? "Ready" : "Pending"}
              </span>
            </div>
          ))}
        </div>
        <div className="provider-note">
          <ShieldCheck size={15} />
          Missing cutoff evidence blocks evaluation automatically.
        </div>
      </article>
    </div>
  );
}
function ProblemCatalog({
  problems,
  search,
  setSearch,
}: {
  problems: Problem[];
  search: string;
  setSearch: (s: string) => void;
}) {
  return (
    <div className="panel catalog">
      <div className="catalog-top">
        <p>
          <strong>{problems.length}</strong> candidates ·{" "}
          <span className="muted-text">
            Review status is shown for every problem.
          </span>
        </p>
        <label>
          <span className="sr-only">Search problems</span>
          <input
            type="search"
            placeholder="Search by ID or title…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </label>
      </div>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>Problem</th>
              <th>Rating</th>
              <th>Tags</th>
              <th>Contest · UTC</th>
              <th>Review</th>
              <th>
                <span className="sr-only">Details</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {problems.map((p) => (
              <tr key={p.id}>
                <td>
                  <a className="problem-title" href={`#problem/${p.id}`}>
                    <code>{p.id}</code>
                    <strong>{p.name}</strong>
                  </a>
                </td>
                <td>
                  <span className="rating-pill">{p.rating}</span>
                </td>
                <td>
                  <div className="tags">
                    {p.tags.map((t) => (
                      <span key={t}>{t}</span>
                    ))}
                  </div>
                </td>
                <td>
                  <span>{p.contest_date}</span>
                  <small className="model-meta">{p.division}</small>
                </td>
                <td>
                  <span className={`badge ${p.verified ? "green" : ""}`}>
                    {p.verified ? "Verified" : "Review pending"}
                  </span>
                </td>
                <td>
                  <a
                    className="icon-button"
                    href={`#problem/${p.id}`}
                    aria-label={`View ${p.id}`}
                  >
                    <ChevronRight size={16} />
                  </a>
                </td>
              </tr>
            ))}
            {!problems.length && (
              <tr>
                <td colSpan={6} className="chart-empty">
                  No problems match these filters.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
function ProblemDetail({ data, id }: { data: Dataset; id: string }) {
  const p = data.problems.find((p) => p.id === id);
  if (!p)
    return (
      <div className="workspace">
        <h1>Problem not found</h1>
        <a href="#problems">Back to registry</a>
      </div>
    );
  const rows = data.results.filter((r) => r.problem_id === id);
  return (
    <div className="workspace detail">
      <a className="breadcrumb" href="#problems">
        Problem registry <ChevronRight size={13} /> {p.id}
      </a>
      <div className="detail-title">
        <div>
          <div className="eyebrow">
            {p.division} · {p.contest_date} UTC
          </div>
          <h1>
            <span>{p.id}</span> {p.name}
          </h1>
        </div>
        <a
          className="primary-button"
          href={p.url}
          target="_blank"
          rel="noreferrer"
        >
          Read on Codeforces <ExternalLink size={15} />
        </a>
      </div>
      <div className="detail-meta">
        <span className="rating-pill">Rating {p.rating}</span>
        <span className={`badge ${p.verified ? "green" : ""}`}>
          {p.verified ? "Verified tests" : "Review pending"}
        </span>
        <div className="tags">
          {p.tags.map((t) => (
            <span key={t}>{t}</span>
          ))}
        </div>
      </div>
      <div className="callout">
        <ShieldCheck size={20} />
        <p>
          {p.verified
            ? "This problem passed the approval and verification gates. Hidden tests and reference solutions remain private."
            : "This is a collected candidate. It contributes to no model scores until its tests are approved and verified."}{" "}
          The full statement stays on Codeforces.
        </p>
      </div>
      <section className="panel">
        <h2>Per-model outcomes</h2>
        {!rows.length ? (
          <div className="empty-board">
            <Braces size={25} />
            <h3>No evaluations published for this problem.</h3>
            <p>Only complete, verified sample groups appear here.</p>
          </div>
        ) : (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Model</th>
                  <th>Sample</th>
                  <th>Verdict</th>
                  <th>First failing category</th>
                  <th>CPU time</th>
                  <th>Peak memory</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={`${r.model_name}-${r.sample_index}`}>
                    <td>
                      {
                        data.models.find((m) => m.name === r.model_name)
                          ?.display_name
                      }
                    </td>
                    <td>{r.sample_index + 1}</td>
                    <td>
                      <span
                        className={`badge ${r.verdict === "AC" ? "green" : "amber"}`}
                      >
                        {r.verdict}
                      </span>
                    </td>
                    <td>{r.failing_category || "—"}</td>
                    <td>{r.cpu_ms.toFixed(1)} ms</td>
                    <td>{(r.memory_kb / 1024).toFixed(1)} MB</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
      {!!rows.length && (
        <section className="panel provenance">
          <h2>Reproduction records</h2>
          {data.models
            .filter((m) => rows.some((r) => r.model_name === m.name))
            .map((m) => (
              <div key={m.name}>
                <h3>{m.display_name}</h3>
                <p>
                  Run <code>{m.run_id}</code> · {m.run_date} UTC
                </p>
                <p>
                  Training cutoff:{" "}
                  <a href={m.cutoff_source_url}>
                    {m.training_cutoff} <ArrowUpRight size={12} />
                  </a>{" "}
                  · {m.samples_per_problem} samples · {m.language}
                </p>
                <p>
                  Judge <code>{m.image_digest}</code> · Calibration ×
                  {m.calibration_factor}
                </p>
                <pre>{m.compiler_versions}</pre>
                <p>
                  Sampling <code>{JSON.stringify(m.sampling)}</code>
                </p>
              </div>
            ))}
        </section>
      )}
    </div>
  );
}
function Methodology() {
  return (
    <article className="workspace methodology">
      <div className="eyebrow">THE EVALUATION PROTOCOL</div>
      <h1>Evidence before scores.</h1>
      <p className="methodology-lead">
        A reproducible measure of model performance on recent programming
        problems. Every published score has to earn its place.
      </p>
      <div className="method-layout">
        <aside>
          <a href="#methodology/contamination">01 Contamination rule</a>
          <a href="#methodology/verification">02 Test verification</a>
          <a href="#methodology/judge">03 Judge & calibration</a>
          <a href="#methodology/scoring">04 Scoring & uncertainty</a>
          <a href="#methodology/limitations">05 Reproduction & limitations</a>
        </aside>
        <div className="method-content">
          <section id="contamination">
            <span className="overline">01 / CONTAMINATION RESISTANCE</span>
            <h2>Problems released after training ends.</h2>
            <p>
              A model is eligible only when its configuration contains an exact
              model identifier, a documented training cutoff, and a source URL.
              A contest must start strictly after the entire cutoff date in UTC.
              Missing cutoff evidence blocks evaluation.
            </p>
            <p>
              The individual view uses each model’s completed post-cutoff
              problems. The common window uses the intersection of completed
              problem groups after the latest cutoff among the selected models.
              Rating, tag, division, and date filters apply to both.
            </p>
          </section>
          <section id="verification">
            <span className="overline">02 / TEST CREDIBILITY</span>
            <h2>Review, differential checks, then stress tests.</h2>
            <p>
              Each reference has checked Accepted-submission evidence or
              attested editorial provenance. A human reviews the reference,
              independent brute force, seeded generator, exact-constraint
              validator, and checker before approval. Approval binds to hashes;
              edits invalidate it.
            </p>
            <ul>
              <li>Every generated input passes the validator.</li>
              <li>
                The reference matches brute force on at least 500 small random
                inputs and all configured edge cases.
              </li>
              <li>The reference passes all official samples.</li>
              <li>
                At least five max-size cases finish within 50% of the calibrated
                time limit.
              </li>
              <li>
                The final private test set contains 20–80 cases: samples, edges,
                small random cases, and at least five max-size cases.
              </li>
            </ul>
            <p>
              Multi-answer tasks require a custom checker that validates
              feasibility and the reference answer’s optimal objective. It must
              not demand the same output text. Potentially essential statement
              images, interactive tasks, special tasks, and unrated tasks are
              excluded.
            </p>
          </section>
          <section id="judge">
            <span className="overline">03 / EXECUTION ENVIRONMENT</span>
            <h2>A fresh restricted container for every test.</h2>
            <p>
              C++17 compiles with GCC 12.2.0 and <code>-O2</code>; Python uses
              3.11.11. The base image is pinned by digest. Every run records its
              immutable local image identity, platform, compiler versions, and
              calibration factor.
            </p>
            <p>
              Compilation has its own 30-second CPU limit. Execution uses a
              non-root user, no network, a read-only root, a size-limited
              writable work directory, one CPU, 64 processes, equal memory and
              swap limits, a 64 MB combined output cap, and a wall-clock
              deadline. CPU accounting includes descendants. Judging stops at
              the first failure and records its category.
            </p>
            <p>
              The time allowance is the Codeforces limit multiplied by a
              measured machine calibration factor. Calibration requires
              reference CPU baselines and evidence; an uncalibrated environment
              cannot run production evaluation. CPU usage includes a small
              supervisor overhead. Docker tests check verdicts and attempts to
              access the network, write outside the work directory, and fork
              repeatedly.
            </p>
          </section>
          <section id="scoring">
            <span className="overline">04 / SCORING</span>
            <h2>One attempt means one attempt.</h2>
            <p>
              Evaluation is single-shot with no judge feedback. The default is
              four samples per problem. For each problem, accepted samples are
              divided by total samples; pass@1 is the mean of those fractions
              over problems. Incomplete sample groups are excluded. The public
              snapshot uses the latest complete or budget-stopped run per model.
            </p>
            <div className="formula">
              pass@1 = mean<sub>problems</sub>(accepted samples / samples)
              <br />
              <br />
              P(solve | rating r, skill s) = 1 / (1 + 10<sup>(r − s) / 400</sup>
              )
            </div>
            <p>
              The skill estimate maximizes the likelihood of per-sample outcomes
              under this logistic curve. A 95% percentile interval comes from
              1,000 bootstrap resamples of whole problems, preserving correlated
              samples. The deterministic LCG32 bootstrap uses seed 1729,
              identically in the CLI and browser. All-success or all-failure
              data have an unbounded maximum-likelihood estimate and show no
              finite rating.
            </p>
            <p>
              Fewer than 20 measured or eligible problems is flagged as
              insufficient data. Cost per solved problem divides total
              generation cost by the number of distinct problems with at least
              one accepted sample. It depends on the configured sample count.
              Reasoning tokens are included in output cost once, without double
              counting. Prices must be sourced; estimates use configured flat
              token prices unless a provider reports actual cost.
            </p>
          </section>
          <section id="limitations">
            <span className="overline">05 / REPRODUCIBILITY & LIMITATIONS</span>
            <h2>Inspect the protocol. Keep the tests private.</h2>
            <p>
              Every result records its model and provider, date, sampling
              parameters, prompt hash, run ID, judge image identity, compiler
              versions, token usage, cost, CPU time, memory, and first failing
              test category. Raw responses, extracted code, statements, test
              inputs, generators, and verification reports are stored privately.
              The site exports an explicit allowlist of metadata and results.
            </p>
            <p>
              Response caches include the model, problem, exact prompt hash,
              configuration hash, and sample index. Maximum token costs are
              reserved before each paid request. Ambiguous requests remain
              reserved for manual billing reconciliation and are never
              automatically repeated. A budget is only as accurate as its
              configured price ceilings and provider token accounting.
              OpenRouter additionally needs a conservative operator-set input
              reservation.
            </p>
            <p>
              Post-cutoff selection reduces contamination risk; it cannot prove
              a provider’s training disclosure, rule out later exposure, or
              establish model independence. Curated tests cannot prove
              correctness. The rating estimate is a performance proxy rather
              than an official Codeforces rating, and its confidence interval
              does not measure these systematic uncertainties. Different
              candidate sets and fewer than 20 problems limit comparisons.
              Public model outputs are not enabled by default.
            </p>
            <a
              className="primary-button"
              href={`${REPO}/blob/main/prompts/single-shot.txt`}
            >
              Read the fixed prompt <ArrowUpRight size={15} />
            </a>{" "}
            <a className="text-link" href={`${REPO}/blob/main/README.md`}>
              Reproduce a run <ArrowUpRight size={15} />
            </a>
          </section>
        </div>
      </div>
    </article>
  );
}
export default App;
