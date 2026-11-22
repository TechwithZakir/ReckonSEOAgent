import type { NativeSession } from '../lib/native-auth'

const KEY = 'reckon.native.session'

type StoredSession = { access_token: string; user_id: string; expires_at: number }

const TOKEN = /^rk1_[A-Za-z0-9_-]{43}$/
const UUID = /^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$/i

/**
 * Tab-scoped persistence so a page refresh does not sign the user out. The token is opaque,
 * server-revocable and bound to an absolute expiry; it is cleared on sign-out, expiry or any
 * 401 from the API, and is re-validated with the server before it is trusted again.
 */
export function saveNativeSession(
  storage: Storage,
  session: NativeSession,
  now: number = Date.now(),
): void {
  const stored: StoredSession = {
    access_token: session.access_token,
    user_id: session.user_id,
    expires_at: now + session.expires_in * 1000,
  }
  try {
    storage.setItem(KEY, JSON.stringify(stored))
  } catch {
    // Storage may be unavailable (private mode/quota); the in-memory session still works.
  }
}

export function loadNativeSession(
  storage: Storage,
  now: number = Date.now(),
): NativeSession | null {
  let raw: string | null
  try {
    raw = storage.getItem(KEY)
  } catch {
    return null
  }
  if (!raw) return null
  try {
    const value: unknown = JSON.parse(raw)
    if (
      value && typeof value === 'object' &&
      'access_token' in value && typeof value.access_token === 'string' &&
      TOKEN.test(value.access_token) &&
      'user_id' in value && typeof value.user_id === 'string' && UUID.test(value.user_id) &&
      'expires_at' in value && typeof value.expires_at === 'number'
    ) {
      const remaining = Math.floor((value.expires_at - now) / 1000)
      if (remaining > 0) {
        return { access_token: value.access_token, user_id: value.user_id, expires_in: remaining }
      }
    }
  } catch {
    // fall through to clearing the invalid entry
  }
  clearNativeSession(storage)
  return null
}

export function clearNativeSession(storage: Storage): void {
  try {
    storage.removeItem(KEY)
  } catch {
    // nothing to clear
  }
}
