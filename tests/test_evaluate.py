import asyncio
from datetime import UTC
from pathlib import Path

import pytest

from cflive.db import connect
from cflive.evaluate import evaluate, extract_code
from cflive.judge import Judgment
from cflive.models import ModelConfig
from cflive.providers import FakeAdapter, UncertainRequest
from cflive.workflow import approve, verify
from tests.helpers import synthetic_problem
from tests.test_workflow import FakeJudge, prepare_fake


@pytest.mark.parametrize(
    "text,language,code",
    [
        ("```cpp\nint main(){}\n```", "cpp17", "int main(){}\n"),
        ("text\n```c++\nint main(){}\n```\nexplanation", "cpp17", "int main(){}\n"),
        ("int main(){}", "cpp17", None),
        ("```cpp\na\n```\n```cpp\nb\n```", "cpp17", None),
        ("```python\nprint(1)\n```", "python3", "print(1)\n"),
        ("```python\nprint(1)\n```", "cpp17", None),
    ],
)
def test_code_extraction(text, language, code):
    assert extract_code(text, language) == code


def config():
    return ModelConfig(
        provider="fake",
        model_id="synthetic-only",
        display_name="Synthetic test model",
        training_cutoff="2025-01-01",
        cutoff_source_url="https://example.org/cutoff",
        release_date="2025-02-01",
        max_output_tokens=100,
        concurrency=1,
        prices={
            "input_per_million": 1,
            "output_per_million": 2,
            "source_url": "https://example.org/prices",
        },
    )


class EvalJudge(FakeJudge):
    image = "sha256:synthetic"

    def judge(self, code, tests, **kwargs):
        return Judgment("AC" if code else "NO_CODE")


def setup(con, tmp_path):
    ws, directory = synthetic_problem(con, tmp_path)
    prepare_fake(directory)
    approve(con, ws, "2000A")
    assert verify(con, ws, "2000A", EvalJudge())["status"] == "verified"
    return ws


def run(con, ws, adapter, **kwargs):
    return asyncio.run(
        evaluate(
            con,
            ws,
            name="synthetic",
            config=config(),
            adapter=adapter,
            judge=EvalJudge(),
            template=Path("prompts/single-shot.txt").read_text(),
            samples=2,
            judge_workers=1,
            require_calibration=False,
            **kwargs,
        )
    )


def test_cache_rerun_never_pays_twice(tmp_path):
    with connect(tmp_path / "db") as con:
        ws = setup(con, tmp_path)
        adapter = FakeAdapter()
        first = run(con, ws, adapter, budget_usd=1)
        second = run(con, ws, adapter, budget_usd=1)
        assert first["status"] == second["status"] == "complete"
        assert adapter.calls == 2 and second["cached"] == 2
        assert second["spent_usd"] == 0
        assert con.execute("SELECT count(*) FROM generations").fetchone()[0] == 2
        assert con.execute("SELECT count(*) FROM judgments").fetchone()[0] == 4


def test_budget_stops_before_request(tmp_path):
    with connect(tmp_path / "db") as con:
        ws = setup(con, tmp_path)
        adapter = FakeAdapter()
        report = run(con, ws, adapter, budget_usd=0.00001)
        assert report["status"] == "budget_stopped" and adapter.calls == 0
        assert report["spent_usd"] == report["reserved_usd"] == 0


def test_ambiguous_call_remains_reserved_and_cannot_replay(tmp_path):
    class Broken(FakeAdapter):
        async def generate(self, prompt):
            self.calls += 1
            raise UncertainRequest("simulated lost paid response")

    with connect(tmp_path / "db") as con:
        ws = setup(con, tmp_path)
        adapter = Broken()
        first = run(con, ws, adapter, budget_usd=1)
        assert first["status"] == "needs_attention" and first["reserved_usd"] > 0
        second = run(con, ws, adapter, budget_usd=1)
        assert second["status"] == "needs_attention" and adapter.calls == 1


def test_missing_cutoff_refused_without_calls(tmp_path):
    with connect(tmp_path / "db") as con:
        ws = setup(con, tmp_path)
        c = config()
        c.training_cutoff = None
        adapter = FakeAdapter()
        with pytest.raises(ValueError, match="training_cutoff"):
            asyncio.run(
                evaluate(
                    con,
                    ws,
                    name="missing",
                    config=c,
                    adapter=adapter,
                    judge=EvalJudge(),
                    template="",
                    budget_usd=1,
                    require_calibration=False,
                )
            )
        assert adapter.calls == 0


def test_cutoff_day_is_excluded():
    c = config()
    from datetime import datetime

    assert c.cutoff_timestamp() == int(datetime(2025, 1, 1, 23, 59, 59, tzinfo=UTC).timestamp())


def test_metadata_updates_do_not_regenerate_identical_paid_requests():
    c = config()
    request_hash, metadata_hash = c.request_hash(), c.hash()
    c.display_name = "Updated display name"
    c.concurrency = 4
    c.prices.input_per_million = 10
    assert c.hash() != metadata_hash
    assert c.request_hash() == request_hash
    c.max_output_tokens += 100
    assert c.request_hash() != request_hash
