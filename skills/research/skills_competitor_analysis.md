# Skill: Competitor Analysis
Status: planned

## Purpose
Compare authorized public evidence between a website and approved competitors.

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
Crawl, approved SERP/data-provider adapters and deterministic diffing.
Evidence provenance, reproducibility, no unsupported claims and rate-limit handling.

## Guardrails
Use public or licensed evidence only. Do not copy, scrape excessively or impersonate
competitors. Label hypotheses.

## Evaluation Tests
- Groundedness: no fabricated evidence
- Tenant isolation
- Policy violation is rejected
