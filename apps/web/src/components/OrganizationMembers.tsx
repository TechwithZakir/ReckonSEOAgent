import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { listOrganizationMembers } from '../lib/organizations'
import type { OrganizationContext, OrganizationMemberPage } from '../lib/organizations'
import { approveChange, proposeChange } from '../lib/organization-management'
import type { Proposal, ProposalInput } from '../lib/organization-management'

export function OrganizationMembers({
  accessToken, organization,
}: {
  accessToken: string
  organization: OrganizationContext
}) {
  const [page, setPage] = useState<OrganizationMemberPage | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [membersError, setMembersError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [retry, setRetry] = useState(0)
  const [action, setAction] = useState<ProposalInput['action']>('invite')
  const [email, setEmail] = useState('')
  const [userId, setUserId] = useState('')
  const [role, setRole] = useState<OrganizationContext['role']>('viewer')
  const [reason, setReason] = useState('')
  const [proposal, setProposal] = useState<Proposal | null>(null)
  const [result, setResult] = useState<string | null>(null)
  const key = useRef(crypto.randomUUID())
  useEffect(() => {
    let active = true
    void listOrganizationMembers(accessToken, organization.organization_id).then(
      (value) => { if (active) { setPage(value); setMembersError(null) } },
      () => { if (active) setMembersError('Could not load organization members.') },
    )
    return () => { active = false }
  }, [accessToken, organization.organization_id, retry])

  const loadMore = async () => {
    if (!page?.next_cursor) return
    setBusy(true)
    setMembersError(null)
    try {
      const next = await listOrganizationMembers(accessToken, organization.organization_id, page.next_cursor)
      setPage({ items: [...page.items, ...next.items], next_cursor: next.next_cursor })
    } catch {
      setMembersError('Could not load more organization members.')
    } finally {
      setBusy(false)
    }
  }
  const createProposal = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setBusy(true)
    setError(null)
    setResult(null)
    try {
      setProposal(await proposeChange(accessToken, organization.organization_id, {
        action, role, reason, ...(action === 'invite' ? { email } : { user_id: userId }),
      }, key.current))
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not create the proposal.')
    } finally { setBusy(false) }
  }
  const approve = async () => {
    if (!proposal) return
    setBusy(true)
    setError(null)
    try {
      const outcome = await approveChange(accessToken, organization.organization_id, proposal)
      setResult(outcome.notification_status === 'smtp_accepted'
        ? 'Invitation created. The mail server accepted the notification; delivery is not verified.'
        : outcome.notification_status === 'unconfirmed'
          ? 'Invitation exists, but notification delivery is unconfirmed.'
          : 'Role change applied.')
      setProposal(null)
      key.current = crypto.randomUUID()
      setRetry((value) => value + 1)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not approve the proposal.')
    } finally { setBusy(false) }
  }
  return (
    <section className="workspace-organizations" aria-labelledby="members-title">
      <strong id="members-title">Organization members</strong>
      {!page && !membersError && <p>Loading members…</p>}
      {page && (
        <ul>
          {page.items.map((member) => (
            <li key={member.user_id}>
              <span>
                <strong>{member.email ?? 'External identity'}</strong>
                <small>{member.role} · {member.user_id}</small>
              </span>
            </li>
          ))}
        </ul>
      )}
      {page?.next_cursor && (
        <button className="button button--secondary" type="button" disabled={busy} onClick={() => void loadMore()}>
          Load more members
        </button>
      )}
      {membersError && (
        <>
          <p className="workspace-setup__error" role="alert">{membersError}</p>
          <button className="button button--secondary" type="button" disabled={busy}
            onClick={() => { setPage(null); setMembersError(null); setRetry((value) => value + 1) }}>
            Retry members
          </button>
        </>
      )}
      <h3>Manage access</h3>
      <p>Owners manage all roles. Admins can manage editors and viewers only.</p>
      <p>Invitations require configured email and a recipient account with a verified matching email.</p>
      {!proposal ? (
        <form className="workspace-form" onSubmit={(event) => void createProposal(event)}>
          <label htmlFor="membership-action">Change type</label>
          <select id="membership-action" value={action} disabled={busy} onChange={(event) => {
            setAction(event.target.value === 'invite' ? 'invite' : 'role_change')
            key.current = crypto.randomUUID()
          }}>
            <option value="invite">Invite member</option>
            <option value="role_change">Change member role</option>
          </select>
          {action === 'invite' ? (
            <>
              <label htmlFor="member-email">Email address</label>
              <input id="member-email" type="email" maxLength={320} required value={email} disabled={busy}
                onChange={(event) => { setEmail(event.target.value); key.current = crypto.randomUUID() }} />
            </>
          ) : (
            <>
              <label htmlFor="member-target">Member</label>
              <select id="member-target" required value={userId} disabled={busy}
                onChange={(event) => { setUserId(event.target.value); key.current = crypto.randomUUID() }}>
                <option value="">Select a member</option>
                {page?.items.filter((member) => organization.role === 'owner' || !['owner', 'admin'].includes(member.role))
                  .map((member) => <option key={member.user_id} value={member.user_id}>
                    {member.email ?? member.user_id} ({member.role})
                  </option>)}
              </select>
            </>
          )}
          <label htmlFor="member-role">New role</label>
          <select id="member-role" value={role} disabled={busy} onChange={(event) => {
            const value = event.target.value
            if (value === 'owner' || value === 'admin' || value === 'editor' || value === 'viewer') setRole(value)
            key.current = crypto.randomUUID()
          }}>
            <option value="viewer">Viewer</option><option value="editor">Editor</option>
            {organization.role === 'owner' && <><option value="admin">Admin</option><option value="owner">Owner</option></>}
          </select>
          <label htmlFor="membership-reason">Reason</label>
          <input id="membership-reason" minLength={3} maxLength={200} required value={reason} disabled={busy}
            onChange={(event) => { setReason(event.target.value); key.current = crypto.randomUUID() }} />
          <button className="button button--primary" disabled={busy} type="submit">Review change</button>
        </form>
      ) : (
        <div>
          <h4>Review and approve</h4>
          <p>{proposal.action === 'invite' ? 'Invite' : 'Change role for'} {proposal.email ?? page?.items.find(
            (member) => member.user_id === proposal.user_id,
          )?.email ?? proposal.user_id} to <strong>{proposal.role}</strong>.</p>
          <p>Reason: {proposal.reason}</p>
          <p>Approval expires: {new Date(proposal.expires_at).toLocaleString()}</p>
          <button className="button button--primary" disabled={busy || proposal.approved}
            onClick={() => void approve()} type="button">Approve change</button>
          <button className="button button--secondary" disabled={busy}
            onClick={() => { setProposal(null); key.current = crypto.randomUUID(); setError(null) }} type="button">
            Cancel review
          </button>
        </div>
      )}
      {error && <p className="workspace-setup__error" role="alert">{error}</p>}
      {result && <p role="status">{result}</p>}
    </section>
  )
}
