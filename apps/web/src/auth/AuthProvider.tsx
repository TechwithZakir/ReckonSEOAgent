import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react'
import type { ReactNode } from 'react'
import type { User } from 'oidc-client-ts'
import { AuthContext } from './AuthContext'
import type { AuthStatus } from './AuthContext'
import { NativeAuthError, listNativeSessions, signOutNative } from '../lib/native-auth'
import {
  clearNativeSession,
  loadNativeSession,
  saveNativeSession,
} from './native-session-store'
import type { NativeSession } from '../lib/native-auth'
import {
  createOidcUserManager,
  resolveOidcConfig,
} from './oidc'

const signInCallbackPath = '/auth/callback'
const signOutCallbackPath = '/auth/signout-callback'

export function AuthProvider({ children }: { children: ReactNode }) {
  const config = useMemo(
    () => resolveOidcConfig(import.meta.env, window.location.origin),
    [],
  )
  const manager = useMemo(
    () =>
      config.kind === 'configured'
        ? createOidcUserManager(config.config, window.sessionStorage)
        : null,
    [config],
  )
  const [user, setUser] = useState<User | null>(null)
  const [nativeSession, setNativeSession] = useState<NativeSession | null>(null)
  const [status, setStatus] = useState<AuthStatus>(
    config.kind === 'configured' ? 'initializing' : 'unconfigured',
  )
  const [error, setError] = useState<string | null>(null)
  const [restoring, setRestoring] = useState(
    () => loadNativeSession(window.sessionStorage) !== null,
  )
  const initializationRef = useRef<Promise<User | null> | null>(null)
  const sessionId = useMemo(
    () => user || nativeSession ? crypto.randomUUID() : null,
    [user, nativeSession],
  )

  useEffect(() => {
    if (!manager) {
      return
    }

    let active = true
    if (!initializationRef.current) {
      const callbackPath = window.location.pathname
      initializationRef.current = (async () => {
        try {
          if (callbackPath === signInCallbackPath) {
            return await manager.signinRedirectCallback()
          }
          if (callbackPath === signOutCallbackPath) {
            await manager.signoutRedirectCallback()
            return null
          }
          return await manager.getUser()
        } finally {
          if (
            callbackPath === signInCallbackPath ||
            callbackPath === signOutCallbackPath
          ) {
            window.history.replaceState({}, document.title, '/')
          }
        }
      })()
    }

    void initializationRef.current
      .then((currentUser) => {
        if (active) {
          const validUser =
            currentUser &&
            !currentUser.expired &&
            currentUser.access_token &&
            currentUser.profile.sub
              ? currentUser
              : null
          setUser(validUser)
          setStatus((previous) =>
            validUser ? 'signed-in' : previous === 'signed-in' ? previous : 'signed-out',
          )
          setError(null)
        }
      })
      .catch(() => {
        if (active) {
          setUser(null)
          setStatus('error')
          setError(
            'Sign-in could not be completed. Check the identity provider setup and try again.',
          )
        }
      })
    return () => {
      active = false
    }
  }, [manager])

  useEffect(() => {
    // Restore a native session after a page refresh, but only if the server still accepts it.
    const stored = loadNativeSession(window.sessionStorage)
    if (!stored) {
      return
    }
    let active = true
    void listNativeSessions(stored.access_token)
      .then(() => {
        if (active) {
          setUser(null)
          setNativeSession(stored)
          setStatus('signed-in')
        }
      })
      .catch((cause: unknown) => {
        if (cause instanceof NativeAuthError && cause.status === 401) {
          clearNativeSession(window.sessionStorage)
        }
      })
      .finally(() => {
        if (active) setRestoring(false)
      })
    return () => {
      active = false
    }
  }, [])

  const signIn = useCallback(async () => {
    if (!manager) {
      return
    }
    setError(null)
    try {
      await manager.signinRedirect()
    } catch {
      setError('Sign-in could not be started. Check the identity provider setup and try again.')
    }
  }, [manager])

  const acceptNativeSession = useCallback((session: NativeSession) => {
    setUser(null)
    saveNativeSession(window.sessionStorage, session)
    setNativeSession(session)
    setStatus('signed-in')
    setError(null)
  }, [])

  useEffect(() => {
    if (!nativeSession) return
    const timer = window.setTimeout(() => {
      clearNativeSession(window.sessionStorage)
      setNativeSession(null)
      setStatus(manager ? 'signed-out' : 'unconfigured')
      setError('Your session expired. Please sign in again.')
    }, nativeSession.expires_in * 1000)
    return () => window.clearTimeout(timer)
  }, [nativeSession, manager])

  useEffect(() => {
    // Detect server-side revocation (for example "sign out other sessions") without waiting
    // for the absolute expiry. Only a 401 signs the user out; network errors are ignored.
    if (!nativeSession) return
    const token = nativeSession.access_token
    let active = true
    const check = () => {
      void listNativeSessions(token).catch((cause: unknown) => {
        if (active && cause instanceof NativeAuthError && cause.status === 401) {
          clearNativeSession(window.sessionStorage)
          setNativeSession(null)
          setStatus(manager ? 'signed-out' : 'unconfigured')
          setError('Your session was ended. Please sign in again.')
        }
      })
    }
    const interval = window.setInterval(check, 60_000)
    window.addEventListener('focus', check)
    return () => {
      active = false
      window.clearInterval(interval)
      window.removeEventListener('focus', check)
    }
  }, [nativeSession, manager])

  const signOut = useCallback(async () => {
    if (nativeSession) {
      setError(null)
      try {
        await signOutNative(nativeSession.access_token)
      } catch (cause) {
        if (!(cause instanceof NativeAuthError && cause.status === 401)) {
          setError('Sign-out could not be completed. Please try again.')
          return
        }
      }
      clearNativeSession(window.sessionStorage)
      setNativeSession(null)
      setStatus(manager ? 'signed-out' : 'unconfigured')
      return
    }
    if (!manager) {
      return
    }
    setError(null)
    try {
      await manager.signoutRedirect()
    } catch {
      setError('Sign-out could not be completed. Try again or end the provider session directly.')
    }
  }, [manager, nativeSession])

  const value = useMemo(
    () => ({
      config, status: restoring ? ('initializing' as const) : status,
      user: nativeSession
        ? { access_token: nativeSession.access_token, profile: { sub: nativeSession.user_id, iss: 'reckon-native' } }
        : user,
      sessionId, error, signIn, signOut, acceptNativeSession,
    }),
    [config, status, restoring, user, nativeSession, sessionId, error, signIn, signOut, acceptNativeSession],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
