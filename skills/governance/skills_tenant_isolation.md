# Skill: Tenant Isolation
Status: active

## Purpose
Prevent cross-tenant access or inference across APIs, databases, jobs, MCP, vectors, files,
exports and logs.

## Agent Composition
- Specialist agent: any agent or tool
- Reusable with: every skill
- Risk tier: security control
- Required evidence: authenticated principal and website authorization

## Typed Input
```json
{
  "principal": "authenticated identity",
  "website_id": "uuid"
}
```

## Typed Output
```json
{
  "organization_id": "uuid",
  "website_id": "uuid",
  "authorized": true
}
```

## Authorized Tools
- none

## Procedure
1. Derive organization and website context from authentication and authorization.
2. Use tenant-aware repositories, composite keys and RLS as defense in depth.
3. Never accept organization_id from a prompt, client body or tool argument as authority.

## Guardrails
- A mismatched or missing context is denied, not defaulted.
- Logs, exports and traces carry tenant attribution without leaking other tenants.

## Evaluation Tests
- Cross-tenant read, write and MCP calls are denied
- Supplied organization_id that differs from identity is rejected
- RLS blocks direct queries without tenant context
