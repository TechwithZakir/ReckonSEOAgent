import asyncio
import hashlib
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from reckon_api.config import Settings
from reckon_api.dependencies import get_database_session
from reckon_api.main import create_app
from reckon_api.native_mail import EmailDeliveryUnavailable
from reckon_core.persistence import (
    Base, NativeAccount, NativeSession, Organization, OrganizationChange,
    OrganizationInvitation, OrganizationMembership, User,
)
from reckon_core.tenancy import OrganizationRole


class FixtureMailer:
    def __init__(self) -> None:
        self.notifications: list[tuple[str, str]] = []
        self.fail = False

    def send_organization_invitation(self, email: str, name: str) -> None:
        self.notifications.append((email, name))
        if self.fail:
            raise EmailDeliveryUnavailable


@pytest.fixture
def management_api() -> Iterator[tuple[FastAPI, sessionmaker[Session], UUID, dict[str, tuple[UUID, str]], FixtureMailer]]:
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    people: dict[str, tuple[UUID, str]] = {}
    with factory.begin() as session:
        organization = Organization(name="Fixture org")
        session.add(organization)
        session.flush()
        org_id = organization.id
        for index, name in enumerate(("owner", "admin", "viewer", "recipient", "wrong", "unverified")):
            user = User()
            session.add(user)
            session.flush()
            token = "rk1_" + chr(65 + index) * 43
            people[name] = (user.id, token)
            session.add(NativeAccount(
                user_id=user.id, email=f"{name}@example.com", password_hash="fixture",
                email_verified=name != "unverified",
            ))
            session.add(NativeSession(
                token_hash=hashlib.sha256(token.encode()).hexdigest(), user_id=user.id,
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            ))
            if name in {"owner", "admin", "viewer"}:
                session.add(OrganizationMembership(
                    organization_id=org_id, user_id=user.id,
                    role=OrganizationRole(name), is_active=True,
                ))
    app = create_app(Settings(_env_file=None, environment="test", native_auth_enabled=True))
    mailer = FixtureMailer()
    app.state.verification_mailer = mailer

    def override() -> Iterator[Session]:
        with factory() as session:
            yield session

    app.dependency_overrides[get_database_session] = override
    try:
        yield app, factory, org_id, people, mailer
    finally:
        engine.dispose()


def headers(people: dict[str, tuple[UUID, str]], name: str, key: str = "fixture-key-1") -> dict[str, str]:
    return {"Authorization": f"Bearer {people[name][1]}", "Idempotency-Key": key}


def test_role_approval_is_bound_authorized_and_preserves_last_owner(
    management_api: tuple[FastAPI, sessionmaker[Session], UUID, dict[str, tuple[UUID, str]], FixtureMailer],
) -> None:
    app, factory, org, people, _ = management_api

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            path = f"/api/v1/organizations/{org}/changes"
            body = {"action": "role_change", "user_id": str(people["viewer"][0]), "role": "editor", "reason": "Grant editing"}
            assert (await client.post(path, headers=headers(people, "viewer"), json=body)).status_code == 403
            proposed = await client.post(path, headers=headers(people, "owner"), json=body)
            assert proposed.status_code == 200
            change = proposed.json()
            assert not change["approved"] and change["approval_hash"]
            assert (await client.post(path, headers=headers(people, "owner"), json={**body, "role": "admin"})).status_code == 409
            approve = f"{path}/{change['id']}/approve"
            assert (await client.post(approve, headers=headers(people, "admin"), json={
                "approval_hash": change["approval_hash"]
            })).status_code == 409
            assert (await client.post(approve, headers=headers(people, "owner"), json={
                "approval_hash": "0" * 64
            })).status_code == 409
            applied = await client.post(approve, headers=headers(people, "owner"), json={
                "approval_hash": change["approval_hash"]
            })
            assert applied.status_code == 200 and applied.json()["approved"] is True
            assert (await client.post(approve, headers=headers(people, "owner"), json={
                "approval_hash": change["approval_hash"]
            })).status_code == 200
            with factory() as session:
                member = session.get(OrganizationMembership, {"organization_id": org, "user_id": people["viewer"][0]})
                assert member is not None and member.role == OrganizationRole.EDITOR
            owner_body = {"action": "role_change", "user_id": str(people["owner"][0]), "role": "viewer", "reason": "Test last owner"}
            assert (await client.post(path, headers=headers(people, "admin", "fixture-key-2"), json=owner_body)).status_code == 403
            owner_change = (await client.post(path, headers=headers(people, "owner", "fixture-key-3"), json=owner_body)).json()
            denied = await client.post(f"{path}/{owner_change['id']}/approve", headers=headers(people, "owner"), json={
                "approval_hash": owner_change["approval_hash"]
            })
            assert denied.status_code == 409 and "last owner" in denied.text

    asyncio.run(run())


def test_approval_rejects_target_drift_and_expiry(
    management_api: tuple[FastAPI, sessionmaker[Session], UUID, dict[str, tuple[UUID, str]], FixtureMailer],
) -> None:
    app, factory, org, people, _ = management_api

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            path = f"/api/v1/organizations/{org}/changes"
            body = {"action": "role_change", "user_id": str(people["viewer"][0]), "role": "editor", "reason": "Grant editing"}
            first = (await client.post(path, headers=headers(people, "owner"), json=body)).json()
            with factory.begin() as session:
                member = session.get(OrganizationMembership, {"organization_id": org, "user_id": people["viewer"][0]})
                assert member is not None
                member.role = OrganizationRole.ADMIN
            with factory.begin() as session:
                member = session.get(OrganizationMembership, {"organization_id": org, "user_id": people["viewer"][0]})
                assert member is not None
                member.role = OrganizationRole.VIEWER
            assert (await client.post(f"{path}/{first['id']}/approve", headers=headers(people, "owner"), json={
                "approval_hash": first["approval_hash"]
            })).status_code == 409
            second = (await client.post(path, headers=headers(people, "owner", "fixture-key-2"), json=body)).json()
            with factory.begin() as session:
                change = session.get(OrganizationChange, UUID(second["id"]))
                assert change is not None
                change.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            assert (await client.post(f"{path}/{second['id']}/approve", headers=headers(people, "owner"), json={
                "approval_hash": second["approval_hash"]
            })).status_code == 409

    asyncio.run(run())


def test_invitation_requires_matching_verified_email_and_cannot_replay_after_revocation(
    management_api: tuple[FastAPI, sessionmaker[Session], UUID, dict[str, tuple[UUID, str]], FixtureMailer],
) -> None:
    app, factory, org, people, mailer = management_api

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            path = f"/api/v1/organizations/{org}/changes"
            body = {"action": "invite", "email": "recipient@example.com", "role": "viewer", "reason": "Invite teammate"}
            change = (await client.post(path, headers=headers(people, "admin"), json=body)).json()
            response = await client.post(f"{path}/{change['id']}/approve", headers=headers(people, "admin"), json={
                "approval_hash": change["approval_hash"]
            })
            assert response.status_code == 200 and response.json()["notification_status"] == "smtp_accepted"
            invite_id = response.json()["invitation_id"]
            assert mailer.notifications == [("recipient@example.com", "Fixture org")]
            assert (await client.get("/api/v1/invitations", headers=headers(people, "wrong"))).json() == []
            assert (await client.get("/api/v1/invitations", headers=headers(people, "unverified"))).json() == []
            invites = await client.get("/api/v1/invitations", headers=headers(people, "recipient"))
            assert len(invites.json()) == 1 and invites.headers["cache-control"] == "no-store"
            accept = f"/api/v1/invitations/{invite_id}/accept"
            assert (await client.post(accept, headers=headers(people, "wrong"))).status_code == 404
            assert (await client.post(accept, headers=headers(people, "recipient"))).status_code == 200
            assert (await client.post(accept, headers=headers(people, "recipient"))).status_code == 200
            with factory.begin() as session:
                member = session.get(OrganizationMembership, {
                    "organization_id": org, "user_id": people["recipient"][0],
                })
                assert member is not None
                member.is_active = False
            assert (await client.post(accept, headers=headers(people, "recipient"))).status_code == 404

    asyncio.run(run())


def test_invitation_smtp_failure_is_explicit_and_never_automatically_retried(
    management_api: tuple[FastAPI, sessionmaker[Session], UUID, dict[str, tuple[UUID, str]], FixtureMailer],
) -> None:
    app, factory, org, people, mailer = management_api
    mailer.fail = True

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            path = f"/api/v1/organizations/{org}/changes"
            change = (await client.post(path, headers=headers(people, "owner"), json={
                "action": "invite", "email": "recipient@example.com", "role": "editor", "reason": "Invite teammate"
            })).json()
            url = f"{path}/{change['id']}/approve"
            failed = await client.post(url, headers=headers(people, "owner"), json={"approval_hash": change["approval_hash"]})
            assert failed.status_code == 503 and "could not be confirmed" in failed.text
            replay = await client.post(url, headers=headers(people, "owner"), json={"approval_hash": change["approval_hash"]})
            assert replay.status_code == 200 and replay.json()["notification_status"] == "unconfirmed"
            assert len(mailer.notifications) == 1
            with factory() as session:
                assert session.scalar(select(OrganizationInvitation)) is not None

    asyncio.run(run())


def test_unconfigured_mailer_rolls_back_approval(
    management_api: tuple[FastAPI, sessionmaker[Session], UUID, dict[str, tuple[UUID, str]], FixtureMailer],
) -> None:
    app, factory, org, people, _ = management_api
    app.state.verification_mailer = None

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            path = f"/api/v1/organizations/{org}/changes"
            change = (await client.post(path, headers=headers(people, "owner"), json={
                "action": "invite", "email": "recipient@example.com", "role": "viewer", "reason": "Invite teammate"
            })).json()
            response = await client.post(f"{path}/{change['id']}/approve", headers=headers(people, "owner"), json={
                "approval_hash": change["approval_hash"]
            })
            assert response.status_code == 503
            assert response.headers["cache-control"] == "no-store"
            with factory() as session:
                stored = session.get(OrganizationChange, UUID(change["id"]))
                assert stored is not None and stored.approved_at is None
                assert session.scalar(select(OrganizationInvitation)) is None

    asyncio.run(run())
