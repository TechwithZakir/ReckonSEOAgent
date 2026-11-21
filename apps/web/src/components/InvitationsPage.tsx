import { useEffect, useState } from 'react'
import { useAuth } from '../auth/AuthContext'
import { acceptInvitation, listInvitations } from '../lib/organization-management'
import type { Invitation } from '../lib/organization-management'

export function InvitationsPage({ onNavigate }: { onNavigate: (path: string) => void }) {
  const auth = useAuth()
  const [invitations, setInvitations] = useState<Invitation[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [refresh, setRefresh] = useState(0)
  const token = auth.user?.access_token
  useEffect(() => {
    if (!token) return
    let active = true
    void listInvitations(token).then(
      (items) => { if (active) { setInvitations(items); setError(null) } },
      (cause: unknown) => { if (active) setError(cause instanceof Error ? cause.message : 'Could not load invitations.') },
    )
    return () => { active = false }
  }, [token, refresh])
  const accept = async (invite: Invitation) => {
    if (!token) return
    setBusy(true)
    setError(null)
    try {
      await acceptInvitation(token, invite.invitation_id)
      setMessage(`Joined ${invite.organization_name}. Select it in your workspace.`)
      setRefresh((value) => value + 1)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not accept the invitation.')
    } finally { setBusy(false) }
  }
  return (
    <div className="app-shell login-page">
      <header className="login-page__header">
        <a href="/" onClick={(event) => { event.preventDefault(); onNavigate('/') }}>Back to workspace</a>
      </header>
      <main className="login-page__main">
        <section className="login-card workspace-card__content">
          <h1>Organization invitations</h1>
          <p>Invitations appear only for a native account with the matching verified email address.</p>
          <p>Up to 50 pending invitations are shown, ordered by expiry.</p>
          {auth.status === 'initializing' && <p>Checking your sign-in…</p>}
          {auth.status !== 'signed-in' && auth.status !== 'initializing' && (
            <a href="/login?next=%2Finvitations"
              onClick={(event) => { event.preventDefault(); onNavigate('/login?next=%2Finvitations') }}>
              Sign in to view invitations
            </a>
          )}
          {auth.status === 'signed-in' && !invitations && !error && <p>Loading invitations…</p>}
          {invitations?.length === 0 && <p>No pending invitations for this verified account.</p>}
          {invitations && invitations.length > 0 && (
            <ul>{invitations.map((invite) => <li key={invite.invitation_id}>
              <strong>{invite.organization_name}</strong> · {invite.role} · expires {new Date(invite.expires_at).toLocaleString()}
              <button className="button button--primary" type="button" disabled={busy}
                onClick={() => void accept(invite)}>Accept invitation</button>
            </li>)}</ul>
          )}
          {error && <p className="workspace-setup__error" role="alert">{error}</p>}
          {error && token && <button type="button" onClick={() => setRefresh((value) => value + 1)}>Retry</button>}
          {message && <p role="status">{message}</p>}
        </section>
      </main>
    </div>
  )
}
