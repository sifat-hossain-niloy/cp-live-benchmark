import asyncio

import httpx
import pytest

from cflive.models import ModelConfig
from cflive.providers import HTTPAdapter, UncertainRequest, parse_response


@pytest.mark.parametrize(
    "provider,raw,text,inputs,outputs,reasoning",
    [
        (
            "openai",
            {
                "output": [
                    {"type": "message", "content": [{"type": "output_text", "text": "code"}]}
                ],
                "usage": {
                    "input_tokens": 10,
                    "output_tokens": 20,
                    "output_tokens_details": {"reasoning_tokens": 15},
                },
            },
            "code",
            10,
            20,
            15,
        ),
        (
            "anthropic",
            {
                "content": [
                    {"type": "thinking", "thinking": "private"},
                    {"type": "text", "text": "code"},
                ],
                "usage": {"input_tokens": 10, "output_tokens": 20},
            },
            "code",
            10,
            20,
            None,
        ),
        (
            "google",
            {
                "candidates": [
                    {"content": {"parts": [{"text": "private", "thought": True}, {"text": "code"}]}}
                ],
                "usageMetadata": {
                    "promptTokenCount": 10,
                    "candidatesTokenCount": 20,
                    "thoughtsTokenCount": 15,
                },
            },
            "code",
            10,
            35,
            15,
        ),
        (
            "openrouter",
            {
                "choices": [{"message": {"content": "code"}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 20, "cost": 0.1},
            },
            "code",
            10,
            20,
            None,
        ),
    ],
)
def test_provider_usage(provider, raw, text, inputs, outputs, reasoning):
    result = parse_response(provider, raw, 12)
    assert (result.text, result.input_tokens, result.output_tokens, result.reasoning_tokens) == (
        text,
        inputs,
        outputs,
        reasoning,
    )


def test_uncertain_transport_never_retried():
    calls = []

    def handle(request):
        calls.append(request)
        raise httpx.ReadTimeout("uncertain")

    adapter = HTTPAdapter(
        ModelConfig(provider="openai", display_name="test", model_id="synthetic"),
        httpx.AsyncClient(transport=httpx.MockTransport(handle)),
        api_key="synthetic",
    )
    with pytest.raises(UncertainRequest):
        asyncio.run(adapter.generate("test"))
    assert len(calls) == 1


def test_preflight_request_shape_and_no_tools():
    seen = []

    def handle(request):
        import json

        seen.append((request.url.path, json.loads(request.content)))
        return httpx.Response(200, json={"input_tokens": 12})

    adapter = HTTPAdapter(
        ModelConfig(provider="openai", display_name="test", model_id="synthetic"),
        httpx.AsyncClient(transport=httpx.MockTransport(handle)),
        api_key="synthetic",
    )
    assert asyncio.run(adapter.count_input("prompt")) == 12
    assert seen == [("/v1/responses/input_tokens", {"model": "synthetic", "input": "prompt"})]
