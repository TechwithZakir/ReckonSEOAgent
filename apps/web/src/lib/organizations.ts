export type OrganizationContext = {
  organization_id: string
  role: 'owner' | 'admin' | 'editor' | 'viewer'
}

export class OrganizationApiError extends Error {
  readonly status: number

  constructor(message: string, status: number) {
    super(message)
    this.name = 'OrganizationApiError'
    this.status = status
  }
}

function isOrganizationContext(value: unknown): value is OrganizationContext {
  if (!value || typeof value !== 'object') {
    return false
  }

  const context = value as Record<string, unknown>
  return (
    typeof context.organization_id === 'string' &&
    /^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$/i.test(
      context.organization_id,
    ) &&
    ['owner', 'admin', 'editor', 'viewer'].includes(String(context.role))
  )
}

async function readContext(response: Response): Promise<OrganizationContext> {
  if (!response.ok) {
    const messages: Record<number, string> = {
      401: 'This account cannot access Reckon yet. Confirm identity provisioning and the API audience.',
      404: 'The organization was not found or your account is not a member.',
      409: 'The organization request conflicted with an earlier request.',
      503: 'The API is temporarily unavailable. Try again shortly.',
    }
    throw new OrganizationApiError(
      messages[response.status] ?? `The API rejected the request (HTTP ${response.status}).`,
      response.status,
    )
  }

  const payload: unknown = await response.json()
  if (!isOrganizationContext(payload)) {
    throw new OrganizationApiError('The API returned an invalid organization response.', response.status)
  }
  return payload
}

export async function createOrganization(
  accessToken: string,
  name: string,
  idempotencyKey: string,
  fetcher: typeof fetch = fetch,
): Promise<OrganizationContext> {
  const response = await fetcher('/api/v1/organizations', {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${accessToken}`,
      'Content-Type': 'application/json',
      'Idempotency-Key': idempotencyKey,
    },
    body: JSON.stringify({ name }),
  })
  return readContext(response)
}

export async function getOrganizationContext(
  accessToken: string,
  organizationId: string,
  fetcher: typeof fetch = fetch,
): Promise<OrganizationContext> {
  const response = await fetcher(
    `/api/v1/organizations/${encodeURIComponent(organizationId)}/context`,
    {
      headers: { Authorization: `Bearer ${accessToken}` },
    },
  )
  return readContext(response)
}
