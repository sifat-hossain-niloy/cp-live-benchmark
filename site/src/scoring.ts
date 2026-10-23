import type { CI, Dataset, Filters, Outcome, Score } from "./types";

export function probability(skill: number, rating: number): number {
  const z = ((rating - skill) * Math.log(10)) / 400;
  if (z >= 0) {
    const e = Math.exp(-Math.min(z, 745));
    return e / (1 + e);
  }
  return 1 / (1 + Math.exp(Math.max(z, -745)));
}
export function fitSkill(outcomes: Outcome[]): number | null {
  if (!outcomes.length) return null;
  const accepted = outcomes.reduce((a, o) => a + o.accepted, 0);
  const total = outcomes.reduce((a, o) => a + o.samples, 0);
  if (accepted === 0 || accepted === total) return null;
  const buckets = new Map<number, number>();
  for (const o of outcomes)
    buckets.set(o.rating, (buckets.get(o.rating) || 0) + o.samples);
  let low = Math.min(...buckets.keys()) - 12000,
    high = Math.max(...buckets.keys()) + 12000;
  for (let i = 0; i < 65; i++) {
    const mid = (low + high) / 2;
    let expected = 0;
    for (const [r, n] of buckets) expected += n * probability(mid, r);
    if (expected < accepted) low = mid;
    else high = mid;
  }
  return (low + high) / 2;
}
export function bootstrap(outcomes: Outcome[], resamples = 1000): CI {
  if (!outcomes.length)
    return {
      low: null,
      high: null,
      unbounded_low: false,
      unbounded_high: false,
    };
  let state = 1729;
  const random = () => {
    state = (Math.imul(1664525, state) + 1013904223) >>> 0;
    return state / 4294967296;
  };
  const estimates: number[] = [];
  for (let i = 0; i < resamples; i++) {
    const sample = Array.from(
      { length: outcomes.length },
      () => outcomes[Math.floor(random() * outcomes.length)],
    );
    estimates.push(
      fitSkill(sample) ??
        (sample.reduce((a, o) => a + o.accepted, 0) === 0
          ? -Infinity
          : Infinity),
    );
  }
  estimates.sort((a, b) => a - b);
  function percentile(q: number) {
    const pos = q * (estimates.length - 1),
      a = estimates[Math.floor(pos)],
      b = estimates[Math.ceil(pos)];
    if (a === b) return a;
    if (!Number.isFinite(a) || !Number.isFinite(b))
      return !Number.isFinite(a) ? a : b;
    return a + (b - a) * (pos % 1);
  }
  const low = percentile(0.025),
    high = percentile(0.975);
  return {
    low: Number.isFinite(low) ? low : null,
    high: Number.isFinite(high) ? high : null,
    unbounded_low: low === -Infinity,
    unbounded_high: high === Infinity,
  };
}
export function selectIds(
  data: Dataset,
  filters: Filters,
): Map<string, Set<string>> {
  const models = data.models.filter((m) => filters.models.includes(m.name));
  const candidates = new Set(
    data.problems
      .filter(
        (p) =>
          p.verified &&
          p.contest_date >= filters.since &&
          (!filters.rating ||
            Math.floor(p.rating / 100) * 100 === Number(filters.rating)) &&
          (!filters.tag || p.tags.includes(filters.tag)) &&
          (!filters.division || p.division === filters.division),
      )
      .map((p) => p.id),
  );
  const selected = new Map(
    models.map((m) => [
      m.name,
      new Set(m.scored_problem_ids.filter((id) => candidates.has(id))),
    ]),
  );
  if (filters.common && models.length) {
    const latest = models
      .map((m) => m.training_cutoff)
      .sort()
      .at(-1)!;
    const after = new Set(
      data.problems.filter((p) => p.contest_date > latest).map((p) => p.id),
    );
    const shared = new Set(
      [...candidates].filter(
        (id) =>
          after.has(id) && [...selected.values()].every((ids) => ids.has(id)),
      ),
    );
    for (const model of models) selected.set(model.name, shared);
  }
  return selected;
}
export function scores(data: Dataset, filters: Filters): Score[] {
  const ids = selectIds(data, filters),
    problems = new Map(data.problems.map((p) => [p.id, p]));
  const avg = (xs: Outcome[]) =>
    xs.length
      ? xs.reduce((a, o) => a + o.accepted / o.samples, 0) / xs.length
      : null;
  const result: Score[] = [];
  for (const model of data.models) {
    const selected = ids.get(model.name);
    if (!selected) continue;
    const rows = data.results.filter(
      (r) => r.model_name === model.name && selected.has(r.problem_id),
    );
    const outcomes: Outcome[] = [...selected]
      .sort()
      .map((id) => {
        const group = rows.filter((r) => r.problem_id === id);
        return {
          id,
          rating: problems.get(id)!.rating,
          accepted: group.filter((r) => r.verdict === "AC").length,
          samples: group.length,
        };
      })
      .filter((o) => o.samples > 0);
    const cost = rows.reduce((a, r) => a + r.cost_usd, 0),
      solved = outcomes.filter((o) => o.accepted > 0).length;
    const bandGroups = new Map<string, Outcome[]>(),
      tagGroups = new Map<string, Outcome[]>();
    for (const o of outcomes) {
      const band = String(Math.floor(o.rating / 100) * 100);
      bandGroups.set(band, [...(bandGroups.get(band) || []), o]);
      for (const tag of problems.get(o.id)!.tags)
        tagGroups.set(tag, [...(tagGroups.get(tag) || []), o]);
    }
    const verdicts: Record<string, number> = {};
    for (const row of rows)
      verdicts[row.verdict] = (verdicts[row.verdict] || 0) + 1;
    result.push({
      model,
      pass1: avg(outcomes),
      rating: fitSkill(outcomes),
      ci: bootstrap(outcomes),
      problems: outcomes.length,
      eligible: model.eligible_problem_ids.length,
      samples: rows.length,
      solved,
      cost,
      costPerSolved: solved ? cost / solved : null,
      insufficient:
        Math.min(outcomes.length, model.eligible_problem_ids.length) < 20,
      bands: Object.fromEntries([...bandGroups].map(([k, v]) => [k, avg(v)!])),
      tags: Object.fromEntries([...tagGroups].map(([k, v]) => [k, avg(v)!])),
      verdicts,
    });
  }
  return result.sort((a, b) => (b.pass1 ?? -1) - (a.pass1 ?? -1));
}
