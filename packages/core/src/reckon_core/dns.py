from typing import Protocol

import dns.exception
import dns.resolver


class DnsTxtLookupUnavailable(RuntimeError):
    pass


class DnsTxtLookup(Protocol):
    def records(self, name: str) -> tuple[str, ...]:
        """Return TXT records for a DNS name."""


class PublicDnsTxtResolver:
    def __init__(self, timeout_seconds: float = 3.0) -> None:
        self._timeout_seconds = timeout_seconds

    def records(self, name: str) -> tuple[str, ...]:
        resolver = dns.resolver.Resolver()
        try:
            answer = resolver.resolve(
                name,
                "TXT",
                lifetime=self._timeout_seconds,
                raise_on_no_answer=False,
                search=False,
            )
        except dns.resolver.NXDOMAIN:
            return ()
        except (dns.resolver.NoNameservers, dns.exception.Timeout) as error:
            raise DnsTxtLookupUnavailable(
                "DNS TXT lookup could not be completed."
            ) from error

        if answer.rrset is None:
            return ()

        records: list[str] = []
        for record in answer:
            records.append(
                b"".join(record.strings).decode("utf-8", errors="replace")
            )
        return tuple(records)
