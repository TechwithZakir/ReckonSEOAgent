# Skill: Keyword Research
Status: planned

## Purpose
Identify query opportunities from approved keyword/search data and site context.

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
Search/keyword provider adapters, Search Console, deterministic clustering.
Validate locale/device/date context; retrieve provider data; cluster queries; separate
brand/non-brand; preserve provider timestamp and source; map opportunities to existing or
new pages.
Coverage, cluster quality, source freshness, tenant isolation and no fabricated metrics.

## Guardrails
Do not present estimated or licensed metrics as guaranteed. Do not infer unavailable volume
or ranking data. Never scrape prohibited SERPs at scale.

## Evaluation Tests
- Groundedness: no fabricated evidence
- Tenant isolation
- Policy violation is rejected
