import { describe, expect, it, vi } from 'vitest'
import {
  createOrganization,
  getOrganizationContext,
  OrganizationApiError,
} from './organizations'

describe('organization API client', () => {
  it('creates with the bearer token and idempotency key, then parses the typed context', async () => {
    const fetcher = vi.fn<typeof fetch>(async () =>
      new Response(
        JSON.stringify({
          organization_id: 'bca7dcf3-908e-4dcf-a985-5cc68f2355ea',
          role: 'owner',
        }),
        { status: 201, headers: { 'Content-Type': 'application/json' } },
      ),
    )

    await expect(
      createOrganization('opaque-access-token', 'Example org', 'request-123', fetcher),
    ).resolves.toEqual({
      organization_id: 'bca7dcf3-908e-4dcf-a985-5cc68f2355ea',
      role: 'owner',
    })
    expect(fetcher).toHaveBeenCalledWith(
      '/api/v1/organizations',
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({
          Authorization: 'Bearer opaque-access-token',
          'Idempotency-Key': 'request-123',
        }),
        body: JSON.stringify({ name: 'Example org' }),
      }),
    )
  })

  it('checks membership through the server and does not treat an unauthorized response as access', async () => {
    const fetcher = vi.fn<typeof fetch>(async () =>
      new Response(JSON.stringify({ detail: 'not available' }), { status: 404 }),
    )

    await expect(
      getOrganizationContext(
        'opaque-access-token',
        'org-id/with-path',
        fetcher,
      ),
    ).rejects.toMatchObject({
      name: 'OrganizationApiError',
      status: 404,
    } satisfies Partial<OrganizationApiError>)
    expect(fetcher).toHaveBeenCalledWith(
      '/api/v1/organizations/org-id%2Fwith-path/context',
      { headers: { Authorization: 'Bearer opaque-access-token' } },
    )
  })

  it('rejects malformed success payloads', async () => {
    const fetcher: typeof fetch = async () =>
      new Response(
        JSON.stringify({ organization_id: 'not-a-uuid', role: 'unrecognized' }),
        { status: 200 },
      )

    await expect(
      getOrganizationContext('opaque-access-token', 'org-id', fetcher),
    ).rejects.toThrow('invalid organization response')
  })

  it('accepts all server-defined organization roles', async () => {
    const fetcher: typeof fetch = async () =>
      new Response(
        JSON.stringify({
          organization_id: 'bca7dcf3-908e-4dcf-a985-5cc68f2355ea',
          role: 'viewer',
        }),
        { status: 200 },
      )

    await expect(
      getOrganizationContext('opaque-access-token', 'org-id', fetcher),
    ).resolves.toMatchObject({ role: 'viewer' })
  })
})
