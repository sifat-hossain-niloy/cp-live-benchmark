"""Project paths and validated public configuration."""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Workspace:
    root: Path

    @property
    def data(self) -> Path:
        return self.root / "data"

    @property
    def problems(self) -> Path:
        return self.root / "problems"

    @property
    def db(self) -> Path:
        return self.data / "cflive.sqlite3"

    def initialize(self) -> None:
        for path in (self.data, self.problems, self.data / "html", self.data / "statements"):
            path.mkdir(parents=True, exist_ok=True)
