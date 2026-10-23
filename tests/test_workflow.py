from pathlib import Path

import pytest

from cflive.db import connect
from cflive.judge import Execution, Program
from cflive.workflow import (
    approve,
    artifact_hash,
    current_approval,
    read_meta,
    scaffold,
    verify,
    write_meta,
)
from tests.helpers import synthetic_problem


class FakeJudge:
    identity = {"image_id": "sha256:synthetic", "architecture": "test"}
    compiler_versions = "synthetic test double"
    factor = 1.0
    bad_validator = False
    bad_brute = False
    slow = False

    def compile(self, code, language):
        # Kept separate in tests: the workflow's _compile supplies the source content.
        return Program(__import__("pathlib").Path(code.splitlines()[0]), language), Execution("OK")

    def run(self, program, input_text, **kwargs):
        name = program.path.name
        if name == "gen.py":
            arguments = kwargs["arguments"]
            return Execution("OK", stdout=f"{arguments[-1]} 1\n")
        if name == "validator.py":
            return Execution("RE" if self.bad_validator else "OK")
        value = sum(map(int, input_text.split())) + int(self.bad_brute and name == "brute.py")
        return Execution("OK", stdout=str(value), cpu_ms=1500 if self.slow else 5)


def prepare_fake(directory):
    for name in ("reference.cpp", "brute.py", "gen.py", "validator.py"):
        (directory / name).write_text(name + "\n")
    import hashlib

    meta = read_meta(directory)
    meta["provenance"]["source_sha256"] = hashlib.sha256(
        (directory / "reference.cpp").read_bytes()
    ).hexdigest()
    write_meta(directory, meta)


def test_scaffold_resumes_without_overwriting(tmp_path):
    with connect(tmp_path / "db") as con:
        ws, directory = synthetic_problem(con, tmp_path)
        before = (directory / "reference.cpp").read_text()
        scaffold(con, ws, "2000A")
        assert (directory / "reference.cpp").read_text() == before


def test_approval_requires_provenance_and_detects_mutation(tmp_path):
    with connect(tmp_path / "db") as con:
        ws, directory = synthetic_problem(con, tmp_path)
        meta = read_meta(directory)
        meta["provenance"]["verified"] = False
        write_meta(directory, meta)
        with pytest.raises(ValueError, match="provenance"):
            approve(con, ws, "2000A")
        meta["provenance"]["verified"] = True
        write_meta(directory, meta)
        digest = approve(con, ws, "2000A", "reviewer")
        assert approve(con, ws, "2000A", "reviewer") == digest
        assert current_approval(con, directory)["approved_by"] == "reviewer"
        (directory / "gen.py").write_text("changed")
        with pytest.raises(ValueError, match="changed"):
            current_approval(con, directory)


def test_full_verification_counts_and_hidden_integrity(tmp_path):
    with connect(tmp_path / "db") as con:
        ws, directory = synthetic_problem(con, tmp_path)
        prepare_fake(directory)
        approve(con, ws, "2000A")
        digest = artifact_hash(directory)
        report = verify(con, ws, "2000A", FakeJudge())
        assert report["status"] == "verified"
        assert report["counts"]["small_random"] == 500
        assert report["counts"]["edge"] == 10
        assert report["counts"]["max_size"] == 5
        assert 20 <= report["final_count"] <= 80
        assert artifact_hash(directory) == digest
        current_approval(con, directory, verified=True)
        (directory / "hidden" / "tests.json").write_text("[]")
        with pytest.raises(ValueError, match="hidden tests changed"):
            current_approval(con, directory, verified=True)


@pytest.mark.parametrize(
    "failure,error",
    [("bad_validator", "Validator rejected"), ("bad_brute", "mismatch"), ("slow", "50%")],
)
def test_verification_failures_preserve_input(tmp_path, failure, error):
    with connect(tmp_path / "db") as con:
        ws, directory = synthetic_problem(con, tmp_path)
        prepare_fake(directory)
        approve(con, ws, "2000A")
        judge = FakeJudge()
        setattr(judge, failure, True)
        report = verify(con, ws, "2000A", judge)
        assert report["status"] == "failed"
        assert error in report["error"]
        assert (directory / "hidden" / "last_input.txt").exists()
        assert con.execute("SELECT status FROM test_sets").fetchone()[0] == "approved"


def test_multi_answer_cannot_use_tokens(tmp_path):
    with connect(tmp_path / "db") as con:
        ws, directory = synthetic_problem(con, tmp_path)
        meta = read_meta(directory)
        meta["multi_answer"] = True
        write_meta(directory, meta)
        with pytest.raises(ValueError, match="custom checker"):
            approve(con, ws, "2000A")


def test_collected_limits_cannot_be_silently_overridden(tmp_path):
    with connect(tmp_path / "db") as con:
        ws, directory = synthetic_problem(con, tmp_path)
        meta = read_meta(directory)
        meta["time_limit_seconds"] = 20
        write_meta(directory, meta)
        with pytest.raises(ValueError, match="time_limit_seconds"):
            approve(con, ws, "2000A")


def test_source_refresh_invalidates_approval_without_rewriting_assets(tmp_path):
    with connect(tmp_path / "db") as con:
        ws, directory = synthetic_problem(con, tmp_path)
        approve(con, ws, "2000A")
        con.execute("UPDATE problems SET rating=1300 WHERE id='2000A'")
        with pytest.raises(ValueError, match="rating"):
            current_approval(con, directory)


class CountingJudge(FakeJudge):
    def __init__(self, interrupt_after=None):
        self.calls = 0
        self.interrupt_after = interrupt_after

    def run(self, *args, **kwargs):
        self.calls += 1
        if self.interrupt_after is not None and self.calls > self.interrupt_after:
            raise KeyboardInterrupt("synthetic interruption")
        return super().run(*args, **kwargs)


def test_verification_is_idempotent_and_force_remeasures(tmp_path):
    with connect(tmp_path / "db") as con:
        ws, directory = synthetic_problem(con, tmp_path)
        prepare_fake(directory)
        approve(con, ws, "2000A")
        first = verify(con, ws, "2000A", CountingJudge())
        again = CountingJudge()
        assert verify(con, ws, "2000A", again)["cached_return"]
        assert again.calls == 0
        measured = CountingJudge()
        report = verify(con, ws, "2000A", measured, force=True)
        assert measured.calls > 2000 and report["reused_cases"] == 0
        assert report["final_count"] == first["final_count"]


def test_interrupted_verification_resumes_completed_cases(tmp_path):
    with connect(tmp_path / "db") as con:
        ws, directory = synthetic_problem(con, tmp_path)
        prepare_fake(directory)
        approve(con, ws, "2000A")
        with pytest.raises(KeyboardInterrupt):
            verify(con, ws, "2000A", CountingJudge(interrupt_after=18))
        completed = con.execute("SELECT count(*) FROM verification_cases").fetchone()[0]
        assert completed > 1
        assert con.execute("SELECT status FROM test_sets").fetchone()[0] == "approved"
        report = verify(con, ws, "2000A", CountingJudge())
        assert report["status"] == "verified" and report["reused_cases"] == completed
        assert report["counts"]["small_random"] == 500


def test_environment_changes_and_corrupt_checkpoints_are_not_reused(tmp_path, monkeypatch):
    with connect(tmp_path / "db") as con:
        ws, directory = synthetic_problem(con, tmp_path)
        prepare_fake(directory)
        approve(con, ws, "2000A")
        with pytest.raises(KeyboardInterrupt):
            verify(con, ws, "2000A", CountingJudge(interrupt_after=18))
        con.execute("UPDATE verification_cases SET payload_json='corrupt'")
        report = verify(con, ws, "2000A", CountingJudge())
        assert report["status"] == "verified" and report["reused_cases"] == 0
        other = CountingJudge()
        other.identity = {**other.identity, "machine_fingerprint": "new"}
        report = verify(con, ws, "2000A", other)
        assert report["status"] == "verified" and report["reused_cases"] == 0
        original_read = Path.read_bytes

        def changed_checker(path):
            data = original_read(path)
            return data + b"# implementation changed" if path.name == "checkers.py" else data

        monkeypatch.setattr(Path, "read_bytes", changed_checker)
        report = verify(con, ws, "2000A", other)
        assert report["status"] == "verified" and report["reused_cases"] == 0
