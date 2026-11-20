import { describe, expect, it, vi } from 'vitest'
import {
  createWebsite,
  listWebsites,
  verifyWebsite,
} from './websites'

const organizationId = 'c03e775d-cdd9-493e-a81e-6da16cb1a194'
const websiteId = 'bca7dcf3-908e-4dcf-a985-5cc68f2355ea'

describe('website API client', () => {
  it('creates a website with bearer auth and an idempotency key', async () => {
    const fetcher = vi.fn<typeof fetch>(async () =>
      new Response(
        JSON.stringify({
          website_id: websiteId,
          origin: 'https://example.com',
          verification_status: 'pending',
          dns_txt_name: '_reckon-verify.example.com',
          dns_txt_value: 'reckon-seo-verification=random-token',
        }),
        { status: 201 },
      ),
    )

    await expect(
      createWebsite(
        'opaque-access-token',
        organizationId,
        'https://example.com',
        'site-create-123',
        fetcher,
      ),
    ).resolves.toMatchObject({
      website_id: websiteId,
      verification_status: 'pending',
    })
    expect(fetcher).toHaveBeenCalledWith(
      `/api/v1/organizations/${organizationId}/websites`,
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({
          Authorization: 'Bearer opaque-access-token',
          'Idempotency-Key': 'site-create-123',
        }),
        body: JSON.stringify({ url: 'https://example.com' }),
      }),
    )
  })

  it('loads website records using the authenticated organization route', async () => {
    const fetcher = vi.fn<typeof fetch>(async () =>
      new Response(
        JSON.stringify([
          {
            website_id: websiteId,
            origin: 'https://example.com',
            verification_status: 'verified',
            dns_txt_name: '_reckon-verify.example.com',
            dns_txt_value: null,
          },
        ]),
        { status: 200 },
      ),
    )

    await expect(
      listWebsites('opaque-access-token', organizationId, fetcher),
    ).resolves.toHaveLength(1)
    expect(fetcher).toHaveBeenCalledWith(
      `/api/v1/organizations/${organizationId}/websites`,
      { headers: { Authorization: 'Bearer opaque-access-token' } },
    )
  })

  it('does not report verification unless the API confirms it', async () => {
    const pending = vi.fn<typeof fetch>(async () =>
      new Response(JSON.stringify({ detail: 'not verified' }), { status: 409 }),
    )
    const verified = vi.fn<typeof fetch>(async () =>
      new Response(
        JSON.stringify({
          website_id: websiteId,
          verification_status: 'verified',
        }),
        { status: 200 },
      ),
    )

    await expect(
      verifyWebsite('opaque-access-token', organizationId, websiteId, pending),
    ).rejects.toThrow('DNS TXT verification record was not found')
    await expect(
      verifyWebsite('opaque-access-token', organizationId, websiteId, verified),
    ).resolves.toBeUndefined()
    expect(verified).toHaveBeenCalledWith(
      `/api/v1/organizations/${organizationId}/websites/${websiteId}/verify`,
      expect.objectContaining({
        method: 'POST',
        headers: { Authorization: 'Bearer opaque-access-token' },
      }),
    )
  })
})
