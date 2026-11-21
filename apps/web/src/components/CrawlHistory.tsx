import { useEffect, useRef, useState } from 'react'
import {
  CrawlApiError,
  deleteCrawlSchedule,
  listCrawlSchedules,
  listCrawls,
  prioritizeCrawl,
  purgeCrawlHistory,
  saveCrawlSchedule,
  startCrawl,
} from '../lib/crawls'
import type { CrawlSchedule } from '../lib/crawls'
import type { CrawlResponse } from '../lib/crawls'

export function CrawlResults({ crawls }: { crawls: CrawlResponse[] }) {
  if (crawls.length === 0) {
    return (
      <div className="crawl-history__empty">
        <strong>No crawl results yet.</strong>
        <p>Start a crawl to see findings and sitemap evidence for this website.</p>
      </div>
    )
  }

  const membershipLabel = (listed: boolean | null | undefined) => {
    if (listed === true) return 'Listed in the fully parsed relevant URL set'
    if (listed === false) return 'Not found in the fully analyzed URL set'
    return listed === null ? 'Not determinable or not applicable' : 'Not reported'
  }

  const latest = crawls[0]
  const findings = latest.findings
  const impactCounts = findings === null
    ? null
    : (['high', 'medium', 'low'] as const).map((impact) => ({
        impact,
        count: findings.filter((finding) => finding.impact === impact).length,
      }))

  return (
    <>
    <section aria-label="Latest crawl summary" className="crawl-summary">
      <div className="crawl-summary__heading">
        <div>
          <span className="crawl-summary__eyebrow">LATEST CRAWL</span>
          <h5>{latest.title || 'Homepage crawl'}</h5>
          <p>Started {new Date(latest.started_at).toLocaleString()}</p>
        </div>
        <span className={`crawl-summary__status crawl-summary__status--${latest.status}`}>
          {latest.status === 'disallowed' ? 'Blocked by robots' : latest.status}
        </span>
      </div>
      <div className="crawl-summary__metrics">
        <div>
          <span>Findings reported</span>
          <strong>{latest.findings === null ? 'Unavailable' : latest.findings.length}</strong>
          {impactCounts && (
            <p>
              {impactCounts.map(({ impact, count }) => `${count} ${impact}`).join(' · ')}
            </p>
          )}
        </div>
        <div>
          <span>Sitemap documents</span>
          <strong>{latest.sitemap_evidence === null ? 'Unavailable' : latest.sitemap_evidence.length}</strong>
          <p>Reported in this crawl</p>
        </div>
        <div>
          <span>Homepage response</span>
          <strong>{latest.http_status === null ? 'Unavailable' : `HTTP ${latest.http_status}`}</strong>
          <p>{latest.audit_version ? `Audit ${latest.audit_version}` : 'Audit not available'}</p>
        </div>
      </div>
    </section>
    <h5 className="crawl-history__section-title">Recent crawl history</h5>
    <ol className="crawl-history__list">
      {crawls.map((crawl, index) => (
        <li key={crawl.crawl_id}>
          <details open={index === 0}>
            <summary>
              {index === 0 ? 'Latest · ' : ''}{crawl.status} · {new Date(crawl.started_at).toLocaleString()}
              {crawl.title ? ` · ${crawl.title}` : ''}
            </summary>
            <dl className="crawl-history__details">
              <div><dt>Crawl ID</dt><dd>{crawl.crawl_id}</dd></div>
              <div><dt>Completed</dt><dd>{crawl.completed_at ? new Date(crawl.completed_at).toLocaleString() : 'Not completed'}</dd></div>
              <div><dt>HTTP status</dt><dd>{crawl.http_status ?? 'Not available'}</dd></div>
              <div><dt>Audit version</dt><dd>{crawl.audit_version ?? 'Not available'}</dd></div>
              {crawl.error_code && <div><dt>Error</dt><dd>{crawl.error_code}</dd></div>}
            </dl>
            <h5>Findings</h5>
            {crawl.findings === null ? <p>Findings are not available.</p> : crawl.findings.length === 0 ? <p>No findings reported.</p> : (
              <>
                <div aria-label="Finding counts by impact" className="crawl-history__impact-summary">
                  <strong>By impact</strong>
                  {(['high', 'medium', 'low'] as const).map((impact) => (
                    <span key={impact}>{impact[0].toUpperCase() + impact.slice(1)}: {crawl.findings!.filter((finding) => finding.impact === impact).length}</span>
                  ))}
                </div>
                <ul className="crawl-history__findings">
                  {crawl.findings.map((finding, index) => (
                    <li key={`${finding.code}-${index}`}>
                      <div className="crawl-history__finding-heading">
                        <strong>{finding.summary}</strong>
                        <span className={`crawl-history__impact crawl-history__impact--${finding.impact}`}>
                          {finding.impact} impact
                        </span>
                      </div>
                      <p>Check: {finding.code} · Confidence: {finding.confidence} · Effort: {finding.effort}</p>
                      <p><strong>Source:</strong> {finding.source_url}</p>
                      <p><strong>Evidence:</strong> {finding.evidence}</p>
                      <p><strong>Recommendation:</strong> {finding.recommendation}</p>
                      <p><strong>Verification:</strong> {finding.verification}</p>
                    </li>
                  ))}
                </ul>
              </>
            )}
            <h5>Sitemap evidence</h5>
            {crawl.sitemap_evidence === null ? <p>Sitemap evidence is not available.</p> : crawl.sitemap_evidence.length === 0 ? <p>No sitemap evidence reported.</p> : (
              <ul className="crawl-history__findings">
                {crawl.sitemap_evidence.map((sitemap, index) => (
                  <li key={`${sitemap.url}-${index}`}>
                    <strong>{sitemap.url}</strong> · {sitemap.status}
                    {sitemap.http_status_code !== null && ` · HTTP ${sitemap.http_status_code}`}
                    {sitemap.document_type && ` · ${sitemap.document_type}`}
                    {sitemap.url_count !== null && ` · ${sitemap.url_count} URLs`}
                    {sitemap.child_sitemap_count !== null && ` · ${sitemap.child_sitemap_count} child sitemaps`}
                    {sitemap.rejected_count !== null && ` · ${sitemap.rejected_count} rejected`}
                    {sitemap.truncated && ' · truncated'}
                    {sitemap.document_type === 'urlset' && (
                      <dl className="crawl-history__membership">
                        <div><dt>Homepage URL-set membership</dt><dd>{membershipLabel(sitemap.homepage_listed)}</dd></div>
                        <div><dt>Canonical URL-set membership</dt><dd>{membershipLabel(sitemap.canonical_url_listed)}</dd></div>
                      </dl>
                    )}
                    {sitemap.child_sitemap_urls.length > 0 && <p>Child sitemaps: {sitemap.child_sitemap_urls.join(', ')}</p>}
                  </li>
                ))}
              </ul>
            )}
          </details>
        </li>
      ))}
    </ol>
    </>
  )
}

export function CrawlHistory({
  accessToken, organizationId, websiteId, verified, role, onUsageChanged,
}: CrawlHistoryProps) {
  return <CrawlHistoryState key={JSON.stringify([accessToken, organizationId, websiteId, verified])}
    accessToken={accessToken} organizationId={organizationId} websiteId={websiteId} verified={verified} role={role}
    onUsageChanged={onUsageChanged} />
}

type CrawlHistoryProps = {
  accessToken: string
  organizationId: string
  websiteId: string
  verified: boolean
  role?: 'owner' | 'admin' | 'editor' | 'viewer'
  onUsageChanged?: () => void
}

function CrawlHistoryState({ accessToken, organizationId, websiteId, verified, role, onUsageChanged }: CrawlHistoryProps) {
  const [crawls, setCrawls] = useState<CrawlResponse[]>([])
  const [loading, setLoading] = useState(verified)
  const [busy, setBusy] = useState(false)
  const [historyError, setHistoryError] = useState<string | null>(null)
  const [crawlError, setCrawlError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [specialistNotice, setSpecialistNotice] = useState<string | null>(null)
  const [purgeReason, setPurgeReason] = useState('')
  const [schedules, setSchedules] = useState<CrawlSchedule[]>([])
  const [scheduleFrequency, setScheduleFrequency] = useState<'daily' | 'weekly'>('daily')
  const [scheduleActive, setScheduleActive] = useState(true)
  const [version, setVersion] = useState(0)
  const [retry, setRetry] = useState(false)
  const requestKey = useRef<string | null>(null)
  const inFlight = useRef(false)
  const generation = useRef(0)

  useEffect(() => {
    generation.current += 1
    const current = generation.current
    return () => { generation.current = current + 1 }
  }, [accessToken, organizationId, websiteId, verified])

  useEffect(() => {
    if (!verified) return
    let active = true
    void listCrawls(accessToken, organizationId, websiteId)
      .then((items) => { if (active) setCrawls(items) })
      .catch((cause: unknown) => {
        if (active) setHistoryError(cause instanceof Error ? cause.message : 'Could not load crawl history.')
      })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [accessToken, organizationId, websiteId, verified, version])

  useEffect(() => {
    if (!verified || !role || !['owner', 'admin'].includes(role)) return
    let active = true
    void listCrawlSchedules(accessToken, organizationId, websiteId)
      .then((rows) => {
        if (active) {
          setSchedules(rows)
          if (rows[0]) {
            setScheduleFrequency(rows[0].frequency)
            setScheduleActive(rows[0].active)
          }
        }
      })
      .catch((cause: unknown) => {
        if (active) setCrawlError(cause instanceof Error ? cause.message : 'Could not load crawl schedules.')
      })
    return () => { active = false }
  }, [accessToken, organizationId, websiteId, verified, role, version])

  const handleCrawl = async () => {
    if (!verified || inFlight.current) return
    inFlight.current = true
    const current = generation.current
    const key = requestKey.current ?? crypto.randomUUID()
    requestKey.current = key
    setBusy(true)
    setCrawlError(null)
    setNotice(null)
    try {
      const result = await startCrawl(accessToken, organizationId, websiteId, key)
      if (current !== generation.current) return
      requestKey.current = null
      setRetry(false)
      setNotice(
        result.status === 'running'
          ? 'Crawl queued and running. Refresh history to see its result.'
          : result.status === 'completed'
            ? 'Crawl completed.'
            : 'Crawl was disallowed by robots policy.',
      )
      setLoading(true)
      setHistoryError(null)
      setVersion((value) => value + 1)
    } catch (cause) {
      if (current !== generation.current) return
      const uncertain = !(cause instanceof CrawlApiError) || cause.status === 409 ||
        cause.status >= 500 || (cause.status >= 200 && cause.status < 300)
      if (!uncertain) requestKey.current = null
      setRetry(uncertain)
      setCrawlError(cause instanceof Error ? cause.message : 'Could not start the crawl.')
    } finally {
      if (current === generation.current) {
        inFlight.current = false
        setBusy(false)
        onUsageChanged?.()
      }
    }
  }

  const handlePrioritize = async () => {
    const latest = crawls[0]
    if (!verified || !latest || latest.status !== 'completed' || latest.findings === null || latest.findings.length === 0) return
    setBusy(true)
    setCrawlError(null)
    setSpecialistNotice(null)
    try {
      const result = await prioritizeCrawl(
        accessToken,
        organizationId,
        websiteId,
        latest.crawl_id,
        crypto.randomUUID(),
      )
      if (result.status === 'completed') {
        setSpecialistNotice(
          `Prioritization completed. Ordered findings: ${(result.ordered_codes ?? []).join(', ')}.`,
        )
      } else if (result.status === 'unknown') {
        setSpecialistNotice('The provider outcome is unknown. AI usage remains unresolved; do not retry blindly.')
      } else {
        setCrawlError('The specialist returned invalid output and was not accepted.')
      }
    } catch (cause) {
      setCrawlError(cause instanceof Error ? cause.message : 'Could not prioritize crawl findings.')
    } finally {
      setBusy(false)
    }
  }

  const handlePurge = async () => {
    if (!verified || !role || !['owner', 'admin'].includes(role)) return
    setBusy(true)
    setCrawlError(null)
    setNotice(null)
    try {
      const result = await purgeCrawlHistory(
        accessToken,
        organizationId,
        websiteId,
        purgeReason,
      )
      setNotice(`Purged ${result.deleted_count} crawl run(s) older than ${result.retention_days} days.`)
      setPurgeReason('')
      setVersion((value) => value + 1)
    } catch (cause) {
      setCrawlError(cause instanceof Error ? cause.message : 'Could not purge crawl history.')
    } finally {
      setBusy(false)
    }
  }

  const handleSaveSchedule = async () => {
    if (!verified || !role || !['owner', 'admin'].includes(role)) return
    setBusy(true)
    setCrawlError(null)
    setNotice(null)
    try {
      await saveCrawlSchedule(
        accessToken,
        organizationId,
        websiteId,
        scheduleFrequency,
        scheduleActive,
        schedules[0]?.schedule_id ?? null,
      )
      setNotice('Crawl schedule saved.')
      setVersion((value) => value + 1)
    } catch (cause) {
      setCrawlError(cause instanceof Error ? cause.message : 'Could not save crawl schedule.')
    } finally {
      setBusy(false)
    }
  }

  const handleDeleteSchedule = async (scheduleId: string) => {
    setBusy(true)
    setCrawlError(null)
    setNotice(null)
    try {
      await deleteCrawlSchedule(accessToken, organizationId, websiteId, scheduleId)
      setSchedules((current) => current.filter((schedule) => schedule.schedule_id !== scheduleId))
      setNotice('Crawl schedule removed.')
    } catch (cause) {
      setCrawlError(cause instanceof Error ? cause.message : 'Could not remove crawl schedule.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <section aria-label="Crawl history" className="crawl-history">
      <div className="crawl-history__heading">
        <h4>Crawl history</h4>
        <div className="crawl-history__actions">
          <button className="button button--primary" disabled={!verified || busy} onClick={() => void handleCrawl()} type="button">
            {busy ? 'Crawling…' : retry ? 'Retry crawl request' : 'Start crawl'}
          </button>
          <button className="button button--secondary" disabled={!verified || loading || busy} onClick={() => { setLoading(true); setHistoryError(null); setVersion((value) => value + 1) }} type="button">
            {loading ? 'Loading…' : 'Refresh history'}
          </button>
          <button
            className="button button--secondary"
            disabled={!verified || busy || loading || crawls[0]?.status !== 'completed' || !crawls[0]?.findings?.length}
            onClick={() => void handlePrioritize()}
            type="button"
          >
            Prioritize findings
          </button>
        </div>
      </div>
      {!verified && <p>Verify this website before crawling or viewing its history.</p>}
      {busy && <p role="status">Crawl in progress…</p>}
      {notice && <p role="status">{notice}</p>}
      {specialistNotice && <p role="status">{specialistNotice}</p>}
      {crawlError && <p className="workspace-setup__error" role="alert">Crawl request: {crawlError}</p>}
      {retry && (
        <p>
          The outcome may be unknown. Retry uses the same request key; check history before starting a new crawl.{' '}
          <button className="button button--secondary" disabled={busy} onClick={() => { requestKey.current = null; setRetry(false); setCrawlError(null) }} type="button">Start a new request instead</button>
        </p>
      )}
      {role && ['owner', 'admin'].includes(role) && verified && (
        <form
          className="workspace-form"
          onSubmit={(event) => {
            event.preventDefault()
            void handleSaveSchedule()
          }}
        >
          <h5>Crawl schedule</h5>
          <label htmlFor={`crawl-schedule-frequency-${websiteId}`}>Frequency</label>
          <select
            id={`crawl-schedule-frequency-${websiteId}`}
            value={scheduleFrequency}
            disabled={busy}
            onChange={(event) => setScheduleFrequency(event.target.value === 'weekly' ? 'weekly' : 'daily')}
          >
            <option value="daily">Daily</option>
            <option value="weekly">Weekly</option>
          </select>
          <label htmlFor={`crawl-schedule-active-${websiteId}`}>Active</label>
          <input
            id={`crawl-schedule-active-${websiteId}`}
            type="checkbox"
            checked={scheduleActive}
            disabled={busy}
            onChange={(event) => setScheduleActive(event.target.checked)}
          />
          <button className="button button--secondary" type="submit" disabled={busy}>
            {schedules.length > 0 ? 'Update schedule' : 'Create schedule'}
          </button>
          {schedules.map((schedule) => (
            <div key={schedule.schedule_id}>
              <p>
                {schedule.frequency} · {schedule.active ? 'active' : 'paused'} · next
                {' '}{new Date(schedule.next_run_at).toLocaleString()}
              </p>
              <button
                className="button button--secondary"
                type="button"
                disabled={busy}
                onClick={() => void handleDeleteSchedule(schedule.schedule_id)}
              >
                Remove schedule
              </button>
            </div>
          ))}
        </form>
      )}
      {role && ['owner', 'admin'].includes(role) && verified && (
        <form
          className="workspace-form"
          onSubmit={(event) => {
            event.preventDefault()
            void handlePurge()
          }}
        >
          <label htmlFor={`crawl-purge-reason-${websiteId}`}>Retention purge reason</label>
          <input
            id={`crawl-purge-reason-${websiteId}`}
            minLength={3}
            maxLength={200}
            required
            value={purgeReason}
            disabled={busy}
            onChange={(event) => setPurgeReason(event.target.value)}
          />
          <button className="button button--secondary" type="submit" disabled={busy}>
            Purge expired crawl history
          </button>
        </form>
      )}
      {verified && historyError && <p className="workspace-setup__error" role="alert">History: {historyError}</p>}
      {verified && loading && <p role="status">Loading crawl history…</p>}
      {verified && !loading && !historyError && <CrawlResults crawls={crawls} />}
    </section>
  )
}
