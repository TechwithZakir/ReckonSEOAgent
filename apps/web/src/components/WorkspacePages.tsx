import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { AccountSecurity } from './AccountSecurity'
import { AIModelSettings } from './AIModelSettings'
import { OrganizationMembers } from './OrganizationMembers'
import { SeoActionInbox } from './SeoActionInbox'
import { WebsiteOnboarding } from './WebsiteOnboarding'
import type { OrganizationContext } from '../lib/organizations'
import { downloadAuditEvents, listAuditEvents } from '../lib/organizations'
import type { AuditEvent } from '../lib/organizations'
import { getEngineAudit, listCrawls } from '../lib/crawls'
import type { EngineAudit, EngineName } from '../lib/crawls'
import { listWebsites } from '../lib/websites'

type Props = {
  page: string
  accessToken: string
  organization: OrganizationContext | null
}

function pageHeading(kicker: string, title: string, description: string) {
  return (
    <div className="mock-page__heading">
      <div>
        <p className="section-kicker">{kicker}</p>
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
    </div>
  )
}

function LiveAuditFeed({
  accessToken,
  organization,
}: {
  accessToken: string
  organization: OrganizationContext
}) {
  const [events, setEvents] = useState<AuditEvent[]>([])
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let active = true
    void listAuditEvents(accessToken, organization.organization_id)
      .then((rows) => { if (active) { setEvents(rows); setError(null) } })
      .catch((cause: unknown) => {
        if (active) setError(cause instanceof Error ? cause.message : 'Could not load audit events.')
      })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [accessToken, organization.organization_id])

  if (loading) return <p>Loading audit events…</p>
  if (error) return <p className="workspace-setup__error" role="alert">{error}</p>
  if (events.length === 0) return <p>No tenant audit events are recorded yet.</p>
  return (
    <div className="mock-grid">
      {events.slice(0, 12).map((event) => (
        <article className="workspace-card" key={event.event_id}>
          <div className="workspace-card__content">
            <span className="status-label status-label--muted">{event.action}</span>
            <h3>{event.resource_type}</h3>
            <p>{new Date(event.created_at).toLocaleString()} · Request {event.request_id}</p>
          </div>
        </article>
      ))}
    </div>
  )
}

function LiveEnginePanel({
  accessToken,
  organization,
  engine,
}: {
  accessToken: string
  organization: OrganizationContext
  engine: EngineName
}) {
  const [audit, setAudit] = useState<EngineAudit | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let active = true
    void (async () => {
      const websites = await listWebsites(accessToken, organization.organization_id)
      const verified = websites.find((website) => website.verification_status === 'verified')
      if (!verified) {
        if (active) {
          setAudit(null)
          setError('A verified website is required before an engine audit.')
        }
        return
      }
      const crawls = await listCrawls(
        accessToken,
        organization.organization_id,
        verified.website_id,
      )
      const completed = crawls.find((crawl) => crawl.status === 'completed')
      if (!completed) {
        if (active) {
          setAudit(null)
          setError('A completed crawl is required before this engine audit.')
        }
        return
      }
      const result = await getEngineAudit(
        accessToken,
        organization.organization_id,
        verified.website_id,
        completed.crawl_id,
        engine,
      )
      if (active) {
        setAudit(result)
        setError(null)
      }
    })().catch((cause: unknown) => {
      if (active) setError(cause instanceof Error ? cause.message : 'Could not load engine audit.')
    }).finally(() => {
      if (active) setLoading(false)
    })
    return () => { active = false }
  }, [accessToken, organization.organization_id, engine])

  if (loading) return <p>Loading engine evidence…</p>
  if (error) return <p className="workspace-setup__error" role="alert">{error}</p>
  if (!audit) return <p>No engine audit is available.</p>
  return (
    <div className="workspace-card">
      <div className="workspace-card__content">
        <span className={`status-label ${audit.coverage === 'complete' ? 'status-label--healthy' : 'status-label--muted'}`}>
          Coverage: {audit.coverage}
        </span>
        <h2>{audit.version}</h2>
        {audit.findings.map((finding) => (
          <article key={finding.code}>
            <h3>{finding.title}</h3>
            <p>{finding.evidence}</p>
            <p><strong>Recommendation:</strong> {finding.recommendation}</p>
            <p><strong>Verification:</strong> {finding.verification}</p>
          </article>
        ))}
      </div>
    </div>
  )
}

export function WorkspacePages({ page, accessToken, organization }: Props) {
  const [messages, setMessages] = useState<{ role: 'user' | 'assistant'; text: string }[]>([])
  const [prompt, setPrompt] = useState('')
  const [mcpTools, setMcpTools] = useState<{ name: string; read_only: boolean; tenant_scoped: boolean }[]>([])
  const [mcpError, setMcpError] = useState<string | null>(null)
  const [cmsStatus, setCmsStatus] = useState<'checking' | 'configured' | 'not-configured' | 'error'>('not-configured')

  useEffect(() => {
    let active = true
    void fetch('/api/v1/mcp/tools', { cache: 'no-store' })
      .then(async (response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`)
        return await response.json() as unknown
      })
      .then((value) => {
        if (active && Array.isArray(value)) setMcpTools(value as { name: string; read_only: boolean; tenant_scoped: boolean }[])
      })
      .catch((cause: unknown) => {
        if (active) setMcpError(cause instanceof Error ? cause.message : 'Could not load MCP tools.')
      })
    return () => { active = false }
  }, [])

  useEffect(() => {
    if (!accessToken || !organization) {
      return
    }
    let active = true
    void fetch(`/api/v1/organizations/${encodeURIComponent(organization.organization_id)}/cms/wordpress/discover`, {
      headers: { Authorization: `Bearer ${accessToken}` },
      cache: 'no-store',
    }).then(async (response) => {
      if (active) setCmsStatus(response.ok ? 'configured' : response.status === 503 ? 'not-configured' : 'error')
    }).catch(() => {
      if (active) setCmsStatus('error')
    })
    return () => { active = false }
  }, [accessToken, organization])

  if (page === 'Websites') {
    return (
      <section className="mock-page">
        {pageHeading('WEBSITE KNOWLEDGE GRAPH', 'Website Intelligence', 'A live view of your verified properties and crawl evidence.')}
        {organization ? (
          <WebsiteOnboarding
            accessToken={accessToken}
            organization={organization}
          />
        ) : (
          <div className="workspace-card workspace-card--connected">
            <div className="workspace-card__content">
              <h2>Connect a workspace</h2>
              <p>Website intelligence is available after organization and website authorization.</p>
            </div>
          </div>
        )}
      </section>
    )
  }

  if (page === 'Technical audits') {
    return (
      <section className="mock-page">
        {pageHeading('EVIDENCE-BASED DIAGNOSTICS', 'SEO Audits', 'Run bounded crawls and inspect deterministic findings tied to source URLs.')}
        {organization ? (
          <>
            <WebsiteOnboarding accessToken={accessToken} organization={organization} />
            {organization.role !== 'viewer' && (
              <LiveAuditFeed accessToken={accessToken} organization={organization} />
            )}
          </>
        ) : (
          <div className="workspace-card workspace-card--connected">
            <div className="workspace-card__content">
              <h2>Connect a workspace</h2>
              <p>Audits require a verified website and active organization membership.</p>
            </div>
          </div>
        )}
      </section>
    )
  }

  if (page === 'AI Agent Control') {
    return (
      <section className="mock-page">
        {pageHeading('GOVERNED AGENT OPERATIONS', 'AI Agent Control', 'Trace specialist work through typed inputs, policy, usage and audit events.')}
        <div className="mock-grid mock-grid--three">
          {[
            ['Technical SEO Agent', 'Deterministic homepage and sitemap evidence', 'Read-only prioritization'],
            ['Crawl Worker', 'Tenant-bound queued crawl execution', 'Redis/Celery opt-in'],
            ['Execution Agent', 'Approval-bound external work', 'Not yet implemented'],
            ['Search Intelligence Agent', 'Provider-neutral research', 'Not yet implemented'],
            ['Content Strategy Agent', 'Evidence-grounded briefs', 'Not yet implemented'],
            ['Execution Governance', 'Approval, target and rollback checks', 'Partially implemented'],
          ].map(([name, description, status]) => (
            <article className="workspace-card mock-agent-card" key={name}>
              <div className="workspace-card__content">
                <span className="status-label status-label--muted">{status}</span>
                <h3>{name}</h3>
                <p>{description}</p>
              </div>
            </article>
          ))}
        </div>
      </section>
    )
  }

  if (page === 'Agent activity') {
    return (
      <section className="mock-page">
        {pageHeading('TRACEABLE AGENT WORK', 'Agent activity', 'Recent tenant-attributed actions, crawls and model operations.')}
        {organization ? (
          organization.role === 'viewer' ? (
            <div className="workspace-card">
              <div className="workspace-card__content">
                <h2>Administrator access required</h2>
                <p>Audit event history is restricted to organization owners and admins.</p>
              </div>
            </div>
          ) : (
            <LiveAuditFeed accessToken={accessToken} organization={organization} />
          )
        ) : (
          <div className="workspace-card">
            <div className="workspace-card__content">
              <h2>Connect a workspace</h2>
              <p>Agent activity is tenant-scoped.</p>
            </div>
          </div>
        )}
      </section>
    )
  }

  if (page === 'Recommendations') {
    return (
      <section className="mock-page">
        {pageHeading('RECOMMENDATION QUEUE', 'Recommendations', 'Evidence-backed recommendations are available through crawl findings and specialist prioritization.')}
        {organization ? (
          <>
            <div className="workspace-card">
              <div className="workspace-card__content">
                <h2>Crawl findings are the current recommendation source</h2>
                <p>Open Websites or SEO Audits, run a verified crawl, and use specialist prioritization. Publishing and external changes remain approval-controlled.</p>
              </div>
            </div>
            {organization.role !== 'viewer' && (
              <LiveAuditFeed accessToken={accessToken} organization={organization} />
            )}
          </>
        ) : (
          <div className="workspace-card">
            <div className="workspace-card__content">
              <h2>Connect a workspace</h2>
              <p>Recommendations require website evidence and organization authorization.</p>
            </div>
          </div>
        )}
      </section>
    )
  }

  if (page === 'Approvals') {
    return (
      <section className="mock-page">
        {pageHeading('HUMAN-IN-THE-LOOP GOVERNANCE', 'Approval Inbox', 'Review organization and access proposals through the bound approval workflow.')}
        {organization ? (
          <>
            <SeoActionInbox accessToken={accessToken} organization={organization} />
            <OrganizationMembers accessToken={accessToken} organization={organization} />
          </>
        ) : (
          <div className="workspace-card">
            <div className="workspace-card__content">
              <h2>Connect a workspace</h2>
              <p>Approval operations require an active organization.</p>
            </div>
          </div>
        )}
      </section>
    )
  }

  if (page === 'Agency Workspace') {
    return (
      <section className="mock-page">
        {pageHeading('MULTI-CLIENT OPERATIONS', 'Agency Workspace', 'Manage client organizations and team access through tenant-scoped organization controls.')}
        {organization ? (
          <OrganizationMembers accessToken={accessToken} organization={organization} />
        ) : (
          <div className="workspace-card">
            <div className="workspace-card__content">
              <h2>Connect a workspace</h2>
              <p>Select or create an organization to manage client access.</p>
            </div>
          </div>
        )}
      </section>
    )
  }

  if (page === 'Ask SEO Copilot') {
    const submit = (event: FormEvent<HTMLFormElement>) => {
      event.preventDefault()
      const value = prompt.trim()
      if (!value) return
      setMessages((current) => [
        ...current,
        { role: 'user', text: value },
        {
          role: 'assistant',
          text: 'This workspace has no live model chat endpoint connected. Use the technical crawl, audit, prioritization and approval surfaces until an authorized provider chat adapter is configured.',
        },
      ])
      setPrompt('')
    }
    return (
      <section className="mock-page">
        {pageHeading('CONVERSATIONAL SEO INTELLIGENCE', 'Ask SEO Copilot', 'Live chat is unavailable until a provider and bounded chat task policy are configured.')}
        <div className="workspace-card mock-chat">
          <div className="workspace-card__content mock-chat__messages" aria-live="polite">
            {messages.length === 0 && (
              <p>Ask about crawl evidence, schedules or access policies. Live model responses require saved AI settings and a chat authorization policy.</p>
            )}
            {messages.map((message, index) => (
              <div className={`mock-chat__message mock-chat__message--${message.role}`} key={`${message.role}-${index}`}>
                {message.text}
              </div>
            ))}
          </div>
          <form className="mock-chat__form" onSubmit={submit}>
            <input
              value={prompt}
              onChange={(event) => setPrompt(event.target.value)}
              placeholder="Ask about your evidence-backed SEO workspace"
              maxLength={500}
            />
            <button className="button button--primary" type="submit">Send</button>
          </form>
        </div>
      </section>
    )
  }

  if (page === 'System settings') {
    return (
      <section className="mock-page">
        {pageHeading('PLATFORM CONFIGURATION', 'Workspace Settings', 'Manage AI providers, credentials and account security.')}
        {organization && (
          <AIModelSettings
            accessToken={accessToken}
            organization={organization}
          />
        )}
        {accessToken && (
          <AccountSecurity accessToken={accessToken} />
        )}
      </section>
    )
  }

  if (page === 'Site Bot') {
    return (
      <section className="mock-page">
        {pageHeading('AUTONOMOUS MONITORING', 'Site Bot', 'Review scheduled crawl policies and execution status.')}
        {organization ? (
          <WebsiteOnboarding accessToken={accessToken} organization={organization} />
        ) : (
          <div className="workspace-card">
            <div className="workspace-card__content">
              <h2>Connect a workspace</h2>
              <p>Bot scheduling requires a tenant, verified website and active Redis/Celery execution policy.</p>
            </div>
          </div>
        )}
      </section>
    )
  }

  if (page === 'Integrations') {
    return (
      <section className="mock-page">
        {pageHeading('CONNECTIONS', 'Integrations', 'Review MCP, CMS and external provider configuration states.')}
        <div className="mock-grid mock-grid--three">
          <article className="workspace-card">
            <div className="workspace-card__content">
              <span className="status-label status-label--healthy">Read-only MCP ready</span>
              <h3>MCP tools</h3>
              {mcpError && <p className="workspace-setup__error" role="alert">{mcpError}</p>}
              {mcpTools.length === 0 && !mcpError && <p>Loading tool inventory…</p>}
              {mcpTools.map((tool) => <p key={tool.name}>{tool.name}</p>)}
            </div>
          </article>
          <article className="workspace-card">
            <div className="workspace-card__content">
              <span className={`status-label ${cmsStatus === 'configured' ? 'status-label--healthy' : 'status-label--muted'}`}>
                {cmsStatus === 'configured' ? 'CMS discovery verified' : cmsStatus === 'checking' ? 'Checking CMS' : cmsStatus === 'not-configured' ? 'Not configured' : 'Discovery unavailable'}
              </span>
              <h3>WordPress CMS</h3>
              <p>Read-only capability discovery. External writes remain disabled until approval and verification are implemented.</p>
            </div>
          </article>
          <article className="workspace-card">
            <div className="workspace-card__content">
              <span className="status-label status-label--muted">Credentials deferred</span>
              <h3>Search / AI providers</h3>
              <p>OIDC, SMTP, OpenAI/Anthropic and other providers remain unconfigured until local credentials are supplied.</p>
            </div>
          </article>
        </div>
      </section>
    )
  }

  if (page === 'Reports') {
    return (
      <section className="mock-page">
        {pageHeading('REPORTING', 'Reports', 'Export and review tenant-scoped audit activity when an organization is connected.')}
        {organization ? (
          organization.role === 'viewer' ? (
            <div className="workspace-card">
              <div className="workspace-card__content">
                <h2>Administrator access required</h2>
                <p>Audit reports are restricted to organization owners and admins.</p>
              </div>
            </div>
          ) : (
            <>
              <div className="workspace-card">
                <div className="workspace-card__content">
                  <button
                    className="button button--secondary"
                    type="button"
                    onClick={() => void downloadAuditEvents(accessToken, organization.organization_id)}
                  >
                    Export audit CSV
                  </button>
                </div>
              </div>
              <LiveAuditFeed accessToken={accessToken} organization={organization} />
            </>
          )
        ) : (
          <div className="workspace-card">
            <div className="workspace-card__content">
              <h2>Connect a workspace</h2>
              <p>Reports are tenant-scoped and require a selected organization.</p>
            </div>
          </div>
        )}
      </section>
    )
  }

  if (
    [
      'Keywords',
      'Content Studio',
      'LinkPilot',
      'Local SEO',
      'E-Commerce',
      'Enterprise',
      'Media & Query',
      'Emerging / GEO',
    ].includes(page)
  ) {
    const engineByPage: Record<string, EngineName> = {
      'Keywords': 'keywords',
      'Content Studio': 'content_studio',
      'LinkPilot': 'linkpilot',
      'Local SEO': 'local_seo',
      'E-Commerce': 'ecommerce',
      'Enterprise': 'enterprise',
      'Media & Query': 'media_query',
      'Emerging / GEO': 'emerging_geo',
    }
    return (
      <section className="mock-page">
        {pageHeading('SEO ENGINE', page, 'Evidence-backed deterministic analysis; external data remains explicitly unavailable until configured.')}
        {organization ? (
          <LiveEnginePanel
            accessToken={accessToken}
            organization={organization}
            engine={engineByPage[page]}
          />
        ) : (
          <div className="workspace-card">
            <div className="workspace-card__content">
              <h2>Connect a workspace</h2>
              <p>Engine findings require verified website crawl evidence.</p>
            </div>
          </div>
        )}
      </section>
    )
  }

  return (
    <section className="mock-page">
      {pageHeading('WORKSPACE', page, 'The selected workspace view is available in the overview and connected sections.')}
    </section>
  )
}
