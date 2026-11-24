export type DraftField = 'meta_title' | 'meta_description' | 'heading'

export const DRAFT_FIELDS: { value: DraftField; label: string; hint: string }[] = [
  { value: 'meta_title', label: 'Page title', hint: '15–65 characters shown as the search result headline.' },
  { value: 'meta_description', label: 'Meta description', hint: '70–165 characters shown under the headline.' },
  { value: 'heading', label: 'Main heading (H1)', hint: '8–80 characters describing the page topic.' },
]

export type FixDraft = {
  proposal_id: string
  status: 'proposed'
  field: DraftField
  target_url: string
  before_value: string
  proposed_value: string
  rationale: string
  risk: 'low'
  expires_at: string
}

export class FixDraftError extends Error {
  readonly status: number
  constructor(message: string, status: number) {
    super(message)
    this.name = 'FixDraftError'
    this.status = status
  }
}

const FRIENDLY: Record<number, string> = {
  403: 'Only owners and admins can ask the AI agent to draft fixes.',
  404: 'That website was not found in this workspace.',
  409: 'Save your AI settings, verify the website, and check robots.txt allows Reckon to read the page.',
  422: 'Enter a page address on the selected website.',
  429: 'The organization has reached its daily AI limit.',
  502: 'The AI draft did not pass Reckon’s safety checks. Please try again.',
  503: 'The page could not be fetched right now. Please try again.',
  504: 'The AI agent took too long. Please try again.',
}

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null

export function parseFixDraft(value: unknown): FixDraft {
  if (
    !isRecord(value) ||
    typeof value.proposal_id !== 'string' ||
    value.status !== 'proposed' ||
    !['meta_title', 'meta_description', 'heading'].includes(String(value.field)) ||
    typeof value.target_url !== 'string' ||
    typeof value.before_value !== 'string' ||
    typeof value.proposed_value !== 'string' ||
    typeof value.rationale !== 'string' ||
    typeof value.expires_at !== 'string'
  ) {
    throw new FixDraftError('The API returned an invalid draft.', 502)
  }
  return {
    proposal_id: value.proposal_id,
    status: 'proposed',
    field: value.field as DraftField,
    target_url: value.target_url,
    before_value: value.before_value,
    proposed_value: value.proposed_value,
    rationale: value.rationale,
    risk: 'low',
    expires_at: value.expires_at,
  }
}

export async function requestFixDraft(
  token: string,
  organizationId: string,
  websiteId: string,
  request: { field: DraftField; target_url: string },
  idempotencyKey: string,
  fetcher: typeof fetch = fetch,
): Promise<FixDraft> {
  let response: Response
  try {
    response = await fetcher(
      `/api/v1/organizations/${encodeURIComponent(organizationId)}/websites/${encodeURIComponent(websiteId)}/fix-drafts`,
      {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${token}`,
          'Content-Type': 'application/json',
          'Idempotency-Key': idempotencyKey,
        },
        body: JSON.stringify(request),
        cache: 'no-store',
      },
    )
  } catch {
    throw new FixDraftError('The API could not be reached. Please try again.', 0)
  }
  if (!response.ok) {
    let detail: string | null = null
    try {
      const body: unknown = await response.json()
      // Server messages are deliberate, non-leaky text for these statuses.
      if (isRecord(body) && typeof body.detail === 'string' && [409, 422, 429, 502, 503].includes(response.status)) {
        detail = body.detail
      }
    } catch {
      // fall back to friendly text
    }
    throw new FixDraftError(
      detail ?? FRIENDLY[response.status] ?? `Drafting failed (HTTP ${response.status}).`,
      response.status,
    )
  }
  return parseFixDraft(await response.json())
}
