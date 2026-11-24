import { describe, expect, it, vi } from 'vitest'
import {
  groupFindings,
  parsePublicAudit,
  PublicAuditError,
  runPublicAudit,
  scoreTone,
  severityCounts,
} from './public-audit'

const finding = {
  id: 'missing_title', category: 'On-page', severity: 'medium', title: 'No title',
  found: 'x', why_it_matters: 'y', how_to_fix: 'z', url: 'https://example.com/',
}
const report = {
  host: 'example.com', final_url: 'https://example.com/', score: 80, grade: 'B',
  pages_checked: 3, findings: [finding],
  checks: [{ category: 'On-page', label: 'Title', passed: false }],
  audit_version: 'public-v4', cached: false,
}
const ok = (body: unknown) => new Response(JSON.stringify(body), { status: 200 })
const asFetch = (fn: unknown) => fn as typeof fetch

describe('public audit client', () => {
  it('parses a valid report', () => {
    expect(parsePublicAudit(report).findings).toHaveLength(1)
  })

  it.each([
    { ...report, score: 101 },
    { ...report, grade: 'Z' },
    { ...report, findings: [{ ...finding, severity: 'critical' }] },
    { ...report, findings: [{ ...finding, how_to_fix: 5 }] },
    { ...report, checks: [{ label: 'x' }] },
    null,
  ])('rejects malformed payloads', (value) => {
    expect(() => parsePublicAudit(value)).toThrow(PublicAuditError)
  })

  it('posts the address and returns the report', async () => {
    const fetcher = vi.fn().mockResolvedValue(ok(report))
    const result = await runPublicAudit('example.com', asFetch(fetcher))
    expect(result.host).toBe('example.com')
    const init = fetcher.mock.calls[0][1] as RequestInit
    expect(init.method).toBe('POST')
    expect(init.body).toBe(JSON.stringify({ url: 'example.com' }))
  })

  it('shows the server message for rejected addresses', async () => {
    const fetcher = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: 'Enter a domain name, not an IP address.' }), { status: 422 }),
    )
    await expect(runPublicAudit('1.1.1.1', asFetch(fetcher))).rejects.toThrow(
      'Enter a domain name, not an IP address.',
    )
  })

  it('uses friendly text for rate limits and network failures', async () => {
    const limited = vi.fn().mockResolvedValue(new Response('nope', { status: 429 }))
    await expect(runPublicAudit('a.com', asFetch(limited))).rejects.toThrow(/hourly/)
    const down = vi.fn().mockRejectedValue(new TypeError('failed'))
    await expect(runPublicAudit('a.com', asFetch(down))).rejects.toThrow(/could not be reached/)
  })

  it('summarises findings', () => {
    const items = [
      finding,
      { ...finding, id: 'b', severity: 'high', category: 'Crawlability' },
    ] as never
    expect(severityCounts(items)).toEqual({ high: 1, medium: 1, low: 0 })
    expect([...groupFindings(items).keys()]).toEqual(['On-page', 'Crawlability'])
    expect([scoreTone(90), scoreTone(60), scoreTone(10)]).toEqual(['good', 'fair', 'poor'])
  })
})
