import asyncio
import hashlib
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from reckon_api.config import Settings
from reckon_api.dependencies import get_database_session
from reckon_api.main import create_app
from reckon_core.persistence import (
    Base,
    NativeAccount,
    NativeSession,
    Organization,
    PlatformAdministrator,
    User,
)
from reckon_core.native_auth import hash_password


@pytest.fixture
def platform_api() -> Iterator[tuple[FastAPI, sessionmaker[Session], str, str]]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory.begin() as session:
        admin = User()
        user = User()
        organization = Organization(name="Fixture")
        session.add_all((admin, user, organization))
        session.flush()
        admin_token = "rk1_" + "A" * 43
        user_token = "rk1_" + "B" * 43
        session.add_all((
            NativeAccount(
                user_id=admin.id,
                email="admin@example.com",
                password_hash=hash_password("fixture-password-123"),
                email_verified=True,
            ),
            NativeAccount(
                user_id=user.id,
                email="user@example.com",
                password_hash=hash_password("fixture-password-456"),
                email_verified=True,
            ),
            PlatformAdministrator(slot=1, user_id=admin.id),
            NativeSession(
                token_hash=hashlib.sha256(admin_token.encode()).hexdigest(),
                user_id=admin.id,
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            ),
            NativeSession(
                token_hash=hashlib.sha256(user_token.encode()).hexdigest(),
                user_id=user.id,
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            ),
        ))
    app = create_app(Settings(
        _env_file=None,
        environment="test",
        native_auth_enabled=True,
    ))

    def override() -> Iterator[Session]:
        with factory() as session:
            yield session

    app.dependency_overrides[get_database_session] = override
    try:
        yield app, factory, admin_token, user_token
    finally:
        engine.dispose()


def test_platform_summary_and_audit_require_platform_admin(
    platform_api: tuple[FastAPI, sessionmaker[Session], str, str],
) -> None:
    app, _, admin_token, user_token = platform_api

    async def run() -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            assert (await client.get("/api/v1/platform/summary")).status_code == 401
            denied = await client.get(
                "/api/v1/platform/summary",
                headers={"Authorization": f"Bearer {user_token}"},
            )
            assert denied.status_code == 403
            summary = await client.get(
                "/api/v1/platform/summary",
                headers={"Authorization": f"Bearer {admin_token}"},
            )
            assert summary.status_code == 200
            assert summary.headers["cache-control"] == "no-store"
            assert summary.json()["organization_count"] == 1
            assert summary.json()["active_member_count"] == 0
            assert summary.json()["native_account_count"] == 2
            assert summary.json()["active_native_session_count"] == 2

            events = await client.get(
                "/api/v1/platform/audit-events?limit=25",
                headers={"Authorization": f"Bearer {admin_token}"},
            )
            assert events.status_code == 200
            assert events.headers["cache-control"] == "no-store"
            assert events.json() == []
            assert (await client.get(
                "/api/v1/platform/audit-events",
                headers={"Authorization": f"Bearer {user_token}"},
            )).status_code == 403

    asyncio.run(run())
