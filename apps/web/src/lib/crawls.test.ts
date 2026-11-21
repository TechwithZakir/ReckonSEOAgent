import { describe, expect, it, vi } from 'vitest'
import { listCrawls, startCrawl } from './crawls'
import type { CrawlResponse } from './crawls'

export const websiteId = 'bca7dcf3-908e-4dcf-a985-5cc68f2355ea'
export const crawl: CrawlResponse = {
  crawl_id: 'c03e775d-cdd9-493e-a81e-6da16cb1a194',
  website_id: websiteId,
  status: 'completed',
  started_at: '2026-01-01T10:00:00Z',
  completed_at: '2026-01-01T10:00:01Z',
  final_url: 'https://example.com/',
  http_status: 200,
  content_type: 'text/html',
  bytes_read: 100,
  title: 'Example',
  audit_version: '1',
  findings: [{
    code: 'missing_title', impact: 'high', confidence: 'high', effort: 'low',
    source_url: 'https://example.com/', summary: 'Title missing',
    evidence: 'No title', recommendation: 'Add a title', verification: 'Check the title',
  }],
  meta_description: null,
  h1_count: 1,
  meta_robots_noindex: false,
  x_robots_noindex: null,
  canonical_url: null,
  canonical_link_count: 0,
  robots_status_code: 200,
  sitemap_urls: ['https://example.com/sitemap.xml'],
  sitemap_evidence: [{
    url: 'https://example.com/sitemap.xml', status: 'fetched', http_status_code: 200,
    document_type: 'urlset', url_count: 3, child_sitemap_count: 0,
    child_sitemap_urls: [], rejected_count: 0, truncated: false,
  }],
  sitemap_declaration_count: 1,
  sitemap_rejected_count: 0,
  sitemap_discovery_truncated: false,
  redirect_count: 0,
  error_code: null,
}

const response = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), { status })

describe('crawl API client', () => {
  it('starts a confirmed crawl with authenticated scoped URL and idempotency key', async () => {
    const fetcher = vi.fn<typeof fetch>(async () => response(crawl))
    await expect(startCrawl('token', 'org/id', websiteId, 'crawl-key-123', fetcher)).resolves.toEqual(crawl)
    expect(fetcher).toHaveBeenCalledWith(
      `/api/v1/organizations/org%2Fid/websites/${websiteId}/crawl`,
      { method: 'POST', headers: { Authorization: 'Bearer token', 'Idempotency-Key': 'crawl-key-123' } },
    )
    await expect(startCrawl('token', 'org', websiteId, 'bad', fetcher)).rejects.toThrow('idempotency')
    expect(fetcher).toHaveBeenCalledTimes(1)
  })

  it('loads newest-first history without altering order', async () => {
    const earlier = { ...crawl, crawl_id: 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa' }
    const fetcher = vi.fn<typeof fetch>(async () => response([crawl, earlier]))
    await expect(listCrawls('token', 'org', websiteId, fetcher)).resolves.toEqual([crawl, earlier])
    expect(fetcher).toHaveBeenCalledWith(
      `/api/v1/organizations/org/websites/${websiteId}/crawls?limit=20&offset=0`,
      { headers: { Authorization: 'Bearer token' } },
    )
  })

  it('rejects malformed, unfinished and wrong-site responses instead of claiming success', async () => {
    for (const result of [
      { ...crawl, website_id: 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa' },
      { ...crawl, status: 'running' },
      { ...crawl, completed_at: null },
      { ...crawl, started_at: '1' },
      { ...crawl, findings: [{ ...crawl.findings![0], evidence: 42 }] },
      { ...crawl, findings: [{ ...crawl.findings![0], impact: 'unknown' }] },
      { ...crawl, sitemap_evidence: [{ ...crawl.sitemap_evidence![0], truncated: 'no' }] },
      { ...crawl, sitemap_evidence: [{ ...crawl.sitemap_evidence![0], homepage_listed: 'yes' }] },
      { ...crawl, sitemap_evidence: [{ ...crawl.sitemap_evidence![0], canonical_url_listed: 0 }] },
      { ...crawl, status: 'disdisallowed' },
    ]) {
      await expect(startCrawl('token', 'org', websiteId, 'crawl-key-123', async () => response(result))).rejects.toThrow()
    }
    await expect(listCrawls('token', 'org', websiteId, async () => response([{}]))).rejects.toThrow('invalid crawl history')
    await expect(startCrawl('token', 'org', websiteId, 'crawl-key-123', async () => new Response('bad json'))).rejects.toThrow('invalid crawl response')
  })

  it('accepts a confirmed robots disallow without labeling it completed', async () => {
    const result = { ...crawl, status: 'disallowed' as const, error_code: 'robots_disallowed' }
    await expect(startCrawl('token', 'org', websiteId, 'crawl-key-123', async () => response(result))).resolves.toMatchObject({ status: 'disallowed' })
  })

  it('accepts the deterministic sitemap membership findings', async () => {
    const result = {
      ...crawl,
      findings: [
        {
          ...crawl.findings![0],
          code: 'homepage_not_in_sitemap',
          summary: 'The homepage was not found in the analyzed sitemap URL sets.',
        },
        {
          ...crawl.findings![0],
          code: 'canonical_not_in_sitemap',
          summary: 'The same-host canonical URL was not found in the sitemap.',
        },
      ],
    }

    await expect(
      startCrawl('token', 'org', websiteId, 'crawl-key-123', async () =>
        response(result),
      ),
    ).resolves.toMatchObject({ status: 'completed' })
  })

  it.each([409, 422, 429, 503])('surfaces HTTP %s errors', async (status) => {
    await expect(startCrawl('token', 'org', websiteId, 'crawl-key-123', async () => response({}, status)))
      .rejects.toMatchObject({ name: 'CrawlApiError', status, message: expect.stringContaining(`HTTP ${status}`) })
  })
})
