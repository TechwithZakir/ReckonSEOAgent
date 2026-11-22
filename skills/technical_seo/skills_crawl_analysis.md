# Skill: Crawl Analysis
Status: planned

## Purpose
Interpret crawl graph data, status codes, links and page-level observations.

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
Crawler, robots parser, URL normalizer, redirect resolver and evidence store.

## Guardrails
Honor robots.txt and configured limits. Block private IPs, DNS-rebound targets and
cloud metadata endpoints before and after redirects.

## Evaluation Tests
- Groundedness: no fabricated evidence
- Tenant isolation
- Policy violation is rejected
