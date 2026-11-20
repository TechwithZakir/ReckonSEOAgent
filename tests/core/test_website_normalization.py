import pytest

from reckon_core.websites import (
    InvalidWebsiteUrl,
    has_website_verification_record,
    normalize_website_url,
    website_verification_record_name,
    website_verification_record_value,
)


def test_normalizes_public_website_origins() -> None:
    website = normalize_website_url("HTTPS://BÜCHER.DE:443/")

    assert website.scheme == "https"
    assert website.host == "xn--bcher-kva.de"
    assert website.origin == "https://xn--bcher-kva.de"


@pytest.mark.parametrize(
    "value",
    [
        "https://user:password@example.com",
        "https://example.com/path",
        "https://example.com?query=1",
        "https://example.com/?",
        "https://example.com#fragment",
        "https://example.com/#",
        "ftp://example.com",
        "https://127.0.0.1",
        "http://[::1]",
        "http://localhost",
        "https://app.example.local",
        "https://example.com:8443",
        "https://-invalid.example",
    ],
)
def test_rejects_unsafe_or_non_origin_website_urls(value: str) -> None:
    with pytest.raises(InvalidWebsiteUrl):
        normalize_website_url(value)


def test_builds_exact_dns_txt_challenge() -> None:
    token = "random-challenge-token"
    record_name = website_verification_record_name("example.com")
    record_value = website_verification_record_value(token)

    assert record_name == "_reckon-verify.example.com"
    assert record_value == "reckon-seo-verification=random-challenge-token"
    assert has_website_verification_record(
        ('"other=value"', f'"{record_value}"'),
        token,
    )
    assert not has_website_verification_record(("reckon-seo-verification=wrong",), token)
