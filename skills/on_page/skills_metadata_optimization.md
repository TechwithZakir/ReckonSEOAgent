# Skill: Metadata Optimization
Status: planned

## Purpose
Propose unique, accurate title and description values.

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
Use observed page facts and avoid deceptive snippets. Snapshot existing metadata and verify
rendered/CMS state after execution.

## Evaluation Tests
- Groundedness: no fabricated evidence
- Tenant isolation
- Policy violation is rejected
