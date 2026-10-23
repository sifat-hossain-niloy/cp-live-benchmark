"""Approval, provenance, and reproducible problem verification. All artifacts are private."""

import getpass
import hashlib
import json
import re
import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cflive.checkers import check
from cflive.collect import CodeforcesAPI
from cflive.config import Workspace
from cflive.judge import DockerJudge, Program

ARTIFACT_NAMES = (
    "statement.json",
    "reference.cpp",
    "brute.cpp",
    "brute.py",
    "gen.py",
    "validator.py",
    "checker.py",
    "meta.json",
)
MUTABLE_META = {"status", "approved_at", "approved_by", "artifact_hash", "verification"}


def problem_dir(workspace: Workspace, pid: str) -> Path:
    if not re.fullmatch(r"[1-9]\d{0,5}[A-Z][A-Z0-9]{0,3}", pid):
        raise ValueError("Invalid Codeforces problem ID")
    return workspace.problems / pid


def read_meta(directory: Path) -> dict[str, Any]:
    return json.loads((directory / "meta.json").read_text())


def write_meta(directory: Path, meta: dict[str, Any]) -> None:
    (directory / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n")


def artifact_hash(directory: Path) -> str:
    digest = hashlib.sha256()
    for name in ARTIFACT_NAMES:
        path = directory / name
        if not path.exists():
            continue
        if path.is_symlink():
            raise ValueError(f"Problem assets cannot be symlinks: {name}")
        payload = path.read_bytes()
        if name == "meta.json":
            payload = json.dumps(
                {k: v for k, v in read_meta(directory).items() if k not in MUTABLE_META},
                sort_keys=True,
            ).encode()
        digest.update(name.encode() + b"\0" + payload + b"\0")
    return digest.hexdigest()


def test_hash(tests: list[dict[str, Any]]) -> str:
    return hashlib.sha256(
        json.dumps(tests, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def scaffold(con: sqlite3.Connection, workspace: Workspace, pid: str) -> Path:
    row = con.execute("SELECT * FROM problems WHERE id=?", (pid,)).fetchone()
    if not row or not row["statement_path"] or row["exclusion_reason"]:
        raise ValueError("Scaffolding requires a parsed, non-excluded statement")
    directory = problem_dir(workspace, pid)
    directory.mkdir(parents=True, exist_ok=True)
    tags = [r[0] for r in con.execute("SELECT tag FROM problem_tags WHERE problem_id=?", (pid,))]
    templates = {
        "reference.cpp": '#error "DRAFT: insert known Accepted C++17 source; attest provenance"\n',
        "brute.py": "# DRAFT: implement a small-input oracle, then approve.\n"
        'raise NotImplementedError("Implement independently correct brute force")\n',
        "gen.py": """# DRAFT: seeded generator interface. stdout is one complete valid test input.
import argparse
parser = argparse.ArgumentParser()
parser.add_argument('--seed', type=int, required=True)
parser.add_argument('--mode', required=True,
                    choices=['small_random','edge','max_size','adversarial'])
args = parser.parse_args()
raise NotImplementedError('Implement the exact constraints and each generation mode')
""",
        "validator.py": "# DRAFT: consume stdin; exit 0 only if ALL exact constraints hold.\n"
        'raise NotImplementedError("Implement exact input constraint checks")\n',
        "REVIEW.md": "# Private problem review\n\n"
        "- [ ] Source equals the known Accepted reference\n"
        "- [ ] Brute is independently correct\n- [ ] Validator covers all constraints\n"
        "- [ ] Generator covers edges, max sizes, and relevant adversarial inputs\n"
        "- [ ] Checker validates all valid outputs and optimal value\n"
        "- [ ] Run attest-reference and approve only after manual review\n",
    }
    if row["multi_answer"]:
        templates[
            "checker.py"
        ] = """# DRAFT custom checker: argv = input_path, reference_answer_path, output_path.
# Read paths, validate feasibility and objective against the reference's optimal value.
# Print JSON {"accepted": bool, "message": str}; exceptions mean checker infrastructure failure.
raise NotImplementedError('Review whether this multi-answer flag is applicable; implement checker')
"""
    for name, content in templates.items():
        path = directory / name
        if not path.exists():
            path.write_text(content)
    if not (directory / "statement.json").exists():
        shutil.copyfile(row["statement_path"], directory / "statement.json")
    if not (directory / "meta.json").exists():
        write_meta(
            directory,
            {
                "problem_id": pid,
                "status": "draft",
                "rating": row["rating"],
                "tags": tags,
                "contest_start": row["contest_start"],
                "time_limit_seconds": row["time_limit"],
                "memory_limit_mb": row["memory_limit"],
                "checker": "custom" if row["multi_answer"] else "tokens",
                "multi_answer": bool(row["multi_answer"]),
                "provenance": {
                    "kind": "accepted_submission",
                    "submission_id": None,
                    "handle": None,
                    "url": None,
                    "verified": False,
                },
                "generation": {
                    "seed": 1729,
                    "small_count": 500,
                    "edge_count": 10,
                    "final_small_count": 12,
                    "max_size_count": 5,
                    "adversarial_count": 0,
                },
            },
        )
    return directory


def attest_reference(
    con: sqlite3.Connection,
    workspace: Workspace,
    pid: str,
    *,
    submission_id: int,
    handle: str,
    api: CodeforcesAPI,
    reviewer: str | None = None,
) -> dict[str, Any]:
    """Human attests local source equality; API independently confirms the submission's AC."""
    directory = problem_dir(workspace, pid)
    row = con.execute("SELECT * FROM problems WHERE id=?", (pid,)).fetchone()
    if not row:
        raise ValueError("Unknown problem")
    found = None
    for start in range(1, 10001, 1000):
        submissions = api.call("user.status", handle=handle, **{"from": start, "count": 1000})
        found = next((s for s in submissions if s["id"] == submission_id), None)
        if found or len(submissions) < 1000:
            break
    if not found or found.get("verdict") != "OK":
        raise ValueError(
            "Submission is absent from the latest 10000 submissions or is not Accepted"
        )
    problem = found["problem"]
    if (problem.get("contestId"), problem["index"]) != (row["contest_id"], row["problem_index"]):
        raise ValueError("Accepted submission belongs to another problem")
    if "C++" not in found.get("programmingLanguage", ""):
        raise ValueError("Reference must be a C++ solution; review compatibility with C++17")
    meta = read_meta(directory)
    meta["provenance"] = {
        "kind": "accepted_submission",
        "submission_id": submission_id,
        "handle": handle,
        "verified": True,
        "url": f"https://codeforces.com/contest/{row['contest_id']}/submission/{submission_id}",
        "source_sha256": hashlib.sha256((directory / "reference.cpp").read_bytes()).hexdigest(),
        "attested_by": reviewer or getpass.getuser(),
        "attested_at": datetime.now(UTC).isoformat(),
        "api_evidence": found,
    }
    meta["status"] = "draft"
    write_meta(directory, meta)
    con.execute("UPDATE test_sets SET status='stale' WHERE problem_id=?", (pid,))
    return meta["provenance"]


def require_provenance(directory: Path, meta: dict[str, Any]) -> None:
    p = meta.get("provenance", {})
    if not p.get("verified") or not p.get("url") or not p.get("attested_by"):
        raise ValueError(
            "An accepted reference with checked provenance and source attestation is required"
        )
    if p.get("kind") not in {"accepted_submission", "editorial"}:
        raise ValueError("Provenance kind must be accepted_submission or editorial")
    if p.get("kind") == "accepted_submission":
        evidence = p.get("api_evidence", {})
        if evidence.get("verdict") != "OK" or evidence.get("id") != p.get("submission_id"):
            raise ValueError("Missing Accepted-submission API evidence")
    if (
        p.get("source_sha256")
        != hashlib.sha256((directory / "reference.cpp").read_bytes()).hexdigest()
    ):
        raise ValueError("Reference changed after source provenance was attested")


def require_source_metadata(con: sqlite3.Connection, pid: str, meta: dict[str, Any]) -> None:
    """Do not silently change CF limits, dates, or difficulty when reviewing local assets."""
    row = con.execute("SELECT * FROM problems WHERE id=?", (pid,)).fetchone()
    if row is None or row["exclusion_reason"]:
        raise ValueError("Problem is absent or excluded from the collected candidate pool")
    expected = {
        "problem_id": pid,
        "contest_start": row["contest_start"],
        "rating": row["rating"],
        "time_limit_seconds": row["time_limit"],
        "memory_limit_mb": row["memory_limit"],
    }
    changed = [key for key, value in expected.items() if meta.get(key) != value]
    tags = {r[0] for r in con.execute("SELECT tag FROM problem_tags WHERE problem_id=?", (pid,))}
    if set(meta.get("tags", [])) != tags:
        changed.append("tags")
    if changed:
        raise ValueError("Metadata differs from collected Codeforces source: " + ", ".join(changed))


def approve(
    con: sqlite3.Connection, workspace: Workspace, pid: str, reviewer: str | None = None
) -> str:
    directory = problem_dir(workspace, pid)
    meta = read_meta(directory)
    require_source_metadata(con, pid, meta)
    require_provenance(directory, meta)
    required = ["reference.cpp", "gen.py", "validator.py", "statement.json"]
    if not ((directory / "brute.cpp").exists() or (directory / "brute.py").exists()):
        raise ValueError("A brute-force oracle is required")
    if meta.get("multi_answer") and meta.get("checker") != "custom":
        raise ValueError("Flagged multi-answer problems require a custom checker")
    if meta.get("checker") == "custom":
        required.append("checker.py")
    for name in required:
        if not (directory / name).is_file():
            raise ValueError(f"Missing required asset: {name}")
    digest = artifact_hash(directory)
    existing = con.execute(
        "SELECT id FROM test_sets WHERE problem_id=? AND artifact_hash=? "
        "AND status IN ('approved','verified')",
        (pid, digest),
    ).fetchone()
    if existing:
        return digest
    con.execute("UPDATE test_sets SET status='stale' WHERE problem_id=?", (pid,))
    now, by = datetime.now(UTC).isoformat(), reviewer or getpass.getuser()
    con.execute(
        "INSERT INTO test_sets(problem_id,artifact_hash,status,approved_by,approved_at) "
        "VALUES(?,?,'approved',?,?)",
        (pid, digest, by, now),
    )
    meta.update(status="approved", artifact_hash=digest, approved_by=by, approved_at=now)
    write_meta(directory, meta)
    return digest


def current_approval(con: sqlite3.Connection, directory: Path, *, verified: bool = False):
    pid = directory.name
    require_source_metadata(con, pid, read_meta(directory))
    digest = artifact_hash(directory)
    status = "status='verified'" if verified else "status IN ('approved','verified')"
    row = con.execute(
        f"SELECT * FROM test_sets WHERE problem_id=? AND artifact_hash=? "
        f"AND {status} ORDER BY id DESC LIMIT 1",
        (pid, digest),
    ).fetchone()
    if not row:
        raise ValueError(f"{pid}: assets are unapproved or changed since approval")
    if verified:
        path = directory / "hidden" / "tests.json"
        if not path.exists() or test_hash(json.loads(path.read_text())) != row["test_hash"]:
            raise ValueError(f"{pid}: hidden tests changed since verification")
    return row


def _compile(judge: DockerJudge, path: Path) -> Program:
    program, result = judge.compile(
        path.read_text(), "cpp17" if path.suffix == ".cpp" else "python3"
    )
    if not program:
        raise ValueError(f"{path.name}: compilation failed: {result.stderr}")
    return program


def verify(
    con: sqlite3.Connection, workspace: Workspace, pid: str, judge: DockerJudge
) -> dict[str, Any]:
    """Fail closed; reports and failing inputs remain private even on partial verification."""
    directory = problem_dir(workspace, pid)
    approval = current_approval(con, directory)
    meta = read_meta(directory)
    require_provenance(directory, meta)
    statement = json.loads((directory / "statement.json").read_text())
    plan = meta["generation"]
    if plan["small_count"] < 500 or plan["max_size_count"] < 5:
        raise ValueError("Verification requires >=500 small random and >=5 max-size tests")
    if plan["edge_count"] < 1 or plan["final_small_count"] < 1:
        raise ValueError("At least one edge and final small-random test is required")
    count = (
        len(statement["samples"])
        + plan["edge_count"]
        + plan["final_small_count"]
        + plan["max_size_count"]
        + plan.get("adversarial_count", 0)
    )
    if not 20 <= count <= 80 or plan["final_small_count"] > plan["small_count"]:
        raise ValueError("Final hidden set must contain 20–80 tests and a subset of small cases")
    hidden = directory / "hidden"
    hidden.mkdir(exist_ok=True)
    con.execute(
        "UPDATE test_sets SET status='approved',test_hash=NULL WHERE id=?", (approval["id"],)
    )
    con.commit()  # Old verification must not survive an interrupted re-verification.
    report: dict[str, Any] = {
        "problem_id": pid,
        "artifact_hash": approval["artifact_hash"],
        "judge": judge.identity,
        "compiler_versions": judge.compiler_versions,
        "calibration_factor": judge.factor,
        "counts": {},
        "max_cpu_ms": 0,
        "status": "failed",
    }
    final_tests = []
    timings = []
    try:
        reference = _compile(judge, directory / "reference.cpp")
        brute_path = directory / ("brute.cpp" if (directory / "brute.cpp").exists() else "brute.py")
        brute = _compile(judge, brute_path)
        generator = _compile(judge, directory / "gen.py")
        validator = _compile(judge, directory / "validator.py")
        custom = directory / "checker.py"
        limits = {"time_limit": meta["time_limit_seconds"], "memory_mb": meta["memory_limit_mb"]}

        def validate_and_reference(
            input_text: str, category: str, case: int, *, compare_brute: bool
        ) -> dict[str, Any]:
            test_id = f"{category}-{case:04d}"
            report["active_test"] = test_id
            (hidden / "last_input.txt").write_text(input_text)
            valid = judge.run(validator, input_text, time_limit=5, memory_mb=256)
            if valid.verdict != "OK":
                raise ValueError(f"Validator rejected {test_id}: {valid.verdict} {valid.stderr}")
            result = judge.run(reference, input_text, **limits)
            if result.verdict != "OK":
                raise ValueError(f"Reference failed {test_id}: {result.verdict} {result.stderr}")
            if category == "max_size":
                if result.cpu_ms > limits["time_limit"] * judge.factor * 500:
                    raise ValueError(f"Reference exceeds 50% of calibrated time limit on {test_id}")
                timings.append(
                    {"test_id": test_id, "cpu_ms": result.cpu_ms, "memory_kb": result.memory_kb}
                )
            if compare_brute:
                expected = judge.run(brute, input_text, time_limit=10, memory_mb=512)
                if expected.verdict != "OK":
                    raise ValueError(f"Brute failed {test_id}: {expected.verdict}")
                comparison = check(
                    meta["checker"],
                    input_text,
                    expected.stdout,
                    result.stdout,
                    custom_path=custom,
                    sandbox=judge,
                )
                if not comparison.accepted:
                    (hidden / "mismatch-reference.txt").write_text(result.stdout)
                    (hidden / "mismatch-brute.txt").write_text(expected.stdout)
                    raise ValueError(f"Reference/brute mismatch on {test_id}: {comparison.message}")
            report["counts"][category] = report["counts"].get(category, 0) + 1
            return {
                "id": test_id,
                "category": category,
                "input": input_text,
                "output": result.stdout,
            }

        for i, sample in enumerate(statement["samples"]):
            test = validate_and_reference(sample["input"], "sample", i, compare_brute=False)
            if not check(
                meta["checker"],
                sample["input"],
                sample["output"],
                test["output"],
                custom_path=custom,
                sandbox=judge,
            ).accepted:
                raise ValueError(f"Reference failed official sample {i}")
            final_tests.append(test)
        modes = [
            ("small_random", plan["small_count"]),
            ("edge", plan["edge_count"]),
            ("max_size", plan["max_size_count"]),
            ("adversarial", plan.get("adversarial_count", 0)),
        ]
        for mode, total in modes:
            for i in range(total):
                seed = plan["seed"] + i
                generated = judge.run(
                    generator,
                    "",
                    time_limit=10,
                    memory_mb=512,
                    arguments=["--mode", mode, "--seed", str(seed)],
                )
                if generated.verdict != "OK" or not generated.stdout.strip():
                    raise ValueError(f"Generator failed: {mode}/{seed}: {generated.stderr}")
                test = validate_and_reference(
                    generated.stdout, mode, i, compare_brute=mode in {"small_random", "edge"}
                )
                test["seed"] = seed
                if mode != "small_random" or i < plan["final_small_count"]:
                    final_tests.append(test)
        if artifact_hash(directory) != approval["artifact_hash"]:
            raise ValueError("Assets changed during verification")
        report.update(
            status="verified",
            final_count=len(final_tests),
            max_timings=timings,
            max_cpu_ms=max((t["cpu_ms"] for t in timings), default=0),
        )
        digest = test_hash(final_tests)
        (hidden / "tests.json").write_text(json.dumps(final_tests, ensure_ascii=False))
        con.execute(
            "UPDATE test_sets SET status='verified',test_hash=?,report_json=? WHERE id=?",
            (digest, json.dumps(report), approval["id"]),
        )
        meta["status"] = "verified"
        meta["verification"] = report
        write_meta(directory, meta)
    except (ValueError, RuntimeError) as exc:
        report["error"] = str(exc)
        report["failing_input_path"] = str(hidden / "last_input.txt")
        con.execute(
            "UPDATE test_sets SET status='approved',report_json=? WHERE id=?",
            (json.dumps(report), approval["id"]),
        )
        meta["status"] = "approved"
        write_meta(directory, meta)
    (hidden / "verification-report.json").write_text(json.dumps(report, indent=2))
    return report
