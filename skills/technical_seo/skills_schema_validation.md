# Skill: Schema Validation
Status: planned

## Purpose
Validate machine-readable structured data against actual visible page/CMS evidence.

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
Do not invent ratings, offers, stock, organization facts or reviews. Validate only
schema types and properties supported by the page.

## Evaluation Tests
- Groundedness: no fabricated evidence
- Tenant isolation
- Policy violation is rejected
