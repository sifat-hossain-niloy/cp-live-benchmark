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
