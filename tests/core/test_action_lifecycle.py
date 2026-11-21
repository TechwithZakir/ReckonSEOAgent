from collections.abc import Iterator
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from reckon_core.action_executor import FixtureActionExecutor
from reckon_core.action_lifecycle import (
    ActionLifecycleConflict,
    SeoActionLifecycle,
)
from reckon_core.persistence import (
    AuditEvent,
    Base,
    Organization,
    OrganizationMembership,
    SeoActionProposal,
    User,
    Website,
)
from reckon_core.tenancy import (
    AuthenticatedPrincipal,
    OrganizationRole,
    TenantAccessDenied,
    TenantContext,
)


@pytest.fixture
def action_workspace() -> Iterator[tuple[sessionmaker[Session], TenantContext, UUID]]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as session:
        user = User()
        organization = Organization(name="Action test")
        session.add_all((user, organization))
        session.flush()
        session.add(
            OrganizationMembership(
                organization_id=organization.id,
                user_id=user.id,
                role=OrganizationRole.OWNER,
                is_active=True,
            )
        )
        website = Website(
            organization_id=organization.id,
            host="example.com",
            scheme="https",
            is_verified=True,
            verification_token="a" * 64,
        )
        session.add(website)
        session.flush()
        context = TenantContext(
            AuthenticatedPrincipal(user.id, "issuer", "subject"),
            organization.id,
            OrganizationRole.OWNER,
        )
        website_id = website.id
        session.commit()
    try:
        yield factory, context, website_id
    finally:
        engine.dispose()


def test_action_lifecycle_is_approved_executed_verified_and_rollbackable(
    action_workspace: tuple[sessionmaker[Session], TenantContext, UUID],
) -> None:
    factory, context, website_id = action_workspace
    with factory() as session:
        lifecycle = SeoActionLifecycle(session)
        proposal = lifecycle.propose(
            context,
            website_id,
            "meta_title",
            "https://example.com/",
            "v1",
            {"title": "Old title"},
            {"title": "New title"},
            "low",
            "Improve homepage title",
            "action-live-001",
            uuid4(),
        )
        session.commit()
        proposal_id = proposal.id
        assert proposal.status == "proposed"

        approved = lifecycle.approve(
            context,
            proposal_id,
            proposal.approval_hash,
            uuid4(),
        )
        session.commit()
        assert approved.status == "approved"

        executed = lifecycle.execute(
            context,
            proposal_id,
            FixtureActionExecutor(),
            uuid4(),
        )
        session.commit()
        assert executed.status == "verified"
        assert executed.executed_state["title"] == "New title"
        assert executed.verification_state["verification"] == "fixture-confirmed"

        rolled_back = lifecycle.rollback(
            context,
            proposal_id,
            FixtureActionExecutor(),
            uuid4(),
        )
        session.commit()
        assert rolled_back.status == "rolled_back"
        assert rolled_back.rollback_state["title"] == "Old title"

        actions = session.scalars(
            select(AuditEvent.action).where(
                AuditEvent.resource_id == proposal_id
            )
        ).all()
        assert {
            "seo_action.proposed",
            "seo_action.approved",
            "seo_action.verified",
            "seo_action.rolled_back",
        }.issubset(set(actions))


def test_action_lifecycle_rejects_hash_drift_expiry_and_unapproved_execution(
    action_workspace: tuple[sessionmaker[Session], TenantContext, UUID],
) -> None:
    factory, context, website_id = action_workspace
    with factory() as session:
        lifecycle = SeoActionLifecycle(session)
        proposal = lifecycle.propose(
            context,
            website_id,
            "canonical",
            "https://example.com/page",
            "v1",
            {"canonical": "https://example.com/old"},
            {"canonical": "https://example.com/new"},
            "high",
            "Fix canonical",
            "action-live-002",
            uuid4(),
        )
        session.commit()
        with pytest.raises(ActionLifecycleConflict):
            lifecycle.approve(context, proposal.id, "0" * 64, uuid4())
        with pytest.raises(ActionLifecycleConflict):
            lifecycle.execute(
                context,
                proposal.id,
                FixtureActionExecutor(),
                uuid4(),
            )


def test_action_target_must_match_website_and_execution_needs_verified_website(
    action_workspace: tuple[sessionmaker[Session], TenantContext, UUID],
) -> None:
    factory, context, website_id = action_workspace
    with factory() as session:
        lifecycle = SeoActionLifecycle(session)
        with pytest.raises(ValueError):
            lifecycle.propose(
                context, website_id, "meta_title", "https://other.example.net/",
                "v1", {"title": "a"}, {"title": "b"}, "low", "Wrong host", "action-live-003", uuid4(),
            )
        proposal = lifecycle.propose(
            context, website_id, "meta_title", "https://example.com/",
            "v1", {"title": "a"}, {"title": "b"}, "low", "Right host", "action-live-004", uuid4(),
        )
        lifecycle.approve(context, proposal.id, proposal.approval_hash, uuid4())
        session.get(Website, website_id).is_verified = False
        session.flush()
        with pytest.raises(ActionLifecycleConflict):
            lifecycle.execute(context, proposal.id, FixtureActionExecutor(), uuid4())
        assert proposal.status == "approved"


def test_documented_plugin_contract_is_verified_by_the_wordpress_read_back(
    action_workspace: tuple[sessionmaker[Session], TenantContext, UUID],
) -> None:
    import httpx
    from pydantic import SecretStr

    from reckon_core.wordpress_executor import WordPressActionExecutor

    live = {"title": "Old title", "modified": "2026-01-01T00:00:00"}

    def wordpress(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            live["title"] = __import__("json").loads(request.content)["title"]
        return httpx.Response(
            200, json={"title": {"raw": live["title"]}, "modified_gmt": live["modified"]}
        )

    class Resolver:
        def addresses(self, host: str) -> tuple[str, ...]:
            return ("93.184.216.34",)

    verifier = WordPressActionExecutor(
        "https://example.com", "fixture", SecretStr("fixture-password"),
        transport=httpx.MockTransport(wordpress), resolver=Resolver(),
    )
    factory, context, website_id = action_workspace
    with factory() as session:
        lifecycle = SeoActionLifecycle(session)
        proposal = lifecycle.propose(
            context, website_id, "heading", "https://example.com/post", "2026-01-01T00:00:00",
            {"wp_type": "posts", "wp_id": "42", "value": "Old title"}, {"value": "New title"},
            "low", "Clearer title", "plugin-contract-001", uuid4(), channel="mcp",
        )
        lifecycle.approve(context, proposal.id, proposal.approval_hash, uuid4())
        lifecycle.claim_external(context, proposal.id, uuid4())

        # The plugin reports a write that did not actually happen: Reckon must not verify it.
        lied = lifecycle.report_external(
            context, proposal.id, "executed", {"value": "New title"}, verifier, uuid4()
        )
        assert lied.status == "failed"

        proposal2 = lifecycle.propose(
            context, website_id, "heading", "https://example.com/post", "2026-01-01T00:00:00",
            {"wp_type": "posts", "wp_id": "42", "value": "Old title"}, {"value": "Better title"},
            "low", "Clearer title again", "plugin-contract-002", uuid4(), channel="mcp",
        )
        lifecycle.approve(context, proposal2.id, proposal2.approval_hash, uuid4())
        lifecycle.claim_external(context, proposal2.id, uuid4())
        live["title"] = "Better title"  # the plugin's real write
        done = lifecycle.report_external(
            context, proposal2.id, "executed", {"value": "Better title"}, verifier, uuid4()
        )
        assert done.status == "verified"
        assert done.verification_state["verification"] == "wordpress-independent-read"
