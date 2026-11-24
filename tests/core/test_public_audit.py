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


WORDS = " ".join(["ceramics"] * 200)
GOOD = (
    '<html lang="en"><head><title>Example Shop – handmade ceramics for your home</title>'
    '<meta name="viewport" content="width=device-width, initial-scale=1">'
    '<meta name="description" content="Browse handmade ceramic mugs, bowls and vases made in small '
    'batches and shipped worldwide with care.">'
    '<meta property="og:title" content="Example Shop"><meta property="og:description" content="d">'
    '<meta property="og:image" content="https://example.com/i.png">'
    '<meta name="twitter:card" content="summary">'
    '<script type="application/ld+json">{"@context":"https://schema.org","@graph":'
    '[{"@type":"Organization","name":"Example"},{"@type":["WebSite"]}]}</script>'
    '<link rel="canonical" href="https://example.com/"></head>'
    "<body><h1>Handmade ceramics</h1><h2>Shop</h2><a href='/about'>About</a>"
    f"<p>{WORDS}</p><script>var ignored = 'x y z';</script></body></html>"
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


def test_apex_redirecting_to_www_audits_the_www_host() -> None:
    report = run_public_audit(crawler({
        "https://example.com/robots.txt": HttpFetchResponse(
            301, {"location": "https://www.example.com/robots.txt"}, b""),
        "https://example.com/": HttpFetchResponse(301, {"location": "https://www.example.com/"}, b""),
        "https://www.example.com/robots.txt": HttpFetchResponse(404, {}, b""),
        "https://www.example.com/": html(GOOD),
    }), "example.com")
    assert report.host == "www.example.com"
    assert report.notice and "redirects to www.example.com" in report.notice


def test_autopilot_marks_fixable_findings_only() -> None:
    report = run_public_audit(crawler({
        "https://example.com/robots.txt": HttpFetchResponse(404, {}, b""),
        "https://example.com/": html('<html><head></head><body><img src="a.png"></body></html>'),
    }), "example.com")
    kinds = {f.id: f.autopilot for f in report.findings}
    assert kinds["missing_title"] == "propose"
    assert kinds["images_missing_alt_text"] == "manual"


def test_clean_page_has_no_advanced_findings() -> None:
    report = run_public_audit(crawler({
        "https://example.com/robots.txt": HttpFetchResponse(404, {}, b""),
        "https://example.com/": html(GOOD),
        "https://example.com/llms.txt": HttpFetchResponse(200, {}, b"# Example"),
    }), "example.com")
    assert report.findings == ()
    assert report.score == 100
    assert all(c.passed for c in report.checks)


def test_mobile_social_schema_and_thin_content_are_reported() -> None:
    report = run_public_audit(crawler({
        "https://example.com/robots.txt": HttpFetchResponse(404, {}, b""),
        "https://example.com/": html(
            "<html><head><title>A decent title for a thin page</title>"
            '<meta name="description" content="' + "d" * 90 + '"></head>'
            "<body><h1>Hi</h1><h2>x</h2><a href='/a'>a</a><p>Only a few words.</p></body></html>"),
    }), "example.com")
    ids = {f.id: f for f in report.findings}
    assert ids["missing_viewport"].severity == "medium"
    assert {"missing_lang", "missing_social_tags", "no_structured_data", "thin_content"} <= set(ids)
    assert "og:image" in ids["missing_social_tags"].found
    assert ids["no_structured_data"].autopilot == "manual"


def test_ai_crawlers_blocked_in_robots_are_reported_but_llms_txt_is_unscored() -> None:
    report = run_public_audit(crawler({
        "https://example.com/robots.txt": HttpFetchResponse(
            200, {"content-type": "text/plain"},
            b"User-agent: GPTBot\nDisallow: /\n\nUser-agent: ClaudeBot\nDisallow: /\n"),
        "https://example.com/": html(GOOD),
    }), "example.com")
    finding = next(f for f in report.findings if f.id == "ai_crawlers_blocked")
    assert "GPTBot" in finding.found and "ClaudeBot" in finding.found
    assert "PerplexityBot" not in finding.found
    assert report.score == 97
    llms = next(c for c in report.checks if c.label.startswith("llms.txt"))
    assert llms.passed is False


def test_duplicate_titles_across_pages_are_flagged_and_fixable() -> None:
    same = (
        '<html lang="en"><head><title>Same title for every page here</title>'
        '<meta name="viewport" content="width=device-width"></head><body><h1>x</h1></body></html>'
    )
    home = same.replace("</body>", "<a href='/b'>b</a></body>")
    report = run_public_audit(crawler({
        "https://example.com/robots.txt": HttpFetchResponse(404, {}, b""),
        "https://example.com/": html(home),
        "https://example.com/b": html(same),
    }), "example.com")
    dup = next(f for f in report.findings if f.id == "duplicate_titles")
    assert dup.severity == "medium" and dup.autopilot == "propose"
    assert "https://example.com/b" in dup.found
