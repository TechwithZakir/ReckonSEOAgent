import {
  InMemoryWebStorage,
  UserManager,
  WebStorageStateStore,
} from 'oidc-client-ts'

export type OidcConfig = {
  authority: string
  clientId: string
  redirectUri: string
  postLogoutRedirectUri: string
  scope: string
  resource?: string
}

export type OidcConfigResult =
  | { kind: 'configured'; config: OidcConfig }
  | { kind: 'missing' }
  | { kind: 'invalid'; message: string }

export function resolveOidcConfig(
  environment: Record<string, string | undefined>,
  appOrigin: string,
): OidcConfigResult {
  const authority = environment.VITE_OIDC_AUTHORITY?.trim()
  const clientId = environment.VITE_OIDC_CLIENT_ID?.trim()
  if (!authority || !clientId) {
    return { kind: 'missing' }
  }

  try {
    const authorityUrl = new URL(authority)
    const originUrl = new URL(appOrigin)
    if (
      authorityUrl.protocol !== 'https:' ||
      authorityUrl.username ||
      authorityUrl.password ||
      authorityUrl.search ||
      authorityUrl.hash
    ) {
      return {
        kind: 'invalid',
        message: 'The identity provider authority must be a clean HTTPS issuer URL.',
      }
    }

    const isLoopback =
      originUrl.hostname === 'localhost' ||
      originUrl.hostname === '127.0.0.1' ||
      originUrl.hostname === '[::1]'
    if (originUrl.protocol !== 'https:' && !(originUrl.protocol === 'http:' && isLoopback)) {
      return {
        kind: 'invalid',
        message: 'The dashboard must use HTTPS outside local development.',
      }
    }

    const scope = environment.VITE_OIDC_SCOPE?.trim() || 'openid profile'
    if (!scope.split(/\s+/).includes('openid')) {
      return {
        kind: 'invalid',
        message: 'The configured OIDC scopes must include openid.',
      }
    }

    return {
      kind: 'configured',
      config: {
        authority: authorityUrl.href,
        clientId,
        redirectUri: new URL('/auth/callback', originUrl).href,
        postLogoutRedirectUri: new URL('/auth/signout-callback', originUrl).href,
        scope,
        resource: environment.VITE_OIDC_RESOURCE?.trim() || undefined,
      },
    }
  } catch {
    return {
      kind: 'invalid',
      message: 'The identity provider configuration contains an invalid URL.',
    }
  }
}

export function createOidcUserManager(
  config: OidcConfig,
  stateStorage: Storage,
): UserManager {
  return new UserManager({
    authority: config.authority,
    client_id: config.clientId,
    redirect_uri: config.redirectUri,
    post_logout_redirect_uri: config.postLogoutRedirectUri,
    response_type: 'code',
    scope: config.scope,
    resource: config.resource,
    stateStore: new WebStorageStateStore({
      prefix: 'reckon.oidc.state.',
      store: stateStorage,
    }),
    userStore: new WebStorageStateStore({
      prefix: 'reckon.oidc.user.',
      store: new InMemoryWebStorage(),
    }),
    automaticSilentRenew: false,
    monitorSession: false,
    loadUserInfo: false,
  })
}
