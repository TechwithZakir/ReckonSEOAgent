import asyncio
import base64
import hashlib
import json
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone

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
from reckon_core.crawler import HomepageCrawler, HttpFetchResponse
from reckon_core.persistence import (
    AuditEvent,
    Base,
    NativeAccount,
    NativeSession,
    Organization,
    OrganizationMembership,
    SeoActionProposal,
    User,
    Website,
)
from reckon_core.tenancy import OrganizationRole

ENCRYPTION_KEY = base64.urlsafe_b64encode(b"a" * 32).decode()
OWNER = "rk1_" + "O" * 43
VIEWER = "rk1_" + "V" * 43
PAGE = (
    '<html lang="en"><head><meta name="viewport" content="width=device-width"></head>'
    "<body><h1>Handmade ceramics</h1><p>We make mugs and bowls by hand in small batches.</p>"
    "</body></html>"
)


class Resolver:
    def addresses(self, host: str) -> tuple[str, ...]:
        return ("93.184.216.34",)


class SiteTransport:
    def get(self, url, host, address, timeout_seconds, max_body_bytes):
        if url.endswith("/robots.txt"):
            return HttpFetchResponse(404, {}, b"")
        return HttpFetchResponse(200, {"content-type": "text/html"}, PAGE.encode())


@pytest.fixture
def env() -> Iterator[tuple[FastAPI, sessionmaker[Session], object, object]]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory.begin() as session:
        owner, viewer, org = User(), User(), Organization(name="Draft API")
        session.add_all((owner, viewer, org))
        session.flush()
        rows = [
            NativeAccount(user_id=owner.id, email="o-draft@example.com", password_hash="x", email_verified=True),
            NativeAccount(user_id=viewer.id, email="v-draft@example.com", password_hash="x", email_verified=True),
            OrganizationMembership(organization_id=org.id, user_id=owner.id,
                                   role=OrganizationRole.OWNER, is_active=True),
            OrganizationMembership(organization_id=org.id, user_id=viewer.id,
                                   role=OrganizationRole.VIEWER, is_active=True),
        ]
        for token, user in ((OWNER, owner), (VIEWER, viewer)):
            rows.append(NativeSession(
                token_hash=hashlib.sha256(token.encode()).hexdigest(), user_id=user.id,
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1)))
        site = Website(organization_id=org.id, host="example.com", scheme="https",
                       is_verified=True, verification_token="t")
        unverified = Website(organization_id=org.id, host="pending.example.org", scheme="https",
                             is_verified=False, verification_token="u")
        session.add_all(rows + [site, unverified])
        session.flush()
        ids = (org.id, site.id, unverified.id)
    app = create_app(Settings(
        _env_file=None, environment="test", native_auth_enabled=True,
        credential_encryption_key=SecretStr(ENCRYPTION_KEY)))
    app.state.homepage_crawler = HomepageCrawler(resolver=Resolver(), transport=SiteTransport())
    app.state.model_test_resolver = Resolver()
    app.dependency_overrides[get_database_session] = lambda: (yield from iter_session(factory))
    yield app, factory, ids[0], (ids[1], ids[2])
    engine.dispose()


def iter_session(factory: sessionmaker[Session]) -> Iterator[Session]:
    with factory() as session:
        yield session


def provider_replying(text: str) -> httpx.MockTransport:
    def handle(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=httpx.ByteStream(json.dumps({
            "status": "completed",
            "output": [{"type": "message", "role": "assistant",
                        "content": [{"type": "output_text", "text": text}]}],
            "usage": {"input_tokens": 120, "output_tokens": 30},
        }).encode()))
    return httpx.MockTransport(handle)


def call(app: FastAPI, method: str, path: str, token: str = OWNER,
         body: dict | None = None, key: str | None = None) -> httpx.Response:
    headers = {"Authorization": f"Bearer {token}"}
    if key:
        headers["Idempotency-Key"] = key

    async def send() -> httpx.Response:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
            return await c.request(method, path, headers=headers, json=body)

    return asyncio.run(send())


def setup_ai(app: FastAPI, org, reply: str) -> None:
    app.state.model_test_transport = provider_replying(reply)
    saved = call(app, "PUT", f"/api/v1/organizations/{org}/ai-settings", body={
        "provider": "openai", "model": "fixture-model", "api_key": "test-key-not-a-real-credential"})
    assert saved.status_code == 200


GOOD = json.dumps({"value": "Handmade Ceramic Mugs and Bowls | Example",
                   "rationale": "Matches the page H1 and content."})


def drafts(org, site) -> str:
    return f"/api/v1/organizations/{org}/websites/{site}/fix-drafts"


def test_draft_becomes_an_approval_gated_proposal(env) -> None:
    app, factory, org, (site, _) = env
    setup_ai(app, org, GOOD)
    response = call(app, "POST", drafts(org, site), body={
        "field": "meta_title", "target_url": "https://example.com/"}, key="draft-key-0001")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "proposed" and body["risk"] == "low"
    assert body["proposed_value"] == "Handmade Ceramic Mugs and Bowls | Example"
    assert body["before_value"] == ""
    assert response.headers["cache-control"] == "no-store"
    assert "test-key-not-a-real-credential" not in response.text
    with factory() as session:
        proposal = session.scalar(select(SeoActionProposal))
        assert proposal.status == "proposed"  # nothing is applied without approval
        assert proposal.action_type == "meta_title"
        assert proposal.target_version.startswith("page:")
        assert proposal.proposed_state == {"value": "Handmade Ceramic Mugs and Bowls | Example"}
        actions = [e.action for e in session.scalars(select(AuditEvent))]
        assert "agent.run.completed" in actions and "seo_action.proposed" in actions
    listed = call(app, "GET", f"/api/v1/organizations/{org}/seo-actions")
    assert listed.status_code == 200 and len(listed.json()) == 1


def test_wordpress_identity_is_stored_when_supplied(env) -> None:
    app, factory, org, (site, _) = env
    setup_ai(app, org, GOOD)
    response = call(app, "POST", drafts(org, site), body={
        "field": "meta_title", "target_url": "https://example.com/",
        "wp_type": "pages", "wp_id": "42", "wp_modified_gmt": "2026-11-20T10:00:00"}, key="draft-key-0002")
    assert response.status_code == 200
    with factory() as session:
        proposal = session.scalar(select(SeoActionProposal))
        assert proposal.before_state["wp_id"] == "42"
        assert proposal.target_version == "2026-11-20T10:00:00"


def test_partial_wordpress_identity_is_rejected(env) -> None:
    app, _, org, (site, _) = env
    response = call(app, "POST", drafts(org, site), body={
        "field": "meta_title", "target_url": "https://example.com/", "wp_id": "42"}, key="draft-key-0003")
    assert response.status_code == 422


def test_viewers_other_hosts_and_unverified_sites_are_rejected_before_any_model_call(env) -> None:
    app, _, org, (site, unverified) = env
    setup_ai(app, org, GOOD)
    calls = {"n": 0}

    def count(_: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(500)

    app.state.model_test_transport = httpx.MockTransport(count)
    ok_body = {"field": "meta_title", "target_url": "https://example.com/"}
    assert call(app, "POST", drafts(org, site), VIEWER, ok_body, "draft-key-0004").status_code == 403
    assert call(app, "POST", drafts(org, site), body={
        "field": "meta_title", "target_url": "https://evil.example/"}, key="draft-key-0005").status_code == 422
    assert call(app, "POST", drafts(org, unverified), body={
        "field": "meta_title", "target_url": "https://pending.example.org/"}, key="draft-key-0006").status_code == 409
    assert call(app, "POST", drafts(org, site), OWNER, ok_body).status_code == 422  # missing key
    assert calls["n"] == 0


def test_unsafe_model_output_is_discarded_and_creates_no_proposal(env) -> None:
    app, factory, org, (site, _) = env
    setup_ai(app, org, json.dumps({"value": "Visit https://evil.example for cheap mugs today"}))
    response = call(app, "POST", drafts(org, site), body={
        "field": "meta_title", "target_url": "https://example.com/"}, key="draft-key-0007")
    assert response.status_code == 502
    assert "safety checks" in response.json()["detail"]
    with factory() as session:
        assert session.scalar(select(SeoActionProposal)) is None
        assert "agent.run.invalid_output" in [e.action for e in session.scalars(select(AuditEvent))]


def test_replaying_the_same_key_is_refused(env) -> None:
    app, _, org, (site, _) = env
    setup_ai(app, org, GOOD)
    body = {"field": "meta_title", "target_url": "https://example.com/"}
    assert call(app, "POST", drafts(org, site), body=body, key="draft-key-0008").status_code == 200
    assert call(app, "POST", drafts(org, site), body=body, key="draft-key-0008").status_code == 409


def test_missing_ai_settings_returns_a_clear_conflict(env) -> None:
    app, _, org, (site, _) = env
    response = call(app, "POST", drafts(org, site), body={
        "field": "meta_title", "target_url": "https://example.com/"}, key="draft-key-0009")
    assert response.status_code == 409
    assert "AI settings" in response.json()["detail"]
