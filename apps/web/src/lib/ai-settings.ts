export type ModelProvider = 'openai' | 'anthropic'

export const DEFAULT_MODEL_ENDPOINTS: Record<ModelProvider, string> = {
  openai: 'https://api.openai.com/v1',
  anthropic: 'https://api.anthropic.com/v1',
}

export type AISettings = {
  configured: boolean
  provider: ModelProvider | null
  model: string | null
  endpoint_url: string | null
  encryption_available: boolean
}

export type AIUsageReservation = {
  reservation_id: string
  task_id: string
  request_id: string
  status: 'reserved' | 'settled'
  provider: string
  model: string
  max_input_tokens: number
  max_output_tokens: number
  input_tokens: number | null
  output_tokens: number | null
  started_at: string
  settled_at: string | null
}

function isAISettings(value: unknown): value is AISettings {
  if (!value || typeof value !== 'object') return false
  const data = value as Record<string, unknown>
  return (
    Object.keys(data).every((key) =>
      ['configured', 'provider', 'model', 'endpoint_url', 'encryption_available'].includes(key),
    ) &&
    typeof data.encryption_available === 'boolean' &&
    ((data.configured === false && data.provider === null && data.model === null && data.endpoint_url === null) ||
      (data.configured === true &&
        (data.provider === 'openai' || data.provider === 'anthropic') &&
        typeof data.model === 'string' &&
        data.model.length > 0 &&
        typeof data.endpoint_url === 'string' && data.endpoint_url.length > 0))
  )
}

async function readSettings(response: Response): Promise<AISettings> {
  if (!response.ok) {
    throw new Error(
      response.status === 403
        ? 'Only organization owners and admins can manage AI settings.'
        : response.status === 409
          ? 'Enter an API key for the selected provider.'
          : response.status === 422
            ? 'Check the provider, model ID, endpoint URL, and API key.'
            : response.status === 503
              ? 'Credential encryption is unavailable or the stored key cannot be decrypted.'
              : `AI settings could not be saved or loaded (HTTP ${response.status}).`,
    )
  }
  const data: unknown = await response.json()
  if (!isAISettings(data)) throw new Error('The API returned invalid AI settings.')
  return data
}

function settingsUrl(organizationId: string): string {
  return `/api/v1/organizations/${encodeURIComponent(organizationId)}/ai-settings`
}

export async function getAISettings(
  token: string, organizationId: string, fetcher: typeof fetch = fetch,
): Promise<AISettings> {
  return readSettings(await fetcher(settingsUrl(organizationId), {
    headers: { Authorization: `Bearer ${token}` },
    cache: 'no-store',
  }))
}

export async function saveAISettings(
  token: string, organizationId: string, provider: ModelProvider, model: string,
  apiKey: string | null, endpointUrl: string, fetcher: typeof fetch = fetch,
): Promise<AISettings> {
  return readSettings(await fetcher(settingsUrl(organizationId), {
    method: 'PUT',
    headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({ provider, model, api_key: apiKey, endpoint_url: endpointUrl }),
    cache: 'no-store',
  }))
}

export async function deleteAISettings(
  token: string, organizationId: string, fetcher: typeof fetch = fetch,
): Promise<void> {
  const response = await fetcher(settingsUrl(organizationId), {
    method: 'DELETE', headers: { Authorization: `Bearer ${token}` }, cache: 'no-store',
  })
  if (!response.ok) {
    throw new Error(`AI settings could not be removed (HTTP ${response.status}).`)
  }
}

export async function testAISettings(
    token: string, organizationId: string, idempotencyKey: string, fetcher: typeof fetch = fetch,
  ): Promise<{ provider: ModelProvider; model: string; input_tokens: number; output_tokens: number }> {
    let response: Response
    try {
      response = await fetcher(`${settingsUrl(organizationId)}/test`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}`, 'Idempotency-Key': idempotencyKey },
        cache: 'no-store',
      })
    } catch {
      throw new Error('The test outcome is unknown; provider charges may have occurred.')
    }
    if (!response.ok) {
      const messages: Record<number, string> = {
        403: 'Only organization owners and admins can test AI settings.',
        409: 'The test was already attempted or the saved settings changed. Review settings before starting a new test.',
        429: 'The organization’s AI test token budget is exhausted.',
        502: 'The provider response could not be verified; charges may be unknown.',
        503: 'AI testing is temporarily unavailable.',
      }
      throw new Error(messages[response.status] ?? `AI testing failed (HTTP ${response.status}).`)
    }
    const data: unknown = await response.json()
    if (!data || typeof data !== 'object') throw new Error('The API returned an invalid AI test response.')
    const result = data as Record<string, unknown>
    if (result.verified !== true || (result.provider !== 'openai' && result.provider !== 'anthropic') ||
        typeof result.model !== 'string' || !Number.isSafeInteger(result.input_tokens) ||
        !Number.isSafeInteger(result.output_tokens) ||
        typeof result.input_tokens !== 'number' || result.input_tokens < 0 ||
        typeof result.output_tokens !== 'number' || result.output_tokens < 0 ||
        !Object.keys(result).every((key) => ['verified', 'provider', 'model', 'input_tokens', 'output_tokens'].includes(key))) {
      throw new Error('The API returned an invalid AI test response.')
    }
    return {
      provider: result.provider, model: result.model,
      input_tokens: result.input_tokens, output_tokens: result.output_tokens,
  }
}

const uuid = /^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$/i

function isAIUsageReservation(value: unknown): value is AIUsageReservation {
  if (!value || typeof value !== 'object') return false
  const row = value as Record<string, unknown>
  return ['reservation_id', 'task_id', 'request_id'].every((key) =>
    typeof row[key] === 'string' && uuid.test(row[key] as string)) &&
    (row.status === 'reserved' || row.status === 'settled') &&
    typeof row.provider === 'string' &&
    typeof row.model === 'string' &&
    Number.isSafeInteger(row.max_input_tokens) && (row.max_input_tokens as number) >= 0 &&
    Number.isSafeInteger(row.max_output_tokens) && (row.max_output_tokens as number) >= 0 &&
    (row.input_tokens === null || (Number.isSafeInteger(row.input_tokens) && (row.input_tokens as number) >= 0)) &&
    (row.output_tokens === null || (Number.isSafeInteger(row.output_tokens) && (row.output_tokens as number) >= 0)) &&
    typeof row.started_at === 'string' &&
    (row.settled_at === null || typeof row.settled_at === 'string')
}

export async function listAIUsage(
  token: string,
  organizationId: string,
  fetcher: typeof fetch = fetch,
): Promise<AIUsageReservation[]> {
  const response = await fetcher(
    `/api/v1/organizations/${encodeURIComponent(organizationId)}/ai-usage`,
    { headers: { Authorization: `Bearer ${token}` }, cache: 'no-store' },
  )
  if (!response.ok) {
    throw new Error(
      response.status === 403
        ? 'Only organization owners and admins can view AI usage.'
        : `AI usage could not be loaded (HTTP ${response.status}).`,
    )
  }
  const data: unknown = await response.json()
  if (!Array.isArray(data) || !data.every(isAIUsageReservation)) {
    throw new Error('The API returned invalid AI usage.')
  }
  return data
}

export async function reconcileAIUsage(
  token: string,
  organizationId: string,
  reservationId: string,
  inputTokens: number,
  outputTokens: number,
  verificationReference: string,
  fetcher: typeof fetch = fetch,
): Promise<AIUsageReservation> {
  if (!uuid.test(reservationId) ||
      !Number.isSafeInteger(inputTokens) || inputTokens < 0 ||
      !Number.isSafeInteger(outputTokens) || outputTokens < 0 ||
      !verificationReference.trim() || verificationReference.trim().length > 256) {
    throw new Error('Invalid AI usage reconciliation.')
  }
  const response = await fetcher(
    `/api/v1/organizations/${encodeURIComponent(organizationId)}/ai-usage/${encodeURIComponent(reservationId)}/reconcile`,
    {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({
        input_tokens: inputTokens,
        output_tokens: outputTokens,
        verification_reference: verificationReference.trim(),
      }),
      cache: 'no-store',
    },
  )
  if (!response.ok) {
    throw new Error(
      response.status === 409
        ? 'This reservation is not unresolved unknown usage.'
        : response.status === 404
          ? 'The AI usage reservation was not found.'
          : `AI usage could not be reconciled (HTTP ${response.status}).`,
    )
  }
  const data: unknown = await response.json()
  if (!isAIUsageReservation(data)) {
    throw new Error('The API returned invalid reconciled AI usage.')
  }
  return data
}
