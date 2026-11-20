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
    assert result.bytes_read == len(b"<html><title> Example page </title></html>")
    assert resolver.hosts == ["example.com", "example.com"]
    assert transport.requests[0][0] == "https://example.com/robots.txt"
    assert transport.requests[1][0] == "https://example.com/"
    assert transport.requests[1][1:3] == ("example.com", "93.184.216.34")


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
