import asyncio
import json

import httpx
import pytest
from pydantic import SecretStr

from reckon_core.model_gateway import (
    ModelAdapterError, ModelExecutionPolicy, ModelGatewayRequest, ModelMessage,
)
from reckon_core.model_providers import ProviderAdapter
from reckon_core.model_settings import ModelProvider


class FixtureResolver:
    def __init__(self, address: str = "8.8.8.8") -> None:
        self.address = address

    def addresses(self, host: str) -> tuple[str, ...]:
        return (self.address,)


@pytest.mark.parametrize("provider", ["openai", "anthropic"])
def test_provider_adapter_pins_address_and_validates_usage(provider: ModelProvider) -> None:
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if provider == "openai":
            body = {
                "status": "completed", "output": [{
                    "type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "OK"}]
                }], "usage": {"input_tokens": 10, "output_tokens": 2},
            }
        else:
            body = {
                "type": "message", "role": "assistant", "stop_reason": "end_turn",
                "content": [{"type": "text", "text": "OK"}],
                "usage": {"input_tokens": 7, "cache_read_input_tokens": 3, "output_tokens": 2},
            }
        return httpx.Response(200, stream=httpx.ByteStream(json.dumps(body).encode()))

    adapter = ProviderAdapter(
        provider, "https://proxy.example.com/v1", SecretStr("fixture-key"), b"ciphertext",
        FixtureResolver(), httpx.MockTransport(handle),
    )
    request = ModelGatewayRequest(
        provider=provider, model="fixture-model", system_prompt="Reply with OK.",
        messages=(ModelMessage(role="user", content="Test connection."),),
    )
    policy = ModelExecutionPolicy(
        provider=provider, model="fixture-model", daily_token_limit=10000,
        max_input_tokens=512, max_output_tokens=128, timeout_seconds=5.0,
    )
    result = asyncio.run(adapter.complete(request, policy, 5))
    assert result.text == "OK"
    assert (result.usage.input_tokens, result.usage.output_tokens) == (10, 2)
    outgoing = requests[0]
    assert outgoing.url.host == "8.8.8.8"
    assert outgoing.url.path == ("/v1/responses" if provider == "openai" else "/v1/messages")
    assert outgoing.headers["host"] == "proxy.example.com"
    assert outgoing.extensions["sni_hostname"] == "proxy.example.com"
    body = json.loads(outgoing.content)
    assert body["model"] == "fixture-model"
    if provider == "openai":
        assert body["store"] is False and body["max_output_tokens"] == 128
    else:
        assert body["max_tokens"] == 128 and outgoing.headers["anthropic-version"] == "2023-06-01"


@pytest.mark.parametrize("mode", ["private", "redirect", "invalid", "oversize", "compressed"])
def test_provider_adapter_rejects_unsafe_or_unverified_responses(mode: str) -> None:
    calls = 0

    def handle(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if mode == "redirect":
            return httpx.Response(302, headers={"Location": "https://127.0.0.1/"})
        if mode == "oversize":
            return httpx.Response(200, stream=httpx.ByteStream(b"x" * 65537))
        if mode == "compressed":
            return httpx.Response(200, headers={"Content-Encoding": "gzip"}, content=b"invalid")
        return httpx.Response(200, stream=httpx.ByteStream(b'{"status":"completed"}'))

    adapter = ProviderAdapter(
        "openai", "https://proxy.example.com/v1", SecretStr("fixture-secret"), b"ciphertext",
        FixtureResolver("127.0.0.1" if mode == "private" else "8.8.8.8"), httpx.MockTransport(handle),
    )
    request = ModelGatewayRequest(
        provider="openai", model="fixture-model", system_prompt="Reply with OK.",
        messages=(ModelMessage(role="user", content="Test connection."),),
    )
    policy = ModelExecutionPolicy(
        provider="openai", model="fixture-model", daily_token_limit=10000,
        max_input_tokens=512, max_output_tokens=128, timeout_seconds=5.0,
    )
    with pytest.raises(ModelAdapterError) as error:
        asyncio.run(adapter.complete(request, policy, 5))
    assert "fixture-secret" not in str(error.value)
    assert calls == (0 if mode == "private" else 1)
