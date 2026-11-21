import socket
import threading
import time

import pytest

import reckon_core.crawler as crawler_module
from reckon_core.crawler import (
    CrawlDisallowed,
    CrawlPolicyError,
    CrawlUnavailable,
    HomepageCrawler,
    HttpFetchResponse,
    SitemapEvidence,
    StdlibPinnedHttpTransport,
)


class FakeAddressResolver:
    def __init__(self, addresses: tuple[str, ...] = ("93.184.216.34",)) -> None:
        self._addresses = addresses
        self.hosts: list[str] = []

    def addresses(self, host: str) -> tuple[str, ...]:
        self.hosts.append(host)
        return self._addresses


class FakeTransport:
    def __init__(self, responses: tuple[HttpFetchResponse, ...]) -> None:
        self._responses = list(responses)
        self.requests: list[tuple[str, str, str, float, int]] = []

    def get(
        self,
        url: str,
        host: str,
        address: str,
        timeout_seconds: float,
        max_body_bytes: int,
    ) -> HttpFetchResponse:
        self.requests.append((url, host, address, timeout_seconds, max_body_bytes))
        return self._responses.pop(0)


def response(
    status_code: int,
    *,
    headers: dict[str, str] | None = None,
    body: bytes = b"",
) -> HttpFetchResponse:
    return HttpFetchResponse(
        status_code=status_code,
        headers=headers or {},
        body=body,
    )


def test_crawl_pins_request_to_public_dns_answer_and_extracts_title() -> None:
    resolver = FakeAddressResolver()
    transport = FakeTransport(
        (
            response(404),
            response(
                200,
                headers={"content-type": "text/html; charset=utf-8"},
                body=b"<html><title> Example page </title></html>",
            ),
        )
    )

    result = HomepageCrawler(resolver, transport).crawl("https", "example.com")

    assert result.final_url == "https://example.com/"
    assert result.status_code == 200
    assert result.title == "Example page"
    assert result.meta_description is None
    assert result.h1_count == 0
    assert result.robots_status_code == 404
    assert result.sitemap_urls == ()
    assert result.sitemap_declaration_count == 0
    assert result.bytes_read == len(b"<html><title> Example page </title></html>")
    assert resolver.hosts == ["example.com", "example.com"]
    assert transport.requests[0][0] == "https://example.com/robots.txt"
    assert transport.requests[1][0] == "https://example.com/"
    assert transport.requests[1][1:3] == ("example.com", "93.184.216.34")


def test_crawl_extracts_bounded_meta_description_and_h1_count() -> None:
    html = (
        '<META NAME="Description" CONTENT="  Useful &amp; concise   summary ">'
        "<h1>First</h1><H1>Second</H1>"
    ).encode()
    transport = FakeTransport(
        (
            response(404),
            response(
                200,
                headers={"content-type": "text/html; charset=utf-8"},
                body=html,
            ),
        )
    )

    result = HomepageCrawler(FakeAddressResolver(), transport).crawl(
        "https",
        "example.com",
    )

    assert result.meta_description == "Useful & concise summary"
    assert result.h1_count == 2


def test_crawl_captures_noindex_signals_and_redacts_canonical_url() -> None:
    transport = FakeTransport(
        (
            response(404),
            response(
                200,
                headers={
                    "content-type": "text/html",
                    "x-robots-tag": "googlebot: noindex, nofollow",
                },
                body=(
                    b'<meta name="robots" content="index, follow">'
                    b'<meta name="googlebot" content="NoIndex">'
                    b'<link rel="alternate CANONICAL" '
                    b'href="/preferred?access_token=secret#section">'
                ),
            ),
        )
    )

    result = HomepageCrawler(FakeAddressResolver(), transport).crawl(
        "https",
        "example.com",
    )

    assert result.meta_robots_noindex is True
    assert result.x_robots_noindex is True
    assert result.canonical_url == "https://example.com/preferred"
    assert result.canonical_link_count == 1
    assert "secret" not in str(result.canonical_url)


def test_crawl_discovers_only_safe_same_host_sitemap_urls() -> None:
    robots = b"\n".join(
        (
            b"Sitemap: https://example.com/sitemap.xml?token=secret",
            b"Sitemap: /maps/index.xml",
            b"Sitemap: https://other.example.net/sitemap.xml",
            b"Sitemap: javascript:alert(1)",
        )
    )
    transport = FakeTransport(
        (
            response(200, body=robots),
            response(200, headers={"content-type": "text/html"}),
            response(
                200,
                headers={"content-type": "application/xml"},
                body=b"<urlset><url><loc>https://example.com/a</loc></url></urlset>",
            ),
            response(
                200,
                headers={"content-type": "application/xml"},
                body=b"<urlset><url><loc>https://example.com/b</loc></url></urlset>",
            ),
        )
    )

    result = HomepageCrawler(FakeAddressResolver(), transport).crawl(
        "https",
        "example.com",
    )

    assert result.robots_status_code == 200
    assert result.sitemap_declaration_count == 4
    assert result.sitemap_urls == (
        "https://example.com/sitemap.xml",
        "https://example.com/maps/index.xml",
    )
    assert result.sitemap_rejected_count == 2
    assert result.sitemap_discovery_truncated is False
    assert [item.url_count for item in result.sitemap_evidence or ()] == [1, 1]
    assert len(transport.requests) == 4
    assert all(
        request[-1] == crawler_module._MAX_SITEMAP_BODY_BYTES
        for request in transport.requests[2:]
    )
    assert all("secret" not in url for url, *_ in transport.requests)


def test_crawl_caps_sitemap_candidates_and_fetches_only_the_retained_urls() -> None:
    robots = "\n".join(
        f"Sitemap: https://example.com/sitemap-{index}.xml"
        for index in range(12)
    ).encode()
    transport = FakeTransport(
        (
            response(200, body=robots),
            response(200, headers={"content-type": "text/html"}),
            *(response(404) for _ in range(10)),
        )
    )

    result = HomepageCrawler(FakeAddressResolver(), transport).crawl(
        "https",
        "example.com",
    )

    assert result.sitemap_declaration_count == 12
    assert result.sitemap_urls is not None
    assert len(result.sitemap_urls) == 10
    assert result.sitemap_discovery_truncated is True
    assert len(result.sitemap_evidence or ()) == 10
    assert len(transport.requests) == 12


def test_crawl_caps_the_number_of_robots_sitemap_declarations_examined() -> None:
    declarations = ["Sitemap: https://example.com/sitemap.xml"] * 100
    declarations.append("Sitemap: https://external.example.net/sitemap.xml")
    transport = FakeTransport(
        (
            response(200, body="\n".join(declarations).encode()),
            response(200, headers={"content-type": "text/html"}),
            response(404),
        )
    )

    result = HomepageCrawler(FakeAddressResolver(), transport).crawl(
        "https",
        "example.com",
    )

    assert result.sitemap_declaration_count == 101
    assert result.sitemap_urls == ("https://example.com/sitemap.xml",)
    assert result.sitemap_rejected_count == 0
    assert result.sitemap_discovery_truncated is True
    assert len(transport.requests) == 3


def test_crawl_counts_only_unique_same_host_urls_in_sitemap_xml() -> None:
    sitemap = b"""<?xml version="1.0" encoding="UTF-8"?>
    <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <url><loc>https://example.com/page?token=secret</loc></url>
      <url><loc>https://example.com/page</loc></url>
      <url><loc>https://external.example.net/page</loc></url>
      <url><loc>not a URL</loc></url>
    </urlset>"""
    transport = FakeTransport(
        (
            response(200, body=b"Sitemap: https://example.com/sitemap.xml"),
            response(200, headers={"content-type": "text/html"}),
            response(
                200,
                headers={"content-type": "application/xml; charset=utf-8"},
                body=sitemap,
            ),
        )
    )

    result = HomepageCrawler(FakeAddressResolver(), transport).crawl(
        "https",
        "example.com",
    )

    assert result.sitemap_evidence == (
        SitemapEvidence(
            url="https://example.com/sitemap.xml",
            status="fetched",
            http_status_code=200,
            document_type="urlset",
            url_count=1,
            homepage_listed=None,
            canonical_url_listed=None,
            rejected_count=2,
        ),
    )
    assert "secret" not in str(result.sitemap_evidence)
    assert len(transport.requests) == 3


def test_crawl_records_homepage_and_canonical_sitemap_membership() -> None:
    sitemap = b"""<urlset>
      <url><loc>https://example.com/</loc></url>
      <url><loc>https://example.com/preferred</loc></url>
    </urlset>"""
    transport = FakeTransport(
        (
            response(200, body=b"Sitemap: https://example.com/sitemap.xml"),
            response(
                200,
                headers={"content-type": "text/html"},
                body=b'<link rel="canonical" href="/preferred?ref=private">',
            ),
            response(
                200,
                headers={"content-type": "application/xml"},
                body=sitemap,
            ),
        )
    )

    result = HomepageCrawler(FakeAddressResolver(), transport).crawl(
        "https",
        "example.com",
    )

    assert result.sitemap_evidence is not None
    assert result.sitemap_evidence[0].homepage_listed is True
    assert result.sitemap_evidence[0].canonical_url_listed is True
    assert result.canonical_url == "https://example.com/preferred"


def test_crawl_marks_absent_urls_false_in_a_complete_sitemap() -> None:
    sitemap = b"<urlset><url><loc>https://example.com/other</loc></url></urlset>"
    transport = FakeTransport(
        (
            response(200, body=b"Sitemap: https://example.com/sitemap.xml"),
            response(
                200,
                headers={"content-type": "text/html"},
                body=b'<link rel="canonical" href="/preferred">',
            ),
            response(
                200,
                headers={"content-type": "application/xml"},
                body=sitemap,
            ),
        )
    )

    result = HomepageCrawler(FakeAddressResolver(), transport).crawl(
        "https",
        "example.com",
    )

    assert result.sitemap_evidence is not None
    assert result.sitemap_evidence[0].homepage_listed is False
    assert result.sitemap_evidence[0].canonical_url_listed is False


def test_crawl_marks_sitemap_membership_unknown_when_url_set_is_truncated() -> None:
    sitemap = b"<urlset>" + (b"<url/>" * 10_001) + b"</urlset>"
    transport = FakeTransport(
        (
            response(200, body=b"Sitemap: https://example.com/sitemap.xml"),
            response(200, headers={"content-type": "text/html"}),
            response(
                200,
                headers={"content-type": "application/xml"},
                body=sitemap,
            ),
        )
    )

    result = HomepageCrawler(FakeAddressResolver(), transport).crawl(
        "https",
        "example.com",
    )

    assert result.sitemap_evidence is not None
    assert result.sitemap_evidence[0].homepage_listed is None


def test_crawl_fetches_validated_sitemap_index_children() -> None:
    sitemap_index = b"""<sitemapindex>
      <sitemap><loc>https://example.com/child.xml</loc></sitemap>
      <sitemap><loc>https://external.example.net/child.xml</loc></sitemap>
    </sitemapindex>"""
    transport = FakeTransport(
        (
            response(200, body=b"Sitemap: https://example.com/index.xml"),
            response(200, headers={"content-type": "text/html"}),
            response(
                200,
                headers={"content-type": "application/xml"},
                body=sitemap_index,
            ),
            response(
                200,
                headers={"content-type": "application/xml"},
                body=b"<urlset><url><loc>https://example.com/page</loc></url></urlset>",
            ),
        )
    )

    result = HomepageCrawler(FakeAddressResolver(), transport).crawl(
        "https",
        "example.com",
    )

    evidence = result.sitemap_evidence
    assert evidence is not None
    assert evidence[0].document_type == "sitemapindex"
    assert evidence[0].child_sitemap_count == 1
    assert evidence[0].child_sitemap_urls == (
        "https://example.com/child.xml",
    )
    assert evidence[0].url_count is None
    assert evidence[0].rejected_count == 1
    assert evidence[1].url == "https://example.com/child.xml"
    assert evidence[1].url_count == 1
    assert len(transport.requests) == 4


def test_crawl_shares_the_sitemap_document_limit_with_index_children() -> None:
    robots = "\n".join(
        f"Sitemap: https://example.com/sitemap-{index}.xml"
        for index in range(9)
    ).encode()
    sitemap_index = b"""<sitemapindex>
      <sitemap><loc>https://example.com/child-1.xml</loc></sitemap>
      <sitemap><loc>https://example.com/child-2.xml</loc></sitemap>
    </sitemapindex>"""
    top_level_responses = (
        response(
            200,
            headers={"content-type": "application/xml"},
            body=sitemap_index,
        ),
        *(response(404) for _ in range(8)),
    )
    transport = FakeTransport(
        (
            response(200, body=robots),
            response(200, headers={"content-type": "text/html"}),
            *top_level_responses,
            response(
                200,
                headers={"content-type": "application/xml"},
                body=b"<urlset><url><loc>https://example.com/page</loc></url></urlset>",
            ),
        )
    )

    result = HomepageCrawler(FakeAddressResolver(), transport).crawl(
        "https",
        "example.com",
    )

    evidence = result.sitemap_evidence
    assert evidence is not None
    assert len(transport.requests) == 12
    assert len([item for item in evidence if item.http_status_code is not None]) == 10
    assert evidence[-2].url == "https://example.com/child-1.xml"
    assert evidence[-2].status == "fetched"
    assert evidence[-1].url == "https://example.com/child-2.xml"
    assert evidence[-1].status == "fetch_limit_reached"


@pytest.mark.parametrize(
    "body",
    (
        b"<!DOCTYPE urlset [<!ENTITY x SYSTEM 'file:///etc/passwd'>]>"
        b"<urlset><url><loc>&x;</loc></url></urlset>",
        b"<urlset><url>",
    ),
)
def test_crawl_rejects_unsafe_or_malformed_sitemap_xml(body: bytes) -> None:
    transport = FakeTransport(
        (
            response(200, body=b"Sitemap: https://example.com/sitemap.xml"),
            response(200, headers={"content-type": "text/html"}),
            response(
                200,
                headers={"content-type": "application/xml"},
                body=body,
            ),
        )
    )

    result = HomepageCrawler(FakeAddressResolver(), transport).crawl(
        "https",
        "example.com",
    )

    assert result.sitemap_evidence is not None
    assert result.sitemap_evidence[0].status == "invalid_xml"


def test_crawl_does_not_fetch_robots_disallowed_sitemap() -> None:
    robots = (
        b"User-agent: *\n"
        b"Disallow: /private/\n"
        b"Sitemap: https://example.com/private/sitemap.xml"
    )
    transport = FakeTransport(
        (
            response(200, body=robots),
            response(200, headers={"content-type": "text/html"}),
        )
    )

    result = HomepageCrawler(FakeAddressResolver(), transport).crawl(
        "https",
        "example.com",
    )

    assert result.sitemap_evidence == (
        SitemapEvidence(
            url="https://example.com/private/sitemap.xml",
            status="robots_disallowed",
        ),
    )
    assert len(transport.requests) == 2


def test_crawl_rechecks_robots_policy_after_sitemap_redirects() -> None:
    robots = (
        b"User-agent: *\n"
        b"Disallow: /private/\n"
        b"Sitemap: https://example.com/sitemap.xml"
    )
    transport = FakeTransport(
        (
            response(200, body=robots),
            response(200, headers={"content-type": "text/html"}),
            response(302, headers={"location": "/private/sitemap.xml"}),
        )
    )

    result = HomepageCrawler(FakeAddressResolver(), transport).crawl(
        "https",
        "example.com",
    )

    assert result.sitemap_evidence == (
        SitemapEvidence(
            url="https://example.com/sitemap.xml",
            status="robots_disallowed",
        ),
    )
    assert len(transport.requests) == 3


def test_crawl_rechecks_robots_policy_after_homepage_redirects() -> None:
    robots = b"User-agent: *\nDisallow: /private/"
    transport = FakeTransport(
        (
            response(200, body=robots),
            response(302, headers={"location": "/private/home"}),
        )
    )

    with pytest.raises(CrawlDisallowed):
        HomepageCrawler(FakeAddressResolver(), transport).crawl(
            "https",
            "example.com",
        )

    assert len(transport.requests) == 2


def test_crawl_rejects_sitemap_response_over_the_byte_limit() -> None:
    oversized_body = b"<urlset/>" + b" " * crawler_module._MAX_SITEMAP_BODY_BYTES
    transport = FakeTransport(
        (
            response(200, body=b"Sitemap: https://example.com/sitemap.xml"),
            response(200, headers={"content-type": "text/html"}),
            response(
                200,
                headers={"content-type": "application/xml"},
                body=oversized_body,
            ),
        )
    )

    result = HomepageCrawler(FakeAddressResolver(), transport).crawl(
        "https",
        "example.com",
    )

    assert result.sitemap_evidence is not None
    assert result.sitemap_evidence[0].status == "fetch_rejected"


def test_crawl_marks_sitemap_entry_count_truncation() -> None:
    sitemap = b"<urlset>" + (b"<url/>" * 10_001) + b"</urlset>"
    transport = FakeTransport(
        (
            response(200, body=b"Sitemap: https://example.com/sitemap.xml"),
            response(200, headers={"content-type": "text/html"}),
            response(
                200,
                headers={"content-type": "application/xml"},
                body=sitemap,
            ),
        )
    )

    result = HomepageCrawler(FakeAddressResolver(), transport).crawl(
        "https",
        "example.com",
    )

    assert result.sitemap_evidence is not None
    assert result.sitemap_evidence[0].truncated is True
    assert result.sitemap_evidence[0].rejected_count == 10_000


def test_crawl_counts_invalid_and_duplicate_canonical_links() -> None:
    transport = FakeTransport(
        (
            response(404),
            response(
                200,
                headers={"content-type": "text/html"},
                body=(
                    b'<link rel="canonical" href="javascript:alert(1)">'
                    b'<link rel="canonical" href="https://example.net/page">'
                ),
            ),
        )
    )

    result = HomepageCrawler(FakeAddressResolver(), transport).crawl(
        "https",
        "example.com",
    )

    assert result.canonical_url is None
    assert result.canonical_link_count == 2


def test_crawl_caps_extracted_meta_description_length() -> None:
    html = f'<meta name="description" content="{"x" * 1100}">'.encode()
    transport = FakeTransport(
        (
            response(404),
            response(
                200,
                headers={"content-type": "text/html"},
                body=html,
            ),
        )
    )

    result = HomepageCrawler(FakeAddressResolver(), transport).crawl(
        "https",
        "example.com",
    )

    assert result.meta_description == "x" * 1000


def test_crawl_does_not_parse_seo_metadata_from_non_html_responses() -> None:
    transport = FakeTransport(
        (
            response(404),
            response(
                200,
                headers={"content-type": "application/json"},
                body=b'{"title": "not HTML"}',
            ),
        )
    )

    result = HomepageCrawler(FakeAddressResolver(), transport).crawl(
        "https",
        "example.com",
    )

    assert result.title is None
    assert result.meta_description is None
    assert result.h1_count is None
    assert result.meta_robots_noindex is None
    assert result.canonical_link_count is None


def test_crawl_revalidates_same_host_redirect_and_rejects_external_redirect() -> None:
    resolver = FakeAddressResolver()
    transport = FakeTransport(
        (
            response(404),
            response(302, headers={"location": "/home"}),
            response(200, headers={"content-type": "text/html"}, body=b"<title>Done</title>"),
        )
    )

    result = HomepageCrawler(resolver, transport).crawl("https", "example.com")

    assert result.final_url == "https://example.com/home"
    assert result.redirect_count == 1
    assert resolver.hosts == ["example.com", "example.com", "example.com"]

    external_transport = FakeTransport(
        (
            response(404),
            response(302, headers={"location": "http://127.0.0.1/admin"}),
        )
    )
    with pytest.raises(CrawlPolicyError, match="verified website host"):
        HomepageCrawler(FakeAddressResolver(), external_transport).crawl(
            "https",
            "example.com",
        )
    assert len(external_transport.requests) == 2


def test_crawl_result_redacts_redirect_query_parameters() -> None:
    transport = FakeTransport(
        (
            response(404),
            response(
                302,
                headers={"location": "/?access_token=untrusted-value"},
            ),
            response(200, headers={"content-type": "text/html"}),
        )
    )

    result = HomepageCrawler(FakeAddressResolver(), transport).crawl(
        "https",
        "example.com",
    )

    assert transport.requests[2][0] == (
        "https://example.com/?access_token=untrusted-value"
    )
    assert result.final_url == "https://example.com/"


@pytest.mark.parametrize(
    "location",
    (
        "http://example.com/insecure",
        "https://example.com:8443/",
        "https://user@example.com/",
    ),
)
def test_crawl_rejects_downgrade_custom_port_and_credentials(
    location: str,
) -> None:
    transport = FakeTransport(
        (response(404), response(302, headers={"location": location}))
    )

    with pytest.raises(CrawlPolicyError):
        HomepageCrawler(FakeAddressResolver(), transport).crawl(
            "https",
            "example.com",
        )


def test_crawl_rejects_non_public_dns_before_connecting() -> None:
    transport = FakeTransport((response(200),))

    with pytest.raises(CrawlPolicyError, match="non-public"):
        HomepageCrawler(
            FakeAddressResolver(("93.184.216.34", "169.254.169.254")),
            transport,
        ).crawl("https", "example.com")

    assert transport.requests == []


def test_stdlib_transport_parses_a_pinned_http_response(monkeypatch) -> None:
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    address, port = listener.getsockname()
    listener.settimeout(2)
    create_connection = socket.create_connection

    def connect_to_test_server(target, timeout, source_address=None):
        return create_connection((address, port), timeout, source_address)

    monkeypatch.setattr(crawler_module.socket, "create_connection", connect_to_test_server)

    def serve_response() -> None:
        try:
            connection, _ = listener.accept()
        except OSError:
            return
        with connection:
            connection.recv(4096)
            connection.sendall(
                b"HTTP/1.1 200 OK\r\n"
                b"Content-Type: text/html\r\n"
                b"Content-Length: 5\r\n"
                b"Connection: close\r\n\r\n"
                b"hello"
            )

    server = threading.Thread(target=serve_response, daemon=True)
    server.start()
    try:
        result = StdlibPinnedHttpTransport().get(
            url=f"http://example.com:{port}/",
            host="example.com",
            address=address,
            timeout_seconds=1,
            max_body_bytes=32,
        )
        assert result.status_code == 200
        assert result.headers["content-type"] == "text/html"
        assert result.body == b"hello"
    finally:
        listener.close()
        server.join(timeout=1)


def test_crawl_rejects_response_received_after_aggregate_deadline(monkeypatch) -> None:
    now = [100.0]
    monkeypatch.setattr(crawler_module, "monotonic", lambda: now[0])

    class LateTransport(FakeTransport):
        def get(
            self,
            url: str,
            host: str,
            address: str,
            timeout_seconds: float,
            max_body_bytes: int,
        ) -> HttpFetchResponse:
            result = super().get(url, host, address, timeout_seconds, max_body_bytes)
            if url == "https://example.com/":
                now[0] += 16
            return result

    with pytest.raises(CrawlUnavailable, match="time limit"):
        HomepageCrawler(
            FakeAddressResolver(),
            LateTransport((response(404), response(200))),
        ).crawl("https", "example.com")


def test_crawl_obeys_robots_disallow_without_requesting_homepage() -> None:
    transport = FakeTransport(
        (
            response(
                200,
                body=b"User-agent: ReckonSEOCrawler\nDisallow: /\n",
            ),
        )
    )

    with pytest.raises(CrawlDisallowed, match="robots.txt disallows"):
        HomepageCrawler(FakeAddressResolver(), transport).crawl(
            "https",
            "example.com",
        )

    assert [request[0] for request in transport.requests] == [
        "https://example.com/robots.txt"
    ]


def test_crawl_allows_homepage_when_robots_only_disallows_other_paths() -> None:
    transport = FakeTransport(
        (
            response(
                200,
                body=b"User-agent: ReckonSEOCrawler\nDisallow: /private\n",
            ),
            response(200, headers={"content-type": "text/html"}, body=b"<title>Home</title>"),
        )
    )

    result = HomepageCrawler(FakeAddressResolver(), transport).crawl(
        "https",
        "example.com",
    )

    assert result.title == "Home"
    assert [request[0] for request in transport.requests] == [
        "https://example.com/robots.txt",
        "https://example.com/",
    ]


def test_crawl_rejects_external_robots_redirect() -> None:
    transport = FakeTransport(
        (response(302, headers={"location": "https://other.example/robots.txt"}),)
    )

    with pytest.raises(CrawlPolicyError, match="verified website host"):
        HomepageCrawler(FakeAddressResolver(), transport).crawl(
            "https",
            "example.com",
        )

    assert [request[0] for request in transport.requests] == [
        "https://example.com/robots.txt"
    ]


@pytest.mark.parametrize(
    ("status_code", "error"),
    (
        (403, CrawlDisallowed),
        (429, CrawlDisallowed),
        (500, CrawlUnavailable),
    ),
)
def test_crawl_fails_closed_when_robots_cannot_be_checked(
    status_code: int,
    error: type[Exception],
) -> None:
    transport = FakeTransport((response(status_code),))

    with pytest.raises(error):
        HomepageCrawler(FakeAddressResolver(), transport).crawl(
            "https",
            "example.com",
        )

    assert len(transport.requests) == 1


@pytest.mark.parametrize("slow_part", ("headers", "body"))
def test_stdlib_transport_enforces_deadline_for_trickling_response(
    monkeypatch,
    slow_part: str,
) -> None:
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    address, port = listener.getsockname()
    listener.settimeout(2)
    accepted = threading.Event()
    create_connection = socket.create_connection

    def connect_to_test_server(target, timeout, source_address=None):
        return create_connection((address, port), timeout, source_address)

    monkeypatch.setattr(crawler_module.socket, "create_connection", connect_to_test_server)

    def serve_slow_response() -> None:
        try:
            connection, _ = listener.accept()
        except OSError:
            return
        accepted.set()
        with connection:
            connection.recv(4096)

            def send_slowly(payload: bytes) -> None:
                for byte in payload:
                    time.sleep(0.08)
                    try:
                        connection.sendall(bytes((byte,)))
                    except OSError:
                        return

            headers = (
                b"HTTP/1.1 200 OK\r\n"
                b"Content-Length: 8\r\n"
                b"Connection: close\r\n\r\n"
            )
            if slow_part == "headers":
                send_slowly(headers)
                return

            connection.sendall(headers)
            for _ in range(8):
                time.sleep(0.08)
                try:
                    connection.sendall(b"x")
                except OSError:
                    break

    server = threading.Thread(target=serve_slow_response, daemon=True)
    server.start()
    try:
        with pytest.raises(TimeoutError):
            StdlibPinnedHttpTransport().get(
                url=f"http://example.com:{port}/",
                host="example.com",
                address=address,
                timeout_seconds=0.25,
                max_body_bytes=32,
            )
        assert accepted.is_set()
    finally:
        listener.close()
        server.join(timeout=1)
