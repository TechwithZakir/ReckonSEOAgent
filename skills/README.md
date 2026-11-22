# Reckon SEO Autopilot Skills

These skills define reusable specialist behavior for Reckon SEO Autopilot. Agents compose
skills dynamically with typed contracts, least-privilege tools and evaluation requirements.

## Composition

An agent run must declare:

- Agent definition and purpose
- One or more skill files
- Authorized tools
- Model and budget policy
- Bounded steps and timeout
- Typed inputs and outputs
- Required evidence
- Evaluation, security and failure rules
- Tenant, user, website, task and policy attribution

## Categories

- `research/`: keyword, competitor, intent and SERP research
- `technical_seo/`: crawl, indexability, schema and performance
- `content/`: content audits, optimization, authority and briefs
- `on_page/`: page optimization, internal links and metadata
- `off_page/`: backlink and link-quality analysis
- `execution/`: WordPress/CMS, browser automation, verification and rollback
- `analytics/`: Search Console, performance and opportunities
- `governance/`: prompt defense, approval, tenancy, compliance and cost
- `reporting/`: reporting and recommendation prioritization
- `product/`: solution product, UX, SaaS and implementation knowledge

## Format and validation

Every skill follows `_skill_template.md`, including a `Status: active|planned` line.
`active` skills are backed by real code and may list only registered MCP tools; `planned`
skills document intent and grant no tools. `reckon_core.skills` loads and validates them and
`tests/core/test_skills.py` lints the whole directory. `product/` holds reference knowledge,
not agent skills.

Skills are guidance for deterministic and agent-assisted work. They must not grant tools or
bypass the central policy engine.

## Plugin tool name mapping

The Claude plugin (`plugins/reckon-seo-copilot`) exposes the same governed MCP tools under
bridge names. Skills here always use the API names.

| Plugin bridge name | API tool name |
|---|---|
| `reckon_crawl_list` | `reckon.crawl.list` |
| `reckon_start_crawl` | `reckon.crawl.start` |
| `reckon_website_evidence` | `reckon.website.evidence.get` |
| `reckon_engine_audit` | `reckon.engine.audit.get` |
| `reckon_propose_action` | `reckon.seo_action.propose` |
| `reckon_approved_actions` | `reckon.seo_action.approved.list` |
| `reckon_claim_action` | `reckon.seo_action.claim` |
| `reckon_report_action` | `reckon.seo_action.report` |
