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
  const [status, setStatus] = useState<AuthStatus>(
    config.kind === 'configured' ? 'initializing' : 'unconfigured',
  )
  const [error, setError] = useState<string | null>(null)
  const initializationRef = useRef<Promise<User | null> | null>(null)

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
          setStatus(validUser ? 'signed-in' : 'signed-out')
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

  const signOut = useCallback(async () => {
    if (!manager) {
      return
    }
    setError(null)
    try {
      await manager.signoutRedirect()
    } catch {
      setError('Sign-out could not be completed. Try again or end the provider session directly.')
    }
  }, [manager])

  const value = useMemo(
    () => ({ config, status, user, error, signIn, signOut }),
    [config, status, user, error, signIn, signOut],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
