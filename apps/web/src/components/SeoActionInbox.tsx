import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import {
  approveSeoAction,
  describeError,
  describeVerification,
  executeSeoAction,
  hasInFlightClaim,
  listSeoActions,
  proposeSeoAction,
  rejectSeoAction,
  rollbackSeoAction,
  statusNote,
  wasRecovered,
} from '../lib/seo-actions'
import type { SeoAction } from '../lib/seo-actions'
import type { OrganizationContext } from '../lib/organizations'

export function SeoActionInbox({
  accessToken,
  organization,
}: {
  accessToken: string
  organization: OrganizationContext
}) {
  const [actions, setActions] = useState<SeoAction[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const [websiteId, setWebsiteId] = useState('')
  const [targetUrl, setTargetUrl] = useState('')
  const [targetVersion, setTargetVersion] = useState('v1')
  const [actionType, setActionType] = useState<'meta_title' | 'meta_description' | 'canonical' | 'heading' | 'schema' | 'redirect' | 'internal_link' | 'other'>('meta_title')
  const [risk, setRisk] = useState<'low' | 'medium' | 'high'>('low')
  const [reason, setReason] = useState('')
  const [beforeValue, setBeforeValue] = useState('')
  const [afterValue, setAfterValue] = useState('')

  const refresh = async () => {
    setError(null)
    try {
      setActions(await listSeoActions(accessToken, organization.organization_id))
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not load SEO actions.')
    }
  }

  useEffect(() => {
    let active = true
    void listSeoActions(accessToken, organization.organization_id)
      .then((rows) => { if (active) setActions(rows) })
      .catch((cause: unknown) => {
        if (active) setError(cause instanceof Error ? cause.message : 'Could not load SEO actions.')
      })
    return () => { active = false }
  }, [accessToken, organization.organization_id])

  const watching = hasInFlightClaim(actions)
  useEffect(() => {
    if (!watching) return undefined
    const timer = window.setInterval(() => {
      void listSeoActions(accessToken, organization.organization_id)
        .then(setActions)
        .catch(() => undefined)
    }, 15000)
    return () => window.clearInterval(timer)
  }, [watching, accessToken, organization.organization_id])

  const propose = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setBusy(true)
    setError(null)
    setMessage(null)
    try {
      await proposeSeoAction(
        accessToken,
        organization.organization_id,
        crypto.randomUUID(),
        {
          website_id: websiteId,
          action_type: actionType,
          target_url: targetUrl,
          target_version: targetVersion,
          before_state: { value: beforeValue },
          proposed_state: { value: afterValue },
          risk,
          reason,
        },
      )
      setMessage('Action proposed. Approval is required before fixture execution.')
      setReason('')
      setBeforeValue('')
      setAfterValue('')
      await refresh()
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not propose SEO action.')
    } finally {
      setBusy(false)
    }
  }

  const decide = async (action: SeoAction, operation: 'approve' | 'reject') => {
    setBusy(true)
    setError(null)
    setMessage(null)
    try {
      if (operation === 'approve') {
        await approveSeoAction(
          accessToken,
          organization.organization_id,
          action.proposal_id,
          action.approval_hash,
        )
      } else {
        await rejectSeoAction(
          accessToken,
          organization.organization_id,
          action.proposal_id,
        )
      }
      setMessage(operation === 'approve' ? 'Action approved.' : 'Action rejected.')
      await refresh()
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not update SEO action.')
    } finally {
      setBusy(false)
    }
  }

  const execute = async (action: SeoAction) => {
    setBusy(true)
    setError(null)
    setMessage(null)
    try {
      const result = await executeSeoAction(
        accessToken,
        organization.organization_id,
        action.proposal_id,
      )
      setMessage(
        result.status === 'verified'
          ? 'Fixture execution and independent verification passed.'
          : 'Execution did not verify.',
      )
      await refresh()
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not execute SEO action.')
    } finally {
      setBusy(false)
    }
  }

  const rollback = async (action: SeoAction) => {
    setBusy(true)
    setError(null)
    setMessage(null)
    try {
      await rollbackSeoAction(
        accessToken,
        organization.organization_id,
        action.proposal_id,
      )
      setMessage('Action rollback completed in the fixture executor.')
      await refresh()
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not rollback SEO action.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="workspace-card">
      <div className="workspace-card__content">
        <h2>Approval Inbox</h2>
        {error && <p className="workspace-setup__error" role="alert">{error}</p>}
        {message && <p role="status">{message}</p>}
        {(organization.role === 'owner' || organization.role === 'admin') && (
          <form className="workspace-form" onSubmit={(event) => void propose(event)}>
            <label htmlFor="action-website">Website ID</label>
            <input id="action-website" required value={websiteId} disabled={busy} onChange={(event) => setWebsiteId(event.target.value)} />
            <label htmlFor="action-type">Action type</label>
            <select id="action-type" value={actionType} disabled={busy} onChange={(event) => setActionType(event.target.value as typeof actionType)}>
              <option value="meta_title">Meta title</option>
              <option value="meta_description">Meta description</option>
              <option value="canonical">Canonical</option>
              <option value="heading">Heading</option>
              <option value="schema">Schema</option>
              <option value="redirect">Redirect</option>
              <option value="internal_link">Internal link</option>
              <option value="other">Other</option>
            </select>
            <label htmlFor="action-url">Target URL</label>
            <input id="action-url" type="url" required value={targetUrl} disabled={busy} onChange={(event) => setTargetUrl(event.target.value)} />
            <label htmlFor="action-version">Target version</label>
            <input id="action-version" required value={targetVersion} disabled={busy} onChange={(event) => setTargetVersion(event.target.value)} />
            <label htmlFor="action-risk">Risk</label>
            <select id="action-risk" value={risk} disabled={busy} onChange={(event) => setRisk(event.target.value as typeof risk)}>
              <option value="low">Low</option>
              <option value="medium">Medium</option>
              <option value="high">High</option>
            </select>
            <label htmlFor="action-before">Before state</label>
            <textarea id="action-before" required value={beforeValue} disabled={busy} onChange={(event) => setBeforeValue(event.target.value)} />
            <label htmlFor="action-after">Proposed state</label>
            <textarea id="action-after" required value={afterValue} disabled={busy} onChange={(event) => setAfterValue(event.target.value)} />
            <label htmlFor="action-reason">Reason</label>
            <input id="action-reason" required minLength={3} maxLength={200} value={reason} disabled={busy} onChange={(event) => setReason(event.target.value)} />
            <button className="button button--primary" type="submit" disabled={busy}>Create proposal</button>
          </form>
        )}
        <h3>Proposals</h3>
        {actions.length === 0 && <p>No SEO actions have been proposed.</p>}
        {actions.map((action) => (
          <article className="workspace-card" key={action.proposal_id}>
            <div className="workspace-card__content">
              <span className={`status-label status-label--${action.status === 'verified' ? 'healthy' : action.status === 'failed' ? 'unavailable' : 'muted'}`}>{action.status.replace('_', ' ')}</span>
              <h3>{action.action_type} · {action.risk} risk</h3>
              <p>{action.target_url}</p>
              <p>Reason: {action.reason}</p>
              <dl>
                <dt>Before</dt><dd>{action.before_state.value ?? '—'}</dd>
                <dt>Proposed</dt><dd>{action.proposed_state.value ?? '—'}</dd>
                <dt>Expires</dt><dd>{new Date(action.expires_at).toLocaleString()}</dd>
              </dl>
              {statusNote(action) && <p role="status">{statusNote(action)}</p>}
              {wasRecovered(action) && (
                <p role="status">The executor never reported; Reckon found the approved value live and recorded it as verified.</p>
              )}
              {describeError(action.error_code) && (
                <p className="workspace-setup__error" role="alert">{describeError(action.error_code)}</p>
              )}
              {action.status === 'proposed' && (
                <div>
                  <button className="button button--primary" type="button" disabled={busy} onClick={() => void decide(action, 'approve')}>Approve</button>
                  <button className="button button--secondary" type="button" disabled={busy} onClick={() => void decide(action, 'reject')}>Reject</button>
                </div>
              )}
              {action.status === 'approved' && (
                <button className="button button--primary" type="button" disabled={busy} onClick={() => void execute(action)}>Execute fixture staging action</button>
              )}
              {['executed', 'verified', 'failed'].includes(action.status) && (
                <button className="button button--secondary" type="button" disabled={busy} onClick={() => void rollback(action)}>Rollback</button>
              )}
              {describeVerification(action.verification_state) && (
                <p>{describeVerification(action.verification_state)}</p>
              )}
            </div>
          </article>
        ))}
      </div>
    </section>
  )
}
