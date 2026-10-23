"""Per-problem balanced pass@1 and logistic performance estimates, not official CF ratings."""

import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from statistics import mean
from typing import Any


@dataclass(frozen=True)
class Outcome:
    problem_id: str
    rating: int
    accepted: int
    samples: int


def pass_at_one(outcomes: list[Outcome]) -> float | None:
    return mean(o.accepted / o.samples for o in outcomes) if outcomes else None


def solve_probability(skill: float, rating: float) -> float:
    z = (rating - skill) * math.log(10) / 400
    if z >= 0:
        exp = math.exp(-min(z, 745))
        return exp / (1 + exp)
    return 1 / (1 + math.exp(max(z, -745)))


def fit_skill(outcomes: list[Outcome]) -> float | None:
    """The MLE is unbounded for all-success/all-failure data; never invent finite endpoints."""
    if not outcomes:
        return None
    accepted, total = sum(o.accepted for o in outcomes), sum(o.samples for o in outcomes)
    if accepted == 0 or accepted == total:
        return None
    buckets: dict[int, int] = defaultdict(int)
    for outcome in outcomes:
        buckets[outcome.rating] += outcome.samples
    low, high = min(buckets) - 12000.0, max(buckets) + 12000.0
    for _ in range(65):
        skill = (low + high) / 2
        expectation = sum(n * solve_probability(skill, r) for r, n in buckets.items())
        if expectation < accepted:
            low = skill
        else:
            high = skill
    return (low + high) / 2


def bootstrap_ci(
    outcomes: list[Outcome], *, resamples: int = 1000, seed: int = 1729
) -> dict[str, Any]:
    """Cluster bootstrap: draw whole problems, retaining all their correlated samples."""
    if not outcomes or resamples < 2:
        return {
            "low": None,
            "high": None,
            "resamples": resamples,
            "unbounded_low": False,
            "unbounded_high": False,
        }
    state = seed & 0xFFFFFFFF

    def random_index() -> int:
        nonlocal state
        state = (1664525 * state + 1013904223) & 0xFFFFFFFF
        return int(state / 4294967296 * len(outcomes))

    estimates = []
    for _ in range(resamples):
        sampled = [outcomes[random_index()] for _ in outcomes]
        skill = fit_skill(sampled)
        if skill is None:
            skill = float("-inf") if sum(o.accepted for o in sampled) == 0 else float("inf")
        estimates.append(skill)
    estimates.sort()

    def percentile(q: float) -> float:
        pos = q * (len(estimates) - 1)
        a, b = estimates[math.floor(pos)], estimates[math.ceil(pos)]
        if a == b:
            return a
        if not math.isfinite(a) or not math.isfinite(b):
            return a if not math.isfinite(a) else b
        return a + (b - a) * (pos % 1)

    low, high = percentile(0.025), percentile(0.975)
    return {
        "low": low if math.isfinite(low) else None,
        "high": high if math.isfinite(high) else None,
        "resamples": resamples,
        "unbounded_low": low == float("-inf"),
        "unbounded_high": high == float("inf"),
    }


def selected_problem_ids(
    data: dict[str, Any],
    *,
    common: bool = False,
    selected_models: list[str] | None = None,
    since: str | None = None,
    rating_band: int | None = None,
    tag: str | None = None,
    division: str | None = None,
) -> dict[str, set[str]]:
    models = [m for m in data["models"] if selected_models is None or m["name"] in selected_models]
    candidates = {
        p["id"]
        for p in data["problems"]
        if p["verified"]
        and (not since or p["contest_date"] >= since)
        and (rating_band is None or p["rating"] // 100 * 100 == rating_band)
        and (not tag or tag in p["tags"])
        and (not division or p["division"] == division)
    }
    available = {m["name"]: candidates & set(m["scored_problem_ids"]) for m in models}
    if common and models:
        latest = max(m["training_cutoff"] for m in models)
        after_latest = {p["id"] for p in data["problems"] if p["contest_date"] > latest}
        shared = set.intersection(*available.values()) & after_latest
        return {m["name"]: shared for m in models}
    return available


def score_data(
    data: dict[str, Any], *, common: bool = False, resamples: int = 1000, **filters: Any
) -> list[dict[str, Any]]:
    selected = selected_problem_ids(data, common=common, **filters)
    problems = {p["id"]: p for p in data["problems"]}
    result = []
    for model in data["models"]:
        name = model["name"]
        if name not in selected:
            continue
        ids = selected[name]
        by_problem: dict[str, list[dict]] = defaultdict(list)
        for row in data["results"]:
            if row["model_name"] == name and row["problem_id"] in ids:
                by_problem[row["problem_id"]].append(row)
        outcomes = [
            Outcome(
                pid, problems[pid]["rating"], sum(row["verdict"] == "AC" for row in rows), len(rows)
            )
            for pid, rows in sorted(by_problem.items())
        ]
        total_cost = sum(r["cost_usd"] for rows in by_problem.values() for r in rows)
        solved = sum(o.accepted > 0 for o in outcomes)
        by_band: dict[int, list[Outcome]] = defaultdict(list)
        by_tag: dict[str, list[Outcome]] = defaultdict(list)
        by_division: dict[str, list[Outcome]] = defaultdict(list)
        for outcome in outcomes:
            problem = problems[outcome.problem_id]
            by_band[outcome.rating // 100 * 100].append(outcome)
            by_division[problem["division"]].append(outcome)
            for tag in problem["tags"]:
                by_tag[tag].append(outcome)
        eligible = len(model["eligible_problem_ids"])
        result.append(
            {
                "name": name,
                "display_name": model["display_name"],
                "pass_at_one": pass_at_one(outcomes),
                "estimated_rating": fit_skill(outcomes),
                "rating_ci": bootstrap_ci(outcomes, resamples=resamples),
                "problem_count": len(outcomes),
                "eligible_problem_count": eligible,
                "samples": sum(o.samples for o in outcomes),
                "solved_problems": solved,
                "total_cost_usd": total_cost,
                "cost_per_solved_problem": total_cost / solved if solved else None,
                "status": "insufficient_data" if min(len(outcomes), eligible) < 20 else "ready",
                "rating_band": {str(k): pass_at_one(v) for k, v in sorted(by_band.items())},
                "tags": {k: pass_at_one(v) for k, v in sorted(by_tag.items())},
                "division": {k: pass_at_one(v) for k, v in sorted(by_division.items())},
                "verdicts": dict(
                    Counter(r["verdict"] for rows in by_problem.values() for r in rows)
                ),
            }
        )
    return sorted(
        result, key=lambda r: (r["pass_at_one"] is not None, r["pass_at_one"] or 0), reverse=True
    )
