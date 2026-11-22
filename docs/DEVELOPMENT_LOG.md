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
- Added one-time MFA recovery codes. Codes are hashed at rest, regenerated in a batch, shown
  once in the Account Security UI and consumed atomically with MFA sign-in. Applied migration
  `0020_native_mfa_recovery` with explicit approval.

### Platform administration operations

- Added platform-admin-only read-only summary and audit event routes. Summary data covers
  organizations, active memberships, native accounts and active native sessions. Audit events
  are bounded and ordered newest-first. Regular users receive 403 and unauthenticated callers
  receive 401; no tenant impersonation or mutation is available.

### Shared organization permission matrix

- Added a central typed role-to-capability matrix for organization view, member management,
  website verification, crawl and purge operations, AI settings/usage and specialist runs.
  Existing API role checks now use this matrix for least-privilege decisions; target-specific
  rules such as admin limits on owner/admin membership changes remain additional checks.

### Evidence-only SEO engine verticals

- Added typed audit engines for keyword intent review, content studio, ecommerce, enterprise,
  media/query and emerging GEO analysis. Findings come only from crawl/page evidence and never
  fabricate search volume, rankings or answer-engine mentions.
- Added explicit unavailable states for LinkPilot and local SEO until approved provider or
  verified business-profile data is configured. Added the tenant-bound
  `/engines/{engine}` API and dashboard engine panels.

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

### Approved SEO action lifecycle

- Added immutable, tenant-scoped SEO action proposals with exact target-version binding,
  before/proposed/after/verification/rollback state, risk, expiry and approval hashes.
- Added approve/reject/execute/verify/rollback API routes and an Approval Inbox UI.
- Execution is disabled without a confirmed executor. Test environments use a fixture executor
  that verifies proposed state and restores before-state; no real CMS write is performed.

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

Reconciled 2026-11-22 against the code (migrations through 0021; multi-page crawl, crawl
schedules, Celery dispatch, MFA, CMS adapters, MCP tools, SEO action lifecycle, WordPress
executor, SEO engines and the Claude plugin now exist). Remaining gaps:

- Real OIDC sign-in is unverified end to end; SMTP is unconfigured locally; Redis/Celery has
  not been exercised against a live worker; no real WordPress write has been performed.
- WordPress execution uses one global site from environment settings. Per-website,
  tenant-scoped encrypted CMS credentials are required before multi-tenant use.
- MCP tool calls are now metered per organization per UTC day (`reckon_core.tool_metering`,
  `RECKON_MCP_DAILY_TOOL_CALL_LIMIT`, default 500, HTTP 429 when exceeded; calls are recorded
  as `mcp.tool_call` audit events). Direct `/seo-actions` dashboard routes and outbound
  WordPress API calls are still unmetered, and there is no HTTP-level 429 test yet.
- Billing/plans are intentionally out of scope; they will be integrated later with the
  Reckon SaaS module.
- Migrations 0017/0019/0020 reviewed: 0017 only adds columns to an RLS table, 0019 enforces
  RLS, 0020 holds per-user identity data (not organization-owned).
- Only one agent exists (`GovernedPrioritizationAgent`). No agent runtime with tenant evidence
  loading, durable traces or evaluation suite.
- `apps/worker`, `apps/mcp_server`, `apps/browser_gateway`, `packages/ai_engine` and
  `packages/seo_engine` do not exist; the code lives in `packages/core` and `apps/api`.
- Provider-backed capabilities (Search Console, backlinks, SERP, Core Web Vitals, LinkPilot,
  local SEO) are planned; the matching skills are marked `Status: planned`.
- Plan quotas, retention/cleanup, deployment, backup/restore remain unverified.
- Test gaps: prompt-injection regression for MCP evidence tools, an HTTP-level 429 metering
  test, and interactive (click/submit) component tests. Smoke tests now exist for
  `SeoActionInbox`, `PlatformOperations`, `AccountSecurity`, plus unit tests for
  `lib/seo-actions.ts` and `crawl_worker.py` (Celery config and enqueue; no live broker).
- Run web tests from PowerShell/cmd (`npx vitest run` in `apps/web`); under Git Bash the `/d/...`
  path breaks vitest ("reading 'config'").
- The database role used by deployment must not be a superuser or have `BYPASSRLS`.

## Roadmap (from 2026-11-22)

1. Agent runtime v1: tenant-scoped evidence, trusted task authorizer, durable traces,
   API/dashboard control, agent-evaluation tests.
2. Real WordPress execution on staging with per-website encrypted credentials.
3. Extract `ai_engine`, `seo_engine`, `worker` and `mcp_server` from the monolith.
4. Production readiness: OIDC, SMTP, live Celery, plan quotas, deploy/backup.
5. Provider-backed capabilities and the isolated browser gateway.

## Review and skills update — 2026-11-22

- Reviewed commits 9393b3c..d80ea6a (all authored by the repository owner; no Copilot branch).
- WordPress executor config now raises explicit errors instead of `assert`.
- Medium/high-risk actions cannot be approved by their proposer.
- `.sf/` (Salesforce CLI artifacts) untracked and ignored.
- Added `reckon_core.skills` (loader/validator) and `tests/core/test_skills.py`; all skills
  now follow `skills/_skill_template.md` with `Status: active|planned`. Active skills:
  technical audit, recommendation prioritization, prompt injection defense, tenant isolation,
  SEO action lifecycle. `specialist_agents.build_prioritization_request` validates through
  the loader.

## Session persistence and metering follow-up — 2026-11-22

- Page refresh no longer signs the user out: native sessions are kept per tab in
  `sessionStorage` (`auth/native-session-store.ts`) with an absolute expiry, re-validated
  against `GET /api/v1/auth/sessions` before being trusted, and cleared on sign-out, expiry or
  a 401. OIDC users are also kept per tab instead of in memory. The open page and theme
  survive a refresh. Trade-off: an opaque, server-revocable token is readable by script in that
  tab; an httpOnly-cookie session would be stronger and is a future hardening item.
- After a refresh the user must still reconnect the workspace (organization) selection.
- Mid-session revocation (a 401 from any API call while signed in) is not yet turned into an
  automatic sign-out.
- The daily tool-call cap now covers MCP routes and the dashboard `/seo-actions` routes
  (`reckon_api/tool_metering.py`); HTTP 429 and prompt-injection regression tests added.
- Plugin bridge names are mapped to API tool names in `skills/README.md`.
- Agent runtime v1 not started: it needs a real model provider key to verify end to end.

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

## WordPress staging executor and MCP proposal tool — 2026-11-21

- Added `WordPressActionExecutor` (`reckon_core/wordpress_executor.py`): single-field
  (`heading` → post/page `title`) REST writes bound to the one configured HTTPS site. It
  pins every request to a public DNS answer, never follows redirects, checks the live
  `modified_gmt` and before-value against the approved proposal, confirms each write by an
  independent read-back, and refuses rollback if the value changed after execution. Other
  action types fail closed until explicitly mapped.
- The executor is created only when `RECKON_CMS_WORDPRESS_EXECUTION_ENABLED=true` together
  with the WordPress credentials, and never in `production` or `test`. Credentials are
  global to the deployment, so use a dedicated staging site; execution additionally requires
  a verified website whose host equals the action target host.
- Proposals must target the selected website's host; execute and rollback re-check that the
  website is verified.
- Added MCP tool `reckon.seo_action.propose`: creates a pending proposal only (manager role,
  no high-risk, idempotent, audited with `channel: mcp`) and withholds the approval hash;
  approval and execution stay on the human lifecycle API.
- Removed a duplicate SEO action router registration.
- Validation: `python -m pytest tests -q` passed (281 tests). No real WordPress request was
  made; tests use mock transports. The running API was not restarted.
- Still open: live staging WordPress credentials and a real drill, MCP OAuth scopes, backup/restore drill, browser egress isolation.

## Claude plugin execution via Reckon SEO Copilot MCP — 2026-11-21

- Decision: WordPress changes are performed by the Claude plugin, not by Reckon's REST
  executor. The direct `WordPressActionExecutor` stays disabled by default and is only used,
  when explicitly enabled, as Reckon's independent read-back verifier.
- New MCP tools (manager role, tenant-scoped, audited with `channel: mcp`):
  `reckon.seo_action.approved.list` (unexpired approved actions per website),
  `reckon.seo_action.claim` (approved → executing; a second claim returns 409 so only one
  executor writes) and `reckon.seo_action.report` (`executed` or `failed` plus the state the
  plugin observed).
- A report moves the action to `verified` only if Reckon's own verifier read-back confirms
  it. With no verifier configured the action stays `executed` (unverified) and the response
  has `verified_by_reckon: false`. A mismatch marks it `failed`. Repeating an identical
  report is idempotent; a different one returns 409. Rollback remains available to managers.
- Known limit: a claimed action whose plugin never reports stays `executing`; an operator
  must resolve it manually.
- Validation: `python -m pytest tests -q` passed (283 tests). The running API was not
  restarted; no real request was made.

## Reckon SEO Copilot Claude plugin — 2026-11-21

- Added read MCP tools `reckon.website.evidence.get` (latest or chosen completed crawl,
  response flagged `untrusted_content`) and `reckon.engine.audit.get`. Both need crawl-view
  access and are tenant-scoped; the 404 for another tenant's website matches existing routes.
- Added `plugins/reckon-seo-copilot`: Claude plugin manifest, `.mcp.json`, two skills
  (site review/propose; execute approved) and a stdlib+httpx stdio MCP bridge. The bridge
  fixes the tenant from operator config, validates arguments, derives deterministic
  idempotency keys for proposals, refuses redirects and oversized results, never echoes the
  token, and has no approve/reject tool.
- Validation: `python -m pytest tests -q` passed (297 tests); a stdio `tools/list` smoke
  test returned all seven tools. No real Claude session, WordPress site or provider call was
  made, and the API was not restarted (the new API tools need a restart to be served).
- Limits: plugin access uses a member session token (no scoped plugin tokens/OAuth yet);
  verification needs Reckon's staging verifier enabled; the plugin cannot start crawls.

## Plugin crawl tool and WordPress skills — 2026-11-21

- Added MCP tool `reckon.crawl.start`, which calls the existing governed crawl route
  (verified website, idempotency, daily quota, robots.txt, public-DNS pinning, optional
  Celery queue) and additionally requires the `crawl.run` permission. The bridge exposes it
  as `reckon_start_crawl` with a fresh or caller-supplied idempotency key, so re-crawls work
  and retries do not duplicate.
- Added skills `crawl-website` and `wordpress-apply-action` and linked the review and execute
  skills to them. The documented state contract (`wp_type`, `wp_id`, `value`, `modified_gmt`
  as `target_version`) is covered by a lifecycle test: a plugin report for a write that did
  not happen ends `failed`; a real write is `verified` by Reckon's own read-back.
- Only `heading` (post/page title) is executable and verifiable today. Other action types are
  recommendations; the skills do not claim them.
- Validation: `python -m pytest tests -q` passed (300 tests). No real crawl, WordPress or
  Claude request was made; the running API still needs an approved restart to serve the new
  tools.

## Workspace restore on refresh — 2026-11-22

- Bug: the selected page persisted across refresh but the organization was only restored by
  `WorkspaceSetup`, which renders on Overview only. Refreshing on Websites or any other page
  left `workspace` null, so those pages asked to connect again.
- Fix: `App` now restores the saved organization (re-verified through
  `getOrganizationContext`, so membership is still checked by the API) on every non-Overview
  page; a 404 clears the saved selection. `activeOrganizationKey` moved to `lib/organizations`.
- Validation: `tsc -b` clean, Vitest 94 passed. No browser refresh test or new regression
  test was added yet.

## Workspace restore regression test — 2026-11-22

- Moved the refresh-restore logic into `restoreSavedOrganization` in `lib/organizations`
  (re-verifies membership through the API, clears the saved selection only on 404, never
  calls the API when nothing is saved). `App` now calls it. Added 3 Vitest cases.
- Validation: `tsc -b` clean; `npx vitest run --pool=vmThreads` passed (97 tests); Python
  `pytest tests -q` passed (312 tests).
- Environment note: with the default Vitest pools every web test file currently fails with
  `Cannot read properties of undefined (reading 'config')` (Vitest 5.1.1 on Node 24.14.1);
  `--pool=vmThreads` works. Not yet fixed in `vite.config.ts`.
- Still open: live staging WordPress drill, MCP OAuth/scoped plugin tokens, stale `executing`
  claim recovery, backup/restore drill, browser egress isolation. These need credentials,
  infrastructure or product decisions and were not started.

## Claude Chrome extension as governed WordPress fallback — 2026-11-22

- Decision (owner): WordPress changes the REST path cannot make are applied by the Claude
  Chrome extension driving wp-admin. Chrome is a fallback, not the default; REST stays
  preferred (AGENTS.md). Approval, claim, before-state, one-field scope and independent
  verification are unchanged. "100/100" means a clean Reckon audit confirmed by re-crawl,
  never a ranking or third-party score.
- Added `PublicPageVerifier` (`reckon_core/public_page_verifier.py`): read-only; re-fetches
  the proposal URL through the crawler's pinned-DNS, redirect-checked, size-bounded fetcher
  and compares the live HTML with the approved value for `meta_title`, `meta_description`,
  `canonical`, `heading` (exactly one H1) and `schema` (JSON-LD equality). It rejects a
  reported value that differs from the approved one, non-200 pages, private DNS and
  cross-host redirects, and cannot write or roll back.
- `report` MCP route verifies with the REST executor when configured, else the public
  verifier (`app.state.seo_action_verifier`, setting `cms_public_verification_enabled`,
  default on, never set in `test`).
- Plugin skills: `wordpress-chrome-admin` (wp-admin procedure, no credential handling, stop
  on CAPTCHA/re-auth, untrusted page text) and `seo-audit-loop` (crawl, propose, wait for
  approval, apply, re-crawl, max three rounds). `execute-approved-actions` now picks the path.
- Validation: `python -m pytest tests -q` passed (324 tests; 12 new). No real WordPress,
  Chrome session or crawl was exercised; the running API needs a restart to use this.
- Limits: page caches can delay verification; a title template suffix must be included in the
  value; a claimed action whose plugin never reports still stays `executing`; the plugin still
  uses a member session token.

## Vitest default pool fix — 2026-11-22

- Set `test.pool: 'vmThreads'` in `apps/web/vite.config.ts`, so plain `npm test` works on
  Vitest 5.1.1 / Node 24 without the CLI flag.
- Validation: `npm test` passed (97 tests); Python `pytest tests -q` passed (324 tests);
  `tsc -b` clean.
