# Reckon SEO Autopilot — Project Source of Truth

The supplied solution design and UI mock define the product baseline. This repository is
the single implementation of the central platform.

## Authoritative Workspace Files

- `README.md`: project overview, current delivery status and developer setup.
- `docs/DEVELOPMENT_LOG.md`: detailed implementation progress and decisions.
- `LICENSE`: proprietary project license and copyright notice.
- `pyproject.toml`: package author and machine-readable license metadata.
- `.github/copilot-instructions.md`: repository coding and safety instructions.
- `AGENTS.md`: agentic implementation workflow and engineering rules.
- `skills/`: reusable specialist agent skills.
- `skills/product/skills_solution_blueprint.md`: product and delivery decisions.
- `skills/product/skills_ui_design.md`: UI and Aura theme reference.
- `docs/ARCHITECTURE.md`: implemented and planned runtime boundaries.

## External Reference Files

The native design document and HTML mock remain reference attachments outside the
repository unless the user explicitly asks for them to be copied. The HTML mock is visual
guidance only and must not be claimed as implemented application code.

## Current Implementation Scope

The foundation includes FastAPI, verified OIDC tenant access, tenant-scoped persistence,
organization creation, audit events, request IDs and API health checks. The React dashboard
supports configured public-client OIDC login, organization selection, website registration
and DNS TXT ownership verification. The local PostgreSQL database is migrated through
`0002_websites`; RLS has been verified with a least-privileged role. Website verification
does not fetch site content. The shared core includes bounded A/AAAA resolution and rejects
non-public DNS answers, and an isolated bounded homepage fetcher uses the checked IP for
connections and restricts redirects to the verified host. The crawler is not exposed through
the API or dashboard; crawl history, tenant metering, robots.txt handling, and SEO audits
remain unimplemented. A local operator command provisions internal identities from verified
OIDC access tokens; it is not exposed as a public endpoint. No SEO metrics are fabricated.
