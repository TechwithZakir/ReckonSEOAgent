import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { DRAFT_FIELDS, requestFixDraft } from '../lib/fix-drafts'
import type { DraftField, FixDraft } from '../lib/fix-drafts'
import { listWebsites } from '../lib/websites'
import type { Website } from '../lib/websites'
import type { OrganizationContext } from '../lib/organizations'

export function AiFixDraft({
  accessToken,
  organization,
  onDrafted,
}: {
  accessToken: string
  organization: OrganizationContext
  onDrafted: () => void
}) {
  const [websites, setWebsites] = useState<Website[]>([])
  const [loadError, setLoadError] = useState<string | null>(null)
  const [websiteId, setWebsiteId] = useState('')
  const [field, setField] = useState<DraftField>('meta_title')
  const [pageUrl, setPageUrl] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [draft, setDraft] = useState<FixDraft | null>(null)
  const attempt = useRef<{ key: string; signature: string } | null>(null)

  useEffect(() => {
    let active = true
    void listWebsites(accessToken, organization.organization_id)
      .then((rows) => {
        if (!active) return
        const verified = rows.filter((site) => site.verification_status === 'verified')
        setWebsites(verified)
        setWebsiteId((current) => current || verified[0]?.website_id || '')
      })
      .catch((cause: unknown) => {
        if (active) setLoadError(cause instanceof Error ? cause.message : 'Could not load websites.')
      })
    return () => { active = false }
  }, [accessToken, organization.organization_id])

  const selected = websites.find((site) => site.website_id === websiteId)
  const hint = DRAFT_FIELDS.find((item) => item.value === field)?.hint

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (!selected || busy) return
    let target = pageUrl.trim()
    if (!target) target = `${selected.origin}/`
    else if (target.startsWith('/')) target = `${selected.origin}${target}`
    else if (!/^https?:\/\//i.test(target)) target = `https://${target}`
    // A retry of the identical request reuses its key; a changed request starts a new run.
    const signature = `${websiteId}|${field}|${target}`
    if (attempt.current?.signature !== signature) {
      attempt.current = { key: crypto.randomUUID(), signature }
    }
    setBusy(true)
    setError(null)
    setDraft(null)
    try {
      const result = await requestFixDraft(
        accessToken, organization.organization_id, websiteId,
        { field, target_url: target }, attempt.current.key,
      )
      setDraft(result)
      attempt.current = null
      onDrafted()
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Drafting failed. Please try again.')
      // The server refuses to replay a used key, so a retry must be a fresh run.
      attempt.current = null
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="ai-draft" aria-labelledby="ai-draft-title">
      <div className="ai-draft__head">
        <span className="ai-draft__badge">AI agent</span>
        <h3 id="ai-draft-title">Draft a fix with AI</h3>
      </div>
      <p className="ai-draft__lead">
        The agent reads the live page, writes one replacement, and adds it to the inbox below.
        Nothing changes on your site until you approve it, and Reckon verifies the result afterwards.
      </p>
      {loadError && <p className="workspace-setup__error" role="alert">{loadError}</p>}
      {!loadError && websites.length === 0 && (
        <p className="ai-draft__empty">Verify a website first to let the agent draft fixes for it.</p>
      )}
      {websites.length > 0 && (
        <form className="ai-draft__form" onSubmit={(event) => void submit(event)}>
          <label htmlFor="ai-draft-site">Website</label>
          <select id="ai-draft-site" value={websiteId} disabled={busy}
            onChange={(event) => setWebsiteId(event.target.value)}>
            {websites.map((site) => (
              <option key={site.website_id} value={site.website_id}>{site.origin}</option>
            ))}
          </select>
          <label htmlFor="ai-draft-field">What to improve</label>
          <select id="ai-draft-field" value={field} disabled={busy}
            onChange={(event) => setField(event.target.value as DraftField)}>
            {DRAFT_FIELDS.map((item) => (
              <option key={item.value} value={item.value}>{item.label}</option>
            ))}
          </select>
          <small>{hint}</small>
          <label htmlFor="ai-draft-url">Page (optional, defaults to the homepage)</label>
          <input id="ai-draft-url" value={pageUrl} disabled={busy} placeholder="/pricing"
            onChange={(event) => setPageUrl(event.target.value)} />
          <button className="button button--primary" type="submit" disabled={busy}>
            {busy ? 'Reading the page and drafting…' : 'Draft with AI'}
          </button>
        </form>
      )}
      <div aria-live="polite">
        {error && <p className="workspace-setup__error" role="alert">{error}</p>}
        {draft && (
          <div className="ai-draft__result">
            <p><strong>Draft added to the inbox for approval.</strong></p>
            <dl>
              <div><dt>Page</dt><dd>{draft.target_url}</dd></div>
              <div><dt>Current</dt><dd>{draft.before_value || '— (not set)'}</dd></div>
              <div><dt>Proposed</dt><dd className="ai-draft__proposed">{draft.proposed_value}</dd></div>
              {draft.rationale && <div><dt>Why</dt><dd>{draft.rationale}</dd></div>}
            </dl>
          </div>
        )}
      </div>
    </section>
  )
}
