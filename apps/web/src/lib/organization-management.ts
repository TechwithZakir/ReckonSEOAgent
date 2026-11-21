import { OrganizationApiError } from './organizations'
import type { OrganizationContext } from './organizations'

type Role = OrganizationContext['role']
export type ProposalInput = {
  action: 'invite' | 'role_change'
  role: Role
  reason: string
  email?: string
  user_id?: string
}
export type Proposal = ProposalInput & {
  id: string
  approval_hash: string
  expires_at: string
  approved: boolean
}
export type Invitation = {
  invitation_id: string
  organization_id: string
  organization_name: string
  role: Role
  expires_at: string
}
export type Approval = {
  approved: boolean
  invitation_id: string | null
  notification_status: 'not_applicable' | 'unconfirmed' | 'smtp_accepted'
}

const isRole = (value: unknown): value is Role =>
  typeof value === 'string' && ['owner', 'admin', 'editor', 'viewer'].includes(value)
const isRecord = (value: unknown): value is Record<string, unknown> =>
  value !== null && typeof value === 'object'
const isUuid = (value: unknown): value is string =>
  typeof value === 'string' && /^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$/i.test(value)

async function request(
  token: string, url: string, method: 'GET' | 'POST', body?: object, key?: string,
): Promise<unknown> {
  const response = await fetch(url, {
    method,
    headers: {
      Authorization: `Bearer ${token}`,
      ...(body ? { 'Content-Type': 'application/json' } : {}),
      ...(key ? { 'Idempotency-Key': key } : {}),
    },
    ...(body ? { body: JSON.stringify(body) } : {}),
    cache: 'no-store',
  })
  if (!response.ok) {
    let message = `The request failed (HTTP ${response.status}).`
    if (response.status === 409 || response.status === 503) {
      const error: unknown = await response.json().catch(() => null)
      if (isRecord(error) && typeof error.detail === 'string') message = error.detail
    }
    throw new OrganizationApiError(message, response.status)
  }
  return response.json()
}

export async function proposeChange(token: string, orgId: string, input: ProposalInput, key: string): Promise<Proposal> {
  const data = await request(token, `/api/v1/organizations/${encodeURIComponent(orgId)}/changes`, 'POST', input, key)
  if (!isRecord(data) || !isUuid(data.id) || !isRole(data.role) ||
      (data.action !== 'invite' && data.action !== 'role_change') ||
      typeof data.reason !== 'string' || typeof data.expires_at !== 'string' ||
      typeof data.approved !== 'boolean' || typeof data.approval_hash !== 'string' ||
      !/^[a-f0-9]{64}$/.test(data.approval_hash) ||
      !(data.user_id === null || isUuid(data.user_id)) ||
      !(data.email === null || typeof data.email === 'string')) {
    throw new Error('The API returned an invalid proposal.')
  }
  return {
    id: data.id, action: data.action, role: data.role, reason: data.reason,
    ...(typeof data.email === 'string' ? { email: data.email } : {}),
    ...(typeof data.user_id === 'string' ? { user_id: data.user_id } : {}),
    approval_hash: data.approval_hash, expires_at: data.expires_at, approved: data.approved,
  }
}

export async function approveChange(token: string, orgId: string, proposal: Proposal): Promise<Approval> {
  const data = await request(token,
    `/api/v1/organizations/${encodeURIComponent(orgId)}/changes/${encodeURIComponent(proposal.id)}/approve`,
    'POST', { approval_hash: proposal.approval_hash })
  if (!isRecord(data) || data.approved !== true ||
      !(data.invitation_id === null || isUuid(data.invitation_id)) ||
      (data.notification_status !== 'not_applicable' && data.notification_status !== 'unconfirmed' &&
       data.notification_status !== 'smtp_accepted')) {
    throw new Error('The API returned an invalid approval response.')
  }
  return { approved: true, invitation_id: data.invitation_id, notification_status: data.notification_status }
}

export async function listInvitations(token: string): Promise<Invitation[]> {
  const data = await request(token, '/api/v1/invitations', 'GET')
  if (!Array.isArray(data) || !data.every((item: unknown) =>
    isRecord(item) && isUuid(item.invitation_id) && isUuid(item.organization_id) &&
    typeof item.organization_name === 'string' && isRole(item.role) && typeof item.expires_at === 'string')) {
    throw new Error('The API returned an invalid invitation list.')
  }
  return data
}

export async function acceptInvitation(token: string, id: string): Promise<OrganizationContext> {
  const data = await request(token, `/api/v1/invitations/${encodeURIComponent(id)}/accept`, 'POST')
  if (!isRecord(data) || !isUuid(data.organization_id) || !isRole(data.role)) {
    throw new Error('The API returned an invalid invitation response.')
  }
  return { organization_id: data.organization_id, role: data.role }
}
