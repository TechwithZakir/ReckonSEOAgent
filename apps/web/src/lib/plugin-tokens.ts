export type PluginToken = {
  token_id: string
  label: string
  scopes: string[]
  created_at: string
  expires_at: string
  revoked_at: string | null
  last_used_at: string | null
}

export type IssuedPluginToken = PluginToken & { token: string }

const UUID = /^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$/i

function endpoint(organizationId: string): string {
  return `/api/v1/organizations/${encodeURIComponent(organizationId)}/plugin-tokens`
}

function nullableString(value: unknown): boolean {
  return value === null || typeof value === 'string'
}

function isPluginToken(value: unknown): value is PluginToken {
  if (!value || typeof value !== 'object') return false
  const row = value as Record<string, unknown>
  return (
    typeof row.token_id === 'string' &&
    UUID.test(row.token_id) &&
    typeof row.label === 'string' &&
    Array.isArray(row.scopes) &&
    row.scopes.every((scope) => typeof scope === 'string') &&
    typeof row.created_at === 'string' &&
    typeof row.expires_at === 'string' &&
    nullableString(row.revoked_at) &&
    nullableString(row.last_used_at)
  )
}

async function read(response: Response, action: string): Promise<unknown> {
  if (!response.ok) {
    throw new Error(
      response.status === 403
        ? 'Only organization owners and admins can manage plugin tokens.'
        : response.status === 422
          ? 'Check the label, lifetime and the limit of 10 active tokens.'
          : `${action} failed (HTTP ${response.status}).`,
    )
  }
  try {
    return (await response.json()) as unknown
  } catch {
    throw new Error(`The API returned an invalid ${action.toLowerCase()} response.`)
  }
}

export async function listPluginTokens(
  token: string,
  organizationId: string,
  fetcher: typeof fetch = fetch,
): Promise<PluginToken[]> {
  const response = await fetcher(endpoint(organizationId), {
    headers: { Authorization: `Bearer ${token}` },
    cache: 'no-store',
  })
  const value = await read(response, 'Loading plugin tokens')
  if (!Array.isArray(value) || !value.every(isPluginToken)) {
    throw new Error('The API returned invalid plugin tokens.')
  }
  return value
}

export type PluginScopes = { allowed: string[]; default: string[] }

export async function listPluginScopes(
  token: string,
  organizationId: string,
  fetcher: typeof fetch = fetch,
): Promise<PluginScopes> {
  const response = await fetcher(`${endpoint(organizationId)}/scopes`, {
    headers: { Authorization: `Bearer ${token}` },
    cache: 'no-store',
  })
  const value = (await read(response, 'Loading plugin scopes')) as Partial<PluginScopes> | null
  const strings = (list: unknown): list is string[] =>
    Array.isArray(list) && list.every((item) => typeof item === 'string')
  if (!value || !strings(value.allowed) || !strings(value.default)) {
    throw new Error('The API returned invalid plugin scopes.')
  }
  return { allowed: value.allowed, default: value.default }
}

export async function issuePluginToken(
  token: string,
  organizationId: string,
  payload: { label: string; lifetime_days: number; scopes?: string[] },
  fetcher: typeof fetch = fetch,
): Promise<IssuedPluginToken> {
  const response = await fetcher(endpoint(organizationId), {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
    cache: 'no-store',
  })
  const value = await read(response, 'Creating plugin token')
  const secret = (value as { token?: unknown } | null)?.token
  if (!isPluginToken(value) || typeof secret !== 'string' || !secret.startsWith('rkpt_')) {
    throw new Error('The API returned an invalid plugin token.')
  }
  return { ...value, token: secret }
}

export async function revokePluginToken(
  token: string,
  organizationId: string,
  tokenId: string,
  fetcher: typeof fetch = fetch,
): Promise<PluginToken> {
  const response = await fetcher(`${endpoint(organizationId)}/${encodeURIComponent(tokenId)}`, {
    method: 'DELETE',
    headers: { Authorization: `Bearer ${token}` },
    cache: 'no-store',
  })
  const value = await read(response, 'Revoking plugin token')
  if (!isPluginToken(value)) throw new Error('The API returned an invalid plugin token.')
  return value
}

export function tokenState(row: PluginToken, now: Date = new Date()): 'active' | 'revoked' | 'expired' {
  if (row.revoked_at !== null) return 'revoked'
  return new Date(row.expires_at) <= now ? 'expired' : 'active'
}
