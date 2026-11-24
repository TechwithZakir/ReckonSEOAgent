import { describe, expect, it, vi } from 'vitest'
import { FixDraftError, parseFixDraft, requestFixDraft } from './fix-drafts'

const draft = {
  proposal_id: '6f0f4d7e-1111-4222-8333-444455556666', status: 'proposed', field: 'meta_title',
  target_url: 'https://example.com/', before_value: '', proposed_value: 'Handmade Ceramic Mugs | Example',
  rationale: 'Matches the H1.', risk: 'low', expires_at: '2026-11-24T12:00:00+00:00',
}
const asFetch = (fn: unknown) => fn as typeof fetch

describe('fix draft client', () => {
  it('parses a valid draft', () => {
    expect(parseFixDraft(draft).proposed_value).toContain('Ceramic')
  })

  it.each([
    { ...draft, status: 'executed' },
    { ...draft, field: 'canonical' },
    { ...draft, proposed_value: 5 },
    null,
  ])('rejects malformed drafts', (value) => {
    expect(() => parseFixDraft(value)).toThrow(FixDraftError)
  })

  it('posts with the idempotency key and bearer token', async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify(draft), { status: 200 }))
    const result = await requestFixDraft('tok', 'org 1', 'site', {
      field: 'meta_title', target_url: 'https://example.com/',
    }, 'key-12345678', asFetch(fetcher))
    expect(result.proposal_id).toBe(draft.proposal_id)
    const [url, init] = fetcher.mock.calls[0] as [string, RequestInit]
    expect(url).toBe('/api/v1/organizations/org%201/websites/site/fix-drafts')
    expect((init.headers as Record<string, string>)['Idempotency-Key']).toBe('key-12345678')
    expect((init.headers as Record<string, string>).Authorization).toBe('Bearer tok')
  })

  it('surfaces deliberate server messages and friendly fallbacks', async () => {
    const conflict = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: 'Save AI settings before running a specialist agent.' }), { status: 409 }),
    )
    await expect(
      requestFixDraft('t', 'o', 's', { field: 'heading', target_url: 'x' }, 'k-12345678', asFetch(conflict)),
    ).rejects.toThrow('Save AI settings')
    const forbidden = vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: 'secret' }), { status: 403 }))
    await expect(
      requestFixDraft('t', 'o', 's', { field: 'heading', target_url: 'x' }, 'k-12345678', asFetch(forbidden)),
    ).rejects.toThrow('Only owners and admins')
    const down = vi.fn().mockRejectedValue(new TypeError('x'))
    await expect(
      requestFixDraft('t', 'o', 's', { field: 'heading', target_url: 'x' }, 'k-12345678', asFetch(down)),
    ).rejects.toThrow('could not be reached')
  })
})
