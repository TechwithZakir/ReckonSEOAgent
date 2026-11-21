import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import type { CrawlResponse } from '../lib/crawls'
import { CrawlHistory, CrawlResults } from './CrawlHistory'

const websiteId = 'bca7dcf3-908e-4dcf-a985-5cc68f2355ea'
const crawl: CrawlResponse = {
  crawl_id: 'c03e775d-cdd9-493e-a81e-6da16cb1a194',
  website_id: websiteId,
  status: 'completed',
  started_at: '2026-01-01T10:00:00Z',
  completed_at: '2026-01-01T10:00:01Z',
  http_status: 200,
  final_url: 'https://example.com/',
  content_type: 'text/html',
  bytes_read: 100,
  title: 'Example',
  audit_version: '1',
  error_code: null,
  findings: [{
    code: 'missing_title', impact: 'high', confidence: 'high', effort: 'low',
    source_url: 'https://example.com/', summary: 'Title missing',
    evidence: 'No title', recommendation: 'Add a title', verification: 'Check the title',
  }],
  sitemap_evidence: [{
    url: 'https://example.com/sitemap.xml', status: 'fetched', http_status_code: 200,
    document_type: 'urlset', url_count: 3, child_sitemap_count: 0,
    child_sitemap_urls: [], rejected_count: 0, truncated: false,
  }],
  meta_description: null,
  h1_count: 1,
  meta_robots_noindex: false,
  x_robots_noindex: null,
  canonical_url: null,
  canonical_link_count: 0,
  robots_status_code: 200,
  sitemap_urls: ['https://example.com/sitemap.xml'],
  sitemap_declaration_count: 1,
  sitemap_rejected_count: 0,
  sitemap_discovery_truncated: false,
  redirect_count: 0,
  internal_urls: [],
  page_evidence: [],
}

describe('crawl history display', () => {
  it('disables crawl and specialist actions for an unverified website', () => {
    const html = renderToStaticMarkup(
      <CrawlHistory accessToken="token" organizationId="org" websiteId={websiteId} verified={false} />,
    )
    expect(html).toContain('Verify this website before crawling')
    expect(html.match(/disabled=""/g)).toHaveLength(3)
    expect(html).not.toContain('token')
  })

  it('shows loading and empty states', () => {
    expect(renderToStaticMarkup(
      <CrawlHistory accessToken="token" organizationId="org" websiteId={websiteId} verified />,
    )).toContain('Loading crawl history')
    expect(renderToStaticMarkup(<CrawlResults crawls={[]} />)).toContain('No crawl results yet')
  })

  it('renders actual finding and sitemap evidence as escaped text', () => {
    const html = renderToStaticMarkup(<CrawlResults crawls={[{
      ...crawl,
      title: '<script>untrusted</script>',
    }]} />)
    expect(html).toContain('&lt;script&gt;untrusted&lt;/script&gt;')
    expect(html).toContain('Title missing')
    expect(html).toContain('No title')
    expect(html).toContain('Add a title')
    expect(html).toContain('Check the title')
    expect(html).toContain('sitemap.xml')
    expect(html).toContain('3 URLs')
    expect(html).toContain('By impact')
    expect(html).toContain('High: 1')
    expect(html).toContain('Medium: 0')
    expect(html).toContain('Low: 0')
  })

  it('distinguishes listed, not found, and indeterminable URL-set membership', () => {
    const urlsets = [
      { ...crawl.sitemap_evidence![0], url: 'https://example.com/true.xml', homepage_listed: true, canonical_url_listed: false },
      { ...crawl.sitemap_evidence![0], url: 'https://example.com/null.xml', homepage_listed: null, canonical_url_listed: null },
    ]
    const html = renderToStaticMarkup(<CrawlResults crawls={[{ ...crawl, sitemap_evidence: urlsets }]} />)
    expect(html).toContain('Homepage URL-set membership')
    expect(html).toContain('Canonical URL-set membership')
    expect(html).toContain('Listed in the fully parsed relevant URL set')
    expect(html).toContain('Not found in the fully analyzed URL set')
    expect(html).toContain('Not determinable or not applicable')
  })

  it('does not present omitted membership fields as absent', () => {
    const html = renderToStaticMarkup(<CrawlResults crawls={[crawl]} />)
    expect(html).toContain('Not reported')
    expect(html).not.toContain('Not found in the fully analyzed URL set')
  })

  it('summarizes the newest run and keeps earlier history available', () => {
    const older = {
      ...crawl,
      crawl_id: 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
      title: 'Earlier page',
      findings: [],
    }
    const html = renderToStaticMarkup(<CrawlResults crawls={[crawl, older]} />)
    const summary = html.split('Recent crawl history')[0]
    expect(summary).toContain('Example')
    expect(summary).toContain('1 high')
    expect(summary).toContain('0 medium')
    expect(summary).toContain('HTTP 200')
    expect(summary).not.toContain('Earlier page')
    expect(html).toContain('Earlier page')
    expect(html).toContain('<details open="">')
  })

  it('distinguishes unavailable evidence from zero results on a failed crawl', () => {
    const html = renderToStaticMarkup(<CrawlResults crawls={[{
      ...crawl,
      status: 'failed',
      title: null,
      findings: null,
      sitemap_evidence: null,
      http_status: null,
      error_code: 'crawl_unavailable',
    }]} />)
    const summary = html.split('Recent crawl history')[0]
    expect(summary).toContain('failed')
    expect(summary.match(/Unavailable/g)).toHaveLength(3)
    expect(summary).not.toContain('0 high')
    expect(html).toContain('crawl_unavailable')
    expect(html).toContain('Findings are not available.')
    expect(html).toContain('Sitemap evidence is not available.')
  })

  it('shows zero reported findings without claiming sitemap coverage', () => {
    const html = renderToStaticMarkup(<CrawlResults crawls={[{
      ...crawl,
      findings: [],
      sitemap_evidence: [{ ...crawl.sitemap_evidence![0], truncated: true }],
    }]} />)
    expect(html).toContain('0 high')
    expect(html).toContain('No findings reported.')
    expect(html).toContain('truncated')
    expect(html).not.toContain('Sitemap coverage complete')
  })
})
