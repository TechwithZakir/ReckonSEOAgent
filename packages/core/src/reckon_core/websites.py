import ipaddress
import re
from dataclasses import dataclass
from urllib.parse import urlsplit


_dns_label = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_non_public_suffixes = (
    ".localhost",
    ".local",
    ".localdomain",
    ".internal",
    ".test",
    ".invalid",
    ".example",
    ".onion",
    ".home.arpa",
)


class InvalidWebsiteUrl(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class NormalizedWebsite:
    scheme: str
    host: str

    @property
    def origin(self) -> str:
        return f"{self.scheme}://{self.host}"


def normalize_website_url(value: str) -> NormalizedWebsite:
    if not value or len(value) > 2048 or value != value.strip():
        raise InvalidWebsiteUrl("Enter a valid website origin.")

    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError as error:
        raise InvalidWebsiteUrl("Enter a valid website origin.") from error

    scheme = parsed.scheme.lower()
    if (
        scheme not in {"http", "https"}
        or not parsed.netloc
        or hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or "?" in value
        or "#" in value
    ):
        raise InvalidWebsiteUrl(
            "Use an HTTP(S) website origin without credentials, path, query, or fragment."
        )

    expected_port = 80 if scheme == "http" else 443
    if port is not None and port != expected_port:
        raise InvalidWebsiteUrl("Only the standard HTTP or HTTPS port is supported.")

    if hostname.endswith(".."):
        raise InvalidWebsiteUrl("Enter a valid public DNS hostname.")
    canonical_hostname = hostname[:-1] if hostname.endswith(".") else hostname
    try:
        host = canonical_hostname.encode("idna").decode("ascii").lower()
    except UnicodeError as error:
        raise InvalidWebsiteUrl("Enter a valid public DNS hostname.") from error
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise InvalidWebsiteUrl("Use a public DNS hostname, not an IP address.")

    if (
        len(host) > 253
        or host == "localhost"
        or host in {"home.arpa", "localdomain"}
        or any(host.endswith(suffix) for suffix in _non_public_suffixes)
    ):
        raise InvalidWebsiteUrl("Local and non-public hostnames cannot be added.")

    labels = host.split(".")
    if len(labels) < 2 or any(not _dns_label.fullmatch(label) for label in labels):
        raise InvalidWebsiteUrl("Enter a valid public DNS hostname.")
    if len(f"_reckon-verify.{host}") > 253:
        raise InvalidWebsiteUrl("The hostname is too long for DNS verification.")

    return NormalizedWebsite(scheme=scheme, host=host)


def website_verification_record_name(host: str) -> str:
    return f"_reckon-verify.{host}"


def website_verification_record_value(token: str) -> str:
    return f"reckon-seo-verification={token}"


def has_website_verification_record(
    records: tuple[str, ...],
    token: str,
) -> bool:
    expected = website_verification_record_value(token)
    return any(record.strip().strip('"') == expected for record in records)
