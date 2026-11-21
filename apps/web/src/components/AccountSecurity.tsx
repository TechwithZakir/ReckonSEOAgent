import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import {
  confirmMfa,
  disableMfa,
  enrollMfa,
  getMfaStatus,
  listNativeSessions,
  revokeNativeSession,
} from '../lib/native-auth'
import type { AccountSessionSummary } from '../lib/native-auth'

export function AccountSecurity({ accessToken }: { accessToken: string }) {
  const [enabled, setEnabled] = useState(false)
  const [sessions, setSessions] = useState<AccountSessionSummary[]>([])
  const [secret, setSecret] = useState<string | null>(null)
  const [code, setCode] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)

  useEffect(() => {
    let active = true
    void Promise.all([
      getMfaStatus(accessToken),
      listNativeSessions(accessToken),
    ]).then(
      ([mfa, accountSessions]) => {
        if (active) {
          setEnabled(mfa.enabled)
          setSessions(accountSessions)
        }
      },
      (cause: unknown) => {
        if (active) setError(cause instanceof Error ? cause.message : 'Could not load account security.')
      },
    )
    return () => { active = false }
  }, [accessToken])

  const enroll = async () => {
    setBusy(true)
    setError(null)
    setMessage(null)
    try {
      const enrollment = await enrollMfa(accessToken)
      setSecret(enrollment.secret)
      setMessage('Add this secret to your authenticator, then enter a 6-digit code to confirm.')
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not start MFA enrollment.')
    } finally {
      setBusy(false)
    }
  }

  const confirm = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await confirmMfa(accessToken, code)
      setEnabled(true)
      setSecret(null)
      setCode('')
      setMessage('MFA is enabled.')
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not confirm MFA.')
    } finally {
      setBusy(false)
    }
  }

  const disable = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await disableMfa(accessToken, code)
      setEnabled(false)
      setCode('')
      setMessage('MFA is disabled.')
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not disable MFA.')
    } finally {
      setBusy(false)
    }
  }

  const revoke = async (sessionId: string) => {
    setBusy(true)
    setError(null)
    try {
      await revokeNativeSession(accessToken, sessionId)
      setSessions((current) => current.filter((session) => session.session_id !== sessionId))
      setMessage('Other account session revoked.')
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not revoke the session.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <section id="account-security" aria-labelledby="account-security-title" className="ai-settings-card">
      <div className="section-heading">
        <div>
          <p className="section-kicker">ACCOUNT SECURITY</p>
          <h2 id="account-security-title">MFA and sessions</h2>
        </div>
        <span className="section-note">Native accounts</span>
      </div>
      {error && <p className="workspace-setup__error" role="alert">{error}</p>}
      {message && <p role="status">{message}</p>}
      <h3>Authenticator app</h3>
      <p>MFA status: <strong>{enabled ? 'Enabled' : 'Disabled'}</strong></p>
      {!enabled && !secret && (
        <button className="button button--primary" type="button" disabled={busy} onClick={() => void enroll()}>
          Enroll MFA
        </button>
      )}
      {!enabled && secret && (
        <form className="ai-settings-form" onSubmit={(event) => void confirm(event)}>
          <label htmlFor="mfa-secret">Setup secret</label>
          <input id="mfa-secret" readOnly value={secret} />
          <label htmlFor="mfa-confirm-code">Authenticator code</label>
          <input
            id="mfa-confirm-code"
            inputMode="numeric"
            pattern="[0-9]{6}"
            minLength={6}
            maxLength={6}
            required
            value={code}
            disabled={busy}
            onChange={(event) => setCode(event.target.value)}
          />
          <button className="button button--primary" type="submit" disabled={busy}>Confirm MFA</button>
        </form>
      )}
      {enabled && (
        <form className="ai-settings-form" onSubmit={(event) => void disable(event)}>
          <label htmlFor="mfa-disable-code">Authenticator code</label>
          <input
            id="mfa-disable-code"
            inputMode="numeric"
            pattern="[0-9]{6}"
            minLength={6}
            maxLength={6}
            required
            value={code}
            disabled={busy}
            onChange={(event) => setCode(event.target.value)}
          />
          <button className="button button--secondary" type="submit" disabled={busy}>Disable MFA</button>
        </form>
      )}
      <h3>Active sessions</h3>
      {sessions.length === 0 && <p>No active native sessions.</p>}
      {sessions.length > 0 && (
        <ul>
          {sessions.map((session) => (
            <li key={session.session_id}>
              <strong>{session.is_current ? 'Current session' : 'Other session'}</strong>
              <p>Expires {new Date(session.expires_at).toLocaleString()}</p>
              {!session.is_current && (
                <button
                  className="button button--secondary"
                  type="button"
                  disabled={busy}
                  onClick={() => void revoke(session.session_id)}
                >
                  Revoke session
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
