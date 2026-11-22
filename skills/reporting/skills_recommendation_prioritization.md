# Skill: Recommendation Prioritization
Status: active

## Purpose
Prioritize recommendations using impact, confidence, effort, dependencies and risk.

## Agent Composition
- Specialist agent: technical-audit-prioritizer
- Reusable with: technical audit, reporting
- Risk tier: low
- Required evidence: findings with impact, confidence and effort metadata

## Typed Input
```json
{
  "findings": [
    {"code": "HomepageFindingCode", "impact": "high", "confidence": "high", "effort": "low"}
  ]
}
```

## Typed Output
```json
{
  "ordered_codes": ["HomepageFindingCode"]
}
```

## Authorized Tools
- none

## Procedure
1. Prefer measurable and reversible work.
2. Surface blocked dependencies and approval requirements.
3. Return every supplied code exactly once, highest priority first.

## Guardrails
- Do not rank by a synthetic score presented as a search-engine guarantee.
- Do not invent findings.

## Evaluation Tests
- Output is a permutation of the input
- Higher impact, higher confidence and lower effort rank earlier when all else is equal
- Malformed output is rejected
