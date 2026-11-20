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
  web/             React + TypeScript dashboard
  worker/          Celery entrypoints (planned)
  mcp_server/      Curated remote MCP surface (planned)
  browser_gateway/ Isolated browser execution (planned)
packages/
  core/            Tenant, identity and initial audit primitives
  ai_engine/       Provider-neutral agents, budgets and evaluations (planned)
  seo_engine/      Deterministic crawl and SEO analysis (planned)
  cms_connectors/  API-first CMS adapters (planned)
```

## Current implementation

The API has `GET /health/live` and a database-backed `GET /health/ready`. Organization
context routes require an OIDC bearer token whose signature is verified against the
configured HTTPS JWKS endpoint, issuer, and API audience. External issuer/subject pairs map
to internal users; active membership is checked from PostgreSQL for every organization
scope. The browser uses a public OIDC client with authorization code and PKCE; the API does
not issue tokens or expose public identity provisioning.
Organization creation requires a caller-supplied idempotency key bound to the authenticated
user and normalized request; key reuse with a different payload is rejected, and a per-user
row lock serializes concurrent retries. Creation and its tenant-scoped audit event commit in
the same transaction. The API assigns a new server-generated request ID to each request
and returns it in `X-Request-ID`.

Internal users can currently be bootstrapped only by the local `reckon_api.cli
provision-identity` operator command. It accepts a token file, verifies the OIDC signature,
issuer, audience and claims using the API verifier, and transactionally creates an internal
user plus external identity mapping. There is no public provisioning endpoint.

The React dashboard reads live/readiness health, supports configured OIDC sign-in, and
provides organization selection plus website registration and DNS TXT verification.
Website APIs require active tenant membership; create/verify operations are owner/admin-only.
Site URLs are normalized as public HTTP(S) origins without credentials, paths, or custom
ports. Verification performs a bounded TXT lookup only; it does not make an HTTP request to
the submitted website. The shared core now includes a bounded single-homepage fetcher: it
validates all A/AAAA answers, connects to a checked IP without resolving the hostname again,
restricts redirects to the verified host, and caps redirects, response bytes, and per-request
socket-operation timeouts. Aggregate timeout behavior still needs transport-level verification.
It is not exposed through the API or dashboard. Crawl history, tenant metering, robots.txt
handling, and end-to-end live-network verification remain unimplemented.

The database application role must be least-privileged and must not be a superuser or have
`BYPASSRLS`; tenant-scoped requests set transaction-local organization context before
reading organization membership. External identity mappings and user accounts are global
identity records, not organization-owned rows.

Migrations through `0002_websites` have been applied to local PostgreSQL 18.7. The `reckon`
application role was verified as non-superuser and non-`BYPASSRLS`; rollback-only integration
checks cover organization and website RLS.

Physical schema names are intentionally compact (`orgs`, `org_members`, `usr_id`, `org_id`,
`idem_key`). Python model attributes and external API fields remain descriptive. Audit
events use short physical columns and RLS on `org_id`. Websites and their idempotency records
use `sites` and `site_create_reqs`, both forced through tenant RLS.

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
