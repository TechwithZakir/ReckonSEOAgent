export type Severity = 'high' | 'medium' | 'low'

export type PublicFinding = {
  id: string
  category: string
  severity: Severity
  title: string
  found: string
  why_it_matters: string
  how_to_fix: string
  url: string
}

export type PublicCheck = { category: string; label: string; passed: boolean }

export type PublicAuditReport = {
  host: string
  final_url: string
  score: number
  grade: 'A' | 'B' | 'C' | 'D' | 'F'
  pages_checked: number
  findings: PublicFinding[]
  checks: PublicCheck[]
  audit_version: string
  cached: boolean
}

export class PublicAuditError extends Error {
  readonly status: number
  constructor(message: string, status: number) {
    super(message)
    this.name = 'PublicAuditError'
    this.status = status
  }
}

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null

function parseFinding(value: unknown): PublicFinding {
  if (
    !isRecord(value) ||
    !['high', 'medium', 'low'].includes(String(value.severity)) ||
    ['id', 'category', 'title', 'found', 'why_it_matters', 'how_to_fix', 'url'].some(
      (key) => typeof value[key] !== 'string',
    )
  ) {
    throw new PublicAuditError('The audit returned an invalid finding.', 502)
  }
  return value as PublicFinding
}

export function parsePublicAudit(value: unknown): PublicAuditReport {
  if (
    !isRecord(value) ||
    typeof value.host !== 'string' ||
    typeof value.final_url !== 'string' ||
    typeof value.score !== 'number' ||
    !Number.isInteger(value.score) ||
    value.score < 0 ||
    value.score > 100 ||
    !['A', 'B', 'C', 'D', 'F'].includes(String(value.grade)) ||
    typeof value.pages_checked !== 'number' ||
    !Array.isArray(value.findings) ||
    !Array.isArray(value.checks)
  ) {
    throw new PublicAuditError('The audit returned an invalid result.', 502)
  }
  const checks = value.checks.map((check): PublicCheck => {
    if (
      !isRecord(check) ||
      typeof check.category !== 'string' ||
      typeof check.label !== 'string' ||
      typeof check.passed !== 'boolean'
    ) {
      throw new PublicAuditError('The audit returned an invalid check.', 502)
    }
    return { category: check.category, label: check.label, passed: check.passed }
  })
  return {
    host: value.host,
    final_url: value.final_url,
    score: value.score,
    grade: value.grade as PublicAuditReport['grade'],
    pages_checked: value.pages_checked,
    findings: value.findings.map(parseFinding),
    checks,
    audit_version: typeof value.audit_version === 'string' ? value.audit_version : '',
    cached: value.cached === true,
  }
}

const FRIENDLY: Record<number, string> = {
  422: 'Enter a public website address such as example.com.',
  429: 'You have reached the hourly audit limit. Please try again later or create an account.',
  502: 'We could not reach that website. Check the address and that the site is online.',
  503: 'The audit service is busy. Please try again in a minute.',
  404: 'The free audit is not available right now.',
}

export async function runPublicAudit(
  url: string,
  fetcher: typeof fetch = fetch,
  signal?: AbortSignal,
): Promise<PublicAuditReport> {
  let response: Response
  try {
    response = await fetcher('/api/v1/public/audit', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url }),
      cache: 'no-store',
      signal,
    })
  } catch (cause) {
    if (cause instanceof DOMException && cause.name === 'AbortError') throw cause
    throw new PublicAuditError('The audit service could not be reached. Please try again.', 0)
  }
  if (!response.ok) {
    let detail: string | null = null
    try {
      const body: unknown = await response.json()
      if (isRecord(body) && typeof body.detail === 'string' && response.status === 422) {
        detail = body.detail
      }
    } catch {
      // fall back to the friendly text
    }
    throw new PublicAuditError(
      detail ?? FRIENDLY[response.status] ?? `The audit failed (HTTP ${response.status}).`,
      response.status,
    )
  }
  return parsePublicAudit(await response.json())
}

export function scoreTone(score: number): 'good' | 'fair' | 'poor' {
  return score >= 80 ? 'good' : score >= 55 ? 'fair' : 'poor'
}

export function groupFindings(findings: PublicFinding[]): Map<string, PublicFinding[]> {
  const groups = new Map<string, PublicFinding[]>()
  for (const finding of findings) {
    groups.set(finding.category, [...(groups.get(finding.category) ?? []), finding])
  }
  return groups
}

export function severityCounts(findings: PublicFinding[]): Record<Severity, number> {
  const counts: Record<Severity, number> = { high: 0, medium: 0, low: 0 }
  for (const finding of findings) counts[finding.severity] += 1
  return counts
}
