import pytest

from reckon_core.crawler import (
    CrawlPolicyError,
    HomepageCrawler,
    HttpFetchResponse,
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
    assert result.bytes_read == len(b"<html><title> Example page </title></html>")
    assert resolver.hosts == ["example.com"]
    assert transport.requests[0][1:3] == ("example.com", "93.184.216.34")


def test_crawl_revalidates_same_host_redirect_and_rejects_external_redirect() -> None:
    resolver = FakeAddressResolver()
    transport = FakeTransport(
        (
            response(302, headers={"location": "/home"}),
            response(200, headers={"content-type": "text/html"}, body=b"<title>Done</title>"),
        )
    )

    result = HomepageCrawler(resolver, transport).crawl("https", "example.com")

    assert result.final_url == "https://example.com/home"
    assert result.redirect_count == 1
    assert resolver.hosts == ["example.com", "example.com"]

    external_transport = FakeTransport(
        (response(302, headers={"location": "http://127.0.0.1/admin"}),)
    )
    with pytest.raises(CrawlPolicyError, match="verified website host"):
        HomepageCrawler(FakeAddressResolver(), external_transport).crawl(
            "https",
            "example.com",
        )
    assert len(external_transport.requests) == 1


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
    transport = FakeTransport((response(302, headers={"location": location}),))

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
