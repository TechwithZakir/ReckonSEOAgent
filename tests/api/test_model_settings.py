import asyncio
import base64
import json
from collections.abc import Iterator
from datetime import datetime, timezone
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI
from pydantic import SecretStr
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from reckon_api.config import Settings
from reckon_api.dependencies import get_database_session
from reckon_api.main import create_app
from reckon_core.model_gateway import ModelGatewayRequest
from reckon_core.model_settings import (
    CredentialCipher, CredentialEncryptionUnavailable, SqlAlchemyModelSettingsRepository,
)
from reckon_core.model_providers import ProviderAdapter
from reckon_core.oidc import InvalidBearerToken
from reckon_core.persistence import (
    AuditEvent, Base, ExternalIdentity, Organization, OrganizationMembership,
    ModelUsageReservation, OrganizationModelSettings, User,
)
from reckon_core.tenancy import (
    AuthenticatedPrincipal, OrganizationRole, TenantAccessDenied, TenantContext,
)

TEST_ENCRYPTION_KEY = base64.urlsafe_b64encode(b"a" * 32).decode()
TEST_API_KEY = "test-key-not-a-real-credential"


class TokenVerifier:
    def verify(self, token: str) -> tuple[str, str]:
        if token not in {"owner", "editor", "other-owner"}:
            raise InvalidBearerToken
        return "https://identity.example.test/", token


@pytest.fixture
def api() -> Iterator[tuple[FastAPI, sessionmaker[Session], UUID, UUID]]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as session:
        owner, editor, other_owner = User(), User(), User()
        first, second = Organization(name="First"), Organization(name="Second")
        session.add_all((owner, editor, other_owner, first, second))
        session.flush()
        session.add_all(
            [
                ExternalIdentity(issuer="https://identity.example.test/", subject=subject, user_id=user.id)
                for subject, user in (("owner", owner), ("editor", editor), ("other-owner", other_owner))
            ]
            + [
                OrganizationMembership(organization_id=org.id, user_id=user.id, role=role, is_active=True)
                for org, user, role in (
                    (first, owner, OrganizationRole.OWNER),
                    (first, editor, OrganizationRole.EDITOR),
                    (second, other_owner, OrganizationRole.OWNER),
                )
            ]
        )
        first_id, second_id = first.id, second.id
        session.commit()
    app = create_app(Settings(
        _env_file=None, environment="test", credential_encryption_key=SecretStr(TEST_ENCRYPTION_KEY)
    ))
    app.state.token_verifier = TokenVerifier()

    def session_override() -> Iterator[Session]:
        with factory() as session:
            yield session

    app.dependency_overrides[get_database_session] = session_override
    try:
        yield app, factory, first_id, second_id
    finally:
        engine.dispose()


def request(
    app: FastAPI, organization_id: UUID, method: str, token: str = "owner",
    body: dict[str, object] | None = None,
) -> httpx.Response:
    async def send() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.request(
                method, f"/api/v1/organizations/{organization_id}/ai-settings",
                headers={"Authorization": f"Bearer {token}"}, json=body,
            )
    return asyncio.run(send())


def usage_request(
    app: FastAPI, organization_id: UUID, method: str, token: str = "owner",
    reservation_id: UUID | None = None, body: dict[str, object] | None = None,
) -> httpx.Response:
    async def send() -> httpx.Response:
        path = f"/api/v1/organizations/{organization_id}/ai-usage"
        if reservation_id is not None:
            path += f"/{reservation_id}/reconcile"
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.request(
                method, path,
                headers={"Authorization": f"Bearer {token}"}, json=body,
            )
    return asyncio.run(send())


def test_settings_are_encrypted_scoped_and_never_return_key(
    api: tuple[FastAPI, sessionmaker[Session], UUID, UUID],
) -> None:
    app, factory, first, second = api
    payload = {"provider": "openai", "model": "gpt-test", "api_key": TEST_API_KEY}
    saved = request(app, first, "PUT", body=payload)
    assert saved.status_code == 200
    assert saved.json() == {
        "configured": True, "provider": "openai", "model": "gpt-test",
        "endpoint_url": "https://api.openai.com/v1",
        "encryption_available": True,
    }
    assert TEST_API_KEY not in saved.text
    fetched = request(app, first, "GET")
    assert fetched.json() == saved.json()
    assert fetched.headers["cache-control"] == "no-store"
    assert TEST_API_KEY not in fetched.text
    assert request(app, first, "GET", "editor").status_code == 403
    assert request(app, first, "PUT", "editor", payload).status_code == 403
    assert request(app, first, "GET", "other-owner").status_code == 404
    assert request(app, second, "GET", "other-owner").json()["configured"] is False
    with factory() as session:
        stored = session.get(OrganizationModelSettings, first)
        assert stored is not None
        assert TEST_API_KEY.encode() not in stored.encrypted_key
        cipher = CredentialCipher(SecretStr(TEST_ENCRYPTION_KEY))
        assert cipher.decrypt(stored.encrypted_key, first, "openai").get_secret_value() == TEST_API_KEY
        with pytest.raises(CredentialEncryptionUnavailable):
            cipher.decrypt(stored.encrypted_key, second, "openai")
        with pytest.raises(CredentialEncryptionUnavailable):
            cipher.decrypt(stored.encrypted_key, first, "anthropic")
        events = session.scalars(select(AuditEvent)).all()
        assert len(events) == 1 and events[0].action == "model_settings.saved"
        assert TEST_API_KEY not in repr(events[0].details)


def test_replace_delete_and_validation_do_not_expose_secrets(
    api: tuple[FastAPI, sessionmaker[Session], UUID, UUID],
) -> None:
    app, factory, first, _ = api
    initial = {"provider": "openai", "model": "gpt-test", "api_key": TEST_API_KEY}
    assert request(app, first, "PUT", body=initial).status_code == 200
    assert request(app, first, "PUT", body={"provider": "openai", "model": "new-model"}).status_code == 200
    assert request(app, first, "PUT", body={"provider": "anthropic", "model": "claude-test"}).status_code == 409
    invalid = request(app, first, "PUT", body={"provider": "invalid", "model": "bad", "api_key": TEST_API_KEY})
    assert invalid.status_code == 422 and TEST_API_KEY not in invalid.text
    assert invalid.headers["cache-control"] == "no-store"
    changed = request(
        app, first, "PUT",
        body={"provider": "anthropic", "model": "claude-test", "api_key": "test-other-key"},
    )
    assert changed.status_code == 200 and changed.json()["provider"] == "anthropic"
    assert changed.json()["endpoint_url"] == "https://api.anthropic.com/v1"
    assert request(app, first, "DELETE", "editor").status_code == 403
    assert request(app, first, "DELETE").status_code == 204
    assert request(app, first, "GET").json()["configured"] is False
    with factory() as session:
        assert session.get(OrganizationModelSettings, first) is None


def test_custom_endpoint_is_tenant_scoped_preserved_and_defaults_on_provider_switch(
    api: tuple[FastAPI, sessionmaker[Session], UUID, UUID],
) -> None:
    app, factory, first, second = api
    response = request(app, first, "PUT", body={
        "provider": "openai", "model": "gpt-test", "api_key": TEST_API_KEY,
        "endpoint_url": "https://proxy.example.com/v1/",
    })
    assert response.status_code == 200
    assert response.json()["endpoint_url"] == "https://proxy.example.com/v1"
    updated = request(app, first, "PUT", body={"provider": "openai", "model": "new-model"})
    assert updated.json()["endpoint_url"] == "https://proxy.example.com/v1"
    assert request(app, second, "GET", "other-owner").json()["endpoint_url"] is None
    switched = request(app, first, "PUT", body={
        "provider": "anthropic", "model": "claude-test", "api_key": "test-key",
    })
    assert switched.json()["endpoint_url"] == "https://api.anthropic.com/v1"
    with factory() as session:
        stored = session.get(OrganizationModelSettings, first)
        assert stored is not None
        stored.endpoint_url = None
        session.commit()
    assert request(app, first, "GET").json()["endpoint_url"] == "https://api.anthropic.com/v1"


@pytest.mark.parametrize("endpoint", [
    "http://example.com/v1",
    "https://127.0.0.1/v1",
    "https://169.254.169.254/v1",
    "https://localhost/v1",
    "https://private.local/v1",
    "https://example.com:8443/v1",
    "https://user:password@example.com/v1",
    "https://example.com/v1?key=secret",
    "https://example.com/v1#secret",
    "https://example.com/v1/../admin",
    "https://example.com/v1/%2e%2e/admin",
])
def test_unsafe_model_endpoints_are_rejected_without_reflecting_input(
    api: tuple[FastAPI, sessionmaker[Session], UUID, UUID], endpoint: str,
) -> None:
    app, factory, first, _ = api
    response = request(app, first, "PUT", body={
        "provider": "openai", "model": "gpt-test", "api_key": TEST_API_KEY, "endpoint_url": endpoint,
    })
    assert response.status_code == 422
    assert TEST_API_KEY not in response.text and endpoint not in response.text
    with factory() as session:
        assert session.get(OrganizationModelSettings, first) is None


def test_save_fails_closed_without_valid_encryption_key(
    api: tuple[FastAPI, sessionmaker[Session], UUID, UUID],
) -> None:
    app, factory, first, _ = api
    app.state.settings.credential_encryption_key = None
    response = request(
        app, first, "PUT", body={"provider": "openai", "model": "gpt-test", "api_key": TEST_API_KEY}
    )
    assert response.status_code == 503 and TEST_API_KEY not in response.text
    assert request(app, first, "GET").json()["encryption_available"] is False
    with factory() as session:
        assert session.get(OrganizationModelSettings, first) is None


def test_staging_rejects_plaintext_credential_transport(
    api: tuple[FastAPI, sessionmaker[Session], UUID, UUID],
) -> None:
    app, factory, first, _ = api
    app.state.settings.environment = "staging"
    response = request(
        app, first, "PUT", body={"provider": "openai", "model": "gpt-test", "api_key": TEST_API_KEY}
    )
    assert response.status_code == 400
    assert TEST_API_KEY not in response.text
    with factory() as session:
        assert session.get(OrganizationModelSettings, first) is None


def test_encryption_rejects_bad_master_keys_and_tampered_ciphertext() -> None:
    with pytest.raises(CredentialEncryptionUnavailable):
        CredentialCipher(SecretStr("not-a-valid-key"))
    cipher = CredentialCipher(SecretStr(TEST_ENCRYPTION_KEY))
    organization_id = uuid4()
    encrypted = cipher.encrypt(SecretStr(TEST_API_KEY), organization_id, "openai")
    with pytest.raises(CredentialEncryptionUnavailable):
        cipher.decrypt(encrypted[:-1] + bytes([encrypted[-1] ^ 1]), organization_id, "openai")


def test_stale_manager_role_cannot_save_settings(
    api: tuple[FastAPI, sessionmaker[Session], UUID, UUID],
) -> None:
    _, factory, first, _ = api
    with factory() as session:
        identity = session.scalar(select(ExternalIdentity).where(ExternalIdentity.subject == "owner"))
        assert identity is not None
        context = TenantContext(
            AuthenticatedPrincipal(identity.user_id, identity.issuer, identity.subject),
            first, OrganizationRole.OWNER,
        )
        membership = session.get(OrganizationMembership, {"organization_id": first, "user_id": identity.user_id})
        assert membership is not None
        membership.role = OrganizationRole.EDITOR
        session.commit()
        with pytest.raises(TenantAccessDenied):
            SqlAlchemyModelSettingsRepository(session).save(
                context, uuid4(), "openai", "test-model", SecretStr(TEST_API_KEY),
                CredentialCipher(SecretStr(TEST_ENCRYPTION_KEY)),
            )
        session.rollback()
        assert session.get(OrganizationModelSettings, first) is None


class FixturePublicResolver:
    def addresses(self, host: str) -> tuple[str, ...]:
        return ("8.8.8.8",)


def test_ai_test_requires_manager_meters_usage_and_rejects_replay(
    api: tuple[FastAPI, sessionmaker[Session], UUID, UUID],
) -> None:
    app, factory, first, second = api
    app.state.model_test_resolver = FixturePublicResolver()
    calls: list[httpx.Request] = []

    def handle(outgoing: httpx.Request) -> httpx.Response:
        calls.append(outgoing)
        return httpx.Response(200, stream=httpx.ByteStream(json.dumps({
            "status": "completed", "output": [{
                "type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "OK"}]
            }], "usage": {"input_tokens": 10, "output_tokens": 2},
        }).encode()))

    app.state.model_test_transport = httpx.MockTransport(handle)
    assert request(app, first, "PUT", body={
        "provider": "openai", "model": "fixture-model", "api_key": TEST_API_KEY,
    }).status_code == 200

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            path = f"/api/v1/organizations/{first}/ai-settings/test"
            headers = {"Authorization": "Bearer owner", "Idempotency-Key": "ai-fixture-test-01"}
            assert (await client.post(path, headers={**headers, "Authorization": "Bearer editor"})).status_code == 403
            assert (await client.post(
                f"/api/v1/organizations/{second}/ai-settings/test", headers=headers,
            )).status_code == 404
            result = await client.post(path, headers=headers)
            assert result.status_code == 200
            assert result.json() == {
                "verified": True, "provider": "openai", "model": "fixture-model",
                "input_tokens": 10, "output_tokens": 2,
            }
            assert result.headers["cache-control"] == "no-store"
            assert TEST_API_KEY not in result.text
            assert (await client.post(path, headers=headers)).status_code == 409

    asyncio.run(run())
    assert len(calls) == 1
    with factory() as session:
        reservation = session.scalar(select(ModelUsageReservation))
        assert reservation is not None
        assert (reservation.status, reservation.input_tokens, reservation.output_tokens) == ("settled", 10, 2)


def test_unconfirmed_ai_test_reserves_budget_and_does_not_retry(
    api: tuple[FastAPI, sessionmaker[Session], UUID, UUID],
) -> None:
    app, factory, first, _ = api
    app.state.settings.ai_test_daily_token_limit = 640
    app.state.model_test_resolver = FixturePublicResolver()
    calls: list[httpx.Request] = []

    def fail(outgoing: httpx.Request) -> httpx.Response:
        calls.append(outgoing)
        return httpx.Response(401, text="provider-secret-error")

    app.state.model_test_transport = httpx.MockTransport(fail)
    assert request(app, first, "PUT", body={
        "provider": "anthropic", "model": "fixture-model", "api_key": TEST_API_KEY,
    }).status_code == 200

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            path = f"/api/v1/organizations/{first}/ai-settings/test"
            headers = {"Authorization": "Bearer owner", "Idempotency-Key": "ai-fixture-test-02"}
            result = await client.post(path, headers=headers)
            assert result.status_code == 502
            assert "provider-secret-error" not in result.text and TEST_API_KEY not in result.text
            assert (await client.post(path, headers=headers)).status_code == 409
            headers["Idempotency-Key"] = "ai-fixture-test-03"
            assert (await client.post(path, headers=headers)).status_code == 429

    asyncio.run(run())
    assert len(calls) == 1
    with factory() as session:
        reservation = session.scalar(select(ModelUsageReservation))
        assert reservation is not None and reservation.status == "reserved"


def test_ai_test_rejects_missing_or_changed_settings_before_dispatch(
    api: tuple[FastAPI, sessionmaker[Session], UUID, UUID], monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, factory, first, _ = api
    app.state.model_test_resolver = FixturePublicResolver()
    calls: list[httpx.Request] = []
    app.state.model_test_transport = httpx.MockTransport(
        lambda outgoing: calls.append(outgoing) or httpx.Response(500)
    )

    async def post(key: str) -> httpx.Response:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            return await client.post(
                f"/api/v1/organizations/{first}/ai-settings/test",
                headers={"Authorization": "Bearer owner", "Idempotency-Key": key},
            )

    assert asyncio.run(post("missing-settings-01")).status_code == 409
    assert request(app, first, "PUT", body={
        "provider": "openai", "model": "fixture-model", "api_key": TEST_API_KEY,
    }).status_code == 200
    original = ProviderAdapter.input_token_upper_bound

    def change_settings(adapter: ProviderAdapter, model_request: ModelGatewayRequest) -> int:
        with factory() as session:
            settings = session.get(OrganizationModelSettings, first)
            assert settings is not None
            settings.model = "changed-model"
            session.commit()
        return original(adapter, model_request)

    monkeypatch.setattr(ProviderAdapter, "input_token_upper_bound", change_settings)
    assert asyncio.run(post("changed-settings-01")).status_code == 409
    assert not calls
    with factory() as session:
        assert session.scalar(select(ModelUsageReservation)) is None


def test_ai_usage_lists_and_reconciles_only_prior_unknown_reservations(
    api: tuple[FastAPI, sessionmaker[Session], UUID, UUID],
) -> None:
    app, factory, first, second = api
    with factory() as session:
        identity = session.scalar(select(ExternalIdentity).where(ExternalIdentity.subject == "owner"))
        assert identity is not None
        reservation = ModelUsageReservation(
            organization_id=first,
            actor_user_id=identity.user_id,
            task_id=uuid4(),
            request_id=uuid4(),
            idempotency_key="usage-reconcile-001",
            request_hash="a" * 64,
            provider="openai",
            model="fixture-model",
            max_input_tokens=100,
            max_output_tokens=50,
            status="reserved",
            started_at=datetime.now(timezone.utc),
        )
        session.add(reservation)
        session.flush()
        session.add(
            AuditEvent(
                organization_id=first,
                actor_user_id=identity.user_id,
                action="model_usage.outcome_unknown",
                resource_type="model_usage",
                resource_id=reservation.id,
                request_id=uuid4(),
                details={"task_id": str(reservation.task_id), "reason": "adapter_error", "elapsed_ms": "10"},
            )
        )
        session.commit()
        reservation_id = reservation.id

    assert usage_request(app, first, "GET", "editor").status_code == 403
    cross_tenant = usage_request(app, second, "GET", "other-owner")
    assert cross_tenant.status_code == 200
    assert cross_tenant.json() == []
    listed = usage_request(app, first, "GET")
    assert listed.status_code == 200
    assert listed.headers["cache-control"] == "no-store"
    assert listed.json()[0]["status"] == "reserved"

    reconciled = usage_request(
        app,
        first,
        "POST",
        reservation_id=reservation_id,
        body={
            "input_tokens": 20,
            "output_tokens": 10,
            "verification_reference": "provider-verification-result-1",
        },
    )
    assert reconciled.status_code == 200
    assert reconciled.json()["status"] == "settled"
    assert reconciled.json()["input_tokens"] == 20
    replay = usage_request(
        app,
        first,
        "POST",
        reservation_id=reservation_id,
        body={
            "input_tokens": 20,
            "output_tokens": 10,
            "verification_reference": "provider-verification-result-1",
        },
    )
    assert replay.status_code == 409
