import dns.exception
import pytest

from reckon_core.dns import DnsTxtLookupUnavailable, PublicDnsTxtResolver


class FakeTxtRecord:
    strings = (b"reckon-seo-", b"verification=token")


class FakeAnswer:
    rrset = object()

    def __iter__(self):
        return iter((FakeTxtRecord(),))


class FakeResolver:
    def __init__(self, answer: FakeAnswer | None = None) -> None:
        self.answer = answer
        self.arguments: tuple[object, ...] | None = None
        self.options: dict[str, object] | None = None

    def resolve(self, *args: object, **kwargs: object) -> FakeAnswer:
        self.arguments = args
        self.options = kwargs
        if self.answer is None:
            raise dns.exception.Timeout
        return self.answer


def test_txt_resolver_joins_chunks_and_disables_search_suffixes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolver = FakeResolver(FakeAnswer())
    monkeypatch.setattr("dns.resolver.Resolver", lambda: resolver)

    records = PublicDnsTxtResolver(timeout_seconds=2.0).records(
        "_reckon-verify.example.com"
    )

    assert records == ("reckon-seo-verification=token",)
    assert resolver.arguments == ("_reckon-verify.example.com", "TXT")
    assert resolver.options == {
        "lifetime": 2.0,
        "raise_on_no_answer": False,
        "search": False,
    }


def test_txt_resolver_surfaces_dns_timeouts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolver = FakeResolver()
    monkeypatch.setattr("dns.resolver.Resolver", lambda: resolver)

    with pytest.raises(DnsTxtLookupUnavailable):
        PublicDnsTxtResolver().records("_reckon-verify.example.com")
