export type OrganizationContext = {
  organization_id: string
  role: 'owner' | 'admin' | 'editor' | 'viewer'
}

export type OrganizationSummary = OrganizationContext & { name: string }
export type OrganizationPage = {
  items: OrganizationSummary[]
  next_cursor: string | null
}
export type OrganizationMember = {
  user_id: string
  email: string | null
  role: OrganizationContext['role']
}
export type OrganizationMemberPage = {
  items: OrganizationMember[]
  next_cursor: string | null
}

export type AuditEvent = {
  event_id: string
  action: string
  resource_type: string
  resource_id: string
  request_id: string
  created_at: string
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

function isOrganizationSummary(value: unknown): value is OrganizationSummary {
  return (
    isOrganizationContext(value) &&
    'name' in value &&
    typeof value.name === 'string' &&
    value.name.length > 0 &&
    value.name.length <= 200
  )
}

function isOrganizationMember(value: unknown): value is OrganizationMember {
  if (!value || typeof value !== 'object') return false
  const member = value as Record<string, unknown>
  return typeof member.user_id === 'string' &&
    /^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$/i.test(member.user_id) &&
    (member.email === null || (typeof member.email === 'string' && member.email.length > 0 && member.email.length <= 320)) &&
    ['owner', 'admin', 'editor', 'viewer'].includes(String(member.role))
}

export async function listOrganizationMembers(
  accessToken: string,
  organizationId: string,
  after: string | null = null,
  fetcher: typeof fetch = fetch,
): Promise<OrganizationMemberPage> {
  const query = after ? `?after=${encodeURIComponent(after)}` : ''
  const response = await fetcher(`/api/v1/organizations/${encodeURIComponent(organizationId)}/members${query}`, {
    headers: { Authorization: `Bearer ${accessToken}` },
    cache: 'no-store',
  })
  if (!response.ok) {
    throw new OrganizationApiError(`Could not load organization members (HTTP ${response.status}).`, response.status)
  }
  const value: unknown = await response.json()
  if (!value || typeof value !== 'object' ||
      !('items' in value) || !Array.isArray(value.items) || !value.items.every(isOrganizationMember) ||
      !('next_cursor' in value) || !(value.next_cursor === null ||
        (typeof value.next_cursor === 'string' &&
          /^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$/i.test(value.next_cursor)))) {
    throw new OrganizationApiError('The API returned an invalid member list.', response.status)
  }
  return { items: value.items, next_cursor: value.next_cursor }
}

export async function listOrganizations(
  accessToken: string,
  after: string | null = null,
  fetcher: typeof fetch = fetch,
): Promise<OrganizationPage> {
  const query = after ? `?after=${encodeURIComponent(after)}` : ''
  const response = await fetcher(`/api/v1/organizations${query}`, {
    headers: { Authorization: `Bearer ${accessToken}` },
    cache: 'no-store',
  })
  if (!response.ok) {
    throw new OrganizationApiError(
      `Could not load organizations (HTTP ${response.status}).`,
      response.status,
    )
  }
  const payload: unknown = await response.json()
  if (!payload || typeof payload !== 'object') {
    throw new OrganizationApiError('The API returned an invalid organization list.', response.status)
  }
  const page = payload as Record<string, unknown>
  if (
    !Array.isArray(page.items) ||
    !page.items.every(isOrganizationSummary) ||
    !(page.next_cursor === null ||
      (typeof page.next_cursor === 'string' &&
        /^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$/i.test(page.next_cursor)))
  ) {
    throw new OrganizationApiError('The API returned an invalid organization list.', response.status)
  }
  return { items: page.items, next_cursor: page.next_cursor }
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

export async function renameOrganization(
  accessToken: string,
  organizationId: string,
  name: string,
  fetcher: typeof fetch = fetch,
): Promise<OrganizationContext & { name: string }> {
  if (!name.trim() || name.trim().length > 200) {
    throw new OrganizationApiError('The organization name must contain 1 to 200 characters.', 422)
  }
  const response = await fetcher(
    `/api/v1/organizations/${encodeURIComponent(organizationId)}/profile`,
    {
      method: 'PATCH',
      headers: {
        Authorization: `Bearer ${accessToken}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ name: name.trim() }),
    },
  )
  if (!response.ok) {
    throw new OrganizationApiError(
      `Could not update the organization profile (HTTP ${response.status}).`,
      response.status,
    )
  }
  const payload: unknown = await response.json()
  if (
    !payload ||
    typeof payload !== 'object' ||
    typeof (payload as Record<string, unknown>).name !== 'string' ||
    !isOrganizationContext(payload)
  ) {
    throw new OrganizationApiError('The API returned an invalid organization profile.', response.status)
  }
  return payload as OrganizationContext & { name: string }
}

export async function listAuditEvents(
  accessToken: string,
  organizationId: string,
  fetcher: typeof fetch = fetch,
): Promise<AuditEvent[]> {
  const response = await fetcher(
    `/api/v1/organizations/${encodeURIComponent(organizationId)}/audit-events?limit=50`,
    { headers: { Authorization: `Bearer ${accessToken}` }, cache: 'no-store' },
  )
  if (!response.ok) {
    throw new OrganizationApiError(
      `Could not load audit events (HTTP ${response.status}).`,
      response.status,
    )
  }
  const value: unknown = await response.json()
  if (!Array.isArray(value)) {
    throw new OrganizationApiError('The API returned invalid audit events.', response.status)
  }
  const uuid = /^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$/i
  for (const event of value) {
    if (
      !event ||
      typeof event !== 'object' ||
      typeof (event as Record<string, unknown>).event_id !== 'string' ||
      !uuid.test((event as Record<string, unknown>).event_id as string) ||
      typeof (event as Record<string, unknown>).action !== 'string' ||
      typeof (event as Record<string, unknown>).resource_type !== 'string' ||
      typeof (event as Record<string, unknown>).resource_id !== 'string' ||
      typeof (event as Record<string, unknown>).request_id !== 'string' ||
      typeof (event as Record<string, unknown>).created_at !== 'string'
    ) {
      throw new OrganizationApiError('The API returned invalid audit events.', response.status)
    }
  }
  return value as AuditEvent[]
}

export async function downloadAuditEvents(
  accessToken: string,
  organizationId: string,
  fetcher: typeof fetch = fetch,
): Promise<void> {
  const events = await listAuditEvents(accessToken, organizationId, fetcher)
  const rows = [
    ['event_id', 'action', 'resource_type', 'resource_id', 'request_id', 'created_at'],
    ...events.map((event) => [
      event.event_id,
      event.action,
      event.resource_type,
      event.resource_id,
      event.request_id,
      event.created_at,
    ]),
  ]
  const escape = (value: string) => `"${value.replaceAll('"', '""')}"`
  const csv = rows
    .map((row) => row.map((value) => escape(value)).join(','))
    .join('\n')
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `reckon-audit-${organizationId}.csv`
  link.click()
  URL.revokeObjectURL(url)
}
