export type CrawlFinding = {
  code: string
  impact: 'high' | 'medium' | 'low'
  confidence: string
  effort: string
  source_url: string
  summary: string
  evidence: string
  recommendation: string
  verification: string
}

export type SitemapEvidence = {
  url: string
  status: string
  http_status_code: number | null
  document_type: 'urlset' | 'sitemapindex' | null
  url_count: number | null
  child_sitemap_count: number | null
  child_sitemap_urls: string[]
  rejected_count: number | null
  truncated: boolean
  homepage_listed?: boolean | null
  canonical_url_listed?: boolean | null
}

export type CrawlResponse = {
  crawl_id: string
  website_id: string
  status: 'running' | 'completed' | 'disallowed' | 'failed'
  started_at: string
  completed_at: string | null
  final_url: string | null
  http_status: number | null
  content_type: string | null
  bytes_read: number | null
  title: string | null
  audit_version: string | null
  findings: CrawlFinding[] | null
  meta_description: string | null
  h1_count: number | null
  meta_robots_noindex: boolean | null
  x_robots_noindex: boolean | null
  canonical_url: string | null
  canonical_link_count: number | null
  robots_status_code: number | null
  sitemap_urls: string[] | null
  sitemap_evidence: SitemapEvidence[] | null
  sitemap_declaration_count: number | null
  sitemap_rejected_count: number | null
  sitemap_discovery_truncated: boolean | null
  redirect_count: number | null
  error_code: string | null
}

export class CrawlApiError extends Error {
  readonly status: number

  constructor(message: string, status: number) {
    super(message)
    this.name = 'CrawlApiError'
    this.status = status
  }
}

const uuid = /^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$/i
const record = (value: unknown): value is Record<string, unknown> =>
  value !== null && typeof value === 'object' && !Array.isArray(value)
const nullableString = (value: unknown) => value === null || typeof value === 'string'
const nullableNumber = (value: unknown) =>
  value === null || (typeof value === 'number' && Number.isInteger(value) && value >= 0)
const nullableBoolean = (value: unknown) => value === null || typeof value === 'boolean'
const strings = (value: unknown) => Array.isArray(value) && value.every((item) => typeof item === 'string')
const date = (value: unknown) =>
  typeof value === 'string' &&
  /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/i.test(value) &&
  !Number.isNaN(Date.parse(value))

function isFinding(value: unknown): value is CrawlFinding {
  return record(value) &&
    ['non_success_http_status', 'missing_title', 'missing_meta_description', 'missing_h1',
      'noindex_directive', 'invalid_canonical_url', 'multiple_canonical_links',
      'cross_host_canonical', 'empty_sitemap', 'incomplete_sitemap_analysis',
      'homepage_not_in_sitemap', 'canonical_not_in_sitemap'].includes(value.code as string) &&
    ['high', 'medium', 'low'].includes(value.impact as string) &&
    value.confidence === 'high' && ['low', 'medium'].includes(value.effort as string) &&
    ['code', 'confidence', 'effort', 'source_url', 'summary', 'evidence', 'recommendation', 'verification']
      .every((key) => typeof value[key] === 'string')
}

function isSitemapEvidence(value: unknown): value is SitemapEvidence {
  return record(value) &&
    typeof value.url === 'string' &&
    ['fetched', 'http_error', 'robots_disallowed', 'fetch_unavailable', 'fetch_rejected',
      'unsupported_content_type', 'invalid_xml', 'deadline_exceeded', 'fetch_limit_reached'].includes(value.status as string) &&
    (value.document_type === null || value.document_type === 'urlset' || value.document_type === 'sitemapindex') &&
    ['http_status_code', 'url_count', 'child_sitemap_count', 'rejected_count'].every((key) => nullableNumber(value[key])) &&
    ['homepage_listed', 'canonical_url_listed'].every((key) =>
      !(key in value) || nullableBoolean(value[key])) &&
    strings(value.child_sitemap_urls) && typeof value.truncated === 'boolean'
}

function isCrawl(value: unknown, websiteId: string): value is CrawlResponse {
  if (!record(value)) return false
  return typeof value.crawl_id === 'string' && uuid.test(value.crawl_id) &&
    value.website_id === websiteId && uuid.test(websiteId) &&
    ['running', 'completed', 'failed', 'disallowed'].includes(value.status as string) &&
    date(value.started_at) && (value.completed_at === null || date(value.completed_at)) &&
    ['final_url', 'content_type', 'title', 'audit_version', 'meta_description', 'canonical_url', 'error_code'].every((key) => nullableString(value[key])) &&
    ['http_status', 'bytes_read', 'h1_count', 'canonical_link_count', 'robots_status_code', 'sitemap_declaration_count', 'sitemap_rejected_count', 'redirect_count'].every((key) => nullableNumber(value[key])) &&
    ['meta_robots_noindex', 'x_robots_noindex', 'sitemap_discovery_truncated'].every((key) => nullableBoolean(value[key])) &&
    (value.findings === null || (Array.isArray(value.findings) && value.findings.every(isFinding))) &&
    (value.sitemap_urls === null || strings(value.sitemap_urls)) &&
    (value.sitemap_evidence === null || (Array.isArray(value.sitemap_evidence) && value.sitemap_evidence.every(isSitemapEvidence)))
}

function endpoint(organizationId: string, websiteId: string): string {
  return `/api/v1/organizations/${encodeURIComponent(organizationId)}/websites/${encodeURIComponent(websiteId)}`
}

async function payload(response: Response, action: string): Promise<unknown> {
  if (!response.ok) {
    const detail = action !== 'Crawl'
      ? `${action} failed.`
      : response.status === 409
      ? 'The crawl conflicts with an existing request or the website is not verified.'
      : response.status === 422
        ? 'The crawl was blocked by the crawl policy or the request was invalid.'
        : response.status === 429
          ? 'The organization has reached its crawl limit.'
          : response.status === 503
            ? 'The crawl service or website is temporarily unavailable.'
            : `${action} failed.`
    throw new CrawlApiError(`${detail} (HTTP ${response.status})`, response.status)
  }
  try {
    return await response.json() as unknown
  } catch {
    throw new CrawlApiError('The API returned an invalid crawl response.', response.status)
  }
}

export async function listCrawls(
  token: string, organizationId: string, websiteId: string, fetcher: typeof fetch = fetch,
): Promise<CrawlResponse[]> {
  const response = await fetcher(`${endpoint(organizationId, websiteId)}/crawls?limit=20&offset=0`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  const result = await payload(response, 'Loading crawl history')
  if (!Array.isArray(result) || !result.every((item) => isCrawl(item, websiteId))) {
    throw new CrawlApiError('The API returned invalid crawl history.', response.status)
  }
  return result
}

export async function startCrawl(
  token: string, organizationId: string, websiteId: string, key: string, fetcher: typeof fetch = fetch,
): Promise<CrawlResponse> {
  if (!/^[A-Za-z0-9._:-]{8,128}$/.test(key)) {
    throw new Error('Invalid crawl idempotency key.')
  }
  const response = await fetcher(`${endpoint(organizationId, websiteId)}/crawl`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}`, 'Idempotency-Key': key },
  })
  const result = await payload(response, 'Crawl')
  if (!isCrawl(result, websiteId) || !['completed', 'disallowed'].includes(result.status) || result.completed_at === null) {
    throw new CrawlApiError('The API did not confirm a finished crawl.', response.status)
  }
  return result
}
