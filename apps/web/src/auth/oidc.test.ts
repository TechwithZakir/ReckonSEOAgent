import { describe, expect, it } from 'vitest'
import { resolveOidcConfig } from './oidc'

describe('resolveOidcConfig', () => {
  it('keeps sign-in unavailable until authority and public client ID are configured', () => {
    expect(resolveOidcConfig({}, 'http://127.0.0.1:5173')).toEqual({
      kind: 'missing',
    })
  })

  it('builds callback URLs for a secure authority and local dashboard', () => {
    expect(
      resolveOidcConfig(
        {
          VITE_OIDC_AUTHORITY: 'https://login.example.org/tenant',
          VITE_OIDC_CLIENT_ID: 'reckon-dashboard',
          VITE_OIDC_RESOURCE: 'https://api.example.org',
        },
        'http://127.0.0.1:5173',
      ),
    ).toEqual({
      kind: 'configured',
      config: {
        authority: 'https://login.example.org/tenant',
        clientId: 'reckon-dashboard',
        redirectUri: 'http://127.0.0.1:5173/auth/callback',
        postLogoutRedirectUri: 'http://127.0.0.1:5173/auth/signout-callback',
        scope: 'openid profile',
        resource: 'https://api.example.org',
      },
    })
  })

  it('rejects insecure or credential-bearing authority URLs and OIDC scopes without openid', () => {
    expect(
      resolveOidcConfig(
        {
          VITE_OIDC_AUTHORITY: 'http://login.example.org',
          VITE_OIDC_CLIENT_ID: 'reckon-dashboard',
        },
        'https://dashboard.example.org',
      ),
    ).toMatchObject({ kind: 'invalid' })

    expect(
      resolveOidcConfig(
        {
          VITE_OIDC_AUTHORITY: 'https://user:pass@login.example.org',
          VITE_OIDC_CLIENT_ID: 'reckon-dashboard',
        },
        'https://dashboard.example.org',
      ),
    ).toMatchObject({ kind: 'invalid' })

    expect(
      resolveOidcConfig(
        {
          VITE_OIDC_AUTHORITY: 'https://login.example.org',
          VITE_OIDC_CLIENT_ID: 'reckon-dashboard',
          VITE_OIDC_SCOPE: 'profile email',
        },
        'https://dashboard.example.org',
      ),
    ).toMatchObject({ kind: 'invalid' })
  })

  it('requires HTTPS for non-loopback dashboard origins', () => {
    expect(
      resolveOidcConfig(
        {
          VITE_OIDC_AUTHORITY: 'https://login.example.org',
          VITE_OIDC_CLIENT_ID: 'reckon-dashboard',
        },
        'http://dashboard.example.org',
      ),
    ).toMatchObject({ kind: 'invalid' })
  })
})
