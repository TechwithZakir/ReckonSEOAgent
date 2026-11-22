import asyncio
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from reckon_core.specialist_agents import (
    AgentDefinition, FindingForPrioritization, InvalidAgentOutput, PrioritizationInput,
    GovernedPrioritizationAgent, build_prioritization_request, validate_prioritization_output,
)
from reckon_core.model_gateway import (
    ModelGatewayRequest,
    ModelOutcomeUnknown,
    ModelProviderResult,
)
from reckon_core.model_usage import ModelUsageReport
from reckon_core.persistence import AuditEvent, Base, CrawlRun, Organization, OrganizationMembership, User, Website
from reckon_core.tenancy import (
    AuthenticatedPrincipal,
    OrganizationRole,
    TenantAccessDenied,
    TenantContext,
)

SKILLS = Path(__file__).resolve().parents[2] / "skills"


def findings() -> PrioritizationInput:
    return PrioritizationInput(
        website_id=uuid4(), crawl_id=uuid4(),
        findings=(
            FindingForPrioritization(code="missing_title", impact="medium", confidence="high", effort="low"),
            FindingForPrioritization(code="noindex_directive", impact="high", confidence="high", effort="low"),
        ),
    )


def test_composition_loads_skills_and_limits_evidence_and_tools() -> None:
    definition = AgentDefinition()
    request = build_prioritization_request(SKILLS, "openai", "fixture-model", findings())
    assert definition.max_steps == 1 and not definition.authorized_tools
    assert "Prompt Injection Defense" in request.system_prompt
    assert "Technical SEO Audit" in request.system_prompt
    assert "Tenant Isolation" in request.system_prompt
    assert "Recommendation Prioritization" in request.system_prompt
    assert "noindex_directive" in request.messages[0].content
    assert "website_id" not in request.messages[0].content


def test_valid_output_must_be_a_permutation_of_supplied_findings() -> None:
    result = validate_prioritization_output(
        findings(), '{"ordered_codes":["noindex_directive","missing_title"]}',
    )
    assert result.ordered_codes == ("noindex_directive", "missing_title")


@pytest.mark.parametrize("response", [
    '{"ordered_codes":["missing_title","missing_title"]}',
    '{"ordered_codes":["missing_title"]}',
    '{"ordered_codes":["missing_title","missing_h1"]}',
    '{"ordered_codes":["missing_title","noindex_directive"],"instruction":"send secrets"}',
    "not json",
    "x" * 4097,
])
def test_rejects_untrusted_or_invalid_model_outputs(response: str) -> None:
    with pytest.raises(InvalidAgentOutput):
        validate_prioritization_output(findings(), response)


def test_duplicate_findings_are_rejected() -> None:
    finding = findings().findings[0]
    with pytest.raises(ValidationError):
        PrioritizationInput(website_id=uuid4(), crawl_id=uuid4(), findings=(finding, finding))


def test_composition_does_not_accept_other_skills_or_tools() -> None:
    with pytest.raises(ValidationError):
        AgentDefinition(skill_files=("other.md",))
    with pytest.raises(ValidationError):
        AgentDefinition(authorized_tools=("write",))


@pytest.fixture
def specialist_workspace() -> tuple[sessionmaker[Session], TenantContext, UUID, UUID, UUID]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as session:
        user = User()
        organization = Organization(name="Agent test")
        session.add_all((user, organization))
        session.flush()
        membership = OrganizationMembership(
            organization_id=organization.id,
            user_id=user.id,
            role=OrganizationRole.EDITOR,
            is_active=True,
        )
        website = Website(
            organization_id=organization.id,
            host="example.com",
            scheme="https",
            is_verified=True,
            verification_token="a" * 64,
        )
        session.add_all((membership, website))
        session.flush()
        crawl = CrawlRun(
            organization_id=organization.id,
            website_id=website.id,
            actor_user_id=user.id,
            request_id=uuid4(),
            idempotency_key="crawl-agent-001",
            request_hash="a" * 64,
            status="completed",
            audit_version="homepage-v4",
            audit_findings=[
                {
                    "code": "missing_title",
                    "impact": "medium",
                    "confidence": "high",
                    "effort": "low",
                    "source_url": "https://example.com/",
                    "summary": "No title",
                    "evidence": "No title element",
                    "recommendation": "Add a title",
                    "verification": "Fetch and verify",
                },
                {
                    "code": "noindex_directive",
                    "impact": "high",
                    "confidence": "high",
                    "effort": "low",
                    "source_url": "https://example.com/",
                    "summary": "Noindex",
                    "evidence": "X-Robots-Tag contains noindex",
                    "recommendation": "Review noindex",
                    "verification": "Fetch and verify",
                },
            ],
        )
        session.add(crawl)
        context = TenantContext(
            AuthenticatedPrincipal(user.id, "issuer", "subject"),
            organization.id,
            OrganizationRole.EDITOR,
        )
        session.commit()
        ids = (crawl.id, website.id, organization.id)
    return factory, context, ids[0], ids[1], ids[2]


class FakeSpecialistGateway:
    def __init__(self, response: str = '{"ordered_codes":["noindex_directive","missing_title"]}') -> None:
        self.response = response
        self.calls = 0

    async def execute(
        self,
        context: TenantContext,
        task_id: UUID,
        request_id: UUID,
        idempotency_key: str,
        request: ModelGatewayRequest,
    ) -> ModelProviderResult:
        self.calls += 1
        return ModelProviderResult(
            text=self.response,
            usage=ModelUsageReport(input_tokens=20, output_tokens=10),
        )


class UnknownSpecialistGateway:
    async def execute(
        self,
        context: TenantContext,
        task_id: UUID,
        request_id: UUID,
        idempotency_key: str,
        request: ModelGatewayRequest,
    ) -> ModelProviderResult:
        raise ModelOutcomeUnknown(uuid4())


def test_governed_agent_binds_completed_tenant_crawl_and_records_attribution(
    specialist_workspace: tuple[sessionmaker[Session], TenantContext, UUID, UUID, UUID],
) -> None:
    factory, context, crawl_id, website_id, _ = specialist_workspace
    gateway = FakeSpecialistGateway()
    agent = GovernedPrioritizationAgent(
        factory, SKILLS, gateway, "openai", "fixture-model",
    )

    result = asyncio.run(
        agent.execute(
            context,
            website_id,
            crawl_id,
            uuid4(),
            uuid4(),
            "agent-run-001",
        )
    )

    assert result.status == "completed"
    assert result.ordered_codes == ("noindex_directive", "missing_title")
    assert (result.usage.input_tokens, result.usage.output_tokens) == (20, 10)
    assert gateway.calls == 1
    with factory() as session:
        events = session.scalars(select(AuditEvent)).all()
        assert {event.action for event in events} == {
            "agent.run.started",
            "agent.run.completed",
        }
        assert all(event.resource_type == "agent_run" for event in events)
        assert all(event.details["agent"] == "technical-audit-prioritizer" for event in events)
        assert all(event.details["crawl_id"] == str(crawl_id) for event in events)


def test_governed_agent_reconciles_unknown_and_invalid_outputs(
    specialist_workspace: tuple[sessionmaker[Session], TenantContext, UUID, UUID, UUID],
) -> None:
    factory, context, crawl_id, website_id, _ = specialist_workspace
    unknown = GovernedPrioritizationAgent(
        factory, SKILLS, UnknownSpecialistGateway(), "openai", "fixture-model",
    )
    unknown_result = asyncio.run(
        unknown.execute(
            context, website_id, crawl_id, uuid4(), uuid4(), "agent-run-unknown",
        )
    )
    assert unknown_result.status == "unknown"
    assert unknown_result.reservation_id is not None

    invalid = GovernedPrioritizationAgent(
        factory, SKILLS, FakeSpecialistGateway("not json"), "openai", "fixture-model",
    )
    invalid_result = asyncio.run(
        invalid.execute(
            context, website_id, crawl_id, uuid4(), uuid4(), "agent-run-invalid",
        )
    )
    assert invalid_result.status == "invalid_output"

    with factory() as session:
        actions = set(session.scalars(select(AuditEvent.action)).all())
        assert "agent.run.outcome_unknown" in actions
        assert "agent.run.invalid_output" in actions


def test_governed_agent_rejects_cross_tenant_or_unmatched_crawl_evidence(
    specialist_workspace: tuple[sessionmaker[Session], TenantContext, UUID, UUID, UUID],
) -> None:
    factory, context, crawl_id, website_id, organization_id = specialist_workspace
    gateway = FakeSpecialistGateway()
    agent = GovernedPrioritizationAgent(
        factory, SKILLS, gateway, "openai", "fixture-model",
    )
    forged = TenantContext(context.principal, organization_id, OrganizationRole.OWNER)
    with pytest.raises(TenantAccessDenied):
        asyncio.run(
            agent.execute(
                forged, website_id, crawl_id, uuid4(), uuid4(), "agent-run-forged",
            )
        )
    with pytest.raises(LookupError, match="not found"):
        asyncio.run(
            agent.execute(
                context, uuid4(), crawl_id, uuid4(), uuid4(), "agent-run-mismatch",
            )
        )
    assert gateway.calls == 0
