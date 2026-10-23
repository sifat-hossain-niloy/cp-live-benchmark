"""Resumable pipeline commands. Run with --root to select a private workspace."""

import json
from datetime import date
from pathlib import Path

import typer

from cflive.collect import CodeforcesAPI, collect, collection_summary
from cflive.config import Workspace
from cflive.db import connect
from cflive.statements import scrape

app = typer.Typer(no_args_is_help=True, pretty_exceptions_show_locals=False)
workspace = Workspace(Path.cwd())


@app.callback()
def main(root: Path = typer.Option(Path.cwd(), help="Project/private workspace root")) -> None:
    global workspace
    workspace = Workspace(root.resolve())
    workspace.initialize()


def emit(value: object) -> None:
    typer.echo(json.dumps(value, indent=2, ensure_ascii=False))


@app.command("collect")
def collect_command(since: str = typer.Option(..., help="Inclusive UTC date YYYY-MM-DD")) -> None:
    """Collect finished, rated, eligible Codeforces problems."""
    with connect(workspace.db) as con:
        emit(collect(con, CodeforcesAPI(), date.fromisoformat(since)))


@app.command("inventory")
def inventory_command() -> None:
    """Count candidates by division and 100-point rating band."""
    with connect(workspace.db) as con:
        emit(collection_summary(con))


@app.command("scrape")
def scrape_command(
    limit: int = typer.Option(60, min=1),
    browser: bool = False,
    problems: list[str] = typer.Option(None),
) -> None:
    """Cache and parse private statements; reruns reuse cached pages."""
    with connect(workspace.db) as con:
        emit(scrape(con, workspace, limit=limit, browser=browser, problem_ids=problems))


@app.command("judge-build")
def judge_build(image: str = "cflive-judge:0.1") -> None:
    """Build the pinned local judge image."""
    import subprocess

    subprocess.run(["docker", "build", "-t", image, str(workspace.root / "judge")], check=True)


@app.command("judge-info")
def judge_info(image: str = "cflive-judge:0.1") -> None:
    """Inspect immutable image identity and compiler versions."""
    from cflive.judge import DockerJudge

    judge = DockerJudge(image, artifact_dir=workspace.root / "artifacts" / "compiled")
    emit({**judge.identity, "compiler_versions": judge.compiler_versions})


@app.command("calibrate")
def calibrate_command(baselines: Path, machine_id: str, image: str = "cflive-judge:0.1") -> None:
    """Compute a CPU calibration factor from supplied, measured reference baselines."""
    from cflive.judge import DockerJudge, calibration

    judge = DockerJudge(image, artifact_dir=workspace.root / "artifacts" / "compiled")
    manifest = json.loads(baselines.read_text())
    entries = []
    for item in manifest:
        if not item.get("evidence_url"):
            raise typer.BadParameter("Each measured baseline needs an evidence_url")
        program, result = judge.compile(
            Path(item["reference_path"]).read_text(), item.get("language", "cpp17")
        )
        if not program:
            raise typer.BadParameter(f"Baseline compilation failed: {result.stderr}")
        entries.append((program, Path(item["input_path"]).read_text(), item["cf_cpu_ms"]))
    report = calibration(judge, entries, machine_id)
    report["baseline_manifest"] = manifest
    destination = workspace.data / "calibration.json"
    destination.write_text(json.dumps(report, indent=2))
    emit(report)


@app.command("scaffold")
def scaffold_command(problem_id: str) -> None:
    """Create private draft assets without overwriting existing work."""
    from cflive.workflow import scaffold

    with connect(workspace.db) as con:
        emit({"directory": str(scaffold(con, workspace, problem_id)), "status": "draft"})


@app.command("attest-reference")
def attest_command(
    problem_id: str, submission_id: int, handle: str, reviewer: str = typer.Option(None)
) -> None:
    """Attest source equality and verify the referenced submission's Accepted verdict."""
    from cflive.workflow import attest_reference

    with connect(workspace.db) as con:
        emit(
            attest_reference(
                con,
                workspace,
                problem_id,
                submission_id=submission_id,
                handle=handle,
                api=CodeforcesAPI(),
                reviewer=reviewer,
            )
        )


@app.command("approve")
def approve_command(problem_id: str, reviewer: str = typer.Option(None)) -> None:
    """Record your manual review of exact problem assets. This does not verify them."""
    from cflive.workflow import approve

    with connect(workspace.db) as con:
        emit({"artifact_hash": approve(con, workspace, problem_id, reviewer), "status": "approved"})


@app.command("verify")
def verify_command(problem_id: str, image: str = "cflive-judge:0.1") -> None:
    """Run validators, differential tests, samples, and max-size performance checks."""
    from cflive.judge import DockerJudge
    from cflive.workflow import verify

    factor = 1.0
    path = workspace.data / "calibration.json"
    judge = DockerJudge(image, artifact_dir=workspace.root / "artifacts" / "compiled")
    if path.exists():
        calibration = json.loads(path.read_text())
        if calibration["judge"] != judge.identity:
            raise typer.BadParameter("Calibration is for a different judge image/platform")
        factor = calibration["factor"]
    judge.factor = factor
    with connect(workspace.db) as con:
        report = verify(con, workspace, problem_id, judge)
        emit(report)
    if report["status"] != "verified":
        raise typer.Exit(1)


@app.command("models")
def models_command(config: Path = Path("models.yaml")) -> None:
    """Validate metadata without making model calls."""
    from cflive.models import load_models

    results = {}
    for name, model in load_models(config).items():
        try:
            model.require_evaluable()
            results[name] = {"ready": True, **model.snapshot()}
        except ValueError as exc:
            results[name] = {"ready": False, "reason": str(exc)}
    emit(results)


@app.command("eval")
def eval_command(
    model: str = typer.Option(...),
    config: Path = Path("models.yaml"),
    problems: list[str] = typer.Option(None),
    samples: int = typer.Option(4, min=1),
    budget: float = typer.Option(5.0, min=0, help="Maximum run cost in USD"),
    workers: int = typer.Option(2, min=1, max=32),
    image: str = "cflive-judge:0.1",
    resume: str = typer.Option(None),
) -> None:
    """Evaluate only verified, post-cutoff problems using a sourced model configuration."""
    import asyncio

    from cflive.evaluate import evaluate
    from cflive.judge import DockerJudge
    from cflive.models import load_models
    from cflive.providers import HTTPAdapter

    models = load_models(config)
    if model not in models:
        raise typer.BadParameter(f"Unknown model: {model}")
    selected = models[model]
    selected.require_evaluable()  # Refuse missing evidence before Docker or any API calls.
    if selected.provider == "fake":
        raise typer.BadParameter("Fake providers cannot run from the production CLI")
    calibration_path = workspace.data / "calibration.json"
    if not calibration_path.exists():
        raise typer.BadParameter("Run calibrate with measured reference baselines first")
    calibration = json.loads(calibration_path.read_text())
    judge = DockerJudge(
        image, factor=calibration["factor"], artifact_dir=workspace.root / "artifacts" / "compiled"
    )

    async def run():
        adapter = HTTPAdapter(selected)
        try:
            with connect(workspace.db) as con:
                return await evaluate(
                    con,
                    workspace,
                    name=model,
                    config=selected,
                    adapter=adapter,
                    judge=judge,
                    template=(workspace.root / "prompts" / "single-shot.txt").read_text(),
                    budget_usd=budget,
                    samples=samples,
                    problem_ids=problems or None,
                    judge_workers=workers,
                    resume=resume,
                )
        finally:
            await adapter.close()

    report = asyncio.run(run())
    emit(report)
    if report["status"] != "complete":
        raise typer.Exit(1)


@app.command("reconcile-generation")
def reconcile_command(
    generation_id: int,
    note: str = typer.Option(...),
    response: Path = typer.Option(None),
    confirmed_not_billed: bool = False,
) -> None:
    """Recover an uncertain response or release its reservation after checking billing."""
    from cflive.evaluate import reconcile_generation

    with connect(workspace.db) as con:
        emit(
            reconcile_generation(
                con,
                workspace,
                generation_id,
                note=note,
                response_json=json.loads(response.read_text()) if response else None,
                confirmed_not_billed=confirmed_not_billed,
            )
        )


@app.command("score")
def score_command(
    common: bool = False,
    since: str = typer.Option(None),
    rating_band: int = typer.Option(None),
    tag: str = typer.Option(None),
    division: str = typer.Option(None),
) -> None:
    """Score complete, verified sample groups with 1000 problem-bootstrap resamples."""
    from cflive.export import public_dataset
    from cflive.scoring import score_data

    with connect(workspace.db) as con:
        data = public_dataset(con, workspace)
        emit(
            score_data(
                data,
                common=common,
                since=since,
                rating_band=rating_band,
                tag=tag,
                division=division,
            )
        )


@app.command("build-site")
def build_site_command(export_only: bool = False, save_snapshot: bool = False) -> None:
    """Allowlist public metadata and results, then build the static React app."""
    import subprocess

    from cflive.export import export_dataset

    destination = workspace.root / "site" / "public" / "data.json"
    with connect(workspace.db) as con:
        data = export_dataset(con, workspace, destination)
    if save_snapshot:
        snapshot = workspace.root / "site" / "snapshots" / "latest.json"
        snapshot.parent.mkdir(parents=True, exist_ok=True)
        snapshot.write_text(destination.read_text())
    if not export_only:
        subprocess.run(["npm", "run", "build"], cwd=workspace.root / "site", check=True)
    emit(
        {
            "export": str(destination),
            "status": data["status"],
            "inventory": data["inventory"],
            "built": not export_only,
        }
    )
