import { afterEach, describe, expect, it, vi } from 'vitest'
import { acceptInvitation, approveChange, listInvitations, proposeChange } from './organization-management'

const id = 'bca7dcf3-908e-4dcf-a985-5cc68f2355ea'
const hash = 'a'.repeat(64)
const proposal = {
  id, action: 'invite' as const, role: 'viewer' as const, reason: 'Invite colleague',
  email: 'colleague@example.com', approval_hash: hash, expires_at: '2030-01-01T00:00:00Z', approved: false,
}

afterEach(() => vi.unstubAllGlobals())

describe('organization management client', () => {
  it('creates a proposal and separately approves its bound hash', async () => {
    const fetcher = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ ...proposal, user_id: null })))
      .mockResolvedValueOnce(new Response(JSON.stringify({
        approved: true, invitation_id: id, notification_status: 'smtp_accepted',
      })))
    vi.stubGlobal('fetch', fetcher)
    const result = await proposeChange('token', id, {
      action: 'invite', role: 'viewer', email: 'colleague@example.com', reason: 'Invite colleague',
    }, 'request-key')
    await expect(approveChange('token', id, result)).resolves.toMatchObject({ notification_status: 'smtp_accepted' })
    expect(fetcher.mock.calls[0][1].headers).toMatchObject({ Authorization: 'Bearer token', 'Idempotency-Key': 'request-key' })
    expect(JSON.parse(fetcher.mock.calls[1][1].body)).toEqual({ approval_hash: hash })
  })

  it('rejects invalid invitations and reports unconfirmed delivery as an error', async () => {
    const fetcher = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify([{ invitation_id: id, organization_id: id, role: 'owner' }])))
      .mockResolvedValueOnce(new Response(JSON.stringify({ detail: 'Invitation created, but email delivery could not be confirmed.' }), { status: 503 }))
    vi.stubGlobal('fetch', fetcher)
    await expect(listInvitations('token')).rejects.toThrow('invalid invitation list')
    await expect(approveChange('token', id, proposal)).rejects.toThrow('delivery could not be confirmed')
  })

  it('validates the accepted organization and does not trust malformed success', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ organization_id: id, role: 'root' }))))
    await expect(acceptInvitation('token', id)).rejects.toThrow('invalid invitation response')
  })
})
