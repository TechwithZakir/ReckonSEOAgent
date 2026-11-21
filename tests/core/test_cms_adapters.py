import asyncio

import httpx
from pydantic import SecretStr

from reckon_core.cms_adapters import CmsAdapterUnavailable, WordPressCmsAdapter


class PublicFixtureResolver:
    def addresses(self, host: str) -> tuple[str, ...]:
        assert host == "wordpress.example.com"
        return ("93.184.216.34",)


def test_wordpress_discovery_requires_confirmed_public_endpoint() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={"namespaces": ["wp/v2"]},
            headers={"content-type": "application/json"},
        )
    )
    adapter = WordPressCmsAdapter(
        "https://wordpress.example.com",
        "fixture",
        SecretStr("fixture-app-password"),
        transport=transport,
        resolver=PublicFixtureResolver(),
    )

    result = asyncio.run(adapter.discover(timeout_seconds=1.0))

    assert result.provider == "wordpress"
    assert result.verified is True
    assert {capability.name for capability in result.capabilities} == {
        "posts",
        "pages",
        "media",
    }
    assert all(capability.approval_required for capability in result.capabilities)


def test_wordpress_discovery_rejects_unconfirmed_provider_response() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(401, text="provider secret")
    )
    adapter = WordPressCmsAdapter(
        "https://wordpress.example.com",
        "fixture",
        SecretStr("fixture-app-password"),
        transport=transport,
        resolver=PublicFixtureResolver(),
    )

    try:
        asyncio.run(adapter.discover(timeout_seconds=1.0))
    except CmsAdapterUnavailable:
        return
    raise AssertionError("Unconfirmed CMS discovery unexpectedly succeeded.")
