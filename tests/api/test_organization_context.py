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
from reckon_core.oidc import IdentityProviderUnavailable, InvalidBearerToken
from reckon_core.persistence import (
    AuditEvent,
    Base,
    ExternalIdentity,
    NativeAccount,
    Organization,
    OrganizationCreationRequest,
    OrganizationMembership,
    User,
)
from reckon_core.tenancy import OrganizationRole


class StaticTokenVerifier:
    def verify(self, token: str) -> tuple[str, str]:
        if token == "provider-down":
            raise IdentityProviderUnavailable
        if token == "unmapped-identity":
            return "https://identity.example.test/", "unmapped-subject"
        if token != "verified-test-token":
            raise InvalidBearerToken
        return "https://identity.example.test/", "provider-subject-1"


@pytest.fixture
def organization_api() -> Iterator[tuple[FastAPI, sessionmaker[Session], UUID]]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)

    with factory() as session:
        user = User()
        organization = Organization(name="Tenant Alpha")
        session.add_all((user, organization))
        session.flush()
        organization_id = organization.id
        session.add_all(
            (
                ExternalIdentity(
                    issuer="https://identity.example.test/",
                    subject="provider-subject-1",
                    user_id=user.id,
                ),
                OrganizationMembership(
                    organization_id=organization.id,
                    user_id=user.id,
                    role=OrganizationRole.EDITOR,
                    is_active=True,
                ),
            )
        )
        session.commit()

    app = create_app(Settings(_env_file=None, environment="test"))
    app.state.token_verifier = StaticTokenVerifier()

    def override_session() -> Iterator[Session]:
        with factory() as request_session:
            yield request_session

    app.dependency_overrides[get_database_session] = override_session
    try:
        yield app, factory, organization_id
    finally:
        engine.dispose()


async def request_context(
    app: FastAPI,
    organization_id: UUID,
    token: str | None,
) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        headers = (
            {"Authorization": f"Bearer {token}"}
            if token is not None
            else {}
        )
        return await client.get(
            f"/api/v1/organizations/{organization_id}/context",
            headers=headers,
        )


async def request_readiness(app: FastAPI) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        return await client.get("/health/ready")


async def create_organization_request(
    app: FastAPI,
    name: str,
    idempotency_key: str | None,
) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        headers = {"Authorization": "Bearer verified-test-token"}
        if idempotency_key is not None:
            headers["Idempotency-Key"] = idempotency_key
        return await client.post(
            "/api/v1/organizations",
            json={"name": name},
            headers=headers,
        )


def test_organization_context_requires_bearer_authentication(
    organization_api: tuple[FastAPI, sessionmaker[Session], UUID],
) -> None:
    app, _, organization_id = organization_api

    response = asyncio.run(request_context(app, organization_id, None))

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_organization_context_reports_identity_provider_outage(
    organization_api: tuple[FastAPI, sessionmaker[Session], UUID],
) -> None:
    app, _, organization_id = organization_api

    response = asyncio.run(
        request_context(app, organization_id, "provider-down")
    )

    assert response.status_code == 503
    assert response.json() == {"detail": "Identity provider is unavailable."}


def test_organization_context_resolves_verified_identity_and_membership(
    organization_api: tuple[FastAPI, sessionmaker[Session], UUID],
) -> None:
    app, _, organization_id = organization_api

    response = asyncio.run(
        request_context(app, organization_id, "verified-test-token")
    )

    assert response.status_code == 200
    assert response.json() == {
        "organization_id": str(organization_id),
        "role": "editor",
    }


def test_organization_context_hides_unrelated_tenant(
    organization_api: tuple[FastAPI, sessionmaker[Session], UUID],
) -> None:
    app, _, _ = organization_api

    response = asyncio.run(
        request_context(app, uuid4(), "verified-test-token")
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Organization not found."}


def test_member_listing_is_manager_only_paginated_and_tenant_scoped(
    organization_api: tuple[FastAPI, sessionmaker[Session], UUID],
) -> None:
    app, factory, organization_id = organization_api
    with factory.begin() as session:
        identity = session.scalar(select(ExternalIdentity))
        assert identity is not None
        actor_id = identity.user_id
        member = User()
        outsider = User()
        other_org = Organization(name="Other organization")
        session.add_all((member, outsider, other_org))
        session.flush()
        member_id, outsider_id = member.id, outsider.id
        session.add_all((
            NativeAccount(user_id=member.id, email="member@example.com", password_hash="fixture"),
            OrganizationMembership(
                organization_id=organization_id, user_id=member.id,
                role=OrganizationRole.VIEWER, is_active=True,
            ),
            OrganizationMembership(
                organization_id=other_org.id, user_id=outsider.id,
                role=OrganizationRole.OWNER, is_active=True,
            ),
        ))

    async def run() -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test",
            headers={"Authorization": "Bearer verified-test-token"},
        ) as client:
            path = f"/api/v1/organizations/{organization_id}/members"
            assert (await client.get(path)).status_code == 403
            with factory.begin() as session:
                membership = session.get(OrganizationMembership, {
                    "organization_id": organization_id, "user_id": actor_id,
                })
                assert membership is not None
                membership.role = OrganizationRole.ADMIN
            first = await client.get(path, params={"limit": 1})
            assert first.status_code == 200 and first.headers["cache-control"] == "no-store"
            assert len(first.json()["items"]) == 1
            cursor = first.json()["next_cursor"]
            assert cursor is not None
            second = await client.get(path, params={"limit": 1, "after": cursor})
            assert second.status_code == 200 and second.json()["next_cursor"] is None
            items = first.json()["items"] + second.json()["items"]
            assert {item["user_id"] for item in items} == {str(actor_id), str(member_id)}
            assert all(item["user_id"] != str(outsider_id) for item in items)
            assert next(item for item in items if item["user_id"] == str(member_id))["email"] == "member@example.com"
            assert next(item for item in items if item["user_id"] == str(actor_id))["email"] is None
            assert (await client.get(f"/api/v1/organizations/{uuid4()}/members")).status_code == 404

    asyncio.run(run())


def test_organization_list_paginates_only_active_memberships(
    organization_api: tuple[FastAPI, sessionmaker[Session], UUID],
) -> None:
    app, factory, first_id = organization_api
    with factory() as session:
        identity = session.scalar(select(ExternalIdentity))
        assert identity is not None
        user_id = identity.user_id
        second, inactive, unrelated = (
            Organization(name="Second"), Organization(name="Inactive"),
            Organization(name="Other tenant"),
        )
        other_user = User()
        session.add_all((second, inactive, unrelated, other_user))
        session.flush()
        session.add_all((
            OrganizationMembership(
                organization_id=second.id, user_id=user_id,
                role=OrganizationRole.ADMIN, is_active=True,
            ),
            OrganizationMembership(
                organization_id=inactive.id, user_id=user_id,
                role=OrganizationRole.VIEWER, is_active=False,
            ),
            OrganizationMembership(
                organization_id=unrelated.id, user_id=other_user.id,
                role=OrganizationRole.OWNER, is_active=True,
            ),
        ))
        second_id = second.id
        session.commit()

    async def run() -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            path = "/api/v1/organizations"
            assert (await client.get(path)).status_code == 401
            assert (await client.get(path, headers={"Authorization": "Bearer verified-test-token"}, params={"limit": 51})).status_code == 422
            headers = {"Authorization": "Bearer verified-test-token"}
            first = await client.get(path, headers=headers, params={"limit": 1})
            assert first.status_code == 200 and first.headers["cache-control"] == "no-store"
            assert len(first.json()["items"]) == 1
            cursor = first.json()["next_cursor"]
            assert cursor is not None
            second_page = await client.get(path, headers=headers, params={"limit": 1, "after": cursor})
            assert second_page.status_code == 200
            assert second_page.json()["next_cursor"] is None
            rows = first.json()["items"] + second_page.json()["items"]
            assert {row["organization_id"] for row in rows} == {str(first_id), str(second_id)}
            assert {row["name"] for row in rows} == {"Tenant Alpha", "Second"}

    asyncio.run(run())


def test_authenticated_user_can_create_owned_organization(
    organization_api: tuple[FastAPI, sessionmaker[Session], UUID],
) -> None:
    app, factory, _ = organization_api

    response = asyncio.run(
        create_organization_request(app, "Tenant Beta", "create-beta-001")
    )

    assert response.status_code == 201
    assert response.json()["role"] == "owner"
    request_id = UUID(response.headers["x-request-id"])
    organization_id = UUID(response.json()["organization_id"])
    with factory() as session:
        assert session.scalar(
            select(func.count(Organization.id)).where(
                Organization.id == organization_id
            )
        ) == 1
        assert session.scalar(
            select(func.count(OrganizationCreationRequest.idempotency_key)).where(
                OrganizationCreationRequest.idempotency_key == "create-beta-001"
            )
        ) == 1
        audit_event = session.scalar(
            select(AuditEvent).where(AuditEvent.resource_id == organization_id)
        )
        assert audit_event is not None
        assert audit_event.action == "organization.created"
        assert audit_event.actor_user_id is not None
        assert audit_event.request_id == request_id
        assert audit_event.details == {"name": "Tenant Beta"}


def test_organization_creation_respects_database_foreign_keys(
    organization_api: tuple[FastAPI, sessionmaker[Session], UUID],
) -> None:
    app, factory, _ = organization_api
    with factory() as session:
        session.connection().exec_driver_sql("PRAGMA foreign_keys=ON")
    response = asyncio.run(
        create_organization_request(app, "Foreign key fixture", "create-foreign-key-001")
    )
    assert response.status_code == 201


def test_organization_creation_replays_idempotent_request(
    organization_api: tuple[FastAPI, sessionmaker[Session], UUID],
) -> None:
    app, factory, _ = organization_api

    first = asyncio.run(
        create_organization_request(app, "Tenant Beta", "create-beta-002")
    )
    replay = asyncio.run(
        create_organization_request(app, "Tenant Beta", "create-beta-002")
    )

    assert first.status_code == replay.status_code == 201
    assert first.json() == replay.json()
    with factory() as session:
        assert session.scalar(
            select(func.count(OrganizationCreationRequest.idempotency_key)).where(
                OrganizationCreationRequest.idempotency_key == "create-beta-002"
            )
        ) == 1
        assert session.scalar(
            select(func.count(AuditEvent.id)).where(
                AuditEvent.resource_id == UUID(first.json()["organization_id"])
            )
        ) == 1


def test_organization_creation_rejects_reused_key_with_different_payload(
    organization_api: tuple[FastAPI, sessionmaker[Session], UUID],
) -> None:
    app, factory, _ = organization_api

    first = asyncio.run(
        create_organization_request(app, "Tenant Beta", "create-beta-003")
    )
    conflicting = asyncio.run(
        create_organization_request(app, "Tenant Gamma", "create-beta-003")
    )

    assert first.status_code == 201
    assert conflicting.status_code == 409
    with factory() as session:
        assert session.scalar(
            select(func.count(OrganizationCreationRequest.idempotency_key)).where(
                OrganizationCreationRequest.idempotency_key == "create-beta-003"
            )
        ) == 1


def test_organization_creation_requires_idempotency_key(
    organization_api: tuple[FastAPI, sessionmaker[Session], UUID],
) -> None:
    app, _, _ = organization_api

    response = asyncio.run(
        create_organization_request(app, "Tenant Beta", None)
    )

    assert response.status_code == 422


def test_readiness_checks_the_configured_database_session(
    organization_api: tuple[FastAPI, sessionmaker[Session], UUID],
) -> None:
    app, _, _ = organization_api

    response = asyncio.run(request_readiness(app))

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_organization_context_rejects_invalid_bearer_token(
    organization_api: tuple[FastAPI, sessionmaker[Session], UUID],
) -> None:
    app, _, organization_id = organization_api

    response = asyncio.run(
        request_context(app, organization_id, "invalid-token")
    )

    assert response.status_code == 401


def test_organization_context_rejects_unmapped_external_identity(
    organization_api: tuple[FastAPI, sessionmaker[Session], UUID],
) -> None:
    app, _, organization_id = organization_api

    response = asyncio.run(
        request_context(app, organization_id, "unmapped-identity")
    )

    assert response.status_code == 401


def test_organization_context_rejects_inactive_membership(
    organization_api: tuple[FastAPI, sessionmaker[Session], UUID],
) -> None:
    app, factory, organization_id = organization_api
    with factory() as session:
        membership = session.scalar(
            select(OrganizationMembership).where(
                OrganizationMembership.organization_id == organization_id
            )
        )
        assert membership is not None
        membership.is_active = False
        session.commit()

    response = asyncio.run(
        request_context(app, organization_id, "verified-test-token")
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Organization not found."}
