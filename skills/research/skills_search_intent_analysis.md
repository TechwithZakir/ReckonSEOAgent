# Skill: Search Intent Analysis
Status: planned

## Purpose
Classify page/query intent and assess whether existing content satisfies that intent.

## Agent Composition
- Specialist agent: not yet implemented
- Reusable with: see skills/README.md
- Risk tier: to be defined when implemented
- Required evidence: tenant-scoped deterministic evidence with source and timestamp

## Typed Input
```json
{
  "website_id": "uuid",
  "scope": {}
}
```

## Typed Output
```json
{
  "status": "completed",
  "findings": [],
  "evidence": [],
  "confidence": 0.0
}
```

## Authorized Tools
- none (planned: tools will be listed here once the backing code exists)

## Procedure
Use SERP observations or licensed data, on-page evidence and query context. Preserve
informational, navigational, commercial and transactional distinctions.

## Guardrails
Do not infer intent solely from keywords when SERP evidence is required. Avoid fabricated
intent scores.

## Evaluation Tests
- Groundedness: no fabricated evidence
- Tenant isolation
- Policy violation is rejected
