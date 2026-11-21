import http.client
import ipaddress
import io
import socket
import ssl
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from html.parser import HTMLParser
from time import monotonic
from typing import Literal, Protocol
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

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
_MAX_META_DESCRIPTION_LENGTH = 1000
_MAX_SITEMAP_DECLARATIONS = 100
_MAX_SITEMAP_URLS = 10
_MAX_SITEMAP_BODY_BYTES = 256 * 1024
_MAX_SITEMAP_ENTRIES = 10_000
_MAX_SITEMAP_CHILD_URLS = 10
_MAX_SITEMAP_DOCUMENTS = 10
_MAX_SITEMAP_SECONDS = 4.0
_MAX_ADDRESS_ATTEMPTS = 2
_REQUEST_TIMEOUT_SECONDS = 2.0
_MAX_RUN_SECONDS = 15.0
_REDIRECT_STATUSES = {301, 302, 303, 307, 308}
_USER_AGENT = "ReckonSEOCrawler/0.1 (+https://reckonseo.com/crawler)"
_ROBOTS_USER_AGENT = "ReckonSEOCrawler"


class _DeadlineSocketReader(io.RawIOBase):
    def __init__(self, sock: socket.socket, deadline: float) -> None:
        self._sock = sock
        self._deadline = deadline

    def readable(self) -> bool:
        return True

    def readinto(self, buffer: memoryview) -> int:
        remaining = self._deadline - monotonic()
        if remaining <= 0:
            raise TimeoutError("The HTTP response exceeded its time limit.")
        self._sock.settimeout(remaining)
        data = self._sock.recv(len(buffer))
        if monotonic() >= self._deadline:
            raise TimeoutError("The HTTP response exceeded its time limit.")
        if not data:
            return 0
        buffer[: len(data)] = data
        return len(data)


class _DeadlineSocket:
    def __init__(self, sock: socket.socket, deadline: float) -> None:
        self._sock = sock
        self._deadline = deadline

    def makefile(
        self,
        mode: str,
        buffering: int | None = None,
    ) -> io.BufferedReader:
        if mode != "rb":
            raise ValueError("The HTTP response requires a binary read stream.")
        raw = _DeadlineSocketReader(self._sock, self._deadline)
        if buffering is not None and buffering > 0:
            return io.BufferedReader(raw, buffer_size=buffering)
        return io.BufferedReader(raw)


class CrawlError(RuntimeError):
    pass


class CrawlPolicyError(CrawlError):
    pass


class CrawlDisallowed(CrawlPolicyError):
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


SitemapFetchStatus = Literal[
    "fetched",
    "http_error",
    "robots_disallowed",
    "fetch_unavailable",
    "fetch_rejected",
    "unsupported_content_type",
    "invalid_xml",
    "deadline_exceeded",
    "fetch_limit_reached",
]
SitemapDocumentType = Literal["urlset", "sitemapindex"]


@dataclass(frozen=True, slots=True)
class SitemapEvidence:
    url: str
    status: SitemapFetchStatus
    http_status_code: int | None = None
    document_type: SitemapDocumentType | None = None
    url_count: int | None = None
    homepage_listed: bool | None = None
    canonical_url_listed: bool | None = None
    child_sitemap_count: int | None = None
    child_sitemap_urls: tuple[str, ...] = ()
    rejected_count: int | None = None
    truncated: bool = False


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
    meta_description: str | None = None
    h1_count: int | None = None
    meta_robots_noindex: bool | None = None
    x_robots_noindex: bool | None = None
    canonical_url: str | None = None
    canonical_link_count: int | None = None
    robots_status_code: int | None = None
    sitemap_urls: tuple[str, ...] | None = None
    sitemap_declaration_count: int | None = None
    sitemap_rejected_count: int | None = None
    sitemap_discovery_truncated: bool | None = None
    sitemap_evidence: tuple[SitemapEvidence, ...] | None = None


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
        deadline = monotonic() + timeout_seconds
        response: http.client.HTTPResponse | None = None
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
            if connection.sock is None:
                raise CrawlUnavailable("The homepage connection was not established.")
            response = connection.response_class(
                _DeadlineSocket(connection.sock, deadline),
                method="GET",
            )
            response.begin()
            headers: dict[str, str] = {}
            for name, value in response.getheaders():
                normalized_name = name.lower()
                if normalized_name == "x-robots-tag" and normalized_name in headers:
                    headers[normalized_name] += f", {value}"
                else:
                    headers[normalized_name] = value
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
                body_bytes = bytearray()
                while len(body_bytes) <= max_body_bytes:
                    remaining = deadline - monotonic()
                    if remaining <= 0:
                        raise TimeoutError(
                            "The HTTP response exceeded its time limit."
                        )
                    chunk = response.read1(
                        min(64 * 1024, max_body_bytes + 1 - len(body_bytes))
                    )
                    if not chunk:
                        break
                    body_bytes.extend(chunk)
                    if monotonic() >= deadline:
                        raise TimeoutError(
                            "The HTTP response exceeded its time limit."
                        )
                body = bytes(body_bytes)
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
            if response is not None:
                response.close()
            connection.close()


@dataclass(frozen=True, slots=True)
class _PageMetadata:
    title: str | None
    description: str | None
    h1_count: int
    robots_noindex: bool | None
    canonical_url: str | None
    canonical_link_count: int


class _PageMetadataParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._in_title = False
        self._title_parts: list[str] = []
        self._title_length = 0
        self._description: str | None = None
        self._h1_count = 0
        self._robots_meta_seen = False
        self._robots_noindex = False
        self._canonical_href: str | None = None
        self._canonical_link_count = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        normalized_tag = tag.lower()
        attributes = {
            name.lower(): value
            for name, value in attrs
            if value is not None
        }
        if normalized_tag == "title":
            self._in_title = True
        elif normalized_tag == "h1":
            self._h1_count += 1
        elif normalized_tag == "meta" and self._description is None:
            if attributes.get("name", "").casefold() == "description":
                description = " ".join(
                    attributes.get("content", "").split()
                )[:_MAX_META_DESCRIPTION_LENGTH]
                self._description = description or None
        if normalized_tag == "meta":
            name = attributes.get("name", "").casefold()
            if name in {"robots", "googlebot"}:
                self._robots_meta_seen = True
                if _has_noindex(attributes.get("content", "")):
                    self._robots_noindex = True
        elif normalized_tag == "link":
            rel_values = attributes.get("rel", "").casefold().split()
            if "canonical" in rel_values:
                self._canonical_link_count += 1
                if self._canonical_link_count == 1:
                    self._canonical_href = attributes.get("href")

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title and self._title_length < 300:
            part = data[: 300 - self._title_length]
            self._title_parts.append(part)
            self._title_length += len(part)

    @property
    def title(self) -> str | None:
        value = " ".join(" ".join(self._title_parts).split())[:300]
        return value or None

    @property
    def description(self) -> str | None:
        return self._description

    @property
    def h1_count(self) -> int:
        return self._h1_count

    @property
    def robots_noindex(self) -> bool | None:
        return self._robots_noindex if self._robots_meta_seen else None

    @property
    def canonical_href(self) -> str | None:
        return self._canonical_href

    @property
    def canonical_link_count(self) -> int:
        return self._canonical_link_count


def _has_noindex(value: str) -> bool:
    directives = (
        directive.split(":", 1)[-1]
        for directive in value.casefold().replace(",", " ").split()
    )
    return any(directive in {"noindex", "none"} for directive in directives)


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


def _normalized_canonical_url(base_url: str, href: str | None) -> str | None:
    if (
        not href
        or len(href) > _MAX_URL_LENGTH
        or href != href.strip()
        or "\\" in href
        or any(ord(char) < 32 for char in href)
    ):
        return None

    candidate = urljoin(base_url, href)
    if len(candidate) > _MAX_URL_LENGTH:
        return None
    try:
        parsed = urlsplit(candidate)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme.lower() not in {"http", "https"}
        or hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or "\\" in candidate
        or any(ord(char) < 32 for char in candidate)
    ):
        return None

    try:
        address = ipaddress.ip_address(hostname)
        canonical_host = address.compressed.lower()
        if address.version == 6:
            canonical_host = f"[{canonical_host}]"
    except ValueError:
        try:
            canonical_host = hostname.encode("idna").decode("ascii").lower()
        except UnicodeError:
            return None

    scheme = parsed.scheme.lower()
    if port not in {None, 80 if scheme == "http" else 443}:
        canonical_host = f"{canonical_host}:{port}"
    return urlunsplit((scheme, canonical_host, parsed.path or "/", "", ""))


def _discover_sitemaps(
    robots_parser: RobotFileParser,
    robots_url: str,
    allowed_host: str,
) -> tuple[tuple[str, ...], int, int, bool]:
    declarations = robots_parser.site_maps() or []
    sitemap_urls: list[str] = []
    seen_urls: set[str] = set()
    rejected_count = 0
    truncated = len(declarations) > _MAX_SITEMAP_DECLARATIONS

    for declaration in declarations[:_MAX_SITEMAP_DECLARATIONS]:
        normalized = _normalized_canonical_url(robots_url, declaration)
        if normalized is None:
            rejected_count += 1
            continue
        try:
            normalized, sitemap_scheme, _ = _validated_url(normalized, allowed_host)
        except CrawlPolicyError:
            rejected_count += 1
            continue
        if (
            urlsplit(robots_url).scheme.lower() == "https"
            and sitemap_scheme != "https"
        ):
            rejected_count += 1
            continue
        if normalized in seen_urls:
            continue
        seen_urls.add(normalized)
        if len(sitemap_urls) == _MAX_SITEMAP_URLS:
            truncated = True
            continue
        sitemap_urls.append(normalized)

    return tuple(sitemap_urls), len(declarations), rejected_count, truncated


def _page_metadata(
    content_type: str,
    body: bytes,
    page_url: str,
) -> _PageMetadata | None:
    media_type = content_type.split(";", 1)[0].strip().lower()
    if media_type not in {"text/html", "application/xhtml+xml"}:
        return None
    parser = _PageMetadataParser()
    parser.feed(body.decode("utf-8", errors="replace"))
    parser.close()
    return _PageMetadata(
        title=parser.title,
        description=parser.description,
        h1_count=parser.h1_count,
        robots_noindex=parser.robots_noindex,
        canonical_url=_normalized_canonical_url(
            page_url,
            parser.canonical_href,
        ),
        canonical_link_count=parser.canonical_link_count,
    )


def _without_query(value: str) -> str:
    parsed = urlsplit(value)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def _fetch_url(
    url: str,
    allowed_host: str,
    resolver: DnsAddressLookup,
    transport: PinnedHttpTransport,
    deadline: float,
    max_body_bytes: int = _MAX_BODY_BYTES,
    robots_parser: RobotFileParser | None = None,
) -> tuple[str, HttpFetchResponse, int]:
    redirects = 0
    visited: set[str] = set()

    while True:
        url, current_scheme, current_host = _validated_url(url, allowed_host)
        if url in visited:
            raise CrawlPolicyError("The website returned a redirect loop.")
        visited.add(url)
        if robots_parser is not None and not robots_parser.can_fetch(
            _ROBOTS_USER_AGENT,
            url,
        ):
            raise CrawlDisallowed("robots.txt disallows this crawl URL.")

        if monotonic() >= deadline:
            raise CrawlUnavailable("The homepage check exceeded its time limit.")
        try:
            target = resolve_public_crawl_target(current_host, resolver)
        except DnsAddressLookupUnavailable as error:
            raise CrawlUnavailable("Website DNS lookup is temporarily unavailable.") from error
        except CrawlTargetError as error:
            raise CrawlPolicyError(str(error)) from error

        last_error: OSError | http.client.HTTPException | None = None
        response: HttpFetchResponse | None = None
        for address in target.addresses[:_MAX_ADDRESS_ATTEMPTS]:
            remaining = deadline - monotonic()
            if remaining <= 0:
                break
            try:
                response = transport.get(
                    url=url,
                    host=current_host,
                    address=address,
                    timeout_seconds=min(_REQUEST_TIMEOUT_SECONDS, remaining),
                    max_body_bytes=max_body_bytes,
                )
                if monotonic() >= deadline:
                    raise CrawlUnavailable(
                        "The homepage check exceeded its time limit."
                    )
                if len(response.body) > max_body_bytes:
                    raise CrawlBodyTooLarge(
                        "The website response exceeds the crawl size limit."
                    )
                break
            except (OSError, http.client.HTTPException) as error:
                last_error = error

        if response is None:
            if monotonic() >= deadline:
                raise CrawlUnavailable(
                    "The homepage check exceeded its time limit."
                ) from last_error
            raise CrawlUnavailable(
                "The website could not be reached at its public DNS addresses."
            ) from last_error

        if response.status_code not in _REDIRECT_STATUSES:
            return url, response, redirects

        location = response.headers.get("location")
        if not location or len(location) > _MAX_URL_LENGTH:
            raise CrawlPolicyError("The website returned an invalid redirect.")
        if redirects >= _MAX_REDIRECTS:
            raise CrawlPolicyError("The website exceeded the redirect limit.")
        next_url = urljoin(url, location)
        next_url, next_scheme, _ = _validated_url(next_url, allowed_host)
        if current_scheme == "https" and next_scheme != "https":
            raise CrawlPolicyError("HTTPS redirects cannot downgrade to HTTP.")
        url = next_url
        redirects += 1


def _xml_local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _normalized_sitemap_location(
    value: str,
    base_url: str,
    allowed_host: str,
) -> str | None:
    try:
        parsed = urlsplit(value)
    except ValueError:
        return None
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        return None

    normalized = _normalized_canonical_url(base_url, value)
    if normalized is None:
        return None
    try:
        normalized, location_scheme, _ = _validated_url(normalized, allowed_host)
    except CrawlPolicyError:
        return None
    if (
        urlsplit(base_url).scheme.lower() == "https"
        and location_scheme != "https"
    ):
        return None
    return normalized


def _parse_sitemap_document(
    sitemap_url: str,
    response: HttpFetchResponse,
    allowed_host: str,
    homepage_url: str,
    canonical_url: str | None,
    base_url: str | None = None,
) -> SitemapEvidence:
    media_type = (
        response.headers.get("content-type", "")
        .split(";", 1)[0]
        .strip()
        .lower()
    )
    if not (
        media_type in {"application/xml", "text/xml"}
        or media_type.endswith("+xml")
    ):
        return SitemapEvidence(
            url=sitemap_url,
            status="unsupported_content_type",
            http_status_code=response.status_code,
        )

    lowered_body = response.body.lower()
    if b"<!doctype" in lowered_body or b"<!entity" in lowered_body:
        return SitemapEvidence(
            url=sitemap_url,
            status="invalid_xml",
            http_status_code=response.status_code,
        )
    try:
        root = ET.fromstring(response.body)
    except (ET.ParseError, RecursionError):
        return SitemapEvidence(
            url=sitemap_url,
            status="invalid_xml",
            http_status_code=response.status_code,
        )

    root_name = _xml_local_name(root.tag)
    if root_name == "urlset":
        entry_name: Literal["url", "sitemap"] = "url"
        document_type: SitemapDocumentType = "urlset"
    elif root_name == "sitemapindex":
        entry_name = "sitemap"
        document_type = "sitemapindex"
    else:
        return SitemapEvidence(
            url=sitemap_url,
            status="invalid_xml",
            http_status_code=response.status_code,
        )

    entries = [
        child for child in root
        if _xml_local_name(child.tag) == entry_name
    ]
    truncated = len(entries) > _MAX_SITEMAP_ENTRIES
    seen_locations: set[str] = set()
    child_sitemap_urls: list[str] = []
    rejected_count = 0
    base_url = base_url or sitemap_url
    homepage_target = _normalized_sitemap_location(
        homepage_url,
        base_url,
        allowed_host,
    )
    canonical_target = (
        _normalized_sitemap_location(canonical_url, base_url, allowed_host)
        if canonical_url is not None
        else None
    )
    homepage_found = False
    canonical_found = False
    for entry in entries[:_MAX_SITEMAP_ENTRIES]:
        location = next(
            (
                child.text.strip()
                for child in entry
                if _xml_local_name(child.tag) == "loc"
                and child.text
                and child.text.strip()
            ),
            None,
        )
        normalized = (
            _normalized_sitemap_location(location, base_url, allowed_host)
            if location is not None
            else None
        )
        if normalized is None:
            rejected_count += 1
            continue
        if normalized in seen_locations:
            continue
        seen_locations.add(normalized)
        if document_type == "urlset":
            homepage_found = homepage_found or normalized == homepage_target
            canonical_found = canonical_found or normalized == canonical_target
        if (
            document_type == "sitemapindex"
            and len(child_sitemap_urls) < _MAX_SITEMAP_CHILD_URLS
        ):
            child_sitemap_urls.append(normalized)

    location_count = len(seen_locations)
    if (
        document_type == "sitemapindex"
        and location_count > _MAX_SITEMAP_CHILD_URLS
    ):
        truncated = True
    return SitemapEvidence(
        url=sitemap_url,
        status="fetched",
        http_status_code=response.status_code,
        document_type=document_type,
        url_count=location_count if document_type == "urlset" else None,
        homepage_listed=(
            homepage_found
            if document_type == "urlset" and not truncated and rejected_count == 0
            else None
        ),
        canonical_url_listed=(
            canonical_found
            if (
                document_type == "urlset"
                and canonical_target is not None
                and not truncated
                and rejected_count == 0
            )
            else None
        ),
        child_sitemap_count=(
            location_count if document_type == "sitemapindex" else None
        ),
        child_sitemap_urls=tuple(child_sitemap_urls),
        rejected_count=rejected_count,
        truncated=truncated,
    )


def _fetch_sitemap_evidence(
    sitemap_urls: tuple[str, ...],
    allowed_host: str,
    resolver: DnsAddressLookup,
    transport: PinnedHttpTransport,
    robots_parser: RobotFileParser | None,
    sitemap_deadline: float,
    homepage_url: str,
    canonical_url: str | None,
) -> tuple[SitemapEvidence, ...]:
    evidence: list[SitemapEvidence] = []
    for sitemap_url in sitemap_urls:
        if robots_parser is not None and not robots_parser.can_fetch(
            _ROBOTS_USER_AGENT,
            sitemap_url,
        ):
            evidence.append(
                SitemapEvidence(url=sitemap_url, status="robots_disallowed")
            )
            continue
        if monotonic() >= sitemap_deadline:
            evidence.append(
                SitemapEvidence(url=sitemap_url, status="deadline_exceeded")
            )
            continue
        try:
            final_url, response, _ = _fetch_url(
                sitemap_url,
                allowed_host,
                resolver,
                transport,
                sitemap_deadline,
                max_body_bytes=_MAX_SITEMAP_BODY_BYTES,
                robots_parser=robots_parser,
            )
        except CrawlUnavailable:
            status: SitemapFetchStatus = (
                "deadline_exceeded"
                if monotonic() >= sitemap_deadline
                else "fetch_unavailable"
            )
            evidence.append(SitemapEvidence(url=sitemap_url, status=status))
            continue
        except CrawlDisallowed:
            evidence.append(
                SitemapEvidence(url=sitemap_url, status="robots_disallowed")
            )
            continue
        except CrawlPolicyError:
            evidence.append(
                SitemapEvidence(url=sitemap_url, status="fetch_rejected")
            )
            continue

        if not 200 <= response.status_code < 300 or response.status_code == 206:
            evidence.append(
                SitemapEvidence(
                    url=sitemap_url,
                    status="http_error",
                    http_status_code=response.status_code,
                )
            )
            continue
        evidence.append(
            _parse_sitemap_document(
                sitemap_url,
                response,
                allowed_host,
                homepage_url,
                canonical_url,
                base_url=_without_query(final_url),
            )
        )
    return tuple(evidence)


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

        homepage_url = f"{scheme}://{host}/"
        deadline = monotonic() + _MAX_RUN_SECONDS

        robots_url = f"{scheme}://{host}/robots.txt"
        robots_final_url, robots_response, _ = _fetch_url(
            robots_url,
            host,
            self._resolver,
            self._transport,
            deadline,
        )
        sitemap_urls: tuple[str, ...] = ()
        sitemap_declaration_count = 0
        sitemap_rejected_count = 0
        sitemap_discovery_truncated = False
        robots_parser: RobotFileParser | None = None
        if (
            200 <= robots_response.status_code < 300
            and robots_response.status_code != 206
        ):
            robots_parser = RobotFileParser()
            robots_parser.parse(
                robots_response.body.decode("utf-8", errors="replace").splitlines()
            )
            (
                sitemap_urls,
                sitemap_declaration_count,
                sitemap_rejected_count,
                sitemap_discovery_truncated,
            ) = _discover_sitemaps(
                robots_parser,
                _without_query(robots_final_url),
                host,
            )
            if not robots_parser.can_fetch(_ROBOTS_USER_AGENT, homepage_url):
                raise CrawlDisallowed("robots.txt disallows crawling this homepage.")
        elif robots_response.status_code not in {404, 410}:
            if 400 <= robots_response.status_code < 500:
                raise CrawlDisallowed(
                    "robots.txt could not be accessed; crawling is denied."
                )
            raise CrawlUnavailable(
                "robots.txt could not be checked; crawling is unavailable."
            )

        final_url, homepage_response, redirects = _fetch_url(
            homepage_url,
            host,
            self._resolver,
            self._transport,
            deadline,
            robots_parser=robots_parser,
        )
        content_type = homepage_response.headers.get("content-type", "")
        metadata = _page_metadata(content_type, homepage_response.body, final_url)
        sitemap_deadline = min(deadline, monotonic() + _MAX_SITEMAP_SECONDS)
        canonical_url = metadata.canonical_url if metadata is not None else None
        homepage_membership_url = _without_query(final_url)
        top_level_sitemap_evidence = _fetch_sitemap_evidence(
            sitemap_urls,
            host,
            self._resolver,
            self._transport,
            robots_parser,
            sitemap_deadline,
            homepage_membership_url,
            canonical_url,
        )
        seen_sitemap_urls = set(sitemap_urls)
        child_sitemap_urls: list[str] = []
        for item in top_level_sitemap_evidence:
            for child_url in item.child_sitemap_urls:
                if child_url not in seen_sitemap_urls:
                    seen_sitemap_urls.add(child_url)
                    child_sitemap_urls.append(child_url)

        child_fetch_limit = max(
            0,
            _MAX_SITEMAP_DOCUMENTS - len(sitemap_urls),
        )
        child_urls_to_fetch = tuple(child_sitemap_urls[:child_fetch_limit])
        child_sitemap_evidence = _fetch_sitemap_evidence(
            child_urls_to_fetch,
            host,
            self._resolver,
            self._transport,
            robots_parser,
            sitemap_deadline,
            homepage_membership_url,
            canonical_url,
        )
        skipped_child_evidence = tuple(
            SitemapEvidence(
                url=child_url,
                status="fetch_limit_reached",
            )
            for child_url in child_sitemap_urls[child_fetch_limit:]
        )
        sitemap_evidence = (
            top_level_sitemap_evidence
            + child_sitemap_evidence
            + skipped_child_evidence
        )
        return CrawlResult(
            final_url=_without_query(final_url),
            status_code=homepage_response.status_code,
            content_type=content_type,
            bytes_read=len(homepage_response.body),
            title=metadata.title if metadata is not None else None,
            redirect_count=redirects,
            meta_description=(
                metadata.description if metadata is not None else None
            ),
            h1_count=metadata.h1_count if metadata is not None else None,
            meta_robots_noindex=(
                metadata.robots_noindex if metadata is not None else None
            ),
            x_robots_noindex=_has_noindex(
                homepage_response.headers["x-robots-tag"]
            )
            if "x-robots-tag" in homepage_response.headers
            else None,
            canonical_url=(
                metadata.canonical_url if metadata is not None else None
            ),
            canonical_link_count=(
                metadata.canonical_link_count if metadata is not None else None
            ),
            robots_status_code=robots_response.status_code,
            sitemap_urls=sitemap_urls,
            sitemap_declaration_count=sitemap_declaration_count,
            sitemap_rejected_count=sitemap_rejected_count,
            sitemap_discovery_truncated=sitemap_discovery_truncated,
            sitemap_evidence=sitemap_evidence,
        )
