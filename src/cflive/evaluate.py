"""Single-shot evaluation with durable paid-response caching and budget reservations."""

import asyncio
import hashlib
import json
import math
import re
import sqlite3
import uuid
from dataclasses import asdict
from typing import Any

from cflive.config import Workspace
from cflive.judge import DockerJudge
from cflive.models import ModelConfig
from cflive.providers import Adapter, RejectedRequest, UncertainRequest
from cflive.workflow import current_approval, problem_dir, read_meta


def extract_code(text: str, language: str = "cpp17") -> str | None:
    """Only accept one fenced solution in the requested language; no prose heuristics."""
    blocks = re.findall(r"^```([^\n`]*)\n(.*?)^```\s*$", text, re.M | re.S)
    allowed = (
        {"cpp", "c++", "cpp17", "c++17", "cc", ""}
        if language == "cpp17"
        else {"python", "python3", "py", ""}
    )
    candidates = [
        code.strip() for label, code in blocks if label.strip().lower() in allowed and code.strip()
    ]
    return candidates[0] + "\n" if len(candidates) == 1 else None


def render_prompt(
    template: str, statement: dict[str, Any], meta: dict[str, Any], language: str
) -> str:
    samples = "\n\n".join(
        f"Input:\n{s['input']}\nOutput:\n{s['output']}" for s in statement["samples"]
    )
    return template.format(
        language_name="C++17" if language == "cpp17" else "Python 3",
        fence="cpp" if language == "cpp17" else "python",
        title=statement["title"],
        legend=statement["legend"],
        input_spec=statement["input"],
        output_spec=statement["output"],
        notes=statement.get("notes", ""),
        samples=samples,
        time_limit_seconds=meta["time_limit_seconds"],
        memory_limit_mb=meta["memory_limit_mb"],
    )


def eligible_problems(
    con: sqlite3.Connection,
    workspace: Workspace,
    config: ModelConfig,
    problem_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    config.require_evaluable()
    rows = con.execute(
        "SELECT * FROM problems WHERE exclusion_reason IS NULL "
        "AND contest_start>? ORDER BY contest_start,id",
        (config.cutoff_timestamp(),),
    ).fetchall()
    selected = []
    failures = {}
    for row in rows:
        if problem_ids is not None and row["id"] not in problem_ids:
            continue
        directory = problem_dir(workspace, row["id"])
        try:
            approval = current_approval(con, directory, verified=True)
            selected.append({**dict(row), "test_set": dict(approval), "directory": directory})
        except (ValueError, FileNotFoundError) as exc:
            failures[row["id"]] = str(exc)
    if problem_ids is not None:
        missing = set(problem_ids) - {p["id"] for p in selected}
        if missing:
            raise ValueError(
                "Requested problems are excluded, before cutoff, or unverified: "
                + ", ".join(sorted(missing))
            )
    return selected


def _cost(config: ModelConfig, input_tokens: int, output_tokens: int) -> float:
    assert config.prices is not None
    return (
        input_tokens * config.prices.input_per_million
        + output_tokens * config.prices.output_per_million
    ) / 1_000_000


class BudgetExceeded(RuntimeError):
    pass


def reserve_generation(con: sqlite3.Connection, run_id: str, key: tuple, amount: float) -> int:
    """Claim the cache key and reserve maximum cost in one SQLite write transaction."""
    con.commit()
    con.execute("BEGIN IMMEDIATE")
    try:
        run = con.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        if run["spent_usd"] + run["reserved_usd"] + amount > run["budget_usd"] + 1e-12:
            raise BudgetExceeded("Next response's maximum token cost would exceed the run budget")
        cursor = con.execute(
            "INSERT INTO generations(run_id,model_name,problem_id,prompt_hash,"
            "config_hash,sample_index,status,reservation_usd) "
            "VALUES(?,?,?,?,?,?,'in_flight',?)",
            (run_id, *key, amount),
        )
        con.execute("UPDATE runs SET reserved_usd=reserved_usd+? WHERE id=?", (amount, run_id))
        con.commit()
        return cursor.lastrowid
    except BaseException:
        con.rollback()
        raise


async def evaluate(
    con: sqlite3.Connection,
    workspace: Workspace,
    *,
    name: str,
    config: ModelConfig,
    adapter: Adapter,
    judge: DockerJudge,
    template: str,
    budget_usd: float,
    samples: int = 4,
    problem_ids: list[str] | None = None,
    judge_workers: int = 2,
    resume: str | None = None,
    require_calibration: bool = True,
) -> dict[str, Any]:
    config.require_evaluable()
    if not math.isfinite(budget_usd) or budget_usd < 0 or samples < 1 or judge_workers < 1:
        raise ValueError("Nonnegative finite budget and positive samples/workers are required")
    if config.provider == "fake" and require_calibration:
        raise ValueError("The fake provider is for offline tests only")
    if require_calibration:
        path = workspace.data / "calibration.json"
        if not path.exists():
            raise ValueError(
                "Evaluation requires a measured data/calibration.json; run cflive calibrate"
            )
        calibration = json.loads(path.read_text())
        if calibration["judge"] != judge.identity or calibration["factor"] != judge.factor:
            raise ValueError("Calibration image/platform/factor does not match the judge")
    problems = eligible_problems(con, workspace, config, problem_ids)
    if not problems:
        raise ValueError("No verified problems after the documented model cutoff")
    for problem in problems:
        report = json.loads(problem["test_set"]["report_json"])
        if report["judge"] != judge.identity or report["calibration_factor"] != judge.factor:
            raise ValueError(f"{problem['id']}: reverify with this calibrated judge image/platform")
    con.execute(
        "INSERT INTO models VALUES(?,?,?,?,?,?,?) ON CONFLICT(name) DO UPDATE SET "
        "provider=excluded.provider,model_id=excluded.model_id,display_name=excluded.display_name,"
        "cutoff=excluded.cutoff,cutoff_source=excluded.cutoff_source,config_json=excluded.config_json",
        (
            name,
            config.provider,
            config.model_id,
            config.display_name,
            config.training_cutoff.isoformat(),
            str(config.cutoff_source_url),
            json.dumps(config.snapshot()),
        ),
    )
    snapshot = {
        "model": config.snapshot(),
        "samples": samples,
        "judge_workers": judge_workers,
        "problem_ids": [p["id"] for p in problems],
        "problem_snapshot": [
            {
                "id": p["id"],
                "rating": p["rating"],
                "contest_start": p["contest_start"],
                "time_limit": p["time_limit"],
                "memory_limit": p["memory_limit"],
                "artifact_hash": p["test_set"]["artifact_hash"],
                "test_hash": p["test_set"]["test_hash"],
            }
            for p in problems
        ],
        "config_hash": config.request_hash(),
        "metadata_hash": config.hash(),
        "template_hash": hashlib.sha256(template.encode()).hexdigest(),
        "calibration_factor": judge.factor,
        "mode": "single-shot",
        "test_only": config.provider == "fake",
    }
    if resume:
        previous = con.execute("SELECT * FROM runs WHERE id=?", (resume,)).fetchone()
        if not previous or json.loads(previous["config_json"]) != snapshot:
            raise ValueError(
                "Resume requires identical model, sampling, prompt, problem set, and workers"
            )
        if previous["image_digest"] != judge.image or previous["budget_usd"] != budget_usd:
            raise ValueError("Resume requires identical judge image and budget")
        run_id = resume
        con.execute(
            "UPDATE runs SET status='running',stop_reason=NULL,finished_at=NULL WHERE id=?",
            (run_id,),
        )
    else:
        run_id = uuid.uuid4().hex
        con.execute(
            "INSERT INTO runs(id,model_name,config_json,image_digest,compiler_versions,"
            "status,budget_usd) VALUES(?,?,?,?,?,'running',?)",
            (run_id, name, json.dumps(snapshot), judge.image, judge.compiler_versions, budget_usd),
        )
    con.commit()
    report: dict[str, Any] = {
        "run_id": run_id,
        "completed": 0,
        "cached": 0,
        "status": "complete",
        "errors": [],
        "stopped_at": None,
    }
    stopped = asyncio.Event()
    provider_slots, judge_slots = (
        asyncio.Semaphore(config.concurrency),
        asyncio.Semaphore(judge_workers),
    )
    queue: asyncio.Queue = asyncio.Queue()
    for problem in problems:
        directory = problem["directory"]
        meta = read_meta(directory)
        statement = json.loads((directory / "statement.json").read_text())
        prompt = render_prompt(template, statement, meta, config.language)
        prompt_hash = hashlib.sha256(prompt.encode()).hexdigest()
        con.execute(
            "INSERT OR IGNORE INTO prompts(hash,template) VALUES(?,?)", (prompt_hash, prompt)
        )
        for sample in range(samples):
            queue.put_nowait((problem, meta, prompt, prompt_hash, sample))
    con.commit()

    async def one(problem, meta, prompt, prompt_hash, sample) -> None:
        key = (name, problem["id"], prompt_hash, config.request_hash(), sample)
        cached = con.execute(
            "SELECT * FROM generations WHERE model_name=? AND problem_id=? "
            "AND prompt_hash=? AND config_hash=? AND sample_index=?",
            key,
        ).fetchone()
        if cached and cached["status"] != "complete":
            raise UncertainRequest(
                f"Generation {cached['id']} is {cached['status']}; resolve it before retrying"
            )
        if cached:
            generation_id, code = cached["id"], cached["code"]
            report["cached"] += 1
        else:
            async with provider_slots:
                if stopped.is_set():
                    return
                counted = await adapter.count_input(prompt)
                if stopped.is_set():
                    return
                # Count endpoints can have small formatting differences. Reserve a documented
                # experiment safety margin; this is not a model context/capability claim.
                input_bound = counted + max(1024, counted // 20)
                amount = _cost(config, input_bound, config.max_output_tokens)
                generation_id = reserve_generation(con, run_id, key, amount)
                try:
                    response = await adapter.generate(prompt)
                except RejectedRequest as exc:
                    con.execute("DELETE FROM generations WHERE id=?", (generation_id,))
                    con.execute(
                        "UPDATE runs SET reserved_usd=reserved_usd-? WHERE id=?", (amount, run_id)
                    )
                    con.commit()
                    raise exc
                except BaseException as exc:
                    raw = getattr(exc, "raw", None)
                    con.execute(
                        "UPDATE generations SET status='uncertain',error=?,response_json=? "
                        "WHERE id=?",
                        (str(exc), json.dumps(raw) if raw else None, generation_id),
                    )
                    con.commit()  # Keep maximum budget reserved until billing is reconciled.
                    raise
                actual_cost = (
                    response.reported_cost
                    if response.reported_cost is not None
                    else _cost(config, response.input_tokens, response.output_tokens)
                )
                code = extract_code(response.text, config.language)
                # Durably retain every successful response even if billing metadata is invalid.
                con.execute(
                    "UPDATE generations SET status='received',raw_response=?,code=?,"
                    "response_json=?,input_tokens=?,output_tokens=?,reasoning_tokens=?,"
                    "latency_ms=? "
                    "WHERE id=?",
                    (
                        response.text,
                        code,
                        json.dumps(response.raw),
                        response.input_tokens,
                        response.output_tokens,
                        response.reasoning_tokens,
                        response.latency_ms,
                        generation_id,
                    ),
                )
                con.commit()
                if not math.isfinite(actual_cost) or actual_cost < 0:
                    raise UncertainRequest("Provider reported invalid billing data")
                con.execute(
                    "UPDATE generations SET status='complete',raw_response=?,code=?,"
                    "input_tokens=?,output_tokens=?,reasoning_tokens=?,cost_usd=?,latency_ms=?,"
                    "response_json=?,reservation_usd=0 WHERE id=?",
                    (
                        response.text,
                        code,
                        response.input_tokens,
                        response.output_tokens,
                        response.reasoning_tokens,
                        actual_cost,
                        response.latency_ms,
                        json.dumps(response.raw),
                        generation_id,
                    ),
                )
                con.execute(
                    "UPDATE runs SET reserved_usd=reserved_usd-?,spent_usd=spent_usd+? WHERE id=?",
                    (amount, actual_cost, run_id),
                )
                # Persist paid response before compilation, judging, or further API work.
                con.commit()
                if actual_cost > amount + 1e-12:
                    raise UncertainRequest(
                        "Reported cost exceeded reservation: pricing/token ceiling must be reviewed"
                    )
        previous = con.execute(
            "SELECT id FROM judgments WHERE generation_id=? AND test_set_id=? AND run_id=?",
            (generation_id, problem["test_set"]["id"], run_id),
        ).fetchone()
        if previous:
            report["completed"] += 1
            return
        async with judge_slots:
            # Detect edits during an in-progress run before spending compute on obsolete tests.
            current_approval(con, problem["directory"], verified=True)
            tests = json.loads((problem["directory"] / "hidden" / "tests.json").read_text())
            judgment = await asyncio.to_thread(
                judge.judge,
                code,
                tests,
                time_limit=meta["time_limit_seconds"],
                memory_mb=meta["memory_limit_mb"],
                checker=meta["checker"],
                language=config.language,
                custom_path=problem["directory"] / "checker.py",
            )
            con.execute(
                "INSERT INTO judgments(generation_id,test_set_id,run_id,verdict,failing_test,"
                "failing_category,cpu_ms,wall_ms,memory_kb,details_json) "
                "VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    generation_id,
                    problem["test_set"]["id"],
                    run_id,
                    judgment.verdict,
                    judgment.failing_test,
                    judgment.failing_category,
                    judgment.cpu_ms,
                    judgment.wall_ms,
                    judgment.memory_kb,
                    json.dumps(asdict(judgment)),
                ),
            )
            con.commit()
            report["completed"] += 1

    async def worker() -> None:
        while not queue.empty() and not stopped.is_set():
            item = queue.get_nowait()
            try:
                await one(*item)
            except Exception as exc:
                stopped.set()
                report["status"] = (
                    "budget_stopped" if isinstance(exc, BudgetExceeded) else "needs_attention"
                )
                report["errors"].append(str(exc))
                report["stopped_at"] = {"problem_id": item[0]["id"], "sample_index": item[4]}
            finally:
                queue.task_done()

    try:
        await asyncio.gather(*(worker() for _ in range(max(config.concurrency, judge_workers))))
    except BaseException:
        con.execute(
            "UPDATE runs SET status='interrupted',stop_reason='Interrupted' WHERE id=?", (run_id,)
        )
        con.commit()
        raise
    status = con.execute("SELECT spent_usd,reserved_usd FROM runs WHERE id=?", (run_id,)).fetchone()
    report.update(dict(status))
    con.execute(
        "UPDATE runs SET status=?,stop_reason=?,finished_at=CURRENT_TIMESTAMP WHERE id=?",
        (report["status"], json.dumps(report), run_id),
    )
    con.commit()
    return report


def reconcile_generation(
    con: sqlite3.Connection,
    workspace: Workspace,
    generation_id: int,
    *,
    note: str,
    response_json: dict | None = None,
    confirmed_not_billed: bool = False,
) -> dict[str, Any]:
    """Operator-only recovery after checking provider logs; never issues a network request."""
    from cflive.providers import parse_response

    row = con.execute("SELECT * FROM generations WHERE id=?", (generation_id,)).fetchone()
    if not row or row["status"] == "complete":
        raise ValueError("Select an unresolved generation")
    if not note.strip() or (response_json is None) == (not confirmed_not_billed):
        raise ValueError(
            "Supply an audit note and exactly one of response JSON or confirmed-not-billed"
        )
    run = con.execute("SELECT * FROM runs WHERE id=?", (row["run_id"],)).fetchone()
    directory = workspace.data / "reconciliations"
    directory.mkdir(exist_ok=True)
    audit = {
        "generation": dict(row),
        "note": note,
        "confirmed_not_billed": confirmed_not_billed,
        "response": response_json,
    }
    (directory / f"{generation_id}-{uuid.uuid4().hex}.json").write_text(json.dumps(audit, indent=2))
    if confirmed_not_billed:
        con.execute("DELETE FROM generations WHERE id=?", (generation_id,))
        con.execute(
            "UPDATE runs SET reserved_usd=MAX(0,reserved_usd-?) WHERE id=?",
            (row["reservation_usd"], row["run_id"]),
        )
        con.commit()
        return {"generation_id": generation_id, "status": "released", "note": note}
    config = ModelConfig.model_validate(json.loads(run["config_json"])["model"])
    response = parse_response(config.provider, response_json, 0)
    cost = (
        response.reported_cost
        if response.reported_cost is not None
        else _cost(config, response.input_tokens, response.output_tokens)
    )
    if not math.isfinite(cost) or cost < 0:
        raise ValueError("Invalid recovered cost")
    con.execute(
        "UPDATE generations SET status='complete',raw_response=?,code=?,response_json=?,"
        "input_tokens=?,output_tokens=?,reasoning_tokens=?,cost_usd=?,reservation_usd=0,"
        "error=NULL WHERE id=?",
        (
            response.text,
            extract_code(response.text, config.language),
            json.dumps(response_json),
            response.input_tokens,
            response.output_tokens,
            response.reasoning_tokens,
            cost,
            generation_id,
        ),
    )
    con.execute(
        "UPDATE runs SET reserved_usd=MAX(0,reserved_usd-?),spent_usd=spent_usd+? WHERE id=?",
        (row["reservation_usd"], cost, row["run_id"]),
    )
    con.commit()
    return {"generation_id": generation_id, "status": "recovered", "cost_usd": cost}
