import asyncio
import base64
import hashlib
import json
import hmac
import struct
import time
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone

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
    Base, NativeAccount, NativeAuthEvent, NativePasswordReset, NativeSession, NativeVerification,
)
from reckon_core.native_auth import NativeAuthRepository, generate_mfa_secret, verify_totp
from uuid import uuid4

EMAIL = "fixture@example.com"
PASSWORD = "fixture-password-123"


class FixtureMailer:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []
        self.notices: list[str] = []
        self.resets: list[tuple[str, str]] = []
        self.reset_notices: list[str] = []
        self.fail = False

    def send_verification(self, email: str, token: str) -> None:
        if self.fail:
            raise EmailDeliveryUnavailable
        self.sent.append((email, token))

    def send_existing_account_notice(self, email: str) -> None:
        if self.fail:
            raise EmailDeliveryUnavailable
        self.notices.append(email)

    def send_password_reset(self, email: str, token: str) -> None:
        if self.fail:
            raise EmailDeliveryUnavailable
        self.resets.append((email, token))

    def send_password_reset_notice(self, email: str) -> None:
        if self.fail:
            raise EmailDeliveryUnavailable
        self.reset_notices.append(email)


@pytest.fixture
def native_api() -> Iterator[tuple[FastAPI, sessionmaker[Session], FixtureMailer]]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    app = create_app(Settings(
        _env_file=None,
        environment="test",
        native_auth_enabled=True,
        credential_encryption_key=base64.urlsafe_b64encode(b"a" * 32).decode(),
    ))
    mailer = FixtureMailer()
    app.state.verification_mailer = mailer

    def override_session() -> Iterator[Session]:
        with factory() as session:
            yield session

    app.dependency_overrides[get_database_session] = override_session
    try:
        yield app, factory, mailer
    finally:
        engine.dispose()


def totp_code(secret: str, now: int | None = None) -> str:
    key = base64.b32decode(secret + "=" * ((8 - len(secret) % 8) % 8), casefold=True)
    counter = int(time.time() if now is None else now) // 30
    digest = hmac.new(key, struct.pack(">Q", counter), "sha1").digest()
    offset = digest[-1] & 15
    binary = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return f"{binary % 1_000_000:06d}"


def test_totp_secret_generation_and_verification_are_typed() -> None:
    secret = generate_mfa_secret()
    now = int(time.time())
    code = totp_code(secret, now)
    assert verify_totp(secret, code, now)
    assert not verify_totp(secret, "12a456", now)
    assert not verify_totp(secret, "000000", now)


def test_native_signup_verification_session_and_revocation(
    native_api: tuple[FastAPI, sessionmaker[Session], FixtureMailer],
) -> None:
    app, factory, mailer = native_api

    async def run() -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            methods = await client.get("/api/v1/auth/methods")
            assert methods.json() == {
                "enabled": True, "signup_available": True, "recovery_available": True
            }
            requested = await client.post("/api/v1/auth/signup", json={"email": EMAIL.upper()})
            assert requested.status_code == 202
            assert requested.headers["cache-control"] == "no-store"
            assert len(mailer.sent) == 1 and mailer.sent[0][0] == EMAIL
            token = mailer.sent[0][1]
            assert token not in requested.text
            denied = await client.post("/api/v1/auth/signin", json={"email": EMAIL, "password": PASSWORD})
            assert denied.status_code == 401
            verified = await client.post("/api/v1/auth/verify", json={"token": token, "password": PASSWORD})
            assert verified.status_code == 204
            assert (await client.post(
                "/api/v1/auth/verify", json={"token": token, "password": "other-password-123"}
            )).status_code == 400
            signed_in = await client.post(
                "/api/v1/auth/signin", json={"email": EMAIL, "password": PASSWORD}
            )
            assert signed_in.status_code == 200 and signed_in.headers["cache-control"] == "no-store"
            access_token = signed_in.json()["access_token"]
            assert access_token.startswith("rk1_")
            headers = {"Authorization": f"Bearer {access_token}", "Idempotency-Key": "native-org-001"}
            created = await client.post("/api/v1/organizations", headers=headers, json={"name": "Native test"})
            assert created.status_code == 201 and created.json()["role"] == "owner"
            organization = created.json()["organization_id"]
            assert (await client.get(
                f"/api/v1/organizations/{organization}/context", headers=headers
            )).status_code == 200
            assert (await client.post("/api/v1/auth/signout", headers=headers)).status_code == 204
            assert (await client.get(
                f"/api/v1/organizations/{organization}/context", headers=headers
            )).status_code == 401
            repeated = await client.post("/api/v1/auth/signup", json={"email": EMAIL})
            assert repeated.status_code == 202 and mailer.notices == [EMAIL]
            with factory() as session:
                account = session.scalar(select(NativeAccount))
                stored_session = session.scalar(select(NativeSession))
                assert account is not None and PASSWORD not in account.password_hash
                assert account.password_hash.startswith("$argon2id$")
                assert stored_session is not None and access_token not in stored_session.token_hash
                assert stored_session.revoked_at is not None
                events = session.scalars(select(NativeAuthEvent)).all()
                assert {event.action for event in events} == {
                    "account.created", "session.created", "session.revoked"
                }
                assert PASSWORD not in repr(events) and access_token not in repr(events)

    asyncio.run(run())


def test_account_session_list_and_revocation_are_scoped(
    native_api: tuple[FastAPI, sessionmaker[Session], FixtureMailer],
) -> None:
    app, factory, mailer = native_api

    async def run() -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            signup = await client.post("/api/v1/auth/signup", json={"email": EMAIL})
            assert signup.status_code == 202
            token = mailer.sent[-1][1]
            verify = await client.post(
                "/api/v1/auth/verify",
                json={"token": token, "password": PASSWORD},
            )
            assert verify.status_code == 204
            first = await client.post(
                "/api/v1/auth/signin",
                json={"email": EMAIL, "password": PASSWORD},
            )
            second = await client.post(
                "/api/v1/auth/signin",
                json={"email": EMAIL, "password": PASSWORD},
            )
            first_token = first.json()["access_token"]
            second_token = second.json()["access_token"]
            assert first_token != second_token
            headers = {"Authorization": f"Bearer {second_token}"}
            sessions = await client.get("/api/v1/auth/sessions", headers=headers)
            assert sessions.status_code == 200
            rows = sessions.json()
            assert len(rows) == 2
            assert sum(row["is_current"] for row in rows) == 1
            first_row = next(row for row in rows if not row["is_current"])
            revoked = await client.delete(
                f"/api/v1/auth/sessions/{first_row['session_id']}",
                headers=headers,
            )
            assert revoked.status_code == 204
            remaining = await client.get("/api/v1/auth/sessions", headers=headers)
            assert remaining.status_code == 200
            assert len(remaining.json()) == 1
            first_headers = {"Authorization": f"Bearer {first_token}"}
            assert (await client.get("/api/v1/auth/sessions", headers=first_headers)).status_code == 401

    asyncio.run(run())


def test_native_mfa_enrollment_challenge_and_disable(
    native_api: tuple[FastAPI, sessionmaker[Session], FixtureMailer],
) -> None:
    app, factory, mailer = native_api

    async def run() -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            assert (await client.post("/api/v1/auth/signup", json={"email": EMAIL})).status_code == 202
            token = mailer.sent[-1][1]
            assert (await client.post(
                "/api/v1/auth/verify",
                json={"token": token, "password": PASSWORD},
            )).status_code == 204
            signed_in = await client.post(
                "/api/v1/auth/signin",
                json={"email": EMAIL, "password": PASSWORD},
            )
            access_token = signed_in.json()["access_token"]
            headers = {"Authorization": f"Bearer {access_token}"}
            assert (await client.get("/api/v1/auth/mfa", headers=headers)).json() == {
                "enabled": False,
                "recovery_codes_remaining": 0,
            }
            enrolled = await client.post("/api/v1/auth/mfa/enroll", headers=headers)
            assert enrolled.status_code == 200
            secret = enrolled.json()["secret"]
            assert enrolled.json()["otpauth_uri"].startswith("otpauth://totp/Reckon:")
            code = totp_code(secret)
            confirmed = await client.post(
                "/api/v1/auth/mfa/confirm",
                headers=headers,
                json={"code": code},
            )
            assert confirmed.status_code == 204
            assert (await client.get("/api/v1/auth/mfa", headers=headers)).json() == {
                "enabled": True,
                "recovery_codes_remaining": 0,
            }

            challenged = await client.post(
                "/api/v1/auth/signin",
                json={"email": EMAIL, "password": PASSWORD},
            )
            assert challenged.status_code == 200
            assert challenged.json()["mfa_required"] is True
            challenge = challenged.json()["challenge"]
            mfa_code = totp_code(secret)
            verified = await client.post(
                "/api/v1/auth/signin/mfa",
                json={"challenge": challenge, "code": mfa_code},
            )
            assert verified.status_code == 200
            assert "access_token" in verified.json()
            mfa_token = verified.json()["access_token"]
            disabled = await client.post(
                "/api/v1/auth/mfa/disable",
                headers={"Authorization": f"Bearer {mfa_token}"},
                json={"code": totp_code(secret)},
            )
            assert disabled.status_code == 204
            assert (await client.get(
                "/api/v1/auth/mfa",
                headers={"Authorization": f"Bearer {mfa_token}"},
            )).json() == {
                "enabled": False,
                "recovery_codes_remaining": 0,
            }

    asyncio.run(run())


def test_native_mfa_recovery_codes_are_one_time(
    native_api: tuple[FastAPI, sessionmaker[Session], FixtureMailer],
) -> None:
    app, factory, mailer = native_api

    async def run() -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            assert (await client.post("/api/v1/auth/signup", json={"email": EMAIL})).status_code == 202
            verify_token = mailer.sent[-1][1]
            assert (await client.post(
                "/api/v1/auth/verify",
                json={"token": verify_token, "password": PASSWORD},
            )).status_code == 204
            signed_in = await client.post(
                "/api/v1/auth/signin",
                json={"email": EMAIL, "password": PASSWORD},
            )
            access_token = signed_in.json()["access_token"]
            headers = {"Authorization": f"Bearer {access_token}"}

            enrolled = await client.post("/api/v1/auth/mfa/enroll", headers=headers)
            secret = enrolled.json()["secret"]
            code = totp_code(secret)
            assert (await client.post(
                "/api/v1/auth/mfa/confirm",
                headers=headers,
                json={"code": code},
            )).status_code == 204
            rotated = await client.post("/api/v1/auth/mfa/recovery-codes", headers=headers)
            assert rotated.status_code == 200
            codes = rotated.json()["codes"]
            assert len(codes) == 10

            challenged = await client.post(
                "/api/v1/auth/signin",
                json={"email": EMAIL, "password": PASSWORD},
            )
            challenge = challenged.json()["challenge"]
            recovery = await client.post(
                "/api/v1/auth/signin/mfa",
                json={"challenge": challenge, "code": codes[0]},
            )
            assert recovery.status_code == 200

            challenge_again = await client.post(
                "/api/v1/auth/signin",
                json={"email": EMAIL, "password": PASSWORD},
            )
            replay = await client.post(
                "/api/v1/auth/signin/mfa",
                json={"challenge": challenge_again.json()["challenge"], "code": codes[0]},
            )
            assert replay.status_code == 400

    asyncio.run(run())


def test_password_reset_revokes_sessions_and_other_links(
    native_api: tuple[FastAPI, sessionmaker[Session], FixtureMailer],
) -> None:
    app, _, mailer = native_api

    async def run() -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            assert (await client.post("/api/v1/auth/signup", json={"email": EMAIL})).status_code == 202
            assert (await client.post("/api/v1/auth/verify", json={
                "token": mailer.sent[-1][1], "password": PASSWORD
            })).status_code == 204
            login = await client.post("/api/v1/auth/signin", json={"email": EMAIL, "password": PASSWORD})
            old_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
            unknown = await client.post("/api/v1/auth/password-reset", json={"email": "unknown@example.com"})
            first = await client.post("/api/v1/auth/password-reset", json={"email": EMAIL})
            assert unknown.status_code == first.status_code == 202
            assert unknown.json() == first.json()
            assert mailer.reset_notices == ["unknown@example.com"]
            token = mailer.resets[-1][1]
            assert token not in first.text
            assert (await client.post("/api/v1/auth/password-reset", json={"email": EMAIL})).status_code == 202
            other_token = mailer.resets[-1][1]
            new_password = "new-fixture-password-456"
            assert (await client.post("/api/v1/auth/password-reset/confirm", json={
                "token": token, "password": new_password
            })).status_code == 204
            for replay in (token, other_token):
                response = await client.post("/api/v1/auth/password-reset/confirm", json={
                    "token": replay, "password": PASSWORD
                })
                assert response.status_code == 400
                assert replay not in response.text and PASSWORD not in response.text
            assert (await client.get("/api/v1/organizations", headers=old_headers)).status_code == 401
            assert (await client.post("/api/v1/auth/signin", json={"email": EMAIL, "password": PASSWORD})).status_code == 401
            assert (await client.post("/api/v1/auth/signin", json={"email": EMAIL, "password": new_password})).status_code == 200

    asyncio.run(run())


def test_password_reset_rejects_expired_tokens_and_reports_mail_failure(
    native_api: tuple[FastAPI, sessionmaker[Session], FixtureMailer],
) -> None:
    app, factory, mailer = native_api

    async def run() -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            assert (await client.post("/api/v1/auth/signup", json={"email": EMAIL})).status_code == 202
            assert (await client.post("/api/v1/auth/verify", json={
                "token": mailer.sent[-1][1], "password": PASSWORD
            })).status_code == 204
            mailer.fail = True
            failed = await client.post("/api/v1/auth/password-reset", json={"email": EMAIL})
            assert failed.status_code == 503 and EMAIL not in failed.text
            mailer.fail = False
            malformed = await client.post("/api/v1/auth/password-reset/confirm", json={
                "token": "private-short-token", "password": PASSWORD,
            })
            assert malformed.status_code == 422
            assert "private-short-token" not in malformed.text and PASSWORD not in malformed.text
            assert (await client.post("/api/v1/auth/password-reset", json={"email": EMAIL})).status_code == 202
            token = mailer.resets[-1][1]
            with factory.begin() as session:
                record = session.get(NativePasswordReset, hashlib.sha256(token.encode()).hexdigest())
                assert record is not None
                record.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            expired = await client.post("/api/v1/auth/password-reset/confirm", json={
                "token": token, "password": "other-fixture-password-456"
            })
            assert expired.status_code == 400
            assert (await client.post("/api/v1/auth/signin", json={"email": EMAIL, "password": PASSWORD})).status_code == 200

    asyncio.run(run())


def test_platform_administrator_is_separate_from_tenant_membership(
    native_api: tuple[FastAPI, sessionmaker[Session], FixtureMailer],
) -> None:
    app, factory, mailer = native_api
    with factory.begin() as session:
        NativeAuthRepository(session).bootstrap_platform_administrator(
            "admin@example.com", PASSWORD, uuid4()
        )

    async def run() -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            assert (await client.get("/api/v1/platform/access")).status_code == 401
            admin_login = await client.post(
                "/api/v1/auth/signin", json={"email": "admin@example.com", "password": PASSWORD}
            )
            admin_headers = {"Authorization": f"Bearer {admin_login.json()['access_token']}"}
            admin_access = await client.get("/api/v1/platform/access", headers=admin_headers)
            assert admin_access.json() == {"is_platform_admin": True}
            assert admin_access.headers["cache-control"] == "no-store"
            assert (await client.post("/api/v1/auth/signup", json={"email": EMAIL})).status_code == 202
            assert (await client.post("/api/v1/auth/verify", json={
                "token": mailer.sent[-1][1], "password": PASSWORD
            })).status_code == 204
            user_login = await client.post(
                "/api/v1/auth/signin", json={"email": EMAIL, "password": PASSWORD}
            )
            user_headers = {
                "Authorization": f"Bearer {user_login.json()['access_token']}",
                "Idempotency-Key": "other-tenant-test",
            }
            assert (await client.get("/api/v1/platform/access", headers=user_headers)).json() == {
                "is_platform_admin": False
            }
            created = await client.post("/api/v1/organizations", headers=user_headers, json={"name": "Other"})
            organization = created.json()["organization_id"]
            assert (await client.get(
                f"/api/v1/organizations/{organization}/context", headers=admin_headers
            )).status_code == 404

    asyncio.run(run())


def test_invalid_expired_and_unavailable_verification_are_safe(
    native_api: tuple[FastAPI, sessionmaker[Session], FixtureMailer],
) -> None:
    app, factory, mailer = native_api

    async def run() -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            invalid = await client.post(
                "/api/v1/auth/verify",
                json={"token": "sensitive-short-token", "password": PASSWORD},
            )
            assert invalid.status_code == 422
            assert "sensitive-short-token" not in invalid.text and PASSWORD not in invalid.text
            for path, body in (
                ("verify", {"token": "x" * 43, "password": "unpaired-surrogate-\ud800"}),
                ("signin", {"email": EMAIL, "password": "unpaired-surrogate-\ud800"}),
            ):
                response = await client.post(
                    f"/api/v1/auth/{path}", content=json.dumps(body).encode("ascii"),
                    headers={"Content-Type": "application/json"},
                )
                assert response.status_code == 422
                assert "unpaired-surrogate" not in response.text
            mailer.fail = True
            failed = await client.post("/api/v1/auth/signup", json={"email": EMAIL})
            assert failed.status_code == 503 and EMAIL not in failed.text
            mailer.fail = False
            assert (await client.post("/api/v1/auth/signup", json={"email": EMAIL})).status_code == 202
            token = mailer.sent[-1][1]
            with factory() as session:
                verification = session.scalar(
                    select(NativeVerification).order_by(NativeVerification.expires_at.desc())
                )
                assert verification is not None
                verification.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
                session.commit()
            expired = await client.post("/api/v1/auth/verify", json={"token": token, "password": PASSWORD})
            assert expired.status_code == 400
            with factory() as session:
                assert session.scalar(select(NativeAccount)) is None

    asyncio.run(run())


def test_native_auth_is_gated_and_signup_is_rate_limited(
    native_api: tuple[FastAPI, sessionmaker[Session], FixtureMailer],
) -> None:
    app, _, mailer = native_api

    async def run() -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            app.state.settings.native_auth_enabled = False
            assert (await client.post("/api/v1/auth/signup", json={"email": EMAIL})).status_code == 503
            app.state.settings.native_auth_enabled = True
            for _ in range(5):
                assert (await client.post("/api/v1/auth/signup", json={"email": EMAIL})).status_code == 202
            assert (await client.post("/api/v1/auth/signup", json={"email": EMAIL})).status_code == 429
            assert len(mailer.sent) == 5

    asyncio.run(run())
