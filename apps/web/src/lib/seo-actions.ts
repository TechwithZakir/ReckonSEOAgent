export type SeoActionStatus =
  | 'proposed'
  | 'approved'
  | 'rejected'
  | 'executing'
  | 'executed'
  | 'verified'
  | 'failed'
  | 'rolled_back'

export type SeoAction = {
  proposal_id: string
  website_id: string
  action_type: string
  target_url: string
  target_version: string
  risk: 'low' | 'medium' | 'high'
  status: SeoActionStatus
  reason: string
  approval_hash: string
  before_state: Record<string, string>
  proposed_state: Record<string, string>
  executed_state: Record<string, string> | null
  verification_state: Record<string, string> | null
  rollback_state: Record<string, string> | null
  error_code: string | null
  created_at: string
  expires_at: string
  approved_at: string | null
  executed_at: string | null
  verified_at: string | null
}

class SeoActionApiError extends Error {
  readonly status: number

  constructor(message: string, status: number) {
    super(message)
    this.name = 'SeoActionApiError'
    this.status = status
  }
}

function endpoint(organizationId: string): string {
  return `/api/v1/organizations/${encodeURIComponent(organizationId)}/seo-actions`
}

function isSeoAction(value: unknown): value is SeoAction {
  if (!value || typeof value !== 'object') return false
  const row = value as Record<string, unknown>
  const uuid = /^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$/i
  const states = (state: unknown) =>
    state === null ||
    (typeof state === 'object' &&
      state !== null &&
      Object.values(state).every((item) => typeof item === 'string'))
  return (
    typeof row.proposal_id === 'string' &&
    uuid.test(row.proposal_id) &&
    typeof row.website_id === 'string' &&
    uuid.test(row.website_id) &&
    typeof row.action_type === 'string' &&
    typeof row.target_url === 'string' &&
    typeof row.target_version === 'string' &&
    ['low', 'medium', 'high'].includes(row.risk as string) &&
    ['proposed', 'approved', 'rejected', 'executing', 'executed', 'verified', 'failed', 'rolled_back'].includes(row.status as string) &&
    typeof row.reason === 'string' &&
    typeof row.approval_hash === 'string' &&
    typeof row.before_state === 'object' &&
    typeof row.proposed_state === 'object' &&
    states(row.executed_state) &&
    states(row.verification_state) &&
    states(row.rollback_state) &&
    (row.error_code === null || typeof row.error_code === 'string') &&
    typeof row.created_at === 'string' &&
    typeof row.expires_at === 'string'
  )
}

async function readResponse(response: Response, action: string): Promise<unknown> {
  if (!response.ok) {
    throw new SeoActionApiError(
      `${action} failed (HTTP ${response.status}).`,
      response.status,
    )
  }
  try {
    return await response.json() as unknown
  } catch {
    throw new SeoActionApiError(`The API returned an invalid ${action.toLowerCase()} response.`, response.status)
  }
}

export async function listSeoActions(
  token: string,
  organizationId: string,
  fetcher: typeof fetch = fetch,
): Promise<SeoAction[]> {
  const response = await fetcher(endpoint(organizationId), {
    headers: { Authorization: `Bearer ${token}` },
    cache: 'no-store',
  })
  const value = await readResponse(response, 'Loading SEO actions')
  if (!Array.isArray(value) || !value.every(isSeoAction)) {
    throw new SeoActionApiError('The API returned invalid SEO actions.', response.status)
  }
  return value
}

export async function proposeSeoAction(
  token: string,
  organizationId: string,
  idempotencyKey: string,
  payload: {
    website_id: string
    action_type: 'meta_title' | 'meta_description' | 'canonical' | 'heading' | 'schema' | 'redirect' | 'internal_link' | 'other'
    target_url: string
    target_version: string
    before_state: Record<string, string>
    proposed_state: Record<string, string>
    risk: 'low' | 'medium' | 'high'
    reason: string
  },
  fetcher: typeof fetch = fetch,
): Promise<SeoAction> {
  const response = await fetcher(endpoint(organizationId), {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json',
      'Idempotency-Key': idempotencyKey,
    },
    body: JSON.stringify(payload),
    cache: 'no-store',
  })
  const value = await readResponse(response, 'Creating SEO action')
  if (!isSeoAction(value)) {
    throw new SeoActionApiError('The API returned an invalid SEO action.', response.status)
  }
  return value
}

async function decision(
  token: string,
  organizationId: string,
  proposalId: string,
  operation: 'approve' | 'reject',
  approvalHash?: string,
  fetcher: typeof fetch = fetch,
): Promise<SeoAction> {
  const response = await fetcher(
    `${endpoint(organizationId)}/${encodeURIComponent(proposalId)}/${operation}`,
    {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${token}`,
        'Content-Type': 'application/json',
      },
      body: operation === 'approve'
        ? JSON.stringify({ approval_hash: approvalHash })
        : undefined,
      cache: 'no-store',
    },
  )
  const value = await readResponse(response, `${operation === 'approve' ? 'Approving' : 'Rejecting'} SEO action`)
  if (!isSeoAction(value)) {
    throw new SeoActionApiError('The API returned an invalid SEO action.', response.status)
  }
  return value
}

export async function approveSeoAction(
  token: string,
  organizationId: string,
  proposalId: string,
  approvalHash: string,
  fetcher: typeof fetch = fetch,
) {
  return decision(token, organizationId, proposalId, 'approve', approvalHash, fetcher)
}

export async function rejectSeoAction(
  token: string,
  organizationId: string,
  proposalId: string,
  fetcher: typeof fetch = fetch,
) {
  return decision(token, organizationId, proposalId, 'reject', undefined, fetcher)
}

export async function executeSeoAction(
  token: string,
  organizationId: string,
  proposalId: string,
  fetcher: typeof fetch = fetch,
) {
  const response = await fetcher(
    `${endpoint(organizationId)}/${encodeURIComponent(proposalId)}/execute`,
    {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
      cache: 'no-store',
    },
  )
  const value = await readResponse(response, 'Executing SEO action')
  if (!isSeoAction(value)) {
    throw new SeoActionApiError('The API returned an invalid SEO action.', response.status)
  }
  return value
}

export async function rollbackSeoAction(
  token: string,
  organizationId: string,
  proposalId: string,
  fetcher: typeof fetch = fetch,
) {
  const response = await fetcher(
    `${endpoint(organizationId)}/${encodeURIComponent(proposalId)}/rollback`,
    {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
      cache: 'no-store',
    },
  )
  const value = await readResponse(response, 'Rolling back SEO action')
  if (!isSeoAction(value)) {
    throw new SeoActionApiError('The API returned an invalid SEO action.', response.status)
  }
  return value
}
