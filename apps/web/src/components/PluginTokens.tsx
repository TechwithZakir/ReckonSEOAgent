import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { issuePluginToken, listPluginScopes, listPluginTokens, revokePluginToken, tokenState } from '../lib/plugin-tokens'
import type { PluginScopes, PluginToken } from '../lib/plugin-tokens'
import type { OrganizationContext } from '../lib/organizations'

export function PluginTokens({
  accessToken,
  organization,
}: {
  accessToken: string
  organization: OrganizationContext
}) {
  const manager = organization.role === 'owner' || organization.role === 'admin'
  const [tokens, setTokens] = useState<PluginToken[]>([])
  const [label, setLabel] = useState('')
  const [days, setDays] = useState(30)
  const [catalogue, setCatalogue] = useState<PluginScopes | null>(null)
  const [chosen, setChosen] = useState<string[]>([])
  const [issued, setIssued] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!manager) return undefined
    let active = true
    void listPluginScopes(accessToken, organization.organization_id)
      .then((scopes) => {
        if (!active) return
        setCatalogue(scopes)
        setChosen(scopes.default)
      })
      .catch(() => undefined)
    void listPluginTokens(accessToken, organization.organization_id)
      .then((rows) => { if (active) setTokens(rows) })
      .catch((cause: unknown) => {
        if (active) setError(cause instanceof Error ? cause.message : 'Could not load plugin tokens.')
      })
    return () => { active = false }
  }, [accessToken, organization.organization_id, manager])

  if (!manager) return null

  const create = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const created = await issuePluginToken(accessToken, organization.organization_id, {
        label,
        lifetime_days: days,
        ...(catalogue ? { scopes: chosen } : {}),
      })
      setIssued(created.token)
      setLabel('')
      setTokens(await listPluginTokens(accessToken, organization.organization_id))
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not create the plugin token.')
    } finally {
      setBusy(false)
    }
  }

  const revoke = async (row: PluginToken) => {
    setBusy(true)
    setError(null)
    try {
      await revokePluginToken(accessToken, organization.organization_id, row.token_id)
      setTokens(await listPluginTokens(accessToken, organization.organization_id))
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not revoke the plugin token.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="workspace-card">
      <div className="workspace-card__content">
        <h2>Claude plugin tokens</h2>
        <p>
          A token lets the Claude plugin act in this organization only, for a fixed set of tools,
          until it expires or you revoke it. Treat it like a password.
        </p>
        {error && <p className="workspace-setup__error" role="alert">{error}</p>}
        {issued && (
          <div role="status">
            <p>Copy this token now. It is shown only once.</p>
            <code>{issued}</code>
            <button className="button button--secondary" type="button" onClick={() => setIssued(null)}>
              I have copied it
            </button>
          </div>
        )}
        <form className="workspace-form" onSubmit={(event) => void create(event)}>
          <label htmlFor="plugin-token-label">Label</label>
          <input id="plugin-token-label" required maxLength={80} value={label} disabled={busy} onChange={(event) => setLabel(event.target.value)} />
          <label htmlFor="plugin-token-days">Lifetime (days, 1-90)</label>
          <input id="plugin-token-days" type="number" min={1} max={90} required value={days} disabled={busy} onChange={(event) => setDays(Number(event.target.value))} />
          {catalogue && (
            <fieldset>
              <legend>Tools this token may call</legend>
              {catalogue.allowed.map((scope) => (
                <label key={scope}>
                  <input
                    type="checkbox"
                    checked={chosen.includes(scope)}
                    disabled={busy}
                    onChange={(event) =>
                      setChosen((current) =>
                        event.target.checked ? [...current, scope] : current.filter((item) => item !== scope),
                      )
                    }
                  />
                  {scope}
                </label>
              ))}
            </fieldset>
          )}
          <button className="button button--primary" type="submit" disabled={busy || (catalogue !== null && chosen.length === 0)}>Create token</button>
        </form>
        {tokens.length === 0 && <p>No plugin tokens have been created.</p>}
        {tokens.map((row) => {
          const state = tokenState(row)
          return (
            <article className="workspace-card" key={row.token_id}>
              <div className="workspace-card__content">
                <span className={`status-label status-label--${state === 'active' ? 'healthy' : 'muted'}`}>{state}</span>
                <h3>{row.label}</h3>
                <p>Expires {new Date(row.expires_at).toLocaleDateString()} · {row.last_used_at ? `last used ${new Date(row.last_used_at).toLocaleString()}` : 'never used'}</p>
                <p>Tools: {row.scopes.join(', ')}</p>
                {state === 'active' && (
                  <button className="button button--secondary" type="button" disabled={busy} onClick={() => void revoke(row)}>Revoke</button>
                )}
              </div>
            </article>
          )
        })}
      </div>
    </section>
  )
}
