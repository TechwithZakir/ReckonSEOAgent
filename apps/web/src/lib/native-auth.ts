export type NativeMethods = { enabled: boolean; signup_available: boolean; recovery_available: boolean }
export type NativeSession = { access_token: string; user_id: string; expires_in: number }

export class NativeAuthError extends Error {
  readonly status: number

  constructor(message: string, status: number) {
    super(message)
    this.name = 'NativeAuthError'
    this.status = status
  }
}

async function post(path: string, body: object | undefined, token?: string): Promise<Response> {
  const response = await fetch(`/api/v1/auth/${path}`, {
    method: 'POST',
    headers: {
      ...(body ? { 'Content-Type': 'application/json' } : {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
    cache: 'no-store',
  })
  if (!response.ok) {
    const messages: Record<number, string> = {
      400: path === 'verify' || path === 'password-reset/confirm'
        ? 'This link is invalid or expired.' : 'The request could not be completed.',
      401: path === 'signin' ? 'Email or password is incorrect.' : 'Your session has expired.',
      422: 'Check the information entered and try again.',
      429: 'Too many requests. Please try again later.',
      503: 'Account access is temporarily unavailable. Please try again later.',
    }
    throw new NativeAuthError(messages[response.status] ?? 'Account access could not be completed.', response.status)
  }
  return response
}

export async function getNativeMethods(): Promise<NativeMethods> {
  const response = await fetch('/api/v1/auth/methods', { cache: 'no-store' })
  if (!response.ok) throw new NativeAuthError('Could not check account availability.', response.status)
  const value: unknown = await response.json()
  if (
    !value || typeof value !== 'object' ||
    !('enabled' in value) || typeof value.enabled !== 'boolean' ||
    !('signup_available' in value) || typeof value.signup_available !== 'boolean' ||
    !('recovery_available' in value) || typeof value.recovery_available !== 'boolean'
  ) throw new NativeAuthError('The API returned an invalid account configuration.', response.status)
  return {
    enabled: value.enabled, signup_available: value.signup_available,
    recovery_available: value.recovery_available,
  }
}

export async function requestSignup(email: string): Promise<void> {
  await post('signup', { email })
}

export async function verifySignup(token: string, password: string): Promise<void> {
  await post('verify', { token, password })
}

export async function requestPasswordReset(email: string): Promise<void> {
  await post('password-reset', { email })
}

export async function confirmPasswordReset(token: string, password: string): Promise<void> {
  await post('password-reset/confirm', { token, password })
}

export async function signInNative(email: string, password: string): Promise<NativeSession> {
  const response = await post('signin', { email, password })
  const value: unknown = await response.json()
  if (
    !value || typeof value !== 'object' ||
    !('access_token' in value) || typeof value.access_token !== 'string' ||
    !/^rk1_[A-Za-z0-9_-]{43}$/.test(value.access_token) ||
    !('user_id' in value) || typeof value.user_id !== 'string' ||
    !/^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$/i.test(value.user_id) ||
    !('expires_in' in value) || typeof value.expires_in !== 'number' ||
    !Number.isInteger(value.expires_in) || value.expires_in <= 0 || value.expires_in > 3600
  ) throw new NativeAuthError('The API returned an invalid session.', response.status)
  return { access_token: value.access_token, user_id: value.user_id, expires_in: value.expires_in }
}

export async function signOutNative(token: string): Promise<void> {
  await post('signout', undefined, token)
}
