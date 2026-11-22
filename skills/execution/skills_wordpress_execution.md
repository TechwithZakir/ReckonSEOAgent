# Skill: WordPress Execution
Status: planned

## Purpose
Support evidence-grounded WordPress discovery and approval-based writes.

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
Discover REST/plugin capabilities; obtain a current snapshot; produce preview/diff; run
central policy/approval; execute through supported APIs; verify live/CMS state; offer
rollback if supported.

## Guardrails
Do not use credential bypass or weak confirmation. Never claim success on an API call alone.

## Evaluation Tests
- Groundedness: no fabricated evidence
- Tenant isolation
- Policy violation is rejected
