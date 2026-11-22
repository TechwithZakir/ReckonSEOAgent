import { describe, expect, it, vi } from 'vitest'
import { issuePluginToken, listPluginScopes, listPluginTokens, revokePluginToken, tokenState } from './plugin-tokens'

const ORG = '11111111-1111-4111-8111-111111111111'
const ROW = {
  token_id: '22222222-2222-4222-8222-222222222222',
  label: 'Claude plugin',
  scopes: ['reckon.seo_action.claim'],
  created_at: '2026-11-22T00:00:00Z',
  expires_at: '2026-12-22T00:00:00Z',
  revoked_at: null,
  last_used_at: null,
}
const reply = (body: unknown, status = 200) =>
  vi.fn().mockResolvedValue(new Response(JSON.stringify(body), { status }))

describe('plugin tokens client', () => {
  it('lists, issues and revokes with the bearer token', async () => {
    const list = reply([ROW])
    expect(await listPluginTokens('t', ORG, list)).toEqual([ROW])
    expect(list.mock.calls[0][1].headers.Authorization).toBe('Bearer t')

    const issue = reply({ ...ROW, token: 'rkpt_abc' }, 201)
    const issued = await issuePluginToken('t', ORG, { label: 'Claude plugin', lifetime_days: 30 }, issue)
    expect(issued.token).toBe('rkpt_abc')
    expect(JSON.parse(issue.mock.calls[0][1].body)).toEqual({ label: 'Claude plugin', lifetime_days: 30 })

    const revoke = reply({ ...ROW, revoked_at: '2026-11-23T00:00:00Z' })
    await revokePluginToken('t', ORG, ROW.token_id, revoke)
    expect(revoke.mock.calls[0][1].method).toBe('DELETE')
  })

  it('rejects malformed responses and explains denials', async () => {
    await expect(listPluginTokens('t', ORG, reply([{ ...ROW, scopes: 'x' }]))).rejects.toThrow('invalid')
    await expect(
      issuePluginToken('t', ORG, { label: 'a', lifetime_days: 30 }, reply({ ...ROW, token: 'bad' }, 201)),
    ).rejects.toThrow('invalid')
    await expect(listPluginTokens('t', ORG, reply({}, 403))).rejects.toThrow('owners and admins')
  })

  it('loads and validates the scope catalogue', async () => {
    const ok = reply({ allowed: ['a', 'b'], default: ['a'] })
    expect(await listPluginScopes('t', ORG, ok)).toEqual({ allowed: ['a', 'b'], default: ['a'] })
    expect(ok.mock.calls[0][0]).toContain('/plugin-tokens/scopes')
    await expect(listPluginScopes('t', ORG, reply({ allowed: 'a', default: [] }))).rejects.toThrow('invalid')
  })

  it('classifies token state', () => {
    const now = new Date('2026-12-01T00:00:00Z')
    expect(tokenState(ROW, now)).toBe('active')
    expect(tokenState({ ...ROW, revoked_at: '2026-11-30T00:00:00Z' }, now)).toBe('revoked')
    expect(tokenState(ROW, new Date('2027-01-01T00:00:00Z'))).toBe('expired')
  })
})
