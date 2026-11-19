# Reckon SEO Autopilot — Project Source of Truth

The supplied solution design and UI mock define the product baseline. The implementation
repository must not duplicate the project for Agensi or Vibe96.

## Authoritative Workspace Files

- `README.md`: project overview, current delivery status and developer setup.
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

The Foundation milestone has started with the FastAPI application package, environment-backed
settings, typed liveness endpoint and focused API test. The liveness route checks only that
the process responds. Authentication, tenant-scoped persistence, readiness dependencies,
dashboard and integrations remain planned and must not be described as implemented.
