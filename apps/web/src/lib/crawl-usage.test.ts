import { describe, expect, it, vi } from 'vitest'
import { getCrawlUsage } from './crawl-usage'

const usage = {
  period_start: '2026-01-01T00:00:00Z',
  period_end: '2026-01-02T00:00:00Z',
  used: 2,
  limit: 10,
  remaining: 8,
}

describe('crawl usage client', () => {
  it('loads the authorized organization usage without caching', async () => {
    const fetcher = vi.fn<typeof fetch>(async () => Response.json(usage))
    await expect(getCrawlUsage('token', 'organization', fetcher)).resolves.toEqual(usage)
    expect(fetcher).toHaveBeenCalledWith(
      '/api/v1/organizations/organization/crawl-usage',
      { headers: { Authorization: 'Bearer token' }, cache: 'no-store' },
    )
  })

  it('rejects invalid counts, invalid periods, and API errors', async () => {
    for (const invalid of [
      { ...usage, remaining: 9 },
      { ...usage, used: -1 },
      { ...usage, period_end: usage.period_start },
    ]) {
      await expect(getCrawlUsage('token', 'org', async () => Response.json(invalid)))
        .rejects.toThrow('invalid crawl usage')
    }
    await expect(getCrawlUsage('token', 'org', async () => new Response(null, { status: 404 })))
      .rejects.toThrow('HTTP 404')
  })
})
