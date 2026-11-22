import { describe, expect, it, vi } from 'vitest'
import {
  approveSeoAction,
  describeError,
  describeVerification,
  hasInFlightClaim,
  statusNote,
  wasRecovered,
  executeSeoAction,
  listSeoActions,
  proposeSeoAction,
  rejectSeoAction,
  rollbackSeoAction,
} from './seo-actions'

const ORG = '11111111-1111-4111-8111-111111111111'
const ACTION = {
  proposal_id: '22222222-2222-4222-8222-222222222222',
  website_id: '33333333-3333-4333-8333-333333333333',
  action_type: 'meta_title',
  target_url: 'https://example.com/',
  target_version: 'v1',
  risk: 'low',
  status: 'proposed',
  reason: 'Improve title',
  approval_hash: 'a'.repeat(64),
  before_state: { title: 'Old' },
  proposed_state: { title: 'New' },
  executed_state: null,
  verification_state: null,
  rollback_state: null,
  error_code: null,
  created_at: '2026-11-22T00:00:00Z',
  expires_at: '2026-11-22T00:30:00Z',
  approved_at: null,
  executed_at: null,
  verified_at: null,
}

function json(body: unknown, status = 200): typeof fetch {
  return vi.fn(async () => new Response(JSON.stringify(body), { status })) as unknown as typeof fetch
}

describe('seo action client', () => {
  it('lists actions with bearer auth and a tenant-scoped URL', async () => {
    const fetcher = json([ACTION])
    const actions = await listSeoActions('tok', ORG, fetcher)
    expect(actions).toHaveLength(1)
    const [url, init] = (fetcher as ReturnType<typeof vi.fn>).mock.calls[0]
    expect(url).toBe(`/api/v1/organizations/${ORG}/seo-actions`)
    expect(init.headers.Authorization).toBe('Bearer tok')
    expect(init.cache).toBe('no-store')
  })

  it('rejects malformed action payloads', async () => {
    await expect(
      listSeoActions('tok', ORG, json([{ ...ACTION, risk: 'critical' }])),
    ).rejects.toThrow('invalid SEO actions')
    await expect(listSeoActions('tok', ORG, json({ not: 'a list' }))).rejects.toThrow(
      'invalid SEO actions',
    )
  })

  it('surfaces HTTP failures without leaking response bodies', async () => {
    await expect(listSeoActions('tok', ORG, json({ detail: 'secret' }, 403))).rejects.toThrow(
      'Loading SEO actions failed (HTTP 403).',
    )
  })

  it('sends the idempotency key when proposing', async () => {
    const fetcher = json(ACTION, 201)
    await proposeSeoAction(
      'tok',
      ORG,
      'idem-key-0001',
      {
        website_id: ACTION.website_id,
        action_type: 'meta_title',
        target_url: ACTION.target_url,
        target_version: 'v1',
        before_state: { title: 'Old' },
        proposed_state: { title: 'New' },
        risk: 'low',
        reason: 'Improve title',
      },
      fetcher,
    )
    const init = (fetcher as ReturnType<typeof vi.fn>).mock.calls[0][1]
    expect(init.method).toBe('POST')
    expect(init.headers['Idempotency-Key']).toBe('idem-key-0001')
  })

  it('encodes ids and sends the approval hash only on approve', async () => {
    const approve = json({ ...ACTION, status: 'approved' })
    await approveSeoAction('tok', ORG, ACTION.proposal_id, ACTION.approval_hash, approve)
    const call = (approve as ReturnType<typeof vi.fn>).mock.calls[0]
    expect(call[0]).toBe(`/api/v1/organizations/${ORG}/seo-actions/${ACTION.proposal_id}/approve`)
    expect(JSON.parse(call[1].body)).toEqual({ approval_hash: ACTION.approval_hash })

    const reject = json({ ...ACTION, status: 'rejected' })
    await rejectSeoAction('tok', ORG, ACTION.proposal_id, reject)
    expect((reject as ReturnType<typeof vi.fn>).mock.calls[0][1].body).toBeUndefined()
  })

  it('executes and rolls back through POST endpoints', async () => {
    const run = json({ ...ACTION, status: 'verified' })
    await executeSeoAction('tok', ORG, ACTION.proposal_id, run)
    expect((run as ReturnType<typeof vi.fn>).mock.calls[0][0]).toMatch(/\/execute$/)

    const back = json({ ...ACTION, status: 'rolled_back' })
    await rollbackSeoAction('tok', ORG, ACTION.proposal_id, back)
    expect((back as ReturnType<typeof vi.fn>).mock.calls[0][0]).toMatch(/\/rollback$/)
  })
})

describe('action presentation', () => {
  const action = ACTION as unknown as Parameters<typeof statusNote>[0]

  it('explains known failure codes and falls back for unknown ones', () => {
    expect(describeError(null)).toBeNull()
    expect(describeError('external_claim_timeout')).toContain('never reported')
    expect(describeError('PublicVerificationFailed')).toContain('does not match')
    expect(describeError('Weird')).toBe('The action failed (Weird).')
  })

  it('describes verification evidence and recovered claims', () => {
    expect(describeVerification(null)).toBeNull()
    expect(
      describeVerification({
        verification: 'public-page-readback',
        value: 'New title | Site',
        page_url: 'https://example.com/p',
      }),
    ).toBe('Confirmed by live page read-back — "New title | Site" (https://example.com/p)')
    expect(wasRecovered({ ...action, executed_state: { execution: 'recovered-by-readback' } })).toBe(true)
    expect(wasRecovered(action)).toBe(false)
  })

  it('notes in-flight claims so the inbox keeps polling', () => {
    const executing = { ...action, status: 'executing' as const }
    expect(statusNote(executing)).toContain('15 minutes')
    expect(statusNote(action)).toBeNull()
    expect(hasInFlightClaim([action, executing])).toBe(true)
    expect(hasInFlightClaim([action])).toBe(false)
  })
})
