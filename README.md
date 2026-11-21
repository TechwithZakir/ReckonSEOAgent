# Reckon SEO Autopilot

Reckon SEO Autopilot is an independent, AI-native, multi-tenant SEO operations platform.
Its core product is a governed agent runtime that turns website evidence into traceable
recommendations and, with authorization, verified actions.

This repository contains the central platform. The Aura HTML mock is a visual reference
only; this project does not use the Frappe framework.

## Ownership and license

Copyright © 2026 Reckon Technologies Ltd. All rights reserved. This project is proprietary;
see [LICENSE](./LICENSE). The package metadata uses `LicenseRef-Proprietary`.

## Development status

**Current milestone: Tenant-authorized homepage crawling and evidence-backed audits**

- [x] Establish the FastAPI application package and typed liveness contract.
- [x] Add an isolated API test and local developer commands.
- [x] Verify OIDC bearer tokens against an HTTPS JWKS endpoint with an explicit RS256 allowlist.
- [x] Resolve authenticated subjects to persisted users and active organization memberships.
- [x] Add PostgreSQL tenant row-level security for organizations and memberships.
- [x] Apply the PostgreSQL migration and verify tenant isolation with a non-bypass role.
- [x] Add authenticated, owner-assigned organization creation with request idempotency.
- [x] List and switch between an authenticated user's active organizations.
- [x] Let organization owners/admins view a paginated member roster.
- [x] Add approval-bound role changes and verified-email invitations (SMTP required for invitations).
- [x] Record tenant-scoped organization-creation audit events with server request IDs.
- [x] Add controlled identity provisioning from a verified OIDC access token.
- [x] Add browser OIDC authorization-code sign-in with PKCE and in-memory token storage.
- [x] Add an optional native email/password signup, verification and sign-in foundation.
- [x] Add a local-only, interactive bootstrap for an initial platform administrator.
- [x] Add email-based password recovery with session revocation.
- [x] Add authenticated organization creation/selection and verify membership through the API.
- [x] Add tenant-scoped website registration with idempotent creation.
- [x] Verify website control using an exact DNS TXT challenge before enabling site status.
- [ ] Configure a real OIDC client and verify an end-to-end sign-in.
- [x] Expand homepage audit coverage and usage limits.
- [x] Add a responsive React dashboard shell with live API/database health checks.
- [x] Add an internal tenant-scoped model-token ledger and provider-neutral gateway boundary.
- [x] Add typed composition and output validation for a read-only technical audit prioritizer.
- [x] Add organization AI settings for OpenAI or Anthropic with encrypted API-key storage.
- [x] Add tenant-visible AI usage records and evidence-bound unknown-outcome reconciliation.
- [x] Add dashboard AI usage visibility, reconciliation controls and specialist prioritization controls.
- [x] Add native account session listing and per-session revocation APIs.
- [x] Add encrypted TOTP MFA enrollment, challenge sign-in and disable APIs.
- [x] Add account-security, MFA challenge, session revocation and crawl-retention UI controls.
- [x] Add a shared typed organization permission matrix for tenant operations.
- [x] Add tenant crawl schedules for daily/weekly cadence with owner/admin CRUD and opt-in due-worker execution.
- [x] Add dashboard authentication and organization setup.
- [x] Add owner/admin website onboarding and DNS verification UI.
- [x] Add verified-site crawling, crawl history and audit evidence to the dashboard.
- [x] Add bounded depth-one same-host page discovery and page-evidence contracts.
- [x] Apply migration `0017_multi_page_crawl_evidence` for retained discovered URLs and page evidence.
- [x] Add opt-in Redis/Celery crawl dispatch with tenant revalidation and queue-failure reconciliation.
- [x] Add explicit owner/admin crawl-history retention purge, bounded to 1000 runs and protected against running deletion.
- [x] Add a bounded DNS resolution gate that rejects non-public crawl targets.
- [x] Add an isolated single-homepage crawler core with pinned-IP requests and bounded redirects.
- [x] Add tenant-authorized, metered homepage crawling with robots enforcement and history.
- [x] Capture versioned deterministic homepage audit findings with source evidence.
- [x] Parse bounded robots.txt sitemap XML and persist URL/index counts as evidence.
- [x] Run the read-only technical audit prioritizer through a tenant-bound gateway with typed output and unknown-outcome reconciliation.
- [x] Expand homepage checks with H2 structure, same-host links and image alt-text evidence.

The liveness endpoint confirms only that the API process responds. The readiness endpoint
checks the configured database. Authenticated organization access requires database
migrations and either a verified native account or a configured OIDC identity mapped to a
user. Access to an existing organization additionally requires an active membership.
`POST /api/v1/organizations` also requires a unique `Idempotency-Key` header. External
identities are currently provisioned through the controlled operator CLI below.

## Technology direction

- Python 3.12+, FastAPI and Pydantic
- SQLAlchemy 2.x, Alembic and PostgreSQL for durable tenant-scoped data
- Redis and Celery for bounded, observable background jobs
- React and TypeScript for the SaaS dashboard
- Isolated Playwright workers only for approved workflows that cannot use an API

Dependencies are introduced with the feature that needs them; unused infrastructure is not
pretended to be operational.
Database table/column names use compact physical forms; Python model attributes and API
fields remain descriptive.

## Quick start

Requires Python 3.12 or newer.

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
Copy-Item .env.example .env
# Edit .env with your database/OIDC server settings and the public VITE_OIDC authority/client ID.
alembic upgrade head
python -m uvicorn reckon_api.main:app --reload --app-dir apps\api\src
```

The example `.env` values are placeholders. Configure PostgreSQL and either native
authentication as described below or a real HTTPS OIDC issuer/JWKS and API audience before
using authenticated organization routes. Native authentication is disabled by default.
Production settings reject a missing database, partial OIDC, or native authentication without
the required SMTP settings.

## API foundation

- `GET /health/live`: process liveness only.
- `GET /health/ready`: verifies database connectivity.
- `GET /api/v1/auth/methods`: reports whether native sign-in and signup email are configured.
- `POST /api/v1/auth/signup`: requests an email verification link.
- `POST /api/v1/auth/verify`: verifies the link and creates an account with the chosen password.
- `POST /api/v1/auth/signin` and `/api/v1/auth/signout`: issue and revoke native sessions.
- `POST /api/v1/auth/password-reset` and `/api/v1/auth/password-reset/confirm`: request and
  complete password recovery. Completion revokes existing native sessions and reset links.
- `GET /api/v1/platform/access`: returns the authenticated user's platform-administrator status.
- `GET /api/v1/organizations/{organization_id}/context`: returns a role only after verified
  bearer authentication and active membership.
- `GET /api/v1/organizations`: cursor-paginated active memberships for the authenticated
  user; organization names are fetched under individual tenant scopes.
- `GET /api/v1/organizations/{organization_id}/members`: paginated member roster, restricted
  to active owners/admins. Native account emails are shown; external identity emails are not
  stored here.
- `POST /api/v1/organizations/{organization_id}/changes`: owner/admin proposal for an
  `invite` or `role_change`; requires an `Idempotency-Key` and returns a 15-minute approval hash.
- `POST /api/v1/organizations/{organization_id}/changes/{change_id}/approve`: the proposing
  manager approves the bound change. Owners manage all roles; admins manage editors/viewers.
  Invitations require configured SMTP; `smtp_accepted` does not confirm delivery. Uncertain
  notifications are not automatically resent.
- `GET /api/v1/invitations` and `POST /api/v1/invitations/{invitation_id}/accept`: discover
  and accept invitations using a matching verified native email. Discovery returns at most 50
  pending invitations, ordered by expiry; invitations expire after seven days.
- `POST /api/v1/organizations`: creates an organization and owner membership atomically;
  requires `Idempotency-Key`, records an audit event and returns `X-Request-ID`.
- `GET /api/v1/organizations/{organization_id}/websites`: lists only websites in an active
  member's organization; pending DNS challenge values are limited to owners/admins.
- `POST /api/v1/organizations/{organization_id}/websites`: owner/admin-only, idempotent
  website-origin registration and DNS TXT challenge creation.
- `POST /api/v1/organizations/{organization_id}/websites/{website_id}/verify`: owner/admin-only
  exact TXT verification; returns verified only after DNS confirms the challenge.
- `POST /api/v1/organizations/{organization_id}/websites/{website_id}/crawl`: active-member
  crawl of a verified site; requires `Idempotency-Key`, records an audit/evidence row, and
  reserves the organization's daily crawl budget before network access. The default limit is
  10 attempts per UTC day per organization, including failures and interrupted runs.
- `GET /api/v1/organizations/{organization_id}/crawl-usage`: returns the active member's
  organization-wide crawl attempts, limit, remaining allowance and UTC-day boundaries.
  The response is a non-cacheable snapshot, not a reservation: concurrent requests can
  change availability before a crawl starts.
- `GET /api/v1/organizations/{organization_id}/websites/{website_id}/crawls`: lists the
  authenticated member's crawl history for that website, newest first; supports `limit`
  (default 20, maximum 100) and `offset` pagination. Responses include the stored
  `homepage-v4` findings, evidence, impact, confidence, effort, recommendations and verification
  steps when a completed crawl has been audited. Raw indexability signals include X-Robots-Tag,
  robots meta noindex, a query-redacted canonical URL and bounded same-host sitemap references
  declared by robots.txt. Up to ten same-host sitemap documents are fetched after the homepage,
  under a four-second aggregate budget and 256 KiB per document. Responses report per-document
  status, XML type, unique URL or child-sitemap counts, rejected-entry counts and truncation.
  Validated sitemap-index children may be fetched to one level within the same ten-document
  budget; page URLs are never fetched. Fully analyzed URL sets report whether the homepage and
  same-host canonical URL were listed; incomplete analysis leaves membership unknown.

Set `RECKON_CRAWL_DAILY_LIMIT` to a positive integer to change the per-organization default
budget. Replaying a completed or robots-disallowed request with the same key returns its
stored result without consuming another crawl. On a subsequent crawl reservation, runs still
marked `running` after five minutes are finalized as interrupted; those attempts still count
toward the daily budget.

### Internal model gateway foundation

The internal model-usage ledger reserves input and output token ceilings against a supplied
organization daily limit. PostgreSQL row locks serialize reservations; unresolved reservations
continue to count across UTC days until settled. Trusted callers can record reported usage
idempotently, including provider overages, without storing prompts. The internal gateway
accepts injected trusted authorization and adapters, commits a bound reservation before
dispatch, rejects replays, and settles reported usage before returning a response. Timeouts
and other uncertain outcomes remain reserved; recognized uncertain outcomes produce an audit
event when it can be committed.

OpenAI and Anthropic adapters are currently used only by the organization settings test;
there is no general agent runtime, billing integration or operator reconciliation workflow.
The gateway relies on provider-reported usage and cannot independently verify it. Its
concurrency limit is per instance, and synchronous work can exceed the async timeout.
This foundation is not production-ready model metering.

The internal technical-audit prioritizer composition loads an allowlisted set of reusable
skills and accepts only deterministic finding metadata. Its output must contain exactly the
supplied finding codes. This is a composition and validation foundation, not an exposed or
executable agent workflow: tenant-scoped evidence loading, task authorization, model/budget
binding and durable run tracing still need to be connected before use.

### Organization AI settings

Owners and admins can open **System settings → AI model**, select OpenAI or Anthropic, enter
a model ID, API base URL and API key for their organization. The default base URLs are
`https://api.openai.com/v1` and `https://api.anthropic.com/v1`. One provider is stored at a time;
switching providers requires a new key and replaces the previous setting. Keys can also be
removed. They are encrypted with AES-256-GCM, are not returned by the API, and are not
validated against the provider when saved. Saving settings does not run a model request.

**Test AI** sends a short fixed prompt to the saved endpoint using the saved key, and may
incur provider charges. It reports success only after a valid response with usage; it does not
enable other AI features. Tests reserve up to 640 tokens against the organization's daily
limit (`RECKON_AI_TEST_DAILY_TOKEN_LIMIT`, default 10,000). Unconfirmed outcomes retain
their reservation across days and are not automatically retried; reconciliation is not yet
available. Concurrency is limited per API process, not globally.

The optional `endpoint_url` field in `PUT /api/v1/organizations/{organization_id}/ai-settings`
stores a custom HTTPS base URL for the active provider; omitting it preserves the current URL
for that provider or selects the official default when switching. Existing settings without a
stored endpoint use their provider's default. Custom URLs must use a public DNS hostname on
port 443, with no credentials, query or fragment. Do not put secrets in the URL. A future
test against a custom endpoint discloses the API key and fixed test prompt to its operator.
No DNS lookup or connection is performed when saving; testing resolves and pins public
addresses and rejects redirects.

To enable encrypted storage locally, first configure `.env` and run the migrations. If no
encryption key is already configured, this command adds one without displaying it:

```powershell
python -c "import base64,secrets; from pathlib import Path; p=Path('.env'); t=p.read_text(encoding='utf-8'); m='RECKON_CREDENTIAL_ENCRYPTION_KEY='; lines=t.splitlines(); assert not any(x.startswith(m) and x[len(m):].strip() for x in lines), 'Encryption key already configured; do not overwrite it.'; lines=[x for x in lines if not x.startswith(m)]; lines.append(m+base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()); p.write_text('\n'.join(lines)+'\n', encoding='utf-8')"
```

Keep the master key private, backed up securely, and stable across API instances. Do not
put it in a browser environment variable. Rotation and automated recovery are not implemented;
losing or changing it makes existing credentials unreadable until replaced. Restart the API
after configuring it. Use HTTPS outside localhost, including correctly configured trusted
proxy headers in staging/production. Disable request-body logging at proxies and gateways.
Local/test modes are not production security settings.
Authenticated sign-in and organization membership are still required.

### Native account setup

Native accounts are an early foundation, not production-ready. Apply the migrations and
configure the optional `RECKON_NATIVE_AUTH_ENABLED`, `RECKON_SMTP_HOST`, `RECKON_SMTP_PORT`,
`RECKON_SMTP_TLS`, `RECKON_SMTP_FROM` and `RECKON_WEB_PUBLIC_ORIGIN` settings shown in
[.env.example](./.env.example). If the SMTP service requires authentication, configure
`RECKON_SMTP_USERNAME` and `RECKON_SMTP_PASSWORD` together. Keep credentials server-side
and restart the API after configuration. The public web origin must be HTTPS outside local
development, and `/auth/verify` must serve the dashboard. Configure trusted proxy headers
correctly, disable request-body logging, and disable email link rewriting/tracking.

The recipient chooses a password after opening a single-use, 30-minute verification link.
Native access tokens are stored in browser memory, expire after one hour, and are revoked on
successful sign-out; refreshing the page requires signing in again. Account registration and
password recovery are unavailable until SMTP is configured. Recovery links are single-use,
expire after 30 minutes and revoke all native sessions and other recovery links. No real mail
provider was configured or tested here. Session management, email changes, invitations, MFA
and production abuse monitoring remain unimplemented; do not enable this foundation for
production accounts yet.

### Initial local platform administrator

After applying migrations, enable `RECKON_NATIVE_AUTH_ENABLED=true` for local sign-in.
Create the initial account from a private interactive terminal:

```powershell
python -m reckon_api.cli bootstrap-admin --email admin@example.com
```

Replace the example address with the intended administrator's email. Enter and confirm a
unique password privately at the prompts; never supply it on the command line. The command
is restricted to the local environment, refuses noninteractive input, existing accounts and
a second bootstrap, and stores an Argon2id hash rather than a password. It does not require
SMTP for this operator-created account. This is a platform role, not an organization
membership: normal tenant authorization still applies. Administrator-management operations
and production bootstrap are not yet implemented.

Open `/login` or use the dashboard **Sign in** button. Public signup still requires SMTP.

### Controlled identity provisioning

There is no public user-provisioning endpoint. An operator can map a verified external
identity to an internal user by supplying a short-lived access token in a restricted local
file:

```powershell
python -m reckon_api.cli provision-identity --token-file C:\secure\oidc-access-token.txt
```

Configure the OIDC issuer, audience and JWKS URL first. The command verifies the token's
signature and required claims, creates the user and identity mapping transactionally, and
is idempotent for an already provisioned identity. It never prints the token. Delete the
token file after use. Browser sign-in does not provision identities; the operator bootstrap
remains required before organization APIs are available.

### Browser sign-in configuration

Configure a public OIDC client using authorization code flow with PKCE. In the root `.env`,
set `VITE_OIDC_AUTHORITY` to the same issuer used by `RECKON_OIDC_ISSUER`, and set the public
`VITE_OIDC_CLIENT_ID`. Register these callback URLs with the provider:

- `http://127.0.0.1:5173/auth/callback`
- `http://127.0.0.1:5173/auth/signout-callback`

Set `VITE_OIDC_RESOURCE` only when the provider requires an API resource parameter; configure
the provider so its access-token audience is accepted by `RECKON_OIDC_AUDIENCE`. Restart
Vite after changing `.env`. `VITE_` values are shipped to browsers: never put a client secret,
database password, or API credential in them. The SPA keeps tokens in memory; session storage
is used only for the short-lived OIDC redirect transaction and the non-secret active
organization ID. A real login requires a configured provider/client and an operator-provisioned
identity.

### Website onboarding

After signing in with a provisioned identity and selecting an organization, an owner or admin
can register an HTTP(S) website origin. Add the displayed TXT record at the supplied DNS name,
wait for DNS propagation, then select **Verify DNS record**. A website is marked verified only
when the API finds the exact challenge value. The onboarding flow performs DNS TXT lookups
only; it does not fetch or crawl the website.

### Crawler safety foundation

The shared core has a bounded A/AAAA resolver, rejects non-public DNS answers, and includes
a bounded homepage fetcher that connects to the validated IP, validates same-host redirects,
limits response bytes, and applies a monotonic request deadline across response headers and
body reads. HTML results include deterministic title, meta-description and H1-count evidence;
non-HTML responses do not produce page metadata. Results arriving after the aggregate crawl
deadline are rejected. DNS A/AAAA lookups have separate per-query bounds. Before fetching
the homepage, the crawler retrieves and enforces `robots.txt`; only 404/410 are treated as an
absent policy, other 4xx responses
deny crawling, and server errors fail closed. Active members can start a verified-site crawl
from the dashboard; the API applies tenant-scoped daily reservations, idempotency, persistence
and audit events. Completed HTML crawls store deterministic
`homepage-v4` findings for non-success HTTP status, missing title, meta description and H1,
observed noindex directives, invalid or duplicate canonical links, and cross-host canonicals.
Findings are source-linked observations with explicit impact, confidence, effort,
recommendation and verification fields—not a synthetic SEO score or a complete indexability
verdict. Discovery examines at most 100 robots.txt declarations and retains up to ten unique,
normalized same-host URLs; invalid and external entries are counted as rejected. Sitemap XML is
parsed with byte and entry limits, rejects DTD/entity declarations, obeys robots rules, and only
counts unique same-host locations. A capped set of validated sitemap-index children can be
fetched to one level within the same ten-document and four-second limits; page URLs are never
fetched, so sitewide sitemap coverage remains incomplete. Fully analyzed URL sets also record
whether the homepage and same-host canonical were listed, suppressing absence findings when
coverage is incomplete. No live external fetch was performed.

## Dashboard preview

The dashboard displays live API/database health, supports configured OIDC sign-in, and lets
an authenticated, provisioned organization owner/admin register a website and complete DNS
TXT ownership verification. Active organization members can start crawls for verified sites,
refresh recent crawl history and inspect evidence-backed findings. Membership is checked by
the API before showing an organization, its websites or crawl history. Registration and DNS
verification do not fetch the website. The website section shows a refreshable snapshot of
the organization's shared daily crawl budget; actual reservations are enforced by the API.
For each verified website, the latest crawl summary shows reported finding counts, sitemap
document count and homepage response, with expandable history and evidence. Missing data is
shown as unavailable rather than zero.
The overview also shows account setup, access to site evidence and live API/database status
before sign-in; it does not display fabricated site data or metrics. The
dashboard requires Node.js 20.19+ or 22.12+.

With the API running at `http://127.0.0.1:8000`, open a second PowerShell terminal:

```powershell
cd apps\web
npm install
npm run dev
```

Open `http://127.0.0.1:5173`. The Vite development server proxies health, API and OpenAPI
documentation requests to the local FastAPI server. Open `http://127.0.0.1:8000/docs` for
the API directly or `http://127.0.0.1:8000/health/live` for its liveness response.

Optional local settings are listed in [`.env.example`](./.env.example); copy it to `.env`
before changing them. Its author/license comments are informational only; ownership and
license are defined by the project metadata and `LICENSE`, not runtime environment values.

## Tests

```powershell
python -m pytest
```

For the dashboard, from `apps\web` run:

```powershell
npm test
npm run build
npm run lint
```

## Repository map

```text
apps/api/src/reckon_api/   FastAPI application
apps/web/                  React + TypeScript dashboard
tests/api/                 API contract tests
tests/core/                Tenant and token security tests
packages/core/src/         Shared identity, tenant and persistence primitives
migrations/                PostgreSQL schema and row-level security
skills/                    Reusable specialist agent skills
docs/                      Product and engineering documentation
```

## Product and engineering references

- [Agent instructions](./AGENTS.md)
- [Copilot instructions](./.github/copilot-instructions.md)
- [Project source of truth](./docs/PROJECT_SOURCE_OF_TRUTH.md)
- [Architecture](./docs/ARCHITECTURE.md)
- [Development log](./docs/DEVELOPMENT_LOG.md)
- [Specialist skills](./skills/README.md)

Every agent/tool composition must be typed, least-privilege, tenant-attributed, bounded,
budgeted, observable and evaluated. Crawled and externally supplied text is untrusted.
External writes require shared policy/approval checks and independent verification; SEO
manipulation, fake reviews, cloaking, hidden text and scaled low-value content are out of
scope.
