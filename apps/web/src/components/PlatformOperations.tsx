import { useEffect, useState } from 'react'

type PlatformSummary = {
  organization_count: number
  active_member_count: number
  native_account_count: number
  active_native_session_count: number
}

type PlatformAuditEvent = {
  event_id: string
  organization_id: string
  action: string
  resource_type: string
  resource_id: string
  request_id: string
  created_at: string
}

export function PlatformOperations({ accessToken }: { accessToken: string }) {
  const [summary, setSummary] = useState<PlatformSummary | null>(null)
  const [events, setEvents] = useState<PlatformAuditEvent[]>([])
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let active = true
    void Promise.all([
      fetch('/api/v1/platform/summary', {
        headers: { Authorization: `Bearer ${accessToken}` },
        cache: 'no-store',
      }),
      fetch('/api/v1/platform/audit-events?limit=50', {
        headers: { Authorization: `Bearer ${accessToken}` },
        cache: 'no-store',
      }),
    ]).then(async ([summaryResponse, eventResponse]) => {
      if (!summaryResponse.ok || !eventResponse.ok) {
        throw new Error('Platform operations could not be loaded.')
      }
      const [summaryValue, eventValue] = await Promise.all([
        summaryResponse.json() as Promise<PlatformSummary>,
        eventResponse.json() as Promise<PlatformAuditEvent[]>,
      ])
      if (active) {
        setSummary(summaryValue)
        setEvents(eventValue)
      }
    }).catch((cause: unknown) => {
      if (active) setError(cause instanceof Error ? cause.message : 'Could not load platform operations.')
    })
    return () => { active = false }
  }, [accessToken])

  return (
    <section className="mock-page">
      <div className="mock-page__heading">
        <div>
          <p className="section-kicker">PLATFORM OPERATIONS</p>
          <h1>Platform administration</h1>
          <p>Read-only tenant and native-account inventory for the initial platform administrator.</p>
        </div>
      </div>
      {error && <p className="workspace-setup__error" role="alert">{error}</p>}
      {summary && (
        <div className="mock-grid mock-grid--three">
          {[
            ['Organizations', summary.organization_count],
            ['Active memberships', summary.active_member_count],
            ['Native accounts', summary.native_account_count],
            ['Active native sessions', summary.active_native_session_count],
          ].map(([label, value]) => (
            <article className="workspace-card" key={String(label)}>
              <div className="workspace-card__content">
                <span className="status-label status-label--muted">{label}</span>
                <h2>{value}</h2>
              </div>
            </article>
          ))}
        </div>
      )}
      <div className="workspace-card">
        <div className="workspace-card__content">
          <h2>Recent platform audit events</h2>
          {events.length === 0 && <p>No audit events found.</p>}
          {events.map((event) => (
            <article key={event.event_id}>
              <strong>{event.action}</strong>
              <p>{event.resource_type} · Organization {event.organization_id} · {new Date(event.created_at).toLocaleString()}</p>
            </article>
          ))}
        </div>
      </div>
    </section>
  )
}
