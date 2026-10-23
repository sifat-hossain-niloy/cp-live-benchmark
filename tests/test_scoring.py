import random

import pytest

from cflive.scoring import (
    Outcome,
    bootstrap_ci,
    fit_skill,
    pass_at_one,
    selected_problem_ids,
    solve_probability,
)


def test_pass_at_one_balances_problems_not_samples():
    assert pass_at_one([Outcome("a", 800, 1, 1), Outcome("b", 900, 0, 4)]) == 0.5
    assert pass_at_one([]) is None


def test_known_synthetic_skill_mle():
    rng = random.Random(97)
    true_skill = 1850
    outcomes = []
    for i in range(1000):
        rating = rng.randrange(800, 3001, 100)
        k = sum(rng.random() < solve_probability(true_skill, rating) for _ in range(4))
        outcomes.append(Outcome(str(i), rating, k, 4))
    assert fit_skill(outcomes) == pytest.approx(true_skill, abs=40)
    ci = bootstrap_ci(outcomes, resamples=1000)
    assert ci["low"] < fit_skill(outcomes) < ci["high"]
    assert ci["resamples"] == 1000


def test_bootstrap_problem_clusters_and_unbounded_mle():
    outcomes = [Outcome("a", 1200, 0, 4), Outcome("b", 1600, 4, 4)]
    ci = bootstrap_ci(outcomes)
    assert ci["unbounded_low"] and ci["unbounded_high"]
    assert fit_skill([outcomes[0]]) is None
    assert fit_skill([outcomes[1]]) is None
    assert bootstrap_ci(outcomes) == ci


def test_common_window_uses_same_completed_problems_and_latest_cutoff():
    data = {
        "models": [
            {"name": "a", "training_cutoff": "2025-01-01", "scored_problem_ids": ["p", "q", "r"]},
            {"name": "b", "training_cutoff": "2025-02-01", "scored_problem_ids": ["q", "r", "s"]},
        ],
        "problems": [
            {
                "id": pid,
                "verified": True,
                "contest_date": day,
                "rating": 1200,
                "tags": ["math"],
                "division": "Div. 2",
            }
            for pid, day in [
                ("p", "2025-01-20"),
                ("q", "2025-02-01"),
                ("r", "2025-02-02"),
                ("s", "2025-02-03"),
            ]
        ],
    }
    assert selected_problem_ids(data, common=True) == {"a": {"r"}, "b": {"r"}}
    assert selected_problem_ids(data, common=True, since="2025-02-03") == {"a": set(), "b": set()}
