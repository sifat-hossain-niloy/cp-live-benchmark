"""Sourced model configuration. Missing scientific metadata is a hard evaluation gate."""

import hashlib
import json
from datetime import UTC, date, datetime, time
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class Prices(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    input_per_million: float = Field(ge=0)
    output_per_million: float = Field(ge=0)
    source_url: HttpUrl


class ModelConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    provider: Literal["openai", "anthropic", "google", "openrouter", "fake"]
    model_id: str | None = None
    display_name: str
    training_cutoff: date | None = None
    cutoff_source_url: HttpUrl | None = None
    release_date: date | None = None
    sampling: dict[str, Any] = Field(default_factory=dict)
    max_output_tokens: int = Field(default=8192, ge=16)
    prices: Prices | None = None
    language: Literal["cpp17", "python3"] = "cpp17"
    concurrency: int = Field(default=2, ge=1, le=32)
    timeout_seconds: float = Field(default=300, gt=0)
    # OpenRouter has no portable preflight count. This is a user-set billing reservation,
    # never a claimed context limit; use a provider-backed count for a stronger bound.
    input_reservation_tokens: int | None = Field(default=None, gt=0)
    anthropic_version: str = "2023-06-01"

    def require_evaluable(self) -> None:
        missing = [
            name
            for name in (
                "model_id",
                "training_cutoff",
                "cutoff_source_url",
                "release_date",
                "prices",
            )
            if getattr(self, name) is None
        ]
        if missing:
            raise ValueError(
                "Refusing evaluation: missing sourced model configuration: " + ", ".join(missing)
            )
        if self.provider == "openrouter" and self.input_reservation_tokens is None:
            raise ValueError(
                "OpenRouter requires an explicit input_reservation_tokens billing ceiling"
            )
        if self.release_date and self.training_cutoff and self.training_cutoff > self.release_date:
            raise ValueError("Training cutoff cannot follow model release date")
        allowed = {
            "openai": {"temperature", "top_p", "reasoning"},
            "anthropic": {"temperature", "top_p", "top_k", "thinking"},
            "google": {"temperature", "topP", "topK", "seed", "thinkingConfig"},
            "openrouter": {"temperature", "top_p", "top_k", "seed", "reasoning", "provider"},
            "fake": {"temperature", "seed"},
        }[self.provider]
        if set(self.sampling) - allowed:
            raise ValueError(f"Unsupported sampling keys: {set(self.sampling) - allowed}")

    def cutoff_timestamp(self) -> int:
        if self.training_cutoff is None:
            raise ValueError("No documented training cutoff")
        # A date alone does not identify an hour. Exclude the entire cutoff day (UTC).
        return int(datetime.combine(self.training_cutoff, time.max, UTC).timestamp())

    def snapshot(self) -> dict[str, Any]:
        return self.model_dump(mode="json")

    def hash(self) -> str:
        return hashlib.sha256(json.dumps(self.snapshot(), sort_keys=True).encode()).hexdigest()


def load_models(path: Path) -> dict[str, ModelConfig]:
    raw = yaml.safe_load(path.read_text()) or {}
    return {
        name: ModelConfig.model_validate(config) for name, config in raw.get("models", {}).items()
    }
