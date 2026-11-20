export type Website = {
  website_id: string
  origin: string
  verification_status: 'pending' | 'verified'
  dns_txt_name: string
  dns_txt_value: string | null
}

export class WebsiteApiError extends Error {
  readonly status: number

  constructor(message: string, status: number) {
    super(message)
    this.name = 'WebsiteApiError'
    this.status = status
  }
}

function isWebsite(value: unknown): value is Website {
  if (!value || typeof value !== 'object') {
    return false
  }

  const website = value as Record<string, unknown>
  return (
    typeof website.website_id === 'string' &&
    /^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$/i.test(
      website.website_id,
    ) &&
    typeof website.origin === 'string' &&
    (website.verification_status === 'pending' ||
      website.verification_status === 'verified') &&
    typeof website.dns_txt_name === 'string' &&
    (typeof website.dns_txt_value === 'string' ||
      website.dns_txt_value === null)
  )
}

async function readWebsiteResponse(response: Response): Promise<Website> {
  if (!response.ok) {
    throw new WebsiteApiError(
      response.status === 401
        ? 'Your account is not authorized for website onboarding.'
        : response.status === 403
          ? 'Only organization owners and admins can manage websites.'
          : response.status === 409
            ? 'The website already exists or this request conflicts with an earlier attempt.'
            : response.status === 422
              ? 'Enter a public HTTP(S) website origin without a path.'
              : response.status === 503
                ? 'DNS verification is temporarily unavailable.'
                : `The API rejected the website request (HTTP ${response.status}).`,
      response.status,
    )
  }

  const payload: unknown = await response.json()
  if (!isWebsite(payload)) {
    throw new WebsiteApiError('The API returned an invalid website response.', response.status)
  }
  return payload
}

export async function listWebsites(
  accessToken: string,
  organizationId: string,
  fetcher: typeof fetch = fetch,
): Promise<Website[]> {
  const response = await fetcher(
    `/api/v1/organizations/${encodeURIComponent(organizationId)}/websites`,
    { headers: { Authorization: `Bearer ${accessToken}` } },
  )
  if (!response.ok) {
    throw new WebsiteApiError(
      `Could not load websites (HTTP ${response.status}).`,
      response.status,
    )
  }

  const payload: unknown = await response.json()
  if (!Array.isArray(payload) || !payload.every(isWebsite)) {
    throw new WebsiteApiError('The API returned an invalid website list.', response.status)
  }
  return payload
}

export async function createWebsite(
  accessToken: string,
  organizationId: string,
  url: string,
  idempotencyKey: string,
  fetcher: typeof fetch = fetch,
): Promise<Website> {
  const response = await fetcher(
    `/api/v1/organizations/${encodeURIComponent(organizationId)}/websites`,
    {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${accessToken}`,
        'Content-Type': 'application/json',
        'Idempotency-Key': idempotencyKey,
      },
      body: JSON.stringify({ url }),
    },
  )
  return readWebsiteResponse(response)
}

export async function verifyWebsite(
  accessToken: string,
  organizationId: string,
  websiteId: string,
  fetcher: typeof fetch = fetch,
): Promise<void> {
  const response = await fetcher(
    `/api/v1/organizations/${encodeURIComponent(organizationId)}/websites/${encodeURIComponent(websiteId)}/verify`,
    {
      method: 'POST',
      headers: { Authorization: `Bearer ${accessToken}` },
    },
  )
  if (!response.ok) {
    throw new WebsiteApiError(
      response.status === 409
        ? 'The DNS TXT verification record was not found yet. Check the record and retry.'
        : response.status === 503
          ? 'DNS verification is temporarily unavailable. Try again shortly.'
          : response.status === 403
            ? 'Only organization owners and admins can verify websites.'
            : `Website verification failed (HTTP ${response.status}).`,
      response.status,
    )
  }

  const payload: unknown = await response.json()
  if (
    !payload ||
    typeof payload !== 'object' ||
    !('verification_status' in payload) ||
    payload.verification_status !== 'verified' ||
    !('website_id' in payload) ||
    payload.website_id !== websiteId
  ) {
    throw new WebsiteApiError('The API did not confirm website verification.', response.status)
  }
}
