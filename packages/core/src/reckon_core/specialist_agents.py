"""Trusted composition for the first, read-only specialist agent."""

import json
from pathlib import Path
from typing import Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from sqlalchemy import select, text
from sqlalchemy.orm import Session, sessionmaker

from reckon_core.model_gateway import (
    ModelExecutionPolicy,
    ModelGatewayRequest,
    ModelMessage,
    ModelOutcomeUnknown,
    ModelProviderResult,
)
from reckon_core.model_usage import ModelUsageReport
from reckon_core.persistence import AuditEvent, CrawlRun
from reckon_core.repositories import SqlAlchemyMembershipRepository
from reckon_core.seo_audit import FindingConfidence, FindingEffort, FindingImpact, HomepageFindingCode
from reckon_core.tenancy import (
    TenantAccessDenied,
    TenantContext,
)
from reckon_core.permissions import OrganizationPermission, require_permission
from reckon_core.skills import SkillValidationError, load_skill

_SKILL_FILES = (
    "technical_seo/skills_technical_audit.md",
    "reporting/skills_recommendation_prioritization.md",
    "governance/skills_prompt_injection_defense.md",
    "governance/skills_tenant_isolation.md",
)


class FindingForPrioritization(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    code: HomepageFindingCode
    impact: FindingImpact
    confidence: FindingConfidence
    effort: FindingEffort


class PrioritizationInput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    website_id: UUID
    crawl_id: UUID
    findings: tuple[FindingForPrioritization, ...] = Field(min_length=1, max_length=12)

    @model_validator(mode="after")
    def unique_findings(self) -> "PrioritizationInput":
        if len({finding.code for finding in self.findings}) != len(self.findings):
            raise ValueError("Finding codes must be unique.")
        return self


class PrioritizationOutput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    ordered_codes: tuple[HomepageFindingCode, ...] = Field(min_length=1, max_length=12)


class AgentDefinition(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: Literal["technical-audit-prioritizer"] = "technical-audit-prioritizer"
    skill_files: tuple[
        Literal["technical_seo/skills_technical_audit.md"],
        Literal["reporting/skills_recommendation_prioritization.md"],
        Literal["governance/skills_prompt_injection_defense.md"],
        Literal["governance/skills_tenant_isolation.md"],
    ] = _SKILL_FILES
    authorized_tools: tuple[()] = ()
    max_steps: Literal[1] = 1


class InvalidAgentOutput(ValueError):
    pass


class AgentRunResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    status: Literal["completed", "unknown", "invalid_output"]
    ordered_codes: tuple[HomepageFindingCode, ...] | None = None
    reservation_id: UUID | None = None
    usage: ModelUsageReport | None = None


class SpecialistGateway(Protocol):
    async def execute(
        self,
        context: TenantContext,
        task_id: UUID,
        request_id: UUID,
        idempotency_key: str,
        request: ModelGatewayRequest,
    ) -> ModelProviderResult:
        """Execute only through the bounded model gateway."""


class SpecialistPrioritizationAuthorizer:
    """Trusted task policy: read-only, no tools, bounded model and token limits."""

    def __init__(self, policy: ModelExecutionPolicy) -> None:
        self._policy = policy

    def authorize(
        self,
        context: TenantContext,
        task_id: UUID,
        request: ModelGatewayRequest,
    ) -> ModelExecutionPolicy:
        require_permission(context.role, OrganizationPermission.AGENT_RUN)
        if type(task_id) is not UUID:
            raise ValueError("The specialist task ID must be typed.")
        if request.provider != self._policy.provider or request.model != self._policy.model:
            raise ValueError("The specialist request is outside its task policy.")
        return self._policy


class GovernedPrioritizationAgent:
    """Bind deterministic crawl evidence to one read-only, bounded specialist run."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        skills_root: Path,
        gateway: SpecialistGateway,
        provider: str,
        model: str,
    ) -> None:
        self._session_factory = session_factory
        self._skills_root = skills_root
        self._gateway = gateway
        self._provider = provider
        self._model = model

    def _load_evidence(
        self,
        session: Session,
        context: TenantContext,
        website_id: UUID,
        crawl_id: UUID,
    ) -> PrioritizationInput:
        role = SqlAlchemyMembershipRepository(session).role_for_active_membership(
            context.principal.user_id,
            context.organization_id,
        )
        if role is None or role != context.role:
            raise TenantAccessDenied
        if session.get_bind().dialect.name == "postgresql":
            session.execute(
                text("SELECT set_config('app.org_id', :organization_id, true)"),
                {"organization_id": str(context.organization_id)},
            )
        crawl = session.scalar(
            select(CrawlRun).where(
                CrawlRun.organization_id == context.organization_id,
                CrawlRun.website_id == website_id,
                CrawlRun.id == crawl_id,
            )
        )
        if crawl is None:
            raise LookupError("The tenant crawl evidence was not found.")
        if crawl.status != "completed" or crawl.audit_findings is None:
            raise LookupError("The crawl has no reconciled completed evidence.")

        findings: list[FindingForPrioritization] = []
        for finding in crawl.audit_findings:
            try:
                findings.append(
                    FindingForPrioritization(
                        code=finding["code"],
                        impact=finding["impact"],
                        confidence=finding["confidence"],
                        effort=finding["effort"],
                    )
                )
            except (KeyError, ValidationError):
                raise LookupError("The crawl evidence does not match the audit contract.") from None
        if not findings:
            raise LookupError("The completed crawl has no findings to prioritize.")
        return PrioritizationInput(
            website_id=website_id,
            crawl_id=crawl_id,
            findings=tuple(findings),
        )

    def _record(
        self,
        session: Session,
        context: TenantContext,
        request_id: UUID,
        crawl_id: UUID,
        task_id: UUID,
        action: str,
        details: dict[str, str],
    ) -> None:
        session.add(
            AuditEvent(
                organization_id=context.organization_id,
                actor_user_id=context.principal.user_id,
                action=action,
                resource_type="agent_run",
                resource_id=task_id,
                request_id=request_id,
                details={
                    "crawl_id": str(crawl_id),
                    "agent": "technical-audit-prioritizer",
                    **details,
                },
            )
        )

    async def execute(
        self,
        context: TenantContext,
        website_id: UUID,
        crawl_id: UUID,
        task_id: UUID,
        request_id: UUID,
        idempotency_key: str,
    ) -> AgentRunResult:
        with self._session_factory() as session:
            agent_input = self._load_evidence(
                session, context, website_id, crawl_id,
            )
            self._record(
                session, context, request_id, crawl_id, task_id,
                "agent.run.started", {"status": "started"},
            )
            session.commit()

        request = build_prioritization_request(
            self._skills_root, self._provider, self._model, agent_input,
        )
        try:
            result = await self._gateway.execute(
                context, task_id, request_id, idempotency_key, request,
            )
        except ModelOutcomeUnknown as error:
            with self._session_factory() as session:
                self._record(
                    session, context, request_id, crawl_id, task_id,
                    "agent.run.outcome_unknown",
                    {"status": "unknown", "reservation_id": str(error.reservation_id)},
                )
                session.commit()
            return AgentRunResult(
                status="unknown",
                reservation_id=error.reservation_id,
            )

        with self._session_factory() as session:
            try:
                output = validate_prioritization_output(agent_input, result.text)
            except InvalidAgentOutput as error:
                self._record(
                    session, context, request_id, crawl_id, task_id,
                    "agent.run.invalid_output",
                    {"status": "invalid_output", "reason": str(error)},
                )
                session.commit()
                return AgentRunResult(status="invalid_output")
            self._record(
                session, context, request_id, crawl_id, task_id,
                "agent.run.completed",
                {"status": "completed"},
            )
            session.commit()
        return AgentRunResult(
            status="completed",
            ordered_codes=output.ordered_codes,
            usage=result.usage,
        )


def build_prioritization_request(
    skills_root: Path, provider: str, model: str, agent_input: PrioritizationInput,
) -> ModelGatewayRequest:
    """Compose the allowlisted skills and deterministic finding metadata; no page text or tools."""
    skills: list[str] = []
    for relative_path in _SKILL_FILES:
        try:
            skill = load_skill(skills_root, relative_path, known_tools=())
        except SkillValidationError as error:
            raise ValueError("A specialist skill is empty, invalid or exceeds its size limit.") from error
        if skill.status != "active" or skill.authorized_tools:
            raise ValueError("A prioritization skill must be active and grant no tools.")
        skills.append((skills_root / relative_path).read_text(encoding="utf-8"))
    prompt = (
        "You are a read-only technical SEO prioritization agent. "
        "Follow the trusted skills below. Return only a JSON object with one field "
        '"ordered_codes": an array containing every supplied finding code exactly once, '
        "in priority order. Do not invent findings or use tools.\n\n"
        + "\n\n".join(skills)
    )
    findings = [finding.model_dump(mode="json") for finding in agent_input.findings]
    return ModelGatewayRequest(
        provider=provider,
        model=model,
        system_prompt=prompt,
        messages=(ModelMessage(role="user", content=json.dumps(findings, separators=(",", ":"))),),
    )


def validate_prioritization_output(
    agent_input: PrioritizationInput, response: str,
) -> PrioritizationOutput:
    """Accept only a complete permutation of the supplied deterministic findings."""
    if len(response.encode("utf-8")) > 4096:
        raise InvalidAgentOutput("The agent output exceeded its size limit.")
    try:
        output = PrioritizationOutput.model_validate_json(response)
    except ValidationError:
        raise InvalidAgentOutput("The agent output did not match its contract.") from None
    actual = output.ordered_codes
    expected = {finding.code for finding in agent_input.findings}
    if len(actual) != len(expected) or set(actual) != expected:
        raise InvalidAgentOutput("The agent output did not match the supplied findings.")
    return output
