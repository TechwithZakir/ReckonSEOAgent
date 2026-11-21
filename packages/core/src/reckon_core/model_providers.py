import asyncio
import hashlib
from typing import Literal
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, Field, SecretStr, ValidationError

from reckon_core.crawl_security import (
    CrawlTargetError, DnsAddressLookup, DnsAddressLookupUnavailable, resolve_public_crawl_target,
)
from reckon_core.model_gateway import (
    ModelAdapterError, ModelExecutionPolicy, ModelGatewayRequest, ModelProviderResult,
)
from reckon_core.model_settings import ModelProvider, normalize_model_endpoint
from reckon_core.model_usage import ModelUsageReport, TokenCount

_MAX_RESPONSE_BYTES = 64 * 1024


class _Usage(BaseModel):
    input_tokens: TokenCount
    output_tokens: TokenCount


class _AnthropicUsage(_Usage):
    cache_creation_input_tokens: TokenCount = 0
    cache_read_input_tokens: TokenCount = 0


class _Content(BaseModel):
    type: str
    text: str | None = None


class _Output(BaseModel):
    type: str
    role: str | None = None
    content: list[_Content] = Field(default_factory=list)


class _OpenAIResponse(BaseModel):
    status: Literal["completed"]
    output: list[_Output]
    usage: _Usage


class _AnthropicResponse(BaseModel):
    type: Literal["message"]
    role: Literal["assistant"]
    stop_reason: Literal["end_turn", "stop_sequence", "max_tokens"]
    content: list[_Content]
    usage: _AnthropicUsage


class ProviderAdapter:
    def __init__(
        self, provider: ModelProvider, endpoint: str, api_key: SecretStr,
        encrypted_key: bytes, resolver: DnsAddressLookup,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._provider = provider
        self._endpoint = normalize_model_endpoint(endpoint)
        self._key = api_key
        self._resolver = resolver
        self._transport = transport
        self.binding_version = hashlib.sha256(
            provider.encode() + b"\0" + self._endpoint.encode() + b"\0" + encrypted_key
        ).hexdigest()

    def input_token_upper_bound(self, request: ModelGatewayRequest) -> int:
        return 128 + sum(
            len(value.encode("utf-8")) * 4
            for value in (request.system_prompt, *(message.content for message in request.messages))
        )

    async def complete(
        self, request: ModelGatewayRequest, policy: ModelExecutionPolicy, timeout_seconds: float,
    ) -> ModelProviderResult:
        if request.provider != self._provider or request.model != policy.model:
            raise ModelAdapterError("The provider request does not match the authorized policy.")
        if self._provider == "openai":
            path = "/responses"
            body = {
                "model": request.model, "instructions": request.system_prompt,
                "input": [{"role": message.role, "content": message.content} for message in request.messages],
                "max_output_tokens": policy.max_output_tokens, "store": False,
            }
            authorization = {"Authorization": f"Bearer {self._key.get_secret_value()}"}
        else:
            path = "/messages"
            body = {
                "model": request.model, "system": request.system_prompt,
                "messages": [{"role": message.role, "content": message.content} for message in request.messages],
                "max_tokens": policy.max_output_tokens,
            }
            authorization = {
                "x-api-key": self._key.get_secret_value(), "anthropic-version": "2023-06-01",
            }
        endpoint = urlsplit(self._endpoint)
        if endpoint.hostname is None:
            raise ModelAdapterError("The provider endpoint is invalid.")
        try:
            async with asyncio.timeout(timeout_seconds):
                target = await asyncio.to_thread(resolve_public_crawl_target, endpoint.hostname, self._resolver)
                address = target.addresses[0]
                authority = f"[{address}]" if ":" in address else address
                url = f"https://{authority}{endpoint.path}{path}"
                headers = {
                    **authorization, "Host": target.host, "Accept": "application/json",
                    "Accept-Encoding": "identity", "Content-Type": "application/json",
                }
                async with httpx.AsyncClient(
                    transport=self._transport, trust_env=False, follow_redirects=False,
                    timeout=httpx.Timeout(timeout_seconds),
                ) as client:
                    async with client.stream(
                        "POST", url, headers=headers, json=body,
                        extensions={"sni_hostname": target.host},
                    ) as response:
                        if response.status_code != 200 or response.headers.get("content-encoding", "identity").lower() != "identity":
                            raise ModelAdapterError("The provider did not return a confirmed response.")
                        data = bytearray()
                        async for chunk in response.aiter_raw():
                            if len(chunk) > _MAX_RESPONSE_BYTES - len(data):
                                raise ModelAdapterError("The provider response exceeded the size limit.")
                            data.extend(chunk)
            if self._provider == "openai":
                openai_result = _OpenAIResponse.model_validate_json(data)
                texts = [
                    block.text for item in openai_result.output if item.type == "message" and item.role == "assistant"
                    for block in item.content if block.type == "output_text" and block.text
                ]
                input_tokens = openai_result.usage.input_tokens
                output_tokens = openai_result.usage.output_tokens
            else:
                anthropic_result = _AnthropicResponse.model_validate_json(data)
                texts = [block.text for block in anthropic_result.content if block.type == "text" and block.text]
                input_tokens = (
                    anthropic_result.usage.input_tokens + anthropic_result.usage.cache_creation_input_tokens
                    + anthropic_result.usage.cache_read_input_tokens
                )
                output_tokens = anthropic_result.usage.output_tokens
            if not texts:
                raise ModelAdapterError("The provider did not return an assistant response.")
            return ModelProviderResult(
                text="\n".join(texts),
                usage=ModelUsageReport(
                    input_tokens=input_tokens, output_tokens=output_tokens,
                ),
            )
        except (CrawlTargetError, DnsAddressLookupUnavailable, httpx.HTTPError, TimeoutError, ValidationError, ValueError):
            raise ModelAdapterError("The provider response could not be verified.") from None
