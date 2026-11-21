import { describe, expect, it, vi } from 'vitest'
import {
  createOrganization,
  getOrganizationContext,
  listOrganizationMembers,
  listOrganizations,
  OrganizationApiError,
  renameOrganization,
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

  it('updates an organization profile with the typed manager response', async () => {
    const id = 'bca7dcf3-908e-4dcf-a985-5cc68f2355ea'
    const fetcher = vi.fn<typeof fetch>(async () =>
      new Response(JSON.stringify({
        organization_id: id,
        name: 'Renamed organization',
        role: 'admin',
      }), { status: 200 }),
    )
    await expect(
      renameOrganization('token', id, 'Renamed organization', fetcher),
    ).resolves.toEqual({
      organization_id: id,
      name: 'Renamed organization',
      role: 'admin',
    })
    expect(fetcher).toHaveBeenCalledWith(
      `/api/v1/organizations/${id}/profile`,
      expect.objectContaining({
        method: 'PATCH',
        headers: expect.objectContaining({ Authorization: 'Bearer token' }),
        body: JSON.stringify({ name: 'Renamed organization' }),
      }),
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

  it('loads a typed organization page and sends the continuation cursor', async () => {
    const id = 'bca7dcf3-908e-4dcf-a985-5cc68f2355ea'
    const fetcher = vi.fn<typeof fetch>(async () =>
      new Response(JSON.stringify({
        items: [{ organization_id: id, name: 'Example org', role: 'owner' }],
        next_cursor: null,
      }), { status: 200 }),
    )
    await expect(listOrganizations('token', id, fetcher)).resolves.toEqual({
      items: [{ organization_id: id, name: 'Example org', role: 'owner' }],
      next_cursor: null,
    })
    expect(fetcher).toHaveBeenCalledWith(
      `/api/v1/organizations?after=${id}`,
      { headers: { Authorization: 'Bearer token' }, cache: 'no-store' },
    )
  })

  it('rejects invalid organization pages rather than presenting them as empty', async () => {
    const fetcher: typeof fetch = async () =>
      new Response(JSON.stringify({ items: [], next_cursor: 'not-a-uuid' }), { status: 200 })
    await expect(listOrganizations('token', null, fetcher))
      .rejects.toThrow('invalid organization list')
  })

  it('loads a tenant member page and rejects malformed member roles', async () => {
    const id = 'bca7dcf3-908e-4dcf-a985-5cc68f2355ea'
    const fetcher = vi.fn<typeof fetch>()
      .mockResolvedValueOnce(new Response(JSON.stringify({
        items: [{ user_id: id, email: null, role: 'owner' }], next_cursor: null,
      })))
      .mockResolvedValueOnce(new Response(JSON.stringify({
        items: [{ user_id: id, email: null, role: 'superuser' }], next_cursor: null,
      })))
    await expect(listOrganizationMembers('token', id, null, fetcher)).resolves.toEqual({
      items: [{ user_id: id, email: null, role: 'owner' }], next_cursor: null,
    })
    expect(fetcher).toHaveBeenCalledWith(
      `/api/v1/organizations/${id}/members`,
      { headers: { Authorization: 'Bearer token' }, cache: 'no-store' },
    )
    await expect(listOrganizationMembers('token', id, null, fetcher)).rejects.toThrow('invalid member list')
  })
})
