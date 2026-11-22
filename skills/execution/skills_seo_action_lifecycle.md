# Skill: SEO Action Lifecycle
Status: active

## Purpose
Propose, approve, claim, execute, verify and report externally visible SEO changes through the
governed lifecycle. Covers the Claude plugin and MCP path.

## Agent Composition
- Specialist agent: governed execution agent (plugin or runtime)
- Reusable with: WordPress execution, human approval, change verification, rollback
- Risk tier: medium/high (externally visible writes)
- Required evidence: current website evidence and captured before-state

## Typed Input
```json
{
  "website_id": "uuid",
  "action": {"kind": "wordpress.update_post", "target": "post id", "fields": {"title": "text"}},
  "reason": "text grounded in evidence"
}
```

## Typed Output
```json
{
  "proposal_id": "uuid",
  "status": "proposed|approved|claimed|executed|verified|rolled_back|failed",
  "requires_human_approval": true,
  "verification_required": true
}
```

## Authorized Tools
- `reckon.website.evidence.get`
- `reckon.seo_action.propose`
- `reckon.seo_action.approved.list`
- `reckon.seo_action.claim`
- `reckon.seo_action.report`

## Procedure
1. Read current evidence; never propose from memory.
2. Propose a minimal, typed change. The approval hash is never exposed to the proposer.
3. A different authorized human approves; a proposer must not approve their own medium/high-risk action.
4. Claim only approved, unexpired actions; execution is idempotent and checks target version.
5. Verify by independent read-back; report the verified result or the failure.
6. Roll back only when the live value still matches the executed value.

## Guardrails
- Never claim success without independent verification.
- Proposals expire; re-propose after target drift.
- Organization context comes from identity, never from tool arguments.
- No link manipulation, hidden text, cloaking or scaled low-value content.

## Evaluation Tests
- Unapproved or expired actions cannot be claimed
- Target drift blocks execution and rollback
- Cross-tenant claim and report are denied
- Report without verification is not marked successful
