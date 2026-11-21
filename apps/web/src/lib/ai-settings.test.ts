import { describe, expect, it, vi } from 'vitest'
import { deleteAISettings, getAISettings, listAIUsage, reconcileAIUsage, saveAISettings, testAISettings } from './ai-settings'

describe('AI settings API', () => {
  it('saves the selected provider without exposing the key in the response', async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(new Response(JSON.stringify({
      configured: true, provider: 'openai', model: 'test-model', endpoint_url: 'https://proxy.example.com/v1', encryption_available: true,
    }), { status: 200 }))
    const result = await saveAISettings('session-token', 'org-id', 'openai', 'test-model', 'fake-key', 'https://proxy.example.com/v1', fetcher)
    expect(result.model).toBe('test-model')
    expect(JSON.stringify(result)).not.toContain('fake-key')
    expect(fetcher).toHaveBeenCalledWith(
      '/api/v1/organizations/org-id/ai-settings',
      expect.objectContaining({
        method: 'PUT',
        cache: 'no-store',
        body: JSON.stringify({ provider: 'openai', model: 'test-model', api_key: 'fake-key', endpoint_url: 'https://proxy.example.com/v1' }),
      }),
    )
  })

  it('rejects responses containing unexpected credential fields', async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(new Response(JSON.stringify({
      configured: true, provider: 'anthropic', model: 'test', endpoint_url: 'https://api.anthropic.com/v1', encryption_available: true,
      api_key: 'fake-key',
    }), { status: 200 }))
    await expect(getAISettings('token', 'org', fetcher)).rejects.toThrow('invalid AI settings')
  })

  it('reports server failures without reflecting their response body', async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(new Response('fake-key', { status: 422 }))
    await expect(saveAISettings('token', 'org', 'anthropic', 'test', 'fake-key', 'https://api.anthropic.com/v1', fetcher))
      .rejects.toThrow('Check the provider')
    const remove = vi.fn<typeof fetch>().mockResolvedValue(new Response(null, { status: 204 }))
    await expect(deleteAISettings('token', 'org', remove)).resolves.toBeUndefined()
  })

  it('rejects a configured response without an endpoint', async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(new Response(JSON.stringify({
      configured: true, provider: 'openai', model: 'test', endpoint_url: null, encryption_available: true,
    })))
    await expect(getAISettings('token', 'org', fetcher)).rejects.toThrow('invalid AI settings')
  })

  it('tests saved settings and rejects unverified responses without exposing server errors', async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(new Response(JSON.stringify({
      verified: true, provider: 'openai', model: 'test', input_tokens: 10, output_tokens: 2,
    }))).mockResolvedValueOnce(new Response('secret provider error', { status: 502 }))
    await expect(testAISettings('token', 'org', 'test-key-1', fetcher)).resolves.toEqual({
      provider: 'openai', model: 'test', input_tokens: 10, output_tokens: 2,
    })
    expect(fetcher).toHaveBeenCalledWith('/api/v1/organizations/org/ai-settings/test', expect.objectContaining({
      method: 'POST', headers: { Authorization: 'Bearer token', 'Idempotency-Key': 'test-key-1' },
    }))
    await expect(testAISettings('token', 'org', 'test-key-2', fetcher)).rejects.toThrow('could not be verified')
  })

  it('lists and reconciles tenant AI usage only with an independent reference', async () => {
    const reservationId = 'c03e775d-cdd9-493e-a81e-6da16cb1a194'
    const row = {
      reservation_id: reservationId,
      task_id: 'bca7dcf3-908e-4dcf-a985-5cc68f2355ea',
      request_id: 'a43db4b4-0e3a-4b83-a1f8-1b7d4c01a1b1',
      status: 'reserved',
      provider: 'openai',
      model: 'test-model',
      max_input_tokens: 4096,
      max_output_tokens: 512,
      input_tokens: null,
      output_tokens: null,
      started_at: '2026-01-01T10:00:00Z',
      settled_at: null,
    }
    const fetcher = vi.fn<typeof fetch>()
      .mockResolvedValueOnce(new Response(JSON.stringify([row]), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ ...row, status: 'settled', input_tokens: 20, output_tokens: 10, settled_at: '2026-01-01T10:00:01Z' }), { status: 200 }))
    await expect(listAIUsage('token', 'org', fetcher)).resolves.toEqual([row])
    await expect(reconcileAIUsage('token', 'org', reservationId, 20, 10, 'provider-verification-result-1', fetcher)).resolves.toMatchObject({
      status: 'settled', input_tokens: 20, output_tokens: 10,
    })
    await expect(reconcileAIUsage('token', 'org', reservationId, 20, 10, '', fetcher)).rejects.toThrow('Invalid AI usage reconciliation')
  })
})
