from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from reckon_core.specialist_agents import (
    AgentDefinition, FindingForPrioritization, InvalidAgentOutput, PrioritizationInput,
    build_prioritization_request, validate_prioritization_output,
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
