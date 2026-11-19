# Reckon SEO Autopilot

Reckon SEO Autopilot is an independent, AI-native, multi-tenant SEO operations platform.
Its core product is a governed agent runtime that turns website evidence into traceable
recommendations and, with authorization, verified actions.

This repository is the central platform. Agensi and Vibe96 are distribution layers, not
separate copies of the SEO engine. The Aura HTML mock is a visual reference only; this
project does not use the Frappe framework.

## Development status

**Current milestone: Foundation — API bootstrap**

- [x] Establish the FastAPI application package and typed liveness contract.
- [x] Add an isolated API test and local developer commands.
- [ ] Implement authentication, organization membership and tenant-scoped persistence.
- [ ] Add usage limits, audit events, dashboard shell and local service orchestration.
- [ ] Implement website onboarding and evidence-backed SEO audits.

The health endpoint confirms only that the API process responds. It does not claim that a
database, queue, provider, or customer integration is available.

## Technology direction

- Python 3.12+, FastAPI and Pydantic
- SQLAlchemy 2.x, Alembic and PostgreSQL for durable tenant-scoped data
- Redis and Celery for bounded, observable background jobs
- React and TypeScript for the SaaS dashboard
- Isolated Playwright workers only for approved workflows that cannot use an API

Dependencies are introduced with the feature that needs them; unused infrastructure is not
pretended to be operational.

## Quick start

Requires Python 3.12 or newer.

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
python -m uvicorn reckon_api.main:app --reload --app-dir apps\api\src
```

Open `http://127.0.0.1:8000/docs` for the local OpenAPI UI and
`http://127.0.0.1:8000/health/live` for the liveness response.
Optional local settings are listed in [`.env.example`](./.env.example); copy it to `.env`
before changing them.

## Tests

```powershell
python -m pytest
```

## Repository map

```text
apps/api/src/reckon_api/   FastAPI application
tests/api/                 API contract tests
skills/                    Reusable specialist agent skills
docs/                      Product and engineering documentation
```

## Product and engineering references

- [Agent instructions](./AGENTS.md)
- [Copilot instructions](./.github/copilot-instructions.md)
- [Project source of truth](./docs/PROJECT_SOURCE_OF_TRUTH.md)
- [Architecture](./docs/ARCHITECTURE.md)
- [Specialist skills](./skills/README.md)

Every agent/tool composition must be typed, least-privilege, tenant-attributed, bounded,
budgeted, observable and evaluated. Crawled and externally supplied text is untrusted.
External writes require shared policy/approval checks and independent verification; SEO
manipulation, fake reviews, cloaking, hidden text and scaled low-value content are out of
scope.
