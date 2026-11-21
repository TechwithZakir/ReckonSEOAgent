import { useEffect, useState } from 'react'
import { getCrawlUsage } from '../lib/crawl-usage'
import type { CrawlUsage as CrawlUsageData } from '../lib/crawl-usage'

export function CrawlUsage({
  accessToken,
  organizationId,
  version,
}: {
  accessToken: string
  organizationId: string
  version: number
}) {
  const [usage, setUsage] = useState<CrawlUsageData | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [refreshVersion, setRefreshVersion] = useState(0)

  useEffect(() => {
    let active = true
    void getCrawlUsage(accessToken, organizationId)
      .then((result) => {
        if (active) {
          setUsage(result)
          setError(null)
        }
      })
      .catch((cause: unknown) => {
        if (active) {
          setUsage(null)
          setError(cause instanceof Error ? cause.message : 'Could not load crawl usage.')
        }
      })
    return () => { active = false }
  }, [accessToken, organizationId, version, refreshVersion])

  return (
    <section aria-label="Organization crawl usage" className="crawl-usage">
      <div>
        <strong>Daily organization crawl usage</strong>
        {error ? (
          <p role="alert">{error}</p>
        ) : usage ? (
          <p>
            {usage.used} of {usage.limit} attempts used · {usage.remaining} remaining.
            Resets {new Date(usage.period_end).toLocaleString()}.
          </p>
        ) : (
          <p role="status">Loading crawl usage…</p>
        )}
        <p>Snapshot only; concurrent attempts may change availability. Failed attempts count.</p>
      </div>
      <button
        className="button button--secondary"
        onClick={() => setRefreshVersion((current) => current + 1)}
        type="button"
      >
        Refresh usage
      </button>
    </section>
  )
}
