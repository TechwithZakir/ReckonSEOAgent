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

**Current milestone: Website onboarding and ownership verification**

- [x] Establish the FastAPI application package and typed liveness contract.
- [x] Add an isolated API test and local developer commands.
- [x] Verify OIDC bearer tokens against an HTTPS JWKS endpoint with an explicit RS256 allowlist.
- [x] Resolve authenticated subjects to persisted users and active organization memberships.
- [x] Add PostgreSQL tenant row-level security for organizations and memberships.
- [x] Apply the PostgreSQL migration and verify tenant isolation with a non-bypass role.
- [x] Add authenticated, owner-assigned organization creation with request idempotency.
- [x] Record tenant-scoped organization-creation audit events with server request IDs.
- [x] Add controlled identity provisioning from a verified OIDC access token.
- [x] Add browser OIDC authorization-code sign-in with PKCE and in-memory token storage.
- [x] Add authenticated organization creation/selection and verify membership through the API.
- [x] Add tenant-scoped website registration with idempotent creation.
- [x] Verify website control using an exact DNS TXT challenge before enabling site status.
- [ ] Configure a real OIDC client and verify an end-to-end sign-in.
- [ ] Expand audit coverage; add member invitations and usage limits.
- [x] Add a responsive React dashboard shell with live API/database health checks.
- [x] Add dashboard authentication and organization setup.
- [x] Add owner/admin website onboarding and DNS verification UI.
- [x] Add a bounded DNS resolution gate that rejects non-public crawl targets.
- [x] Add an isolated single-homepage crawler core with pinned-IP requests and bounded redirects.
- [ ] Implement SSRF-hardened crawling and evidence-backed SEO audits.

The liveness endpoint confirms only that the API process responds. The readiness endpoint
checks the configured database. Authenticated organization access requires configured OIDC,
database migrations and an existing external-identity-to-user mapping and membership.
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

The example `.env` values are placeholders. Configure a real HTTPS OIDC issuer/JWKS and API
audience, and a PostgreSQL connection before using authenticated organization routes.
Production settings reject missing database or partial OIDC configuration.

## API foundation

- `GET /health/live`: process liveness only.
- `GET /health/ready`: verifies database connectivity.
- `GET /api/v1/organizations/{organization_id}/context`: returns a role only after verified
  bearer authentication and active membership.
- `POST /api/v1/organizations`: creates an organization and owner membership atomically;
  requires `Idempotency-Key`, records an audit event and returns `X-Request-ID`.
- `GET /api/v1/organizations/{organization_id}/websites`: lists only websites in an active
  member's organization; pending DNS challenge values are limited to owners/admins.
- `POST /api/v1/organizations/{organization_id}/websites`: owner/admin-only, idempotent
  website-origin registration and DNS TXT challenge creation.
- `POST /api/v1/organizations/{organization_id}/websites/{website_id}/verify`: owner/admin-only
  exact TXT verification; returns verified only after DNS confirms the challenge.

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
limits response bytes, and applies socket-operation timeouts. It is not exposed through the
API or dashboard; there is no crawl history, tenant metering, or robots.txt handling yet.
Aggregate timeout behavior still needs transport-level verification. No live external fetch
was performed.

## Dashboard preview

The dashboard displays live API/database health, supports configured OIDC sign-in, and lets
an authenticated, provisioned organization owner/admin register a website and complete DNS
TXT ownership verification. Membership is checked by the API before showing an organization
or its websites. Registration and DNS verification do not fetch the website; crawling,
SSRF-safe network access, and SEO data are not yet connected. The UI does not display
fabricated metrics. The dashboard requires Node.js 20.19+ or 22.12+.

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
