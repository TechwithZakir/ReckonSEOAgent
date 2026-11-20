import dns.exception
import pytest

from reckon_core.crawl_security import (
    CrawlTargetError,
    DnsAddressLookupUnavailable,
    PublicDnsAddressResolver,
    resolve_public_crawl_target,
)


class FakeAddressRecord:
    def __init__(self, value: str) -> None:
        self.value = value

    def __str__(self) -> str:
        return self.value


class FakeAnswer:
    def __init__(self, values: tuple[str, ...] = ()) -> None:
        self.rrset = object() if values else None
        self._records = tuple(FakeAddressRecord(value) for value in values)

    def __iter__(self):
        return iter(self._records)


class FakeResolver:
    def __init__(
        self,
        answers: dict[str, FakeAnswer] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.answers = answers or {}
        self.error = error
        self.calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def resolve(self, *args: object, **kwargs: object) -> FakeAnswer:
        self.calls.append((args, kwargs))
        if self.error:
            raise self.error
        return self.answers.get(str(args[1]), FakeAnswer())


class FakeAddressLookup:
    def __init__(self, answers: tuple[str, ...]) -> None:
        self.answers = answers
        self.host: str | None = None

    def addresses(self, host: str) -> tuple[str, ...]:
        self.host = host
        return self.answers


def test_public_dns_resolver_checks_both_families_without_search(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolver = FakeResolver(
        {
            "A": FakeAnswer(("93.184.216.34",)),
            "AAAA": FakeAnswer(("2606:2800:220:1:248:1893:25c8:1946",)),
        }
    )
    monkeypatch.setattr("dns.resolver.Resolver", lambda: resolver)

    addresses = PublicDnsAddressResolver(timeout_seconds=2.0).addresses(
        "example.com"
    )

    assert addresses == (
        "93.184.216.34",
        "2606:2800:220:1:248:1893:25c8:1946",
    )
    assert [call[0] for call in resolver.calls] == [
        ("example.com", "A"),
        ("example.com", "AAAA"),
    ]
    assert all(
        call[1]
        == {
            "lifetime": 2.0,
            "raise_on_no_answer": False,
            "search": False,
        }
        for call in resolver.calls
    )


def test_public_dns_resolver_reports_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolver = FakeResolver(error=dns.exception.Timeout)
    monkeypatch.setattr("dns.resolver.Resolver", lambda: resolver)

    with pytest.raises(DnsAddressLookupUnavailable):
        PublicDnsAddressResolver().addresses("example.com")


def test_target_accepts_only_public_answers_and_normalizes_host() -> None:
    lookup = FakeAddressLookup(("93.184.216.34", "2606:2800:220:1:248:1893:25c8:1946"))

    target = resolve_public_crawl_target("Example.COM.", lookup)

    assert lookup.host == "example.com"
    assert target.host == "example.com"
    assert target.addresses == lookup.answers


@pytest.mark.parametrize(
    "address",
    (
        "127.0.0.1",
        "10.0.0.8",
        "169.254.169.254",
        "::1",
        "fc00::1",
        "fe80::1",
        "::ffff:127.0.0.1",
    ),
)
def test_target_rejects_non_public_answers(address: str) -> None:
    with pytest.raises(CrawlTargetError, match="non-public"):
        resolve_public_crawl_target("example.com", FakeAddressLookup((address,)))


def test_target_rejects_mixed_public_and_private_answers() -> None:
    with pytest.raises(CrawlTargetError, match="non-public"):
        resolve_public_crawl_target(
            "example.com",
            FakeAddressLookup(("93.184.216.34", "192.168.1.1")),
        )


@pytest.mark.parametrize("host", ("127.0.0.1", "localhost", "example.com/path", ""))
def test_target_rejects_invalid_hosts(host: str) -> None:
    with pytest.raises(CrawlTargetError):
        resolve_public_crawl_target(host, FakeAddressLookup(("93.184.216.34",)))


def test_target_rejects_no_addresses_and_excessive_answers() -> None:
    with pytest.raises(CrawlTargetError, match="no address"):
        resolve_public_crawl_target("example.com", FakeAddressLookup(()))

    answers = tuple(f"93.184.216.{index}" for index in range(1, 34))
    with pytest.raises(CrawlTargetError, match="too many"):
        resolve_public_crawl_target("example.com", FakeAddressLookup(answers))
