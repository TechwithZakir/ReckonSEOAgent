import asyncio
import hashlib
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier, Event
from uuid import uuid4

import pytest
import httpx
from sqlalchemy import create_engine, delete, inspect, select, text
from sqlalchemy.orm import sessionmaker

from reckon_api.config import Settings
from reckon_api.main import create_app
from reckon_core.native_auth import NativeAuthRepository, hash_password
from reckon_core.persistence import NativeAccount, NativeAuthRateLimit, NativeVerification, User


def test_postgres_concurrent_native_rate_limit_is_atomic() -> None:
    settings = Settings()
    if settings.database_url is None:
        pytest.skip("RECKON_DATABASE_URL is not configured.")
    engine = create_engine(settings.database_url.get_secret_value())
    identity = f"auth-test-{uuid4()}"
    bucket = hashlib.sha256(f"signup-ip:{identity}".encode()).hexdigest()
    factory = sessionmaker(engine)
    try:
        if not inspect(engine).has_table("auth_limits"):
            pytest.skip("Native authentication migration has not been applied.")
        with engine.connect() as connection:
            role = connection.execute(
                text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")
            ).one()
            assert role.rolsuper is False and role.rolbypassrls is False
        barrier = Barrier(8)

        def reserve() -> bool:
            with factory() as session:
                barrier.wait(timeout=10)
                allowed = NativeAuthRepository(session).rate_limit(
                    "signup-ip", identity, 3, timedelta(hours=1)
                )
                session.commit()
                return allowed

        with ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(lambda _: reserve(), range(8)))
        assert sum(results) == 3
    finally:
        if inspect(engine).has_table("auth_limits"):
            with factory.begin() as session:
                session.execute(delete(NativeAuthRateLimit).where(NativeAuthRateLimit.bucket_hash == bucket))
        engine.dispose()


def test_postgres_native_account_flow_with_fixture_mail() -> None:
    settings = Settings()
    if settings.database_url is None:
        pytest.skip("RECKON_DATABASE_URL is not configured.")
    engine = create_engine(settings.database_url.get_secret_value())
    email = f"auth-test-{uuid4()}@example.com"
    client_ip = f"auth-fixture-{uuid4()}"
    factory = sessionmaker(engine)

    class FixtureMailer:
        token: str | None = None

        def send_verification(self, recipient: str, token: str) -> None:
            assert recipient == email
            self.token = token

        def send_existing_account_notice(self, recipient: str) -> None:
            pytest.fail("A new fixture account must not already exist.")

    mailer = FixtureMailer()
    try:
        if not inspect(engine).has_table("auth_accounts"):
            pytest.skip("Native authentication migration has not been applied.")
        app = create_app(Settings(
            _env_file=None, environment="test", database_url=settings.database_url,
            native_auth_enabled=True,
        ))
        app.state.verification_mailer = mailer

        async def run() -> None:
            transport = httpx.ASGITransport(app=app, client=(client_ip, 12345))
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                assert (await client.post("/api/v1/auth/signup", json={"email": email})).status_code == 202
                assert mailer.token is not None
                password = "fixture-password-123"
                assert (await client.post(
                    "/api/v1/auth/verify", json={"token": mailer.token, "password": password}
                )).status_code == 204
                signed_in = await client.post(
                    "/api/v1/auth/signin", json={"email": email, "password": password}
                )
                assert signed_in.status_code == 200
                headers = {"Authorization": f"Bearer {signed_in.json()['access_token']}"}
                assert (await client.get("/api/v1/organizations", headers=headers)).json() == {
                    "items": [], "next_cursor": None,
                }
                assert (await client.post("/api/v1/auth/signout", headers=headers)).status_code == 204
                assert (await client.get("/api/v1/organizations", headers=headers)).status_code == 401

        asyncio.run(run())
    finally:
        if inspect(engine).has_table("auth_accounts"):
            with factory.begin() as session:
                user_id = session.scalar(select(NativeAccount.user_id).where(NativeAccount.email == email))
                if user_id:
                    session.execute(delete(User).where(User.id == user_id))
                session.execute(delete(NativeVerification).where(NativeVerification.email == email))
                buckets = [
                    hashlib.sha256(f"{action}:{identity}".encode()).hexdigest()
                    for action, identity in (
                        ("signup-ip", client_ip), ("signup-email", email), ("verify-ip", client_ip),
                        ("login-ip", client_ip), ("login-email", email),
                    )
                ]
                session.execute(delete(NativeAuthRateLimit).where(NativeAuthRateLimit.bucket_hash.in_(buckets)))
        engine.dispose()


def test_postgres_password_reset_serializes_with_sign_in() -> None:
    settings = Settings()
    if settings.database_url is None:
        pytest.skip("RECKON_DATABASE_URL is not configured.")
    engine = create_engine(settings.database_url.get_secret_value())
    if not inspect(engine).has_table("auth_reset"):
        engine.dispose()
        pytest.skip("Password reset migration has not been applied.")
    factory = sessionmaker(engine, expire_on_commit=False)
    email = f"auth-race-{uuid4()}@example.com"
    password = "fixture-password-123"
    signed_in = Event()
    allow_commit = Event()
    reset_started = Event()
    reset_finished = Event()
    user_id = None
    try:
        with factory.begin() as session:
            user = User()
            session.add(user)
            session.flush()
            user_id = user.id
            session.add(NativeAccount(user_id=user.id, email=email, password_hash=hash_password(password)))
        with factory.begin() as session:
            token = NativeAuthRepository(session).begin_password_reset(email)
            assert token is not None

        def login() -> str:
            with factory.begin() as session:
                session_token, _ = NativeAuthRepository(session).sign_in(email, password, uuid4())
                signed_in.set()
                if not allow_commit.wait(timeout=10):
                    raise TimeoutError("The fixture login was not released.")
                return session_token

        def reset() -> None:
            if not signed_in.wait(timeout=10):
                raise TimeoutError("The fixture login did not start.")
            reset_started.set()
            try:
                with factory.begin() as session:
                    NativeAuthRepository(session).complete_password_reset(
                        token, "updated-fixture-password-456", uuid4()
                    )
            finally:
                reset_finished.set()

        with ThreadPoolExecutor(max_workers=2) as executor:
            login_future = executor.submit(login)
            reset_future = executor.submit(reset)
            try:
                assert reset_started.wait(timeout=10)
                assert not reset_finished.wait(timeout=0.3)
            finally:
                allow_commit.set()
            session_token = login_future.result(timeout=10)
            reset_future.result(timeout=10)
        with factory() as session:
            assert NativeAuthRepository(session).authenticate(session_token) is None
    finally:
        allow_commit.set()
        if user_id is not None:
            with factory.begin() as session:
                session.execute(delete(User).where(User.id == user_id))
        engine.dispose()
