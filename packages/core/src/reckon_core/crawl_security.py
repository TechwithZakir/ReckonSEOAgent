import ipaddress
import re
from dataclasses import dataclass
from typing import Protocol

import dns.exception
import dns.resolver


_dns_label = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_MAX_DNS_ADDRESSES = 32


class CrawlTargetError(ValueError):
    pass


class DnsAddressLookupUnavailable(RuntimeError):
    pass


class DnsAddressLookup(Protocol):
    def addresses(self, host: str) -> tuple[str, ...]:
        """Return A and AAAA answers for a hostname."""


@dataclass(frozen=True, slots=True)
class PublicCrawlTarget:
    host: str
    addresses: tuple[str, ...]


class PublicDnsAddressResolver:
    def __init__(self, timeout_seconds: float = 3.0) -> None:
        if timeout_seconds <= 0:
            raise ValueError("DNS timeout must be greater than zero.")
        self._timeout_seconds = timeout_seconds

    def addresses(self, host: str) -> tuple[str, ...]:
        resolver = dns.resolver.Resolver()
        found: list[str] = []
        for record_type in ("A", "AAAA"):
            try:
                answer = resolver.resolve(
                    host,
                    record_type,
                    lifetime=self._timeout_seconds,
                    raise_on_no_answer=False,
                    search=False,
                )
            except dns.resolver.NXDOMAIN:
                return ()
            except (dns.resolver.NoNameservers, dns.exception.Timeout) as error:
                raise DnsAddressLookupUnavailable(
                    "DNS address lookup could not be completed."
                ) from error

            if answer.rrset is not None:
                found.extend(str(record) for record in answer)
        return tuple(found)


def _normalize_hostname(host: str) -> str:
    if not host or host != host.strip() or "%" in host:
        raise CrawlTargetError("A valid public hostname is required.")

    canonical = host[:-1] if host.endswith(".") else host
    try:
        canonical = canonical.encode("idna").decode("ascii").lower()
    except UnicodeError as error:
        raise CrawlTargetError("A valid public hostname is required.") from error

    try:
        ipaddress.ip_address(canonical)
    except ValueError:
        pass
    else:
        raise CrawlTargetError("Crawling IP-literal hosts is not allowed.")

    labels = canonical.split(".")
    if (
        len(canonical) > 253
        or len(labels) < 2
        or any(not _dns_label.fullmatch(label) for label in labels)
    ):
        raise CrawlTargetError("A valid public hostname is required.")
    return canonical


def resolve_public_crawl_target(
    host: str,
    resolver: DnsAddressLookup,
) -> PublicCrawlTarget:
    canonical_host = _normalize_hostname(host)
    answers = resolver.addresses(canonical_host)
    if not answers:
        raise CrawlTargetError("The hostname has no address records.")
    if len(answers) > _MAX_DNS_ADDRESSES:
        raise CrawlTargetError("The hostname returned too many address records.")

    public_addresses: list[str] = []
    for answer in answers:
        try:
            address = ipaddress.ip_address(answer)
        except ValueError as error:
            raise CrawlTargetError("DNS returned an invalid IP address.") from error

        if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
            raise CrawlTargetError("DNS returned a non-public IP address.")
        if not address.is_global:
            raise CrawlTargetError("DNS returned a non-public IP address.")
        public_addresses.append(address.compressed)

    return PublicCrawlTarget(
        host=canonical_host,
        addresses=tuple(dict.fromkeys(public_addresses)),
    )
