"""Allowlisted public JSON. Never serialize private rows, statements, or test reports."""

import json
import sqlite3
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cflive.collect import collection_summary
from cflive.config import Workspace
from cflive.models import ModelConfig, load_models
from cflive.scoring import score_data
from cflive.workflow import current_approval, problem_dir


def public_dataset(con: sqlite3.Connection, workspace: Workspace) -> dict[str, Any]:
    tags: dict[str, list[str]] = defaultdict(list)
    for row in con.execute("SELECT * FROM problem_tags ORDER BY tag"):
        tags[row["problem_id"]].append(row["tag"])
    problems, verified_sets = [], {}
    draft_count = 0
    for row in con.execute(
        "SELECT p.*,c.division FROM problems p JOIN contests c "
        "ON c.id=p.contest_id WHERE p.exclusion_reason IS NULL ORDER BY p.contest_start,p.id"
    ):
        pid = row["id"]
        directory = problem_dir(workspace, pid)
        draft_count += (directory / "meta.json").exists()
        try:
            verified_sets[pid] = dict(current_approval(con, directory, verified=True))
        except (ValueError, FileNotFoundError):
            pass
        problems.append(
            {
                "id": pid,
                "contest_id": row["contest_id"],
                "index": row["problem_index"],
                "name": row["name"],
                "rating": row["rating"],
                "tags": tags[pid],
                "division": row["division"],
                "contest_start": row["contest_start"],
                "contest_date": datetime.fromtimestamp(row["contest_start"], UTC)
                .date()
                .isoformat(),
                "url": f"https://codeforces.com/contest/{row['contest_id']}/problem/{row['problem_index']}",
                "verified": pid in verified_sets,
                "statement_cached": bool(row["statement_path"]),
            }
        )
    model_records, results, seen = [], [], set()
    runs = con.execute(
        "SELECT * FROM runs WHERE status IN ('complete','budget_stopped') ORDER BY rowid DESC"
    ).fetchall()
    for run in runs:
        name = run["model_name"]
        if name in seen:
            continue
        snapshot = json.loads(run["config_json"])
        config = ModelConfig.model_validate(snapshot["model"])
        if (
            config.provider == "fake"
            or snapshot.get("test_only")
            or snapshot.get("mode") != "single-shot"
        ):
            continue
        config.require_evaluable()
        seen.add(name)
        eligible = {
            p["id"]
            for p in problems
            if p["verified"] and p["contest_start"] > config.cutoff_timestamp()
        }
        rows = con.execute(
            "SELECT g.id AS generation_id,g.problem_id,g.sample_index,g.prompt_hash,"
            "g.cost_usd,g.config_hash,j.verdict,j.failing_category,j.cpu_ms,j.memory_kb,"
            "j.test_set_id,j.created_at FROM judgments j JOIN generations g "
            "ON g.id=j.generation_id WHERE j.run_id=? AND g.status='complete'",
            (run["id"],),
        ).fetchall()
        by_problem: dict[str, list[Any]] = defaultdict(list)
        for row in rows:
            pid = row["problem_id"]
            if (
                pid in eligible
                and row["test_set_id"] == verified_sets[pid]["id"]
                and row["config_hash"] == snapshot["config_hash"]
            ):
                by_problem[pid].append(row)
        complete = {
            pid
            for pid, rows in by_problem.items()
            if sorted(r["sample_index"] for r in rows) == list(range(snapshot["samples"]))
        }
        for pid in sorted(complete):
            for row in by_problem[pid]:
                results.append(
                    {
                        "model_name": name,
                        "problem_id": pid,
                        "sample_index": row["sample_index"],
                        "verdict": row["verdict"],
                        "failing_category": row["failing_category"],
                        "cpu_ms": row["cpu_ms"],
                        "memory_kb": row["memory_kb"],
                        "cost_usd": row["cost_usd"],
                        "prompt_hash": row["prompt_hash"],
                        "run_id": run["id"],
                        "judged_at": row["created_at"],
                        "test_set_hash": verified_sets[pid]["test_hash"],
                    }
                )
        model_records.append(
            {
                "name": name,
                "display_name": config.display_name,
                "provider": config.provider,
                "model_id": config.model_id,
                "training_cutoff": config.training_cutoff.isoformat(),
                "cutoff_source_url": str(config.cutoff_source_url),
                "release_date": config.release_date.isoformat(),
                "sampling": config.sampling,
                "max_output_tokens": config.max_output_tokens,
                "language": config.language,
                "samples_per_problem": snapshot["samples"],
                "eligible_problem_ids": sorted(eligible),
                "scored_problem_ids": sorted(complete),
                "run_id": run["id"],
                "run_date": run["created_at"],
                "run_status": run["status"],
                "image_digest": run["image_digest"],
                "compiler_versions": run["compiler_versions"],
                "calibration_factor": snapshot["calibration_factor"],
                "config_hash": snapshot["config_hash"],
                "template_hash": snapshot["template_hash"],
            }
        )
    configurations = []
    config_path = workspace.root / "models.yaml"
    if config_path.exists():
        for name, model in load_models(config_path).items():
            try:
                model.require_evaluable()
                ready, reason = True, None
            except ValueError as exc:
                ready, reason = False, str(exc)
            configurations.append(
                {
                    "name": name,
                    "display_name": model.display_name,
                    "provider": model.provider,
                    "ready": ready,
                    "reason": reason,
                }
            )
    summary = collection_summary(con)
    data = {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "status": "ready" if results else "awaiting_verified_evaluations",
        "inventory": {
            "collected_candidates": summary["eligible_candidates"],
            "statements_cached": sum(p["statement_cached"] for p in problems),
            "draft_directories": draft_count,
            "verified_problems": len(verified_sets),
            "evaluated_models": len(model_records),
            "configured_models": sum(c["ready"] for c in configurations),
        },
        "collection": summary,
        "model_configurations": configurations,
        "models": sorted(model_records, key=lambda m: m["name"]),
        "problems": problems,
        "results": results,
        "methodology": {
            "bootstrap_resamples": 1000,
            "bootstrap_seed": 1729,
            "cutoff_rule": "Contest start must follow the entire documented cutoff day (UTC).",
            "run_selection": (
                "Latest complete or budget-stopped single-shot run per model; "
                "only complete sample groups."
            ),
            "cost_definition": (
                "Generation cost divided by problems with at least one accepted sample."
            ),
            "rating_caveat": "A logistic performance proxy, not an official Codeforces rating.",
        },
    }
    return data


def export_dataset(
    con: sqlite3.Connection, workspace: Workspace, destination: Path
) -> dict[str, Any]:
    data = public_dataset(con, workspace)
    data["scores"] = {"individual": score_data(data), "common": score_data(data, common=True)}
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False) + "\n")
    temporary.replace(destination)
    return data
