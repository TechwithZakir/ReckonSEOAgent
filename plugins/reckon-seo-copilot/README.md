# Reckon SEO Copilot plugin for Claude

Lets Claude read Reckon's audited website evidence, propose SEO changes for human
approval, and carry out approved changes, with Reckon verifying the result itself.

## Contents

- `.claude-plugin/plugin.json`: plugin manifest.
- `.mcp.json`: starts the stdio bridge in `server/reckon_mcp_bridge.py`.
- `skills/crawl-website`: start and monitor a governed Reckon crawl.
- `skills/seo-site-review`: read evidence, rank findings, propose changes.
- `skills/execute-approved-actions`: claim, apply, read back and report approved changes.
- `skills/wordpress-apply-action`: WordPress playbook and the state contract Reckon verifies.
- `skills/wordpress-chrome-admin`: governed fallback that drives wp-admin through the Claude Chrome extension.
- `skills/seo-audit-loop`: crawl, propose, approve, apply and re-crawl until the audit is clean.
- `server/reckon_mcp_bridge.py`: thin bridge to the Reckon MCP tool API (needs Python 3.12+
  and `httpx`; no other dependencies).

## Configuration

Set these in the environment that launches Claude. Never commit them.

| Variable | Meaning |
| --- | --- |
| `RECKON_API_URL` | Reckon API base URL. HTTPS only; plain HTTP is accepted for localhost. |
| `RECKON_ORGANIZATION_ID` | The one organization this plugin acts for. Not a tool argument. |
| `RECKON_ACCESS_TOKEN` | A scoped plugin token (`rkpt_…`, preferred) or a member session token. The member must be Admin or Owner. |

### Scoped plugin tokens

An Owner or Admin issues a token with `POST /api/v1/organizations/{id}/plugin-tokens`
(`label`, optional `scopes`, `lifetime_days` 1-90). The plaintext is shown once. A token works
only in its own organization, only for its listed tools, and only on MCP tool routes, so it
cannot manage tokens or call any other API. The issuing member's role still applies, and
`DELETE .../plugin-tokens/{token_id}` revokes it at once. Default scopes exclude
`reckon.crawl.start`; add it explicitly if the plugin should start crawls. Treat the token as
a secret and never commit it.

## Tools

| Tool | Purpose |
| --- | --- |
| `reckon_crawl_list` | Recent crawl runs. |
| `reckon_start_crawl` | Start a governed crawl (needs crawl-run permission; quota, robots and DNS rules apply). |
| `reckon_website_evidence` | Latest completed crawl evidence (flagged untrusted). |
| `reckon_engine_audit` | Evidence-derived engine audit. |
| `reckon_propose_action` | Pending proposal only (low/medium risk, idempotent). |
| `reckon_approved_actions` | Human-approved, unexpired actions. |
| `reckon_claim_action` | Reserve one action; a second claim returns 409. |
| `reckon_report_action` | Report `executed` or `failed`; Reckon verifies independently. |

There is deliberately no approve or reject tool. Approval happens in Reckon by a human.

## Trust model

- Tenant identity comes from the token and `RECKON_ORGANIZATION_ID`; arguments that try to
  name an organization are rejected.
- Arguments are validated before any request. Redirects are not followed, responses are
  size-capped, and errors never include the token.
- A write counts as verified only when Reckon's own read-back confirms it
  (`verified_by_reckon: true`). Without a Reckon verifier the action stays `executed`.

## Current limits

- The access token is a normal member session token. There are no dedicated plugin tokens
  or OAuth scopes yet, so it carries that member's full permissions and expires with the
  session.
- Reckon's verifier must be enabled (staging WordPress executor) for actions to reach
  `verified`.
- Verifiable action types are `meta_title`, `meta_description`, `canonical`, `heading` and `schema`. Reckon confirms them by re-reading the public page (`CMS_PUBLIC_VERIFICATION_ENABLED`, default on outside tests). `redirect`, `internal_link` and `other` stay recommendations. A page cache can delay verification.
- The Chrome path needs the user to be signed in to wp-admin in their own browser; the plugin never handles WordPress credentials.
- The skills use whatever WordPress tool Claude has; the plugin does not bundle one or store WordPress credentials.
