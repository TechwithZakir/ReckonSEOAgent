import { createContext, useContext } from 'react'
import type { OidcConfigResult } from './oidc'
import type { NativeSession } from '../lib/native-auth'

export type AuthStatus =
  | 'initializing'
  | 'unconfigured'
  | 'signed-out'
  | 'signed-in'
  | 'error'

export type AuthContextValue = {
  config: OidcConfigResult
  status: AuthStatus
  user: { access_token: string; profile: { sub: string; iss?: string } } | null
  sessionId: string | null
  error: string | null
  signIn: () => Promise<void>
  acceptNativeSession: (session: NativeSession) => void
  signOut: () => Promise<void>
}

export const AuthContext = createContext<AuthContextValue | null>(null)

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext)
  if (!context) {
    throw new Error('useAuth must be used inside AuthProvider.')
  }
  return context
}
