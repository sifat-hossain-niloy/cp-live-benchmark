"""Fresh-container Docker judging with immutable toolchain identities."""

import base64
import hashlib
import json
import os
import platform
import subprocess
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cflive.checkers import check


@dataclass
class Execution:
    verdict: str
    stdout: str = ""
    stderr: str = ""
    cpu_ms: float = 0
    wall_ms: float = 0
    memory_kb: int = 0
    artifact: str | None = None


@dataclass
class Judgment:
    verdict: str
    failing_test: str | None = None
    failing_category: str | None = None
    cpu_ms: float = 0
    wall_ms: float = 0
    memory_kb: int = 0
    message: str = ""


@dataclass
class Program:
    path: Path
    language: str


def _docker(args: list[str], *, timeout: float = 60) -> subprocess.CompletedProcess:
    result = subprocess.run(["docker", *args], capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError(f"Docker infrastructure failure: {result.stderr[-4000:]}")
    return result


class DockerJudge:
    def __init__(
        self,
        image: str = "cflive-judge:0.1",
        *,
        factor: float = 1.0,
        output_limit: int = 64 * 1024 * 1024,
        artifact_dir: Path | None = None,
    ) -> None:
        if not 0 < factor <= 100:
            raise ValueError("Calibration factor must be in (0,100]")
        info = json.loads(_docker(["image", "inspect", image]).stdout)[0]
        self.image = info["Id"]  # Never resolve a mutable tag again during the run.
        self.identity = {
            "image_id": self.image,
            "repo_digests": info.get("RepoDigests", []),
            "architecture": info["Architecture"],
            "os": info["Os"],
        }
        machine = _docker(
            ["info", "--format", "{{.ID}}/{{.NCPU}}/{{.MemTotal}}/{{.KernelVersion}}"]
        )
        self.identity["machine_fingerprint"] = hashlib.sha256(
            (platform.node() + machine.stdout.strip()).encode()
        ).hexdigest()
        self.factor, self.output_limit = factor, output_limit
        self.artifact_dir = artifact_dir or Path("artifacts/compiled")
        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        versions = _docker(
            [
                "run",
                "--rm",
                "--network",
                "none",
                "--read-only",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges",
                "--entrypoint",
                "sh",
                self.image,
                "-c",
                "g++ --version; python3 --version",
            ]
        ).stdout
        self.compiler_versions = versions.strip()

    def _execute(
        self,
        command: list[str],
        mounts: dict[Path, str],
        *,
        cpu: float,
        memory_mb: int,
        input_path: str = "/dev/null",
        compile_step: bool = False,
    ) -> Execution:
        name = "cflive-" + uuid.uuid4().hex
        wall = 30.0 if compile_step else max(3.0, cpu * 3 + 1)
        args = [
            "run",
            "--name",
            name,
            "--network",
            "none",
            "--read-only",
            "--user",
            "65534:65534",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--memory",
            f"{memory_mb}m",
            "--memory-swap",
            f"{memory_mb}m",
            "--pids-limit",
            "64",
            "--cpus",
            "1",
            "--ulimit",
            "core=0",
            "--tmpfs",
            "/work:rw,nosuid,nodev,exec,size=192m,mode=1777",
        ]
        for source, target in mounts.items():
            resolved = source.resolve()
            if "," in str(resolved):
                raise ValueError("Docker mount paths cannot contain commas")
            args += ["--mount", f"type=bind,source={resolved},target={target},readonly"]
        args += [
            self.image,
            "--cpu",
            str(cpu),
            "--wall",
            str(wall),
            "--output-limit",
            str(self.output_limit),
            "--input",
            input_path,
        ]
        if compile_step:
            args.append("--compile")
        args += ["--", *command]
        try:
            result = subprocess.run(
                ["docker", *args], capture_output=True, text=True, timeout=wall + 20
            )
            inspect = json.loads(_docker(["inspect", name]).stdout)[0]
            if inspect["State"].get("OOMKilled"):
                return Execution("MLE")
            if result.returncode:
                # Infrastructure failures must never silently become contestant verdicts.
                raise RuntimeError(f"Judge supervisor failed: {result.stderr[-2000:]}")
            payload = json.loads(result.stdout)
            return Execution(
                **{k: payload[k] for k in Execution.__dataclass_fields__ if k in payload}
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError("Docker supervisor did not terminate within its wall-clock deadline")
        finally:
            subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=30)

    def compile(self, code: str, language: str = "cpp17") -> tuple[Program | None, Execution]:
        key = hashlib.sha256((self.image + language + code).encode()).hexdigest()
        path = self.artifact_dir / (key + (".py" if language == "python3" else ".bin"))
        if language == "python3":
            if not path.exists():
                path.write_text(code)
                path.chmod(0o444)
            # Syntax errors are CE; py_compile writes only to the sandbox tmpfs.
            result = self._execute(
                ["python3", "-c", "import ast; ast.parse(open('/artifact/main.py').read())"],
                {path: "/artifact/main.py"},
                cpu=30,
                memory_mb=512,
                compile_step=True,
            )
            return (
                Program(path, language) if result.verdict == "OK" else None,
                result if result.verdict == "OK" else Execution("CE", stderr=result.stderr),
            )
        if language != "cpp17":
            raise ValueError("Supported languages: cpp17, python3")
        if path.exists():
            return Program(path, language), Execution("OK")
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "main.cpp"
            source.write_text(code)
            source.chmod(0o444)
            result = self._execute(
                ["g++", "-std=c++17", "-O2", "-pipe", "/artifact/main.cpp", "-o", "/work/program"],
                {source: "/artifact/main.cpp"},
                cpu=30,
                memory_mb=1024,
                compile_step=True,
            )
        if result.verdict != "OK" or not result.artifact:
            return None, Execution("CE", stderr=result.stderr)
        temporary = path.with_suffix("." + uuid.uuid4().hex + ".tmp")
        temporary.write_bytes(base64.b64decode(result.artifact, validate=True))
        temporary.chmod(0o555)
        os.replace(temporary, path)
        return Program(path, language), result

    def run(
        self,
        program: Program,
        input_text: str,
        *,
        time_limit: float,
        memory_mb: int,
        extra_files: dict[Path, str] | None = None,
        arguments: list[str] | None = None,
    ) -> Execution:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "input"
            source.write_text(input_text)
            source.chmod(0o444)
            target = "/artifact/main.py" if program.language == "python3" else "/artifact/program"
            command = ["python3", "-s", "-P", target] if program.language == "python3" else [target]
            return self._execute(
                command + (arguments or []),
                {program.path: target, source: "/input/test", **(extra_files or {})},
                cpu=time_limit * self.factor,
                memory_mb=memory_mb,
                input_path="/input/test",
            )

    def custom_check(
        self, checker: Path, input_text: str, expected: str, actual: str
    ) -> tuple[bool, str]:
        with tempfile.TemporaryDirectory() as directory:
            answer, output = Path(directory) / "answer", Path(directory) / "output"
            answer.write_text(expected)
            output.write_text(actual)
            for path in (answer, output):
                path.chmod(0o444)
            result = self.run(
                Program(checker, "python3"),
                input_text,
                time_limit=5,
                memory_mb=256,
                extra_files={answer: "/input/answer", output: "/input/output"},
                arguments=["/input/test", "/input/answer", "/input/output"],
            )
            if result.verdict not in ("OK", "RE"):
                raise RuntimeError(f"Custom checker failed: {result.verdict}: {result.stderr}")
            # The custom checker protocol is JSON, so exceptions are never scored as WA.
            try:
                report = json.loads(result.stdout)
                if result.verdict != "OK" or type(report["accepted"]) is not bool:
                    raise ValueError("Invalid checker report")
                return report["accepted"], report.get("message", "")
            except (ValueError, KeyError, TypeError) as exc:
                raise RuntimeError(f"Custom checker protocol error: {result.stderr}") from exc

    def judge(
        self,
        code: str | None,
        tests: list[dict[str, Any]],
        *,
        time_limit: float,
        memory_mb: int,
        checker: str = "tokens",
        language: str = "cpp17",
        custom_path: Path | None = None,
    ) -> Judgment:
        if not code:
            return Judgment("NO_CODE")
        program, compilation = self.compile(code, language)
        if not program:
            return Judgment("CE", message=compilation.stderr)
        judgment = Judgment("AC")
        for test in tests:
            result = self.run(program, test["input"], time_limit=time_limit, memory_mb=memory_mb)
            judgment.cpu_ms = max(judgment.cpu_ms, result.cpu_ms)
            judgment.wall_ms = max(judgment.wall_ms, result.wall_ms)
            judgment.memory_kb = max(judgment.memory_kb, result.memory_kb)
            verdict = result.verdict
            if verdict == "OK":
                compared = check(
                    checker,
                    test["input"],
                    test["output"],
                    result.stdout,
                    custom_path=custom_path,
                    sandbox=self,
                )
                verdict = "AC" if compared.accepted else "WA"
            if verdict != "AC":
                judgment.verdict = verdict
                judgment.failing_test = test["id"]
                judgment.failing_category = test["category"]
                judgment.message = result.stderr
                break
        return judgment


def calibration(
    judge: DockerJudge, baselines: list[tuple[Program, str, float]], machine_id: str
) -> dict[str, Any]:
    """Median local CPU / supplied CF reference CPU; no invented calibration baseline."""
    from statistics import median

    ratios = []
    observations = []
    for program, input_text, cf_cpu_ms in baselines:
        if cf_cpu_ms <= 0:
            raise ValueError("Calibration requires a positive measured CF CPU baseline")
        measured = [judge.run(program, input_text, time_limit=30, memory_mb=1024) for _ in range(3)]
        if any(r.verdict != "OK" for r in measured):
            raise ValueError("Calibration reference failed")
        local_ms = median(r.cpu_ms for r in measured)
        ratios.append(local_ms / cf_cpu_ms)
        observations.append(
            {
                "cf_cpu_ms": cf_cpu_ms,
                "local_cpu_ms": local_ms,
                "source_hash": hashlib.sha256(program.path.read_bytes()).hexdigest(),
                "input_hash": hashlib.sha256(input_text.encode()).hexdigest(),
            }
        )
    if not ratios:
        raise ValueError("At least one approved measured reference baseline is required")
    return {
        "factor": median(ratios),
        "machine_id": machine_id,
        "judge": judge.identity,
        "compiler_versions": judge.compiler_versions,
        "observations": observations,
    }
