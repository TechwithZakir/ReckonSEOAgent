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
- `server/reckon_mcp_bridge.py`: thin bridge to the Reckon MCP tool API (needs Python 3.12+
  and `httpx`; no other dependencies).

## Configuration

Set these in the environment that launches Claude. Never commit them.

| Variable | Meaning |
| --- | --- |
| `RECKON_API_URL` | Reckon API base URL. HTTPS only; plain HTTP is accepted for localhost. |
| `RECKON_ORGANIZATION_ID` | The one organization this plugin acts for. Not a tool argument. |
| `RECKON_ACCESS_TOKEN` | Bearer token of a Reckon member with the Admin or Owner role. |

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
- Only `heading` (post/page title) has a verified WordPress mapping. Other action types can be proposed as recommendations but are not executed by the skills.
- The skills use whatever WordPress tool Claude has; the plugin does not bundle one or store WordPress credentials.
