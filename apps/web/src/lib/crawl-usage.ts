export type CrawlUsage = {
  period_start: string
  period_end: string
  used: number
  limit: number
  remaining: number
}

export async function getCrawlUsage(
  accessToken: string,
  organizationId: string,
  fetcher: typeof fetch = fetch,
): Promise<CrawlUsage> {
  const response = await fetcher(
    `/api/v1/organizations/${encodeURIComponent(organizationId)}/crawl-usage`,
    { headers: { Authorization: `Bearer ${accessToken}` }, cache: 'no-store' },
  )
  if (!response.ok) {
    throw new Error(`Could not load crawl usage (HTTP ${response.status}).`)
  }
  const value: unknown = await response.json()
  if (!value || typeof value !== 'object') {
    throw new Error('The API returned invalid crawl usage.')
  }
  const usage = value as Record<string, unknown>
  if (
    typeof usage.period_start !== 'string' ||
    typeof usage.period_end !== 'string' ||
    !Number.isFinite(Date.parse(usage.period_start)) ||
    !Number.isFinite(Date.parse(usage.period_end)) ||
    Date.parse(usage.period_start) >= Date.parse(usage.period_end) ||
    typeof usage.used !== 'number' ||
    !Number.isSafeInteger(usage.used) ||
    usage.used < 0 ||
    typeof usage.limit !== 'number' ||
    !Number.isSafeInteger(usage.limit) ||
    usage.limit < 1 ||
    typeof usage.remaining !== 'number' ||
    !Number.isSafeInteger(usage.remaining) ||
    usage.remaining !== Math.max(0, usage.limit - usage.used)
  ) {
    throw new Error('The API returned invalid crawl usage.')
  }
  return {
    period_start: usage.period_start,
    period_end: usage.period_end,
    used: usage.used,
    limit: usage.limit,
    remaining: usage.remaining,
  }
}
