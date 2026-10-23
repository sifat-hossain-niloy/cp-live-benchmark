"""Small HTTP adapters based on official provider schemas; never invoke tools or search."""

import asyncio
import os
import time
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import quote

import httpx

from cflive.models import ModelConfig


@dataclass
class Response:
    text: str
    input_tokens: int
    output_tokens: int
    reasoning_tokens: int | None
    latency_ms: float
    raw: dict[str, Any]
    reported_cost: float | None = None


class Adapter(Protocol):
    async def count_input(self, prompt: str) -> int: ...
    async def generate(self, prompt: str) -> Response: ...


class RejectedRequest(RuntimeError):
    """Provider explicitly rejected the request before generation (safe to release budget)."""


class UncertainRequest(RuntimeError):
    """A request might have been billed; never automatically resend it."""


class HTTPAdapter:
    def __init__(
        self,
        config: ModelConfig,
        client: httpx.AsyncClient | None = None,
        api_key: str | None = None,
    ) -> None:
        self.config = config
        variable = {
            "openai": "OPENAI_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY",
            "google": "GOOGLE_API_KEY",
            "openrouter": "OPENROUTER_API_KEY",
        }[config.provider]
        self.key = api_key or os.environ.get(variable)
        if not self.key:
            raise ValueError(f"Set {variable}; no API key is stored in configuration or logs")
        self.client = client or httpx.AsyncClient(timeout=config.timeout_seconds)

    async def close(self) -> None:
        await self.client.aclose()

    async def _post(self, url: str, body: dict[str, Any], *, preflight: bool = False) -> dict:
        provider = self.config.provider
        headers = (
            {"x-api-key": self.key, "anthropic-version": self.config.anthropic_version}
            if provider == "anthropic"
            else {"x-goog-api-key": self.key}
            if provider == "google"
            else {"Authorization": f"Bearer {self.key}"}
        )
        for attempt in range(6):
            try:
                result = await self.client.post(url, json=body, headers=headers)
            except httpx.TransportError as exc:
                raise UncertainRequest(
                    "Provider transport failed; response may have been billed"
                ) from exc
            if result.status_code == 429:
                if attempt == 5:
                    raise RejectedRequest("Provider rate limit persisted after six attempts")
                try:
                    delay = float(result.headers.get("Retry-After", 2**attempt))
                except ValueError:
                    delay = 2**attempt
                await asyncio.sleep(min(60, max(1, delay)))
                continue
            if result.status_code >= 500 or result.status_code in {408, 409}:
                if preflight:
                    raise RejectedRequest(f"Token preflight failed: HTTP {result.status_code}")
                raise UncertainRequest(f"Provider HTTP {result.status_code}; billing uncertain")
            if result.is_error:
                # Never print request headers, prompts, credentials, or provider echo bodies.
                raise RejectedRequest(f"Provider rejected request: HTTP {result.status_code}")
            try:
                payload = result.json()
            except ValueError as exc:
                raise UncertainRequest("Provider response was not valid JSON") from exc
            if "error" in payload:
                raise UncertainRequest("Provider returned an error envelope; billing uncertain")
            return payload
        raise AssertionError("unreachable")

    async def count_input(self, prompt: str) -> int:
        c = self.config
        if c.provider == "openai":
            raw = await self._post(
                "https://api.openai.com/v1/responses/input_tokens",
                {"model": c.model_id, "input": prompt},
                preflight=True,
            )
            return int(raw["input_tokens"])
        if c.provider == "anthropic":
            raw = await self._post(
                "https://api.anthropic.com/v1/messages/count_tokens",
                {
                    "model": c.model_id,
                    "messages": [{"role": "user", "content": prompt}],
                    **({"thinking": c.sampling["thinking"]} if "thinking" in c.sampling else {}),
                },
                preflight=True,
            )
            return int(raw["input_tokens"])
        if c.provider == "google":
            model = quote((c.model_id or "").removeprefix("models/"), safe="")
            raw = await self._post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:countTokens",
                {"contents": [{"role": "user", "parts": [{"text": prompt}]}]},
                preflight=True,
            )
            return int(raw["totalTokens"])
        ceiling = c.input_reservation_tokens
        if ceiling is None or ceiling < len(prompt.encode()) + 4096:
            raise RejectedRequest(
                "OpenRouter input reservation must exceed UTF-8 prompt bytes + 4096"
            )
        return ceiling

    async def generate(self, prompt: str) -> Response:
        c, start = self.config, time.monotonic()
        if c.provider == "openai":
            raw = await self._post(
                "https://api.openai.com/v1/responses",
                {
                    "model": c.model_id,
                    "input": prompt,
                    "max_output_tokens": c.max_output_tokens,
                    "store": False,
                    **c.sampling,
                },
            )
        elif c.provider == "anthropic":
            raw = await self._post(
                "https://api.anthropic.com/v1/messages",
                {
                    "model": c.model_id,
                    "max_tokens": c.max_output_tokens,
                    "messages": [{"role": "user", "content": prompt}],
                    **c.sampling,
                },
            )
        elif c.provider == "google":
            model = quote((c.model_id or "").removeprefix("models/"), safe="")
            raw = await self._post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                {
                    "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                    "generationConfig": {"maxOutputTokens": c.max_output_tokens, **c.sampling},
                },
            )
        else:
            raw = await self._post(
                "https://openrouter.ai/api/v1/chat/completions",
                {
                    "model": c.model_id,
                    "max_tokens": c.max_output_tokens,
                    "messages": [{"role": "user", "content": prompt}],
                    **c.sampling,
                },
            )
        try:
            return parse_response(c.provider, raw, (time.monotonic() - start) * 1000)
        except (KeyError, TypeError, ValueError) as exc:
            # Preserve the actual paid response for manual recovery; never generate again.
            failure = UncertainRequest(
                "Provider response schema/usage missing; manual recovery required"
            )
            failure.raw = raw
            raise failure from exc


def parse_response(provider: str, raw: dict[str, Any], latency: float) -> Response:
    """Reasoning is already included in OpenAI/Anthropic output; Google reports it separately."""
    if provider == "openai":
        text = "\n".join(
            part["text"]
            for item in raw.get("output", [])
            if item.get("type") == "message"
            for part in item.get("content", [])
            if part.get("type") == "output_text"
        )
        usage = raw["usage"]
        return Response(
            text,
            usage["input_tokens"],
            usage["output_tokens"],
            usage.get("output_tokens_details", {}).get("reasoning_tokens"),
            latency,
            raw,
        )
    if provider == "anthropic":
        text = "\n".join(
            part["text"] for part in raw.get("content", []) if part.get("type") == "text"
        )
        u = raw["usage"]
        inputs = (
            u["input_tokens"]
            + u.get("cache_read_input_tokens", 0)
            + u.get("cache_creation_input_tokens", 0)
        )
        return Response(text, inputs, u["output_tokens"], None, latency, raw)
    if provider == "google":
        text = "\n".join(
            part.get("text", "")
            for candidate in raw.get("candidates", [])
            for part in candidate.get("content", {}).get("parts", [])
            if not part.get("thought")
        )
        u = raw["usageMetadata"]
        reasoning = u.get("thoughtsTokenCount", 0)
        return Response(
            text,
            u["promptTokenCount"],
            u.get("candidatesTokenCount", 0) + reasoning,
            reasoning,
            latency,
            raw,
        )
    usage = raw["usage"]
    return Response(
        raw["choices"][0]["message"].get("content") or "",
        usage["prompt_tokens"],
        usage["completion_tokens"],
        usage.get("completion_tokens_details", {}).get("reasoning_tokens"),
        latency,
        raw,
        usage.get("cost"),
    )


class FakeAdapter:
    """Deterministic offline adapter, restricted to test/demo runs and never public scores."""

    def __init__(self, responses: list[str] | None = None) -> None:
        self.responses = responses or ["```cpp\nint main(){}\n```"]
        self.calls = 0

    async def count_input(self, prompt: str) -> int:
        return 100

    async def generate(self, prompt: str) -> Response:
        text = self.responses[self.calls % len(self.responses)]
        self.calls += 1
        return Response(text, 100, 50, 0, 1, {"fake": True, "text": text})
