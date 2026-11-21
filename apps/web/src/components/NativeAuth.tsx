import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { useAuth } from '../auth/AuthContext'
import {
  confirmPasswordReset, getNativeMethods, requestPasswordReset, requestSignup,
  confirmNativeSignInMfa, signInNative, verifySignup,
} from '../lib/native-auth'
import type { NativeMethods } from '../lib/native-auth'

export function NativeAuth({ onSignedIn }: { onSignedIn: () => void }) {
  const auth = useAuth()
  const [methods, setMethods] = useState<NativeMethods | null>(null)
  const [mode, setMode] = useState<'signin' | 'signup' | 'verify' | 'recover' | 'reset'>(() => {
    if (window.location.pathname === '/auth/verify') return 'verify'
    if (window.location.pathname === '/auth/reset') return 'reset'
    return 'signin'
  })
  const [token, setToken] = useState<string | null>(() =>
    window.location.pathname === '/auth/verify' || window.location.pathname === '/auth/reset'
      ? new URLSearchParams(window.location.hash.slice(1)).get('token')
      : null,
  )
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirmation, setConfirmation] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const [mfaChallenge, setMfaChallenge] = useState<string | null>(null)

  useEffect(() => {
    if (window.location.pathname === '/auth/verify' || window.location.pathname === '/auth/reset') {
      window.history.replaceState({}, document.title, '/login')
    }
    let active = true
    void getNativeMethods().then(
      (value) => { if (active) setMethods(value) },
      () => { if (active) setError('Could not check account availability. Please refresh and try again.') },
    )
    return () => { active = false }
  }, [])

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setBusy(true)
    setError(null)
    setMessage(null)
    try {
      if (mfaChallenge) {
        if (!/^(?:[0-9]{6}|[0-9A-F]{12})$/.test(password)) {
          setError('Enter a 6-digit MFA code or 12-character recovery code.')
          return
        }
        const session = await confirmNativeSignInMfa(mfaChallenge, password)
        setMfaChallenge(null)
        setPassword('')
        auth.acceptNativeSession(session)
        onSignedIn()
      } else if (mode === 'signup') {
        await requestSignup(email)
        setMessage('If eligible, you will receive a verification email.')
      } else if (mode === 'recover') {
        await requestPasswordReset(email)
        setMessage('If eligible, you will receive a recovery email.')
      } else if (mode === 'verify' || mode === 'reset') {
        if (!token || !/^[A-Za-z0-9_-]{43}$/.test(token)) {
          setError('This link is invalid or expired.')
          return
        }
        if (password !== confirmation) {
          setError('The passwords do not match.')
          return
        }
        if (mode === 'verify') await verifySignup(token, password)
        else await confirmPasswordReset(token, password)
        setToken(null)
        setPassword('')
        setConfirmation('')
        setMode('signin')
        setMessage(mode === 'verify' ? 'Email verified. You can now sign in.' : 'Password updated. You can now sign in.')
      } else {
        const session = await signInNative(email, password)
        if ('mfa_required' in session) {
          setMfaChallenge(session.challenge)
          setPassword('')
          setMessage('Enter the 6-digit MFA code to complete sign-in.')
        } else {
          setPassword('')
          auth.acceptNativeSession(session)
          onSignedIn()
        }
      }
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Account access could not be completed.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="native-auth">
      <p>{mode === 'verify' ? 'Choose a password to finish verifying your account.'
        : mode === 'reset' ? 'Choose a new password for your account.'
          : mode === 'recover' ? 'Request a password recovery email.'
            : 'Use your Reckon account to access your organizations.'}</p>
      {!methods?.enabled && !error && (
        <p>{methods ? 'Reckon account sign-in is not enabled on the API.' : 'Checking Reckon account availability…'}</p>
      )}
      <form className="workspace-form" onSubmit={(event) => void submit(event)}>
        {mfaChallenge && (
          <>
            <label htmlFor="native-mfa-code">MFA code</label>
            <input
              id="native-mfa-code"
              inputMode="numeric"
              pattern="[0-9]{6}|[0-9A-F]{12}"
              minLength={6}
              maxLength={12}
              required
              disabled={busy}
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />
          </>
        )}
        {!mfaChallenge && mode !== 'verify' && mode !== 'reset' && (
          <>
            <label htmlFor="native-email">Email address</label>
            <input id="native-email" type="email" autoComplete="email" maxLength={320} required disabled={busy || !methods?.enabled}
              value={email} onChange={(event) => setEmail(event.target.value)} />
          </>
        )}
        {!mfaChallenge && mode !== 'signup' && mode !== 'recover' && (
          <>
            <label htmlFor="native-password">{mode === 'verify' || mode === 'reset' ? 'Choose a password' : 'Password'}</label>
            <input id="native-password" type="password" autoComplete={mode === 'verify' || mode === 'reset' ? 'new-password' : 'current-password'}
              minLength={mode === 'verify' || mode === 'reset' ? 12 : undefined} maxLength={128} required disabled={busy || !methods?.enabled}
              value={password} onChange={(event) => setPassword(event.target.value)} />
            {(mode === 'verify' || mode === 'reset') && <p>Use 12 to 128 characters.</p>}
            {(mode === 'verify' || mode === 'reset') && (
              <>
                <label htmlFor="native-confirmation">Confirm password</label>
                <input id="native-confirmation" type="password" autoComplete="new-password"
                  minLength={12} maxLength={128} required disabled={busy || !methods?.enabled}
                  value={confirmation} onChange={(event) => setConfirmation(event.target.value)} />
              </>
            )}
          </>
        )}
        {error && <p className="workspace-setup__error" role="alert">{error}</p>}
        {message && <p role="status">{message}</p>}
        <button className="button button--primary" disabled={busy || !methods?.enabled || auth.status === 'initializing'} type="submit">
          {busy ? 'Working…' : mfaChallenge ? 'Complete MFA sign-in' : mode === 'verify' ? 'Verify account' : mode === 'signup' ? 'Send verification email'
            : mode === 'recover' ? 'Send recovery email' : mode === 'reset' ? 'Reset password' : 'Sign in with email'}
        </button>
      </form>
      {mode === 'signin' && (
        <button className="button button--secondary" type="button" disabled={busy || !methods?.enabled || !methods.signup_available}
          onClick={() => { setMode('signup'); setError(null); setMessage(null); setPassword('') }}>
          Create an account
        </button>
      )}
      {mode === 'signin' && (
        <button className="button button--secondary" type="button" disabled={busy || !methods?.enabled || !methods.recovery_available}
          onClick={() => { setMode('recover'); setError(null); setMessage(null); setPassword('') }}>
          Forgot password
        </button>
      )}
      {mode !== 'signin' && (
        <button className="button button--secondary" type="button" disabled={busy}
          onClick={() => { setMode('signin'); setToken(null); setError(null); setMessage(null); setPassword(''); setConfirmation('') }}>
          Back to sign in
        </button>
      )}
      {methods?.enabled && !methods.signup_available && mode === 'signin' && <p>Account registration email is not configured.</p>}
      {methods?.enabled && !methods.recovery_available && mode === 'signin' && <p>Password recovery email is not configured.</p>}
    </div>
  )
}
