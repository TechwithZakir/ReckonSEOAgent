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
`0011_membership_discovery`; tenant RLS is exercised with a least-privileged role. The
dashboard can list and switch between an authenticated user's active organizations. Native
signup, sign-in, SMTP verification, invitations, member management and organization profile
editing remain planned. Owners and
admins can store one OpenAI or Anthropic model selection and encrypted API key per organization;
stored credentials are not yet used or verified by a provider. An internal model
token ledger and provider-neutral gateway boundary exist, but no real provider adapter, task
authorizer, agent runtime, public model API or reconciliation workflow is implemented. Website
verification does not fetch site content. The shared core performs bounded public DNS
validation, pinned-IP homepage requests, same-host redirects and robots.txt enforcement. The
authenticated API provides verified-site crawling, daily tenant budgets, idempotency, crawl
history, a non-cacheable tenant crawl-usage snapshot, interrupted-run recovery, and versioned deterministic homepage audit findings for
page metadata and indexability signals. Sitemap declarations in robots.txt are bounded to ten
same-host candidates. XML documents are fetched under strict byte/time limits and summarized as
tenant-scoped evidence. Validated sitemap-index children may be fetched to one level within the
shared document/time limits; page URLs are not fetched. Active members can start verified-site
crawls and inspect usage, recent results and findings from the dashboard. Broad technical audits,
sitemap coverage, multi-page crawling, and background execution remain unimplemented. A local
operator command provisions
internal identities from verified OIDC access tokens; it is not exposed as a public endpoint.
No synthetic SEO scores or metrics are fabricated.
