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

### Specialist-agent composition foundation

- Added a typed, read-only technical audit prioritizer composition. It loads the technical
  audit, prioritization, prompt-injection and tenant-isolation skills from an allowlist,
  includes only deterministic finding metadata in model input, and accepts only a complete
  permutation of the supplied finding codes. It grants no tools.
- Added a runnable core/API vertical slice for the read-only prioritizer. It loads only
  completed tenant/website crawl findings, binds a fixed task policy and model budget,
  executes through the existing model gateway, validates the typed result and records
  started/completed/unknown/invalid audit events. Unknown outcomes return 502 and preserve
  gateway reservations without claiming success. The API route uses idempotency, settings
  binding and the allowlisted skill root; no real provider request is made by tests.

### AI provider test

- Added a manager-only, metered **Test AI** action with OpenAI Responses and Anthropic
  Messages adapters. It sends a fixed prompt to the saved endpoint, pins validated public
  DNS addresses, disables redirects, bounds response size and returns usage only after a
  valid provider response. Custom endpoints receive the key and prompt.
- The default organization budget is 10,000 tokens per day; each test reserves 640 tokens
  before dispatch. Unknown outcomes remain reserved across days without automatic retry or
  an operator reconciliation workflow. Concurrency limits are per API process.
- Provider tests use mocked responses only. Actual provider connectivity remains unverified
  until an authorized user deliberately runs a test.

### AI usage visibility and reconciliation

- Added manager-only tenant AI usage listing and reconciliation APIs. Usage remains
  tenant-attributed and exposes reserved/settled state, limits, reported tokens and timestamps.
  Only reservations with a recorded unknown-outcome audit event can be reconciled, and
  reconciliation requires confirmed usage counts plus an independent verification reference.

### Broader homepage technical audits

- Extended the isolated homepage crawler with bounded H2, same-host internal-link and image
  alt-text evidence. The deterministic homepage audit emits medium/low-impact findings with
  source URLs and verification guidance. No additional crawl or page fetch occurs.

### Bounded multi-page crawl evidence

- Added a depth-one discovered-page crawler. It normalizes same-host HTML links, removes
  tracking fragments/query parameters from evidence, de-duplicates URLs, applies robots.txt,
  caps discovered pages at 10 and uses an aggregate 15-second page phase. External hosts,
  unsafe URLs and non-page responses are recorded or rejected without a second-hop fetch.
- Added additive `0017_multi_page_crawl_evidence` persistence/API contracts for discovered URLs
  and page evidence. The migration was applied with explicit operator approval and confirmed
  at `0017_multi_page_crawl_evidence (head)`. The local API was started and
  `/health/live` and `/health/ready` returned HTTP 200.

### Redis/Celery crawl dispatch

- Added opt-in Redis/Celery crawl dispatch configuration. By default, crawls remain synchronous.
  When enabled, the API reserves and audits the crawl, sends a tenant-bound task containing
  organization, website, run, actor and request IDs, and returns `running`. The worker
  rechecks tenant membership and website/run state before execution and has no blind retry.
  Queue failures mark the run `failed` as `crawl_queue_unavailable`.
- No Redis broker or Celery worker was started, and no real crawl or provider request was made
  during implementation. Tests inject the queue and verify that no synchronous crawler call
  occurs and worker payload IDs match the persisted run.
 - Redis was unavailable on `127.0.0.1:6379`, so no worker was started. The latest API process
  was restarted with explicit approval; liveness and readiness returned HTTP 200.

### Explicit crawl-history retention

- Added a server-derived retention cutoff from `RECKON_CRAWL_HISTORY_RETENTION_DAYS`
  (default 365, bounded 30–3650 days) and an owner/admin-only purge API. Purges delete at most
  1000 terminal crawl rows older than the cutoff, preserve running rows, and record an audited
  count/cutoff/reason event. Cleanup is never automatic and requires an explicit reason.
 - Applied with explicit restart approval; the local API liveness/readiness checks returned 200.

### Organization profile management

- Added an owner/admin organization profile rename API and dashboard control. Updates are
  tenant-scoped, audited and limited to 1–200 characters. Viewer accounts receive 403.

### AI usage and specialist dashboard visibility

- Added dashboard controls for AI usage reservations and evidence-bound reconciliation.
  Reserved and settled usage remain visible, and reconciliation requires confirmed token
  counts and an independent verification reference. Added crawl-history specialist run controls
  for the existing read-only prioritizer with unknown/invalid outcome messaging.

### Native account session management

- Added native-account session listing and per-session revocation. Listings expose only a
  SHA-256 session fingerprint, expiry and current-session indicator; raw bearer tokens are
  never returned or written to audit details. Revocation is tenant-independent account state,
  scoped to the authenticated native user, and audited.

### Native-account TOTP MFA

- Added encrypted TOTP secret enrollment, 5-minute challenge sign-in, confirmation and disable
  APIs. TOTP secrets use the existing credential master key and are never returned after
  enrollment except by the one-time enrollment response. Challenge values are hashed in
  PostgreSQL/SQLite and consumed once. Invalid codes remain explicit and do not create sessions.
- Applied migration `0018_native_mfa` with explicit approval and restarted the local API.

### Shared organization permission matrix

- Added a central typed role-to-capability matrix for organization view, member management,
  website verification, crawl and purge operations, AI settings/usage and specialist runs.
  Existing API role checks now use this matrix for least-privilege decisions; target-specific
  rules such as admin limits on owner/admin membership changes remain additional checks.

### Account, MFA and retention UI

- Added an Account Security dashboard section for native-account TOTP enrollment,
  confirmation, disable and active-session revocation.
- Added MFA challenge handling to the native sign-in form.
- Added an owner/admin crawl-history purge form with an explicit reason and refreshed history
  after successful cleanup.
- MCP tools and CMS workflows remain backend-planned and are not represented as available UI controls.

### Tenant crawl schedules

- Added migration `0019_crawl_schedules` for tenant-scoped daily/weekly crawl cadence.
- Added owner/admin CRUD API and dashboard controls, and a bounded due-schedule Celery task.
  Due schedules reserve the tenant crawl budget and dispatch the existing tenant-revalidated
  crawl task. Redis/Celery execution remains opt-in and no broker is running locally.

### Local Redis and MCP/CMS foundation

- Installed Redis 8.10.3 locally and started it on loopback port 6379. Started separate
  Celery worker and beat processes; Redis/HELLO and an initial due-schedule task succeeded.
- Added read-only tenant MCP tool discovery and invocation routes for crawl history and schedules.
  Tool names and inputs are typed, tenant membership is revalidated and no MCP write operation is
  exposed.
- Added a provider-neutral CMS adapter contract and public-DNS-pinned WordPress discovery adapter.
  CMS writes remain disabled and approval-required. Discovery tests use mock transports; no real
  WordPress endpoint or credential was contacted.
- Real OIDC, SMTP, provider API keys and WordPress application passwords remain intentionally
  unconfigured. `.env.example` contains names only; secrets belong in the local `.env` or
  organization credential storage and must never be committed.

### AI provider endpoints

- Added editable, organization-scoped API base URLs with official OpenAI and Anthropic
  defaults, public-hostname/HTTPS syntax checks and the existing encrypted key handling.
  One provider remains active at a time. Saving does not validate or contact the endpoint.
- Applied migration `0016_model_endpoint` and restarted the API with operator approval.
  Targeted validation passed: 20 backend tests, including PostgreSQL tenant isolation, and
  57 dashboard tests, plus dashboard lint/build and a live API fixture. No provider was
  contacted at that stage.

### Organization creation foreign-key fix

- Organization creation now flushes the organization before its membership, idempotency
  record and audit event, while keeping all writes in one transaction. Added API coverage
  with SQLite foreign keys enabled and a non-bypass PostgreSQL test for creation, replay,
  tenant-scoped records and rollback.

### Phase 21: organization management

- Added owner/admin review and approval flows for role changes and email invitations,
  including last-owner protection, idempotency, membership-version checks and audit events.
  Invitations are discoverable only by a matching verified native email; OIDC-only accounts
  and the locally bootstrapped unverified administrator cannot accept them.
- Added dashboard management controls and an invitations page. SMTP is required for new
  invitations; SMTP acceptance is not delivery verification, and uncertain sends are not
  automatically retried.
- Applied migration `0015_org_management` and restarted the local API with operator approval.
  PostgreSQL tests cover recipient isolation, stale manager authorization, concurrent approval
  and acceptance, and the last-owner race. No real mail was sent. SMTP remains unconfigured,
  so new invitations cannot yet be approved locally.
- Validation: 203 backend and 56 dashboard tests passed; dashboard lint/build and API
  liveness/readiness passed. The invitations and login navigation were checked in a browser.
  Invitation discovery currently shows at most 50 pending invitations, ordered by expiry.

### Phase 20: organization member roster

- Added a paginated active-member roster for owners and admins, with tenant-scoped membership
  checks, manager revalidation and non-cacheable responses. Native account emails are shown;
  external identity emails are not stored. PostgreSQL RLS and API tests cover isolation and
  unauthorized roles.
- Added a member view to connected workspaces. At that phase invitations, role changes and
  last-owner protections remained unimplemented.
- Restarted the local API with user approval and verified the roster with isolated browser
  fixtures. Validation: 193 backend tests and 51 dashboard tests passed; dashboard
  lint/build and Python compilation passed.

### Phase 19: password recovery

- Added rate-limited email recovery with hashed, 30-minute single-use links and generic
  responses. Resetting a password invalidates other recovery links and revokes existing native
  sessions. PostgreSQL account locks serialize concurrent sign-in and password reset.
- Added **Forgot password** and reset screens on `/login`. Applied migration
  `0014_password_reset` and restarted the local API with user approval. SMTP is still
  unconfigured, so recovery and public signup remain unavailable; no real email was sent.
- Tested fixture recovery, replay, expiry, email failure, session revocation and concurrent
  PostgreSQL sign-in/reset. Member invitations and role management are still future stages.
- Validation: 191 backend and 50 dashboard tests passed. Dashboard lint/build, Python
  compilation, changed-file Pylance diagnostics, and browser navigation/recovery fixtures
  passed.

### Phase 18: local administrator and login navigation

- Added a singleton initial platform-administrator role and a local-only interactive bootstrap
  command. Passwords are prompted privately and hashed; existing accounts are not promoted,
  and bootstrap cannot replace an existing administrator. The role does not bypass tenant
  membership checks and currently has no platform-management operations.
- Added a dedicated `/login` page with browser back/forward navigation and a visible dashboard
  sign-in button. Native and OIDC sign-in paths remain available when configured.
- Applied migration `0013_platform_admin`, enabled local native sign-in and restarted the API
  with user approval. The operator initialized the administrator using the private prompt.
  Public registration still needs SMTP; administrator management is not yet implemented.

### Phase 17: native account foundation

- Added optional email-first signup, Argon2id password verification, single-use verification
  tokens, one-hour revocable bearer sessions and persistent request limits. Verification
  links carry their token in a fragment, the dashboard clears it, and sensitive validation
  errors and account responses are not cached or reflected.
- Added dashboard signup, verification, sign-in and sign-out while retaining OIDC. Browser
  tokens remain in memory. An isolated browser fixture exercises the complete UI flow; no
  real email or provider was contacted.
- Applied migration `0012_native_auth` and restarted the local API with user approval.
  SMTP and native accounts remain disabled, so the forms are visible but unavailable.
  Password recovery, MFA, member invitations, account management, operational abuse controls
  and production hardening remain future work; do not treat this as production-ready.
- Validation: 183 backend tests and 49 dashboard tests passed, including fixture-based
  PostgreSQL signup and concurrent rate limiting under the non-bypass application role.
  Mocked SMTP and browser authentication, dashboard lint/build, Python compilation and
  changed-file Pylance diagnostics passed. No real email was sent.

### Phase 16: organization discovery and switching

- Added authenticated, cursor-paginated organization discovery with a read-only RLS policy
  restricted to the current user's active memberships. Organization details are individually
  tenant-scoped and membership is rechecked when switching.
- The workspace UI lists organizations, supports pagination, creation and verified switching,
  and retains the existing connect-by-ID option. Applied local migration
  `0011_membership_discovery`; PostgreSQL tests exercise isolation using a non-bypass role.
- At this phase native signup/sign-in and SMTP were not yet implemented; member invitations,
  role management, organization profile editing and account controls remain future phases.
- Validation: 176 backend tests and 45 dashboard tests passed; dashboard lint/build and Python
  compilation passed. The switcher was browser-tested with isolated fixture data.
- With user approval, restarted the local API and verified the organization routes and API
  and dashboard-proxy readiness. Real sign-in remains unconfigured.

### Phase 15: organization AI settings

- Added owner/admin-only provider and model settings, encrypted per-organization API-key
  storage, removal, no-store responses, credential-safe validation errors and audit events.
  PostgreSQL RLS and locked membership checks protect tenant-scoped writes. Model and key
  validity are not checked with providers, and stored settings are not connected to an adapter.
- Added the dashboard System settings entry and an AI model form. The encryption key must be
  configured server-side, OIDC membership is required, and no secret is returned by the API.
  Staging/production writes require HTTPS; key rotation and recovery remain unimplemented.
- Applied the additive local `0010_org_model_settings` migration. No real provider credentials
  or network requests were used.
- Validation: 174 backend tests and 43 dashboard tests passed; dashboard lint/build and Python
  compilation passed. The unsigned-in settings navigation was checked on desktop and mobile.
- With user approval, configured a local encryption key and restarted the local API; API and
  dashboard-proxy readiness returned HTTP 200. Real OIDC sign-in remains unconfigured.

### Phase 14: internal model gateway boundary

- Added typed gateway contracts and injected trusted policy and adapter interfaces. Membership
  and role are checked, a request-bound reservation is committed before dispatch, and replay
  cannot dispatch again. Reported usage is committed before returning; provider overages remain
  recorded and raise an error. A deadline reached before dispatch settles zero usage.
- Unknown provider outcomes and caller cancellation keep reservations charged; recognized
  outcomes record tenant-scoped audit details when possible. A per-instance semaphore remains
  occupied until the adapter task finishes, including when it ignores cancellation.
- Only fake adapters and authorizers exist; no real provider call was made. Provider reports
  are trusted rather than independently verified, synchronous work can exceed the async
  timeout, and there is no distributed concurrency limit or operator reconciliation. Real
  task policy, provider integration, production metering and agent runtime remain future work.
- Validation: 167 backend tests passed, including live PostgreSQL RLS and gateway checks;
  Python compilation and `git diff --check` passed.

### Phase 13: model token reservation foundation

- Added typed model reservation and usage-report contracts and a tenant-scoped PostgreSQL
  ledger with forced RLS, idempotency binding, organization-level reservation locking and
  transactionally recorded audit events. Unresolved reservations remain charged across UTC
  days; settled usage above the reservation is retained and can block future reservations.
- Applied the additive local `0009_model_usage` migration. Concurrent-budget and RLS tests use
  the least-privileged local PostgreSQL role and clean up their test records.
- At this phase no model gateway, provider calls, provider-report verification, public usage
  endpoint or reconciliation workflow was added. The ledger alone is not a complete enforcement
  boundary; integrations must commit before calls, enforce provider limits and reject replays.

### Phase 12: website and crawl-results view

- Expanded the connected website workspace and added a latest-crawl summary with reported
  finding impacts, sitemap document count and homepage response. The latest run opens by
  default; earlier runs remain expandable, and findings show their source and impact.
- Kept unavailable evidence separate from zero reported findings, retained sitemap
  truncation and membership details, and avoided showing an empty website list after a
  loading error. The dashboard still requires a provisioned OIDC identity and verified
  website for real crawl data.

### Phase 11: visible operations overview

- Added dashboard cards for account access, website evidence and live platform health,
  including setup and website navigation actions. The overview remains useful before
  authentication without showing invented SEO results.
- Preserved verified-site crawl and tenant authorization requirements; site details and
  usage still require a connected organization.

### Phase 10: local readiness and crawl budget visibility

- Restarted the local API with its configured project environment after the existing process
  reported no database configuration. Direct PostgreSQL access and API readiness succeeded;
  no production deployment or real OIDC account connection was performed.
- Added a non-cacheable organization crawl-usage endpoint and a dashboard snapshot for active
  members. The snapshot uses the same UTC window and tenant-scoped reservation count as
  enforcement, counts failed attempts, and is not an allowance guarantee under concurrency.
- Real browser sign-in remains dependent on an externally configured OIDC provider and
  operator-provisioned identity. Other usage categories and agent metering remain future work.

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
- HTML crawl results now capture bounded title and meta-description text plus an H1 count using
  the deterministic parser. These observations are persisted and returned as crawl evidence;
  non-HTML responses omit page metadata.
- Added the deterministic `homepage-v2` audit for non-success HTTP status, missing title/meta
  description/H1, noindex directives, and invalid, duplicate or cross-host canonical links.
  X-Robots-Tag and robots meta signals are recorded independently; canonical query strings are
  stripped. Findings include URL, direct evidence, impact, confidence, effort, recommendation
  and verification; no score or complete indexability verdict is computed. Findings and rule
  version are persisted with crawl runs and returned consistently in history.
- Crawl results retain robots.txt status and up to ten normalized, query-redacted sitemap URLs
  declared for the verified host. Discovery examines at most 100 declarations; invalid or
  external examined entries are counted as rejected, and truncation is explicit. Sitemap
  documents are then fetched within a four-second aggregate budget and 256 KiB per-document
  limit. The parser rejects DTD/entity declarations, obeys robots rules, and stores counts of
  unique same-host URLs or sitemap-index children. It retains capped child references and may
  fetch one child level under the same ten-document/four-second budget; it never fetches page URLs.
- Added the deterministic `homepage-v3` sitemap audit. It reports empty parsed documents and
  incomplete sitemap analysis when fetches fail, entries are rejected, or bounded parsing/fetch
  limits prevent complete inspection; it does not infer a sitewide indexability score.
- Added `homepage-v4` URL-set membership evidence for the crawled homepage and same-host
  canonical. Absence findings are emitted only when all discovered sitemap documents and child
  references were completely analyzed; unknown or incomplete coverage remains explicit.
- A later crawl reservation now reconciles runs still marked `running` after five minutes as
  `worker_interrupted`, timestamps and audits the recovery, and preserves their daily budget
  charge. Recent in-progress idempotent retries remain conflicts; crawl history exposes stored
  error codes.
- Added an active-member crawl-history endpoint scoped to one website, with stable newest-first
  ordering, bounded limit/offset pagination and tenant-context RLS.
- Applied migrations through `0008_sitemap_document_evidence` to local PostgreSQL 18.7 and extended
  live RLS/concurrency integration tests. The API uses an injected crawler in tests; no live
  external site was fetched.
- Added the dashboard's first crawl workflow: active members can start a crawl for verified
  websites, inspect persisted findings and sitemap evidence, and refresh recent history.
  Crawl responses must validate before the UI reports completion; ambiguous retries reuse
  their idempotency key. Multi-page crawl, plan-specific quotas, retention/cleanup, and
  background execution remain unimplemented.

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
- The dashboard supports onboarding and a narrow crawl/history workflow; broader technical
  audit controls, multi-page workflows and agent-run operations remain unimplemented.
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
