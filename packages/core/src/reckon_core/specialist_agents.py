"""Trusted composition for the first, read-only specialist agent."""

import json
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from reckon_core.model_gateway import ModelGatewayRequest, ModelMessage
from reckon_core.seo_audit import FindingConfidence, FindingEffort, FindingImpact, HomepageFindingCode

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


def build_prioritization_request(
    skills_root: Path, provider: str, model: str, agent_input: PrioritizationInput,
) -> ModelGatewayRequest:
    """Compose the allowlisted skills and deterministic finding metadata; no page text or tools."""
    skills: list[str] = []
    for relative_path in _SKILL_FILES:
        content = (skills_root / relative_path).read_text(encoding="utf-8")
        if not content.strip() or len(content.encode("utf-8")) > 16_384:
            raise ValueError("A specialist skill is empty or exceeds its size limit.")
        skills.append(content)
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
