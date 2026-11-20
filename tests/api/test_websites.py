import asyncio
from collections.abc import Iterator
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from reckon_api.config import Settings
from reckon_api.dependencies import get_database_session
from reckon_api.main import create_app
from reckon_core.crawler import CrawlDisallowed, CrawlResult, CrawlUnavailable
from reckon_core.dns import DnsTxtLookupUnavailable
from reckon_core.oidc import InvalidBearerToken
from reckon_core.persistence import (
    AuditEvent,
    Base,
    CrawlRun,
    ExternalIdentity,
    Organization,
    OrganizationMembership,
    User,
    Website,
    WebsiteCreationRequest,
)
from reckon_core.tenancy import OrganizationRole
from reckon_core.websites import website_verification_record_value


class StaticTokenVerifier:
    def verify(self, token: str) -> tuple[str, str]:
        if token not in {"owner-token", "editor-token", "unmapped-token"}:
            raise InvalidBearerToken
        subject = {
            "owner-token": "owner-subject",
            "editor-token": "editor-subject",
            "unmapped-token": "unmapped-subject",
        }[token]
        return "https://identity.example.test/", subject


class StaticDnsResolver:
    def __init__(self, records: tuple[str, ...] = ()) -> None:
        self._records = records
        self.last_name: str | None = None

    def records(self, name: str) -> tuple[str, ...]:
        self.last_name = name
        return self._records


class UnavailableDnsResolver:
    def records(self, _: str) -> tuple[str, ...]:
        raise DnsTxtLookupUnavailable


class StaticHomepageCrawler:
    def __init__(self, outcome: CrawlResult | Exception) -> None:
        self.outcome = outcome
        self.calls: list[tuple[str, str]] = []

    def crawl(self, scheme: str, host: str) -> CrawlResult:
        self.calls.append((scheme, host))
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


@pytest.fixture
def website_api() -> Iterator[tuple[FastAPI, sessionmaker[Session], UUID]]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)

    with factory() as session:
        owner = User()
        editor = User()
        organization = Organization(name="Website Tenant")
        session.add_all((owner, editor, organization))
        session.flush()
        organization_id = organization.id
        session.add_all(
            (
                ExternalIdentity(
                    issuer="https://identity.example.test/",
                    subject="owner-subject",
                    user_id=owner.id,
                ),
                ExternalIdentity(
                    issuer="https://identity.example.test/",
                    subject="editor-subject",
                    user_id=editor.id,
                ),
                OrganizationMembership(
                    organization_id=organization_id,
                    user_id=owner.id,
                    role=OrganizationRole.OWNER,
                    is_active=True,
                ),
                OrganizationMembership(
                    organization_id=organization_id,
                    user_id=editor.id,
                    role=OrganizationRole.EDITOR,
                    is_active=True,
                ),
            )
        )
        session.commit()

    app = create_app(Settings(_env_file=None, environment="test"))
    app.state.token_verifier = StaticTokenVerifier()
    app.state.dns_txt_resolver = StaticDnsResolver()

    def override_session() -> Iterator[Session]:
        with factory() as request_session:
            yield request_session

    app.dependency_overrides[get_database_session] = override_session
    try:
        yield app, factory, organization_id
    finally:
        engine.dispose()


async def website_request(
    app: FastAPI,
    method: str,
    path: str,
    token: str = "owner-token",
    body: dict[str, str] | None = None,
    idempotency_key: str | None = None,
) -> httpx.Response:
    headers = {"Authorization": f"Bearer {token}"}
    if idempotency_key is not None:
        headers["Idempotency-Key"] = idempotency_key
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        return await client.request(method, path, headers=headers, json=body)


def create_website(
    app: FastAPI,
    organization_id: UUID,
    url: str,
    key: str = "site-create-001",
    token: str = "owner-token",
) -> httpx.Response:
    return asyncio.run(
        website_request(
            app,
            "POST",
            f"/api/v1/organizations/{organization_id}/websites",
            token=token,
            body={"url": url},
            idempotency_key=key,
        )
    )


def register_verified_website(
    app: FastAPI,
    factory: sessionmaker[Session],
    organization_id: UUID,
    url: str = "https://crawl.example.com",
    key: str = "site-create-001",
) -> UUID:
    created = create_website(app, organization_id, url, key=key)
    website_id = UUID(created.json()["website_id"])
    with factory() as session:
        website = session.get(Website, website_id)
        assert website is not None
        website.is_verified = True
        session.commit()
    return website_id


def test_website_creation_returns_dns_challenge_and_audits_without_token(
    website_api: tuple[FastAPI, sessionmaker[Session], UUID],
) -> None:
    app, factory, organization_id = website_api

    response = create_website(app, organization_id, "HTTPS://Example.COM/")

    assert response.status_code == 201
    payload = response.json()
    assert payload["origin"] == "https://example.com"
    assert payload["verification_status"] == "pending"
    assert payload["dns_txt_name"] == "_reckon-verify.example.com"
    assert payload["dns_txt_value"].startswith("reckon-seo-verification=")
    with factory() as session:
        website = session.get(Website, UUID(payload["website_id"]))
        assert website is not None
        assert website.is_verified is False
        assert website.verification_token not in str(
            session.scalar(select(AuditEvent.details).where(AuditEvent.resource_id == website.id))
        )
        assert session.scalar(
            select(func.count(AuditEvent.id)).where(
                AuditEvent.resource_id == website.id
            )
        ) == 1


def test_website_creation_replays_idempotently_and_rejects_conflicting_payloads(
    website_api: tuple[FastAPI, sessionmaker[Session], UUID],
) -> None:
    app, factory, organization_id = website_api
    first = create_website(app, organization_id, "https://example.com", "site-create-002")
    replay = create_website(app, organization_id, "https://example.com/", "site-create-002")
    conflict = create_website(
        app,
        organization_id,
        "https://other.example.org",
        "site-create-002",
    )

    assert first.status_code == replay.status_code == 201
    assert first.json() == replay.json()
    assert conflict.status_code == 409
    with factory() as session:
        assert session.scalar(select(func.count(Website.id))) == 1
        assert session.scalar(select(func.count(WebsiteCreationRequest.idempotency_key))) == 1


def test_website_creation_blocks_duplicate_hosts_and_non_admin_members(
    website_api: tuple[FastAPI, sessionmaker[Session], UUID],
) -> None:
    app, _, organization_id = website_api
    first = create_website(app, organization_id, "https://example.com", "site-create-003")
    duplicate = create_website(app, organization_id, "http://example.com", "site-create-004")
    editor = create_website(
        app,
        organization_id,
        "https://editor-example.com",
        "site-create-005",
        token="editor-token",
    )

    assert first.status_code == 201
    assert duplicate.status_code == 409
    assert editor.status_code == 403


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1",
        "http://localhost",
        "https://user:pass@example.com",
        "https://example.com/private/path",
        "file://example.com",
    ],
)
def test_website_creation_rejects_non_public_or_non_origin_urls(
    website_api: tuple[FastAPI, sessionmaker[Session], UUID],
    url: str,
) -> None:
    app, _, organization_id = website_api

    response = create_website(app, organization_id, url)

    assert response.status_code == 422


def test_website_verification_requires_exact_dns_txt_record_and_is_idempotent(
    website_api: tuple[FastAPI, sessionmaker[Session], UUID],
) -> None:
    app, factory, organization_id = website_api
    created = create_website(app, organization_id, "https://example.com", "site-create-006")
    payload = created.json()
    resolver = StaticDnsResolver((payload["dns_txt_value"],))
    app.state.dns_txt_resolver = resolver
    path = (
        f"/api/v1/organizations/{organization_id}/websites/"
        f"{payload['website_id']}/verify"
    )

    verified = asyncio.run(website_request(app, "POST", path))
    repeated = asyncio.run(website_request(app, "POST", path))

    assert verified.status_code == repeated.status_code == 200
    assert verified.json() == {
        "website_id": payload["website_id"],
        "verification_status": "verified",
    }
    assert resolver.last_name == "_reckon-verify.example.com"
    with factory() as session:
        website = session.get(Website, UUID(payload["website_id"]))
        assert website is not None and website.is_verified
        assert session.scalar(
            select(func.count(AuditEvent.id)).where(
                AuditEvent.resource_id == website.id
            )
        ) == 2


def test_missing_dns_challenge_is_not_reported_as_verified(
    website_api: tuple[FastAPI, sessionmaker[Session], UUID],
) -> None:
    app, factory, organization_id = website_api
    created = create_website(app, organization_id, "https://example.com", "site-create-007")
    path = (
        f"/api/v1/organizations/{organization_id}/websites/"
        f"{created.json()['website_id']}/verify"
    )

    response = asyncio.run(website_request(app, "POST", path))

    assert response.status_code == 409
    with factory() as session:
        website = session.get(Website, UUID(created.json()["website_id"]))
        assert website is not None and not website.is_verified


def test_dns_provider_outage_is_reported_as_unavailable(
    website_api: tuple[FastAPI, sessionmaker[Session], UUID],
) -> None:
    app, _, organization_id = website_api
    created = create_website(app, organization_id, "https://example.com", "site-create-008")
    app.state.dns_txt_resolver = UnavailableDnsResolver()
    path = (
        f"/api/v1/organizations/{organization_id}/websites/"
        f"{created.json()['website_id']}/verify"
    )

    response = asyncio.run(website_request(app, "POST", path))

    assert response.status_code == 503
    assert response.json() == {"detail": "DNS verification is temporarily unavailable."}


def test_website_list_hides_pending_challenge_from_non_admin_members(
    website_api: tuple[FastAPI, sessionmaker[Session], UUID],
) -> None:
    app, _, organization_id = website_api
    create_website(app, organization_id, "https://example.com", "site-create-009")
    path = f"/api/v1/organizations/{organization_id}/websites"

    response = asyncio.run(website_request(app, "GET", path, token="editor-token"))

    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["dns_txt_value"] is None


def test_website_list_requires_active_organization_membership(
    website_api: tuple[FastAPI, sessionmaker[Session], UUID],
) -> None:
    app, _, _ = website_api
    unrelated_organization_id = uuid4()

    response = asyncio.run(
        website_request(
            app,
            "GET",
            f"/api/v1/organizations/{unrelated_organization_id}/websites",
        )
    )

    assert response.status_code == 404


def test_website_verification_is_owner_admin_only(
    website_api: tuple[FastAPI, sessionmaker[Session], UUID],
) -> None:
    app, _, organization_id = website_api
    created = create_website(app, organization_id, "https://example.com", "site-create-010")
    path = (
        f"/api/v1/organizations/{organization_id}/websites/"
        f"{created.json()['website_id']}/verify"
    )

    response = asyncio.run(
        website_request(app, "POST", path, token="editor-token")
    )

    assert response.status_code == 403


def test_unmapped_identity_cannot_register_a_website(
    website_api: tuple[FastAPI, sessionmaker[Session], UUID],
) -> None:
    app, _, organization_id = website_api

    response = create_website(
        app,
        organization_id,
        "https://example.com",
        token="unmapped-token",
    )

    assert response.status_code == 401


def test_member_crawl_is_persisted_audited_and_idempotent(
    website_api: tuple[FastAPI, sessionmaker[Session], UUID],
) -> None:
    app, factory, organization_id = website_api
    website_id = register_verified_website(app, factory, organization_id)
    crawler = StaticHomepageCrawler(
        CrawlResult(
            final_url="https://crawl.example.com/",
            status_code=200,
            content_type="text/html",
            bytes_read=18,
            title="Homepage",
            redirect_count=0,
        )
    )
    app.state.homepage_crawler = crawler
    path = (
        f"/api/v1/organizations/{organization_id}/websites/"
        f"{website_id}/crawl"
    )

    first = asyncio.run(
        website_request(
            app,
            "POST",
            path,
            token="editor-token",
            idempotency_key="crawl-run-001",
        )
    )
    replay = asyncio.run(
        website_request(
            app,
            "POST",
            path,
            token="editor-token",
            idempotency_key="crawl-run-001",
        )
    )
    other_website_id = register_verified_website(
        app,
        factory,
        organization_id,
        "https://othercrawl.example.com",
        key="site-create-002",
    )
    conflicting_replay = asyncio.run(
        website_request(
            app,
            "POST",
            (
                f"/api/v1/organizations/{organization_id}/websites/"
                f"{other_website_id}/crawl"
            ),
            token="editor-token",
            idempotency_key="crawl-run-001",
        )
    )

    assert first.status_code == 200
    assert first.json()["status"] == "completed"
    assert first.json()["title"] == "Homepage"
    assert replay.status_code == 200
    assert replay.json() == first.json()
    assert conflicting_replay.status_code == 409
    assert crawler.calls == [("https", "crawl.example.com")]
    with factory() as session:
        run = session.get(CrawlRun, UUID(first.json()["crawl_id"]))
        assert run is not None
        assert run.status == "completed"
        assert run.bytes_read == 18
        actions = session.scalars(
            select(AuditEvent.action).where(AuditEvent.resource_id == run.id)
        ).all()
        assert set(actions) == {"crawl.started", "crawl.completed"}


def test_member_can_list_paginated_crawl_history_for_own_website(
    website_api: tuple[FastAPI, sessionmaker[Session], UUID],
) -> None:
    app, factory, organization_id = website_api
    website_id = register_verified_website(app, factory, organization_id)
    other_website_id = register_verified_website(
        app,
        factory,
        organization_id,
        "https://othercrawl.example.com",
        key="site-create-002",
    )
    app.state.homepage_crawler = StaticHomepageCrawler(
        CrawlResult(
            final_url="https://crawl.example.com/",
            status_code=200,
            content_type="text/html",
            bytes_read=18,
            title="Homepage",
            redirect_count=0,
        )
    )
    crawl_path = (
        f"/api/v1/organizations/{organization_id}/websites/"
        f"{website_id}/crawl"
    )
    for key in ("crawl-history-001", "crawl-history-002", "crawl-history-003"):
        response = asyncio.run(
            website_request(
                app,
                "POST",
                crawl_path,
                token="editor-token",
                idempotency_key=key,
            )
        )
        assert response.status_code == 200

    history_path = (
        f"/api/v1/organizations/{organization_id}/websites/"
        f"{website_id}/crawls"
    )
    first_page = asyncio.run(
        website_request(app, "GET", f"{history_path}?limit=2", token="editor-token")
    )
    second_page = asyncio.run(
        website_request(
            app,
            "GET",
            f"{history_path}?limit=2&offset=2",
            token="editor-token",
        )
    )
    other_website_history = asyncio.run(
        website_request(
            app,
            "GET",
            (
                f"/api/v1/organizations/{organization_id}/websites/"
                f"{other_website_id}/crawls"
            ),
            token="editor-token",
        )
    )

    assert first_page.status_code == second_page.status_code == 200
    assert len(first_page.json()) == 2
    assert len(second_page.json()) == 1
    assert all(item["status"] == "completed" for item in first_page.json())
    assert all(item["website_id"] == str(website_id) for item in first_page.json())
    assert other_website_history.status_code == 200
    assert other_website_history.json() == []


def test_crawl_history_requires_active_tenant_membership_and_bounds_page_size(
    website_api: tuple[FastAPI, sessionmaker[Session], UUID],
) -> None:
    app, factory, organization_id = website_api
    website_id = register_verified_website(app, factory, organization_id)
    path = (
        f"/api/v1/organizations/{organization_id}/websites/"
        f"{website_id}/crawls"
    )

    unauthorized = asyncio.run(
        website_request(
            app,
            "GET",
            (
                f"/api/v1/organizations/{uuid4()}/websites/"
                f"{website_id}/crawls"
            ),
        )
    )
    invalid_limit = asyncio.run(
        website_request(app, "GET", f"{path}?limit=101")
    )
    missing_website = asyncio.run(
        website_request(
            app,
            "GET",
            (
                f"/api/v1/organizations/{organization_id}/websites/"
                f"{uuid4()}/crawls"
            ),
        )
    )

    assert unauthorized.status_code == 404
    assert invalid_limit.status_code == 422
    assert missing_website.status_code == 404


def test_failed_crawl_consumes_the_organization_daily_budget(
    website_api: tuple[FastAPI, sessionmaker[Session], UUID],
) -> None:
    app, factory, organization_id = website_api
    app.state.settings = Settings(
        _env_file=None,
        environment="test",
        crawl_daily_limit=1,
    )
    website_id = register_verified_website(app, factory, organization_id)
    crawler = StaticHomepageCrawler(CrawlUnavailable("network unavailable"))
    app.state.homepage_crawler = crawler
    path = (
        f"/api/v1/organizations/{organization_id}/websites/"
        f"{website_id}/crawl"
    )

    failed = asyncio.run(
        website_request(
            app,
            "POST",
            path,
            idempotency_key="crawl-budget-001",
        )
    )
    over_budget = asyncio.run(
        website_request(
            app,
            "POST",
            path,
            idempotency_key="crawl-budget-002",
        )
    )

    assert failed.status_code == 503
    assert over_budget.status_code == 429
    assert crawler.calls == [("https", "crawl.example.com")]
    with factory() as session:
        run = session.scalar(select(CrawlRun))
        assert run is not None
        assert run.status == "failed"
        assert run.error_code == "crawl_unavailable"
        assert session.scalar(select(func.count(CrawlRun.id))) == 1


def test_disallowed_crawl_is_audited_and_idempotently_replayed(
    website_api: tuple[FastAPI, sessionmaker[Session], UUID],
) -> None:
    app, factory, organization_id = website_api
    website_id = register_verified_website(app, factory, organization_id)
    crawler = StaticHomepageCrawler(CrawlDisallowed("robots.txt denied access"))
    app.state.homepage_crawler = crawler
    path = (
        f"/api/v1/organizations/{organization_id}/websites/"
        f"{website_id}/crawl"
    )

    first = asyncio.run(
        website_request(app, "POST", path, idempotency_key="crawl-policy-001")
    )
    replay = asyncio.run(
        website_request(app, "POST", path, idempotency_key="crawl-policy-001")
    )

    assert first.status_code == replay.status_code == 200
    assert first.json()["status"] == "disallowed"
    assert replay.json() == first.json()
    assert crawler.calls == [("https", "crawl.example.com")]
    with factory() as session:
        run = session.get(CrawlRun, UUID(first.json()["crawl_id"]))
        assert run is not None
        assert run.error_code == "robots_disallowed"


def test_unverified_website_cannot_be_crawled(
    website_api: tuple[FastAPI, sessionmaker[Session], UUID],
) -> None:
    app, factory, organization_id = website_api
    created = create_website(app, organization_id, "https://crawl.example.com")
    website_id = UUID(created.json()["website_id"])
    crawler = StaticHomepageCrawler(
        CrawlResult(
            final_url="https://crawl.example.com/",
            status_code=200,
            content_type="text/html",
            bytes_read=0,
            title=None,
            redirect_count=0,
        )
    )
    app.state.homepage_crawler = crawler

    response = asyncio.run(
        website_request(
            app,
            "POST",
            f"/api/v1/organizations/{organization_id}/websites/{website_id}/crawl",
            idempotency_key="crawl-pending-001",
        )
    )

    assert response.status_code == 409
    assert crawler.calls == []
    with factory() as session:
        assert session.scalar(select(func.count(CrawlRun.id))) == 0


def test_crawl_requires_active_tenant_membership(
    website_api: tuple[FastAPI, sessionmaker[Session], UUID],
) -> None:
    app, _, _ = website_api
    crawler = StaticHomepageCrawler(
        CrawlResult(
            final_url="https://crawl.example.com/",
            status_code=200,
            content_type="text/html",
            bytes_read=0,
            title=None,
            redirect_count=0,
        )
    )
    app.state.homepage_crawler = crawler
    organization_id = uuid4()

    response = asyncio.run(
        website_request(
            app,
            "POST",
            (
                f"/api/v1/organizations/{organization_id}/websites/"
                f"{uuid4()}/crawl"
            ),
            idempotency_key="crawl-tenant-001",
        )
    )

    assert response.status_code == 404
    assert crawler.calls == []
