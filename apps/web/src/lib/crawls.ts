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

export type PageEvidence = {
  url: string
  status: 'fetched' | 'robots_disallowed' | 'fetch_unavailable' | 'fetch_rejected' | 'unsupported_content_type'
  http_status_code: number | null
  content_type: string | null
  bytes_read: number | null
  title: string | null
  meta_description: string | null
  h1_count: number | null
  h2_count: number | null
  internal_link_count: number | null
  image_count: number | null
  missing_alt_text_count: number | null
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
  internal_urls: string[]
  page_evidence: PageEvidence[]
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
      'homepage_not_in_sitemap', 'canonical_not_in_sitemap', 'missing_h2',
      'no_internal_links', 'images_missing_alt_text'].includes(value.code as string) &&
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

function isPageEvidence(value: unknown): value is PageEvidence {
  if (!record(value) || typeof value.url !== 'string') return false
  return ['fetched', 'robots_disallowed', 'fetch_unavailable', 'fetch_rejected', 'unsupported_content_type'].includes(value.status as string) &&
    nullableNumber(value.http_status_code) &&
    nullableString(value.content_type) &&
    nullableNumber(value.bytes_read) &&
    nullableString(value.title) &&
    nullableString(value.meta_description) &&
    ['h1_count', 'h2_count', 'internal_link_count', 'image_count', 'missing_alt_text_count'].every((key) => nullableNumber(value[key]))
}

function isCrawl(value: unknown, websiteId: string): value is CrawlResponse {
  if (!record(value)) return false
  if (!(typeof value.crawl_id === 'string' && uuid.test(value.crawl_id) &&
    value.website_id === websiteId && uuid.test(websiteId) &&
    ['running', 'completed', 'failed', 'disallowed'].includes(value.status as string) &&
    date(value.started_at) && (value.completed_at === null || date(value.completed_at)) &&
    ['final_url', 'content_type', 'title', 'audit_version', 'meta_description', 'canonical_url', 'error_code'].every((key) => nullableString(value[key])) &&
    ['http_status', 'bytes_read', 'h1_count', 'canonical_link_count', 'robots_status_code', 'sitemap_declaration_count', 'sitemap_rejected_count', 'redirect_count'].every((key) => nullableNumber(value[key])) &&
    ['meta_robots_noindex', 'x_robots_noindex', 'sitemap_discovery_truncated'].every((key) => nullableBoolean(value[key])) &&
    (value.findings === null || (Array.isArray(value.findings) && value.findings.every(isFinding))) &&
    (value.sitemap_urls === null || strings(value.sitemap_urls)) &&
    (value.sitemap_evidence === null || (Array.isArray(value.sitemap_evidence) && value.sitemap_evidence.every(isSitemapEvidence))) &&
    strings(value.internal_urls) &&
    Array.isArray(value.page_evidence) &&
    value.page_evidence.every(isPageEvidence))) {
    return false
  }
  if (value.status === 'running' && value.completed_at !== null) return false
  if (value.status === 'completed' && value.completed_at === null) return false
  if (value.status === 'disallowed' && value.completed_at === null) return false
  return true
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
  if (!isCrawl(result, websiteId)) {
    throw new CrawlApiError('The API returned an invalid crawl result.', response.status)
  }
  if (result.status === 'completed') {
    if (result.completed_at === null) {
      throw new CrawlApiError('The API confirmed completion without a completion time.', response.status)
    }
  } else if (result.status === 'running') {
    return result
  } else if (result.status !== 'disallowed') {
    throw new CrawlApiError('The API did not confirm a finished or queued crawl.', response.status)
  }
  return result
}

export type PrioritizationResponse = {
  status: 'completed' | 'unknown' | 'invalid_output'
  ordered_codes: string[] | null
  reservation_id: string | null
  input_tokens: number | null
  output_tokens: number | null
}

export async function prioritizeCrawl(
  token: string,
  organizationId: string,
  websiteId: string,
  crawlId: string,
  idempotencyKey: string,
  fetcher: typeof fetch = fetch,
): Promise<PrioritizationResponse> {
  if (!/^[A-Za-z0-9._:-]{8,128}$/.test(idempotencyKey)) {
    throw new Error('Invalid specialist idempotency key.')
  }
  const response = await fetcher(
    `${endpoint(organizationId, websiteId)}/crawls/${encodeURIComponent(crawlId)}/prioritize`,
    {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}`, 'Idempotency-Key': idempotencyKey },
      cache: 'no-store',
    },
  )
  if (!response.ok) {
    throw new CrawlApiError(
      response.status === 502
        ? 'The specialist result could not be verified.'
        : response.status === 429
          ? 'The organization has reached its AI token budget.'
          : `Specialist prioritization failed (HTTP ${response.status}).`,
      response.status,
    )
  }
  const data: unknown = await response.json()
  if (!record(data) ||
      !['completed', 'unknown', 'invalid_output'].includes(data.status as string) ||
      !(data.ordered_codes === null || (Array.isArray(data.ordered_codes) && data.ordered_codes.every((code) => typeof code === 'string'))) ||
      !(data.reservation_id === null || (typeof data.reservation_id === 'string' && uuid.test(data.reservation_id))) ||
      !(data.input_tokens === null || (typeof data.input_tokens === 'number' && Number.isSafeInteger(data.input_tokens) && data.input_tokens >= 0)) ||
      !(data.output_tokens === null || (typeof data.output_tokens === 'number' && Number.isSafeInteger(data.output_tokens) && data.output_tokens >= 0))) {
    throw new CrawlApiError('The API returned invalid specialist output.', response.status)
  }
  return data as PrioritizationResponse
}

export type PurgeCrawlHistoryResponse = {
  deleted_count: number
  cutoff: string
  retention_days: number
}

export async function purgeCrawlHistory(
  token: string,
  organizationId: string,
  websiteId: string,
  reason: string,
  fetcher: typeof fetch = fetch,
): Promise<PurgeCrawlHistoryResponse> {
  if (!reason.trim() || reason.trim().length < 3 || reason.trim().length > 200) {
    throw new CrawlApiError('A purge reason containing 3 to 200 characters is required.', 422)
  }
  const response = await fetcher(
    `${endpoint(organizationId, websiteId)}/crawls/purge`,
    {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${token}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ reason: reason.trim() }),
      cache: 'no-store',
    },
  )
  if (!response.ok) {
    throw new CrawlApiError(
      response.status === 403
        ? 'Only organization owners and admins can purge crawl history.'
        : `Crawl history could not be purged (HTTP ${response.status}).`,
      response.status,
    )
  }
  const data: unknown = await response.json()
  if (
    !record(data) ||
    typeof data.deleted_count !== 'number' ||
    !Number.isSafeInteger(data.deleted_count) ||
    data.deleted_count < 0 ||
    typeof data.cutoff !== 'string' ||
    typeof data.retention_days !== 'number' ||
    !Number.isSafeInteger(data.retention_days)
  ) {
    throw new CrawlApiError('The API returned invalid crawl purge output.', response.status)
  }
  return data as PurgeCrawlHistoryResponse
}

export type CrawlSchedule = {
  schedule_id: string
  website_id: string
  frequency: 'daily' | 'weekly'
  active: boolean
  next_run_at: string
  last_run_id: string | null
  created_at: string
}

function isCrawlSchedule(value: unknown): value is CrawlSchedule {
  return record(value) &&
    typeof value.schedule_id === 'string' &&
    uuid.test(value.schedule_id) &&
    typeof value.website_id === 'string' &&
    uuid.test(value.website_id) &&
    (value.frequency === 'daily' || value.frequency === 'weekly') &&
    typeof value.active === 'boolean' &&
    typeof value.next_run_at === 'string' &&
    date(value.next_run_at) &&
    (value.last_run_id === null ||
      (typeof value.last_run_id === 'string' && uuid.test(value.last_run_id))) &&
    typeof value.created_at === 'string' &&
    date(value.created_at)
}

export async function listCrawlSchedules(
  token: string,
  organizationId: string,
  websiteId: string,
  fetcher: typeof fetch = fetch,
): Promise<CrawlSchedule[]> {
  const response = await fetcher(
    `${endpoint(organizationId, websiteId)}/crawl-schedules`,
    { headers: { Authorization: `Bearer ${token}` }, cache: 'no-store' },
  )
  if (!response.ok) {
    throw new CrawlApiError(`Crawl schedules could not be loaded (HTTP ${response.status}).`, response.status)
  }
  const data: unknown = await response.json()
  if (!Array.isArray(data) || !data.every(isCrawlSchedule)) {
    throw new CrawlApiError('The API returned invalid crawl schedules.', response.status)
  }
  return data
}

export async function saveCrawlSchedule(
  token: string,
  organizationId: string,
  websiteId: string,
  frequency: 'daily' | 'weekly',
  active: boolean,
  scheduleId: string | null = null,
  fetcher: typeof fetch = fetch,
): Promise<CrawlSchedule> {
  const path = `${endpoint(organizationId, websiteId)}/crawl-schedules${scheduleId ? `/${encodeURIComponent(scheduleId)}` : ''}`
  const response = await fetcher(path, {
    method: scheduleId ? 'PATCH' : 'POST',
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ frequency, active }),
    cache: 'no-store',
  })
  if (!response.ok) {
    throw new CrawlApiError(
      response.status === 403
        ? 'Only organization owners and admins can manage crawl schedules.'
        : `Crawl schedule could not be saved (HTTP ${response.status}).`,
      response.status,
    )
  }
  const data: unknown = await response.json()
  if (!isCrawlSchedule(data)) {
    throw new CrawlApiError('The API returned invalid crawl schedule output.', response.status)
  }
  return data
}

export async function deleteCrawlSchedule(
  token: string,
  organizationId: string,
  websiteId: string,
  scheduleId: string,
  fetcher: typeof fetch = fetch,
): Promise<void> {
  const response = await fetcher(
    `${endpoint(organizationId, websiteId)}/crawl-schedules/${encodeURIComponent(scheduleId)}`,
    {
      method: 'DELETE',
      headers: { Authorization: `Bearer ${token}` },
      cache: 'no-store',
    },
  )
  if (!response.ok) {
    throw new CrawlApiError(
      `Crawl schedule could not be deleted (HTTP ${response.status}).`,
      response.status,
    )
  }
}

export type EngineName =
  | 'keywords'
  | 'content_studio'
  | 'linkpilot'
  | 'local_seo'
  | 'ecommerce'
  | 'enterprise'
  | 'media_query'
  | 'emerging_geo'

export type EngineFinding = {
  code: string
  title: string
  impact: 'high' | 'medium' | 'low'
  confidence: 'high' | 'medium'
  effort: 'low' | 'medium' | 'high'
  source_url: string
  evidence: string
  recommendation: string
  verification: string
}

export type EngineAudit = {
  engine: EngineName
  version: string
  coverage: 'complete' | 'partial' | 'unavailable'
  findings: EngineFinding[]
}

export async function getEngineAudit(
  token: string,
  organizationId: string,
  websiteId: string,
  crawlId: string,
  engine: EngineName,
  fetcher: typeof fetch = fetch,
): Promise<EngineAudit> {
  const response = await fetcher(
    `${endpoint(organizationId, websiteId)}/crawls/${encodeURIComponent(crawlId)}/engines/${engine}`,
    { headers: { Authorization: `Bearer ${token}` }, cache: 'no-store' },
  )
  if (!response.ok) {
    throw new CrawlApiError(
      `Engine audit could not be loaded (HTTP ${response.status}).`,
      response.status,
    )
  }
  const data: unknown = await response.json()
  if (
    !record(data) ||
    data.engine !== engine ||
    typeof data.version !== 'string' ||
    !['complete', 'partial', 'unavailable'].includes(data.coverage as string) ||
    !Array.isArray(data.findings)
  ) {
    throw new CrawlApiError('The API returned invalid engine audit output.', response.status)
  }
  for (const finding of data.findings) {
    if (
      !record(finding) ||
      typeof finding.code !== 'string' ||
      typeof finding.title !== 'string' ||
      !['high', 'medium', 'low'].includes(finding.impact as string) ||
      !['high', 'medium'].includes(finding.confidence as string) ||
      !['low', 'medium', 'high'].includes(finding.effort as string) ||
      ['source_url', 'evidence', 'recommendation', 'verification'].some(
        (key) => typeof finding[key] !== 'string',
      )
    ) {
      throw new CrawlApiError('The API returned invalid engine findings.', response.status)
    }
  }
  return data as EngineAudit
}
