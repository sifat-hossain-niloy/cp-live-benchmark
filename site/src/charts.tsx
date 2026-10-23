import { ArrowRight } from "lucide-react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { Problem, Score } from "./types";
import { COLORS, VERDICTS, VERDICT_COLORS } from "./palette";
const percent = (value: number | null) =>
  value === null ? "—" : `${(value * 100).toFixed(1)}%`;
export function CandidateDistribution({
  problems,
  hasResults,
}: {
  problems: Problem[];
  hasResults: boolean;
}) {
  const counts = new Map<number, number>();
  for (const p of problems)
    counts.set(p.rating, (counts.get(p.rating) || 0) + 1);
  const chart = [...counts]
    .sort((a, b) => a[0] - b[0])
    .map(([rating, count]) => ({ rating, count }));
  return (
    <section className="panel distribution">
      <div className="distribution-heading">
        <div>
          <span className="overline">
            {hasResults ? "THE PROBLEM POOL" : "PREPARATION SNAPSHOT"}
          </span>
          <h3>Candidate difficulty distribution</h3>
          <p>
            Collected metadata only. Unverified candidates do not contribute to
            model scores.
          </p>
        </div>
        <a className="text-link" href="#problems">
          Browse {problems.length} candidates <ArrowRight size={15} />
        </a>
      </div>
      <div
        className="chart-frame"
        aria-label="Candidate problem counts by Codeforces rating"
      >
        {chart.length ? (
          <ResponsiveContainer width="100%" height={220}>
            <BarChart
              data={chart}
              margin={{ top: 15, right: 15, left: -25, bottom: 0 }}
            >
              <CartesianGrid
                vertical={false}
                stroke="var(--line)"
                strokeDasharray="3 5"
              />
              <XAxis
                dataKey="rating"
                tick={{ fontSize: 11, fill: "var(--muted)" }}
                axisLine={false}
                tickLine={false}
                minTickGap={25}
              />
              <YAxis
                allowDecimals={false}
                tick={{ fontSize: 11, fill: "var(--muted)" }}
                axisLine={false}
                tickLine={false}
              />
              <Tooltip cursor={{ fill: "var(--wash)" }} />
              <Bar
                dataKey="count"
                name="Candidates"
                fill="#2855e8"
                radius={[3, 3, 0, 0]}
                maxBarSize={26}
              />
            </BarChart>
          </ResponsiveContainer>
        ) : (
          <p className="chart-empty">No candidates match these filters.</p>
        )}
      </div>
    </section>
  );
}
export function Analysis({ ranked }: { ranked: Score[] }) {
  const bands = [...new Set(ranked.flatMap((s) => Object.keys(s.bands)))].sort(
    (a, b) => Number(a) - Number(b),
  );
  const bandData = bands.map((r) =>
    Object.fromEntries([
      ["rating", r],
      ...ranked.map((s, i) => [
        `series${i}`,
        s.bands[r] === undefined ? undefined : s.bands[r] * 100,
      ]),
    ]),
  );
  const tags = [...new Set(ranked.flatMap((s) => Object.keys(s.tags)))].sort();
  const verdictData = ranked.map((s) => ({
    name: s.model.display_name,
    ...s.verdicts,
  }));
  return (
    <div className="analysis-grid">
      <article className="panel">
        <span className="overline">DIFFICULTY PROFILE</span>
        <h3>Pass@1 by rating band</h3>
        <div className="chart-frame">
          <ResponsiveContainer width="100%" height={270}>
            <LineChart data={bandData}>
              <CartesianGrid stroke="var(--line)" vertical={false} />
              <XAxis dataKey="rating" tick={{ fontSize: 11 }} />
              <YAxis domain={[0, 100]} unit="%" tick={{ fontSize: 11 }} />
              <Tooltip />
              <Legend />
              {ranked.map((s, i) => (
                <Line
                  key={s.model.name}
                  type="monotone"
                  dataKey={`series${i}`}
                  name={s.model.display_name}
                  stroke={COLORS[i % COLORS.length]}
                  connectNulls={false}
                  strokeWidth={2}
                />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </div>
      </article>
      <article className="panel">
        <span className="overline">WHERE SOLUTIONS FAIL</span>
        <h3>Verdict distribution</h3>
        <div className="chart-frame">
          <ResponsiveContainer width="100%" height={270}>
            <BarChart data={verdictData}>
              <XAxis dataKey="name" tick={{ fontSize: 10 }} />
              <YAxis allowDecimals={false} />
              <Tooltip />
              <Legend />
              {VERDICTS.map((v, i) => (
                <Bar
                  key={v}
                  dataKey={v}
                  stackId="verdict"
                  fill={VERDICT_COLORS[i]}
                />
              ))}
            </BarChart>
          </ResponsiveContainer>
        </div>
      </article>
      <article className="panel heatmap-panel">
        <span className="overline">TOPIC COVERAGE</span>
        <h3>Pass@1 across problem tags</h3>
        <div className="table-scroll">
          <table className="heatmap">
            <thead>
              <tr>
                <th>Model</th>
                {tags.map((t) => (
                  <th key={t}>{t}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {ranked.map((s) => (
                <tr key={s.model.name}>
                  <th>{s.model.display_name}</th>
                  {tags.map((t) => (
                    <td
                      key={t}
                      style={{
                        background:
                          s.tags[t] === undefined
                            ? "var(--wash)"
                            : `rgba(40,85,232,${0.08 + s.tags[t] * 0.52})`,
                        color: "var(--ink)",
                      }}
                    >
                      {percent(s.tags[t] ?? null)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </article>
    </div>
  );
}
