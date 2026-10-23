import json

from cflive.db import connect
from cflive.export import export_dataset, public_dataset
from cflive.workflow import approve, verify
from tests.helpers import synthetic_problem
from tests.test_workflow import FakeJudge, prepare_fake


def test_export_never_contains_private_artifacts(tmp_path):
    with connect(tmp_path / "db") as con:
        ws, directory = synthetic_problem(con, tmp_path)
        prepare_fake(directory)
        approve(con, ws, "2000A")
        verify(con, ws, "2000A", FakeJudge())
        destination = tmp_path / "public" / "data.json"
        data = export_dataset(con, ws, destination)
        exported = destination.read_text()
        assert data["inventory"]["verified_problems"] == 1
        assert data["models"] == data["results"] == []
        for private in [
            "Add integers",
            "reference.cpp",
            "source_sha256",
            "last_input.txt",
            str(tmp_path),
            "api_evidence",
            "raw_response",
            "statement_path",
        ]:
            assert private not in exported
        assert json.loads(exported)["problems"][0]["url"].startswith("https://codeforces.com/")
        (directory / "gen.py").write_text("changed after verification")
        assert public_dataset(con, ws)["inventory"]["verified_problems"] == 0


def test_empty_workspace_is_honest(tmp_path):
    from cflive.config import Workspace

    ws = Workspace(tmp_path)
    ws.initialize()
    with connect(ws.db) as con:
        data = public_dataset(con, ws)
        assert data["status"] == "awaiting_verified_evaluations"
        assert data["inventory"]["verified_problems"] == 0


def test_complete_groups_only_and_cached_reruns_not_duplicated(tmp_path):
    import asyncio
    from pathlib import Path

    from cflive.evaluate import evaluate
    from cflive.providers import FakeAdapter
    from tests.test_evaluate import EvalJudge, config, setup

    with connect(tmp_path / "db") as con:
        ws = setup(con, tmp_path)
        model = config()
        model.provider = "openai"  # Exercise publication with an offline fake adapter only.
        adapter = FakeAdapter()

        async def run(budget):
            return await evaluate(
                con,
                ws,
                name="synthetic-only",
                config=model,
                adapter=adapter,
                judge=EvalJudge(),
                template=Path("prompts/single-shot.txt").read_text(),
                samples=2,
                judge_workers=1,
                budget_usd=budget,
                require_calibration=False,
            )

        first = asyncio.run(run(0.0014))
        assert first["status"] == "budget_stopped" and adapter.calls == 1
        assert public_dataset(con, ws)["results"] == []
        assert asyncio.run(run(1))["status"] == "complete"
        assert asyncio.run(run(1))["status"] == "complete"
        public = public_dataset(con, ws)
        assert len(public["models"]) == 1 and len(public["results"]) == 2
        assert adapter.calls == 2
        assert "raw_response" not in json.dumps(public)


def test_fake_providers_never_appear_in_public_scores(tmp_path):
    from cflive.providers import FakeAdapter
    from tests.test_evaluate import run, setup

    with connect(tmp_path / "db") as con:
        ws = setup(con, tmp_path)
        run(con, ws, FakeAdapter(), budget_usd=1)
        public = public_dataset(con, ws)
        assert public["models"] == [] and public["results"] == []
