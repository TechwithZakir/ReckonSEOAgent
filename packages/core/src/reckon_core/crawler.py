import http.client
import socket
import ssl
import time
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Protocol
from urllib.parse import urljoin, urlsplit, urlunsplit

from reckon_core.crawl_security import (
    CrawlTargetError,
    DnsAddressLookup,
    DnsAddressLookupUnavailable,
    PublicDnsAddressResolver,
    resolve_public_crawl_target,
)


_MAX_URL_LENGTH = 2048
_MAX_REDIRECTS = 2
_MAX_BODY_BYTES = 512 * 1024
_MAX_ADDRESS_ATTEMPTS = 2
_REQUEST_TIMEOUT_SECONDS = 2.0
_MAX_RUN_SECONDS = 15.0
_REDIRECT_STATUSES = {301, 302, 303, 307, 308}
_USER_AGENT = "ReckonSEOCrawler/0.1 (+https://reckonseo.com/crawler)"


class CrawlError(RuntimeError):
    pass


class CrawlPolicyError(CrawlError):
    pass


class CrawlUnavailable(CrawlError):
    pass


class CrawlBodyTooLarge(CrawlPolicyError):
    pass


@dataclass(frozen=True, slots=True)
class HttpFetchResponse:
    status_code: int
    headers: dict[str, str]
    body: bytes


class PinnedHttpTransport(Protocol):
    def get(
        self,
        url: str,
        host: str,
        address: str,
        timeout_seconds: float,
        max_body_bytes: int,
    ) -> HttpFetchResponse:
        """Fetch using the supplied address without resolving the hostname again."""


@dataclass(frozen=True, slots=True)
class CrawlResult:
    final_url: str
    status_code: int
    content_type: str
    bytes_read: int
    title: str | None
    redirect_count: int


class _PinnedHTTPConnection(http.client.HTTPConnection):
    def __init__(self, host: str, address: str, timeout: float) -> None:
        super().__init__(host, timeout=timeout)
        self._address = address

    def connect(self) -> None:
        self.sock = socket.create_connection(
            (self._address, self.port),
            self.timeout,
            self.source_address,
        )


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(
        self,
        host: str,
        address: str,
        timeout: float,
        context: ssl.SSLContext,
    ) -> None:
        super().__init__(host, timeout=timeout, context=context)
        self._address = address

    def connect(self) -> None:
        raw_socket = socket.create_connection(
            (self._address, self.port),
            self.timeout,
            self.source_address,
        )
        self.sock = self._context.wrap_socket(
            raw_socket,
            server_hostname=self._tunnel_host or self.host,
        )


class StdlibPinnedHttpTransport:
    def get(
        self,
        url: str,
        host: str,
        address: str,
        timeout_seconds: float,
        max_body_bytes: int,
    ) -> HttpFetchResponse:
        parsed = urlsplit(url)
        port = 443 if parsed.scheme == "https" else 80
        if parsed.scheme == "https":
            connection: http.client.HTTPConnection = _PinnedHTTPSConnection(
                host,
                address,
                timeout_seconds,
                ssl.create_default_context(),
            )
        else:
            connection = _PinnedHTTPConnection(host, address, timeout_seconds)

        request_target = urlunsplit(("", "", parsed.path or "/", parsed.query, ""))
        try:
            connection.request(
                "GET",
                request_target,
                headers={
                    "Accept": "text/html,application/xhtml+xml",
                    "Accept-Encoding": "identity",
                    "Connection": "close",
                    "Host": host if port in {80, 443} else f"{host}:{port}",
                    "User-Agent": _USER_AGENT,
                },
            )
            response = connection.getresponse()
            headers = {
                name.lower(): value
                for name, value in response.getheaders()
            }
            if headers.get("content-encoding", "identity").lower() != "identity":
                raise CrawlPolicyError("Compressed crawl responses are not accepted.")

            content_length = headers.get("content-length")
            if content_length is not None:
                try:
                    declared_length = int(content_length)
                except ValueError as error:
                    raise CrawlPolicyError(
                        "The website returned an invalid content length."
                    ) from error
                if declared_length < 0:
                    raise CrawlPolicyError(
                        "The website returned an invalid content length."
                    )
                if declared_length > max_body_bytes:
                    raise CrawlBodyTooLarge("The homepage exceeds the crawl size limit.")

            if response.status in _REDIRECT_STATUSES:
                body = b""
            else:
                body = response.read(max_body_bytes + 1)
                if len(body) > max_body_bytes:
                    raise CrawlBodyTooLarge(
                        "The homepage exceeds the crawl size limit."
                    )
            return HttpFetchResponse(
                status_code=response.status,
                headers=headers,
                body=body,
            )
        finally:
            connection.close()


class _TitleParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._in_title = False
        self._parts: list[str] = []
        self._length = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "title":
            self._in_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title and self._length < 300:
            part = data[: 300 - self._length]
            self._parts.append(part)
            self._length += len(part)

    @property
    def title(self) -> str | None:
        value = " ".join(" ".join(self._parts).split())[:300]
        return value or None


def _validated_url(value: str, allowed_host: str) -> tuple[str, str, str]:
    if (
        not value
        or len(value) > _MAX_URL_LENGTH
        or value != value.strip()
        or "\\" in value
        or any(ord(char) < 32 for char in value)
    ):
        raise CrawlPolicyError("The crawl URL is invalid.")

    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError as error:
        raise CrawlPolicyError("The crawl URL is invalid.") from error

    if (
        parsed.scheme.lower() not in {"http", "https"}
        or hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise CrawlPolicyError("Only public HTTP(S) pages without credentials are allowed.")

    try:
        canonical_host = hostname.encode("idna").decode("ascii").lower()
        canonical_allowed_host = allowed_host.encode("idna").decode("ascii").lower()
    except UnicodeError as error:
        raise CrawlPolicyError("The crawl URL hostname is invalid.") from error

    if canonical_host != canonical_allowed_host:
        raise CrawlPolicyError("Crawling is restricted to the verified website host.")
    if port not in {None, 80 if parsed.scheme.lower() == "http" else 443}:
        raise CrawlPolicyError("Non-standard crawl ports are not allowed.")

    scheme = parsed.scheme.lower()
    path = parsed.path or "/"
    url = urlunsplit((scheme, canonical_host, path, parsed.query, ""))
    return url, scheme, canonical_host


def _page_title(content_type: str, body: bytes) -> str | None:
    media_type = content_type.split(";", 1)[0].strip().lower()
    if media_type not in {"text/html", "application/xhtml+xml"}:
        return None
    parser = _TitleParser()
    parser.feed(body.decode("utf-8", errors="replace"))
    parser.close()
    return parser.title


class HomepageCrawler:
    def __init__(
        self,
        resolver: DnsAddressLookup | None = None,
        transport: PinnedHttpTransport | None = None,
    ) -> None:
        self._resolver = resolver or PublicDnsAddressResolver(timeout_seconds=1.0)
        self._transport = transport or StdlibPinnedHttpTransport()

    def crawl(self, scheme: str, host: str) -> CrawlResult:
        if scheme not in {"http", "https"}:
            raise CrawlPolicyError("Only public HTTP(S) websites can be crawled.")

        url = f"{scheme}://{host}/"
        redirects = 0
        visited: set[str] = set()
        deadline = time.monotonic() + _MAX_RUN_SECONDS

        while True:
            url, current_scheme, current_host = _validated_url(url, host)
            if url in visited:
                raise CrawlPolicyError("The website returned a redirect loop.")
            visited.add(url)

            if time.monotonic() >= deadline:
                raise CrawlUnavailable("The homepage check exceeded its time limit.")
            try:
                target = resolve_public_crawl_target(current_host, self._resolver)
            except DnsAddressLookupUnavailable as error:
                raise CrawlUnavailable("Website DNS lookup is temporarily unavailable.") from error
            except CrawlTargetError as error:
                raise CrawlPolicyError(str(error)) from error

            last_error: OSError | http.client.HTTPException | None = None
            response: HttpFetchResponse | None = None
            for address in target.addresses[:_MAX_ADDRESS_ATTEMPTS]:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                try:
                    response = self._transport.get(
                        url=url,
                        host=current_host,
                        address=address,
                        timeout_seconds=min(_REQUEST_TIMEOUT_SECONDS, remaining),
                        max_body_bytes=_MAX_BODY_BYTES,
                    )
                    break
                except (OSError, http.client.HTTPException) as error:
                    last_error = error

            if response is None:
                if time.monotonic() >= deadline:
                    raise CrawlUnavailable(
                        "The homepage check exceeded its time limit."
                    ) from last_error
                raise CrawlUnavailable(
                    "The website could not be reached at its public DNS addresses."
                ) from last_error

            if response.status_code in _REDIRECT_STATUSES:
                location = response.headers.get("location")
                if not location or len(location) > _MAX_URL_LENGTH:
                    raise CrawlPolicyError("The website returned an invalid redirect.")
                if redirects >= _MAX_REDIRECTS:
                    raise CrawlPolicyError("The website exceeded the redirect limit.")
                next_url = urljoin(url, location)
                next_url, next_scheme, _ = _validated_url(next_url, host)
                if current_scheme == "https" and next_scheme != "https":
                    raise CrawlPolicyError("HTTPS redirects cannot downgrade to HTTP.")
                url = next_url
                redirects += 1
                continue

            content_type = response.headers.get("content-type", "")
            return CrawlResult(
                final_url=url,
                status_code=response.status_code,
                content_type=content_type,
                bytes_read=len(response.body),
                title=_page_title(content_type, response.body),
                redirect_count=redirects,
            )
