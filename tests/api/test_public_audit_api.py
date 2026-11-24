import asyncio

import httpx

from reckon_api.config import Settings
from reckon_api.main import create_app
from reckon_core.crawler import HomepageCrawler, HttpFetchResponse

PAGE = (
    "<html><head><title>Example Shop – handmade ceramics for your home</title></head>"
    "<body><h1>Hi</h1></body></html>"
)


class Resolver:
    def addresses(self, host: str) -> tuple[str, ...]:
        return ("93.184.216.34",)


class Transport:
    def __init__(self) -> None:
        self.calls = 0

    def get(self, url, host, address, timeout_seconds, max_body_bytes):
        self.calls += 1
        if url.endswith("/robots.txt"):
            return HttpFetchResponse(404, {}, b"")
        return HttpFetchResponse(200, {"content-type": "text/html"}, PAGE.encode())


def make_app(limit: int = 5, enabled: bool = True):
    app = create_app(Settings(
        _env_file=None, environment="test",
        public_audit_hourly_limit=limit, public_audit_enabled=enabled))
    transport = Transport()
    app.state.homepage_crawler = HomepageCrawler(resolver=Resolver(), transport=transport)
    return app, transport


def post(app, url: str) -> httpx.Response:
    async def call() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.post("/api/v1/public/audit", json={"url": url})

    return asyncio.run(call())


def test_audit_needs_no_authentication_and_is_not_cacheable() -> None:
    app, _ = make_app()
    response = post(app, "example.com")
    assert response.status_code == 200
    body = response.json()
    assert body["host"] == "example.com"
    assert 0 <= body["score"] <= 100
    assert body["findings"] and body["checks"]
    assert response.headers["cache-control"] == "no-store"


def test_private_and_malformed_targets_are_rejected_without_fetching() -> None:
    app, transport = make_app()
    for target in ("http://169.254.169.254", "localhost", "http://10.0.0.5/", "not a url"):
        assert post(app, target).status_code == 422
    assert transport.calls == 0


def test_repeat_audit_uses_cache_and_does_not_spend_the_limit() -> None:
    app, transport = make_app(limit=1)
    first = post(app, "example.com")
    calls = transport.calls
    second = post(app, "https://example.com/other")
    assert first.status_code == second.status_code == 200
    assert second.json()["cached"] is True
    assert transport.calls == calls


def test_hourly_limit_returns_429() -> None:
    app, _ = make_app(limit=1)
    assert post(app, "one.example.com").status_code == 200
    limited = post(app, "two.example.com")
    assert limited.status_code == 429
    assert limited.headers["retry-after"] == "3600"


def test_disabled_feature_returns_404() -> None:
    app, _ = make_app(enabled=False)
    assert post(app, "example.com").status_code == 404
