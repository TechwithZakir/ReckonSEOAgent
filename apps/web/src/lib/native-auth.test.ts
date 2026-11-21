import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  confirmPasswordReset, getNativeMethods, requestSignup, signInNative, signOutNative, verifySignup,
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
})
