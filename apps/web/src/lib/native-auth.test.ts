import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  confirmNativeSignInMfa,
  confirmPasswordReset, getNativeMethods, listNativeSessions, requestSignup,
  revokeNativeSession, signInNative, signOutNative, verifySignup,
  rotateMfaRecoveryCodes,
} from './native-auth'

afterEach(() => vi.unstubAllGlobals())

describe('native account API', () => {
  it('sends verification credentials only in the request body', async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(new Response(null, { status: 204 }))
    vi.stubGlobal('fetch', fetcher)
    await verifySignup('fixture-token', 'fixture-password')
    expect(fetcher).toHaveBeenCalledWith('/api/v1/auth/verify', expect.objectContaining({
      method: 'POST',
      cache: 'no-store',
      body: JSON.stringify({ token: 'fixture-token', password: 'fixture-password' }),
    }))
  })

  it('rejects invalid session responses without accepting a forged token', async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(new Response(JSON.stringify({
      access_token: 'unexpected', user_id: 'not-a-uuid', expires_in: 3600,
    })))
    vi.stubGlobal('fetch', fetcher)
    await expect(signInNative('fixture@example.com', 'fixture-password')).rejects.toThrow('invalid session')
  })

  it('sends recovery credentials in the body rather than the URL', async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(new Response(null, { status: 204 }))
    vi.stubGlobal('fetch', fetcher)
    await confirmPasswordReset('fixture-token', 'fixture-password')
    expect(fetcher).toHaveBeenCalledWith('/api/v1/auth/password-reset/confirm', expect.objectContaining({
      method: 'POST',
      cache: 'no-store',
      body: JSON.stringify({ token: 'fixture-token', password: 'fixture-password' }),
    }))
  })

  it('never displays the server response body on failure', async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(new Response('fixture-password', { status: 422 }))
    vi.stubGlobal('fetch', fetcher)
    await expect(requestSignup('fixture@example.com')).rejects.toThrow('Check the information')
  })

  it('accepts configured methods and revokes a session using bearer authorization', async () => {
    const fetcher = vi.fn<typeof fetch>()
      .mockResolvedValueOnce(new Response(JSON.stringify({
        enabled: true, signup_available: false, recovery_available: false,
      })))
      .mockResolvedValueOnce(new Response(null, { status: 204 }))
    vi.stubGlobal('fetch', fetcher)
    await expect(getNativeMethods()).resolves.toEqual({
      enabled: true, signup_available: false, recovery_available: false,
    })
    await signOutNative('fixture-session')
    expect(fetcher).toHaveBeenLastCalledWith('/api/v1/auth/signout', expect.objectContaining({
      method: 'POST',
      headers: { Authorization: 'Bearer fixture-session' },
      cache: 'no-store',
    }))
  })

  it('lists and revokes account sessions without exposing tokens', async () => {
    const sessionId = 'a'.repeat(64)
    const fetcher = vi.fn<typeof fetch>()
      .mockResolvedValueOnce(new Response(JSON.stringify([
        { session_id: sessionId, expires_at: '2026-01-01T10:00:00Z', is_current: true },
      ]), { status: 200 }))
      .mockResolvedValueOnce(new Response(null, { status: 204 }))
    vi.stubGlobal('fetch', fetcher)
    await expect(listNativeSessions('rk1_fixture')).resolves.toEqual([
      { session_id: sessionId, expires_at: '2026-01-01T10:00:00Z', is_current: true },
    ])
    await revokeNativeSession('rk1_fixture', sessionId)
    expect(fetcher).toHaveBeenLastCalledWith(
      `/api/v1/auth/sessions/${sessionId}`,
      expect.objectContaining({
        method: 'DELETE',
        headers: { Authorization: 'Bearer rk1_fixture' },
      }),
    )
  })

  it('parses MFA challenges and confirms a challenge session', async () => {
    const challenge = `rk1_${'a'.repeat(43)}`
    const accessToken = `rk1_${'b'.repeat(43)}`
    const fetcher = vi.fn<typeof fetch>()
      .mockResolvedValueOnce(new Response(JSON.stringify({
        mfa_required: true,
        challenge,
        expires_in: 300,
      }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({
        access_token: accessToken,
        user_id: 'bca7dcf3-908e-4dcf-a985-5cc68f2355ea',
        expires_in: 3600,
      }), { status: 200 }))
    vi.stubGlobal('fetch', fetcher)
    const { signInNative } = await import('./native-auth')
    await expect(signInNative('fixture@example.com', 'fixture-password')).resolves.toEqual({
      mfa_required: true,
      challenge,
      expires_in: 300,
    })
    await expect(confirmNativeSignInMfa(challenge, '123456')).resolves.toMatchObject({
      access_token: accessToken,
      expires_in: 3600,
    })
  })

  it('rotates MFA recovery codes and never sends them in the URL', async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(JSON.stringify({
        codes: ['A1B2C3D4E5F6', 'F6E5D4C3B2A1'],
      }), { status: 200 }),
    )
    vi.stubGlobal('fetch', fetcher)
    await expect(rotateMfaRecoveryCodes('rk1_fixture')).resolves.toEqual([
      'A1B2C3D4E5F6',
      'F6E5D4C3B2A1',
    ])
    expect(fetcher).toHaveBeenCalledWith(
      '/api/v1/auth/mfa/recovery-codes',
      expect.objectContaining({
        method: 'POST',
        headers: { Authorization: 'Bearer rk1_fixture' },
      }),
    )
  })
})
