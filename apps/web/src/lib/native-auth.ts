export type NativeMethods = { enabled: boolean; signup_available: boolean; recovery_available: boolean }
export type NativeSession = { access_token: string; user_id: string; expires_in: number }
export type AccountSessionSummary = { session_id: string; expires_at: string; is_current: boolean }
export type NativeSignInResult = NativeSession | {
  mfa_required: true
  challenge: string
  expires_in: number
}

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

export async function signInNative(email: string, password: string): Promise<NativeSignInResult> {
  const response = await post('signin', { email, password })
  const value: unknown = await response.json()
  if (!value || typeof value !== 'object') {
    throw new NativeAuthError('The API returned an invalid sign-in response.', response.status)
  }
  if ('mfa_required' in value && value.mfa_required === true) {
    const recordValue = value as Record<string, unknown>
    if (
      typeof recordValue.challenge !== 'string' ||
      !/^rk1_[A-Za-z0-9_-]{43}$/.test(recordValue.challenge) ||
      typeof recordValue.expires_in !== 'number' ||
      !Number.isInteger(recordValue.expires_in) ||
      recordValue.expires_in <= 0 ||
      recordValue.expires_in > 300
    ) throw new NativeAuthError('The API returned an invalid MFA challenge.', response.status)
    return {
      mfa_required: true,
      challenge: recordValue.challenge,
      expires_in: recordValue.expires_in,
    }
  }
  if (
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

export async function listNativeSessions(token: string): Promise<AccountSessionSummary[]> {
  const response = await fetch('/api/v1/auth/sessions', {
    headers: { Authorization: `Bearer ${token}` },
    cache: 'no-store',
  })
  if (!response.ok) {
    throw new NativeAuthError('Account sessions could not be loaded.', response.status)
  }
  const value: unknown = await response.json()
  if (!Array.isArray(value)) {
    throw new NativeAuthError('The API returned invalid account sessions.', response.status)
  }
  const uuidHash = /^[0-9a-f]{64}$/i
  const date = /^\d{4}-\d{2}-\d{2}T/
  if (!value.every((row) =>
    row && typeof row === 'object' &&
    'session_id' in row && typeof row.session_id === 'string' && uuidHash.test(row.session_id) &&
    'expires_at' in row && typeof row.expires_at === 'string' && date.test(row.expires_at) &&
    'is_current' in row && typeof row.is_current === 'boolean')) {
    throw new NativeAuthError('The API returned invalid account sessions.', response.status)
  }
  return value as AccountSessionSummary[]
}

export async function revokeNativeSession(token: string, sessionId: string): Promise<void> {
  if (!/^[0-9a-f]{64}$/i.test(sessionId)) {
    throw new NativeAuthError('Invalid account session.', 422)
  }
  const response = await fetch(
    `/api/v1/auth/sessions/${encodeURIComponent(sessionId)}`,
    {
      method: 'DELETE',
      headers: { Authorization: `Bearer ${token}` },
      cache: 'no-store',
    },
  )
  if (!response.ok) {
    throw new NativeAuthError(
      response.status === 404
        ? 'The account session was not found.'
        : 'The account session could not be revoked.',
      response.status,
    )
  }
}

export async function confirmNativeSignInMfa(
  challenge: string,
  code: string,
): Promise<NativeSession> {
  const response = await post('signin/mfa', { challenge, code })
  const value: unknown = await response.json()
  if (
    !value || typeof value !== 'object' ||
    !('access_token' in value) || typeof value.access_token !== 'string' ||
    !/^rk1_[A-Za-z0-9_-]{43}$/.test(value.access_token) ||
    !('user_id' in value) || typeof value.user_id !== 'string' ||
    !/^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$/i.test(value.user_id) ||
    !('expires_in' in value) || typeof value.expires_in !== 'number' ||
    value.expires_in !== 3600
  ) throw new NativeAuthError('The API returned an invalid MFA session.', response.status)
  return { access_token: value.access_token, user_id: value.user_id, expires_in: value.expires_in }
}

export async function getMfaStatus(token: string): Promise<{ enabled: boolean; recovery_codes_remaining: number }> {
  const response = await fetch('/api/v1/auth/mfa', {
    headers: { Authorization: `Bearer ${token}` },
    cache: 'no-store',
  })
  if (!response.ok) throw new NativeAuthError('MFA status could not be loaded.', response.status)
  const value: unknown = await response.json()
  if (
    !value ||
    typeof value !== 'object' ||
    !('enabled' in value) ||
    typeof value.enabled !== 'boolean' ||
    !('recovery_codes_remaining' in value) ||
    typeof value.recovery_codes_remaining !== 'number'
  ) {
    throw new NativeAuthError('The API returned invalid MFA status.', response.status)
  }
  return {
    enabled: value.enabled,
    recovery_codes_remaining: value.recovery_codes_remaining,
  }
}

export async function enrollMfa(
  token: string,
): Promise<{ secret: string; otpauth_uri: string }> {
  const response = await post('mfa/enroll', undefined, token)
  const value: unknown = await response.json()
  const recordValue = value as Record<string, unknown> | null
  if (
    !recordValue ||
    typeof recordValue.secret !== 'string' ||
    typeof recordValue.otpauth_uri !== 'string'
  ) throw new NativeAuthError('The API returned invalid MFA enrollment.', response.status)
  return { secret: recordValue.secret, otpauth_uri: recordValue.otpauth_uri }
}

export async function confirmMfa(token: string, code: string): Promise<void> {
  await post('mfa/confirm', { code }, token)
}

export async function disableMfa(token: string, code: string): Promise<void> {
  await post('mfa/disable', { code }, token)
}

export async function rotateMfaRecoveryCodes(
  token: string,
): Promise<string[]> {
  const response = await post('mfa/recovery-codes', undefined, token)
  const value: unknown = await response.json()
  if (
    !value ||
    typeof value !== 'object' ||
    !('codes' in value) ||
    !Array.isArray(value.codes) ||
    !value.codes.every((code) => typeof code === 'string' && /^[0-9A-F]{12}$/.test(code))
  ) {
    throw new NativeAuthError('The API returned invalid recovery codes.', response.status)
  }
  return value.codes
}
