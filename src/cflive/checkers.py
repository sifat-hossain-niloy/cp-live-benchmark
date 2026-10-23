"""Output comparison; custom checkers validate feasibility and the optimal value."""

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class CheckerSandbox(Protocol):
    def custom_check(
        self, checker: Path, input_text: str, expected: str, actual: str
    ) -> tuple[bool, str]: ...


@dataclass
class CheckResult:
    accepted: bool
    message: str = ""


def check(
    kind: str,
    input_text: str,
    expected: str,
    actual: str,
    *,
    custom_path: Path | None = None,
    sandbox: CheckerSandbox | None = None,
) -> CheckResult:
    if kind == "exact":
        return CheckResult(expected.replace("\r\n", "\n") == actual.replace("\r\n", "\n"))
    if kind == "tokens":
        return CheckResult(expected.split() == actual.split())
    if kind.startswith("float:"):
        epsilon = float(kind.split(":", 1)[1])
        if not math.isfinite(epsilon) or epsilon <= 0:
            raise ValueError("Float checker tolerance must be positive and finite")
        a, b = expected.split(), actual.split()
        if len(a) != len(b):
            return CheckResult(False, "Token counts differ")
        for x, y in zip(a, b):
            try:
                xx, yy = float(x), float(y)
                if not (math.isfinite(xx) and math.isfinite(yy)):
                    return CheckResult(False, "Non-finite numeric output")
                if abs(xx - yy) > epsilon * max(1, abs(xx)):
                    return CheckResult(False, "Numeric tolerance exceeded")
            except ValueError:
                if x != y:
                    return CheckResult(False, "Non-numeric tokens differ")
        return CheckResult(True)
    if kind == "custom" and custom_path and sandbox:
        accepted, message = sandbox.custom_check(custom_path, input_text, expected, actual)
        return CheckResult(accepted, message)
    raise ValueError(f"Unsupported or unconfigured checker: {kind}")
