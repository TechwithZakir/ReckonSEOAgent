import pytest

from reckon_core.crawler import CrawlUnavailable, HomepageCrawler, HttpFetchResponse
from reckon_core.public_audit import (
    PublicAuditTargetError,
    PublicAuditUnavailable,
    normalize_target,
    run_public_audit,
)


class Resolver:
    def addresses(self, host: str) -> tuple[str, ...]:
        return ("93.184.216.34",)


class RoutingTransport:
    def __init__(self, routes: dict[str, HttpFetchResponse]) -> None:
        self.routes = routes
        self.urls: list[str] = []

    def get(self, url, host, address, timeout_seconds, max_body_bytes):
        self.urls.append(url)
        return self.routes.get(url, HttpFetchResponse(404, {}, b""))


def html(body: str) -> HttpFetchResponse:
    return HttpFetchResponse(200, {"content-type": "text/html"}, body.encode())


GOOD = (
    "<html><head><title>Example Shop – handmade ceramics for your home</title>"
    '<meta name="description" content="Browse handmade ceramic mugs, bowls and vases made in small '
    'batches and shipped worldwide with care.">'
    '<link rel="canonical" href="https://example.com/"></head>'
    "<body><h1>Handmade ceramics</h1><h2>Shop</h2><a href='/about'>About</a></body></html>"
)


def crawler(routes: dict[str, HttpFetchResponse]) -> HomepageCrawler:
    return HomepageCrawler(resolver=Resolver(), transport=RoutingTransport(routes))


@pytest.mark.parametrize("raw,expected", [
    ("example.com", ("https", "example.com")),
    ("  https://Example.com/path?q=1 ", ("https", "example.com")),
    ("http://sub.example.co.uk", ("http", "sub.example.co.uk")),
    ("bücher.de", ("https", "xn--bcher-kva.de")),
])
def test_normalize_accepts_public_domains(raw: str, expected: tuple[str, str]) -> None:
    assert normalize_target(raw) == expected


@pytest.mark.parametrize("raw", [
    "", "localhost", "127.0.0.1", "http://10.0.0.1", "http://[::1]", "ftp://example.com",
    "http://user:pw@example.com", "example.com:8080", "intranet.local", "a b.com", "x" * 400,
    "javascript:alert(1)", r"http://example.com\@evil.com",
])
def test_normalize_rejects_unsafe_targets(raw: str) -> None:
    with pytest.raises(PublicAuditTargetError):
        normalize_target(raw)


def test_clean_site_scores_high() -> None:
    report = run_public_audit(crawler({
        "https://example.com/robots.txt": HttpFetchResponse(404, {}, b""),
        "https://example.com/": html(GOOD),
    }), "example.com")
    assert report.host == "example.com"
    assert report.score >= 85
    assert not [f for f in report.findings if f.severity == "high"]
    assert any(c.label == "Title tag present" and c.passed for c in report.checks)


def test_missing_basics_are_reported_with_fixes() -> None:
    report = run_public_audit(crawler({
        "https://example.com/robots.txt": HttpFetchResponse(404, {}, b""),
        "https://example.com/": html("<html><head></head><body><p>hi</p></body></html>"),
    }), "https://example.com")
    ids = {f.id for f in report.findings}
    assert {"missing_title", "missing_meta_description", "missing_h1"} <= ids
    assert report.score < 100
    assert all(f.how_to_fix and f.why_it_matters for f in report.findings)
    assert [c for c in report.checks if not c.passed]


def test_noindex_is_high_severity() -> None:
    report = run_public_audit(crawler({
        "https://example.com/robots.txt": HttpFetchResponse(404, {}, b""),
        "https://example.com/": html(
            '<html><head><title>A fine long title for testing</title>'
            '<meta name="robots" content="noindex"></head><body><h1>x</h1></body></html>'),
    }), "example.com")
    assert report.findings[0].id == "noindex_directive"
    assert report.findings[0].severity == "high"


def test_robots_disallow_is_respected_and_reported() -> None:
    with pytest.raises(PublicAuditUnavailable):
        run_public_audit(crawler({
            "https://example.com/robots.txt": HttpFetchResponse(
                200, {"content-type": "text/plain"}, b"User-agent: *\nDisallow: /\n"),
            "https://example.com/": html(GOOD),
        }), "example.com")


def test_unreachable_site_raises_unavailable() -> None:
    class Down:
        def get(self, *args, **kwargs):
            raise CrawlUnavailable("down")

    with pytest.raises(PublicAuditUnavailable):
        run_public_audit(HomepageCrawler(resolver=Resolver(), transport=Down()), "example.com")
