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
from reckon_core.dns import DnsTxtLookupUnavailable
from reckon_core.oidc import InvalidBearerToken
from reckon_core.persistence import (
    AuditEvent,
    Base,
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
