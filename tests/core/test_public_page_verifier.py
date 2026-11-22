import json
from types import SimpleNamespace

import pytest

from reckon_core.crawler import HttpFetchResponse
from reckon_core.public_page_verifier import (
    PublicPageVerifier,
    PublicVerificationFailed,
    UnsupportedVerification,
)


class PublicResolver:
    def addresses(self, host: str) -> tuple[str, ...]:
        return ("93.184.216.34",)


class PrivateResolver:
    def addresses(self, host: str) -> tuple[str, ...]:
        return ("169.254.169.254",)


class Transport:
    def __init__(self, html: str, status: int = 200, headers: dict[str, str] | None = None):
        self.html, self.status, self.headers = html, status, headers or {}
        self.urls: list[str] = []

    def get(self, url, host, address, timeout_seconds, max_body_bytes):
        self.urls.append(url)
        return HttpFetchResponse(self.status, self.headers, self.html.encode())


def proposal(action_type: str, value: str, reported: str | None = None):
    return SimpleNamespace(
        action_type=action_type,
        target_url="https://staging.example.com/post/",
        proposed_state={"value": value},
        executed_state={"value": value if reported is None else reported},
    )


def verifier(html: str, resolver=None, **kwargs):
    transport = Transport(html, **kwargs)
    return (
        PublicPageVerifier(
            resolver or PublicResolver(), transport, sleep=lambda _: None, retry_delays=()
        ),
        transport,
    )


def test_verifies_title_description_canonical_and_h1() -> None:
    html = (
        "<html><head><title> New  title </title>"
        '<meta name="description" content="A  good description">'
        '<link rel="canonical" href="/post/"></head>'
        "<body><h1>Main <em>heading</em></h1></body></html>"
    )
    v, _ = verifier(html)
    assert v.verify(proposal("meta_title", "New title"))["value"] == "New title"
    assert v.verify(proposal("meta_description", "A good description"))["value"]
    assert v.verify(proposal("canonical", "https://staging.example.com/post/"))["value"]
    result = v.verify(proposal("heading", "Main heading"))
    assert result["verification"] == "public-page-readback"


def test_verifies_json_ld_by_structure() -> None:
    block = {"@type": "Article", "headline": "Hi"}
    html = f'<script type="application/ld+json">{json.dumps(block)}</script>'
    v, _ = verifier(html)
    assert v.verify(proposal("schema", json.dumps({"headline": "Hi", "@type": "Article"})))


@pytest.mark.parametrize(
    "action_type,value,html",
    [
        ("meta_title", "Wanted", "<title>Other</title>"),
        ("meta_description", "Wanted", '<meta name="description" content="Other">'),
        (
            "meta_description",
            "Wanted",
            '<meta name="description" content="Wanted"><meta name="description" content="Wanted">',
        ),
        ("canonical", "https://staging.example.com/a", '<link rel="canonical" href="/b">'),
        ("heading", "Wanted", "<h1>Wanted</h1><h1>Wanted</h1>"),
        ("schema", '{"a": 1}', '<script type="application/ld+json">{"a": 2}</script>'),
        ("schema", "not json", "<p>x</p>"),
    ],
)
def test_mismatch_never_verifies(action_type: str, value: str, html: str) -> None:
    v, _ = verifier(html)
    with pytest.raises(PublicVerificationFailed):
        v.verify(proposal(action_type, value))


def test_reported_value_must_equal_approved_value() -> None:
    v, transport = verifier("<title>Wanted</title>")
    with pytest.raises(PublicVerificationFailed):
        v.verify(proposal("meta_title", "Wanted", reported="Different"))
    assert transport.urls == []


def test_unsupported_types_non_200_and_private_dns_fail_closed() -> None:
    v, _ = verifier("<title>Wanted</title>")
    for kind in ("redirect", "internal_link", "other"):
        with pytest.raises(UnsupportedVerification):
            v.verify(proposal(kind, "x"))
    v, _ = verifier("<title>Wanted</title>", status=404)
    with pytest.raises(PublicVerificationFailed):
        v.verify(proposal("meta_title", "Wanted"))
    v, transport = verifier("<title>Wanted</title>", resolver=PrivateResolver())
    with pytest.raises(PublicVerificationFailed):
        v.verify(proposal("meta_title", "Wanted"))
    assert transport.urls == []


def test_cross_host_redirect_is_rejected_and_writes_are_unsupported() -> None:
    v, _ = verifier("", status=301, headers={"location": "https://evil.example.net/"})
    with pytest.raises(PublicVerificationFailed):
        v.verify(proposal("meta_title", "Wanted"))
    with pytest.raises(UnsupportedVerification):
        v.execute(proposal("meta_title", "Wanted"))
    with pytest.raises(UnsupportedVerification):
        v.rollback(proposal("meta_title", "Wanted"))


def test_title_template_suffix_is_accepted_only_after_the_approved_text() -> None:
    v, _ = verifier("<title>New title | Example Site</title>")
    assert v.verify(proposal("meta_title", "New title"))["value"] == "New title | Example Site"
    for live in ("Other New title | Example Site", "New titleXYZ", "New title"[:-1]):
        v, _ = verifier(f"<title>{live}</title>")
        with pytest.raises(PublicVerificationFailed):
            v.verify(proposal("meta_title", "New title"))


class SequenceTransport:
    def __init__(self, pages: list[str]):
        self.pages, self.calls = pages, 0

    def get(self, url, host, address, timeout_seconds, max_body_bytes):
        page = self.pages[min(self.calls, len(self.pages) - 1)]
        self.calls += 1
        return HttpFetchResponse(200, {}, page.encode())


def test_stale_cache_is_retried_then_verifies() -> None:
    delays: list[float] = []
    transport = SequenceTransport(["<title>Old</title>", "<title>New title</title>"])
    v = PublicPageVerifier(PublicResolver(), transport, sleep=delays.append, retry_delays=(2.0, 5.0))
    assert v.verify(proposal("meta_title", "New title"))["value"] == "New title"
    assert delays == [2.0] and transport.calls == 2


def test_persistent_mismatch_stops_after_bounded_retries_and_disagreement_is_not_retried() -> None:
    delays: list[float] = []
    transport = SequenceTransport(["<title>Old</title>"])
    v = PublicPageVerifier(PublicResolver(), transport, sleep=delays.append, retry_delays=(2.0, 5.0))
    with pytest.raises(PublicVerificationFailed):
        v.verify(proposal("meta_title", "New title"))
    assert delays == [2.0, 5.0] and transport.calls == 3
    with pytest.raises(PublicVerificationFailed):
        v.verify(proposal("meta_title", "New title", reported="Different"))
    assert transport.calls == 3
