import { createContext, useContext } from 'react'
import type { User } from 'oidc-client-ts'
import type { OidcConfigResult } from './oidc'

export type AuthStatus =
  | 'initializing'
  | 'unconfigured'
  | 'signed-out'
  | 'signed-in'
  | 'error'

export type AuthContextValue = {
  config: OidcConfigResult
  status: AuthStatus
  user: User | null
  error: string | null
  signIn: () => Promise<void>
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
