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
