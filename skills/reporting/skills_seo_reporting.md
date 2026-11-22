# Skill: SEO Reporting
Status: planned

## Purpose
Create accurate reports for operational outcomes and measured trends.

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
To be expanded when the backing tools exist.

## Guardrails
Separate observed metrics, recommendations and confirmed changes. Include data source,
timestamp, scope and limitations. Do not promise rankings or outcomes.

## Evaluation Tests
- Groundedness: no fabricated evidence
- Tenant isolation
- Policy violation is rejected
