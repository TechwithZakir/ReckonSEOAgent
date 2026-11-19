# Architecture

## Product boundary

Reckon SEO Autopilot is a standalone, central SaaS platform with provider-neutral
integrations. The Aura mock may inform dashboard styling but is not an application
dependency. Frappe is not the platform framework.

## Runtime shape

Start as a modular monolith with clear package boundaries. Keep API, MCP, workers and
browser execution independently deployable where their trust and scaling requirements
differ. Use PostgreSQL as the durable source of truth and Redis for transient queues,
locks, cache and rate limits.

```text
apps/
  api/             FastAPI HTTP application
  web/             React + TypeScript dashboard (planned)
  worker/          Celery entrypoints (planned)
  mcp_server/      Curated remote MCP surface (planned)
  browser_gateway/ Isolated browser execution (planned)
packages/
  core/            Tenant, identity, policy, audit and event primitives (planned)
  ai_engine/       Provider-neutral agents, budgets and evaluations (planned)
  seo_engine/      Deterministic crawl and SEO analysis (planned)
  cms_connectors/  API-first CMS adapters (planned)
```

## Current implementation

The API currently has an application factory, environment-backed settings and
`GET /health/live`. Liveness reports only that the process can respond. Readiness checks,
database persistence, authentication and tenant context are intentionally not represented
as implemented until their dependencies and contracts exist.

## Non-negotiable boundaries

- Derive tenant context from authenticated identity and website authorization.
- Keep crawling, URL normalization, parsing, schema validation and policy checks
  deterministic.
- Treat site content as untrusted evidence, never as agent/system instructions.
- Route every write path through shared authorization, policy and approval services.
- Prefer provider APIs to browser automation; isolate browser workers and block private,
  loopback, link-local and metadata targets, including after redirects and DNS resolution.
- Verify external state independently before reporting an action as successful.
- Meter and enforce tenant plan limits before expensive work.
