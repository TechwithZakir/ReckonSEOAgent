"""Independent verification of SEO changes by reading the public page.

Used for changes applied by an external executor (for example the Claude Chrome extension
driving wp-admin). It never writes. It fetches the proposal's public URL through the same
pinned-DNS, redirect-checked, size-bounded fetcher as the crawler and compares what the
live HTML actually serves with the approved value. The page is untrusted data; it is only
parsed and compared, never interpreted.
"""

import json
import re
import time
from collections.abc import Callable
from html.parser import HTMLParser
from time import monotonic
from urllib.parse import urljoin, urlsplit

from reckon_core.crawl_security import DnsAddressLookup, PublicDnsAddressResolver
from reckon_core.crawler import (
    CrawlError,
    PinnedHttpTransport,
    StdlibPinnedHttpTransport,
    _fetch_url,
)
from reckon_core.persistence import SeoActionProposal

VERIFIABLE_ACTION_TYPES = frozenset(
    {"meta_title", "meta_description", "canonical", "heading", "schema"}
)
_MAX_BODY_BYTES = 1024 * 1024
_MAX_RUN_SECONDS = 15.0
_MAX_JSON_LD_BLOCKS = 20


# A page cache can serve the old HTML briefly after an edit. Retry a bounded number of times
# (total wait stays inside one request) before reporting a mismatch.
_RETRY_DELAYS_SECONDS = (2.0, 5.0)
# A theme may append " | Site name" to <title>; accepted only after the approved text.
_TITLE_SUFFIX = re.compile(r"^\s*[-\u2013\u2014|\u00b7:\u2022]\s*\S.{0,80}$")


class PublicVerificationError(RuntimeError):
    pass


class UnsupportedVerification(PublicVerificationError):
    pass


class PublicVerificationFailed(PublicVerificationError):
    pass


def _collapse(value: str) -> str:
    return " ".join(value.split())


class _LivePageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title_parts: list[str] = []
        self.descriptions: list[str] = []
        self.canonicals: list[str] = []
        self.h1s: list[str] = []
        self.json_ld: list[str] = []
        self._in_title = False
        self._in_json_ld = False
        self._h1_depth = 0
        self._h1_parts: list[str] = []
        self._json_parts: list[str] = []
        self._chars = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        attributes = {name.lower(): value for name, value in attrs if value is not None}
        if tag == "title":
            self._in_title = True
        elif tag == "h1":
            self._h1_depth += 1
        elif tag == "meta" and attributes.get("name", "").casefold() == "description":
            self.descriptions.append(_collapse(attributes.get("content", "")))
        elif tag == "link" and "canonical" in attributes.get("rel", "").casefold().split():
            self.canonicals.append(attributes.get("href", "").strip())
        elif tag == "script" and attributes.get("type", "").casefold() == "application/ld+json":
            if len(self.json_ld) < _MAX_JSON_LD_BLOCKS:
                self._in_json_ld = True
                self._json_parts = []

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "title":
            self._in_title = False
        elif tag == "h1" and self._h1_depth:
            self._h1_depth -= 1
            if self._h1_depth == 0:
                self.h1s.append(_collapse("".join(self._h1_parts)))
                self._h1_parts = []
        elif tag == "script" and self._in_json_ld:
            self._in_json_ld = False
            self.json_ld.append("".join(self._json_parts))

    def handle_data(self, data: str) -> None:
        self._chars += len(data)
        if self._chars > 4_000_000:
            return
        if self._in_title:
            self.title_parts.append(data)
        if self._h1_depth:
            self._h1_parts.append(data)
        if self._in_json_ld:
            self._json_parts.append(data)


class FallbackVerifier:
    """Verify with the REST executor, or the public page for types it does not support."""

    def __init__(self, primary: object, fallback: "PublicPageVerifier") -> None:
        self._primary = primary
        self._fallback = fallback

    def verify(self, proposal: SeoActionProposal) -> dict[str, str]:
        from reckon_core.wordpress_executor import UnsupportedWordPressAction

        try:
            return self._primary.verify(proposal)  # type: ignore[attr-defined]
        except UnsupportedWordPressAction:
            return self._fallback.verify(proposal)


class PublicPageVerifier:
    """Read-only verifier satisfying the verify part of the action executor contract."""

    binding_version = "public-page-verifier-v1"

    def __init__(
        self,
        resolver: DnsAddressLookup | None = None,
        transport: PinnedHttpTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        retry_delays: tuple[float, ...] = _RETRY_DELAYS_SECONDS,
    ) -> None:
        self._sleep = sleep
        self._retry_delays = retry_delays
        self._resolver = resolver or PublicDnsAddressResolver(timeout_seconds=1.0)
        self._transport = transport or StdlibPinnedHttpTransport()

    def execute(self, proposal: SeoActionProposal) -> dict[str, str]:
        raise UnsupportedVerification("The public page verifier never writes.")

    def rollback(self, proposal: SeoActionProposal) -> dict[str, str]:
        raise UnsupportedVerification("The public page verifier never writes.")

    def verify(self, proposal: SeoActionProposal) -> dict[str, str]:
        attempt = 0
        while True:
            try:
                return self._verify_once(proposal)
            except PublicVerificationFailed:
                if attempt >= len(self._retry_delays) or not self._retryable(proposal):
                    raise
                self._sleep(self._retry_delays[attempt])
                attempt += 1

    @staticmethod
    def _retryable(proposal: SeoActionProposal) -> bool:
        # Only a cache-style mismatch is worth retrying, not a disagreeing executor report.
        expected = proposal.proposed_state.get("value")
        reported = (proposal.executed_state or {}).get("value")
        return isinstance(expected, str) and bool(expected.strip()) and reported == expected

    def _verify_once(self, proposal: SeoActionProposal) -> dict[str, str]:
        if proposal.action_type not in VERIFIABLE_ACTION_TYPES:
            raise UnsupportedVerification(
                f"{proposal.action_type} cannot be verified from the public page."
            )
        expected = proposal.proposed_state.get("value")
        if not isinstance(expected, str) or not expected.strip():
            raise PublicVerificationFailed("The approved proposal has no value to verify.")
        reported = (proposal.executed_state or {}).get("value")
        if reported != expected:
            raise PublicVerificationFailed("The executor reported a different value.")

        host = urlsplit(proposal.target_url).hostname
        if host is None:
            raise PublicVerificationFailed("The proposal target URL has no host.")
        try:
            final_url, response, _ = _fetch_url(
                proposal.target_url,
                host,
                self._resolver,
                self._transport,
                monotonic() + _MAX_RUN_SECONDS,
                max_body_bytes=_MAX_BODY_BYTES,
            )
        except CrawlError as error:
            raise PublicVerificationFailed(f"The public page could not be read: {error}") from error
        if response.status_code != 200:
            raise PublicVerificationFailed(
                f"The public page returned HTTP {response.status_code}."
            )

        parser = _LivePageParser()
        parser.feed(response.body.decode("utf-8", errors="replace"))
        parser.close()
        observed = self._observe(proposal.action_type, parser, final_url, expected)
        return {
            "value": observed,
            "verification": "public-page-readback",
            "page_url": final_url,
        }

    @staticmethod
    def _observe(action_type: str, page: _LivePageParser, final_url: str, expected: str) -> str:
        want = _collapse(expected)
        if action_type == "meta_title":
            live = _collapse("".join(page.title_parts))
            if live != want and not (
                live.startswith(want) and _TITLE_SUFFIX.match(live[len(want):])
            ):
                raise PublicVerificationFailed("The live <title> does not match the approved value.")
            return live
        if action_type == "meta_description":
            if len(page.descriptions) != 1 or page.descriptions[0] != want:
                raise PublicVerificationFailed(
                    "The live page must serve exactly one matching meta description."
                )
            return page.descriptions[0]
        if action_type == "canonical":
            if len(page.canonicals) != 1:
                raise PublicVerificationFailed("The live page must serve exactly one canonical link.")
            live = urljoin(final_url, page.canonicals[0])
            if live != urljoin(final_url, expected.strip()):
                raise PublicVerificationFailed("The live canonical does not match the approved value.")
            return live
        if action_type == "heading":
            if len(page.h1s) != 1 or page.h1s[0] != want:
                raise PublicVerificationFailed(
                    "The live page must serve exactly one matching H1."
                )
            return page.h1s[0]
        # schema: the approved value is a JSON document that must appear as a JSON-LD block.
        try:
            wanted = json.loads(expected)
        except ValueError as error:
            raise PublicVerificationFailed("The approved schema value is not valid JSON.") from error
        for block in page.json_ld:
            try:
                if json.loads(block) == wanted:
                    return expected
            except ValueError:
                continue
        raise PublicVerificationFailed("No live JSON-LD block matches the approved schema.")
