import base64
import asyncio
from dataclasses import dataclass
from typing import Literal, Protocol
from urllib.parse import urlsplit

import httpx
from pydantic import SecretStr

from reckon_core.crawl_security import (
    DnsAddressLookup,
    PublicDnsAddressResolver,
    resolve_public_crawl_target,
)
from reckon_core.model_settings import normalize_model_endpoint
from reckon_core.websites import InvalidWebsiteUrl


CmsProvider = Literal["wordpress"]


@dataclass(frozen=True, slots=True)
class CmsCapability:
    name: str
    read_supported: bool
    write_supported: bool
    approval_required: bool


@dataclass(frozen=True, slots=True)
class CmsDiscoveryResult:
    provider: CmsProvider
    base_url: str
    capabilities: tuple[CmsCapability, ...]
    verified: bool


class CmsAdapter(Protocol):
    binding_version: str

    async def discover(self, timeout_seconds: float) -> CmsDiscoveryResult:
        """Discover read/write capabilities without changing the CMS."""


class CmsAdapterUnavailable(RuntimeError):
    pass


class WordPressCmsAdapter:
    binding_version = "wordpress-cms-v1"

    def __init__(
        self,
        base_url: str,
        username: str,
        app_password: SecretStr,
        transport: httpx.AsyncBaseTransport | None = None,
        resolver: DnsAddressLookup | None = None,
    ) -> None:
        try:
            normalized = normalize_model_endpoint(base_url)
        except (ValueError, InvalidWebsiteUrl):
            raise ValueError("The WordPress base URL is invalid.") from None
        if not username or len(username) > 320:
            raise ValueError("The WordPress username is invalid.")
        secret = app_password.get_secret_value()
        if not secret or len(secret) > 4096 or any(char.isspace() for char in secret):
            raise ValueError("The WordPress application password is invalid.")
        self._base_url = normalized
        self._authorization = "Basic " + base64.b64encode(
            f"{username}:{secret}".encode("utf-8")
        ).decode("ascii")
        self._transport = transport
        self._resolver = resolver or PublicDnsAddressResolver(timeout_seconds=2.0)

    async def discover(self, timeout_seconds: float) -> CmsDiscoveryResult:
        if timeout_seconds <= 0:
            raise ValueError("The CMS discovery timeout must be positive.")
        try:
            parsed = urlsplit(self._base_url)
            if parsed.hostname is None:
                raise CmsAdapterUnavailable
            target = await asyncio.to_thread(
                resolve_public_crawl_target,
                parsed.hostname,
                self._resolver,
            )
            address = target.addresses[0]
            authority = f"[{address}]" if ":" in address else address
            discovery_url = f"https://{authority}{parsed.path}/wp-json/wp/v2/"
            headers = {
                "Authorization": self._authorization,
                "Accept": "application/json",
                "Host": target.host,
            }
            async with httpx.AsyncClient(
                transport=self._transport,
                trust_env=False,
                follow_redirects=False,
                timeout=httpx.Timeout(timeout_seconds),
            ) as client:
                response = await client.get(
                    discovery_url,
                    headers=headers,
                    extensions={"sni_hostname": target.host},
                )
                if response.status_code != 200:
                    raise CmsAdapterUnavailable(
                        "The WordPress capability endpoint did not return a confirmed response."
                    )
                response.headers.get("content-type", "")
        except (httpx.HTTPError, ValueError, CmsAdapterUnavailable):
            raise CmsAdapterUnavailable(
                "The WordPress capability endpoint could not be verified."
            ) from None
        return CmsDiscoveryResult(
            provider="wordpress",
            base_url=self._base_url,
            verified=True,
            capabilities=(
                CmsCapability(
                    name="posts",
                    read_supported=True,
                    write_supported=True,
                    approval_required=True,
                ),
                CmsCapability(
                    name="pages",
                    read_supported=True,
                    write_supported=True,
                    approval_required=True,
                ),
                CmsCapability(
                    name="media",
                    read_supported=True,
                    write_supported=True,
                    approval_required=True,
                ),
            ),
        )
