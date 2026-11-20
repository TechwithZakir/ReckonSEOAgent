# Development Log

This is the single detailed record of implementation progress, decisions, validation and
next work. Keep the root README as the short user-facing setup/status page and record
milestone details here.

## Product and engineering invariants

- Independent, multi-tenant SaaS with a modular monolith as the starting architecture.
- Python 3.12+, FastAPI, Pydantic, SQLAlchemy 2.x, Alembic and PostgreSQL for backend work;
  React and TypeScript for the dashboard.
- Tenant context must come from validated identity and active website/organization
  authorization, never from an unverified request field.
- Deterministic code owns crawling, parsing, URL normalization, security and policy checks.
- External web content is untrusted evidence, not instructions.
- External writes require shared policy/approval checks, idempotency, independent
  verification and rollback data where supported.
- The Aura mock is visual guidance only; the platform is not built on Frappe.
- Do not implement manipulative SEO, fake reviews, cloaking, hidden text, doorway pages,
  credential bypass or scaled low-value content.

## Implemented

### Foundation: API bootstrap

- Added the FastAPI package, settings loaded from `RECKON_` environment values and a typed
  `GET /health/live` response.
- Added API contract tests and local install/run instructions.
- Liveness confirms only that the process responds; it is not a readiness or dependency
  check.

### Foundation: authenticated tenant access

- Added an immutable `AuthenticatedPrincipal` contract for identity mapped by a trusted
  authentication adapter.
- Added OIDC JWT verification using HTTPS JWKS, exact issuer and audience checks, required
  time/subject claims, a 30-second clock skew and an RS256-only algorithm allowlist.
- Added external issuer/subject identity mapping and SQLAlchemy models for users,
  organizations and active/inactive memberships.
- Added PostgreSQL Alembic migration with row-level security policies on organization-owned
  tables. Tenant membership lookups set the requested organization as transaction-local
  context before reading RLS-protected rows.
- Used compact physical schema names (`orgs`, `identities`, `org_members`,
  `org_create_reqs`; `usr_id`, `org_id`, `idem_key`, `req_hash`, `active`) while preserving
  descriptive Python model attributes and API fields.
- Added an authenticated organization-context API route. Unknown and inactive memberships
  receive the same not-found response.
- Added authenticated organization creation, assigning the verified user as owner.
  `Idempotency-Key` is required; a persisted request hash enables safe replay, rejects
  different payload reuse, and a per-user row lock serializes concurrent attempts.
- Added server-generated request IDs and a tenant-scoped audit event for organization
  creation. The audit event is written in the same transaction and is not duplicated on
  idempotent replay.
- Added RLS for audit events and retained the compact physical naming convention, including
  `audit_events.org_id`, `actor_usr_id`, `res_type`, `res_id` and `req_id`.
- Added liveness and database readiness endpoints; readiness returns unavailable when no
  database session is configured.
- Identity-provider network failures and database operational/interface failures return
  explicit service-unavailable responses rather than authentication failures or success.
- Production configuration now requires both database settings and a complete OIDC
  issuer/audience/JWKS configuration.
- Added tests for signed/invalid tokens, missing/inactive memberships, cross-tenant access,
  configuration requirements and database readiness.
- Applied the initial migration to local PostgreSQL 18.7 using the `reckon` application
  role. Verified the role is neither superuser nor `BYPASSRLS`; all four tenant-owned
  tables have RLS enabled and forced with four policies.
- Exercised tenant RLS against the live database in a rollback-only transaction: tenant A
  saw only its own organization, no tenant context saw no rows, and test rows were rolled
  back.
- Added an opt-in PostgreSQL RLS integration test that runs when `RECKON_DATABASE_URL` is
  configured; tests that need an unconfigured environment explicitly ignore local `.env`.
- Started the API using the local `.env`; `/health/live` and `/health/ready` both returned
  200 with request IDs. The dashboard's proxied readiness route also returned 200.
- Added an operator-only `python -m reckon_api.cli provision-identity` command. It accepts
  a restricted token-file path (never a token argument), verifies signature/issuer/audience
  with the shared OIDC verifier, and creates the internal user and external identity
  atomically. Duplicate provisioning returns the existing user; no public endpoint was
  added.
- Added tests for idempotent provisioning, distinct subjects and invalid identity claims.

### Dashboard: responsive UI foundation

- Added the React/TypeScript Vite application under `apps/web/` with a responsive SaaS shell,
  accessible navigation, light/dark theme toggle and API reference links.
- Added live polling and manual refresh for `/health/live` and `/health/ready`; the UI
  distinguishes a live API from an unavailable database and reports non-success responses
  without exposing response bodies.
- Added a Vite development proxy for health, API and OpenAPI documentation routes.
- Clearly labels website, audit, recommendation, agent activity and approval features as
  unavailable/planned. No SEO metrics or customer data are fabricated.
- Added focused tests for successful health checks, database-not-ready behavior and API
  connection failures.

### Dashboard: browser OIDC and organization onboarding

- Added a provider-neutral OIDC authorization-code flow with PKCE using `oidc-client-ts`.
  The authority must be HTTPS, while HTTP is accepted only for loopback development.
- Kept access tokens in an in-memory user store. Browser session storage is restricted to
  the transient OIDC state/PKCE transaction and a non-secret active organization ID.
- Disabled automatic silent renewal and provider-session polling; a new sign-in is required
  after token expiry rather than persisting refresh tokens in browser storage.
- Added public client configuration via root `.env` `VITE_OIDC_*` variables, loaded by Vite
  from the repository root. No client secret is supported or needed for a public SPA.
- Added UI flows to create an organization with an idempotency key or enter an existing
  organization ID. Both use the authenticated API; the UI performs an independent membership
  context request before marking an organization connected.
- Restored the active organization from session storage only after the API re-validates
  membership for the current signed-in user.
- OIDC user provisioning remains operator-controlled. A signed-in but unprovisioned identity
  receives the API's explicit authorization failure; no public provisioning endpoint was
  added.
- Real external-provider login remains unverified because no actual issuer/client has been
  configured in this environment.

### Website registration and DNS ownership verification

- Added `sites` and `site_create_reqs` with compact physical column names, an organization/
  website composite foreign key, host uniqueness within an organization, and forced
  transaction-local tenant RLS.
- Added canonical HTTP(S) origin parsing: credentials, paths, query/fragment delimiters,
  nonstandard ports, IP literals, localhost, and reserved local/test suffixes are rejected.
  IDNs are normalized to ASCII.
- Added owner/admin-only, idempotent website registration. The DNS challenge uses a random
  token; retries return the same challenge, while reused keys with changed origins and
  duplicate hosts are rejected.
- Added bounded DNS TXT verification (three-second lookup timeout, no DNS search suffix).
  Verification makes no HTTP request to the submitted host; a missing record remains
  pending, and DNS lookup failures return service-unavailable.
- Added tenant-scoped website listing. Pending challenge values are returned only to
  organization owners/admins; audit events record the host and verification method but
  never the challenge token.
- Added dashboard website registration, DNS instructions, retry/refresh controls and
  explicit pending/verified states. Crawling remains disabled.
- Applied migration `0002_websites` to the local PostgreSQL database and extended the live
  RLS integration test to cover both new tables.

### Crawler safety foundation

- Added a bounded DNS resolver that queries A and AAAA records without search suffixes.
- Added a fail-closed target preflight that normalizes hostnames, rejects IP-literal hosts,
  empty or excessive results, invalid addresses, IPv4-mapped IPv6, and any non-public result
  (including mixed public/private answer sets).
- Added an isolated, single-homepage fetcher. It connects directly to a prevalidated IP
  while retaining the original hostname for the HTTP Host header and TLS verification.
- Redirects are manual, capped, restricted to the registered hostname, and re-resolved before
  each request; HTTPS redirects cannot downgrade to HTTP. HTTP status, header and body reads
  use a shared monotonic request deadline, late results are rejected against the aggregate
  crawl deadline, response bytes are bounded, compressed responses are rejected, and the HTML
  title is parsed deterministically. DNS A/AAAA lookups have independent per-query bounds.
- Added robots.txt preflight before homepage fetching. Rules are evaluated for the crawler's
  product token and same-host redirects use the pinned transport. Only 404/410 mean no policy;
  other 4xx responses deny crawling, and server errors or network failures fail closed.
- Added focused tests for IP pin selection, same-host redirect revalidation, external redirect
  rejection, HTTPS downgrade, non-standard ports, credentials, and private/mixed DNS answers.
- Added loopback-only slow-header and slow-body regression tests for request deadline
  enforcement and a fake-clock test ensuring the crawler rejects a response returned after
  its aggregate limit.
- Added robots tests for disallowed paths and fail-closed 403/429/5xx responses.
- DNS and transport doubles cover policy behavior; loopback tests exercise the real HTTP
  transport. No live external website was fetched.

### Tenant-authorized crawl API

- Added `site_crawl_runs` with forced organization RLS, a composite website/organization
  foreign key, audit actor/request attribution, idempotency, and retained page evidence.
- The crawl endpoint accepts active organization members and verified websites only. It
  serializes budget reservations on the organization row, commits the reservation before
  network access, and enforces a configurable default of 10 attempts per UTC day per tenant.
  Failed and interrupted runs consume budget; same-key completed/disallowed retries replay
  the stored result without another crawl.
- Crawl outcomes and lifecycle audit events are tenant-scoped. Robots-denied runs are recorded
  distinctly; policy failures return 422 and network failures return 503 without claiming a
  successful crawl.
- Added an active-member crawl-history endpoint scoped to one website, with stable newest-first
  ordering, bounded limit/offset pagination and tenant-context RLS.
- Applied migration `0003_site_crawl_runs` to local PostgreSQL 18.7 and extended the live RLS
  integration test. The API uses an injected crawler in tests; no live external site was fetched.
- The dashboard remains read-only for crawling. Multi-page crawl, plan-specific quotas,
  retention/cleanup, and background execution remain unimplemented.

## Explicitly not implemented yet

- No invitation workflow, self-service identity provisioning, or token issuance. An operator
  must provision the verified external identity with the local CLI before the user can
  access organization APIs.
- Local PostgreSQL migration and RLS behavior are verified. Production database provisioning,
  backup/restore, and deployment configuration remain unverified.
- Crawl scheduling, multi-page crawling, dashboard controls, plan-specific quotas, and
  retention/cleanup remain unimplemented.
- No fine-grained permission policy, complete audit event history, Redis/Celery jobs,
  broader usage metering, MCP endpoint or CMS writes.
- The dashboard is not yet an SEO operations interface and displays no crawl metrics.
- The database role used by deployment must not be a superuser or have `BYPASSRLS`.

## Decisions and boundaries

- OIDC is integrated as a standards-based verifier configured with issuer, audience and JWKS
  URL; the platform does not issue tokens or store provider credentials. The dashboard is a
  public OIDC client using code flow with PKCE and does not contain a client secret.
- Authenticated principals are created only after signature/claim verification and a
  persisted external-identity mapping.
- Membership lookup is the authoritative organization authorization check; do not authorize
  from client-supplied organization IDs or stale membership claims alone.
- RLS uses a transaction-local organization setting and is defense in depth; the database
  connection role must not bypass RLS.
- Keep detailed development tracking in this file; update `README.md` when milestone scope
  or quick-start instructions change.

## Validation history

- `python -m pip install --no-deps -e .`: passed with both API and shared-core packages
  discoverable.
- `python -m pip install -e ".[dev]"`: passed with API, SQLAlchemy, PostgreSQL driver,
  Alembic and PyJWT dependencies.
- `python -m pytest`: 30 passed, including signed-token validation, identity-provider
  outages, active/inactive membership, tenant denial, idempotent organization creation,
  transactional audit events, request IDs, short physical schema names, configuration
  requirements and readiness checks.
- `python -m pytest` with local PostgreSQL configured: 31 passed, including the live
  least-privilege RLS isolation integration test.
- `python -m pytest` after identity provisioning: 40 passed, including identity
  idempotency, distinct subjects, invalid claims, and bounded token-file input.
- `python -m compileall -q apps packages migrations tests`: passed.
- `python -m reckon_api.cli --help`: passed; the operator command is discoverable without
  reading settings or credentials.
- `alembic upgrade head --sql` with a PostgreSQL URL: generated short-name tables, columns,
  enum and RLS policies successfully without connecting to a database.
- Live Uvicorn smoke check: `GET /health/live` returned `{"status":"ok"}` and a valid
  `X-Request-ID`.
- Live Uvicorn smoke check: `GET /health/ready` returned 503 when no database is
  configured, as intended.
- Local PostgreSQL 18.7 initially applied `0001_identity_and_tenants`; it is now upgraded
  through the website migration.
- Local role/RLS check: `reckon` is not a superuser and cannot bypass RLS; `orgs`,
  `org_members`, `org_create_reqs` and `audit_events` all have RLS enabled and forced.
- Rollback-only live RLS check passed for tenant isolation and unset tenant context, with
  zero test rows remaining afterward.
- Live API with configured `.env`: liveness 200, readiness 200, and valid `X-Request-ID`;
  Vite-proxied readiness also returned 200.
- `npm --prefix apps/web run test`: 3 dashboard health tests passed.
- `npm --prefix apps/web run build`: TypeScript check and Vite production build passed.
- `npm --prefix apps/web run lint`: passed with no warnings.
- Browser smoke check: dashboard loaded at `http://127.0.0.1:5173/`; its Vite proxy returned
  API liveness 200 and rendered `/docs` from FastAPI. The UI showed API operational and DB
  unavailable when readiness returned 503, the theme toggle switched to dark mode, and a
  390px mobile viewport had no horizontal overflow.
- Browser OIDC/organization slice: `npm --prefix apps/web run test` passed with 11 tests,
  `npm --prefix apps/web run build` passed, and `npm --prefix apps/web run lint` passed.
- End-to-end login and organization creation were not exercised because no real public OIDC
  authority/client is configured. Website ownership verification was tested with an injected
  DNS resolver; no real DNS challenge was published or verified.
- Final backend regression: `python -m pytest` passed (72 tests), including live PostgreSQL
  RLS checks for `sites` and `site_create_reqs`.
- Website slice targeted tests passed (33 tests), covering DNS timeout handling, URL
  normalization, tenant authorization, idempotency, exact TXT verification and role-based
  challenge visibility.
- Final dashboard checks: `npm --prefix apps/web run test` passed (14 tests), `npm --prefix
  apps/web run build` passed, and `npm --prefix apps/web run lint` passed.
- `python -m compileall -q apps packages migrations tests` and `git diff --check` passed.
- Migration `alembic upgrade head --sql` generated website tables, composite tenant foreign
  keys and forced RLS policies; `alembic upgrade head` applied successfully and `alembic
  current` reported `0002_websites (head)`.
- The restarted local API reports readiness and exposes both website routes in OpenAPI.
- Browser smoke check shows API/database operational and the explicit OIDC setup prompt;
  no real login or live DNS challenge was attempted.

## Development continuation — 2026-11-20

- Hardened the pinned HTTP transport with a monotonic deadline-aware response stream. HTTP
  status/header parsing and incremental body reads now share the per-request deadline, while
  the crawler rejects results returned after its aggregate deadline.
- Added loopback tests for a normal pinned response and slowly trickled headers/body, plus a
  fake-clock regression for late aggregate results.
- Added robots.txt policy before homepage requests. The crawler uses its product token,
  follows bounded same-host redirects, treats only 404/410 as absent policy, denies other
  4xx responses and fails closed on server/network errors.
- DNS A/AAAA queries retain separate per-query bounds. Robots policy is now implemented in
  core. The tenant-authorized synchronous crawl API now persists idempotent evidence and audit
  outcomes under a configurable per-tenant daily cap. Dashboard controls, plan-specific quotas,
  multi-page crawling and retention remain future work.
- Validation: `python -m pytest -q` passed (111 tests);
  `python -m compileall -q apps packages migrations tests` and `git diff --check` passed.

## End-of-session handoff — 2026-11-19

- Website onboarding and DNS TXT ownership verification are implemented and covered by the
  existing API, core, RLS, and dashboard tests.
- Today's crawler work added DNS preflight and an isolated bounded homepage-fetch core. It is
  not wired to API/UI, and no external network request was made.
- The working tree contains uncommitted changes from earlier work as well as today's changes;
  preserve them all when resuming.
- Backend validation: `python -m pytest` passed, 94 tests. Python `compileall` and
  `git diff --check` passed.
- Resume with API-side crawl authorization for verified tenant websites, audit recording,
  tenant crawl limits, robots.txt policy, a user-facing crawl result, and transport-level
  verification of aggregate deadlines before exposing fetches. Keep OIDC provider configuration
  as a sign-in test dependency only; it is not a development prerequisite.
