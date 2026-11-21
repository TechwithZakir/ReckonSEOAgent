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

An internal model-token ledger provides tenant-scoped, idempotent reservations and usage
settlement with forced PostgreSQL RLS and serialized organization-level budget checks.
Unresolved reservations remain charged across day boundaries. The internal provider-neutral
gateway checks membership, delegates task authorization to a trusted local policy, binds the
effective request and adapter version, commits a reservation before dispatch, rejects replays,
and commits reported usage before returning. Unknown outcomes retain their reservation; a
recognized outcome produces an audit event when the actor remains authorized and the database
is available.
No prompts or provider error messages are stored in those audit details.

Owners and admins can save one provider/model selection and API key per organization through
the AI settings API. Credentials are encrypted with AES-256-GCM using a server-supplied key;
the organization and provider are authenticated as associated data. PostgreSQL forces RLS,
manager authorization is rechecked under lock for writes, and audit events omit credentials.
Responses never return the key. HTTPS is required in staging/production and for non-loopback
local API clients. Trusted TLS proxy configuration remains an operator responsibility.
Encryption does not protect keys from a compromised API process or master key. Key rotation,
provider connectivity verification and use of these settings by an adapter are not implemented.

Only test authorizers and adapters exist. A real trusted authorizer must validate task
ownership, system prompt, model and limits; a real adapter must provide a conservative input
bound, enforce provider limits and transport deadlines, and report provider-confirmed usage.
The gateway does not independently verify those reports. Its semaphore is per gateway instance,
and synchronous authorization, database and adapter preparation cannot be preempted by the
async timeout. A timed-out or cancelled call may continue; its reservation remains charged and
capacity remains occupied until the adapter task finishes. Automatic settlement and operator
reconciliation are absent. This is not production-ready provider metering or an agent runtime.

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

The organization list discovers only the authenticated user's active memberships under a
user-specific SELECT policy when no organization is selected. Each organization's name
and current membership are then fetched under that organization's RLS scope. Results are
cursor-paginated, and selecting a workspace rechecks membership. Native accounts, SMTP
verification, member invitations, role management and organization profile editing are
not yet implemented.

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
monotonic deadlines across response headers and bodies. Responses that arrive after the
aggregate crawl deadline are rejected; DNS A/AAAA lookups have separate per-query bounds.
The crawler fetches and enforces `robots.txt` before the homepage; only 404/410 are treated
as absent, other 4xx responses deny crawling, and server errors fail closed. The dashboard
lets active members crawl verified sites and inspect recent crawl history. The authenticated
crawl API accepts active members and verified sites,
reserves a per-organization daily budget before network access, and persists idempotent
tenant-scoped outcomes plus audit events. HTML observations include bounded title and
meta-description text plus an H1 count; these remain untrusted website evidence. The default
cap is 10 attempts per organization per UTC day, including failures and interrupted runs.
On a later reservation, running records older than five minutes are finalized as interrupted
and retain their budget charge. Plan-specific quotas and end-to-end live-network verification
remain unimplemented. Completed crawls run the versioned deterministic `homepage-v4` audit,
which records source-linked findings for non-success HTTP status; missing title, meta
description or H1 evidence; observed noindex directives; and invalid, duplicate or cross-host
canonical links. Both X-Robots-Tag and robots meta are recorded independently, and canonical
queries are stripped before persistence. robots.txt sitemap declarations yield at most ten
normalized same-host URLs; external, invalid and over-limit candidates are not fetched. After the
homepage, at most ten sitemap documents are fetched under a four-second aggregate budget and
256 KiB per document. XML parsing rejects DTD/entity declarations, counts unique same-host URL
locations or index children, and follows robots rules. It retains a capped set of normalized
index-child references and may fetch one child level within the same ten-document/four-second
budget. Page URLs are not fetched.
Sitemap findings report confirmed empty documents and incomplete parsing/fetch evidence.
Fully analyzed URL sets also record homepage and same-host canonical membership; absence
findings are suppressed whenever sitemap discovery or parsing is incomplete. Findings carry
impact, confidence, effort, recommendation and verification fields; they are not combined into
a synthetic score or a complete indexability verdict. Sitewide sitemap coverage, rendered-page
signals, multi-page audits and broader dashboard workflows remain unimplemented.

The database application role must be least-privileged and must not be a superuser or have
`BYPASSRLS`; tenant-scoped requests set transaction-local organization context before
reading organization membership. External identity mappings and user accounts are global
identity records, not organization-owned rows.

Migrations through `0008_sitemap_document_evidence` have been applied to local PostgreSQL 18.7. The
`reckon` application role was verified as non-superuser and non-`BYPASSRLS`; rollback-only
integration checks cover organization, website, and crawl-run RLS.

Physical schema names are intentionally compact (`orgs`, `org_members`, `usr_id`, `org_id`,
`idem_key`). Python model attributes and external API fields remain descriptive. Audit
events use short physical columns and RLS on `org_id`. Websites, idempotency records and crawl
history use `sites`, `site_create_reqs` and `site_crawl_runs`, all forced through tenant RLS.

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
