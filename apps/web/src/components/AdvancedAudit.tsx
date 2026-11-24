import { useEffect, useRef, useState } from 'react'
import { parsePublicAudit } from '../lib/public-audit'
import type { PublicAuditReport } from '../lib/public-audit'
import { listWebsites } from '../lib/websites'
import type { Website } from '../lib/websites'
import type { OrganizationContext } from '../lib/organizations'
import { AuditReport } from './PublicAuditTool'

async function runAdvancedAudit(
  token: string,
  organizationId: string,
  websiteId: string,
  signal: AbortSignal,
): Promise<PublicAuditReport> {
  let response: Response
  try {
    response = await fetch(
      `/api/v1/organizations/${encodeURIComponent(organizationId)}/websites/${encodeURIComponent(websiteId)}/advanced-audit`,
      { method: 'POST', headers: { Authorization: `Bearer ${token}` }, cache: 'no-store', signal },
    )
  } catch (cause) {
    if (cause instanceof DOMException && cause.name === 'AbortError') throw cause
    throw new Error('The audit service could not be reached. Please try again.')
  }
  if (!response.ok) {
    const messages: Record<number, string> = {
      404: 'That website was not found in this workspace.',
      409: 'Verify the website (DNS check) before running an audit.',
      429: 'The organization has reached its daily tool limit.',
      502: 'We could not audit that website. It may be offline or blocking automated requests.',
      503: 'The audit service is busy. Please try again in a minute.',
    }
    throw new Error(messages[response.status] ?? `The audit failed (HTTP ${response.status}).`)
  }
  return parsePublicAudit(await response.json())
}

export function AdvancedAudit({
  accessToken,
  organization,
}: {
  accessToken: string
  organization: OrganizationContext
}) {
  const [websites, setWebsites] = useState<Website[]>([])
  const [loaded, setLoaded] = useState(false)
  const [websiteId, setWebsiteId] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [report, setReport] = useState<PublicAuditReport | null>(null)
  const controller = useRef<AbortController | null>(null)

  useEffect(() => {
    let active = true
    void listWebsites(accessToken, organization.organization_id)
      .then((rows) => {
        if (!active) return
        const verified = rows.filter((site) => site.verification_status === 'verified')
        setWebsites(verified)
        setWebsiteId((current) => current || verified[0]?.website_id || '')
      })
      .catch((cause: unknown) => {
        if (active) setError(cause instanceof Error ? cause.message : 'Could not load websites.')
      })
      .finally(() => { if (active) setLoaded(true) })
    return () => { active = false; controller.current?.abort() }
  }, [accessToken, organization.organization_id])

  const run = async () => {
    if (!websiteId || busy) return
    controller.current?.abort()
    const current = new AbortController()
    controller.current = current
    setBusy(true)
    setError(null)
    setReport(null)
    try {
      const result = await runAdvancedAudit(accessToken, organization.organization_id, websiteId, current.signal)
      if (!current.signal.aborted) setReport(result)
    } catch (cause) {
      if (!current.signal.aborted) {
        setError(cause instanceof Error ? cause.message : 'The audit failed. Please try again.')
      }
    } finally {
      if (!current.signal.aborted) setBusy(false)
    }
  }

  return (
    <section className="workspace-card workspace-card--connected advanced-audit" aria-labelledby="adv-audit-title">
      <div className="workspace-card__content">
        <span className="status-label status-label--healthy">Advanced audit</span>
        <h2 id="adv-audit-title">Advanced SEO audit</h2>
        <p>
          Checks crawlability, on-page basics, duplicate titles, mobile and social tags, structured
          data and AI-search readiness. Issues marked “AI fix” can be drafted by the agent in the
          Approvals page and applied only after you approve them.
        </p>
        {loaded && websites.length === 0 && !error && (
          <p>Add and verify a website above to run an advanced audit.</p>
        )}
        {websites.length > 0 && (
          <div className="advanced-audit__controls">
            <label htmlFor="adv-audit-site">Website</label>
            <select id="adv-audit-site" value={websiteId} disabled={busy}
              onChange={(event) => setWebsiteId(event.target.value)}>
              {websites.map((site) => (
                <option key={site.website_id} value={site.website_id}>{site.origin}</option>
              ))}
            </select>
            <button className="button button--primary" type="button" disabled={busy} onClick={() => void run()}>
              {busy ? 'Auditing… (5–20 seconds)' : 'Run advanced audit'}
            </button>
          </div>
        )}
        <div aria-live="polite">
          {error && <p className="workspace-setup__error" role="alert">{error}</p>}
        </div>
        {report && <div className="pa-tool"><AuditReport report={report} /></div>}
      </div>
    </section>
  )
}
