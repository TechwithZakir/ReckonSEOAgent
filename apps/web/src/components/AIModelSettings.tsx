import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { DEFAULT_MODEL_ENDPOINTS, deleteAISettings, getAISettings, listAIUsage, reconcileAIUsage, saveAISettings, testAISettings } from '../lib/ai-settings'
import type { AISettings, AIUsageReservation, ModelProvider } from '../lib/ai-settings'
import type { OrganizationContext } from '../lib/organizations'

export function AIModelSettings({
  accessToken,
  organization,
}: {
  accessToken: string
  organization: OrganizationContext | null
}) {
  const [settings, setSettings] = useState<AISettings | null>(null)
  const [provider, setProvider] = useState<ModelProvider>('openai')
  const [model, setModel] = useState('')
  const [endpoint, setEndpoint] = useState(DEFAULT_MODEL_ENDPOINTS.openai)
  const [apiKey, setApiKey] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const [usage, setUsage] = useState<AIUsageReservation[]>([])
  const [usageError, setUsageError] = useState<string | null>(null)
  const [verificationReference, setVerificationReference] = useState<Record<string, string>>({})
  const [inputUsage, setInputUsage] = useState<Record<string, string>>({})
  const [outputUsage, setOutputUsage] = useState<Record<string, string>>({})
  const manager = organization?.role === 'owner' || organization?.role === 'admin'
  const organizationId = organization?.organization_id

  useEffect(() => {
    if (!accessToken || !organizationId || !manager) return
    let active = true
    void getAISettings(accessToken, organizationId)
      .then((result) => {
        if (!active) return
        setSettings(result)
        if (result.provider) setProvider(result.provider)
        if (result.model) setModel(result.model)
        if (result.endpoint_url) setEndpoint(result.endpoint_url)
      })
      .catch((cause: unknown) => {
        if (active) setError(cause instanceof Error ? cause.message : 'Could not load AI settings.')
      })
    return () => { active = false }
  }, [accessToken, organizationId, manager])

  useEffect(() => {
    if (!accessToken || !organizationId || !manager) return
    let active = true
    void listAIUsage(accessToken, organizationId)
      .then((rows) => { if (active) setUsage(rows) })
      .catch((cause: unknown) => {
        if (active) setUsageError(cause instanceof Error ? cause.message : 'Could not load AI usage.')
      })
    return () => { active = false }
  }, [accessToken, organizationId, manager, message])

  const save = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!organizationId || !settings) return
    setBusy(true)
    setError(null)
    setMessage(null)
    try {
      const result = await saveAISettings(
        accessToken, organizationId, provider, model.trim(), apiKey || null, endpoint,
      )
      setSettings(result)
      setApiKey('')
      setMessage('Settings saved. The provider and model have not been tested or connected.')
    } catch (cause) {
      setApiKey('')
      setError(cause instanceof Error ? cause.message : 'Could not save AI settings.')
    } finally {
      setBusy(false)
    }
  }

  const remove = async () => {
    if (!organizationId || !settings) return
    setBusy(true)
    setError(null)
    setMessage(null)
    try {
      await deleteAISettings(accessToken, organizationId)
      setSettings({ configured: false, provider: null, model: null, endpoint_url: null, encryption_available: settings.encryption_available })
      setApiKey('')
      setModel('')
      setEndpoint(DEFAULT_MODEL_ENDPOINTS[provider])
      setMessage('AI settings and the stored key were removed.')
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not remove AI settings.')
    } finally {
      setBusy(false)
    }
  }

  const test = async () => {
    if (!organizationId || !settings?.configured) return
    setBusy(true)
    setError(null)
    setMessage(null)
    try {
      const result = await testAISettings(accessToken, organizationId, crypto.randomUUID())
      setMessage(`Test succeeded: ${result.provider} · ${result.model}. Usage: ${result.input_tokens} input and ${result.output_tokens} output tokens.`)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'AI test could not be completed.')
    } finally { setBusy(false) }
  }

  const reconcile = async (reservation: AIUsageReservation) => {
    if (!organizationId) return
    setBusy(true)
    setError(null)
    setMessage(null)
    try {
      const reference = verificationReference[reservation.reservation_id] ?? ''
      const inputTokens = Number(inputUsage[reservation.reservation_id] ?? '0')
      const outputTokens = Number(outputUsage[reservation.reservation_id] ?? '0')
      await reconcileAIUsage(
        accessToken,
        organizationId,
        reservation.reservation_id,
        inputTokens,
        outputTokens,
        reference,
      )
      setMessage('Unknown usage was reconciled only after an independent verification reference was supplied.')
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not reconcile AI usage.')
    } finally {
      setBusy(false)
    }
  }

  const unsaved = settings?.configured && (
    provider !== settings.provider || model.trim() !== settings.model ||
    endpoint !== settings.endpoint_url || apiKey.length > 0
  )

  return (
    <section aria-labelledby="ai-settings-title" className="ai-settings-card" id="ai-settings">
      <div className="section-heading">
        <div>
          <p className="section-kicker">SYSTEM SETTINGS</p>
          <h2 id="ai-settings-title">AI model</h2>
        </div>
        <span className="section-note">Organization-specific</span>
      </div>
      <p>Choose OpenAI or Anthropic and a model ID for this organization. Saving does not test the key; Test AI sends a short, metered request and may incur charges.</p>
      {!organization || !accessToken ? (
        <p>Sign in and connect an organization to manage AI settings.</p>
      ) : !manager ? (
        <p>Only organization owners and admins can manage AI settings.</p>
      ) : (
        <>
          {error && <p className="workspace-setup__error" role="alert">{error}</p>}
          {message && <p aria-live="polite">{message}</p>}
          {!settings && !error && <p>Loading AI settings…</p>}
          {settings && (
            <>
              {!settings.encryption_available && (
                <p className="workspace-setup__error" role="alert">
                  Credential encryption must be configured by the platform operator before saving.
                </p>
              )}
              {settings.configured && (
                <p>Saved: {settings.provider} · {settings.model} · {settings.endpoint_url}. The API key is never displayed.</p>
              )}
              <form className="ai-settings-form" onSubmit={(event) => void save(event)}>
                <label htmlFor="ai-provider">Provider</label>
                <select
                  id="ai-provider" value={provider} disabled={busy}
                  onChange={(event) => {
                    const selected = event.target.value
                    if (selected === 'openai' || selected === 'anthropic') {
                      setProvider(selected)
                      setEndpoint(selected === settings.provider && settings.endpoint_url
                        ? settings.endpoint_url : DEFAULT_MODEL_ENDPOINTS[selected])
                    }
                    setApiKey('')
                  }}
                >
                  <option value="openai">OpenAI</option>
                  <option value="anthropic">Anthropic</option>
                </select>
                <label htmlFor="ai-model">Model ID</label>
                <input
                  id="ai-model" value={model} onChange={(event) => setModel(event.target.value)}
                  maxLength={128} placeholder="Enter the provider's model ID" required disabled={busy}
                />
                <label htmlFor="ai-endpoint">API base URL</label>
                <input
                  id="ai-endpoint" type="url" value={endpoint} onChange={(event) => setEndpoint(event.target.value)}
                  maxLength={2048} required disabled={busy}
                />
                <p>Official defaults: OpenAI {DEFAULT_MODEL_ENDPOINTS.openai}; Anthropic {DEFAULT_MODEL_ENDPOINTS.anthropic}.</p>
                <p>Use a trusted HTTPS endpoint on port 443 without credentials or query parameters. Testing sends your API key and a short test prompt to that endpoint.</p>
                <label htmlFor="ai-key">API key</label>
                <input
                  id="ai-key" type="password" autoComplete="new-password" value={apiKey}
                  onChange={(event) => setApiKey(event.target.value)} maxLength={4096}
                  required={!settings.configured || provider !== settings.provider} disabled={busy}
                  placeholder={settings.configured && provider === settings.provider ? 'Leave blank to keep the current key' : 'Enter an API key'}
                />
                <p>Keys are encrypted on the server and are not returned to the browser. Use HTTPS outside localhost.</p>
                <div className="ai-settings-actions">
                  <button className="button button--primary" disabled={busy || !settings.encryption_available} type="submit">
                    {busy ? 'Working…' : 'Save AI settings'}
                  </button>
                  {settings.configured && (
                    <button className="button button--secondary" type="button"
                      disabled={busy || !settings.encryption_available || Boolean(unsaved)} onClick={() => void test()}>
                      Test AI
                    </button>
                  )}
                  {settings.configured && (
                    <button className="button button--secondary" disabled={busy} onClick={() => void remove()} type="button">
                      Remove settings and key
                    </button>
                  )}
                </div>
                {unsaved && <p>Save your changes before testing.</p>}
              </form>
            </>
          )}
          <h3>AI usage</h3>
          {usageError && <p className="workspace-setup__error" role="alert">{usageError}</p>}
          {usage.length === 0 && !usageError && <p>No AI usage reservations recorded.</p>}
          {usage.length > 0 && (
            <ul>
              {usage.map((reservation) => (
                <li key={reservation.reservation_id}>
                  <strong>{reservation.provider} · {reservation.model}</strong>
                  <p>Status: {reservation.status}</p>
                  <p>Maximum: {reservation.max_input_tokens} input / {reservation.max_output_tokens} output tokens</p>
                  <p>Recorded: {reservation.input_tokens ?? 'Unknown'} input / {reservation.output_tokens ?? 'Unknown'} output tokens</p>
                  {reservation.status === 'reserved' && (
                    <div className="ai-settings-form">
                      <label htmlFor={`reconcile-input-${reservation.reservation_id}`}>Verified input tokens</label>
                      <input
                        id={`reconcile-input-${reservation.reservation_id}`}
                        type="number"
                        min={0}
                        value={inputUsage[reservation.reservation_id] ?? '0'}
                        disabled={busy}
                        onChange={(event) => setInputUsage((values) => ({
                          ...values,
                          [reservation.reservation_id]: event.target.value,
                        }))}
                      />
                      <label htmlFor={`reconcile-output-${reservation.reservation_id}`}>Verified output tokens</label>
                      <input
                        id={`reconcile-output-${reservation.reservation_id}`}
                        type="number"
                        min={0}
                        value={outputUsage[reservation.reservation_id] ?? '0'}
                        disabled={busy}
                        onChange={(event) => setOutputUsage((values) => ({
                          ...values,
                          [reservation.reservation_id]: event.target.value,
                        }))}
                      />
                      <label htmlFor={`reconcile-reference-${reservation.reservation_id}`}>Independent verification reference</label>
                      <input
                        id={`reconcile-reference-${reservation.reservation_id}`}
                        minLength={8}
                        maxLength={256}
                        value={verificationReference[reservation.reservation_id] ?? ''}
                        disabled={busy}
                        onChange={(event) => setVerificationReference((values) => ({
                          ...values,
                          [reservation.reservation_id]: event.target.value,
                        }))}
                      />
                      <button
                        className="button button--secondary"
                        type="button"
                        disabled={busy || (verificationReference[reservation.reservation_id] ?? '').trim().length < 8}
                        onClick={() => void reconcile(reservation)}
                      >
                        Reconcile unknown usage
                      </button>
                    </div>
                  )}
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </section>
  )
}
